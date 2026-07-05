"""Default Python runner for Aperture language-agnostic conformance fixtures.

The fixture set is change-controlled. This runner intentionally ships with no new
fixtures; it discovers already-approved JSON fixtures under ``conformance/fixtures``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "aperture-py", ROOT / "src", ROOT):
    path = str(candidate)
    if path not in sys.path and candidate.exists():
        sys.path.insert(0, path)

from aperture import (  # noqa: E402
    Anchor,
    AnchorKind,
    ContextSignature,
    DeltaHistoryRetriever,
    DeltaHistoryStore,
    DeltaResult,
    __version__,
    compare,
    compare_commitment,
    compare_proposal,
    compare_stance,
)
from aperture.c4_wire import as_c4_delta_result  # noqa: E402
from aperture.topology import DecisionGraph, Edge, TopologyProvider  # noqa: E402

try:
    from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only in under-provisioned envs.
    Draft202012Validator = None
    ValidationError = Exception


FIXTURE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://aperture.dev/conformance/fixture.schema.json",
    "type": "object",
    "required": ["case", "input", "expected"],
    "properties": {
        "case": {"type": "string", "minLength": 1},
        "entry": {
            "type": "string",
            "enum": [
                "compare",
                "compare_proposal",
                "compare_stance",
                "compare_commitment",
                "topology.analyze",
                "topology.metric",
                "openai.tools",
                "openai.tool_call",
                "mcp.tool_call",
                "access.anchor_admission",
                "delta_history",
                "schema.validate",
            ],
        },
        "covers": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "provisional": {"type": "boolean"},
        "negative": {"type": "boolean"},
        "input": {"type": "object"},
        "expected": {"type": "object"},
    },
    "additionalProperties": False,
}

FIXTURES_DIR = ROOT / "conformance" / "fixtures"
METHODOLOGY_SCHEMA: Path | None = None

COMPARE_ENTRIES: dict[str, Callable[..., DeltaResult]] = {
    "compare": compare,
    "compare_proposal": compare_proposal,
    "compare_stance": compare_stance,
    "compare_commitment": compare_commitment,
}


@dataclass(frozen=True)
class Actual:
    value: Any
    c4_delta_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class CaseResult:
    case: str
    path: Path
    passed: bool
    failures: tuple[str, ...] = ()


class FixtureError(AssertionError):
    """Raised for fixture shape or assertion failures."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise FixtureError(f"{path}: fixture root must be an object")
    return value


def _require_jsonschema() -> None:
    if Draft202012Validator is None:
        raise FixtureError("jsonschema is required for conformance schema validation")


def _validate_fixture_shape(fixture: dict[str, Any]) -> None:
    _require_jsonschema()
    Draft202012Validator(FIXTURE_SCHEMA).validate(fixture)


