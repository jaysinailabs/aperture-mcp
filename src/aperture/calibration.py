"""Experimental calibration sidecar for ``DeltaResult`` diagnostics.

Calibration metadata is recorded beside a result, never inside ``DeltaResult`` and never
as an input to comparison, aggregation, or reporting decisions. This module is an
envelope only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from aperture.core import AnchorKind, AnchorViolation, DeltaResult, DeltaStatus

__all__ = ["CalibrationRecord", "CalibrationRetriever", "CalibrationStore"]

_FORBIDDEN_KEY_TERMS = frozenset(("conf" + "idence", "sco" + "re", "qual" + "ity"))
_PROVIDER_KEY = "provider"


def _normalized_key(key: str) -> str:
    return key.lower().replace("-", "_").replace(" ", "_")


def _validate_metadata_keys(metadata: Mapping[str, Any]) -> None:
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise TypeError("calibration metadata keys must be strings")
        normalized = _normalized_key(key)
        parts = tuple(part for part in normalized.split("_") if part)
        if normalized in _FORBIDDEN_KEY_TERMS or (
            len(parts) >= 2 and parts[0] == _PROVIDER_KEY and parts[-1] in _FORBIDDEN_KEY_TERMS
        ):
            raise ValueError("calibration metadata may not include provider assessment fields")
        if isinstance(value, Mapping):
            _validate_metadata_keys(cast(Mapping[str, Any], value))


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        _validate_metadata_keys(cast(Mapping[str, Any], value))
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in cast(Mapping[str, Any], value).items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


def _freeze_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate_metadata_keys(metadata)
    return MappingProxyType({key: _freeze_value(value) for key, value in metadata.items()})


def _thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value


def _metadata_to_dict(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _thaw_value(value) for key, value in metadata.items()}


def _clone_record(record: CalibrationRecord) -> CalibrationRecord:
    return CalibrationRecord.from_dict(record.to_dict())


def _metadata_contains(metadata: Mapping[str, Any], provenance: Mapping[str, Any]) -> bool:
    for key, expected in provenance.items():
        if not isinstance(key, str):
            raise TypeError("calibration provenance keys must be strings")
        if key not in metadata:
            return False
        actual = metadata[key]
        if isinstance(actual, Mapping) and isinstance(expected, Mapping):
            if not _metadata_contains(
                cast(Mapping[str, Any], actual), cast(Mapping[str, Any], expected)
            ):
                return False
        elif _thaw_value(actual) != _thaw_value(expected):
            return False
    return True


def _result_from_dict(d: Mapping[str, Any]) -> DeltaResult:
    """Rebuild a ``DeltaResult`` from its ``to_dict()`` wire form."""
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
class CalibrationRecord:
    """Diagnostic calibration metadata attached beside a ``DeltaResult``.

    ``calibration`` is copied into an immutable view at construction time. ``to_dict()``
    always starts from ``result.to_dict()``, so the result's own serialization stays
    independent of this sidecar.
    """

    result: DeltaResult
    calibration: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "calibration", _freeze_metadata(self.calibration))

    def to_dict(self) -> dict[str, Any]:
        d = self.result.to_dict()
        d["calibration"] = _metadata_to_dict(self.calibration)
        d["stability"] = "experimental"
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CalibrationRecord:
        """Rebuild from a ``to_dict()`` payload — for TRUSTED round-trips only.

        This is a reconstruction helper, not an untrusted-input parser: a hostile or
        malformed ``d`` (e.g. bad ``anchor_violations`` entries) can make it raise.
        """
        if d.get("stability") != "experimental":
            raise ValueError("CalibrationRecord requires experimental stability")
        metadata = d["calibration"]
        if not isinstance(metadata, Mapping):
            raise TypeError("calibration metadata must be a mapping")
        return cls(result=_result_from_dict(d), calibration=cast(Mapping[str, Any], metadata))


class CalibrationStore:
    """In-memory caller-persisted store of diagnostic calibration records.

    Thread safety: this store is **not thread-safe**. Construct one per thread /
    logical session; do not share a live instance across threads. To hand state
    across threads / processes, serialize with ``snapshot()`` on the source side
    and rebuild with ``from_snapshot()`` on the destination side.
    """

    def __init__(self) -> None:
        self._records: dict[str, CalibrationRecord] = {}
        self._counter = 0

    def put(self, record: CalibrationRecord) -> str:
        self._counter += 1
        record_id = f"cal-{self._counter}"
        self._records[record_id] = _clone_record(record)
        return record_id

    def get(self, record_id: str) -> CalibrationRecord | None:
        record = self._records.get(record_id)
        if record is None:
            return None
        return _clone_record(record)

    def records(self) -> list[CalibrationRecord]:
        return [_clone_record(record) for record in self._records.values()]

    def snapshot(self) -> dict[str, Any]:
        return {
            "counter": self._counter,
            "records": [
                {"record_id": record_id, "record": record.to_dict()}
                for record_id, record in self._records.items()
            ],
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> CalibrationStore:
        store = cls()
        counter = snapshot.get("counter", 0)
        if not isinstance(counter, int):
            raise TypeError("calibration store counter must be an integer")
        store._counter = counter

        entries = snapshot["records"]
        if not isinstance(entries, list):
            raise TypeError("calibration store records must be a list")
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise TypeError("calibration store record entries must be mappings")
            record_id = entry["record_id"]
            if not isinstance(record_id, str):
                raise TypeError("calibration record id must be a string")
            payload = entry["record"]
            if not isinstance(payload, Mapping):
                raise TypeError("calibration record payload must be a mapping")
            store._records[record_id] = CalibrationRecord.from_dict(
                cast(Mapping[str, Any], payload)
            )
        return store


class CalibrationRetriever:
    """Read-side provenance queries over a ``CalibrationStore``."""

    def __init__(self, store: CalibrationStore) -> None:
        self._store = store

    def query(self, *, provenance: Mapping[str, Any] | None = None) -> list[CalibrationRecord]:
        """Return records whose calibration metadata is a superset of ``provenance``.

        Results are in recording (insertion) order — a neutral chronological order, NOT a
        ranking. ``provenance=None`` returns all records; an empty mapping is rejected (it is an
        ambiguous "all", and this read API is filter-only — never a selector/ranker).
        """
        if provenance is None:
            return self._store.records()
        if not provenance:
            raise ValueError("empty provenance filter; pass provenance=None to get all records")
        _validate_metadata_keys(provenance)
        return [
            record
            for record in self._store.records()
            if _metadata_contains(record.calibration, provenance)
        ]
