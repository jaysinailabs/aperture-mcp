# Aperture commitment tripwire — git hook wrappers

Deterministic, **LLM-free** git preflight. `aperture check` reads a `.aperture.toml`
watchlist at your repo root and, using the **frozen** compare engine, flags every
watched commitment whose **verbatim** text disappeared between two git states. It is a
**signal, not a judge** — blind to paraphrase / softening; it catches only verbatim
disappearance. Bypass any block with `git commit --no-verify`.

First, create your watchlist:

```sh
cp examples/git_decision_drift/.aperture.toml.example .aperture.toml
# edit .aperture.toml — list the files + commitment tokens you care about
```

## Option A — standalone hook (no framework)

```sh
cp examples/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook runs `aperture check --staged` (compares the staged blobs vs `HEAD`) and
blocks the commit if a watched commitment dropped. It fails **open** if `aperture`
is not installed, so it never bricks commits on a machine without the tool.

## Option B — pre-commit.com framework

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/jaysinailabs/aperture-mcp
    rev: v0.2.0
    hooks:
      - id: aperture-commitment-drift
```

The hook id `aperture-commitment-drift` is defined in this repository's root
`.pre-commit-hooks.yaml`. It runs `aperture check` with `always_run: true` and
`pass_filenames: false` (Aperture reads its own `.aperture.toml`, not the staged
file list).

## Option C — CI / GitHub Action

See `examples/github-action/aperture-check.yml` — runs
`aperture check --ref-a <base> --ref-b <head>` on every pull request.

## Install the tool

```sh
pip install aperture-mcp     # provides both `aperture` and `aperture-mcp`
```
