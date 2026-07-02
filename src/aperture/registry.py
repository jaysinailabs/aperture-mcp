"""AnchorRegistry — manage anchor lifecycle, active set, and version-guarded mutations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from aperture.core import Anchor, AnchorKind
from aperture.errors import ApertureError, require_nonempty

__all__ = [
    "AnchorRegistry",
    "LifecycleEvent",
    "StaleWriteError",
    "TerminalStateError",
    "Transition",
    "UnknownAnchorError",
]


_State = Literal["Active", "Revoked", "Superseded"]


class Transition(StrEnum):
    """Audit-event labels encoding which lifecycle mutation occurred."""

    REGISTERED = "Registered"
    REAFFIRMED = "Reaffirmed"
    SUPERSEDED = "Superseded"
    REVOKED = "Revoked"


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """Immutable audit record of a single lifecycle mutation.

    Immutable audit record of a single lifecycle mutation.
    ``at`` (timestamp) is required; ``reason`` is optional.
    """

    anchor_id: str
    transition: Transition
    by: str
    at: str
    reason: str | None = None


class TerminalStateError(ApertureError, RuntimeError):
    """Raised when an operation is attempted on a Revoked or Superseded anchor.

    Re-parented onto ``ApertureError`` via multiple inheritance, so it is now
    catchable as an :class:`~aperture.errors.ApertureError` while pre-existing
    ``except RuntimeError`` handlers keep matching unchanged.
    """


class StaleWriteError(ApertureError, RuntimeError):
    """Raised when `expected_version` does not match the current anchor version.

    Re-parented onto ``ApertureError`` via multiple inheritance, so it is now
    catchable as an :class:`~aperture.errors.ApertureError` while pre-existing
    ``except RuntimeError`` handlers keep matching unchanged.
    """


class UnknownAnchorError(ApertureError, KeyError):
    """Raised when referencing an `anchor_id` that was never registered.

    Re-parented onto ``ApertureError`` via multiple inheritance, so it is now
    catchable as an :class:`~aperture.errors.ApertureError` while pre-existing
    ``except KeyError`` handlers keep matching unchanged.
    """


@dataclass(slots=True)
class _AnchorRecord:
    """Internal mutable per-anchor state."""

    kind: AnchorKind
    state: _State
    version: int
    confidence: int
    reason: str | None = None
    by: str | None = None
    at: str | None = None
    superseded_by_id: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AnchorRegistry:
    """In-memory anchor registry with lifecycle tracking and optimistic versioning.

    Each anchor exists in one of three lifecycle states: ``Active``, ``Revoked``,
    or ``Superseded``.  Every successful mutation appends a ``LifecycleEvent``
    and bumps the anchor's internal version counter.  Callers may supply an
    optional ``expected_version`` to detect stale writes.

    The registry is serializable via ``snapshot()`` / ``from_snapshot()``,
    enabling caller-side persistence; the registry itself performs no storage
    or I/O (it stays in-memory and single-session).

    Thread safety: this registry is **not thread-safe**. Construct one per thread /
    logical session; do not share a live instance across threads. To hand state
    across threads / processes, serialize with ``snapshot()`` on the source side
    and rebuild with ``from_snapshot()`` on the destination side.

    Optimistic versioning is an **in-session** check, not a thread-safe
    compare-and-set (CAS): ``expected_version`` is verified against the current
    version under the assumption that no other writer mutates the same anchor
    concurrently. Under concurrent shared access two writers reading the same
    ``expected_version`` can both pass the check and both mutate, silently losing
    one update (a lost-update race). Use one registry per thread / session — or a
    caller-side lock around the shared instance — if you need true CAS semantics.
    """

    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now_iso
        self._records: dict[str, _AnchorRecord] = {}
        self._events: dict[str, list[LifecycleEvent]] = {}

    # ------------------------------------------------------------------ public API

    def register(self, anchor: Anchor) -> str:
        anchor_id = anchor.id
        if anchor_id in self._records:
            raise ValueError(f"Anchor '{anchor_id}' already registered.")
        now = self._clock()
        self._records[anchor_id] = _AnchorRecord(
            kind=anchor.kind,
            state="Active",
            version=1,
            confidence=1,
        )
        self._events.setdefault(anchor_id, []).append(
            LifecycleEvent(
                anchor_id=anchor_id, transition=Transition.REGISTERED, by="registry", at=now
            )
        )
        return anchor_id

    def reaffirm(
        self,
        anchor_id: str,
        by: str,
        reason: str | None = None,
        expected_version: int | None = None,
    ) -> Anchor:
        """Re-confirm an Active anchor, bumping its confidence and version.

        Args:
            anchor_id: The anchor to reaffirm.
            by: Non-empty actor recorded on the audit event (required).
            reason: Optional free-text justification.
            expected_version: Optional **in-session** optimistic check — NOT a
                thread-safe CAS. Under concurrent shared access two writers with the
                same ``expected_version`` can both pass and both mutate (lost update).
        """
        require_nonempty(by, "by")
        record = self._record_for_op(anchor_id, expected_version)
        if record.state != "Active":
            raise TerminalStateError(f"Anchor '{anchor_id}' is {record.state}, cannot reaffirm.")
        record.confidence += 1
        record.version += 1
        now = self._clock()
        self._events[anchor_id].append(
            LifecycleEvent(
                anchor_id=anchor_id, transition=Transition.REAFFIRMED, by=by, reason=reason, at=now
            )
        )
        return Anchor(kind=record.kind, id=anchor_id)

    def supersede(
        self,
        anchor_id: str,
        by_id: str,
        reason: str,
        by: str,
        expected_version: int | None = None,
    ) -> Anchor:
        """Supersede an Active anchor with another Active anchor.

        Args:
            anchor_id: The anchor being superseded.
            by_id: The Active anchor that supersedes it (must differ from ``anchor_id``).
            reason: Non-empty justification recorded on the audit event (required).
            by: Non-empty actor recorded on the audit event (required).
            expected_version: Optional **in-session** optimistic check — NOT a
                thread-safe CAS. Under concurrent shared access two writers with the
                same ``expected_version`` can both pass and both mutate (lost update).
        """
        require_nonempty(reason, "reason")
        require_nonempty(by, "by")
        if anchor_id == by_id:
            raise ValueError(f"Anchor '{anchor_id}' cannot supersede itself.")
        record = self._record_for_op(anchor_id, expected_version)
        if record.state != "Active":
            raise TerminalStateError(f"Anchor '{anchor_id}' is {record.state}, cannot supersede.")
        superseding = self._records.get(by_id)
        if superseding is None:
            raise UnknownAnchorError(by_id)
        if superseding.state != "Active":
            raise TerminalStateError(
                f"Superseding anchor '{by_id}' is {superseding.state}, must be Active."
            )
        record.state = "Superseded"
        record.reason = reason
        record.by = by
        record.at = self._clock()
        record.superseded_by_id = by_id
        record.version += 1
        self._events[anchor_id].append(
            LifecycleEvent(
                anchor_id=anchor_id,
                transition=Transition.SUPERSEDED,
                by=by,
                reason=reason,
                at=record.at or "",
            )
        )
        return Anchor(kind=record.kind, id=anchor_id)

    def revoke(
        self,
        anchor_id: str,
        reason: str,
        by: str,
        expected_version: int | None = None,
    ) -> Anchor:
        """Revoke an Active anchor (terminal state).

        Args:
            anchor_id: The anchor to revoke.
            reason: Non-empty justification recorded on the audit event (required).
            by: Non-empty actor recorded on the audit event (required).
            expected_version: Optional **in-session** optimistic check — NOT a
                thread-safe CAS. Under concurrent shared access two writers with the
                same ``expected_version`` can both pass and both mutate (lost update).
        """
        require_nonempty(reason, "reason")
        require_nonempty(by, "by")
        record = self._record_for_op(anchor_id, expected_version)
        if record.state != "Active":
            raise TerminalStateError(f"Anchor '{anchor_id}' is {record.state}, cannot revoke.")
        record.state = "Revoked"
        record.reason = reason
        record.by = by
        record.at = self._clock()
        record.version += 1
        self._events[anchor_id].append(
            LifecycleEvent(
                anchor_id=anchor_id,
                transition=Transition.REVOKED,
                by=by,
                reason=reason,
                at=record.at or "",
            )
        )
        return Anchor(kind=record.kind, id=anchor_id)

    def query_active(self) -> list[Anchor]:
        return [
            Anchor(kind=r.kind, id=aid) for aid, r in self._records.items() if r.state == "Active"
        ]

    def query_history(self, anchor_id: str) -> list[LifecycleEvent]:
        return list(self._events.get(anchor_id, []))

    # --------------------------------------------------------------- serialization

    def snapshot(self) -> dict[str, Any]:
        records: dict[str, Any] = {}
        for aid, r in self._records.items():
            records[aid] = {
                "kind": r.kind.value,
                "state": r.state,
                "version": r.version,
                "confidence": r.confidence,
                "reason": r.reason,
                "by": r.by,
                "at": r.at,
                "superseded_by_id": r.superseded_by_id,
            }
        events: dict[str, list[dict[str, Any]]] = {}
        for aid, evts in self._events.items():
            serialized: list[dict[str, Any]] = []
            for e in evts:
                event = {
                    "anchor_id": e.anchor_id,
                    "transition": e.transition.value,
                    "by": e.by,
                    "at": e.at,
                }
                if e.reason is not None:
                    event["reason"] = e.reason
                serialized.append(event)
            events[aid] = serialized
        return {"anchors": records, "events": events}

    @classmethod
    def from_snapshot(
        cls, snapshot: dict[str, Any], clock: Callable[[], str] | None = None
    ) -> AnchorRegistry:
        registry = cls(clock=clock)
        for aid, data in snapshot["anchors"].items():
            registry._records[aid] = _AnchorRecord(
                kind=AnchorKind(data["kind"]),
                state=data["state"],
                version=data["version"],
                confidence=data["confidence"],
                reason=data.get("reason"),
                by=data.get("by"),
                at=data.get("at"),
                superseded_by_id=data.get("superseded_by_id"),
            )
        for aid, evts_data in snapshot["events"].items():
            registry._events[aid] = [
                LifecycleEvent(
                    anchor_id=e["anchor_id"],
                    transition=Transition(e["transition"]),
                    by=e["by"],
                    reason=e.get("reason"),
                    at=e["at"],
                )
                for e in evts_data
            ]
        return registry

    # -------------------------------------------------------------------- helpers

    def _record_for_op(self, anchor_id: str, expected_version: int | None) -> _AnchorRecord:
        record = self._records.get(anchor_id)
        if record is None:
            raise UnknownAnchorError(anchor_id)
        if expected_version is not None and expected_version != record.version:
            raise StaleWriteError(f"Expected version {expected_version}, got {record.version}")
        return record
