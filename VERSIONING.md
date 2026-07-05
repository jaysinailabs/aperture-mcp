# Versioning & compatibility

Aperture has **two version numbers that move independently**. Knowing which one you depend on tells
you what is safe to upgrade.

## 1. The package version (`aperture-mcp` on PyPI)

Follows [Semantic Versioning](https://semver.org). **We are pre-1.0 (`0.x`)**, so per SemVer a
**minor** bump may contain breaking changes. Pin accordingly (e.g. `aperture-mcp~=0.2`) until 1.0.

A change is **breaking** (and bumps the appropriate version) if it alters any of:

- an MCP tool **name** or its required arguments (`compare`, `compare_commitment`, `compare_proposal`,
  `compare_stance`, `health`);
- the **keys or types** of the returned `DeltaResult` / JSON output;
- the set or meaning of the **8 status values** (`ok`, `degraded`, `BLOCKED`, `DROPPED_SILENTLY`,
  `incomparable`, `domain_mismatch`, `provider_unavailable`, `PAUSED`);
- the **anchor matching semantics** (case-insensitive contiguous-substring; directional present-in-A /
  missing-from-B);
- the meaning of an existing field (e.g. what `DROPPED_SILENTLY` asserts).

Non-breaking (patch/minor): new optional tools, new optional result fields, accuracy/heuristic
improvements that don’t change the output shape, docs, and the wording of `reason` notes (the
`reason` string is human-facing and explicitly **not** part of the stable contract).

## 2. The compare contract version (`DeltaResult` / schema)

The protocol contract is versioned separately and is currently **`v0.2` (frozen)**, covered by a
language-agnostic conformance suite. The contract version changes only on a deliberate, reviewed
protocol revision — *not* on every package release. The package version being `0.2.x` while the
contract is `v0.2` is intentional: the **package** is early; the **contract** it implements is the
frozen v0.2.

If you build against the wire contract (e.g. a second implementation), depend on the **contract
version**. If you depend on the Python API or the MCP tool surface, depend on the **package version**.

## Deprecation policy

- Anything deprecated is announced in [CHANGELOG.md](./CHANGELOG.md) with the replacement.
- Within `0.x`, deprecated surfaces may be removed in the next **minor**; from `1.0` onward, not
  before the next **major**, with at least one minor’s overlap where practical.
- The 8-value status set and the anchor-matching semantics are the contract’s load-bearing core; any
  change there is a contract-version event, never a quiet patch.

## What “frozen” does and doesn’t promise

`v0.2-frozen` means the **shape and semantics** of the contract won’t silently change. It does **not**
promise the heuristic gets more accurate — Aperture’s known blind spots (misses reworded/paraphrased
commitments; declines/abstains on translations; still false-flags reformats) are documented limits,
not bugs scheduled for a patch. See the limits table in the [README](./README.md).
