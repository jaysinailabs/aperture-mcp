<!-- mcp-name: io.github.jaysinailabs/aperture-mcp -->

<div align="center">

# Aperture MCP

### Did an agent quietly drop a commitment from your spec — and no one noticed?

[![PyPI](https://img.shields.io/badge/pypi-aperture--mcp-blue)](https://pypi.org/project/aperture-mcp/) [![MCP](https://img.shields.io/badge/MCP-server-purple)](https://modelcontextprotocol.io) [![License](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE) [![status](https://img.shields.io/badge/status-early%2Fpre--1.0-orange)](./VERSIONING.md)

**English** · [简体中文](./README.zh-CN.md)

</div>

AI agents now rewrite the documents that govern your work — specs, plans, ADRs, charters,
`AGENTS.md` files. Somewhere in the edit, a constraint you set earlier can quietly disappear.

**Aperture MCP is a *commitment tripwire*.** You name the commitments you care about; it flags —
**word for word** — when one of them vanishes between two versions of a decision document.

> **A signal, not a judge.** It trips; *you* investigate.
> Opt-in · runs locally · never trains on your data.

---

## What it is (and what it is not)

Aperture MCP is a small tool (and plain Python library) that
compares **two text states of the same decision** — an earlier version and a later one — and
surfaces a narrow, specific kind of **decision drift**: when a **tracked commitment’s exact text
disappeared**.

- ✅ **It does:** flag when a commitment you listed *verbatim* is present in version A and gone
  from version B — across commits, sessions, or authors. It returns a structured, comparable
  result with **its own blind spots written on the label**.
- ❌ **It does *not*:** understand meaning. It matches text as a case-insensitive substring, so it
  **misses** a commitment that was *reworded / softened / paraphrased* (it looks dropped-free even
  though the promise weakened); it **declines/abstains** on a commitment that was merely *translated*
  (it can’t compare verbatim across scripts, so it returns `degraded` rather than false-flag); and it
  can still **false-flag** a commitment that was merely *reformatted* (the words moved, the meaning
  didn’t). It does not rank options, score quality, or
  tell you a change was *wrong*. **That judgment stays with you.**

If you want one sentence: **Aperture MCP is `grep` for vanished commitments, wrapped so an agent can
call it mid-task and get a structured answer that admits what it can’t see.**

---

## Quickstart (≈2 minutes)

```sh
pip install aperture-mcp
```

Run the bundled example (clone the repo first) — it trips on a dropped commitment against
checked-in fixtures, with no setup, no API keys, fully offline:

```sh
python3 examples/git_decision_drift/git_decision_drift.py
```

```text
Aperture MCP · commitment tripwire — a fixture/sample decision-doc edit

  [TRIPPED ] 'ci-gates-green'             (in_before=True, in_after=False)
  [ held  ] 'data-never-leaves-device'   (in_before=True, in_after=True)

  One watched commitment vanished between the two versions; one held.
  Aperture MCP makes the disappearance visible — you decide whether it was intended.
```

Use it from your own code:

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

Wire it into an MCP client (Cursor, Cline, Goose, or any stdio-capable host):

```jsonc
{
  "mcpServers": {
    "aperture-mcp": { "command": "aperture-mcp" }
  }
}
```

> Prefer zero-install? Point the client at `uvx` instead:
> `{ "command": "uvx", "args": ["aperture-mcp"] }`.

---

## A scene you’ll recognize

On a long task, your agent keeps rewriting the doc it works from — a plan, a spec — across sessions
and edits. And every so often, a line that mattered just… vanishes.

*“Always ask before you delete anything.”* Gone.
*“User data never leaves the device.”* Gone.
*“The free tier stays free.”* Gone.

Nobody meant to drop them; nobody reads all 400 lines of the diff.

Aperture MCP watches the exact lines you name. Give it two versions of the doc and it won’t try to
understand them or judge them — it just tells you which promise was there, word for word, and now
isn’t. A tripwire, not a judge — and honest about the rest: soften a line, reword it, or change a
number instead of deleting it, and it’ll slip past. Better you hear that now.

---

## What trips it — and what slips past

Aperture MCP is a **heuristic**. We measured it on our own gold corpus and we publish the numbers
instead of a single flattering score, because *knowing where it’s blind is the product* —
**recall 0.400, precision 0.667** on a 100-case corpus (it catches 26 of 65 real drifts; ~1 flag in 3
is noise), full breakdown in [docs/measured-limits.md](docs/measured-limits.md):

| Kind of change | Does Aperture MCP flag it? |
| --- | --- |
| A watched commitment **deleted verbatim** | ✅ Reliably — this is the one thing it’s good at |
| A commitment **reworded / softened** (“must” → “should”) | ❌ **Missed** — the text still “matches” |
| A commitment **paraphrased / restructured** | ❌ **Missed** |
| A number / scope / negation quietly changed | ❌ **Missed** |
| A commitment **translated** to another language | ⚠️ **Declines (abstains)** for a *natural-language* anchor — it can’t compare verbatim across scripts, so it returns `degraded` rather than false-flag (a commitment dropped **and** translated is missed) |

> **Anchor style matters for that last row:** the abstain applies to a **natural-language** anchor. A
> **code-identifier** anchor (the `ci-gates-green` style the quickstart teaches) is treated as
> *translation-stable* — Aperture keeps checking it across languages, so if that exact token disappears
> it still flags `DROPPED_SILENTLY` (usually what you want for a stable identifier).

**Takeaway:** treat every flag as *“look here,”* never as *“this is wrong”* — and never assume
silence means nothing drifted. Aperture MCP catches the **verbatim disappearance** case well and is
honest that it catches little else. That narrow, reliable signal is useful precisely *because*
it doesn’t pretend to be more.

> **Hit one of those misses on your own docs?** That's the single most useful thing you can send us —
> [report it in ~30s](#hit-a-miss-help-it-improve) (your wording is optional). Real misses guide what
> we fix next.

> Why not just `git diff`? You can reproduce the core check with `grep`. What Aperture MCP adds is that
> an **agent can call it mid-task** (over MCP), it returns a **structured, directional result**
> (`ok` / `degraded` / `DROPPED_SILENTLY` / …), and it **reports its own blind spots** in the
> result so a human can audit the gaps. It’s ergonomics + honesty around a simple, legible check —
> not a smarter detector.

---

## Why this exists

Long-running and multi-agent workflows drift. A constraint set in turn 3 / session 1 / by agent A
gets quietly edited away forty turns later, in another session, by agent B — and nobody notices
until it ships. Aperture MCP is a **preflight you can put on the documents agents maintain**: name the
commitments that must not silently vanish, and get a tripwire when one does.

It is deliberately **small and legible**. It is not an AI that decides for you; it is a signal that
helps *you* stay consistent with yourself.

---

## Who it’s for

Teams and builders who **(a)** let AI agents edit repo-resident decision documents — specs, plans,
ADRs, charters, and `AGENTS.md` files — and **(b)** keep those documents under version control.
If your agents touch text that encodes promises, Aperture MCP gives you a cheap, honest tripwire on the
ones you can’t afford to lose silently.

---

## Privacy

- **Opt-in and local.** Aperture MCP runs on your machine. It makes no network calls.
- **Never trains on your data.** Your decision text is yours; it never leaves your process.
- **Usage logging is off by default** and, when enabled, records only **metadata** (timestamp,
  tool, status, counts) — never your decision text or commitment wording.

---

## Honesty about the demo

The repository ships a small **hand-authored fixture ADR** (a before/after pair under
[`examples/git_decision_drift/fixtures/`](./examples/git_decision_drift/fixtures)), where Aperture MCP
correctly flags a commitment we deliberately retired and stays quiet on one we kept. It is a faithful
illustration of the mechanism — but it is a **sample of one that we author and judge ourselves**. It
demonstrates *how the tripwire works*, **not** *that the signal is strong*. For the latter, see the
measured per-family numbers above and in
[`docs/measured-limits.md`](./docs/measured-limits.md).
We have **zero external adopters yet** — if you run Aperture MCP on your own decision docs, we’d love to
hear what it caught and what it missed.

---

## Project status

Early, **pre-1.0**, not yet a production gate. The compare contract (`v0.2`) is frozen and covered
by a conformance suite; the package API may still move. See [VERSIONING.md](./VERSIONING.md) for the
compatibility policy and [CHANGELOG.md](./CHANGELOG.md) for changes.

## Hit a miss? Help it improve

Aperture MCP **will** miss things — that's by design (it's blind to reworded, softened, and translated
commitments). When it misses a drift you cared about, or false-flags a rewrite, telling us is the
single most valuable contribution:

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
