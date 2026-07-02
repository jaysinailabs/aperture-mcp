---
name: Bug report / 缺陷报告
about: Something is broken or behaves unexpectedly / 某处坏了或行为异常
title: "[bug] "
labels: ["bug"]
---

### What happened / 发生了什么

A clear description of the bug. / 清楚描述这个缺陷。

### To reproduce / 复现步骤

Minimal steps or a code snippet. If it involves `compare`, include the `state_a` / `state_b` /
`anchors` you passed (redact text you can't share).
最小复现步骤或代码片段。若涉及 `compare`,附上你传入的 `state_a` / `state_b` / `anchors`
(不能公开的文本请打码)。

### Expected vs actual / 预期 vs 实际

- Expected / 预期:
- Actual / 实际:

### Environment / 环境

- `aperture-mcp` version / 版本:
- Python version / 版本:
- OS / 操作系统:
- MCP client (if relevant) / MCP 客户端(若相关):

> Reminder: Aperture MCP is a heuristic with known blind spots (misses reworded commitments,
> declines/abstains on translations, still false-flags reformats — see the
> [limits](../../docs/measured-limits.md)). A missed/false-flagged *drift* is usually a
> **drift case report**, not a bug.
> 提醒:Aperture MCP 是有已知盲区的启发式(漏掉被改写的承诺、对翻译拒判(abstain)、对重排版仍误报——见
> [局限](../../docs/measured-limits.md))。漏报/误报*漂移*通常应走 **drift case report**,而非 bug。
