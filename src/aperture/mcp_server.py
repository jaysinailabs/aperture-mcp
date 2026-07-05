"""Aperture MCP server — exposes self-consistency compare tools via FastMCP.

Requires the `mcp` package (`pip install mcp`).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from aperture import (
    Anchor,
    AnchorKind,
    __version__,
    compare,
    compare_commitment,
    compare_proposal,
    compare_stance,
)

_ANCHOR_KEYS = {"kind", "id"}
_ANCHOR_KIND_VALUES = {kind.value for kind in AnchorKind}

# Opt-in usage telemetry: when APERTURE_USAGE_LOG names a path, each compare call
# appends ONE metadata line there (tool, status, counts) — never decision text,
# anchor ids, or reasons. Used for dogfood signal from external consumers.
_USAGE_LOG_PATH = os.environ.get("APERTURE_USAGE_LOG")
# Optional provenance label: when APERTURE_USAGE_TAG is set, each logged line carries
# {"tag": <value>}, letting a consumer mark e.g. synthetic/simulated runs so they can be
# excluded from the organic signal. Unset → no tag (treated as organic by convention).
_USAGE_TAG = os.environ.get("APERTURE_USAGE_TAG")


def _log_usage(tool: str, n_anchors: int, result: dict[str, Any]) -> None:
    """Append one metadata-only usage line when APERTURE_USAGE_LOG is set.

    Records tool name, result status/provider/kind, and violation COUNTS only —
    no decision text, anchor ids, or reasons. Opt-in via env; any failure is
    swallowed so telemetry can never break a tool call. The single O_APPEND
    write is atomic, so concurrent server processes can share one log file.
    """
    path = _USAGE_LOG_PATH
    if not path:
        return
    try:
        violations = result.get("anchor_violations") or []
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": tool,
            "status": result.get("status"),
            "provider_family": result.get("provider_family"),
            "state_kind": result.get("state_kind"),
            "n_anchors": n_anchors,
            "n_violations": len(violations),
            "violation_statuses": [v.get("status") for v in violations],
        }
        if _USAGE_TAG:
            record["tag"] = _USAGE_TAG
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        return


# Internal opt-in feedback channel (flag-gated; OFF by default → hidden for public
# release). When APERTURE_FEEDBACK_LOG names a path, an extra `aperture_feedback` tool
# is exposed so a consuming agent can OPTIONALLY leave a message + usage scenario for the
# maintainers. The consumer controls 100% of the content; nothing is auto-scraped (no
# decision text / anchor ids / reasons attached). Unset → the tool is not registered.
_FEEDBACK_LOG_PATH = os.environ.get("APERTURE_FEEDBACK_LOG")


def _log_feedback(record: dict[str, Any]) -> None:
    """Append one consumer-authored feedback line when APERTURE_FEEDBACK_LOG is set.

    Carries only what the calling consumer explicitly passed (message / scenario /
    relates_to / consumer) + a timestamp. Opt-in (the consumer chooses to call the
    tool); any failure is swallowed. Atomic O_APPEND so concurrent servers can share
    one file.
    """
    path = _FEEDBACK_LOG_PATH
    if not path:
        return
    try:
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        return


try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise ImportError(
        "mcp is required for the Aperture MCP server. "
        "Install the mcp package to run the server: pip install mcp"
    ) from e


def _anchors_from_dicts(anchors: list[Any] | None) -> list[Anchor]:
    if anchors is None:
        return []
    parsed: list[Anchor] = []
    for index, item in enumerate(anchors):
        if not isinstance(item, dict):
            raise ValueError(f"anchors[{index}] must be an object with keys kind and id")
        keys = set(item)
        if keys != _ANCHOR_KEYS:
            raise ValueError(f"anchors[{index}] must contain exactly keys kind and id")
        kind = item["kind"]
        anchor_id = item["id"]
        if not isinstance(kind, str) or kind not in _ANCHOR_KIND_VALUES:
            raise ValueError(f"anchors[{index}].kind must be one of {sorted(_ANCHOR_KIND_VALUES)}")
        if not isinstance(anchor_id, str) or anchor_id == "":
            raise ValueError(f"anchors[{index}].id must be a non-empty string")
        parsed.append(Anchor(kind=AnchorKind(kind), id=anchor_id))
    return parsed


_SERVER_INSTRUCTIONS = """\
Aperture flags when a tracked commitment is dropped, a stance reversed, a
proposal weakened, or a named constraint violated — verbatim, between two text
states of the SAME decision (across turns, sessions, or agents). A signal, not
a judge: it surfaces candidate drift for you to check; it does NOT decide, rank,
or reliably find all drift.

