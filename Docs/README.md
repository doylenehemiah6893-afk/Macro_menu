# 项目文档索引与治理规则

> **Status:** CURRENT
>
> **Validated:** 2026-07-13
> **Scope:** 本地 `codex/dev-review-report`；不代表远端 `main` 或 `dev` 已更新

本文是项目文档的统一入口。先读 [STATUS.md](STATUS.md) 判断当前能做什么，再按需进入
设计、证据或历史材料。任何对话摘要、旧 README、根目录二进制文件名或 Release 页面都不能
替代本文规定的权威链。

## 1. 推荐阅读顺序

1. [当前状态与上下文恢复](STATUS.md)
2. [项目结构与上游同步规划](PROJECT_STRUCTURE.md)
3. [2026-07-13 文档与结构治理审计](DOCUMENT_GOVERNANCE_AUDIT_2026-07-13.md)
4. [调查与已批准决策台账](CATVBA重构调查与决策记录.md)
5. [详细恢复设计草案](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
6. [R2018 恢复、依赖与安全交付指南](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md)
7. [发布门禁与回滚手册](发版.md)

## 2. 文档状态词

| 状态 | 含义 | 可以授权实施或发布吗 |
|---|---|---|
| `CURRENT` | 当前状态、索引或治理入口；应随项目推进更新 | 不能独立创造设计决策 |
| `APPROVED` | 已书面批准的规范或决策 | 只能在其明确范围内授权实施 |
| `DRAFT` | 待复核的方案或计划 | 否 |
| `HISTORICAL` | 固定日期和 Git 快照的历史证据 | 否；不得当成当前状态 |
| `SUPERSEDED` | 已被新设计、源码或证据取代 | 否；保留仅用于追溯 |
| `REFERENCE` | 未成为项目规范的参考资料 | 否；目标机验证后才能采用 |
| `QUARANTINE` | 来源、许可证、安全性或可用性不清 | 否；不得进入发布包或执行 |

风险严重度、工作阶段和证据门必须分别写成 `severity:P0`、`phase:P0`、`gate:G0`；
禁止使用没有前缀的 `P0`，避免把高危问题、恢复阶段和发布状态混为一谈。

## 3. 权威链与冲突处理

发生冲突时按以下顺序处理：

1. 目标机原始证据、Git/tree SHA、输入与制品 SHA-256；
2. [决策台账](CATVBA重构调查与决策记录.md) 中明确标为已批准的 DR；
3. 状态为 `APPROVED` 的日期化规格；
4. 恢复指南、运行手册和已核验的操作记录；
5. 历史报告、参考材料和旧计划。

[STATUS.md](STATUS.md) 只汇总“当前到哪里、为什么阻塞、下一步是什么”，不能创造或推翻
设计决策。日期化规格写入仓库不等于已批准。历史报告中的日期、SHA、原限制和负面证据应保持不变；
后续发现只能用勘误或链接追加。

## 4. 当前权威文档

| 文档 | 状态 | 用途 |
|---|---|---|
| [STATUS.md](STATUS.md) | `CURRENT` | NO-GO、门禁、阻塞、唯一下一动作和恢复检查表 |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | `APPROVED`（唯一命名空间/所有权边界）/ `DRAFT`（执行细节） | `Src` 上游镜像、`catvba_refactor/` 唯一本地实现命名空间和 fail-closed intake |
| [DOCUMENT_GOVERNANCE_AUDIT_2026-07-13.md](DOCUMENT_GOVERNANCE_AUDIT_2026-07-13.md) | `HISTORICAL` | 本轮文档清点、编码/错链修复、结构审查、采用结论和延期项 |
| [CATVBA重构调查与决策记录.md](CATVBA重构调查与决策记录.md) | `APPROVED`（仅已标明 DR） | 约束、证据与已批准决策；未批准段落仍不生效 |
| [详细恢复设计](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md) | `DRAFT` | Build Kit、Core 运行时和目标机门禁的完整草案 |
| [恢复与依赖指南](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md) | `CURRENT` / evidence-runbook | NO-GO 根因、依赖、许可证边界、B28 操作与验收 |
| [发版.md](发版.md) | `CURRENT` NO-GO policy / `DRAFT` future process | 当前禁止事项有效；未来证据链、发布器和回滚流程待整体设计批准 |

## 5. 历史、替代与参考材料

| 文档 | 状态 | 处理规则 |
|---|---|---|
| [dev分支审查报告.md](dev分支审查报告.md) | `HISTORICAL` | 保留 2026-07-11、`c584202` / `dev@abce8ff` 的原始审查结论 |
| [bom_reflactor.md](bom_reflactor.md) | `SUPERSEDED` | 旧 BOM 提案；包含已不存在的符号和已被证伪的公共 UDT 设计，不执行 |
| [EKL.md](EKL.md) | `REFERENCE` | EKL 语言参考；需官方文档和目标版本验证 |
| [EKL计算体积.md](EKL计算体积.md) | `QUARANTINE` | 编码、上下文和能力边界未核验，不执行 |
| [../artifacts/analysis_results.md](../artifacts/analysis_results.md) | `SUPERSEDED` | 旧命名/旧源码结构的分析快照 |
| [../artifacts/implementation_plan.md](../artifacts/implementation_plan.md) | `SUPERSEDED` | 已部分实施且部分失效的旧计划，不继续执行 |
| [../DrawFunc/VB.md](../DrawFunc/VB.md) | `SUPERSEDED` | 与现有源码重复的高风险片段，来源未知 |
| [../ref_project/Frame.md](../ref_project/Frame.md) | `REFERENCE` | .NET COM 方案参考；位数和目标机可用性待验证 |
| `../ref_project/temp_new function/*` | `QUARANTINE` 或 `SUPERSEDED` | 临时抓取、重复或高副作用片段，不进入发布包 |

仓库目前没有覆盖 `ref_project/` 和 `DrawFunc/` 的顶层 `LICENSE`、`COPYING` 或 `NOTICE`。
来源未知的文本与代码不得推定可再分发。

## 6. 维护规则

- 每次任务开始先核对 [STATUS.md](STATUS.md)、当前分支、HEAD 和工作树。
- 除既有治理例外外，不新增 tracked 根级实现目录；所有 new/override/config/schema/tool/test/build/dist 路径都属于 `catvba_refactor/`。
- 不直接修改 `Src/`、`resources/`；本地缺陷修复使用显式整组件 override，upstream 采用后再经 intake 退役。
- candidate 必须从固定 Git blobs 读取；不得用 clean worktree、路径阴影或自动选边替代来源证明。
- 设计批准、门禁变化、Build Kit、目标机 build/profile 会话和 upstream intake 都必须写入文件并关联 SHA。
- 历史证据采用追加勘误，不把旧快照改写成当前结论。
- 维护中的 Markdown/YAML/JSON/Python 文件统一使用 UTF-8；遗留 VBA 源码在明确转码设计前保持原字节。
- 任何发布文档都不得包含批量删标签、无共同祖先 squash、全树 `--theirs`、裸 `git push` 或直接从仓库 glob 旧 CATVBA 的操作路径。
