"""Aperture reference implementation.

LAZY TOP-LEVEL RE-EXPORTS (PEP 562). The public names below are re-exported from
their defining submodules but resolved ON DEMAND via a module-level
``__getattr__`` rather than imported eagerly at package-import time. This keeps the
import graph minimal: importing a single submodule (e.g.
``aperture.topology``) no longer drags ``aperture.core`` (the
compare oracle) into ``sys.modules`` as a side effect of running this ``__init__``.
``from aperture import compare`` still works — it triggers a lazy
``importlib.import_module`` of ``aperture.core`` at first access — and
``hasattr(aperture, name)`` for any ``__all__`` name remains true (PEP 562
satisfies the public-surface contract).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public name -> defining submodule. Resolution is lazy (see __getattr__): the
# submodule is imported only when the name is first accessed. Keep in lockstep
# with __all__.
_LAZY_EXPORTS: dict[str, str] = {
    "as_c4_delta_result": "c4_wire",
    "CalibrationRecord": "calibration",
    "CalibrationRetriever": "calibration",
    "CalibrationStore": "calibration",
    "Anchor": "core",
    "AnchorKind": "core",
    "AnchorViolation": "core",
    "DeltaResult": "core",
    "DeltaStatus": "core",
    "aggregate_status": "core",
    "compare": "core",
    "compare_commitment": "core",
    "compare_proposal": "core",
    "compare_stance": "core",
    "compare_text": "core",
    "AlreadyTombstonedError": "delta_history",
    "ContextSignature": "delta_history",
    "DeltaHistoryRetriever": "delta_history",
    "DeltaHistoryStore": "delta_history",
    "DeltaRecord": "delta_history",
    "UnknownRecordError": "delta_history",
    "ApertureError": "errors",
    "MetricsCollector": "metrics",
    "build_openai_tools": "openai_schema",
    "AnchorRegistry": "registry",
    "LifecycleEvent": "registry",
    "StaleWriteError": "registry",
    "TerminalStateError": "registry",
    "Transition": "registry",
    "UnknownAnchorError": "registry",
    "TopologyProvider": "topology",
}

if TYPE_CHECKING:
    # Static re-import so mypy / IDEs see the names as first-class exports. Never
    # executed at runtime (TYPE_CHECKING is False), so it does NOT eagerly import
    # the submodules — the lazy __getattr__ below is the only runtime path.
    from aperture.c4_wire import as_c4_delta_result as as_c4_delta_result
    from aperture.calibration import CalibrationRecord as CalibrationRecord
    from aperture.calibration import CalibrationRetriever as CalibrationRetriever
    from aperture.calibration import CalibrationStore as CalibrationStore
    from aperture.core import Anchor as Anchor
    from aperture.core import AnchorKind as AnchorKind
    from aperture.core import AnchorViolation as AnchorViolation
    from aperture.core import DeltaResult as DeltaResult
    from aperture.core import DeltaStatus as DeltaStatus
    from aperture.core import aggregate_status as aggregate_status
    from aperture.core import compare as compare
    from aperture.core import compare_commitment as compare_commitment
    from aperture.core import compare_proposal as compare_proposal
    from aperture.core import compare_stance as compare_stance
    from aperture.core import compare_text as compare_text
    from aperture.delta_history import AlreadyTombstonedError as AlreadyTombstonedError
    from aperture.delta_history import ContextSignature as ContextSignature
    from aperture.delta_history import DeltaHistoryRetriever as DeltaHistoryRetriever
    from aperture.delta_history import DeltaHistoryStore as DeltaHistoryStore
    from aperture.delta_history import DeltaRecord as DeltaRecord
    from aperture.delta_history import UnknownRecordError as UnknownRecordError
    from aperture.errors import ApertureError as ApertureError
    from aperture.metrics import MetricsCollector as MetricsCollector
    from aperture.openai_schema import build_openai_tools as build_openai_tools
    from aperture.registry import AnchorRegistry as AnchorRegistry
    from aperture.registry import LifecycleEvent as LifecycleEvent
    from aperture.registry import StaleWriteError as StaleWriteError
    from aperture.registry import TerminalStateError as TerminalStateError
    from aperture.registry import Transition as Transition
    from aperture.registry import UnknownAnchorError as UnknownAnchorError
    from aperture.topology import TopologyProvider as TopologyProvider


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute resolution for the package's public names.

    Resolve ``name`` by importing ONLY the submodule it lives in, on first access,
    so importing one submodule does not eagerly pull every sibling (notably
    ``core``) into ``sys.modules``. Unknown names raise ``AttributeError``.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f"{__name__}.{module_name}")
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted([*__all__, "__version__"])


__all__ = [
    "AlreadyTombstonedError",
    "Anchor",
    "AnchorKind",
    "AnchorRegistry",
    "AnchorViolation",
    "ApertureError",
    "CalibrationRecord",
    "CalibrationRetriever",
    "CalibrationStore",
    "ContextSignature",
    "DeltaHistoryRetriever",
    "DeltaHistoryStore",
    "DeltaRecord",
    "DeltaResult",
    "DeltaStatus",
    "LifecycleEvent",
    "MetricsCollector",
    "StaleWriteError",
    "TerminalStateError",
    "TopologyProvider",
    "Transition",
    "UnknownAnchorError",
    "UnknownRecordError",
    "aggregate_status",
    "as_c4_delta_result",
    "build_openai_tools",
    "compare",
    "compare_commitment",
    "compare_proposal",
    "compare_stance",
    "compare_text",
]

__version__ = "0.2.0"
