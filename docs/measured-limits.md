# How well does it actually work? (measured)

We publish these numbers instead of a single flattering score, because **knowing where Aperture is
blind is the product.** A tripwire you can’t trust is worse than no tripwire — so here is exactly
what it caught and missed on our gold corpus.

## The honest headline

On a **100-case** internal gold corpus (curator-built, one scoring family per case, judged by an isolated panel):

| Metric | Value | In plain words |
| --- | --- | --- |
| **Recall** | **0.400** | It caught **26 of 65** real drifts. It **missed 39 (fn_rate 0.600).** |
| **Precision** | **0.667** | Of its **39 flags**, **26 were real**; ~1 in 3 was noise. |
| **Abstain** | **9** | It **declined** rather than guess on 9 cases. |

The full confusion matrix: **tp 26, fp 13, tn 13, fn 39, abstain 9** (100 cases). A
recall-0.40 / precision-0.67 heuristic is **not a gate** and we don’t market it as one. It is a
*signal* you verify on every fire and never read as “all clear.” Its value is that the **one thing it
does reliably — catch a verbatim deletion — it caught on every case in the corpus (24 of 24)**, and it
is honest about the rest. (It is still a heuristic; 24/24 is the corpus, not a guarantee for all time.)

### Precision fell vs. the old 41-case figures — on purpose

The previous public numbers were **recall 0.375 / precision 0.75** on a 41-case corpus. On the v1 gold corpus (100 cases)
**precision drops to 0.667** (recall is roughly flat, 0.375→0.400) because we deliberately **added the
hard drift types the tool is designed to miss** — cap/carve-out obligation weakening, modal softening,
negation flips, numeric changes, scope narrowing, hedging — plus meaning-preserving rewrites that draw
false flags. This is a **more complete, more honest measurement, not a regression and not a
newly-worse tool.** The engine did not get worse; the exam got harder and fairer.

### Read the recall figure as *stress-weighted*, not real-world

The corpus is **deliberately weighted toward hard blind-spot drift types** — it is a **probe of where
the tool is blind, not a random sample of real-world edits.** So **recall 0.40 is a stress-weighted
figure**; real-world recall on a typical edit stream (where verbatim deletion is more common) may
differ. The one signal you can rely on in either setting is **verbatim deletion.**

## Per-family: what trips it, what slips past

Recall splits by **one mechanism**: did the tracked anchor text survive the edit? Every row reconciles
to the headline — **Real drifts** sum to **65**, **Caught** to **26**, recall **0.400**.

| What changed | Real drifts | Caught | Recall |
| --- | --- | --- | --- |
| **Anchor deleted verbatim** — a named commitment or clause removed word-for-word, incl. real decision-doc drops where the anchor phrase itself vanished | 24 | 24 | **1.00** ✅ |
| **Anchor text survived** — the obligation was gutted by an added cap, carve-out, or superseding clause; a modal softened (“must”→“should”); a negation flipped; a number/scope moved; a commitment hedged — while the named anchor stayed present, so the substring still matched | 35 | 0 | **0.00** ❌ |
| **Other self-checks** — proposal / stance profiles (original corpus) | 6 | 2 | 0.33 |
| **Total — real drifts** | **65** | **26** | **0.400** |

The story is one line: **when the anchor phrase is deleted, it catches it (24 of 24); when the wording
survives but the meaning weakened, it misses it (0 of 35).** That is the whole product — a substring
tripwire, blind to everything that keeps the substring.

Recall is meaningful only for **verbatim deletion** — a named commitment or clause removed
word-for-word, and real decision-doc drops where the anchor phrase itself vanished. **Everything on
the semantic-weakening surface is missed** (fn_rate ≈ 1.0 for that aggregate row): the obligation was
gutted by an added cap, carve-out, or superseding clause; the modal was softened; a negation flipped;
a threshold moved — while the named anchor text **survived**, so the substring match still passes.

**No-drift controls are kept out of the recall table** (recall is about catching *real* drifts). The
corpus also holds meaning-**preserving** rewrites — paraphrases, synonym swaps, active→passive,
defined-term substitutions, reorderings — where the anchor substring vanished even though nothing
actually changed. Those drive the **precision** cost: **13 false flags** of 39 (precision 0.667). And
on cases it cannot compare verbatim across scripts it **abstains** (9 cases) rather than false-flag.

## Two things v1 now measures that the old corpus did not

**The silent-“ok” false negative.** Via the commitment self-check, the engine can confidently return
“no dropped commitments detected” while the obligation was actually **gutted by an added cap,
carve-out, or softening clause** and the named anchor survived verbatim. This is the scariest miss —
the tool reports *clear* while the promise quietly weakened — and it was **untested** before v1. It is
now in the corpus, and it is a **known blind spot**, not a solved one.

**Dogfooded on our own documents.** v1 was run against **real git revisions of our own planning,
charter, and positioning docs**. It caught verbatim removals — and it **missed** softenings of
Aperture’s **own** positioning commitments, e.g. a mission line whose meaning weakened across a
revision while the anchor phrase survived, so the edit slipped past. We keep those misses in the
corpus precisely because they are the honest picture: the tool is blind to semantic weakening even
when the document is our own. The corpus spans **English contract clauses and Chinese decision
documents**.

## Why we shipped it anyway

Because the narrow signal is real, cheap, local, and *legible* — and because the alternative (a
semantic detector) is a different, much heavier project we deliberately have not built. A tool that
catches verbatim deletion reliably and **tells you plainly it catches little else** is more useful
than one that claims broad “drift detection” and quietly fails open. If your commitments live in text
an agent edits, watching for their verbatim disappearance is a real, if humble, line of defense.

## Caveats on these numbers

- **Precision fell because the exam got harder, not the tool worse.** v1 deliberately added the hard,
  semantic drift types the tool is designed to miss (plus meaning-preserving rewrites that draw false
  flags); precision dropped 0.75→0.667 while recall held roughly flat (0.375→0.400) on a much larger,
  harder corpus. That is a **more honest** measurement, not a regression — don’t read the figures as an
  easy score.
- **The corpus is a probe, not a sample.** It is deliberately weighted toward hard blind-spot drift
  types, so **recall 0.40 is stress-weighted** and not an estimate of real-world catch rate. The one
  reliable signal remains **verbatim deletion.**
- **Precision costs are real rewrites.** 13 false flags of 39 come from meaning-preserving
  paraphrase / synonym / reordering edits where the anchor substring vanished — not from bugs.
- Numbers are **deterministic** (no model in the scoring path), produced by our internal scoring
  harness against the **private** gold corpus — which is intentionally **not** bundled, so the figures
  can’t be regenerated from this repo alone. The *measurements* are public; the corpus stays private.
- Help us improve them: real-world misses and false-flags are the most valuable contribution — see
  [CONTRIBUTING.md](../CONTRIBUTING.md).
