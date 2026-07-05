# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the package follows
[Semantic Versioning](https://semver.org) (see [VERSIONING.md](./VERSIONING.md)).

## [Unreleased]

## [0.2.0] - 2026-07-05

Aperture is now a commitment tripwire with **multiple surfaces** — a deterministic
git preflight, a CLI, and the MCP server — not just an MCP tool. The MCP server is
one adapter (for an agent to call mid-task); the git hook is the tripwire's most
reliable form, because it fires on the commit event itself with no model in the loop.

The frozen **v0.2** `compare` contract is unchanged; everything here is application-layer.

### Added
- **`aperture check` CLI** — a deterministic, LLM-free commitment tripwire for git.
  Reads an `.aperture.toml` watchlist and flags any watched commitment that vanished
  **verbatim** between two git states (default `HEAD` vs the working tree; `--staged`
  for the index; `--ref-a/--ref-b` for CI). Exits non-zero to block a commit by default
  (`fail_on_drop`); `--warn-only` never blocks. Stdlib-only, offline, zero new runtime
  dependencies. Same honest blind spot as the rest of Aperture — it sees only verbatim
  disappearance, and says so.
- **`.aperture.toml`** config convention (per-file commitment watchlists).
- **Git pre-commit hook wiring**: a `.pre-commit-hooks.yaml` for the pre-commit.com
  framework, plus a standalone `examples/hooks/pre-commit` and install notes.
- **GitHub Action** example (`examples/github-action/aperture-check.yml`) that runs
  `aperture check` on pull requests.

### Notes
- `pip install aperture-mcp` now also installs the `aperture` console script (CLI + git
  hook) alongside the `aperture-mcp` server. The `-mcp` suffix is a historical
  package-name artifact; the product is **Aperture**.
- Privacy is unchanged and, if anything, more apt: the CLI and git hook run fully local
  and offline; your decision text never leaves your process.

## [0.1.0] - 2026-07-02

Initial public preview.

### Added
- `aperture` Python library: `compare`, `compare_commitment`, `compare_proposal`, `compare_stance`,
  over the frozen **v0.2** `DeltaResult` contract (8-value status, anchors, anchor violations).
- `aperture-mcp` MCP server (stdio) exposing the compare tools + a `health` check.
- `examples/git_decision_drift/`: a commitment tripwire over the version history of a decision
  document, runnable against checked-in fixtures.
- Honest, measured per-family limits (recall/precision) published alongside the tool rather than a
  single aggregate score.

### Known limits
- Matches commitments as case-insensitive contiguous substrings: **misses** reworded / softened /
  paraphrased / numerically-changed commitments; **declines/abstains** on **translated** ones (returns
  `degraded`, false-positive rate 0); still **false-flags** **reformatted** ones (same script).
  See the limits table in the [README](./README.md).
