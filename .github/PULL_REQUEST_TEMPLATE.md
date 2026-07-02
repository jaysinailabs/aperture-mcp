### What this changes / 这个改动做了什么

A short description. / 简短描述。

### Checklist / 检查清单

- [ ] The **compare contract (`v0.2`)** is unchanged — or this is a deliberate, reviewed protocol
      change (see [VERSIONING.md](../VERSIONING.md)).
      **compare 契约(`v0.2`)未变**——或这是一次审慎、经评审的协议改动(见 [VERSIONING.md](../VERSIONING.md))。
- [ ] If this changes what the tool can or can't see, the **limits** are updated in the same PR
      (README table + `docs/measured-limits.md`).
      若改变了“工具能看见 / 看不见什么”,在**同一 PR**里更新局限(README 表 + `docs/measured-limits.md`)。
- [ ] No new over-claim: nothing implies Aperture MCP catches drift it doesn't (verbatim substrings only;
      misses rewording, declines/abstains on translation, still false-flags reformats).
      无新增 over-claim:没有任何措辞暗示它能抓它抓不到的漂移(只匹配逐字子串;漏改写、对翻译拒判(abstain)、对重排版仍误报)。
- [ ] Tests / linters pass locally. / 本地测试 / linter 通过。
