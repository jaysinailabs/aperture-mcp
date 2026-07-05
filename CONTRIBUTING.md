# Contributing to Aperture

**English** · [简体中文](./CONTRIBUTING.zh-CN.md)

Thanks for looking. Aperture is small on purpose, and its most valuable contributions are **honest
reports of where it works and where it doesn’t** — not just code.

## The single most useful thing you can do

Point Aperture at **your own** versioned decision docs (specs, plans, ADRs, charters) and tell us:

- a real **drop it caught** that mattered, or
- a real **drift it missed** (a reworded / softened / paraphrased commitment it stayed silent on), or
- a **false alarm** (a reformat — same-script rearrangement — it flagged as dropped; or a
  *natural-language*-anchored *translation* it flagged, which should instead decline/abstain). Note: a
  **code-identifier** anchor (e.g. `ci-gates-green`) flagged across a translation is *correct*, not a
  false alarm — it's translation-stable, so its exact token vanishing is a real drop.

These reports are how the limits table in the README stays honest and how the gold corpus grows.
Open an issue using the **“drift case report”** template.

## Two feedback channels — and the honest boundary between them

1. **Usage log (`APERTURE_USAGE_LOG`)** — *off by default*, fully local, and records **only
   metadata** (timestamp, tool, status, counts). It **never** contains your decision text or your
   commitment wording. It is a plain local file you can read or delete; nothing is sent anywhere.

2. **Contributing a real case** — a **separate, explicit** choice, made through the **“drift case
   report”** issue template (above). Be clear-eyed about what it involves: a useful benchmark case
   needs the **actual before/after wording**, because the wording *is* the test — so sharing a case
   **crosses** the metadata boundary and sends real text. Only include wording you’re comfortable
   making public; we don’t pretend it can be anonymized. The curated benchmark accepts only cases
   shared this way, under a license grant and an isolated review.

We will never blur these two. Metadata logging stays metadata-only; contributing a case is an
explicit choice to share text.

## Code contributions

- Keep the **compare contract** (`v0.2`, frozen) intact — see [VERSIONING.md](./VERSIONING.md).
  Contract-touching changes are a deliberate, reviewed protocol event, not a PR drive-by.
- Match the existing honesty discipline: if a change alters what the tool can or can’t see, update
  the README limits table in the same PR.
- Run the tests and linters before opening a PR.

## Conduct

By participating you agree to the [Code of Conduct](./CODE_OF_CONDUCT.md).
