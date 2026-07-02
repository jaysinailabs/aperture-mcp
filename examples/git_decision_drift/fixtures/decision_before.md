# ADR-007: Release gating policy

## Decision

Before any production release, we commit to:

- **ci-gates-green** — every CI gate passes on the exact release commit.
- **data-never-leaves-device** — user data is processed locally and is never sent off-device.

## Status

Accepted.
