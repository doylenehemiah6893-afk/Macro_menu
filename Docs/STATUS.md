# CATVBA R2018 恢复状态

> 状态：CURRENT
>
> 更新日期：2026-07-13
>
> 分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`
>
> 交付结论：**NO-GO**
>
> `release_eligible=false`

本文是当前状态与上下文恢复入口。详细事实以 Git 文件、固定哈希和目标机证据为准。

## 1. 立即停止条件

- 不普通/生产安装、运行、回滚或分发根目录旧 CATVBA；
- 不从旧 CATVBA `Save As` 创建 B28 工程；
- 不声称本地完成 CATIA Compile、运行、许可证或发布验证；
- 不安装 B30/x86/Temp/未知 DLL 来补污染引用；
- 不执行 `LicenseReset.catvbs` 或持久化修改许可证；
- 不写 fork `main/dev` 或上游仓库；
- 不打正式 tag/Release，不使用现有 workflow 发布旧二进制。

## 2. 当前事实

| 项目 | 状态 |
|---|---|
| 本地 CATIA | 无；只能编写、静态分析、pytest、Build Kit 和审计准备 |
| 目标宿主 | CATIA V5-6R2018（R28/B28）、VBA7、64 位 |
| 目标资格 | `(AB3 OR HD2 OR MD2) AND SPA AND FTA` |
| Core | 不早绑定 SPA/FTA；在 P-AB3/P-HD2/P-MD2 分别通过的能力交集 |
| SPA/FTA | 目标机保证权益；物理隔离为默认部署 Fleet Extensions |
| 上游 | `verysolecd/Macro_menu:dev` 是 Src/resources 逻辑来源 |
| fork | main/dev 镜像上游；个人实现只写 codex/dev-review-report |
| Python | 根 pyproject.toml/uv.lock/.python-version 为唯一真源 |
| 目录 | `catvba_refactor/` 已包含离线 Python、四份 manifest/schema、pytest；VBA Runtime 目录仍只有边界说明 |
| 设计 | 总架构和四份子规格已于 2026-07-13 获用户书面确认 |
| 实施计划 | 离线 Build Kit 计划 Tasks 1–12 和首次 baseline intake 已实施；已批准 Core Runtime MVP 的实施计划是下一项 |
| Intake baseline | upstream/fork `dev` 已独立复核并接受为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；本地只读 `refs/heads/dev` 已原子建立，远端未写入 |
| 离线测试 | `uv run pytest -q`：414 passed；端到端 fixture 双构建得到相同 Kit/ZIP |
| 当前仓库 CLI | `inventory/check` exit 0、`formal_eligible=true`、零获批 candidate；`build-kit` exit 3 `NO_BUILDABLE_COMPONENTS`，未生成 Kit |
| CATIA 证据 | 缺 B28 Compile、重启、三最小 profile、SPA/FTA、试点与回滚 |

## 3. 遗留证据

| 文件 | SHA-256 | 定位 |
|---|---|---|
| `CATIA_V5_SimpleMacroMenu.catvba` | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` | legacy evidence only |
| `CAT_menu.catvba` | `1C8EC220F3D97F84D5404F24225938B2A8E2821D3F16BFEF5964E97023CA2FCA` | legacy evidence only |

## 4. 设计入口

- [恢复总架构](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
- [离线 Build Kit](superpowers/specs/2026-07-13-catvba-offline-build-kit-design.md)
- [Core Runtime MVP](superpowers/specs/2026-07-13-catvba-core-runtime-mvp-design.md)
- [B28 验证、许可证与交付](superpowers/specs/2026-07-13-catvba-b28-validation-delivery-design.md)
- [上游 intake 与 fork 同步](superpowers/specs/2026-07-13-catvba-upstream-intake-design.md)
- [离线 Build Kit 实施计划](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)
- [项目结构](PROJECT_STRUCTURE.md)
- [调查与决策台账](CATVBA重构调查与决策记录.md)

## 5. 状态门

| Gate | 状态 | 原因 |
|---|---|---|
| G0 INPUT-FROZEN | `NOT_RUN` | baseline 已接受，但尚无获批 Core candidate bindings，未生成仓库输入冻结 receipt |
| G1 KIT-READY | `NOT_RUN` | 无仓库 Kit；仓库 manifest 尚无获批 Core component/tool |
| G2 B28-ENV-ATTESTED | `BLOCKED` | 缺正式 SP/HF、References、环境证据 |
| G3 BUILT-UNVERIFIED | `BLOCKED` | 未从空白 B28 工程构建 |
| G4 BASE-PROFILE-MATRIX-PASS | `BLOCKED` | 缺 P-AB3/P-HD2/P-MD2 |
| G5 FLEET-SPA-FTA-PASS | `BLOCKED` | 缺 SPA/FTA 分包与三个 profile 证据 |
| G6 SECURITY-PILOT-READY | `BLOCKED` | 缺回传审计、安全包装、试点和回滚 |
| G7 RELEASE-APPROVED | `BLOCKED` | 缺全部上游门和正式审批 |

fixture PASS、目录或文档存在都不表示仓库 Gate 通过。

## 6. A 环境验证记录

| 检查 | 2026-07-13 结果 | 结论边界 |
|---|---|---|
| `uv sync --frozen` | PASS | 根项目/lock 可复现；不是 CATIA 环境验证 |
| `uv run pytest -q` | 414 passed | Python、政策、intake、审计和打包逻辑通过 |
| `test_end_to_end.py` | PASS | 临时 Git 仓库双构建的 kit ID、catalog、SHA256SUMS、ZIP bytes/hash 相同；目录/ZIP 均通过 verifier |
| fixture dirty candidate | exit 3，错误 JSON 写入 stderr；无 Kit/输出目录 | governed tree 漂移失败关闭 |
| fixture worktree check | exit 0，`formal_eligible=false` | 只作诊断，不产生 Kit |
| 当前 clone `inventory/check` | exit 0，`formal_eligible=true`，77 个上游组件、零获批 candidate component/tool | accepted baseline 可复现；不把零 candidate 升级为 G0/G1 |
| 当前 clone `build-kit` | exit 3，`NO_BUILDABLE_COMPONENTS`；无 Kit/输出目录 | 失败关闭，不生成空或伪造 Kit |

首次 baseline intake 已分别只读查询 fork 与上游 `dev`，两者均指向
`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；严格 record 已提交，本地 `refs/heads/dev` 仅在所有
验收通过后以 old=全零原子创建。流程未 checkout `dev`，未创建空 merge，也未写 fork/upstream
`main/dev`。上述测试未启动 CATIA、未写 CATVBA、未证明 References/API/许可证/UI；始终保持
`compile_status=not-run`、`release_eligible=false`。

## 7. 当前下一动作

Core Runtime MVP 规格已经批准；下一步编写其日期化实施计划，再按 TDD 实现审定组件和工具、写入
manifest 并重新执行 G0/G1。不得用 fixture、空包、零 candidate 或 `HEAD` 回退升级仓库状态。

## 8. 外部阻塞

- 正式 Windows、R2018 SP/HF、DS VBA/VBE；
- P-AB3/P-HD2/P-MD2 精确 DSLS entitlement 和隔离方式；
- B28 References GUID/版本/路径；
- 脱敏测试数据；
- 企业签名/ACL、制品库、审批人和证据保留；
- Production 安装根、宏库注册、试点和回滚流程。
