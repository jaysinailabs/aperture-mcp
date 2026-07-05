# Security & privacy

## Privacy posture

Aperture is designed to be boring on privacy, in the good way:

- **Local by default.** The library and the MCP server run in your process. They make **no network
  calls**.
- **No training on your data.** Your decision text is never collected, transmitted, or used to train
  anything.
- **Metadata-only logging.** Usage logging is **off by default**; when enabled it records only
  timestamp / tool / status / counts — never decision text or commitment wording. See
  [CONTRIBUTING.md](./CONTRIBUTING.md) for the boundary between the metadata log and explicit,
  opt-in case contribution (which *does* send text, only when you choose).

## Reporting a vulnerability

If you find a security issue, please **do not** open a public issue. Email the maintainer (see the
repository profile) with details and a reproduction. We’ll acknowledge and work a fix; please give us
a reasonable window before public disclosure.

## Scope notes

Aperture is a **heuristic signal, not a security control**. It misses reworded commitments,
**declines/abstains** on translated ones (returns `degraded`, never false-flags across scripts), and
still false-flags reformatted ones (see the README limits table). Do **not** wire it as a sole gate on
anything that matters — treat every flag as “look here,” and never assume silence means nothing changed.