When to use: you have an earlier state (state_a) and a later state (state_b) of
the same proposal / stance / commitment / plan and want to flag cases where a
commitment was silently dropped, a stance reversed, a proposal weakened, or a
named constraint violated — across turns, sessions, or agents. This is a
signal, not a judge: it surfaces candidate drift, it does not reliably find
all of it.

Anchors (the load-bearing rule): to track a specific item, pass
anchors=[{"kind": "constraint|goal|commitment|baseline", "id": "<token>"}].
The id is matched as a case-insensitive CONTIGUOUS SUBSTRING, so it MUST appear
verbatim in the state text — paraphrase, translation, or a comma in the middle
will NOT match. Keep ids short, same-language as the text, punctuation-free,
stable (e.g. `ci-gates-green`). Violation is DIRECTIONAL: compare and
compare_commitment flag an id present in state_a but missing from state_b;
compare_proposal / compare_stance flag an id missing from state_b. Each tool
checks only certain anchor kinds (see the tool descriptions) — other kinds are
silently ignored.

Known limits (do not over-trust): this is a substring+keyword heuristic, not a
semantic judge, and it fails in BOTH directions — it MISSES drift expressed by
paraphrase / modal / numeric / scope / negation when no tracked substring
changes (it flags only a fraction of true drift), and it FALSELY flags rewrites
/ translations where the anchor substring disappears but the meaning is
preserved. Treat any result as a signal to look closer, never a sole correctness
gate. A newly-adopted anchor (absent from state_a) is invisible to compare /
compare_commitment. compare_commitment cannot tell a fulfilled commitment from
an abandoned one.

