"""DeltaHistoryStore / DeltaHistoryRetriever — cross-call decision-history persistence.

Independent Store / Retriever pair (peer to Provider, not a Provider
family), shaped like ``AnchorRegistry`` —— interface in-spec, storage I/O left to the caller,
in-memory + snapshot / load. Hard invariants kept here:

- ``compare()`` stays a **pure function**: history writes are the caller's **explicit** action
  (``DeltaHistoryStore.put``), never an implicit write-back from ``compare`` (which would make
  it stateful and slide toward cross-session memory — a red line).
- Retrieval lives in the **Retriever**, never inside ``compare`` —— so ``agent_identity`` (a
  query dimension) never makes compare identity-aware (the retriever is a separate object,
- ``similar_context`` is **binary — exact / structural**; embedding / semantic similarity is
  out of v0.2 (通用语义记忆地盘): it is simply absent from this API, and staying absent is
  compliant.
- Deletion = **tombstone with reason**: a tombstoned record stays in the snapshot (审计链不断),
  is filtered from queries by default, and is retrievable with ``include_tombstoned=True``.
- Envelope fields (``record_id`` / ``at`` / ``agent_identity`` / tombstone state) live on the
  Store-record, **not** inside ``DeltaResult`` (which stays frozen and clock / identity-free).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from aperture.core import Anchor, AnchorKind, AnchorViolation, DeltaResult, DeltaStatus
from aperture.errors import ApertureError

__all__ = [
    "AlreadyTombstonedError",
    "ContextSignature",
    "DeltaHistoryRetriever",
    "DeltaHistoryStore",
    "DeltaRecord",
    "InvalidQueryError",
    "UnknownRecordError",
]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_iso_timestamp(value: str, field: str) -> None:
    """Reject a non-ISO-8601 ``since`` / ``until`` query bound.

    The stored ``at`` envelope is produced as an ISO timestamp; the query window is
    compared lexicographically against it. Lexicographic comparison only yields a
    *chronological* answer when both operands are well-formed ISO strings, so a
    malformed bound would silently corrupt the window rather than narrow it. We parse
    with :func:`datetime.fromisoformat` purely to validate; the original string is what
    the comparison still uses (so an offset like ``+00:00`` is preserved verbatim).
    """
    if not isinstance(value, str):
        raise InvalidQueryError(f"{field} must be an ISO-8601 timestamp string")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidQueryError(
            f"{field} must be a well-formed ISO-8601 timestamp; got {value!r}"
        ) from exc


class UnknownRecordError(ApertureError, KeyError):
    """Raised when referencing a ``record_id`` that was never stored.

    Re-parented onto ``ApertureError`` via multiple inheritance, so it is now
    catchable as an :class:`~aperture.errors.ApertureError` while pre-existing
    ``except KeyError`` handlers keep matching unchanged.
    """


class AlreadyTombstonedError(ApertureError, RuntimeError):
    """Raised when tombstoning a record that is already tombstoned.

    Re-parented onto ``ApertureError`` via multiple inheritance, so it is now
    catchable as an :class:`~aperture.errors.ApertureError` while pre-existing
    ``except RuntimeError`` handlers keep matching unchanged.
    """


class InvalidQueryError(ApertureError, ValueError):
    """Raised when a query argument is malformed (e.g. a non-ISO timestamp).

    Inherits from ``ValueError`` so callers may catch it either as an
    :class:`~aperture.errors.ApertureError` or with a plain ``except ValueError``.
    """


@dataclass(frozen=True, slots=True)
class ContextSignature:
    """Structural identity of a compare context, for exact / structural retrieval.

    - **structural** match = same ``state_kind`` + same anchor set (kind + id,
      order-independent).
    - **exact** match additionally requires the same opaque ``context_key`` (a
      caller-supplied identifier for the precise context — e.g. a hash of the compared
      state pair). No embedding / semantic similarity (that is out of v0.2).
    """

    state_kind: str
    anchor_ids: tuple[str, ...]
    context_key: str | None = None

    def __post_init__(self) -> None:
        # Anchor-SET semantics: dedup + order-independent, however the signature is
        # constructed (`of`, direct, or `from_dict`).
        object.__setattr__(self, "anchor_ids", tuple(sorted(set(self.anchor_ids))))

    @classmethod
    def of(
        cls,
        state_kind: str,
        anchors: Iterable[Anchor] | None = None,
        context_key: str | None = None,
    ) -> ContextSignature:
        """Build a signature from the same inputs a caller passes to ``compare``."""
        ids = tuple(f"{a.kind.value}:{a.id}" for a in (anchors or []))
        return cls(state_kind=state_kind, anchor_ids=ids, context_key=context_key)

    @property
    def structural_key(self) -> tuple[str, tuple[str, ...]]:
        """The ``(state_kind, anchor-set)`` tuple used for structural matching."""
        return (self.state_kind, self.anchor_ids)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"state_kind": self.state_kind, "anchor_ids": list(self.anchor_ids)}
        if self.context_key is not None:
            d["context_key"] = self.context_key
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContextSignature:
        return cls(
            state_kind=d["state_kind"],
            anchor_ids=tuple(d["anchor_ids"]),
            context_key=d.get("context_key"),
        )


def _result_from_dict(d: dict[str, Any]) -> DeltaResult:
    """Rebuild a ``DeltaResult`` from its ``to_dict()`` wire form (snapshot round-trip)."""
    violations = [
        AnchorViolation(
            anchor_id=v["anchor_id"],
            kind=AnchorKind(v["kind"]),
            status=DeltaStatus(v["status"]),
            detail=v.get("detail"),
        )
        for v in d.get("anchor_violations", [])
    ]
    return DeltaResult(
        status=DeltaStatus(d["status"]),
        reason=d["reason"],
        provider_family=d.get("provider_family", "mock"),
        profile=d.get("profile"),
        state_kind=d.get("state_kind", "text"),
        anchor_violations=violations,
        event_id=d.get("event_id"),
    )


@dataclass(frozen=True, slots=True)
class DeltaRecord:
    """A stored history entry: a ``DeltaResult`` plus a Store-envelope.

    Envelope fields (``record_id`` / ``at`` / ``agent_identity`` / tombstone state) live
    here, **not** inside ``DeltaResult`` — DeltaResult stays frozen and clock / identity-free
    (by design). Tombstoning marks the record (``tombstoned``) and keeps it in the snapshot,
    so the audit chain is never broken.
    """

    record_id: str
    result: DeltaResult
    signature: ContextSignature
    at: str
    agent_identity: str | None = None
    tombstoned: bool = False
    tombstone_reason: str | None = None
    tombstoned_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "record_id": self.record_id,
            "result": self.result.to_dict(),
            "signature": self.signature.to_dict(),
            "at": self.at,
            "tombstoned": self.tombstoned,
        }
        if self.agent_identity is not None:
            d["agent_identity"] = self.agent_identity
        if self.tombstone_reason is not None:
            d["tombstone_reason"] = self.tombstone_reason
        if self.tombstoned_at is not None:
            d["tombstoned_at"] = self.tombstoned_at
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeltaRecord:
        return cls(
            record_id=d["record_id"],
            result=_result_from_dict(d["result"]),
            signature=ContextSignature.from_dict(d["signature"]),
            at=d["at"],
            agent_identity=d.get("agent_identity"),
            tombstoned=d.get("tombstoned", False),
            tombstone_reason=d.get("tombstone_reason"),
            tombstoned_at=d.get("tombstoned_at"),
        )


class DeltaHistoryStore:
    """In-memory, caller-persisted store of compare history.

    The store is stateful (it *is* a store) but performs no storage / I/O of its own —
    callers serialize via ``snapshot()`` / ``from_snapshot()``. Writes are explicit
    (``put``); the store is never invoked implicitly by ``compare``.

    Thread safety: this store is **not thread-safe**. Construct one per thread /
    logical session; do not share a live instance across threads. To hand state
    across threads / processes, serialize with ``snapshot()`` on the source side
    and rebuild with ``from_snapshot()`` on the destination side.
    """

    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now_iso
        self._records: dict[str, DeltaRecord] = {}
        self._counter = 0

    # ------------------------------------------------------------------ write side

    def put(
        self,
        result: DeltaResult,
        signature: ContextSignature,
        agent_identity: str | None = None,
    ) -> DeltaRecord:
        """Explicitly append a compare result to history (caller-driven write).

        Returns the stored ``DeltaRecord`` with its store-assigned ``record_id`` and
        timestamp. This is the **only** way history grows — ``compare`` never calls it.
        """
        self._counter += 1
        record = DeltaRecord(
            record_id=f"rec-{self._counter}",
            result=result,
            signature=signature,
            at=self._clock(),
            agent_identity=agent_identity,
        )
        self._records[record.record_id] = record
        return record

    def tombstone(self, record_id: str, reason: str) -> DeltaRecord:
        """Soft-delete a record (tombstone with reason).

        The record stays in the snapshot (audit chain unbroken) but is filtered from
        queries by default. Re-tombstoning a tombstoned record is an error.
        """
        if not reason.strip():
            raise ValueError("tombstone requires a non-empty reason")
        record = self._records.get(record_id)
        if record is None:
            raise UnknownRecordError(record_id)
        if record.tombstoned:
            raise AlreadyTombstonedError(record_id)
        tombstoned = replace(
            record, tombstoned=True, tombstone_reason=reason, tombstoned_at=self._clock()
        )
        self._records[record_id] = tombstoned
        return tombstoned

    # ------------------------------------------------------------------- read side

    def get(self, record_id: str, *, include_tombstoned: bool = False) -> DeltaRecord | None:
        record = self._records.get(record_id)
        if record is None:
            return None
        if record.tombstoned and not include_tombstoned:
            return None
        return record

    def records(self, *, include_tombstoned: bool = False) -> list[DeltaRecord]:
        """All records in insertion order; tombstoned filtered out unless requested."""
        return [r for r in self._records.values() if include_tombstoned or not r.tombstoned]

    # --------------------------------------------------------------- serialization

    def snapshot(self) -> dict[str, Any]:
        return {
            "counter": self._counter,
            "records": [r.to_dict() for r in self._records.values()],
        }

    @classmethod
    def from_snapshot(
        cls, snapshot: dict[str, Any], clock: Callable[[], str] | None = None
    ) -> DeltaHistoryStore:
        store = cls(clock=clock)
        store._counter = snapshot.get("counter", 0)
        for d in snapshot["records"]:
            record = DeltaRecord.from_dict(d)
            store._records[record.record_id] = record
        return store


class DeltaHistoryRetriever:
    """Read-side queries over a ``DeltaHistoryStore``.

    Retrieval lives here (never inside ``compare``), so introducing history never makes
    ``compare`` stateful or identity-aware (hard invariant).
    """

    def __init__(self, store: DeltaHistoryStore) -> None:
        self._store = store

    def query(
        self,
        *,
        state_kind: str | None = None,
        agent_identity: str | None = None,
        since: str | None = None,
        until: str | None = None,
        include_tombstoned: bool = False,
    ) -> list[DeltaRecord]:
        """Filter history by envelope dimensions (state_kind / agent_identity / time window).

        ``since`` / ``until`` are ISO-8601 timestamps compared lexicographically (inclusive
        bounds — lexicographic order is chronological for a fixed ISO format). Any dimension
        left ``None`` is unconstrained. A malformed (non-ISO) ``since`` / ``until`` is rejected
        with :class:`InvalidQueryError` rather than silently string-compared against the
        stored timestamps.
        """
        if since is not None:
            _validate_iso_timestamp(since, "since")
        if until is not None:
            _validate_iso_timestamp(until, "until")
        out: list[DeltaRecord] = []
        for r in self._store.records(include_tombstoned=include_tombstoned):
            if state_kind is not None and r.signature.state_kind != state_kind:
                continue
            if agent_identity is not None and r.agent_identity != agent_identity:
                continue
            if since is not None and r.at < since:
                continue
            if until is not None and r.at > until:
                continue
            out.append(r)
        return out

    def similar_context(
        self,
        signature: ContextSignature,
        *,
        mode: Literal["exact", "structural"] = "structural",
        include_tombstoned: bool = False,
    ) -> list[DeltaRecord]:
        """Retrieve prior records sharing the given context.

        - ``structural`` (default): same ``state_kind`` + same anchor set.
        - ``exact``: additionally the same ``context_key``.

        Embedding / semantic similarity is out of v0.2 (general-memory territory) and is
        intentionally not offered — staying absent is compliant (by design).
        """
        out: list[DeltaRecord] = []
        for r in self._store.records(include_tombstoned=include_tombstoned):
            if mode == "structural":
                if r.signature.structural_key == signature.structural_key:
                    out.append(r)
            elif r.signature == signature:
                out.append(r)
        return out
