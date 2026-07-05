<!-- mcp-name: io.github.jaysinailabs/aperture-mcp -->

<div align="center">

# Aperture

### A commitment tripwire &nbsp;·&nbsp; git hook · CI · CLI · MCP

**Did an agent quietly drop a commitment from your spec — and no one noticed?**

[![PyPI](https://img.shields.io/badge/pypi-aperture--mcp-blue)](https://pypi.org/project/aperture-mcp/) [![MCP](https://img.shields.io/badge/MCP-server-purple)](https://modelcontextprotocol.io) [![License](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE) [![status](https://img.shields.io/badge/status-early%2Fpre--1.0-orange)](./VERSIONING.md)

**English** · [简体中文](./README.zh-CN.md)

</div>

AI agents now rewrite the documents that govern your work — specs, plans, ADRs, charters,
`AGENTS.md` files. Somewhere in the edit, a constraint you set earlier can quietly disappear.

**Aperture is a *commitment tripwire*.** You name the commitments you care about; it flags —
**word for word** — when one of them vanishes between two versions of a decision document.

Catching *"a commitment silently vanished"* is a **tripwire** job: it should fire on an event,
deterministically, without asking permission. So Aperture ships that check on the surface that fits
it best first — a **git pre-commit hook / CI check** that runs with **no LLM, offline** — and also as
a **CLI** and an **MCP server** for agents to call mid-task. MCP is one adapter, not the whole
product.

> **A signal, not a judge.** It trips; *you* investigate.
> Opt-in · runs locally · never trains on your data.

---

## What it is (and what it is not)

Aperture compares **two text states of the same decision** — an earlier version and a later one — and
surfaces a narrow, specific kind of **decision drift**: when a **tracked commitment’s exact text
disappeared**. One engine, several surfaces:

- **git pre-commit hook / CI check** — the deterministic form. Fires on the commit / PR event with no
  model in the loop, and blocks (or warns) automatically.
- **`aperture check` CLI** — run the same check by hand between any two git states.
- **MCP server** — so an agent can call the check while it edits (weaker as a tripwire, since it only
  runs if the agent *chooses* to call it — but useful mid-task).

What the engine does and doesn’t do:

- ✅ **It does:** flag when a commitment you listed *verbatim* is present in version A and gone
  from version B — across commits, sessions, or authors. It returns a structured, comparable
  result with **its own blind spots written on the label**.
- ❌ **It does *not*:** understand meaning. It matches text as a case-insensitive substring, so it
  **misses** a commitment that was *reworded / softened / paraphrased* (it looks dropped-free even
  though the promise weakened); it **declines/abstains** on a commitment that was merely *translated*
  (it can’t compare verbatim across scripts, so it returns `degraded` rather than false-flag); and it
  can still **false-flag** a commitment that was merely *reformatted* (the words moved, the meaning
  didn’t). It does not rank options, score quality, or tell you a change was *wrong*. **That judgment
  stays with you.** Moving to the deterministic git-hook makes the check *fire reliably* — it does
  **not** widen what it can see. Same narrow, verbatim signal.

If you want one sentence: **Aperture is `grep` for vanished commitments, wired to fire on commit —
and honest enough to admit what it can’t see.**

---

## Quickstart (≈2 minutes)

```sh
pip install aperture-mcp   # installs the `aperture` CLI + the MCP server (wire the CLI as a git hook — see below)
```

> The PyPI package is named **`aperture-mcp`** because the bare name `aperture` was already taken on
> PyPI. The `-mcp` suffix is a historical package-name artifact — the **product is Aperture**, and
> MCP is only one of its surfaces. One `pip install` gives you all three below.

### 1. The deterministic tripwire — git pre-commit hook / CI (no LLM, offline)

Create a `.aperture.toml` — a watchlist of the commitments that must not silently vanish, per file:

```toml
fail_on_drop = true

[[watch]]
path = "CHARTER.md"
commitments = ["never train on your data", "data stays on the device"]
```

`aperture check` compares two git states and flags any watched commitment that disappeared
**verbatim**:

```sh
aperture check                                    # HEAD vs working tree (default)
aperture check --staged                           # HEAD vs the staged index — for a pre-commit hook
aperture check --ref-a origin/main --ref-b HEAD   # any two refs — for CI on a PR
```

Exit code **1** blocks the commit when a watched commitment dropped (the default);
`--warn-only` prints the finding but never blocks. It’s stdlib-only, makes no network calls, and runs
no model.

Wire it as a **pre-commit hook** — either through the [pre-commit](https://pre-commit.com) framework
(uses this repo’s `.pre-commit-hooks.yaml`):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/jaysinailabs/aperture-mcp
    rev: v0.2.0
    hooks:
      - id: aperture-commitment-drift
```

…or as a standalone `.git/hooks/pre-commit`:

```sh
#!/bin/sh
exec aperture check --staged
```

…or run it in **CI** as a GitHub Action on every PR (needs `fetch-depth: 0` so both
sides are available — see [`examples/github-action/aperture-check.yml`](./examples/github-action/aperture-check.yml)):

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: pip install aperture-mcp
- run: aperture check --ref-a ${{ github.event.pull_request.base.sha }} --ref-b ${{ github.sha }}
```

> Kick the tires first with the bundled fixture (clone the repo): it trips on a dropped commitment
> against checked-in before/after docs, no setup, fully offline —
> `python3 examples/git_decision_drift/git_decision_drift.py`.

### 2. Mid-task, from an agent — the MCP server

The same check, callable by an agent while it edits. (An MCP tool only fires if the agent *chooses*
to call it — a weaker delivery for a tripwire than the git-hook, but handy mid-task.)

```jsonc
{
  "mcpServers": {
    "aperture-mcp": { "command": "aperture-mcp" }
  }
}
```

> Prefer zero-install? Point the client at `uvx` instead:
> `{ "command": "uvx", "args": ["aperture-mcp"] }`.

### 3. Or from your own Python

```python
from aperture import compare, Anchor, AnchorKind

result = compare(
    state_a="We commit to: ci-gates-green before release; data-never-leaves-device.",
    state_b="We commit to: data-never-leaves-device.",
    anchors=[Anchor(kind=AnchorKind.COMMITMENT, id="ci-gates-green")],
)
print(result.status)            # DROPPED_SILENTLY
print(result.anchor_violations) # the commitment that vanished
```

---

## A scene you’ll recognize

On a long task, your agent keeps rewriting the doc it works from — a plan, a spec — across sessions
and edits. And every so often, a line that mattered just… vanishes.

*“Always ask before you delete anything.”* Gone.
*“User data never leaves the device.”* Gone.
*“The free tier stays free.”* Gone.

Nobody meant to drop them; nobody reads all 400 lines of the diff.

Aperture watches the exact lines you name. Put it on the commit — a hook that fires before the drop
lands — and it won’t try to understand the doc or judge it; it just tells you which promise was there,
word for word, and now isn’t. A tripwire, not a judge — and honest about the rest: soften a line,
reword it, or change a number instead of deleting it, and it’ll slip past. Better you hear that now.

---

## What trips it — and what slips past

Aperture is a **heuristic**. We measured it on our own gold corpus and we publish the numbers instead
of a single flattering score, because *knowing where it’s blind is the product* —
**recall 0.400, precision 0.667** on a 100-case corpus, labeled by an isolated LLM-judge panel (it
catches 26 of 65 real drifts; ~1 flag in 3 is noise), full breakdown in
[docs/measured-limits.md](docs/measured-limits.md):

| Kind of change | Does Aperture flag it? |
| --- | --- |
| A watched commitment **deleted verbatim** | ✅ Reliably — this is the one thing it’s good at (24 of 24 in the corpus) |
| A commitment **reworded / softened** (“must” → “should”) | ❌ **Missed** — the text still “matches” |
| A commitment **paraphrased / restructured** | ❌ **Missed** |
| A number / scope / negation quietly changed | ❌ **Missed** |
| A commitment **translated** to another language | ⚠️ **Declines (abstains)** for a *natural-language* anchor — it can’t compare verbatim across scripts, so it returns `degraded` rather than false-flag (a commitment dropped **and** translated is missed) |

> **The deterministic surface doesn’t widen the aperture.** The git-hook fires reliably — but it still
> only catches **verbatim deletion**. Every ❌ / ⚠️ row above is exactly as blind through the hook as
> through MCP. What you gain is *when* it checks (on the commit, without anyone remembering to ask),
> not *what* it can see.

> **Anchor style matters for that last row:** the abstain applies to a **natural-language** anchor. A
> **code-identifier** anchor (the `ci-gates-green` style the quickstart teaches) is treated as
> *translation-stable* — Aperture keeps checking it across languages, so if that exact token disappears
> it still flags `DROPPED_SILENTLY` (usually what you want for a stable identifier).

**Takeaway:** treat every flag as *“look here,”* never as *“this is wrong”* — and never assume
silence means nothing drifted. Aperture catches the **verbatim disappearance** case well and is
honest that it catches little else. That narrow, reliable signal is useful precisely *because*
it doesn’t pretend to be more.

> **Hit one of those misses on your own docs?** That's the single most useful thing you can send us —
> [report it in ~30s](#hit-a-miss-help-it-improve) (your wording is optional). Real misses guide what
> we fix next.

> Why not just `git diff` / `grep`? You can reproduce the core check by hand. What Aperture adds is
> that it’s **wired to fire on the commit / PR event** (as a hook or CI check) *and* callable
> **mid-task by an agent** (over MCP); it returns a **structured, directional result**
> (`ok` / `degraded` / `DROPPED_SILENTLY` / …); and it **reports its own blind spots** in the result
> so a human can audit the gaps. It’s ergonomics + honesty around a simple, legible check — not a
> smarter detector.

---

## Why this exists

Long-running and multi-agent workflows drift. A constraint set in turn 3 / session 1 / by agent A
gets quietly edited away forty turns later, in another session, by agent B — and nobody notices
until it ships. Aperture is a **preflight you can put on the documents agents maintain**: name the
commitments that must not silently vanish, and get a tripwire when one does — ideally on the commit
itself, before the drop ever lands.

It is deliberately **small and legible**. It is not an AI that decides for you; it is a signal that
helps *you* stay consistent with yourself.

---

## Who it’s for

Teams and builders who **(a)** let AI agents edit repo-resident decision documents — specs, plans,
ADRs, charters, and `AGENTS.md` files — and **(b)** keep those documents under version control.
If your agents touch text that encodes promises, Aperture gives you a cheap, honest tripwire — on the
commit, in CI, or mid-task — on the ones you can’t afford to lose silently.

---

## Privacy

- **Opt-in and local.** Aperture runs on your machine — the git-hook, the CLI, and the MCP server
  alike. It makes no network calls.
- **Never trains on your data.** Your decision text is yours; it never leaves your process.
- **Usage logging is off by default** and, when enabled, records only **metadata** (timestamp,
  tool, status, counts) — never your decision text or commitment wording.

---

## Honesty about the demo

The repository ships a small **hand-authored fixture ADR** (a before/after pair under
[`examples/git_decision_drift/fixtures/`](./examples/git_decision_drift/fixtures)), where Aperture
correctly flags a commitment we deliberately retired and stays quiet on one we kept. It is a faithful
illustration of the mechanism — but it is a **sample of one that we author and judge ourselves**. It
demonstrates *how the tripwire works*, **not** *that the signal is strong*. For the latter, see the
measured per-family numbers above and in
[`docs/measured-limits.md`](./docs/measured-limits.md).
We have **zero external adopters yet** — if you run Aperture on your own decision docs, we’d love to
hear what it caught and what it missed.

---

## Project status

Early, **pre-1.0**, not yet a production gate. The compare contract (`v0.2`) is frozen and covered
by a conformance suite; the package API may still move. See [VERSIONING.md](./VERSIONING.md) for the
compatibility policy and [CHANGELOG.md](./CHANGELOG.md) for changes.

## Hit a miss? Help it improve

Aperture **will** miss things — that's by design (it's blind to reworded, softened, and translated
commitments, on every surface). When it misses a drift you cared about, or false-flags a rewrite,
telling us is the single most valuable contribution:

- **~30 seconds, no account/usage data, your wording is optional** →
  [open a drift-case report](../../issues/new?template=drift-case-report.md).
- Real misses tell us **which blind spot to fix next**, and — only if you choose to share the wording —
  can become cases in the gold corpus that keeps the numbers in
  [`docs/measured-limits.md`](./docs/measured-limits.md) honest.

We never auto-collect anything (see [Privacy](#privacy)); this happens only when *you* choose to share.
Questions, or "is this the right tool for my case?" → **[GitHub Discussions](../../discussions)**.

More ways to help: [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[Apache-2.0](./LICENSE).
