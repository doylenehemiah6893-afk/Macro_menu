# CATVBA R2018 恢复状态

> 状态：CURRENT
>
> 更新日期：2026-07-18
>
> 分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`
>
> 交付结论：**NO-GO**
>
> `release_eligible=false`

本文是当前状态与上下文恢复入口。详细事实以 Git 文件、固定哈希和目标机证据为准。

开发续作入口为仓库根 `RESUME.md`、`Docs/ENVIRONMENT_REPRODUCTION.md` 与 `resume/state.json`。初始仓库同步已完成，
但远端首轮 CI 暴露 Windows `uv.exe` 发现和陈旧 delivery selector 两个缺陷；comments-only workflow 也被 GitHub 判为
无效启动。修复已形成新的 clean evidence、独立复审、完整 receipt 和 fresh delivery：
`next_action=run-b28-discovery`、`revocation_status=active`。但本轮 delivery 尚未推送/通过远端双平台复验，目标机不得开始。

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
| 本地/远端 | 首次远端发布已从 `037ab406` fast-forward 到 `2098484`；本地新 evidence=`0b28548`，delivery worktree 待提交/推送 |
| Python | 根 pyproject.toml/uv.lock/.python-version 为唯一真源 |
| 目录 | `catvba_refactor/` 已包含离线 Python、四份 manifest/schema、Core Runtime 固定/生成源码、Form override 和 pytest |
| 设计 | 恢复规格和 B28 G2/G3 证据工具链规格均已获用户书面确认 |
| 实施计划 | 离线 Build Kit、baseline intake、Core Runtime MVP 和 B28 evidence harness 的 A 环境实现已完成 |
| Intake baseline | upstream/fork `dev` 已独立复核并接受为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；本地只读 `refs/heads/dev` 已原子建立，远端未写入 |
| 离线测试 | `0b28548` 正式 receipt：1672 passed、19 warnings；inventory/check、双 Kit、四 verifier、collector smoke 全通过；均非 CATIA 证据 |
| active discovery bundle | `bundle-64084c5ea0dfd63e24d861cb`；provenance SHA-256 `64084c5ea0dfd63e24d861cbf948b05a4af3e33a7268290eb8ecca8158373ffe` |
| active Kit / handoff | `kit-d5ea863e68ba6af1cefa` / `handoff-80d8cb2c06104fcf3c74`；expires `2026-07-25T12:38:11Z` |
| 环境复刻修订 | 首轮远端缺陷已修复并由独立复审确认 Critical/Important=0；本地 delivery 仍等待提交、autocrlf/quotepath clone 和远端双平台复跑 |
| 当前仓库 CLI | 离线 Build Kit/audit/handoff 命令与 target evidence 命令均已具备；已生成确定性 discovery raw skeleton，真实 observation/receipt/approval/seal 仍需 B28 输入 |
| CATIA 证据 | 缺 B28 Compile、重启、三最小 profile、SPA/FTA、试点与回滚 |

## 3. 遗留证据

| 文件 | SHA-256 | 定位 |
|---|---|---|
| `CATIA_V5_SimpleMacroMenu.catvba` | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` | legacy evidence only |
| `CAT_menu.catvba` | `1C8EC220F3D97F84D5404F24225938B2A8E2821D3F16BFEF5964E97023CA2FCA` | legacy evidence only |

## 4. 设计入口

