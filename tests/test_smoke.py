"""Smoke tests for the public Aperture MCP package.

The contract is covered in depth by the conformance suite (``conformance/runner.py``); these are a
fast sanity layer that the package imports and the one capability it reliably has — verbatim
commitment-drop — fires correctly, and does not false-fire when the commitment holds.
"""

from __future__ import annotations

from aperture import Anchor, AnchorKind, __version__, compare


def test_package_imports_with_version() -> None:
    assert isinstance(__version__, str) and __version__


def test_verbatim_commitment_drop_is_flagged() -> None:
    result = compare(
        state_a="We commit to: ci-gates-green before every release.",
        state_b="We commit to: ship it.",
        anchors=[Anchor(kind=AnchorKind.COMMITMENT, id="ci-gates-green")],
    )
    assert any(v.anchor_id == "ci-gates-green" for v in result.anchor_violations)


def test_held_commitment_is_not_flagged() -> None:
    result = compare(
        state_a="We commit to: data-never-leaves-device.",
        state_b="We still commit to: data-never-leaves-device, no exceptions.",
        anchors=[Anchor(kind=AnchorKind.COMMITMENT, id="data-never-leaves-device")],
    )
    assert not any(v.anchor_id == "data-never-leaves-device" for v in result.anchor_violations)
