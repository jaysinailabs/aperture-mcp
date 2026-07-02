"""Commitment tripwire over the version history of a decision document.

Application-layer example over the frozen ``compare`` primitive — it changes no
contract and adds no new status. You give it two text states of the same decision
(an earlier one and a later one) plus a WATCHLIST of commitments you care about; it
reports which watched commitments disappeared, word-for-word, between the versions.

It is a **signal, not a judge**, and a heuristic with documented blind spots:
  - it MISSES a commitment that was reworded / softened / paraphrased (the text still
    "matches" by substring, so it looks like it held);
  - it DECLINES/abstains on a commitment that was merely translated (it can't compare
    verbatim across scripts, so it returns ``degraded`` rather than false-flag);
  - it still FALSE-FLAGS a commitment that was merely reformatted (same script, words
    rearranged — the string changed, the meaning didn't).
A tripped wire means "look here," never "this is wrong" — whether a disappearance was
intended is for a human to decide.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from aperture import Anchor, AnchorKind, compare


@dataclass(frozen=True)
class WatchResult:
    """One watched commitment's fate between two versions of a decision document."""

    commitment: str
    in_a: bool  # appears verbatim in the earlier version
    in_b: bool  # appears verbatim in the later version
    tripped: bool  # present in A, gone from B


def decision_drift(state_a: str, state_b: str, watchlist: list[str]) -> list[WatchResult]:
    """For each watched commitment, report whether it disappeared verbatim from
    ``state_a`` (earlier) to ``state_b`` (later), using the frozen compare primitive.

    A watchlist entry is a short, punctuation-free, same-language token that must
    appear VERBATIM to be tracked (the anchor is a case-insensitive contiguous substring).
    """
    results: list[WatchResult] = []
    for token in watchlist:
        result = compare(state_a, state_b, anchors=[Anchor(kind=AnchorKind.COMMITMENT, id=token)])
        tripped = any(v.anchor_id == token for v in result.anchor_violations)
        results.append(
            WatchResult(
                commitment=token,
                in_a=token in state_a,
                in_b=token in state_b,
                tripped=tripped,
            )
        )
    return results


def _git_show(repo: str, ref: str, path: str) -> str:
    """Return the text of ``path`` as of ``ref`` in the git repo at ``repo``."""
    completed = subprocess.run(
        ["git", "-C", repo, "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def decision_drift_from_git(
    repo: str, path: str, ref_a: str, ref_b: str, watchlist: list[str]
) -> list[WatchResult]:
    """Extract two versions of ``path`` from a live git repo (``ref_a`` earlier,
    ``ref_b`` later) and run :func:`decision_drift` on them. Use this on your own
    versioned decision docs: e.g. ref_a="v1.0", ref_b="HEAD"."""
    return decision_drift(_git_show(repo, ref_a, path), _git_show(repo, ref_b, path), watchlist)


def _format(results: list[WatchResult]) -> str:
    lines = []
    for r in results:
        mark = "TRIPPED " if r.tripped else " held  "
        lines.append(f"  [{mark}] {r.commitment!r:<28} (in_before={r.in_a}, in_after={r.in_b})")
    return "\n".join(lines)


if __name__ == "__main__":
    # Runs offline against the checked-in fixtures, so it works in a fresh clone with
    # no setup. The fixtures are a tiny ADR before/after where an agent's tidy-up
    # quietly dropped one of two release commitments.
    import pathlib

    here = pathlib.Path(__file__).parent
    before = (here / "fixtures" / "decision_before.md").read_text(encoding="utf-8")
    after = (here / "fixtures" / "decision_after.md").read_text(encoding="utf-8")
    watchlist = ["ci-gates-green", "data-never-leaves-device"]
    results = decision_drift(before, after, watchlist)

    print("Aperture MCP · commitment tripwire — a fixture/sample decision-doc edit\n")
    print(_format(results))
    print()
    print("  One watched commitment vanished between the two versions; one held.")
    print("  Aperture MCP makes the disappearance visible — you decide whether it was intended.")

    by_token = {r.commitment: r for r in results}
    assert by_token["ci-gates-green"].tripped is True
    assert by_token["data-never-leaves-device"].tripped is False
