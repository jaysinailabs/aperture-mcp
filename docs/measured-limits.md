# How well does it actually work? (measured)

We publish these numbers instead of a single flattering score, because **knowing where Aperture MCP is
blind is the product.** A tripwire you can’t trust is worse than no tripwire — so here is exactly
what it caught and missed on our gold corpus.

## The honest headline

On a **41-case** internal gold corpus (curator-built, one scoring family per case, judged by an isolated panel):

| Metric | Value | In plain words |
| --- | --- | --- |
| **Recall** | **0.375** | It caught **9 of 24** real drifts. It **missed ~62%.** |
| **Precision** | **0.75** | Of its flags, **9 of 12 were real**; ~1 in 4 was noise. |

A recall-0.38 / precision-0.75 heuristic is **not a gate** and we don’t market it as one. It is a
*signal* you verify on every fire and never read as “all clear.” Its value is that the **one thing it
does reliably, it does at recall 1.0** — and it is honest about the rest.

## Per-family: what trips it, what slips past

Each number below is a **real drop** (a commitment that genuinely changed); **Caught** is how many the
tool flagged. They reconcile to the headline: **Caught** sums to **9**, **Real drops** to **24**, recall **0.375**.

| Drift family | Real drops | Caught | Recall |
| --- | --- | --- | --- |
| **commitment_drop** — a watched commitment deleted verbatim | 6 | 6 | **1.00** ✅ |
| **cross_language** — a real drop in same-script non-English (Chinese) text | 2 | 2 | **1.00** ✅ |
| semantic_drift — small sample, not load-bearing | 1 | 1 | 1.00 |
| factual_revision | 2 | 0 | 0.00 ❌ |
| modal_strength (“must” → “should”) | 4 | 0 | 0.00 ❌ |
| negation (added/removed “not”) | 4 | 0 | 0.00 ❌ |
| scope (narrowed/widened) | 3 | 0 | 0.00 ❌ |
| numeric (a threshold quietly changed) | 1 | 0 | 0.00 ❌ |
| paraphrase_weakening (reworded softer) | 1 | 0 | 0.00 ❌ |
| **Total — distinct real drops** | **24** | **9** | **0.375** |

Recall is high only for **verbatim deletion** (commitment_drop, and a same-script cross-language drop) —
everything semantic is missed.

**No-drift controls are kept out of the table above** (recall is about catching *real* drifts): the
41-case corpus also holds faithful **translations** and **high-surface paraphrases** where nothing
actually changed. On the 2 cross-language translations the tool **abstains** (`degraded`, **fp 0**) —
correctly declining rather than false-flagging a preserved-but-translated commitment. Its false flags
live elsewhere: **precision 0.75** = 9 real of 12 flags, i.e. **3 false flags** (high-surface same-script
rewrites / no-drift controls). **Design limit:** a commitment that is *both* dropped *and* translated out
of the text would be abstained-on, not caught.

**Read it like this:** Aperture MCP reliably catches a commitment that was **deleted word-for-word**. It
is essentially blind to commitments that were **reworded, softened, paraphrased, re-scoped, negated,
or had a number changed** — which is how commitments most often erode in real documents — and it
**declines/abstains** on a commitment that was merely **translated** (it can't compare verbatim across
scripts, so it returns `degraded` rather than false-flag).

## Why we shipped it anyway

Because the narrow signal is real, cheap, local, and *legible* — and because the alternative (a
semantic detector) is a different, much heavier project we deliberately have not built. A tool that
catches one drift mode at recall 1.0 and **tells you plainly it catches little else** is more useful
than one that claims broad “drift detection” and quietly fails open. If your commitments live in text
an agent edits, watching for their verbatim disappearance is a real, if humble, line of defense.

## Caveats on these numbers

- The corpus is **small (n=41)** and curator-built; treat the figures as **directional**, not a
  benchmark leaderboard. The corpus itself is kept private; the *measurements* are
  public.
- The **Real drops** column counts each family's **drift (positive-truth)** cases; they sum to the **24**
  distinct real drifts, and **Caught** sums to **9** (recall 0.375). The full 41-case corpus also holds
  **no-drift control** cases (faithful translations, high-surface paraphrases, and negatives mixed into
  some families); those bear on **precision** (0.75 — 3 false flags of 12), not recall, so they are not in
  the recall table above.
- Numbers are **deterministic** (no model in the scoring path), produced by our internal scoring
  harness against the **private** gold corpus — which is intentionally **not** bundled, so the figures
  can't be regenerated from this repo alone.
- Help us improve them: real-world misses and false-flags are the most valuable contribution — see
  [CONTRIBUTING.md](../CONTRIBUTING.md).
