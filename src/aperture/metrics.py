"""Minimal instrumentation: MetricsCollector with 6 observable indicators."""

from __future__ import annotations

from typing import Any

from aperture.core import DeltaResult, DeltaStatus, aggregate_status


class MetricsCollector:
    """Passively records :class:`DeltaResult` instances and accumulates 6 indicators.

    Pure accumulator with no side effects or external dependencies.  The
    ``snapshot()`` output is a serializable plain dict.

    Thread safety: this collector is **not thread-safe**. Construct one per thread /
    logical session; do not share a live instance across threads. To hand state across
    threads / processes, serialize with ``snapshot()`` on the source side (and rebuild
    a fresh collector from that dict on the destination side).
    """

    def __init__(self, adjust_window: int = 3) -> None:
        self._compare_call_count: int = 0
        self._drift_alert_count: int = 0

        self._chain_count: int = 0
        self._chain_mismatch_count: int = 0

        self._status_dist: dict[str, int] = {}
        self._reason_present: int = 0

        self._adjust_window: int = adjust_window
        self._adjusted_count: int = 0
        self._pending: dict[str, list[int]] = {}

    # -- public API ------------------------------------------------------------

    def record(self, result: DeltaResult) -> None:
        """Ingest a single ``DeltaResult`` and update indicators 1/2/3/5/6."""
        self._compare_call_count += 1

        # 5: status distribution
        sv = result.status.value
        self._status_dist[sv] = self._status_dist.get(sv, 0) + 1

        # 6: reason presence
        if result.reason.strip():
            self._reason_present += 1

        # 2: drift alert
        is_drift = result.status is not DeltaStatus.OK or bool(result.anchor_violations)
        if is_drift:
            self._drift_alert_count += 1

        # 3: adjusted-within-N-turns tracking
        # 按 profile 分桶（family 现统一为 self-consistency；profile 区分 proposal/stance/
        # commitment），base/scaffold 无 profile 时退回 provider_family——保持改前的 per-profile
        # 聚合维度不坍缩（Q8 字段拆分前 family 字段实承担 profile 区分器角色）。
        key = result.profile or result.provider_family
        windows = self._pending.setdefault(key, [])

        # Age existing windows; a window survives N subsequent records (drop
        # only once it would go negative) → inclusive within-N（OK 在 t+1..t+N 都算）.
        surviving: list[int] = [w - 1 for w in windows if w - 1 >= 0]

        if is_drift:
            # New alert. alert 与 recovery 互斥（is_drift 覆盖 status!=ok 或 violations），
            # 故 OK+violations 记为 alert、不当作 recovery。
            surviving.append(self._adjust_window)
            self._pending[key] = surviving
        else:
            # Clean recovery（ok 且无 violations）：该 key 全部待决告警判为已调整。
            self._adjusted_count += len(surviving)
            self._pending[key] = []

    def record_chain(self, cumulative: DeltaResult, segments: list[DeltaResult]) -> None:
        """Record a composite comparison: cumulative vs aggregated sub-statuses.

        If ``cumulative.status`` differs from the P22-aggregate of
        ``[s.status for s in segments]``, a mismatch is counted (indicator 4).
        """
        self._chain_count += 1
        aggregated = aggregate_status([s.status for s in segments])
        if cumulative.status != aggregated:
            self._chain_mismatch_count += 1

    def snapshot(self) -> dict[str, Any]:
        """Return the 6 indicators as a plain dict.

        All rate values are ``float``; count values are ``int``.
        Rates with a zero denominator return ``0.0``.
        """
        total = self._compare_call_count
        reason_rate = 0.0 if total == 0 else self._reason_present / float(total)

        drift_total = self._drift_alert_count
        adjusted_rate = 0.0 if drift_total == 0 else self._adjusted_count / float(drift_total)

        chain_total = self._chain_count
        chain_mismatch_rate = (
            0.0 if chain_total == 0 else self._chain_mismatch_count / float(chain_total)
        )

        return {
            "compare_call_count": total,
            "drift_alert_count": drift_total,
            "adjusted_within_n_turns": adjusted_rate,
            "cumulative_segment_mismatch_rate": chain_mismatch_rate,
            "status_distribution": dict(self._status_dist),
            "reason_presence_rate": reason_rate,
        }
