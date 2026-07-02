"""Aperture OpenAI tool/function-calling schema — access-layer artifact.

Mirrors the same compare contract exposed by the MCP server (`mcp_server.py`):
the self-consistency `compare` family plus a `health` probe, expressed as OpenAI
function-calling tool definitions so an AI can reach Aperture through the OpenAI
tool/function schema as well as through MCP.

Minimal access-layer artifact: it declares the call surface only. It adds no new
comparison logic, is not production-ready, and is not empirically validated. The
`kind` enum is derived from `AnchorKind` so the two access layers cannot drift.
"""

from __future__ import annotations

from typing import Any

from aperture import AnchorKind

# Derived from the canonical enum so this schema cannot drift from the protocol.
_ANCHOR_KINDS: list[str] = [k.value for k in AnchorKind]

# (name, description) kept in lockstep with the mcp_server.py tool descriptions.
_COMPARE_TOOLS: tuple[tuple[str, str], ...] = (
    ("compare", "Compare two states for self-consistency"),
    (
        "compare_proposal",
        "Compare proposal states; flags strong→weak wording regression as a signal",
    ),
    (
        "compare_stance",
        "Compare stance states; flags support↔oppose polarity reversal as a signal",
    ),
    (
        "compare_commitment",
        "Compare commitment states; surfaces an anchor present in state_a but "
        "missing from state_b as a silent-drop signal",
    ),
)


def _compare_parameters() -> dict[str, Any]:
    """JSON Schema for the shared compare(state_a, state_b, anchors?) contract."""
    return {
        "type": "object",
        "properties": {
            "state_a": {"type": "string", "description": "Earlier state text."},
            "state_b": {
                "type": "string",
                "description": "Later state text to compare against state_a.",
            },
            "anchors": {
                "type": "array",
                "description": "Optional anchors to check across the two states.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": _ANCHOR_KINDS},
                        "id": {"type": "string"},
                    },
                    "required": ["kind", "id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["state_a", "state_b"],
        "additionalProperties": False,
    }


def _function_tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def build_openai_tools() -> list[dict[str, Any]]:
    """Return Aperture's compare contract as OpenAI function-calling tool schemas."""
    tools: list[dict[str, Any]] = [
        _function_tool(
            "health",
            "Check Aperture service health",
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
    ]
    tools.extend(
        _function_tool(name, description, _compare_parameters())
        for name, description in _COMPARE_TOOLS
    )
    return tools