def _load_methodology_schema(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        print(
            "methodology schema not bundled; skipping C4 wire schema check",
            file=sys.stderr,
        )
        return None
    return _load_json(path)


def _validate_ref(instance: Any, schema: dict[str, Any], ref: str) -> None:
    _require_jsonschema()
    Draft202012Validator({"$ref": ref, "$defs": schema["$defs"]}).validate(instance)


def _anchors(items: Any) -> list[Anchor]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise FixtureError("input.anchors must be an array when present")
    parsed: list[Anchor] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise FixtureError(f"input.anchors[{index}] must be an object")
        if set(item) != {"kind", "id"}:
            raise FixtureError(f"input.anchors[{index}] must contain exactly kind and id")
        parsed.append(Anchor(kind=AnchorKind(item["kind"]), id=item["id"]))
    return parsed


def _state_pair(payload: Mapping[str, Any]) -> tuple[str, str]:
    left = payload.get("state_a", payload.get("left"))
    right = payload.get("state_b", payload.get("right"))
    if not isinstance(left, str) or not isinstance(right, str):
        raise FixtureError("input must provide string state_a/state_b or left/right")
    return left, right


def _run_compare(entry: str, payload: Mapping[str, Any]) -> Actual:
    state_a, state_b = _state_pair(payload)
    result = COMPARE_ENTRIES[entry](
        state_a,
        state_b,
        anchors=_anchors(payload.get("anchors")),
        context=payload.get("context"),
        event_id=payload.get("event_id"),
    )
    return Actual(value=result.to_dict(), c4_delta_result=as_c4_delta_result(result))


def _edge(item: Any) -> Edge:
    if isinstance(item, dict):
        src = item.get("src", item.get("from"))
        dst = item.get("dst", item.get("to"))
        label = item.get("label")
    elif isinstance(item, list | tuple) and len(item) == 3:
        src, dst, label = item
    else:
        raise FixtureError("graph.edges items must be objects or [src, dst, label] triples")
    if not isinstance(src, str) or not isinstance(dst, str) or not isinstance(label, str):
        raise FixtureError("graph edge src/dst/label must be strings")
    return Edge(src=src, dst=dst, label=label)


def _graph(payload: Mapping[str, Any]) -> DecisionGraph:
    graph = payload.get("graph")
    if not isinstance(graph, dict):
        raise FixtureError("input.graph must be an object")
    raw_edges = graph.get("edges", [])
    if not isinstance(raw_edges, list):
        raise FixtureError("input.graph.edges must be an array")
    edges = tuple(_edge(item) for item in raw_edges)
    raw_nodes = graph.get("nodes")
    if raw_nodes is None:
        return DecisionGraph.from_edges(edges)
    if not isinstance(raw_nodes, list) or not all(isinstance(node, str) for node in raw_nodes):
        raise FixtureError("input.graph.nodes must be an array of strings")
    return DecisionGraph.from_edges(edges, nodes=frozenset(raw_nodes))


def _run_topology(entry: str, payload: Mapping[str, Any]) -> Actual:
    provider = TopologyProvider()
    graph = _graph(payload)
    if entry == "topology.metric":
        metric = payload.get("metric")
        if not isinstance(metric, str):
            raise FixtureError("input.metric must be a string for topology.metric")
        result = provider.metric(metric, graph)
    else:
        result = provider.analyze(graph)
    return Actual(value=result.to_dict())


def _openai_tools_by_name() -> dict[str, dict[str, Any]]:
    from aperture.openai_schema import build_openai_tools

    return {tool["function"]["name"]: tool for tool in build_openai_tools()}


def _run_openai_tools(_: Mapping[str, Any]) -> Actual:
    return Actual(value=list(_openai_tools_by_name().values()))


def _run_openai_tool_call(payload: Mapping[str, Any]) -> Actual:
    tool = payload.get("tool")
    arguments = payload.get("arguments", {})
    if not isinstance(tool, str) or not isinstance(arguments, dict):
        raise FixtureError("openai.tool_call requires input.tool and input.arguments")
    tools = _openai_tools_by_name()
    if tool not in tools:
        raise FixtureError(f"unknown OpenAI tool: {tool}")
    _validate_openai_arguments(tool, arguments, tools)
    if tool == "health":
        return Actual(value={"status": "ok", "name": "aperture", "version": __version__})
    actual = _run_compare(tool, arguments)
    return actual


def _validate_openai_arguments(
    tool: str, arguments: dict[str, Any], tools: Mapping[str, dict[str, Any]]
) -> None:
    _require_jsonschema()
    schema = tools[tool]["function"]["parameters"]
    Draft202012Validator(schema).validate(arguments)


def _run_mcp_tool_call(payload: Mapping[str, Any]) -> Actual:
    try:
        # Optional-dependency import block. `aperture` is first-party under the published src/
        # layout but third-party under the dev layout, so isort groups it differently between the
        # two repos; the noqa pins this order so neither repo's CI churns the block.
        import anyio  # noqa: I001
        from aperture.mcp_server import build_server
        from mcp.shared.memory import create_connected_server_and_client_session
    except ImportError as exc:  # pragma: no cover - depends on optional mcp extra.
        raise FixtureError("mcp.tool_call requires the optional mcp dependency") from exc

    tool = payload.get("tool")
    arguments = payload.get("arguments", {})
    if not isinstance(tool, str) or not isinstance(arguments, dict):
        raise FixtureError("mcp.tool_call requires input.tool and input.arguments")

    async def call() -> dict[str, Any]:
        async with create_connected_server_and_client_session(build_server()) as session:
            result = await session.call_tool(tool, arguments)
            if result.isError:
                raise FixtureError(f"MCP tool returned error for {tool}: {result.content}")
            text = getattr(result.content[0], "text", None)
            if not isinstance(text, str):
                raise FixtureError(f"MCP tool returned non-text content for {tool}")
            decoded = json.loads(text)
            if not isinstance(decoded, dict):
                raise FixtureError(f"MCP tool returned non-object JSON for {tool}")
            return cast(dict[str, Any], decoded)

    value = anyio.run(call)
    if tool in COMPARE_ENTRIES:
        # MCP returns native DeltaResult wire. Rehydrate only enough to build C4 for validation.
        result = _delta_result_from_wire(value)
        return Actual(value=value, c4_delta_result=as_c4_delta_result(result))
    return Actual(value=value)


def _delta_result_from_wire(wire: Mapping[str, Any]) -> DeltaResult:
    from aperture import AnchorViolation, DeltaStatus

    violations = [
        AnchorViolation(
            anchor_id=item["anchor_id"],
            kind=AnchorKind(item["kind"]),
            status=DeltaStatus(item["status"]),
            detail=item.get("detail"),
        )
        for item in wire.get("anchor_violations", [])
    ]
    return DeltaResult(
        status=DeltaStatus(wire["status"]),
        reason=wire.get("reason", ""),
        provider_family=wire.get("provider_family", "mock"),
        profile=wire.get("profile"),
        state_kind=wire.get("state_kind", "text"),
        anchor_violations=violations,
        event_id=wire.get("event_id"),
    )


# Anchor shape guard mirrors aperture.mcp_server._anchors_from_dicts; the illegal-kind
# rejection is grounded on Aperture's OWN AnchorKind enum (the symbol C-AC-4 cites).
_ANCHOR_ADMISSION_KEYS = {"kind", "id"}


def _admit_anchors(anchors: Any) -> list[dict[str, Any]]:
    """Reference of the access-layer anchor admission gate (C-AC-4).

    Mirrors ``aperture.mcp_server._anchors_from_dicts`` shape guards (non-object item, exact
    {kind,id} key set, non-empty string ``id``) and grounds the illegal-``kind`` rejection on
    Aperture's OWN ``AnchorKind(kind)`` enum — the exact symbol C-AC-4 cites, which raises
    ``ValueError`` for any free-form kind (the enum message embeds the rejected value, so the
    structured ``reason`` carries the bad kind). It is replicated here rather than imported
    because importing ``aperture.mcp_server`` pulls the optional ``mcp`` dependency; ``AnchorKind``
    itself is core (no optional dep), so the load-bearing admission is exercised without it.
    (The access layer's redundant ``kind not in {...}`` pre-check is intentionally dropped here
    so that ``AnchorKind``'s own ValueError — the cited rejection — is what surfaces.)

    Returns the accepted anchors as plain dicts. Raises ``ValueError`` for any input that the
    access layer rejects (non-object item, wrong key set, illegal kind, empty/non-string ``id``);
    the wrapping entry converts that documented input error into a structured value.
    """
    if anchors is None:
        return []
    if not isinstance(anchors, list):
        raise ValueError("anchors must be an array of objects with keys kind and id")
    parsed: list[dict[str, Any]] = []
    for index, item in enumerate(anchors):
        if not isinstance(item, dict):
            raise ValueError(f"anchors[{index}] must be an object with keys kind and id")
        if set(item) != _ANCHOR_ADMISSION_KEYS:
            raise ValueError(f"anchors[{index}] must contain exactly keys kind and id")
        kind = item["kind"]
        anchor_id = item["id"]
        if not isinstance(kind, str):
            raise ValueError(f"anchors[{index}].kind must be a string")
        if not isinstance(anchor_id, str) or anchor_id == "":
            raise ValueError(f"anchors[{index}].id must be a non-empty string")
        # AnchorKind(kind) is Aperture's OWN enum admission — the exact symbol C-AC-4 grounds
        # on (`AnchorKind(bad)` raises ValueError). Its message embeds the rejected kind value,
        # so the structured `reason` carries the bad kind for a fixture to assert against.
        admitted = Anchor(kind=AnchorKind(kind), id=anchor_id)
        parsed.append({"kind": admitted.kind.value, "id": admitted.id})
    return parsed


def _run_access_anchor_admission(payload: Mapping[str, Any]) -> Actual:
    """Exercise the access-layer anchor-kind admission as a VALUE-DOMAIN result (C-AC-4).

    "Rejection is a value, not an exception": the documented access-layer input error
    (``ValueError`` from ``AnchorKind`` / the admission gate) is caught and returned as
    ``{"rejected": True, "reason": ...}`` — generalizing the existing ``schema.validate``
    value-domain pattern to the anchor-kind rejection. When anchors are accepted, returns
    ``{"rejected": False, "anchors": [...]}`` so a fixture asserting ``/rejected == true``
    FAILS against a broken impl that silently accepts a free-form anchor (pins the
    "MUST NOT silently accept" limb). ONLY the specific expected ValueError is caught here;
    any other exception propagates to ``run_fixture`` -> FAIL (guards against masking real bugs,
    incl. "MUST NOT crash the server" being asserted as a clean rejection rather than a crash).
    """
    anchors = payload.get("anchors")
    try:
        admitted = _admit_anchors(anchors)
    except ValueError as exc:
        return Actual(value={"rejected": True, "reason": str(exc)})
    return Actual(value={"rejected": False, "anchors": admitted})


def _seq_clock(values: Sequence[str] | None = None) -> Callable[[], str]:
    if values:
        iterator = count()

        def tick() -> str:
            return values[min(next(iterator), len(values) - 1)]

        return tick
    counter = count(1)

    def _tick() -> str:
        n = next(counter)
        hh, rem = divmod(n, 3600)
        mm, ss = divmod(rem, 60)
        return f"2026-06-12T{hh:02d}:{mm:02d}:{ss:02d}+00:00"

    return _tick


def _signature(payload: Mapping[str, Any]) -> ContextSignature:
    state_kind = payload.get("state_kind", "text")
    context_key = payload.get("context_key")
    if not isinstance(state_kind, str):
        raise FixtureError("signature.state_kind must be a string")
    if context_key is not None and not isinstance(context_key, str):
        raise FixtureError("signature.context_key must be a string when present")
    return ContextSignature.of(state_kind, _anchors(payload.get("anchors")), context_key)


def _result_from_spec(spec: Any) -> DeltaResult:
    if isinstance(spec, dict) and "entry" in spec:
        entry = spec["entry"]
        if not isinstance(entry, str) or entry not in COMPARE_ENTRIES:
            raise FixtureError("delta_history result entry must be a compare entry")
        actual = _run_compare(entry, spec.get("input", {}))
        if not isinstance(actual.value, dict):
            raise FixtureError("compare entry returned non-object result")
        return _delta_result_from_wire(actual.value)
    if isinstance(spec, dict):
        return _delta_result_from_wire(spec)
    raise FixtureError("delta_history put.result must be a result object or compare spec")


def _record_to_dict(record: Any) -> dict[str, Any]:
    value = record.to_dict()
    if not isinstance(value, dict):
        raise FixtureError("record.to_dict() returned non-object")
    return cast(dict[str, Any], value)


def _run_delta_history(payload: Mapping[str, Any]) -> Actual:
    clock_values = payload.get("clock")
    if clock_values is not None and (
        not isinstance(clock_values, list) or not all(isinstance(v, str) for v in clock_values)
    ):
        raise FixtureError("input.clock must be an array of timestamp strings")
    store = DeltaHistoryStore(clock=_seq_clock(clock_values))
    retriever = DeltaHistoryRetriever(store)
    outputs: dict[str, Any] = {}
    last: Any = None
    operations = payload.get("operations", [])
    if not isinstance(operations, list):
        raise FixtureError("input.operations must be an array")

    for index, op in enumerate(operations):
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            raise FixtureError(f"input.operations[{index}] must have an op string")
        name = op["op"]
        if name == "put":
            result = _result_from_spec(op["result"])
            signature = _signature(op.get("signature", {}))
            agent_identity = op.get("agent_identity")
            if agent_identity is not None and not isinstance(agent_identity, str):
                raise FixtureError("put.agent_identity must be a string when present")
            last = store.put(result, signature, agent_identity=agent_identity)
        elif name == "tombstone":
            last = store.tombstone(_alias(op["record"], outputs), reason=op["reason"])
        elif name == "query":
            params = op.get("params", {})
            if not isinstance(params, dict):
                raise FixtureError("query.params must be an object")
            last = [_record_to_dict(record) for record in retriever.query(**params)]
        elif name == "similar_context":
            params = op.get("params", {})
            if not isinstance(params, dict):
                raise FixtureError("similar_context.params must be an object")
            signature = _signature(op.get("signature", {}))
            last = [
                _record_to_dict(record) for record in retriever.similar_context(signature, **params)
            ]
        elif name == "snapshot":
            last = store.snapshot()
        else:
            raise FixtureError(f"unsupported delta_history op: {name}")

        alias = op.get("as")
        if isinstance(alias, str):
            outputs[alias] = _normalize_output(last)

    return Actual(
        value={
            "last": _normalize_output(last),
            "outputs": outputs,
            "records": [
                _record_to_dict(record) for record in store.records(include_tombstoned=True)
            ],
        }
    )


def _run_schema_validate(payload: Mapping[str, Any], methodology_schema: dict[str, Any]) -> Actual:
    schema_ref = payload.get("schema_ref")
    if not isinstance(schema_ref, str):
        raise FixtureError("schema.validate requires input.schema_ref")
    if "instances" in payload:
        instances = payload["instances"]
        if not isinstance(instances, list):
            raise FixtureError("schema.validate input.instances must be an array")
        return Actual(
            value={
                "results": [
                    _schema_validation_result(instance, methodology_schema, schema_ref)
                    for instance in instances
                ]
            }
        )
    if "instance" not in payload:
        raise FixtureError("schema.validate requires input.instance or input.instances")
    return Actual(
        value=_schema_validation_result(payload.get("instance"), methodology_schema, schema_ref)
    )


def _schema_validation_result(
    instance: Any, methodology_schema: dict[str, Any], schema_ref: str
) -> dict[str, Any]:
    try:
        _validate_ref(instance, methodology_schema, schema_ref)
        return {"valid": True}
    except ValidationError as exc:
        return {"valid": False, "error": exc.message}


def _alias(value: Any, outputs: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        target = outputs[value[1:]]
        if isinstance(target, dict) and "record_id" in target:
            return target["record_id"]
        return target
    return value


def _normalize_output(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _run_entry(fixture: Mapping[str, Any], methodology_schema: dict[str, Any] | None) -> Actual:
    entry = fixture.get("entry", "compare")
    payload = fixture["input"]
    if not isinstance(entry, str) or not isinstance(payload, dict):
        raise FixtureError("fixture.entry must be a string and fixture.input must be an object")
    if entry in COMPARE_ENTRIES:
        return _run_compare(entry, payload)
    if entry in {"topology.analyze", "topology.metric"}:
        return _run_topology(entry, payload)
    if entry == "openai.tools":
        return _run_openai_tools(payload)
    if entry == "openai.tool_call":
        return _run_openai_tool_call(payload)
    if entry == "mcp.tool_call":
        return _run_mcp_tool_call(payload)
    if entry == "access.anchor_admission":
        return _run_access_anchor_admission(payload)
    if entry == "delta_history":
        return _run_delta_history(payload)
    if entry == "schema.validate":
        if methodology_schema is None:
            print(
                "  SKIP schema.validate — methodology schema not bundled",
                file=sys.stderr,
            )
            return Actual(value={"_skipped": True, "note": "methodology schema not bundled"})
        return _run_schema_validate(payload, methodology_schema)
    raise FixtureError(f"unsupported entry: {entry}")


def _assert_expected(
    actual: Actual,
    expected: Mapping[str, Any],
    methodology_schema: dict[str, Any] | None,
) -> list[str]:
    if isinstance(actual.value, dict) and actual.value.get("_skipped"):
        return []
    failures: list[str] = []
    value = actual.value

    if "output" in expected and value != expected["output"]:
        failures.append(f"output mismatch: expected {expected['output']!r}, got {value!r}")

    if isinstance(value, dict):
        failures.extend(_assert_status_fields(value, expected))
        failures.extend(_assert_anchor_violations(value, expected))
        failures.extend(_assert_topology(value, expected))
        failures.extend(_assert_keys(value, expected))

    failures.extend(_assert_tools(value, expected))
    failures.extend(_assert_path_assertions(value, expected))
    failures.extend(_assert_c4(actual, expected, methodology_schema))
    return failures


def _assert_status_fields(value: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in ("status", "provider_family", "profile", "state_kind", "event_id"):
        if key in expected and value.get(key) != expected[key]:
            failures.append(f"{key}: expected {expected[key]!r}, got {value.get(key)!r}")
    if expected.get("reason_required") is True and not str(value.get("reason", "")).strip():
        failures.append("expected non-empty reason")
    return failures


def _assert_anchor_violations(value: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    spec = expected.get("anchor_violations")
    if spec is None:
        return []
    if not isinstance(spec, dict):
        return ["expected.anchor_violations must be an object"]
    raw = value.get("anchor_violations", [])
    if not isinstance(raw, list):
        return ["actual anchor_violations is not an array"]
    failures: list[str] = []
    if "count" in spec and len(raw) != spec["count"]:
        failures.append(f"anchor_violations count: expected {spec['count']}, got {len(raw)}")
    for needle in spec.get("contains", []):
        if not isinstance(needle, dict):
            failures.append("anchor_violations.contains entries must be objects")
            continue
        if not any(_matches_partial(item, needle) for item in raw if isinstance(item, dict)):
            failures.append(f"anchor_violations missing partial match {needle!r}")
    for forbidden in spec.get("forbidden_keys", []):
        if any(isinstance(item, dict) and forbidden in item for item in raw):
            failures.append(f"anchor_violations must not contain key {forbidden!r}")
    return failures


def _assert_topology(value: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    spec = expected.get("topology")
    if spec is None:
        return []
    if not isinstance(spec, dict):
        return ["expected.topology must be an object"]
    failures: list[str] = []
    for key in ("cut_vertices", "supported_metrics"):
        if key in spec and value.get(key) != spec[key]:
            failures.append(f"{key}: expected {spec[key]!r}, got {value.get(key)!r}")
    for forbidden in spec.get("forbidden_keys", []):
        if forbidden in value:
            failures.append(f"topology result must not contain key {forbidden!r}")
    return failures


def _assert_keys(value: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if "contains_keys" in expected:
        missing = [key for key in expected["contains_keys"] if key not in value]
        if missing:
            failures.append(f"missing expected keys: {missing!r}")
    if "forbidden_keys" in expected:
        present = [key for key in expected["forbidden_keys"] if key in value]
        if present:
            failures.append(f"forbidden keys present: {present!r}")
    return failures


def _assert_tools(value: Any, expected: Mapping[str, Any]) -> list[str]:
    spec = expected.get("tools")
    if spec is None:
        return []
    if not isinstance(spec, dict):
        return ["expected.tools must be an object"]
    if not isinstance(value, list):
        return ["actual tools output is not an array"]
    names = {tool.get("function", {}).get("name") for tool in value if isinstance(tool, dict)}
    failures: list[str] = []
    if "names_exact" in spec and names != set(spec["names_exact"]):
        failures.append(
            f"tool names: expected {sorted(spec['names_exact'])!r}, got {sorted(names)!r}"
        )
    if "names_include" in spec:
        missing = set(spec["names_include"]) - names
        if missing:
            failures.append(f"missing tool names: {sorted(missing)!r}")
    return failures


def _assert_path_assertions(value: Any, expected: Mapping[str, Any]) -> list[str]:
    assertions = expected.get("assertions", [])
    if not isinstance(assertions, list):
        return ["expected.assertions must be an array"]
    failures: list[str] = []
    for assertion in assertions:
        if not isinstance(assertion, dict) or not isinstance(assertion.get("path"), str):
            failures.append("each assertion must be an object with a path string")
            continue
        path = assertion["path"]
        try:
            found = _json_pointer(value, path)
        except KeyError:
            if assertion.get("absent") is True:
                continue
            failures.append(f"path not found: {path}")
            continue
        if assertion.get("absent") is True:
            failures.append(f"path should be absent: {path}")
        if "equals" in assertion and found != assertion["equals"]:
            failures.append(f"{path}: expected {assertion['equals']!r}, got {found!r}")
        if assertion.get("non_empty") is True and not found:
            failures.append(f"{path}: expected non-empty value")
        if "contains" in assertion and assertion["contains"] not in found:
            failures.append(f"{path}: expected to contain {assertion['contains']!r}")
    return failures


def _assert_c4(
    actual: Actual,
    expected: Mapping[str, Any],
    methodology_schema: dict[str, Any] | None,
) -> list[str]:
    wire_spec = expected.get("wire", {})
    if wire_spec is None:
        wire_spec = {}
    if not isinstance(wire_spec, dict):
        return ["expected.wire must be an object"]
    validate_c4 = wire_spec.get("c4_delta_result_valid", actual.c4_delta_result is not None)
    if actual.c4_delta_result is None or validate_c4 is None:
        return []
    if methodology_schema is None:
        return []
    failures: list[str] = []
    try:
        _validate_ref(actual.c4_delta_result, methodology_schema, "#/$defs/C4_DeltaResult")
        valid = True
    except ValidationError as exc:
        valid = False
        validation_error = exc.message
    if validate_c4 is True and not valid:
        failures.append(f"C4_DeltaResult schema validation failed: {validation_error}")
    if validate_c4 is False and valid:
        failures.append("C4_DeltaResult schema validation unexpectedly passed")
    return failures


def _json_pointer(value: Any, path: str) -> Any:
    if path == "":
        return value
    if not path.startswith("/"):
        raise KeyError(path)
    current = value
    for raw_part in path.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _matches_partial(item: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(item.get(key) == value for key, value in expected.items())


def run_fixture(path: Path, methodology_schema: dict[str, Any] | None) -> CaseResult:
    try:
        fixture = _load_json(path)
        _validate_fixture_shape(fixture)
        actual = _run_entry(fixture, methodology_schema)
        failures = _assert_expected(actual, fixture["expected"], methodology_schema)
        return CaseResult(
            case=str(fixture["case"]),
            path=path,
            passed=not failures,
            failures=tuple(failures),
        )
    except Exception as exc:  # noqa: BLE001 - fixture runner must report per-case failure.
        return CaseResult(case=path.stem, path=path, passed=False, failures=(str(exc),))


def discover(fixtures_dir: Path) -> list[Path]:
    return sorted(fixtures_dir.glob("*.json"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR)
    parser.add_argument("--schema", type=Path, default=METHODOLOGY_SCHEMA)
    args = parser.parse_args(argv)

    methodology_schema = _load_methodology_schema(args.schema)

    paths = discover(args.fixtures_dir)
    if not paths:
        print(f"No JSON fixtures found under {args.fixtures_dir}")
        return 2

    results = [run_fixture(path, methodology_schema) for path in paths]
    for result in results:
        rel = result.path.relative_to(ROOT) if result.path.is_relative_to(ROOT) else result.path
        if result.passed:
            print(f"PASS {rel} ({result.case})")
        else:
            print(f"FAIL {rel} ({result.case})")
            for failure in result.failures:
                print(f"  - {failure}")
    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    print(f"{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