- [当前开发规格](CURRENT_DEVELOPMENT_SPEC.md)
- [当前开发计划](CURRENT_DEVELOPMENT_PLAN.md)
- [环境复刻与仓库同步](ENVIRONMENT_REPRODUCTION.md)
- [恢复总架构](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
- [离线 Build Kit](superpowers/specs/2026-07-13-catvba-offline-build-kit-design.md)
- [Core Runtime MVP](superpowers/specs/2026-07-13-catvba-core-runtime-mvp-design.md)
- [B28 验证、许可证与交付](superpowers/specs/2026-07-13-catvba-b28-validation-delivery-design.md)
- [上游 intake 与 fork 同步](superpowers/specs/2026-07-13-catvba-upstream-intake-design.md)
- [离线 Build Kit 实施计划](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)
- [B28 G2/G3 证据工具链规格](superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md)
- [B28 G2/G3 证据工具链实施计划](superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md)
- [B28 Discovery 原生 Windows 唯一执行入口](runbooks/b28-target/README_TARGET_B28.md)
- [历史 G2/G3-C 手册（SUPERSEDED）](runbooks/2026-07-14-catvba-b28-g2-g3-core.md)
- [项目结构](PROJECT_STRUCTURE.md)
- [调查与决策台账](CATVBA重构调查与决策记录.md)

## 5. 状态门

| Gate | 状态 | 原因 |
|---|---|---|
| G0 INPUT-FROZEN | `PASS` | 批准 cutoff 与 A 环境离线输入合同已冻结 |
| G1 KIT-READY | `PASS` | `0b28548` 双 Kit/ZIP、四 verifier、双 operator bundle 与 fresh handoff 已闭合；仅为 A 环境离线证据 |
| G2 B28-ENV-ATTESTED | `BLOCKED` | 缺正式 SP/HF、References、环境证据 |
| G3 BUILT-UNVERIFIED | `BLOCKED` | 未从空白 B28 工程构建 |
| G4 BASE-PROFILE-MATRIX-PASS | `BLOCKED` | 缺 P-AB3/P-HD2/P-MD2 |
| G5 FLEET-SPA-FTA-PASS | `BLOCKED` | 缺 SPA/FTA 分包与三个 profile 证据 |
| G6 SECURITY-PILOT-READY | `BLOCKED` | 缺回传审计、安全包装、试点和回滚 |
| G7 RELEASE-APPROVED | `BLOCKED` | 缺全部上游门和正式审批 |

G0/G1 `PASS` 只说明固定 Git 输入与本地可复算 delivery chain 闭合；两者都不是 CATIA Compile、References、
许可证 checkout、UI 或运行通过。

## 6. 当前 Discovery 交付状态（本地已签发，不是 CATIA PASS）

当前 bundle 为 `artifacts/b28-discovery/bundles/bundle-64084c5ea0dfd63e24d861cb/`；CURRENT 固定 provenance
SHA-256 `64084c5ea0dfd63e24d861cbf948b05a4af3e33a7268290eb8ecca8158373ffe`。active ledger captured-at 为
`2026-07-18T13:38:17Z`，只激活 `handoff-80d8cb2c06104fcf3c74`，并撤回四份旧 handoff。bundle 内含 Kit ZIP、
collector pyz、哈希、handoff、教程和 sanitized offline receipts；本轮记录见
`Docs/process/2026-07-18-remote-publication-and-ci-correction.md`。

只有本轮 delivery commit、远端同步、双平台 CI、GitHub fresh clone 与 fresh Delivery doctor 全部通过后，B28
才可能按当前 bundle quick-start 以原生 Windows `cmd.exe` 和 CPython 3.12 人工执行 raw Discovery。不得使用
WSL、PowerShell、uv 或自动化 CATIA/VBE/DSLS；不得使用任何历史 bundle 的 handoff。

这不是 Compile、References、DSLS checkout、运行、G2/G3 或 release 通过。bundle 固定
`compile_status=not-run`、target cases=`not-run`、`artifact_status=not-produced`、`release_eligible=false`。

## 7. 历史 discovery Kit/handoff A 环境证据（bytes unavailable / withdrawn）

本节精确绑定 clean evidence commit
`2c3d501eaf017a41d838bf2ce39214fd1291802c` 和 tree
`42447cc3ae72d657f76be39355fa134230b1ff28`。本次状态文档提交发生在构建之后，不是被构建的输入；Kit、handoff、
revocation snapshot 和 session skeleton 均在仓库外的隔离临时根中，未进入 Git，实际 bytes 当前不可取得。
因此本节只作为历史 receipt 摘要，不是 active artifact。`handoff-6ed312ee18b254cb3c13` 在本轮 preparation 中
按 withdrawn 处理，不能因历史 expiry 尚未到达而恢复。当前 active bundle/Kit/handoff 只由上一节、
`resume/state.json`、CURRENT 和 ledger 的共同绑定确认。

### 7.1 离线 Gate 与 Build Kit

| 项目 | 精确结果 |
|---|---|
| frozen sync | PASS；22 packages audited |
| 完整 pytest | 1306 passed，19 条第三方 deprecation warnings |
| inventory | `ok=true`、`formal_eligible=true`、零 diagnostics；90 个 discovered = 13 candidate + 77 quarantine |
| check | `ok=true`、`formal_eligible=true`、零 diagnostics；16 component、2 tool |
| Kit ID | `kit-feb504676720445f729c` |
| catalog SHA-256 / identity | `feb504676720445f729c91075f9a8cd40d2a75f35defe2821a297b02b2dd6a5b` |
| manifest SHA-256 | `fa4feb560f07368c64f0115f9575ae5d38d6e4e85de8f65f9ef7125705436fa5` |
| manifest digest | `ca28e71f310505463f382f2affe18d5d96f4fc747d66a1eb8e20a730c1d83240` |
| ZIP SHA-256 | `acecc6c8aeb62bc54e7fddbb8975e9fba2652deb8935d6351817b5fcbc1de571` |
| ZIP sidecar SHA-256 | `840e4cab142c6365bbc0229d23c0e20c1369665ef49231f5a3b47c20cbda8b80` |
| 确定性 | 两个新输出根的完整目录树、catalog、manifest、ZIP 和 sidecar 逐字节相同 |
| verifier | primary directory/ZIP + comparison directory/ZIP：4/4 `ok=true`、零 diagnostics；四份 report digest 均为 `e6ef4c5d1f279ffa487072d298e63fb317230b7ac4b3be7caf75f611026d1d52` |

Core contract 为 `discovery-required`，allowlist 为空；Kit 中 `catvba_artifacts=[]`，没有生成 CATVBA。
独立复核者实际检查了四份 verifier 报告、完整目录比较、ZIP/sidecar 和 Git object，结论无
Critical/Important，复核记录 ID 为 `record.a-env-review.2c3d501`。

### 7.2 历史签发时唯一的 discovery handoff

签发前 canonical revocation snapshot 的 SHA-256 为
`05de64cfc8e35e4f3aa5cd1fccf9e9e9571196cb8630c8b7241c783d7e51ddb8`，`active_handoff_ids=[]`、
`withdrawn_handoff_ids=[]`，source 为 `a-env-active-handoff-ledger`。准备记录为
`record.a-env-preparation.2c3d501`，只有独立复核完成后才使用上述 review ID。

| 项目 | 精确结果 |
|---|---|
| handoff ID | `handoff-6ed312ee18b254cb3c13` |
| handoff SHA-256 | `a27b0a0ae1ff0e0ac819c0458c040fa0788437ac44a2c7ce61fe86861ef0f0f5` |
| purpose/status | 历史签发时为 `discovery` / `active`；当前 bytes unavailable，按 `withdrawn` 处理 |
| created/expires UTC | `2026-07-15T09:00:00Z` / `2026-07-22T09:00:00Z` |
| binding | 上述 Kit ID、ZIP SHA、commit/tree/branch、Core `discovery-required` contract 全部一致 |
| target truth | `compile_status=not-run`、`release_eligible=false` |

输出根中恰好生成一份 handoff JSON；本任务没有创建 formal handoff。

### 7.3 确定性 discovery session skeleton

使用同一 Kit/handoff、`mode=discovery`、`package=core`、`profile=DISCOVERY`、session ID
`session-20260715-discovery-2c3d501` 和 `created_at=2026-07-15T09:05:00Z` 在两个独立输出根初始化。
两套完整 skeleton 逐字节一致，10 个 payload member 全部相同，payload digest 均为
`6f178b23f6dcbcf4a9afeea784db848ab399b7a0d1d936a433bcfd82350865a3`；两次 capture validator 均
`ok=true`、零 diagnostics。没有填写目标机 observation，没有计算 Gate，也没有生成 approval、sealed evidence
或 CATVBA。

当前结论必须原样保持：

```text
G0/G1 = PASS for the bound discovery Kit
G2-G7 = BLOCKED
target cases = not-run
compile_status = not-run
release_eligible = false
```

这些结果只证明离线 evidence harness、确定性 discovery Kit/handoff 和空 session skeleton；不证明 B28、
References、许可证 checkout、Compile、运行或发布。

## 8. 历史 A 环境 Core Kit 证据

本记录精确绑定源/证据提交
`2645033a25e770fe9855b67e05bdefce42bc1c6a`，而不是后续只更改文档的提交。该提交 tree 为
`0b283db266ad7fd7ddcbaec992cea2f273f52032`。构建输出位于临时目录，不进入 Git。

### 8.1 结果与身份

| 项目 | 结果 |
|---|---|
| `uv sync --frozen` | PASS，22 packages audited |
| `uv run pytest -q` | 589 passed，19 条第三方 deprecation warnings |
| `inventory --format json` | `ok=true`、`formal_eligible=true`；90 个 discovered = 13 个获批固定 candidate + 77 个 quarantine；零 diagnostics |
| `check --format json` | `ok=true`、`formal_eligible=true`；13 个固定 candidate + 3 个 generated = `component_count=16`；2 个 tool；零 diagnostics |
| Kit ID | `kit-134ecc68d131cdff743b` |
| catalog SHA-256 | `134ecc68d131cdff743b221a878e2666b88b8353d17f128da6b5705455ccacfe` |
| manifest SHA-256 | `645f9e5d2a9c6069651fd12cfae95c941a23d35765e7f53b89c6acf3b9d26442` |
| manifest digest | `74b31cec68b7a268eeaeb4d2c08ac9fe7c875740a1bf06a589cd85b8621709f9` |
| ZIP SHA-256 | `e6ec490827dd78c4e9e0e83650591a7f46d71892160c1da4284b0e80501a54c7` |
| 确定性 | 双构建的 Kit ID、catalog bytes、manifest SHA、ZIP SHA 和 ZIP bytes 全部相同 |
| verifier | 构建 1 目录/ZIP、构建 2 目录/ZIP：4/4 `ok=true`、零 diagnostics |

### 8.2 精确内容

manifest 精确批准 13 个固定 candidate component 和 2 个 tool；generator 再加入 3 个确定生成
component，因而 checked/built catalog 共 16 个 component。Form 是一个 component，
但以相邻 `.frm/.frx` 两个文件 staging，因此 `packages/core/source/` 共 17 个文件成员。

- 固定：`C_MMButtonHandler`、`C_MMContext`、`C_MMResult`、`C_MMStateGuard`、
  `Cat_Macro_Menu_View`、`MM_DocumentSummary`、`MM_Entry`、`MM_Error`、`MM_HealthCheck`、
  `MM_Log`、`MM_MenuPresenter`、`MM_Protocol`、`MM_TryGet`；
- 生成：`MM_BuildInfo`、`MM_Dispatch`、`MM_MenuCatalog`；
- 工具：`core.healthcheck` → `MM_HealthCheck.RunHealthCheck`，
  `core.document-summary` → `MM_DocumentSummary.RunDocumentSummary`；两者均为 `read-only`，
  `required_capabilities=[]`。

Core staging 不含上游 legacy、第二回合、Fleet、Optional、Office、VBIDE、网络、`Shell`、SPA 或 FTA
component。Catalog 保留物理隔离的 `fleet-spa`/`fleet-fta` package 政策记录，但它们的 import-order
为空且没有扩展 component 进入 Core Kit。

### 8.3 实际命令与临时路径

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json | tee /tmp/macro-menu-core-2645033-inventory.json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json | tee /tmp/macro-menu-core-2645033-check.json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --output-root /tmp/macro-menu-core-2645033-build-1.1dbCf7 build-kit --format json | tee /tmp/macro-menu-core-2645033-receipt-1.l4tLEB.json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --output-root /tmp/macro-menu-core-2645033-build-2.UYfGUJ build-kit --format json | tee /tmp/macro-menu-core-2645033-receipt-2.X2CkWj.json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit /tmp/macro-menu-core-2645033-build-1.1dbCf7/kit-134ecc68d131cdff743b --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit /tmp/macro-menu-core-2645033-build-1.1dbCf7/kit-134ecc68d131cdff743b.zip --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit /tmp/macro-menu-core-2645033-build-2.UYfGUJ/kit-134ecc68d131cdff743b --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit /tmp/macro-menu-core-2645033-build-2.UYfGUJ/kit-134ecc68d131cdff743b.zip --format json
```

原始 JSON 收据临时写入
`/tmp/macro-menu-core-2645033-receipt-1.l4tLEB.json` 和
`/tmp/macro-menu-core-2645033-receipt-2.X2CkWj.json`。另行用 `cmp --silent`/`jq -er` 比较上述五项
确定性身份，均 exit 0。

### 8.4 证据上限

target-test-plan 共 30 个 case，全部 `status=not-run`；`compile_status=not-run`、
`target_build_required=true`、`release_eligible=false`。本工作区没有 CATIA，因此不得从静态 VBA 源码、
Python PASS 或已验证 Kit 推导 CATIA Compile、References、许可证、UI、运行或发布结论。目标资格
仍是 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`；SPA/FTA 保持与 Core 物理隔离，其失败隔离证据尚未执行。

## 9. 已完成的早期 A 环境验证

| 检查 | 2026-07-13 结果 | 结论边界 |
|---|---|---|
| `uv sync --frozen` | PASS | 根项目/lock 可复现；不是 CATIA 环境验证 |
| `uv run pytest -q` | 当时 414 passed | Python、政策、intake、审计和打包逻辑的早期基线 |
| `test_end_to_end.py` | PASS | 临时 Git 仓库双构建的 kit ID、catalog、SHA256SUMS、ZIP bytes/hash 相同；目录/ZIP 均通过 verifier |
| fixture dirty candidate | exit 3，错误 JSON 写入 stderr；无 Kit/输出目录 | governed tree 漂移失败关闭 |
| fixture worktree check | exit 0，`formal_eligible=false` | 只作诊断，不产生 Kit |
| 早期 clone `inventory/check` | exit 0，`formal_eligible=true`，77 个上游组件、零获批 candidate component/tool | accepted baseline 可复现；当时不能升级 G0/G1 |
| 早期 clone `build-kit` | source exit 3；无 Kit/输出目录 | 历史失败关闭证据，已由第 6 节真实 Core Kit 证据取代 |

首次 baseline intake 已分别只读查询 fork 与上游 `dev`，两者均指向
`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；严格 record 已提交，本地 `refs/heads/dev` 仅在所有
验收通过后以 old=全零原子创建。流程未 checkout `dev`，未创建空 merge，也未写 fork/upstream
`main/dev`。上述测试未启动 CATIA、未写 CATVBA、未证明 References/API/许可证/UI；始终保持
`compile_status=not-run`、`release_eligible=false`。

## 10. 当前下一动作

按 `CURRENT_DEVELOPMENT_PLAN.md` 提交本地 delivery record，并在取得外部认证后 fast-forward push。确认远端 HEAD、
Linux/Windows CI 和第二 GitHub fresh clone 后，若 Delivery doctor 仍通过，才恢复 B28 操作窗口。不得复用旧 handoff、
自动化 CATIA、Compile 或 target cases。当前 Gate 不升级。

## 11. 外部阻塞

- 正式 Windows、R2018 SP/HF、DS VBA/VBE；
- P-AB3/P-HD2/P-MD2 精确 DSLS entitlement 和隔离方式；
- B28 References GUID/版本/路径；
- 脱敏测试数据；
- 企业签名/ACL、制品库、审批人和证据保留；
- Production 安装根、宏库注册、试点和回滚流程。
- GitHub HTTPS/SSH/gh 推送凭据；凭据只能配置在仓库外。
