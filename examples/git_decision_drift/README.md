# Commitment tripwire over a decision document's history

A thin, read-only example over the frozen `compare` primitive. You give it two versions of a
decision document plus a **watchlist** of commitments; it reports which ones disappeared,
**word for word**, between the versions — across commits, sessions, or authors.

> **A signal, not a judge.** It trips; you investigate. `compare` is unchanged — this adds no
> contract and no new status.

## Run it (offline)

First install the package (it brings the `aperture` library):

```sh
pip install aperture-mcp
```

Then run the example — offline, no API keys, against the checked-in fixtures:

```sh
python3 git_decision_drift.py
```

It runs against the checked-in fixtures in [`fixtures/`](./fixtures) — a tiny ADR before/after where
an agent's tidy-up quietly dropped one of two release commitments:

```text
  [TRIPPED ] 'ci-gates-green'             (in_before=True, in_after=False)
  [ held  ] 'data-never-leaves-device'   (in_before=True, in_after=True)
```

`ci-gates-green` was present in the earlier version and is gone from the later one → the wire trips.
`data-never-leaves-device` survived in both → it stays quiet.

## Use it on your own repo

```python
from git_decision_drift import decision_drift_from_git

for r in decision_drift_from_git(
    repo=".",
    path="docs/adr/ADR-007.md",
    ref_a="v1.0",          # the earlier version
    ref_b="HEAD",          # the later version
    watchlist=["ci-gates-green", "no-friday-deploy", "data-never-leaves-device"],
):
    print(r)
```

## The honest limits (same as the project's)

- **Verbatim only.** A commitment that was *reworded / softened* (e.g. “must” → “should”) is
  **missed** — the substring still matches. A commitment that was *translated* makes it
  **decline/abstain** (it returns `degraded`, not a false flag, since it can't compare verbatim across
  scripts). A commitment that was *reformatted* (same script, words rearranged) is still
  **false-flagged** as dropped.
- **A trip is not a verdict.** The disappearance may be a deliberate scope cut or real silent drift;
  a human decides — Aperture MCP surfaces it, it does not adjudicate.

Pick watchlist tokens that are short, punctuation-free, same-language as the doc, and stable.
