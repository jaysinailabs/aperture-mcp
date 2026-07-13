"""CLI tests for ``aperture check`` — the fail-closed guarantees.

These pin the invariant that a watched commitment the CLI cannot actually see
(missing path, wording absent from both states, undecodable baseline) is
surfaced as UNTRACKABLE instead of being folded into "intact". A tripwire may
be blind, but it must never report a zone it isn't covering as clear.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from aperture.cli import _git_show, main

COMMITMENT = "data never leaves the device"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, **GIT_ENV},
    )


def _make_repo(tmp_path: Path, doc_text: str, watch_path: str = "DECISIONS.md") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    (repo / "DECISIONS.md").write_text(doc_text, encoding="utf-8")
    (repo / ".aperture.toml").write_text(
        f'fail_on_drop = true\n\n[[watch]]\npath = "{watch_path}"\n'
        f'commitments = ["{COMMITMENT}"]\n',
        encoding="utf-8",
    )
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "init")
    return repo


def test_verbatim_drop_is_flagged_and_blocks(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path, f"Our commitments:\n- {COMMITMENT}\n")
    (repo / "DECISIONS.md").write_text("Our commitments:\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    assert main(["check"]) == 1
    assert "DROPPED" in capsys.readouterr().out


def test_intact_commitment_passes(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path, f"Our commitments:\n- {COMMITMENT}\n")
    monkeypatch.chdir(repo)
    assert main(["check"]) == 0
    assert "intact" in capsys.readouterr().out


def test_missing_watch_path_is_untrackable_not_intact(tmp_path: Path, monkeypatch, capsys) -> None:
    """A typo'd watchlist path must not produce a confident 'intact'."""
    repo = _make_repo(tmp_path, f"- {COMMITMENT}\n", watch_path="TYPO-does-not-exist.md")
    monkeypatch.chdir(repo)
    assert main(["check"]) == 2
    out = capsys.readouterr().out
    assert "UNTRACKABLE" in out
    assert "intact" not in out


def test_commitment_absent_from_both_states_is_untrackable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Misquoted / encoding-mismatched wording: watched text found nowhere."""
    repo = _make_repo(tmp_path, "No such promise here, before or after.\n")
    monkeypatch.chdir(repo)
    assert main(["check"]) == 2
    assert "UNTRACKABLE" in capsys.readouterr().out


def test_newly_adopted_commitment_is_not_untrackable(tmp_path: Path, monkeypatch, capsys) -> None:
    """Adding the commitment and its watch entry in the same commit stays legal."""
    repo = _make_repo(tmp_path, "Nothing yet.\n")
    (repo / "DECISIONS.md").write_text(f"Now we promise:\n- {COMMITMENT}\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "UNTRACKABLE" not in out


def test_warn_only_downgrades_untrackable_to_exit_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path, f"- {COMMITMENT}\n", watch_path="TYPO-does-not-exist.md")
    monkeypatch.chdir(repo)
    assert main(["check", "--warn-only"]) == 0
    assert "UNTRACKABLE" in capsys.readouterr().out


def test_git_show_decodes_non_ascii_blobs_on_any_locale(tmp_path: Path) -> None:
    """_git() must decode git output as UTF-8 explicitly. On a non-UTF-8 locale
    (e.g. GBK Windows) the locale codec chokes on these bytes inside subprocess's
    reader thread and stdout comes back as None with returncode 0 — which then
    fails open. Trivially green on UTF-8 platforms; a real regression guard on
    CJK-locale Windows."""
    repo = _make_repo(tmp_path, f"note — “curly” em dash\n- {COMMITMENT}\n")
    text = _git_show(str(repo), "HEAD:DECISIONS.md")
    assert text is not None
    assert COMMITMENT in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
