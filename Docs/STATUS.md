# CATVBA R2018 恢复状态

> **Status:** CURRENT
>
> **Last verified:** 2026-07-13
>
> **Branch:** `codex/dev-review-report`
>
> **Design baseline:** `b00858681115a0f3d8ebbd2d38d883cf2c6132d0`
>
> **Delivery decision:** **NO-GO**
>
> **release_eligible:** `false`

本文是唯一的当前状态与上下文恢复页。精确的文档版本由包含本文的 Git 提交确定；
`Design baseline` 仅表示本轮文档统一审查所依据的设计提交，不试图自引用未来提交 SHA。

## 1. 立即停止条件

- 不做普通、生产或未授权的旧 CATVBA 安装/运行，不分发，也不把它们当作 seed 或回滚制品；只有另行批准的隔离取证会话可按恢复指南使用只读副本。
- 不从旧 CATVBA `Save As` 创建 B28 工程。
- 不声称已在 CATIA 中 Compile、重启、运行或通过许可证矩阵。
- 不通过安装 B30、x86 VBIDE、旧 DLL、Temp COM 或 Office 组件来补齐污染引用。
- 不执行 `LicenseReset.catvbs`，也不以持久化修改许可证的方式探测能力。
- 不打正式 tag、不创建正式 Release、不把当前 GitHub workflow 当作合格发布器。

## 2. 当前事实快照

| 项目 | 当前状态 |
|---|---|
| 本地 CATIA | 无；本地只允许源码、分析、离线测试和打包准备 |
| 目标宿主 | CATIA V5-6R2018（R28/B28）、VBA7、64 位 Windows |
| Core 定义 | AB3-only、MD2-only、HD2-only 三套 profile 分别通过的严格能力交集 |
| 交付路线 | 源码优先、物理分包、空白 B28 工程导入、证据门驱动 |
| 结构策略 | 已确认本地 Overlay；首阶段不移动 `Src/` 或遗留根目录材料 |
| 文档治理 | 主入口、权威链、结构规划和历史/参考材料已统一；过程见 [2026-07-13 治理审计](DOCUMENT_GOVERNANCE_AUDIT_2026-07-13.md) |
| 详细设计 | `DRAFT`，仍待整体书面复核；写入仓库不等于批准 |
| 实施计划 | 尚未建立获批实施计划；规划的恢复实现尚未开始 |
| 本地工具链 | `macro_build/`、`config/`、`schemas/`、`tests/`、`build/`、`dist/` 均尚未创建 |
| CATIA 目标证据 | 缺少 B28 Compile、重启、三 profile、签名/ACL、试点与回滚证据 |

遗留二进制固定证据：

| 文件 | SHA-256 | 当前定位 |
|---|---|---|
| `CATIA_V5_SimpleMacroMenu.catvba` | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` | 历史正式候选；仅 legacy evidence |
| `CAT_menu.catvba` | `1C8EC220F3D97F84D5404F24225938B2A8E2821D3F16BFEF5964E97023CA2FCA` | 旧分叉；仅 legacy evidence |

## 3. 状态门

状态门模型来自待批准的详细设计；在设计获批前，以下状态只用于保守阻断，不能推导发布资格。

| Gate | 名称 | 状态 | 原因 |
|---|---|---|---|
| G0 | INPUT-FROZEN | `NOT_RUN` | 尚无获批 manifest、输入冻结记录和实现计划 |
| G1 | KIT-READY | `NOT_RUN` | Build Kit 工具链和不可变 Kit 尚不存在 |
| G2 | B28-ENV-ATTESTED | `BLOCKED` | 缺正式 R2018 SP/HF、References 和环境证明 |
| G3 | BUILT-UNVERIFIED | `BLOCKED` | 尚未在空白 B28 工程构建候选 CATVBA |
| G4 | CORE-MATRIX-PASS | `BLOCKED` | 缺 AB3-only / MD2-only / HD2-only 隔离验收 |
| G5 | SECURITY-PACKAGE-PASS | `BLOCKED` | 缺返回制品审计、签名/ACL、哈希和安全包装证据 |
| G6 | PILOT-READY | `BLOCKED` | 缺试点、现场调试和回滚演练 |
| G7 | RELEASE-APPROVED | `BLOCKED` | 缺全部上游门和正式审批记录 |

`phase:P0-P8` 表示恢复工作阶段，`gate:G0-G7` 表示证据门，两者正交；完成某个工作阶段不等于门禁通过。

## 4. 已确认与未确认边界

已确认：

- 方案 2：源码优先恢复，不破解/修补旧加密 CATVBA；
- 首个里程碑 B：离线基础与少量低风险只读 Core 候选；
- Core 只取三种基线 profile 的实测能力交集；
- 本地 Overlay 目录策略，以及 `origin/dev` 为唯一代码上游；
- 旧 CATVBA、许可证重置脚本、未知来源参考材料不得进入正式发布。

仍需书面复核：

- [详细恢复设计](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md) 的整体内容；
- manifest/schema、CLI/API、错误码、生成器和运行时协议细节；
- 五个首批 Core 工具候选的最终范围；
- 企业签名/ACL、目标环境、证据保管、审批人与发布器治理。

## 5. 当前唯一下一动作

完成本轮文档统一检查点后，书面复核详细恢复设计：批准、修改或拒绝。
结果必须追加到 [决策台账](CATVBA重构调查与决策记录.md)，然后才能用
`Docs/superpowers/plans/` 中的日期化计划进入 Overlay 元数据和工具链实施。

在该动作完成前，不创建业务实现、不迁移模块、不生成候选 CATVBA。

## 6. 外部阻塞

- 正式 R2018 SP/HF、B28 References GUID/版本和 64 位 VBA7 环境；
- AB3-only、MD2-only、HD2-only 三套真正隔离的许可证 profile 与 DSLS 证据；
- 企业签名或只读 ACL 方案、审批人、不可变制品库和证据保留策略；
- 脱敏 CATPart/CATProduct/CATDrawing 测试数据与业务验收人；
- 现场安装、试点、故障回滚和模型数据恢复边界。

## 7. 每次恢复会话先核对

1. `git status --short --branch`、当前 HEAD 和工作树；
2. 本页、决策台账、详细 spec 和最新计划的状态；
3. 两个遗留 CATVBA 的大小与 SHA-256 是否变化；
4. `origin/dev` 的已记录 cutoff 是否变化，以及是否已有 intake 记录；
5. 最新测试/门禁证据和唯一下一动作；
6. 不因对话摘要、文件存在或旧 Release 推断“已批准”“已编译”或“可用”。
