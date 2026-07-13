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
| 目录 | `catvba_refactor/` 已包含离线 Python、四份 manifest/schema、Core Runtime 固定/生成源码、Form override 和 pytest |
| 设计 | 总架构和四份子规格已于 2026-07-13 获用户书面确认 |
| 实施计划 | 离线 Build Kit、baseline intake 和 Core Runtime MVP A 环境切片已实施 |
| Intake baseline | upstream/fork `dev` 已独立复核并接受为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；本地只读 `refs/heads/dev` 已原子建立，远端未写入 |
| 离线测试 | 证据提交 `2645033a25e770fe9855b67e05bdefce42bc1c6a`：`uv run pytest -q` 为 589 passed |
| 当前仓库 CLI | `inventory` 发现 90 个：13 个获批固定 candidate + 77 个 quarantine；`check`/Kit catalog 由 generator 加入 3 个组件后为 16 个 component、2 个 tool |
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
| G0 INPUT-FROZEN | `PASS` | 证据绑定 Git `2645033a25e770fe9855b67e05bdefce42bc1c6a`、tree `0b283db266ad7fd7ddcbaec992cea2f273f52032`；源码/manifest/blob/SHA 闭合 |
| G1 KIT-READY | `PASS` | 两次独立构建字节一致，两目录+两 ZIP 均通过 `verify-kit`；仅表示 A 环境离线 Kit 就绪 |
| G2 B28-ENV-ATTESTED | `BLOCKED` | 缺正式 SP/HF、References、环境证据 |
| G3 BUILT-UNVERIFIED | `BLOCKED` | 未从空白 B28 工程构建 |
| G4 BASE-PROFILE-MATRIX-PASS | `BLOCKED` | 缺 P-AB3/P-HD2/P-MD2 |
| G5 FLEET-SPA-FTA-PASS | `BLOCKED` | 缺 SPA/FTA 分包与三个 profile 证据 |
| G6 SECURITY-PILOT-READY | `BLOCKED` | 缺回传审计、安全包装、试点和回滚 |
| G7 RELEASE-APPROVED | `BLOCKED` | 缺全部上游门和正式审批 |

此处 G0/G1 `PASS` 仅由固定 Git 输入、生成收据和可复算的离线 Kit 支撑。它们不是 CATIA
Compile、References、许可证 checkout、UI 或运行通过。

## 6. A 环境 Core Kit 证据

本记录精确绑定源/证据提交
`2645033a25e770fe9855b67e05bdefce42bc1c6a`，而不是后续只更改文档的提交。该提交 tree 为
`0b283db266ad7fd7ddcbaec992cea2f273f52032`。构建输出位于临时目录，不进入 Git。

### 6.1 结果与身份

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

### 6.2 精确内容

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

### 6.3 实际命令与临时路径

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

### 6.4 证据上限

target-test-plan 共 30 个 case，全部 `status=not-run`；`compile_status=not-run`、
`target_build_required=true`、`release_eligible=false`。本工作区没有 CATIA，因此不得从静态 VBA 源码、
Python PASS 或已验证 Kit 推导 CATIA Compile、References、许可证、UI、运行或发布结论。目标资格
仍是 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`；SPA/FTA 保持与 Core 物理隔离，其失败隔离证据尚未执行。

## 7. 已完成的早期 A 环境验证

| 检查 | 2026-07-13 结果 | 结论边界 |
|---|---|---|
| `uv sync --frozen` | PASS | 根项目/lock 可复现；不是 CATIA 环境验证 |
| `uv run pytest -q` | 当时 414 passed | Python、政策、intake、审计和打包逻辑的早期基线 |
| `test_end_to_end.py` | PASS | 临时 Git 仓库双构建的 kit ID、catalog、SHA256SUMS、ZIP bytes/hash 相同；目录/ZIP 均通过 verifier |
| fixture dirty candidate | exit 3，错误 JSON 写入 stderr；无 Kit/输出目录 | governed tree 漂移失败关闭 |
| fixture worktree check | exit 0，`formal_eligible=false` | 只作诊断，不产生 Kit |
| 早期 clone `inventory/check` | exit 0，`formal_eligible=true`，77 个上游组件、零获批 candidate component/tool | accepted baseline 可复现；当时不能升级 G0/G1 |
| 早期 clone `build-kit` | exit 3，`NO_BUILDABLE_COMPONENTS`；无 Kit/输出目录 | 当时的失败关闭证据，已由第 6 节真实 Core Kit 证据取代 |

首次 baseline intake 已分别只读查询 fork 与上游 `dev`，两者均指向
`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；严格 record 已提交，本地 `refs/heads/dev` 仅在所有
验收通过后以 old=全零原子创建。流程未 checkout `dev`，未创建空 merge，也未写 fork/upstream
`main/dev`。上述测试未启动 CATIA、未写 CATVBA、未证明 References/API/许可证/UI；始终保持
`compile_status=not-run`、`release_eligible=false`。

## 8. 当前下一动作

Core Runtime MVP A 环境切片已到 G1。下一步是在受控 B28 空白工程执行 G2/G3：环境声明、
References 证据、按 import-order 导入、Compile、保存、关闭/重启并回传审计制品。不得在无 CATIA
的本工作区将这些步骤标记为完成。

## 9. 外部阻塞

- 正式 Windows、R2018 SP/HF、DS VBA/VBE；
- P-AB3/P-HD2/P-MD2 精确 DSLS entitlement 和隔离方式；
- B28 References GUID/版本/路径；
- 脱敏测试数据；
- 企业签名/ACL、制品库、审批人和证据保留；
- Production 安装根、宏库注册、试点和回滚流程。
