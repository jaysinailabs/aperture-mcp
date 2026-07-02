# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the package follows
[Semantic Versioning](https://semver.org) (see [VERSIONING.md](./VERSIONING.md)).

## [Unreleased]

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
