"""Aperture v0.1 protocol primitives: 八值 status, anchors, DeltaResult, profiles."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from aperture.errors import ApertureError


class DeltaStatus(StrEnum):
    """Eight-value flattened scalar status (C.3).

    Lowercase (v0.0 legacy): ok degraded incomparable domain_mismatch provider_unavailable
    Uppercase (v0.1 new):    BLOCKED DROPPED_SILENTLY PAUSED
    """

    OK = "ok"
    DEGRADED = "degraded"
    INCOMPARABLE = "incomparable"
    DOMAIN_MISMATCH = "domain_mismatch"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    BLOCKED = "BLOCKED"
    DROPPED_SILENTLY = "DROPPED_SILENTLY"
    PAUSED = "PAUSED"


class AnchorKind(StrEnum):
    """Four anchor kinds (C.2), lowercase on wire."""

    GOAL = "goal"
    CONSTRAINT = "constraint"
    COMMITMENT = "commitment"
    BASELINE = "baseline"


@dataclass(frozen=True, slots=True)
class Anchor:
    kind: AnchorKind
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise TypeError("Anchor.id must be a str")
        if self.id == "":
            raise ValueError("Anchor.id must be non-empty")


class InvalidAnchorError(ApertureError, TypeError):
    """Raised when a compare anchor list element is not a valid :class:`Anchor`.

    Historically a bad anchor element surfaced as a raw ``AttributeError`` (e.g.
    ``None.id``) deep inside the anchor loop. ``AttributeError`` is a subclass of
    neither ``TypeError`` nor ``ApertureError``. This error inherits from
    ``TypeError`` (via multiple inheritance) so the bad-anchor case is now
    catchable as both ``except TypeError`` and ``except ApertureError`` — a
    deliberate, safe broadening (not preservation of a prior ``TypeError``
    surface). Validation is read-only: it inspects the element and raises, never
    mutating compare state, so the compare family stays pure.
    """


def _require_valid_anchor(value: object, index: int) -> Anchor:
    """Validate a single anchor-list element and return it as an :class:`Anchor`.

    Raises :class:`InvalidAnchorError` with a clear, call-site-near message when
    ``value`` is not a usable anchor (``None``, or missing a ``kind``/``id``
    attribute), instead of letting a raw ``AttributeError`` surface far from the
    ``compare(...)`` call. Does NOT enforce ``Anchor.kind`` value validity at
    construction time (off-limits) — it only checks the attributes the anchor
    loops actually dereference.
    """
    if value is None:
        raise InvalidAnchorError(f"anchors[{index}] is None; expected an Anchor with .kind and .id")
    if not hasattr(value, "kind") or not hasattr(value, "id"):
        raise InvalidAnchorError(
            f"anchors[{index}] is not a valid Anchor "
            f"(got {type(value).__name__}; missing .kind/.id attribute)"
        )
    return value  # type: ignore[return-value]


def _validated_anchors(anchors: list[Anchor]) -> list[Anchor]:
    """Return ``anchors`` after validating every element is a usable Anchor.

    Pure pass-through: builds no shared/mutable state, only raises
    :class:`InvalidAnchorError` on the first bad element.
    """
    return [_require_valid_anchor(a, i) for i, a in enumerate(anchors)]


@dataclass(frozen=True, slots=True)
class AnchorViolation:
    anchor_id: str
    kind: AnchorKind
    status: DeltaStatus
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "anchor_id": self.anchor_id,
            "kind": self.kind.value,
            "status": self.status.value,
        }
        if self.detail is not None:
            d["detail"] = self.detail
        return d


@dataclass(frozen=True, slots=True)
class DeltaResult:
    """v0.1 self-consistency compare 输出。

    **实现层子集**：仅承载 status / reason / provider_family / state_kind /
    anchor_violations + 可选 `event_id`（caller-supplied instrumentation 关联 id，
    仅在调用方传入时出现，默认 wire 形态不变）。完整 methodology `C4_DeltaResult` 的多视角字段
    （delta / anchor_reaffirmations / per_view_findings / cross_view_conflicts /
    impact_radius / suggested_actions）留后续增量（需 multi-view / TopologyProvider
    机制）。conformance smoke 校验的是 D-1 冻结的子实体（C3_Status / C2_AnchorKind /
    C4_AnchorViolation）从真实取值出发；完整 C4_DeltaResult 仅以手写 wire 例 sanity 校验。
    """

    status: DeltaStatus
    reason: str
    provider_family: str = "mock"
    # self-consistency family 下的 profile（proposal / stance / commitment）；与 provider_family
    # 正交（Q8 字段拆分：family 标家族、profile 标三态）。base / scaffold compare 不设 profile。
    profile: str | None = None
    state_kind: str = "text"
    anchor_violations: list[AnchorViolation] = field(default_factory=list)
    # Optional caller-supplied instrumentation event id (correlates a compare event with
    # metrics / logs). Kept caller-supplied so compare() stays a pure, deterministic
    # function — no generated UUID / clock inside the primitive.
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status.value,
            "reason": self.reason,
            "provider_family": self.provider_family,
            "state_kind": self.state_kind,
            "anchor_violations": [v.to_dict() for v in self.anchor_violations],
        }
        # profile / event_id 仅在存在时出现，保持 base compare 的默认 wire 形态不变。
        if self.profile is not None:
            d["profile"] = self.profile
        if self.event_id is not None:
            d["event_id"] = self.event_id
        return d

    def __post_init__(self) -> None:
        if self.status is not DeltaStatus.OK and not self.reason.strip():
            raise ValueError("non-ok DeltaResult.status requires a non-empty reason")
        if self.anchor_violations:
            status_rank = _SEVERITY_ORDER[self.status]
            max_violation_rank = max(_SEVERITY_ORDER[v.status] for v in self.anchor_violations)
            if status_rank < max_violation_rank:
                raise ValueError(
                    "C-AV-10 violation: DeltaResult.status must be at least as severe "
                    "as every anchor_violations status"
                )


def _finish(
    result: DeltaResult,
    event_id: str | None,
    state_a: str = "",
    state_b: str = "",
    anchors: list[Anchor] | None = None,
    detector_fired: bool = False,
) -> DeltaResult:
    """Stamp event_id + append honest blind-spot reason note(s) onto a result.

    Two reason-only, side-effect-free augmentations, in this order:

    1. **Blind-spot notes** (the blind-spot white-list rules). When NO anchor/detector
       violation fired (``result.anchor_violations == []``) AND no PROFILE
       detector fired (``detector_fired`` is False) we append 0..3
       FACTS-not-verdicts about what this surface-level detector did and did NOT
       cover, computed purely from the inputs + the already-decided result by
       :func:`_blindspot_notes`. We rewrite ONLY ``reason`` (via
       :func:`dataclasses.replace`), never ``status`` / ``anchor_violations`` —
        so the result-status severity invariant and every status/violation fixture stay
       byte-for-byte identical, and a fired detector's violation-join reason is
       left untouched (a blind-spot note on a real violation is incoherent). The
       bracketed ``" [<note>; <note>]"`` suffix keeps the prior reason as a
       literal PREFIX substring. The notes carry zero direction/disposition and
        add zero keys, so the engine red lines (key-whitelist / zero-directionality /
        self-cover / schema-invariant) stay clean.

       ``detector_fired`` is the FACTS-NOT-VERDICTS fix (red-line): a profile
       detector that DID fire with a real signal (proposal strength score >=
       threshold / stance polarity reversal / commitment drift) carries an EMPTY
       ``anchor_violations`` (the signal is not an anchor violation), so the
       anchor-only predicate alone would still append "...no anchor or keyword
       detector hit..." / "...no strength detector threshold was crossed..." —
       notes that flatly CONTRADICT the just-fired detector. Threading the flag
       from those detector-hit return paths suppresses the blind-spot notes there
       while leaving the GENERIC anchorless-diff paths (``detector_fired`` False)
       free to fire the no-anchor note as before. This changes only WHICH reason
       notes append; ``status`` / ``anchor_violations`` are untouched on every
       path.

    2. **event_id echo.** Keeps the compare family pure: event_id is just another
       input echoed into the output, so a given (states, anchors, event_id) still
        maps deterministically to one DeltaResult (determinism preserved —
       the note logic is a pure function of the same inputs).
    """
    if not result.anchor_violations and not detector_fired and state_a != state_b:
        notes = _blindspot_notes(state_a, state_b, anchors or [], result)
        if notes:
            result = replace(result, reason=result.reason + " [" + "; ".join(notes) + "]")
    return result if event_id is None else replace(result, event_id=event_id)


def _require_text_states(state_a: object, state_b: object) -> None:
    for state in (state_a, state_b):
        if not isinstance(state, str):
            raise TypeError(f"v0.2 compare requires str states; got {type(state).__name__}")


# ---------------------------------------------------------------------------
# Cross-language comparability guard (PER-ANCHOR decline, BEFORE detection)
# ---------------------------------------------------------------------------
#
# Aperture matches anchors as verbatim contiguous substrings. Across a
# TRANSLATION (state_a and state_b written in different scripts) a NATURAL-
# LANGUAGE substring structurally cannot survive — the anchor "vanishes" because
# the surrounding text was rewritten in another writing system, with NO bearing
# on whether the commitment was actually dropped. Flagging a violation there is a
# false alarm.
#
# A CODE-IDENTIFIER anchor, however (``ci-gates-green``, ``no-decoder-loop``), is
# reproduced VERBATIM even in a translated doc — a code id is not translated — so
# its absence from a differently-scripted ``state_b`` is a REAL drop signal, not
# a language artifact. The two anchor classes must therefore be handled
# SEPARATELY, not lumped by "does the anchor SET contain a code id".
#
# So when the two states are a CLEAN full CJK<->Latin translation — each side
# essentially ONE script and the two scripts OPPOSITE (the unambiguous fingerprint
# of a translation) — we partition the anchors BEFORE detection:
#   * survivable code-id anchors -> detected normally (a genuine absence still
#     surfaces as a violation);
#   * non-survivable natural-language anchors (and, for compare_commitment, the
#     implicit commitment-key path over natural-language phrases) -> DECLINED:
#     filtered out BEFORE the detection loop / violation construction.
# If no survivable anchor fires and >=1 anchor was declined (or none supplied),
# we return a `degraded` comparability abstain with EMPTY anchor_violations and
# an honest reason. This is a deliberate impl-defined detection-SCOPE choice
# (detection scope is implementation-defined): declined anchors are never fed to
# detection, so no violation is ever detected-then-discarded — a detected violation
# is always surfaced, never dropped.
#
# SCOPE (honest, F6): the guard fires ONLY on a CLEAN full CJK<->Latin translation
# — each side single-script (>= _CJK_HIGH of it AND ZERO letters of the other) and
# the two scripts opposite. `_script_counts` counts NFKC-complete over CJK-language
# scripts (Han/Kana incl. Hentaigana/Hangul/Bopomofo, incl. compatibility/
# fullwidth/stylized forms) and all Latin forms; genuinely-other scripts (Greek,
# Cyrillic, Arabic, …) read neither and run unguarded.
# This is the concrete false-positive family we measured, scoped narrow.
#
# STRUCTURAL guarantee (provable, not tuned): a pair written in the SAME script
# family — both in CJK-script (Han / Kana incl. Hentaigana / Hangul / Bopomofo,
# any presentation form) OR both in Latin-script (any presentation form) — can
# NEVER be classified cross-language, so a same-script-family real drop is NEVER
# swallowed. Codepoints outside that surface (CJK meta-glyphs, non-CJK scripts)
# run unguarded.
#
# WHAT RUNS UNGUARDED (may over-flag exactly as before the guard existed — the SAFE
# direction, an over-flag you verify, NEVER a swallowed drop): ANY MIXED-script doc
# — one carrying >= 1 letter of the OTHER script, whether an embedded URL / config
# path / inline code-id, a bilingual citation or quoted foreign-language error
# message, or a SHORT TERSE revision below _CJK_HIGH — is NOT "pure", so the pair is
# NOT declined and stays fully checkable. This is the deliberate trade the
# presence/dominance designs got wrong: we accept a possible over-flag on a mixed
# doc rather than risk swallowing a real same-language drop.
#
# STRUCTURAL no-swallow guarantee (same-SCRIPT never swallows — provable, not
# tuned): with _OTHER_FLOOR == 0 a firing pair needs one side pure-CJK (ZERO Latin
# letters) and the other pure-Latin (ZERO CJK). The pure-CJK side is a CJK-ONLY-
# script doc; the pure-Latin side is a LATIN-ONLY-script doc — DIFFERENT scripts BY
# CONSTRUCTION. So no same-SCRIPT pair can ever match, and a same-script real drop
# can NEVER be swallowed, for ANY inputs. A natural-language commitment BOTH dropped
# AND cleanly translated is the one case declined (Aperture cannot tell a real
# cross-writing-system drop from a faithful rewrite via substrings, so it abstains
# rather than guess) — but that requires a clean opposite-single-script pair. The
# same-LANGUAGE transliterations / romanizations
# (Pinyin<->Han, Rōmaji<->Kana, Romanized-Korean<->Hangul — the same language in
# two writing systems); declining those is the same honest behavior as declining a
# translation (the alternative is a false-flag), and is the disclosed
# cross-WRITING-SYSTEM limit.
#
# NARROW BY DESIGN: this replaces ONLY the reverted precision bundle's
# script-mismatch idea. The bundle's second guard (high-surface same-script
# "faithful rewrite" abstain) is deliberately NOT reintroduced — it swallowed
# real same-script drops (the headline capability) and stays a separate,
# adversarially-proven-first future experiment.

# CJK letter blocks (Han + Kana + Hangul) — enough to fingerprint a CJK↔Latin
# translation, which is the concrete false-positive family we measured.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul Syllables
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
)

# PURE-vs-PURE opposite-script thresholds. The classifier declines ONLY when the
# two states are UNAMBIGUOUSLY single-script and OPPOSITE — one side ALL-CJK, the
# other ALL-Latin. It does NOT key on a presence/dominance asymmetry (every scalar
# presence threshold conflates "short CJK drop" with "Latin translation" and
# swallowed real same-language drops — the reverted-bundle failure class). A side is
# "pure X" iff it has >= _CJK_HIGH chars of script X AND ZERO letters of the other
# script (_OTHER_FLOOR == 0).
#
# _CJK_HIGH (min chars for a side to count as "substantively" that script) — bounded
# by two concrete design constraints:
#   * UPPER bound: it must stay low enough that the shortest genuine full-translation
#     side still registers as pure-CJK, so real translated documents are not
#     misclassified. Ample headroom above the lower bound.
#   * LOWER bound: a short terse CJK revision (e.g. two-character edits like
#     `不批。`/`取消`/`废除`, 2 CJK chars) must NOT read as pure-CJK, else it pairs
#     "opposite" against a Latin side and swallows the drop. 2 < 4, so those stay
#     below the bar → not pure → never declined → the real drop is detected. A stray
#     1-char CJK glyph in an English doc (`Ship it 好`, 1 CJK) is likewise below 4.
# 4 sits with margin on both sides.
#
# _OTHER_FLOOR == 0 (ZERO letters of the OTHER script tolerated on a "pure" side) —
# this is what makes the same-SCRIPT no-swallow guarantee STRUCTURALLY PROVABLE, not
# tuned: a firing pair needs one pure-CJK side (zero Latin) and one pure-Latin side
# (zero CJK), so the two sides are DIFFERENT scripts by construction — no same-script
# pair can ever fire. ANY mixed-script doc (>= 1 letter of the other script — an
# embedded CJK quote, a URL / config path / inline code-id, a loanword) is NOT
# "pure", so it runs UNGUARDED: an English doc embedding a CJK quote keeps its
# real English drop checkable, and a CJK doc embedding a URL / inline tool-names
# keeps its genuine CJK->CJK drop checkable. `_script_counts` ignores digits /
# punctuation / whitespace, so a CJK doc with numbers or `90天` still has latin == 0
# (only Latin LETTERS disqualify). Same-LANGUAGE transliterations /
# romanizations (Pinyin<->Han, Rōmaji<->Kana, Romanized-Korean<->Hangul) are a
# genuine cross-WRITING-SYSTEM pair — the disclosed limit.
_CJK_HIGH = 4
_OTHER_FLOOR = 0


def _script_counts(text: str) -> tuple[int, int]:
    """Return ``(cjk_chars, latin_letters)`` for ``text`` (NFKC-normalized).

    The NFKC pass folds compatibility/stylized forms (math-bold/italic/fraktur/
    script/double-struck/mono/sans, fullwidth, circled, parenthesized, ``ℓ``,
    halfwidth kana, compat ideographs, Kangxi radicals) to their canonical
    codepoints. Counting is COMPLETE for the writing systems of the CJK languages
    (Chinese / Japanese / Korean) + all Latin presentation forms:

    * Counted as CJK: Han (all planes, incl. compatibility & Kangxi radicals via
      NFKC), Hiragana, Katakana (incl. halfwidth & phonetic ext via NFKC),
      Hentaigana, Hangul (syllables + jamo), Bopomofo (+ extended).
    * Counted as Latin: every Latin letter in any presentation form (ASCII,
      accented, fullwidth, math-styled, circled, ``ℓ``, …) via NFKC.
    * Explicitly OUT OF SCOPE (run unguarded — an over-flag/decline in the SAFE
      direction, never a supported-language swallow): (a) CJK meta-glyphs that are
      not letters of a writing system — CJK Radicals Supplement, CJK Strokes,
      Ideographic Description Characters (all ``isalpha()=False``, not used to
      write prose); (b) scripts of non-CJK languages — Yi, Tangut, Nüshu,
      Cyrillic, Greek, Arabic, etc. Neither can create a SAME-language
      pure-CJK/pure-Latin pair: a meta-glyph string is not a document, and a
      non-CJK-language script paired with Han is a CROSS-language pair, not a
      same-language swallow.

    Every other character (digits, punctuation, whitespace, symbols) is ignored.
    """
    cjk = latin = 0
    for ch in unicodedata.normalize("NFKC", text):
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if (
            "CJK" in name
            or "IDEOGRAPH" in name
            or "HIRAGANA" in name
            or "KATAKANA" in name
            or "HENTAIGANA" in name
            or "HANGUL" in name
            or "BOPOMOFO" in name
        ):
            cjk += 1
        elif "LATIN" in name:
            latin += 1
    return cjk, latin


def _states_cross_language(state_a: str, state_b: str) -> bool:
    """True iff state_a/state_b are a CLEAN full CJK<->Latin translation pair.

    PURE-vs-PURE opposite-script rule: decline as cross-language ONLY when the two
    states are UNAMBIGUOUSLY single-script and OPPOSITE — one side ALL-CJK, the
    other ALL-Latin. A side is "pure X" iff it has >= `_CJK_HIGH` chars of script X
    AND ZERO letters of the other script (`_OTHER_FLOOR` == 0). Cross-language is
    true iff (a pure-CJK and b pure-Latin) OR (a pure-Latin and b pure-CJK).

    INVARIANT — same-SCRIPT never swallows (structural, provable, not tuned): with
    `_OTHER_FLOOR` == 0 a firing pair needs one side pure-CJK (ZERO Latin letters)
    and the other pure-Latin (ZERO CJK). The pure-CJK side is a CJK-only-script doc
    and the pure-Latin side is a Latin-only-script doc — DIFFERENT scripts BY
    CONSTRUCTION. So no SAME-SCRIPT pair can ever satisfy "one pure-CJK AND one
    pure-Latin"; therefore no same-script pair is ever declined, and a same-script
    real drop can NEVER be swallowed, for ANY inputs. What this deliberately gives
    up: ANY mixed-script doc (>= 1 letter of the other script — an embedded
    URL/path/code-id, a bilingual citation, a loanword) is NOT "pure", so the pair
    is NOT declined and runs UNGUARDED, exactly as before this guard existed (the
    guard may over-flag such a doc, but that is the SAFE direction — an over-flag
    you verify, never a swallowed drop).

    DISCLOSED LIMIT — any CROSS-script pair: whether DIFFERENT languages (a
    translation) OR the SAME language written in two scripts (a transliteration /
    romanization: Pinyin<->Han, Rōmaji<->Kana, Romanized-Korean<->Hangul). Across a
    different writing system a verbatim substring cannot be compared, so Aperture
    abstains rather than guess; a commitment both dropped AND rendered in a
    different script is missed here.

    Same-script pairs and mixed docs all return False and run unguarded:
      * CJK->CJK edit          -> not pure-Latin either side -> False.
      * Latin->Latin           -> not pure-CJK either side   -> False.
      * short terse CJK vs CJK -> below _CJK_HIGH  -> not pure      -> False.
      * CJK+URL / EN+CJK-quote -> other-script letter present -> not pure -> False.
      * clean CJK <-> clean EN -> opposite pure   -> True (declined).
      * Han <-> Pinyin         -> opposite pure   -> True (declined; the limit).

    SCOPE (F6): only CJK<->Latin is recognised; `_script_counts` knows no other
    script, so Cyrillic/Arabic/etc. pairs are never "pure-CJK" nor "pure-Latin"
    (both counts near zero) -> False and run unguarded.
    """
    cjk_a, latin_a = _script_counts(state_a)
    cjk_b, latin_b = _script_counts(state_b)
    a_pure_cjk = cjk_a >= _CJK_HIGH and latin_a <= _OTHER_FLOOR
    a_pure_latin = latin_a >= _CJK_HIGH and cjk_a <= _OTHER_FLOOR
    b_pure_cjk = cjk_b >= _CJK_HIGH and latin_b <= _OTHER_FLOOR
    b_pure_latin = latin_b >= _CJK_HIGH and cjk_b <= _OTHER_FLOOR
    return (a_pure_cjk and b_pure_latin) or (a_pure_latin and b_pure_cjk)


def _anchor_survives_translation(anchor_id: str) -> bool:
    """True iff ``anchor_id`` is a CODE-IDENTIFIER-shaped token (F1/F8).

    A code id (``ci-gates-green``, ``no_decoder_loop``, ``deliverMvp``) is
    reproduced VERBATIM when a doc is translated — it is a symbol, not prose — so
    its disappearance from a differently-scripted ``state_b`` is a REAL drop, and
    such an anchor stays checkable ACROSS scripts. A natural-language phrase does
    NOT survive translation and must be declined, not flagged.

    This is a *shape* predicate, NOT a *script* test (the old bug): a Latin
    natural-language phrase (``encrypt data at rest``) has no CJK yet is still
    prose. Heuristic — the id survives iff ALL of:
      * NO whitespace (a code id is one token; prose has spaces);
      * >= 1 ASCII Latin letter (a translated doc keeps Latin identifiers; a CJK
        phrase like ``日志保留九十天`` has none → declined);
      * NO CJK character (a mixed/CJK id would not reappear verbatim).
    A digit-only id (``90``, ``2024``) fails the Latin-letter clause and is
    declined — conservative (F8).
    """
    if any(ch.isspace() for ch in anchor_id):
        return False
    cjk, latin = _script_counts(anchor_id)
    return latin >= 1 and cjk == 0


def _partition_cross_language_anchors(
    anchors: list[Anchor],
) -> tuple[list[Anchor], list[Anchor]]:
    """Split anchors into (survivable_code_ids, declined_natural_language).

    Pure, order-preserving partition used ONLY on a cross-language pair. The
    declined list is filtered OUT before the detection loop — its anchors are
    never fed to a detector, so no violation is ever constructed-then-discarded
    (a detected violation is always surfaced, never dropped; declined = out-of-detection-scope,
    anchors flow into normal detection unchanged.
    """
    survivable: list[Anchor] = []
    declined: list[Anchor] = []
    for a in anchors:
        (survivable if _anchor_survives_translation(a.id) else declined).append(a)
    return survivable, declined


_CROSS_LANGUAGE_DECLINE_REASON = (
    "cross-language (CJK<->Latin): the two states are a clean cross-writing-system "
    "pair — one side all-CJK, the other all-Latin — a full translation OR a "
    "transliteration/romanization (e.g. Pinyin<->Han for the same Chinese), so "
    "natural-language anchors and the implicit commitment-key path cannot be "
    "compared by verbatim substring; those were declined and no drop was detected "
    "for them. A commitment both dropped and cleanly rewritten across writing "
    "systems would also be missed here. (Fires ONLY on a clean single-script "
    "CJK<->Latin pair; ANY mixed-script doc — one carrying >= 1 letter of the other "
    "script, e.g. embedded URLs/paths/code-ids, a bilingual quote, or a short terse "
    "revision — runs unguarded. Code-identifier anchors, which survive translation, "
    "are still checked. Supported writing systems: Han / Kana incl. Hentaigana / "
    "Hangul / Bopomofo + Latin, any presentation form — same-script-family pairs within "
    "that surface are never classified cross-language; codepoints outside that "
    "surface (CJK meta-glyphs, non-CJK scripts) run unguarded.)"
)


def _cross_language_reason(declined_count: int) -> str:
    """The honest decline reason, noting how many anchors were declined.

    ``declined_count`` may be 0 when the only reason to abstain was a suppressed
    implicit commitment-key path (compare_commitment) or no anchors at all.
    """
    base = _CROSS_LANGUAGE_DECLINE_REASON
    if declined_count > 0:
        return f"{base} [{declined_count} non-survivable anchor(s) declined]"
    return base


def _cross_language_declined(
    provider_family: str, profile: str | None, declined_count: int = 0
) -> DeltaResult:
    """A `degraded` comparability abstain: empty anchor_violations, honest reason.

    Returned when a cross-language pair yielded no survivable-anchor violation.
    Nothing is detected-then-discarded (detected-violations invariant untouched; detection scope is
    implementation-defined): the declined anchors were filtered out BEFORE
    the detection loop, never constructed into violations.
    """
    return DeltaResult(
        status=DeltaStatus.DEGRADED,
        reason=_cross_language_reason(declined_count),
        provider_family=provider_family,
        profile=profile,
        state_kind="text",
    )


def compare(
    state_a: str,
    state_b: str,
    anchors: list[Anchor] | None = None,
    context: object = None,
    *,
    event_id: str | None = None,
) -> DeltaResult:
    """Base compare — text diff with optional anchor checking."""
    _require_text_states(state_a, state_b)
    # F3: validate BEFORE the cross-language guard so a malformed anchor
    # (e.g. anchors=[None]) raises InvalidAnchorError even on a cross-language
    # pair, instead of a raw AttributeError from the partition. Matches
    # compare_commitment's ordering.
    anchors = _validated_anchors(anchors or [])
    if state_a == state_b and not anchors:
        return _finish(
            DeltaResult(status=DeltaStatus.OK, reason="states match", provider_family="generic"),
            event_id,
            state_a,
            state_b,
            anchors,
        )

    if state_a != state_b and _states_cross_language(state_a, state_b):
        # PER-ANCHOR cross-language handling (F1/F2): detect ONLY over survivable
        # code-id anchors; the natural-language ones are filtered out BEFORE the
        # detection loop (never constructed-then-discarded → detected-violations invariant).
        survivable, declined = _partition_cross_language_anchors(anchors)
        violations = _check_anchors_generic(state_a, state_b, survivable)
        if violations:
            return _finish(
                _result_from_violations(
                    violations, "generic", None, "text", declined_count=len(declined)
                ),
                event_id,
                state_a,
                state_b,
                survivable,
            )
        if declined or not anchors:
            result = _cross_language_declined("generic", None, len(declined))
            return result if event_id is None else replace(result, event_id=event_id)
        # All anchors survivable, none fired → the survivable pass above already
        # ran detection over the full set (declined is empty here, so
        # survivable == anchors); don't re-run _check_anchors_generic — the
        # Fall through to the no-violation diff result below with `violations`
        # (empty) reused as-is.
    else:
        violations = _check_anchors_generic(state_a, state_b, anchors)

    if violations:
        return _finish(
            _result_from_violations(violations, "generic", None, "text"),
            event_id,
            state_a,
            state_b,
            anchors,
        )

    if state_a == state_b:
        return _finish(
            DeltaResult(status=DeltaStatus.OK, reason="states match", provider_family="generic"),
            event_id,
            state_a,
            state_b,
            anchors,
        )
    return _finish(
        DeltaResult(
            status=DeltaStatus.DEGRADED,
            reason="text states differ",
            provider_family="generic",
        ),
        event_id,
        state_a,
        state_b,
        anchors,
    )


def compare_text(left: str, right: str) -> DeltaResult:
    """Deterministic scaffold text comparison (preserved for backward compat)."""
    if left == right:
        return DeltaResult(status=DeltaStatus.OK, reason="states match")
    return DeltaResult(status=DeltaStatus.DEGRADED, reason="text states differ")


# ---------------------------------------------------------------------------
# Profile: proposal
# ---------------------------------------------------------------------------

# Proposal strong/weak modal detector — bounded-F1 fixed-keyword heuristic (v0.3).
#
# English modals keep word-boundary (\b) matching in a non-capturing group.
# Chinese is appended as a MINIMAL, HIGH-PRECISION subset of bare-substring
# alternatives: CJK has no word boundaries, so \b is a no-op against Chinese and
# every Chinese term is matched as a raw contiguous substring.
#
# Scope of this detector (impl-defined heuristic, NOT a complete cross-language
# modality model):
#   - The Chinese list is deliberately small and high-precision to avoid
#     reopening cross-language determinism via false positives. It covers a few
#     unambiguous strong/weak modals only.
#   - Because Chinese matches as a bare substring, there are KNOWN edges: it does
#     not understand negation ("不必须" still matches 必须 — yields a conservative
#     false-NEGATIVE, never a spurious alarm) and a modal embedded in a longer
#     compound still counts. Terms were dropped for precision in two passes:
#     (a) inherently ambiguous: 一定 ("不一定" reverses), 需 (需要/需求 substring),
#         可能/考虑/尽量 (common non-modal POS);
#     (b) noun/compound collisions that produced confirmed false positives:
#         保证 (→ 保证金 "deposit" / 保证人), 建议 (noun "a suggestion"),
#         可以 (还可以 "not bad"), 最好 (最好的 "the best").
#     What remains is a deliberately tiny, high-precision core. See the
#     no-false-positive regression tests in tests/unit/.
_PROPOSAL_STRONG = re.compile(
    r"\b(?:must|will|shall|require|guarantee|ensure|mandatory)\b"
    r"|必须|务必|应当|确保",
    re.IGNORECASE,
)
_PROPOSAL_WEAK = re.compile(
    r"\b(?:should|may|might|could|optionally|preferably|ideally|consider)\b"
    r"|应该|也许",
    re.IGNORECASE,
)


def _count_keywords(text: str, pattern: re.Pattern[str]) -> int:
    # findall on a pattern with no capturing groups returns whole-match strings
    # (the English alternatives are now a non-capturing group), so each modal —
    # English or Chinese — counts as one occurrence. Verified by unit tests.
    return len(pattern.findall(text))


def _proposal_drift_score(a: str, b: str) -> float:
    """Higher = more drift: strong→weak regressions.

    Bounded-F1 modal detection (impl-defined heuristic; see C-103). Matches a
    fixed set of English modals (word-boundary) plus a MINIMAL HIGH-PRECISION
    Chinese subset matched as bare contiguous substrings:
      STRONG: 必须 / 务必 / 应当 / 确保
      WEAK:   应该 / 也许
    This is NOT a complete cross-language solution. Because Chinese is matched as
    a bare substring, the detector has known boundaries around long compounds and
    negation (e.g. "不必须" still matches 必须 — a conservative false-negative, not
    a spurious alarm). Terms are excluded in two passes to protect precision:
    (a) inherently ambiguous — 一定 inverts under "不一定", 需 is a substring of
    需要/需求, 可能 is often a noun/adjective, 考虑/尽量 commonly read as verbs;
    (b) noun/compound collisions confirmed to false-positive — 保证 (→ 保证金
    "deposit" / 保证人), 建议 (noun "a suggestion"), 可以 (还可以 "not bad"),
    最好 (最好的 "the best"). The remaining core is deliberately tiny.
    """
    strong_a, weak_a = _count_keywords(a, _PROPOSAL_STRONG), _count_keywords(a, _PROPOSAL_WEAK)
    strong_b, weak_b = _count_keywords(b, _PROPOSAL_STRONG), _count_keywords(b, _PROPOSAL_WEAK)
    score = 0.0
    if strong_a > 0 and strong_b < strong_a:
        score += 0.4
    if weak_b > weak_a:
        score += 0.3
    if strong_a > 0 and strong_b == 0:
        score += 0.3
    return min(score, 1.0)


def compare_proposal(
    state_a: str,
    state_b: str,
    anchors: list[Anchor] | None = None,
    context: object = None,
    *,
    event_id: str | None = None,
) -> DeltaResult:
    """Self-consistency check: proposal at t-1 vs t.

    Detects strong→weak keyword regressions (e.g. 'must' → 'should').
    If anchors are provided, checks each constraint/goal anchor for presence in both states.
    """
    _require_text_states(state_a, state_b)
    anchors = _validated_anchors(anchors or [])

    # F4: same PER-ANCHOR cross-language handling as compare/compare_commitment.
    # Detect only over survivable code-id anchors; decline the natural-language
    # ones (filtered out BEFORE the loop →
    # detected-violations invariant preserved). The keyword drift
    # detector is also suppressed on a cross-language pair (a translated modal
    # can't be compared verbatim).
    cross_language = state_a != state_b and _states_cross_language(state_a, state_b)
    active_anchors, declined = (
        _partition_cross_language_anchors(anchors) if cross_language else (anchors, [])
    )

    violations: list[AnchorViolation] = []

    for a in active_anchors:
        if a.kind in (AnchorKind.CONSTRAINT, AnchorKind.GOAL):
            if not _anchor_text_present(a.id, state_b):
                violations.append(
                    AnchorViolation(
                        anchor_id=a.id,
                        kind=a.kind,
                        status=_violation_status_for_kind(a.kind),
                        detail=f"anchor '{a.id}' not reflected in current proposal state",
                    )
                )

    if violations:
        return _finish(
            _result_from_violations(
                violations, "self-consistency", "proposal", "text", declined_count=len(declined)
            ),
            event_id,
            state_a,
            state_b,
            anchors,
        )

    if cross_language and (declined or not active_anchors):
        result = _cross_language_declined("self-consistency", "proposal", len(declined))
        return result if event_id is None else replace(result, event_id=event_id)

    score = 0.0 if cross_language else _proposal_drift_score(state_a, state_b)
    if score >= 0.5:
        return _finish(
            DeltaResult(
                status=DeltaStatus.DEGRADED,
                reason=f"proposal drift score {score:.2f} — strong commitments weakened",
                provider_family="self-consistency",
                profile="proposal",
                state_kind="text",
            ),
            event_id,
            state_a,
            state_b,
            anchors,
            detector_fired=True,
        )
    if state_a == state_b:
        return _finish(
            DeltaResult(
                status=DeltaStatus.OK,
                reason="proposal consistent",
                provider_family="self-consistency",
                profile="proposal",
                state_kind="text",
            ),
            event_id,
            state_a,
            state_b,
            anchors,
        )
    return _finish(
        DeltaResult(
            status=DeltaStatus.OK,
            reason="proposal: no strong→weak drift detected (minor textual change)",
            provider_family="self-consistency",
            profile="proposal",
            state_kind="text",
        ),
        event_id,
        state_a,
        state_b,
        anchors,
    )


# ---------------------------------------------------------------------------
# Profile: stance
# ---------------------------------------------------------------------------

_STANCE_POSITIVE = re.compile(
    r"\b(support|endorse|recommend|favor|approve|agree|accept|adopt|back)\b",
    re.IGNORECASE,
)
_STANCE_NEGATIVE = re.compile(
    r"\b(oppose|reject|decline|refuse|disagree|against|veto|object|challenge)\b",
    re.IGNORECASE,
)


def _stance_polarity(text: str) -> int:
    pos = _count_keywords(text, _STANCE_POSITIVE)
    neg = _count_keywords(text, _STANCE_NEGATIVE)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def compare_stance(
    state_a: str,
    state_b: str,
    anchors: list[Anchor] | None = None,
    context: object = None,
    *,
    event_id: str | None = None,
) -> DeltaResult:
    """Self-consistency check: stance at t-1 vs t.

    Detects polarity reversal (support→oppose or oppose→support).
    Checks anchor presence in both states for goal/baseline anchors.
    """
    _require_text_states(state_a, state_b)
    anchors = _validated_anchors(anchors or [])

    # F4: same PER-ANCHOR cross-language handling. Detect only over survivable
    # code-id anchors; decline natural-language ones (filtered BEFORE the loop →
    # detected-violations invariant preserved). Polarity reversal is also
    # suppressed on a cross-language
    # pair (a translated stance verb can't be matched verbatim).
    cross_language = state_a != state_b and _states_cross_language(state_a, state_b)
    active_anchors, declined = (
        _partition_cross_language_anchors(anchors) if cross_language else (anchors, [])
    )

    violations: list[AnchorViolation] = []

    for a in active_anchors:
        if a.kind in (AnchorKind.GOAL, AnchorKind.BASELINE):
            if not _anchor_text_present(a.id, state_b):
                violations.append(
                    AnchorViolation(
                        anchor_id=a.id,
                        kind=a.kind,
                        status=_violation_status_for_kind(a.kind),
                        detail=f"anchor '{a.id}' not reflected in current stance (drift)",
                    )
                )

    if violations:
        return _finish(
            _result_from_violations(
                violations, "self-consistency", "stance", "text", declined_count=len(declined)
            ),
            event_id,
            state_a,
            state_b,
            anchors,
        )

    if cross_language and (declined or not active_anchors):
        result = _cross_language_declined("self-consistency", "stance", len(declined))
        return result if event_id is None else replace(result, event_id=event_id)

    pol_a = 0 if cross_language else _stance_polarity(state_a)
    pol_b = 0 if cross_language else _stance_polarity(state_b)
    if pol_a != 0 and pol_b != 0 and pol_a != pol_b:
        return _finish(
            DeltaResult(
                status=DeltaStatus.DEGRADED,
                reason="stance polarity reversed between states",
                provider_family="self-consistency",
                profile="stance",
                state_kind="text",
            ),
            event_id,
            state_a,
            state_b,
            anchors,
            detector_fired=True,
        )
    if state_a == state_b:
        return _finish(
            DeltaResult(
                status=DeltaStatus.OK,
                reason="stance consistent",
                provider_family="self-consistency",
                profile="stance",
                state_kind="text",
            ),
            event_id,
            state_a,
            state_b,
            anchors,
        )
    return _finish(
        DeltaResult(
            status=DeltaStatus.OK,
            reason="stance: no polarity reversal detected (textual change only)",
            provider_family="self-consistency",
            profile="stance",
            state_kind="text",
        ),
        event_id,
        state_a,
        state_b,
        anchors,
    )


# ---------------------------------------------------------------------------
# Profile: commitment
# ---------------------------------------------------------------------------

_COMMITMENT_RE = re.compile(
    r"(?:commit\s*(?:to|ted\s*to)?|promise\s*(?:to|d)?|will\s+deliver|guarantee\s*(?:to|d)?|ensure\s*(?:that|s)?)\s+(.+?)(?:[.!?;]|$)",
    re.IGNORECASE,
)


def _extract_commitment_key(text: str) -> list[str]:
    keys: list[str] = []
    for m in _COMMITMENT_RE.finditer(text):
        key = m.group(1).strip().rstrip(".,;").lower()
        key = re.sub(r"\s+", " ", key)
        if len(key) > 3:
            keys.append(key)
    return keys


def _key_preserved(key_a: str, keys_b: list[str]) -> bool:
    """A key is preserved if it is a substring of any key_b or any key_b subsumes it."""
    for kb in keys_b:
        if key_a in kb or kb in key_a:
            return True
    return False


def _dropped_keys(keys_a: list[str], keys_b: list[str]) -> list[str]:
    return [k for k in keys_a if not _key_preserved(k, keys_b)]


def compare_commitment(
    state_a: str,
    state_b: str,
    anchors: list[Anchor] | None = None,
    context: object = None,
    *,
    event_id: str | None = None,
) -> DeltaResult:
    """Self-consistency check: commitment at t-1 vs t.

    Extracts commitment phrases from both states.  A commitment present in
    state_a but missing or weakened in state_b triggers a DROPPED_SILENTLY
    violation.  Anchors of kind COMMITMENT that reference id-like tokens
    missing from state_b also trigger violations.
    """
    _require_text_states(state_a, state_b)
    anchors = _validated_anchors(anchors or [])

    # PER-ANCHOR cross-language handling (F1/F2/F5). On a CJK<->Latin translation
    # pair we (a) detect only over SURVIVABLE code-id anchors, (b) DECLINE the
    # natural-language anchors by filtering them out BEFORE the loop, and (c)
    # SUPPRESS the implicit commitment-key path entirely (extracted keys are
    # natural-language phrases → they FP on a faithful translation). The declined
    # anchors and implicit keys are never turned into violations (detected-violations invariant).
    cross_language = state_a != state_b and _states_cross_language(state_a, state_b)
    if cross_language:
        active_anchors, declined = _partition_cross_language_anchors(anchors)
    else:
        active_anchors, declined = anchors, []

    violations: list[AnchorViolation] = []

    keys_a = _extract_commitment_key(state_a)
    keys_b = _extract_commitment_key(state_b)
    # F5: suppress implicit commitment-key drops in the cross-language branch only
    # (do NOT globally gate _dropped_keys — same-language implicit drops must stay).
    dropped = [] if cross_language else _dropped_keys(keys_a, keys_b)

    # commitment anchor 关联到被丢弃承诺、或 id 不在 state_b → 每锚一条 explicit
    # violation；记下被认领的 dropped key，避免再重复成 implicit（去重）。
    claimed: set[str] = set()
    for a in active_anchors:
        if a.kind != AnchorKind.COMMITMENT:
            continue
        aid = a.id.lower()
        matched = [k for k in dropped if aid in k or k in aid]
        in_a = _anchor_text_present(a.id, state_a)
        in_b = _anchor_text_present(a.id, state_b)
        if (matched or in_a) and not in_b:
            violations.append(
                AnchorViolation(
                    anchor_id=a.id,
                    kind=a.kind,
                    status=DeltaStatus.DROPPED_SILENTLY,
                    detail=f"commitment '{a.id}' present in prior state but missing from current",
                )
            )
            claimed.update(matched)

    # 未被任何 anchor 认领的被丢弃承诺 → 一条 implicit violation
    # (dropped is [] under cross_language, so this never fires there — F5.)
    unclaimed = [k for k in dropped if k not in claimed]
    if unclaimed:
        violations.append(
            AnchorViolation(
                anchor_id="implicit",
                kind=AnchorKind.COMMITMENT,
                status=DeltaStatus.DROPPED_SILENTLY,
                detail=f"commitments dropped silently: {', '.join(sorted(unclaimed))}",
            )
        )

    # Cross-language with no survivable violation → honest decline (empty
    # anchor_violations). Only abstain when we actually declined something (a
    # non-survivable anchor, or the suppressed implicit path when no survivable
    # anchor could carry the signal); if every anchor survived and simply held,
    # fall through to the normal consistent/drift result.
    if cross_language and not violations and (declined or not active_anchors):
        result = _cross_language_declined("self-consistency", "commitment", len(declined))
        return result if event_id is None else replace(result, event_id=event_id)

    if violations:
        return _finish(
            _result_from_violations(
                violations, "self-consistency", "commitment", "text", declined_count=len(declined)
            ),
            event_id,
            state_a,
            state_b,
            anchors,
        )

    # The implicit key-COUNT drift detector also runs over natural-language keys,
    # so it is suppressed on a cross-language pair (F5): a faithful translation
    # legitimately drops the CJK/Latin key count to zero on the other side.
    if not cross_language and _commitment_drift_detected(keys_a, keys_b):
        return _finish(
            DeltaResult(
                status=DeltaStatus.DEGRADED,
                reason="commitment strength weakened between states",
                provider_family="self-consistency",
                profile="commitment",
                state_kind="text",
            ),
            event_id,
            state_a,
            state_b,
            anchors,
            detector_fired=True,
        )
    if state_a == state_b:
        return _finish(
            DeltaResult(
                status=DeltaStatus.OK,
                reason="commitment consistent",
                provider_family="self-consistency",
                profile="commitment",
                state_kind="text",
            ),
            event_id,
            state_a,
            state_b,
            anchors,
        )
    return _finish(
        DeltaResult(
            status=DeltaStatus.OK,
            reason="commitment: no dropped commitments detected (textual change only)",
            provider_family="self-consistency",
            profile="commitment",
            state_kind="text",
        ),
        event_id,
        state_a,
        state_b,
        anchors,
    )


def _commitment_drift_detected(keys_a: list[str], keys_b: list[str]) -> bool:
    return len(keys_a) > 0 and len(keys_b) < len(keys_a) * 0.5


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

# The eight-value severity total order (highest to lowest):
#   BLOCKED > provider_unavailable > PAUSED > DROPPED_SILENTLY
#   > domain_mismatch > incomparable > degraded > ok
# The most severe status across all sub-results wins.
_SEVERITY_ORDER: dict[DeltaStatus, int] = {
    DeltaStatus.OK: 0,
    DeltaStatus.DEGRADED: 1,
    DeltaStatus.INCOMPARABLE: 2,
    DeltaStatus.DOMAIN_MISMATCH: 3,
    DeltaStatus.DROPPED_SILENTLY: 4,
    DeltaStatus.PAUSED: 5,
    DeltaStatus.PROVIDER_UNAVAILABLE: 6,
    DeltaStatus.BLOCKED: 7,
}


def _most_severe(statuses: list[DeltaStatus]) -> DeltaStatus:
    return max(statuses, key=lambda s: _SEVERITY_ORDER.get(s, 0))


def aggregate_status(statuses: list[DeltaStatus]) -> DeltaStatus:
    """Aggregate a list of DeltaStatus values using P22 eight-value total order.

    Returns the most severe status in the list. An empty list returns
    ``DeltaStatus.OK``.
    """
    if not statuses:
        return DeltaStatus.OK
    return _most_severe(statuses)


# anchor kind → violation severity semantics:
#   constraint violation → BLOCKED (hard constraint; decision-maker must explicitly ack)
#   commitment silently dropped → DROPPED_SILENTLY
#   goal / baseline drift → degraded (soft drift, not hard-blocking / not silently dropped)
_KIND_VIOLATION_STATUS: dict[AnchorKind, DeltaStatus] = {
    AnchorKind.CONSTRAINT: DeltaStatus.BLOCKED,
    AnchorKind.COMMITMENT: DeltaStatus.DROPPED_SILENTLY,
    AnchorKind.GOAL: DeltaStatus.DEGRADED,
    AnchorKind.BASELINE: DeltaStatus.DEGRADED,
}


def _violation_status_for_kind(kind: AnchorKind) -> DeltaStatus:
    return _KIND_VIOLATION_STATUS.get(kind, DeltaStatus.DEGRADED)


def _result_from_violations(
    violations: list[AnchorViolation],
    family: str,
    profile: str | None,
    kind: str,
    declined_count: int = 0,
) -> DeltaResult:
    primary = _most_severe([v.status for v in violations])
    reasons = "; ".join(f"[{v.anchor_id}] {v.detail or v.status.value}" for v in violations)
    # When a survivable code-id FIRED but other anchors were
    # declined cross-language, surface the declined count on the fired-path reason
    # too (the decline path already carries it) so the note is never lost on a
    # mixed fired+declined result.
    if declined_count > 0:
        reasons = f"{reasons} [{declined_count} non-survivable anchor(s) declined]"
    return DeltaResult(
        status=primary,
        reason=reasons,
        provider_family=family,
        profile=profile,
        state_kind=kind,
        anchor_violations=list(violations),
    )


def _anchor_text_present(anchor_id: str, text: str) -> bool:
    """Heuristic: check if anchor id tokens appear in text."""
    return anchor_id.lower() in text.lower()


# Deterministic digit-run counter for the numeric blind-spot fact. It counts
# whether numeric tokens are PRESENT/ABSENT only — it NEVER compares magnitudes
# or orders numbers (count only token presence/absence; never compare magnitude or assign meaning).
_DIGIT_RUN = re.compile(r"\d+")


def _blindspot_notes(
    state_a: str,
    state_b: str,
    anchors: list[Anchor],
    result: DeltaResult,
) -> list[str]:
    """Honest blind-spot reason notes — the blind-spot white-list rules.

    Pure function of the inputs + the ALREADY-COMPUTED ``result``. Returns 0..3 of
    the three white-listed wordings, each a first-person STATEMENT OF FACT about
    what this surface-level (substring + keyword) detector did and did NOT cover —
    never a verdict on which state is better/worse and never a disposition about
    what the caller should do. Every quantity below is a local length / substring /
    token-count over the inputs; there is no semantic call.

    Caller (:func:`_finish`) only invokes this when ``result.anchor_violations``
    is empty, but the predicates are re-checked here so the helper is correct in
    isolation. Each wording embeds its self-cover white-list phrase verbatim
    ("large textual change with no anchor" / "no anchors supplied" /
    "numeric tokens or modal" + "directional anchor tracking inactive"), and none
    contains a directional token — so the directional-token checker returns [] on every
    appended reason.
    """
    if result.anchor_violations:
        return []

    notes: list[str] = []

    # Fact 1 — large_surface_change_no_anchor_violation (incl. overlap-churn core).
    # Fires when no detector/anchor violation fired AND no supplied anchor matched
    # in EITHER state (trivially true when anchors == []) AND a paraphrase-scale
    # surface-magnitude rewrite is present (>= 50% length delta). All local.
    no_anchor_matched = all(
        not _anchor_text_present(a.id, state_a) and not _anchor_text_present(a.id, state_b)
        for a in anchors
    )
    if no_anchor_matched:
        denom = max(len(state_a), len(state_b), 1)
        if abs(len(state_b) - len(state_a)) / denom >= 0.5:
            notes.append(
                "large textual change with no anchor or keyword detector hit — "
                "substring/keyword detectors do not cover paraphrase-scale rewrites"
            )

    # Fact 2 — anchors_absent_or_sparse. Narrowest, purely len(anchors): the
    # directional anchor-tracking channel was structurally inactive for this call.
    # Deliberately omits any "supply an anchor" direction-verb (blind-spot ban).
    if len(anchors) == 0:
        notes.append(
            "no anchors supplied — directional anchor tracking inactive for this comparison"
        )

    # Fact 3 — numeric_or_modal_surface_change (narrow, counting-only). Fires when
    # no strength threshold was crossed yet a local TOKEN-PRESENCE COUNT differs:
    # modal-keyword counts or digit-run counts. It only counts whether tokens are
    # present/absent — it never compares magnitudes or assigns the change meaning.
    modal_a = _count_keywords(state_a, _PROPOSAL_STRONG) + _count_keywords(state_a, _PROPOSAL_WEAK)
    modal_b = _count_keywords(state_b, _PROPOSAL_STRONG) + _count_keywords(state_b, _PROPOSAL_WEAK)
    digits_a = len(_DIGIT_RUN.findall(state_a))
    digits_b = len(_DIGIT_RUN.findall(state_b))
    if modal_a != modal_b or digits_a != digits_b:
        notes.append(
            "numeric tokens or modal-keyword counts differ but no strength detector "
            "threshold was crossed — magnitude/ordering of numeric change is outside "
            "surface-count coverage"
        )

    return notes


def _check_anchors_generic(
    state_a: str,
    state_b: str,
    anchors: list[Anchor],
) -> list[AnchorViolation]:
    """Generic anchor check: any anchor id referenced in state_a but missing from state_b."""
    violations: list[AnchorViolation] = []
    for a in _validated_anchors(anchors):
        in_a = _anchor_text_present(a.id, state_a)
        in_b = _anchor_text_present(a.id, state_b)
        if in_a and not in_b:
            violations.append(
                AnchorViolation(
                    anchor_id=a.id,
                    kind=a.kind,
                    status=_violation_status_for_kind(a.kind),
                    detail=f"anchor '{a.id}' present in state_a but missing from state_b",
                )
            )
    return violations
