"""Aperture command-line surface — the commitment tripwire as a git preflight.

``aperture check`` is a DETERMINISTIC, LLM-free git preflight. It reads a
``.aperture.toml`` watchlist of commitments you care about, then runs the FROZEN
``compare_commitment`` engine over two text states of each watched file (by default
``HEAD`` vs the working tree) and surfaces every watched commitment whose verbatim
text DISAPPEARED. Wired as a pre-commit hook it fires on the commit event itself.

It is a **signal, not a judge**. It sees only VERBATIM disappearance of a watched
substring — it is blind to softening / paraphrase / rewrite (a reworded commitment
loses its token and reads as dropped; a real weakening that keeps the token is
missed). A surfaced drop is a prompt to look, never a verdict that something is wrong.

Zero runtime dependencies beyond the stdlib (argparse + tomllib + subprocess) and the
frozen ``aperture`` core. Nothing here touches the contract or adds a status.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from aperture import Anchor, AnchorKind, DeltaStatus, compare_commitment

CONFIG_NAME = ".aperture.toml"


@dataclass(frozen=True)
class Drop:
    """One watched commitment that vanished verbatim between the two states."""

    path: str
    commitment: str


@dataclass(frozen=True)
class WatchEntry:
    path: str
    commitments: list[str]


# --------------------------------------------------------------------------- git


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    # Explicit UTF-8: git emits raw blob bytes regardless of locale. Left to the
    # locale codec (e.g. GBK on Chinese Windows), a decode failure happens inside
    # subprocess's reader thread and surfaces as stdout=None with returncode 0 —
    # indistinguishable from "path absent at this ref", which fails open.
    # errors="replace" keeps a genuinely non-UTF-8 blob from re-raising in that
    # same thread; its mangled text is then caught by the UNTRACKABLE guard.
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _repo_root(start: str) -> str | None:
    """Absolute path of the git work-tree root containing ``start``, or None."""
    proc = _git(start, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _ref_exists(repo: str, ref: str) -> bool:
    """True if ``ref`` resolves to a commit in ``repo``. Used to distinguish a
    genuinely-missing ref (invalid / not fetched in a shallow clone -> must ERROR,
    never fail open) from a path merely absent at a valid ref (a new file)."""
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def _git_show(repo: str, spec: str) -> str | None:
    """Return the blob text for a ``git show`` spec (e.g. ``HEAD:path`` or ``:path``),
    or None if that path is absent from the given ref/index (a new file)."""
    proc = _git(repo, "show", spec)
    if proc.returncode != 0:
        return None
    return proc.stdout


def _before_text(repo: str, ref_a: str, path: str) -> str:
    """The earlier state: file at ``ref_a`` (default HEAD). Absent -> empty (new file)."""
    text = _git_show(repo, f"{ref_a}:{path}")
    return text if text is not None else ""


def _after_text(repo: str, ref_b: str | None, staged: bool, path: str) -> str:
    """The later state. Precedence: explicit ``--ref-b`` > ``--staged`` index blob >
    working-tree file. A missing path yields empty text (treated as fully removed)."""
    if ref_b is not None:
        text = _git_show(repo, f"{ref_b}:{path}")
        return text if text is not None else ""
    if staged:
        text = _git_show(repo, f":{path}")
        return text if text is not None else ""
    try:
        return (Path(repo) / path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _after_label(ref_b: str | None, staged: bool) -> str:
    if ref_b is not None:
        return ref_b
    return "staged" if staged else "working tree"


# ------------------------------------------------------------------------- config


def _load_config(config_path: Path) -> tuple[bool, list[WatchEntry]]:
    """Parse ``.aperture.toml`` -> (fail_on_drop, watch entries). Malformed watch
    entries (missing path / commitments) are skipped with a warning, not fatal."""
    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    fail_on_drop = bool(data.get("fail_on_drop", True))
    entries: list[WatchEntry] = []
    for raw in data.get("watch", []):
        if not isinstance(raw, dict):
            print(f"  (skipping malformed [[watch]] entry: {raw!r})", file=sys.stderr)
            continue
        path = raw.get("path")
        commitments = raw.get("commitments")
        if not isinstance(path, str) or not path:
            print(f"  (skipping [[watch]] entry with no path: {raw!r})", file=sys.stderr)
            continue
        if not isinstance(commitments, list) or not all(isinstance(c, str) for c in commitments):
            print(
                f"  (skipping watch '{path}': commitments must be a list of strings)",
                file=sys.stderr,
            )
            continue
        if commitments:
            entries.append(WatchEntry(path=path, commitments=list(commitments)))
    return fail_on_drop, entries


# --------------------------------------------------------------------------- core


def _dropped_for_entry(before: str, after: str, commitments: list[str]) -> list[str]:
    """Run the frozen commitment engine once for the file; return the watched
    commitments (in listed order) that dropped silently between the two states."""
    result = compare_commitment(
        state_a=before,
        state_b=after,
        anchors=[Anchor(kind=AnchorKind.COMMITMENT, id=c) for c in commitments],
    )
    dropped_ids = {
        v.anchor_id for v in result.anchor_violations if v.status == DeltaStatus.DROPPED_SILENTLY
    }
    return [c for c in commitments if c in dropped_ids]


# --------------------------------------------------------------------------- check


def _cmd_check(args: argparse.Namespace) -> int:
    repo = _repo_root(".")
    if repo is None:
        print("Aperture · commitment tripwire")
        print("  not inside a git repository — nothing to check.")
        return 0

    config_path = Path(args.config).resolve() if args.config else Path(repo) / CONFIG_NAME
    if not config_path.is_file():
        print("Aperture · commitment tripwire")
        print(f"  no {CONFIG_NAME} found; nothing to watch.")
        return 0

    fail_on_drop, entries = _load_config(config_path)
    ref_a: str = args.ref_a or "HEAD"
    ref_b: str | None = args.ref_b

    # Validate EXPLICIT refs so an invalid / unfetched ref ERRORS (fail closed) rather
    # than silently becoming empty text (which would fail open on a shallow CI clone).
    # Default HEAD is exempt: an unborn HEAD (initial commit) legitimately has no prior
    # state, so its `git show` miss => empty before-text is correct, not an error.
    for flag, ref in (("--ref-a", args.ref_a), ("--ref-b", args.ref_b)):
        if ref is not None and not _ref_exists(repo, ref):
            print("Aperture · commitment tripwire")
            print(
                f"  error: {flag} ref {ref!r} not found in this repository. "
                "If this is a shallow clone (e.g. CI), fetch it first — "
                "`git fetch --unshallow` or actions/checkout with `fetch-depth: 0`."
            )
            return 2

    a_label = ref_a
    b_label = _after_label(ref_b, args.staged)

    drops: list[Drop] = []
    untrackable: list[Drop] = []
    watched_count = 0
    for entry in entries:
        watched_count += len(entry.commitments)
        before = _before_text(repo, ref_a, entry.path)
        after = _after_text(repo, ref_b, args.staged, entry.path)
        for commitment in _dropped_for_entry(before, after, entry.commitments):
            drops.append(Drop(path=entry.path, commitment=commitment))
        # Fail closed on commitments the check cannot actually see: watched text
        # found in NEITHER state means the watchlist is not guarding it (wrong
        # [[watch]] path, misquoted wording, non-UTF-8 file). Absent-from-before
        # but present-in-after stays legal — a newly adopted commitment landing
        # in the same change as its watch entry. Same match rule as the engine:
        # case-insensitive contiguous substring.
        for commitment in entry.commitments:
            needle = commitment.lower()
            if needle not in before.lower() and needle not in after.lower():
                untrackable.append(Drop(path=entry.path, commitment=commitment))

    print("Aperture · commitment tripwire")
    if not drops and not untrackable:
        print(
            f"  all {watched_count} watched commitment(s) across {len(entries)} file(s) intact "
            f"({a_label} -> {b_label})."
        )
        return 0

    for drop in drops:
        print(f'  {drop.path}  commitment "{drop.commitment}"  DROPPED  ({a_label} -> {b_label})')
    for miss in untrackable:
        print(
            f'  {miss.path}  commitment "{miss.commitment}"  UNTRACKABLE  '
            f"(found in neither {a_label} nor {b_label})"
        )
    if drops:
        n = len(drops)
        noun = "commitment" if n == 1 else "commitments"
        print(
            f"{n} watched {noun} vanished verbatim. "
            "A signal, not a verdict — confirm it was intended."
        )
        print(
            "(Aperture is blind to softening/paraphrase; it only sees verbatim disappearance. "
            "Bypass: git commit --no-verify)"
        )
    if untrackable:
        n = len(untrackable)
        noun = "commitment" if n == 1 else "commitments"
        print(
            f"{n} watched {noun} found in neither state — the watchlist is NOT guarding "
            "them. Check the [[watch]] path, the exact wording, and that the file is UTF-8."
        )

    blocking = fail_on_drop and not args.warn_only
    if not blocking:
        return 0
    return 1 if drops else 2


# --------------------------------------------------------------------------- argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aperture",
        description="Aperture — deterministic, LLM-free commitment-drift tripwire for git.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check",
        help="flag watched commitments that vanished verbatim between two git states",
        description=(
            "Deterministic commitment tripwire. Reads .aperture.toml and flags any watched "
            "commitment whose verbatim text disappeared between two states (default: HEAD -> "
            "working tree). A signal, not a judge — blind to paraphrase; catches only verbatim "
            "disappearance."
        ),
    )
    check.add_argument(
        "--config",
        help=f"path to the {CONFIG_NAME} config (default: {CONFIG_NAME} at the git repo root)",
    )
    check.add_argument(
        "--staged",
        action="store_true",
        help="compare against the STAGED (index) blob instead of the working tree",
    )
    check.add_argument(
        "--ref-a",
        help="earlier git ref for the BEFORE state (default: HEAD)",
    )
    check.add_argument(
        "--ref-b",
        help="later git ref for the AFTER state (default: working tree; or staged with --staged)",
    )
    check.add_argument(
        "--warn-only",
        action="store_true",
        help="always exit 0 (still prints drops) — overrides config fail_on_drop",
    )
    check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