Result: an 8-value status (ok / degraded / incomparable / domain_mismatch /
provider_unavailable / BLOCKED / DROPPED_SILENTLY / PAUSED) + per-anchor
violations + a reason. A diagnostic signal, not a verdict on which state is better.
"""


def build_server() -> FastMCP:
    mcp = FastMCP("aperture", instructions=_SERVER_INSTRUCTIONS)
    # FastMCP takes no version arg; without this the low-level server reports the
    # mcp SDK's version in the MCP `initialize` handshake (serverInfo.version) and
    # would drift with every SDK upgrade. Pin it to Aperture's own version.
    mcp._mcp_server.version = __version__

    @mcp.tool(description="Liveness check; returns status + name + version.")
    def health() -> dict[str, Any]:
        return {"status": "ok", "name": "aperture", "version": __version__}

    @mcp.tool(
        name="compare",
        description=(
            "Surface drift between two text states of the SAME decision object "
            "(state_a = earlier, state_b = later). Pass anchors=[{kind, id}] to "
            "track specific constraints/goals/commitments/baselines — an id present "
            "in state_a but missing from state_b reads as violated (directional; an "
            "id absent from state_a does not trigger), and the id must appear VERBATIM "
            "(case-insensitive substring) to match — so RE-STATE tracked anchors verbatim in "
            "state_b (a constraint you kept but did not re-state still reads as violated). "
            "Returns an 8-value status (only 4 are emitted on this surface) + violations + "
            "reason. Heuristic, not a semantic judge; a drift signal, not a sole gate."
        ),
    )
    def _compare(
        state_a: str,
        state_b: str,
        anchors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed = _anchors_from_dicts(anchors)
        result = compare(state_a, state_b, anchors=parsed).to_dict()
        _log_usage("compare", len(parsed), result)
        return result

    @mcp.tool(
        name="compare_proposal",
        description=(
            "compare specialized for a PROPOSAL: also flags strength regression "
            "(strong→weak wording) as degraded — but ONLY for a narrow FIXED keyword set "
            "(English modals + 必须/务必/应当/确保→应该/也许); most reworded/softened wording "
            "falls outside this list and is MISSED. Checks ONLY constraint/goal anchors "
            "(other kinds silently ignored) for presence in state_b."
        ),
    )
    def _compare_proposal(
        state_a: str,
        state_b: str,
        anchors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed = _anchors_from_dicts(anchors)
        result = compare_proposal(state_a, state_b, anchors=parsed).to_dict()
        _log_usage("compare_proposal", len(parsed), result)
        return result

    @mcp.tool(
        name="compare_stance",
        description=(
            "compare specialized for a STANCE: also flags polarity reversal "
            "(support↔oppose) as degraded. Checks ONLY goal/baseline anchors "
            "(other kinds silently ignored) in state_b."
        ),
    )
    def _compare_stance(
        state_a: str,
        state_b: str,
        anchors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed = _anchors_from_dicts(anchors)
        result = compare_stance(state_a, state_b, anchors=parsed).to_dict()
        _log_usage("compare_stance", len(parsed), result)
        return result

    @mcp.tool(
        name="compare_commitment",
        description=(
            "compare specialized for a COMMITMENT: checks ONLY commitment anchors; "
            "flags a promise present in state_a but gone from state_b as "
            "DROPPED_SILENTLY. Caveat: cannot distinguish a FULFILLED commitment "
            "from an abandoned one — that disposition is the caller's to decide."
        ),
    )
    def _compare_commitment(
        state_a: str,
        state_b: str,
        anchors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed = _anchors_from_dicts(anchors)
        result = compare_commitment(state_a, state_b, anchors=parsed).to_dict()
        _log_usage("compare_commitment", len(parsed), result)
        return result

    # Internal feedback channel — registered ONLY when APERTURE_FEEDBACK_LOG is set
    # (OFF by default → hidden for public release). Opt-in, consumer-controlled content.
    if _FEEDBACK_LOG_PATH:

        @mcp.tool(
            name="aperture_feedback",
            description=(
                "OPTIONAL: leave a short message / usage-scenario for Aperture's "
                "maintainers (internal feedback channel). Calling this is opt-in and "
                "writes ONLY what you pass here to a local maintainer feedback log — no "
                "decision text, anchors, or compare results are auto-attached; you control "
                "the content. Use it to report friction, a surprising result, or the "
                "scenario you were in (e.g. a reworded-but-held commitment)."
            ),
        )
        def aperture_feedback(
            message: str,
            scenario: str | None = None,
            relates_to: str | None = None,
            consumer: str | None = None,
        ) -> dict[str, Any]:
            record: dict[str, Any] = {
                "ts": datetime.now(UTC).isoformat(),
                "message": message,
            }
            if scenario is not None:
                record["scenario"] = scenario
            if relates_to is not None:
                record["relates_to"] = relates_to
            if consumer is not None:
                record["consumer"] = consumer
            _log_feedback(record)
            return {"status": "ok", "recorded": True}

    return mcp


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point: build the server and serve over stdio.

    Wired as the ``aperture-mcp`` console script via ``[project.scripts]`` in
    ``pyproject.toml``. ``FastMCP.run()`` defaults to the stdio transport,
    matching the published ``server.json`` transport. ``-h``/``--help`` and
    ``--version`` print and exit; any other invocation serves over stdio.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if "-h" in args or "--help" in args:
        print(
            "aperture-mcp — a commitment tripwire for AI-edited decision docs.\n"
            "Speaks the Model Context Protocol over stdio; launch it from an MCP\n"
            'client (e.g. {"command": "aperture-mcp"}), not interactively.\n'
            "\n"
            "  -h, --help     show this message and exit\n"
            "      --version  print version and exit"
        )
        return
    if "--version" in args:
        print(f"aperture-mcp {__version__}")
        return
    build_server().run()


if __name__ == "__main__":
    main()
