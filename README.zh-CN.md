<!-- mcp-name: io.github.jaysinailabs/aperture-mcp -->

<div align="center">

# Aperture MCP

### 你的 agent 是不是悄悄把一条承诺从你的 spec 里删掉了——还没人发现?

[![PyPI](https://img.shields.io/badge/pypi-aperture--mcp-blue)](https://pypi.org/project/aperture-mcp/) [![MCP](https://img.shields.io/badge/MCP-server-purple)](https://modelcontextprotocol.io) [![License](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE) [![status](https://img.shields.io/badge/status-early%2Fpre--1.0-orange)](./VERSIONING.md)

[English](./README.md) · **简体中文**

</div>

AI agents 正在改写那些约束你工作的文档——spec、计划、ADR、charter、`AGENTS.md`。
就在这些改动里,你早先立的一条约束,可能悄悄就没了。

**Aperture MCP 是一根*承诺绊线（commitment tripwire）*。** 你点名你在意的承诺;当其中一条在
一份决策文档的两个版本之间**逐字消失**时,它把它**标出来**。

> **一个信号,不是裁判。** 它只是被触发;**你**去查。
> Opt-in · 本地运行 · 绝不拿你的数据训练。

---

## 它是什么(以及不是什么)

Aperture MCP 是一个小巧的工具(也是纯 Python 库),
它比较**同一个决策的两段文本**——一个早版本、一个晚版本——并在一条**被追踪的承诺、其确切文本
消失了**的时候把它浮现出来。

- ✅ **它能**:标出一条你**逐字**列入清单的承诺——在 A 版里有、在 B 版里没了——跨 commit、
  跨会话、跨作者皆可。它返回一个结构化、可比较的结果,**并把自己的盲区写在标签上**。
- ❌ **它不能**:理解含义。它把文本当**大小写不敏感的子串**来匹配,所以它**会漏**一条被
  *改写 / 软化 / 转述*的承诺(看起来没丢,其实承诺被弱化了);对一条只是被*翻译*的承诺,它会
  **拒判/弃权(abstain)**——它无法跨书写系统逐字比较,于是返回 `degraded` 而不是误报;而对一条
  只是被*重排版*的承诺,它仍**可能误报**(字面变了、意思没变)。它不排序选项、不评分、也不告诉你
  某个改动是*错的*。**那个判断,归你。**

一句话:**Aperture MCP 是"找消失承诺的 `grep`",外面包了一层——让 agent 能在任务中途调用它,
拿到一个结构化、且会坦白自己看不见什么的答案。**

---

## 快速上手(约 2 分钟)

```sh
pip install aperture-mcp
```

跑一下自带示例(先 clone 本仓)——它针对仓内 fixtures 在一条被删的承诺上触发,无需配置、
无需 API key、完全离线:

```sh
python3 examples/git_decision_drift/git_decision_drift.py
```

```text
Aperture MCP · commitment tripwire — a fixture/sample decision-doc edit

  [TRIPPED ] 'ci-gates-green'             (in_before=True, in_after=False)
  [ held  ] 'data-never-leaves-device'   (in_before=True, in_after=True)

  One watched commitment vanished between the two versions; one held.
  Aperture MCP makes the disappearance visible — you decide whether it was intended.
```

在你自己的代码里用:

```python
from aperture import compare, Anchor, AnchorKind

result = compare(
    state_a="We commit to: ci-gates-green before release; data-never-leaves-device.",
    state_b="We commit to: data-never-leaves-device.",
    anchors=[Anchor(kind=AnchorKind.COMMITMENT, id="ci-gates-green")],
)
print(result.status)            # DROPPED_SILENTLY
print(result.anchor_violations) # 那条消失的承诺
```

接进 MCP 客户端(Cursor、Cline、Goose,或任何支持 stdio 的宿主):

```jsonc
{
  "mcpServers": {
    "aperture-mcp": { "command": "aperture-mcp" }
  }
}
```

> 想零安装?把命令换成 `uvx`:`{ "command": "uvx", "args": ["aperture-mcp"] }`。

---

## 一个你会认得的场景

一个长任务里,你的 agent 不停地改它手上的那份文档——一份计划、一份 spec——跨会话、跨一轮轮编辑。
时不时,一句要紧的话就这么……没了。

*“删任何东西前,先问一句。”* 没了。
*“用户数据绝不离开设备。”* 没了。
*“免费档永远免费。”* 没了。

没人存心删,也没人真去读那 400 行 diff。

Aperture MCP 只盯你点名的那几行。给它文档的两个版本,它不会去理解、也不做判断——它只告诉你:
哪一句上一版还在、一字不差,这一版没了。一根绊线,不是判官——而且它对别的很老实:把一句软化、
换个说法、或者改个数字而不是删掉,它就会溜过去。这话先说给你听。

---

## 什么能触发它——什么会溜过去

Aperture MCP 是个**启发式**。我们在自己的金标语料上测过它,并且**把数字公开**、而不是只报一个
好看的总分——因为**知道它在哪里看不见,才是这个产品本身**——**召回 0.375、精确率 0.75**
(41 例语料,24 条真实漂移里逮住 9 条;标出的每 4 条约 1 条是噪声),完整拆解见
[docs/measured-limits.md](docs/measured-limits.md):

| 改动类型 | Aperture MCP 会标出吗? |
| --- | --- |
| 一条被追踪的承诺**被逐字删除** | ✅ 可靠——这是它唯一擅长的 |
| 承诺**被改写 / 软化**（“必须”→“应该”） | ❌ **漏掉**——文本仍然“匹配” |
| 承诺**被转述 / 重组** | ❌ **漏掉** |
| 某个数字 / 范围 / 否定被悄悄改动 | ❌ **漏掉** |
| 承诺**被翻译**成另一种语言 | ⚠️ 对**自然语言**锚点 **拒判(abstain)**——它无法跨书写系统逐字比较,于是返回 `degraded` 而不是误报(此处一条既被删又被翻译的承诺会被漏掉) |

> **这一行取决于锚点风格**:弃权只针对**自然语言**锚点。**代码标识符**锚点(quickstart 教的 `ci-gates-green` 那种)被视为*跨语言稳定*——Aperture 会继续跨语言核它,所以那个 token 一旦消失,它仍会标 `DROPPED_SILENTLY`(对稳定标识符而言通常正是你想要的)。

**要点**:把每一次触发当作*“看这里”*,而**绝不**当作*“这是错的”*——也绝不要以为没触发就等于
没漂移。Aperture MCP 把**逐字消失**这一种情形抓得很好,并且坦白它抓不到别的太多。这个又窄又可靠的
信号有用,**恰恰因为**它不假装自己更强。

> **在你自己的文档上撞到这些漏报了?** 这是你能发给我们的最有用的东西——
> [30 秒报一个](#撞到漏报帮它变好)(措辞可选填)。真实的漏报指引我们**下一个先补哪个盲区**。

> 为什么不直接 `git diff`?核心这一步你确实能用 `grep` 复现。Aperture MCP 多出来的是:**agent
> 能在任务中途调用它**(经 MCP),它返回一个**结构化、有方向的结果**
> (`ok` / `degraded` / `DROPPED_SILENTLY` / …),并**把自己的盲区写进结果里**让人能审。
> 它是围绕一个简单、清楚的检查所做的**人体工学 + 诚实**——不是更聪明的检测器。

---

## 为什么有它

长期运行、多 agent 的工作流会漂移。第 3 轮 / 第 1 个会话 / agent A 立下的一条约束,四十轮后、
在另一个会话里、被 agent B 悄悄改没了——直到它发布出去都没人察觉。Aperture MCP 是你能挂在
**agent 维护的那些文档**上的一道**预检(preflight)**:点名那些不许悄悄消失的承诺,一旦消失,
就给你一根绊线。

它刻意做得**小而清晰**。它不是替你做决定的 AI;它是帮**你**与自己保持一致的一个信号。

---

## 它适合谁

那些**(a)** 让 AI agent 编辑仓内决策文档(spec、计划、ADR、charter、`AGENTS.md`)、并且
**(b)** 把这些文档纳入版本控制的团队和构建者。如果你的 agent 会动到承载承诺的文本,Aperture MCP
给你一根便宜、诚实的绊线,守住那些你输不起的承诺。

---

## 隐私

- **Opt-in 且本地。** Aperture MCP 在你的机器上运行。它不做任何网络请求。
- **绝不拿你的数据训练。** 你的决策文本是你的;它不会离开你的进程。
- **使用日志默认关闭**;开启时也只记录**元数据**(时间戳、工具、状态、计数)——**绝不**记录你的
  决策文本或承诺措辞。

---

## 关于 demo 的诚实话

本仓附带一个小小的**手写 fixture ADR**(位于 [`examples/git_decision_drift/fixtures/`](./examples/git_decision_drift/fixtures)
的 before/after 一对),Aperture MCP 在其上正确地标出一条我们**故意退役**的承诺、并对一条我们保留的
承诺保持沉默。这是机制的一次忠实演示——但它**样本只有一个,而且是我们自己造、自己判的**。它演示的是
*绊线如何工作*,**不是***信号有多强*。后者请看上面的逐族真实数字,以及
[`docs/measured-limits.md`](./docs/measured-limits.md)。我们**目前还没有
任何外部采用者**——如果你把 Aperture MCP 跑在自己的决策文档上,非常欢迎告诉我们它抓到了什么、漏了什么。

---

## 项目状态

早期,**pre-1.0**,还不是生产级闸门。compare 契约(`v0.2`)已冻结、并有 conformance 套件覆盖;
包的 API 仍可能变动。兼容性策略见 [VERSIONING.md](./VERSIONING.md),变更见 [CHANGELOG.md](./CHANGELOG.md)。

## 撞到漏报?帮它变好

Aperture MCP **一定**会漏——这是设计使然(它对被改写、软化、翻译的承诺是瞎的)。当它漏掉一条你在意的
漂移、或对一次改写误报时,**告诉我们**是最有价值的贡献:

- **约 30 秒,不要账号/使用数据,措辞可选填** →
  [开一个 drift-case report](../../issues/new?template=drift-case-report.md)。
- 真实的漏报告诉我们**下一个先补哪个盲区**;并且——仅当你愿意分享措辞时——可进入金标语料,让
  [`docs/measured-limits.md`](./docs/measured-limits.md) 里的数字保持诚实。

我们**绝不**自动采集任何东西(见[隐私](#隐私));只有**你**选择分享时才发生。
有问题、或"这工具适不适合我的场景?" → **[GitHub Discussions](../../discussions)**。

更多帮法见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 许可证

[Apache-2.0](./LICENSE)。
