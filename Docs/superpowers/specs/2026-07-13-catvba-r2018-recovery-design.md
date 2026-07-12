# CATVBA R2018 恢复与首个 Core Build Kit 设计

> 状态：DRAFT — 待用户整体书面复核
>
> 写入本文、引用本文或确认其中某个局部边界，都不等于整体批准；只有决策台账中的书面批准记录才能授权实施。
>
> 日期：2026-07-13
>
> 工作分支：`codex/dev-review-report`
>
> 目标：CATIA V5-6R2018（R28/B28）、VBA7、64 位 Windows

## 1. 目标与不可妥协约束

本设计把当前不可用的单体 CATVBA 重构为源码优先、离线可测试、按许可证物理隔离、能在干净 B28 环境重新构建和现场调试的交付体系。

项目约束：

- 当前工作区没有 CATIA；本地只能编写、分析、测试、生成 Build Kit 和审计回传物，不能声称 CATIA 已编译或可运行。
- Core 严格定义为 AB3-only、MD2-only、HD2-only 三套 profile 分别验证通过的能力交集。
- 只在部分基线 profile 可用的能力进入 Baseline Extension；SPA、ST1、DL1、LO1、DMN、FTA、KWA、Excel 等进入独立 Optional 包。
- Core 禁止 Office、网络、Shell、PowerShell、WSH、VBIDE、MSAPC、运行时源码扫描、许可证修改和额外许可证早绑定类型。
- 现有两个 CATVBA 只作遗留取证样本；不得作为新工程 seed、可信源码或回滚产物。
- 重构只发生在本地 `codex/*` 分支；不修改远端。`origin/dev` 是唯一代码上游，`origin/main` 只作旧发布观察源。
- `Src` 首阶段不移动、不批量转码，降低持续吸收 `origin/dev` 时的冲突。
- 对话摘要不是项目真源；设计、计划、进度、证据和 Git 提交必须持久化。

## 2. 项目分解

项目分为四个可独立验收的子项目：

1. **离线基础与 Build Kit**：Python CLI、schema、源码清点、包/能力策略、静态代码生成、不可变 staging、CATVBA 回传审计。
2. **首个 Core 运行时**：静态菜单、协议、错误/日志、状态守卫和五个只读 `core-candidate`。
3. **B28 构建与三 profile 验收**：空工程导入、Compile、重启、AB3/MD2/HD2 矩阵、签名/ACL、试点和回滚。
4. **后续业务迁移**：Baseline Extension 和各 Licensed Optional；每包另建规格和实施计划。

首份实施计划覆盖子项目 1 和子项目 2 的本地可验证部分，并产出可交给 B28 的 Build Kit。子项目 3 由本设计规定运行手册和证据格式，但没有目标机时保持阻塞。子项目 4 不进入首个里程碑。

## 3. 源码与包边界

### 3.1 真源

唯一真源为：

- `Src` 中的文本 VBA/FRM/FRX；
- `config` 中的项目、包、能力、工具和策略清单；
- `schemas` 中的机器可验证 schema；
- 生成器及其测试。

CATVBA、生成的 `.bas`、Build Kit 和目标机证据都是派生物。生成模块不得回写 `Src`，不得手工编辑。

### 3.2 包级别

```text
CORE_CANDIDATE
BASELINE_EXTENSION
LICENSED_OPTIONAL
DEVTOOLS
QUARANTINE
```

每个现有组件必须恰好属于一个包或 Quarantine。只有明确列为 `shared_contract_modules` 的小型协议模块允许被复制到多个 staging；FRM/FRX 必须作为不可拆分组件处理。

Core 不引用 Optional 工程。Optional 对 Core 只允许版本化的逻辑契约依赖，公共数据通过 Variant 数组传递，或把同一小型 contract 源码复制进各自工程。

### 3.3 当前必须先切断的污染链

- `KCL.bas` 的 `Public pdm As New Cls_PDM` 把 KWA 路径带入共享层；
- `KCL.bas` 的 `Public xlm As New Cls_XLM` 把 Excel 早绑定带入共享层；
- `KCL.GetMeas/getlength` 把 SPA 带入共享层；
- `Drw_myframe` 与 `Drw_myframe2` 混有 Layout2D/LO1 类型；
- `OTH_3Dmark` 同时混有 DMN 和 FTA，并依赖含 KWA 路径的 PDM 类。

首个 Core 不修复或导入整份 KCL/Cls_PDM/Cls_XLM。它使用新的最小 Core 模块；遗留模块默认 Quarantine，后续按功能抽取。

## 4. 离线工具链

### 4.1 文件布局

Windows 下已有 `Src`，Python 包不得命名为大小写仅不同的 `src`。

```text
macro_build/
  __init__.py
  models.py
  config.py
  source.py
  resolve.py
  generate.py
  staging.py
  audit.py
  report.py
  cli.py
config/
  project.yml
  packages.yml
  capabilities.yml
  tools.yml
  policies.yml
schemas/
  project.schema.json
  packages.schema.json
  capabilities.schema.json
  tools.schema.json
  policies.schema.json
  target-evidence.schema.json
  build-kit.schema.json
tests/
  fixtures/
  test_config.py
  test_source.py
  test_resolve.py
  test_generate.py
  test_staging.py
  test_audit.py
  test_cli.py
build/kits/<kit-id>/
dist/build-kit/<kit-id>.zip
```

配置采用 YAML，严格通过 JSON Schema 验证。新增锁定的 `PyYAML` 和 `jsonschema` 依赖；Python 仍为 `>=3.12`。CLI 使用标准库 `argparse`，入口为 `macro-menu-build`，`main.py` 只委托 CLI。

### 4.2 公共 Python 接口

```python
load_manifests(root: Path) -> ManifestSet
scan_sources(config: ProjectConfig) -> SourceInventory
resolve_catalog(
    inventory: SourceInventory,
    manifests: ManifestSet,
    evidence: tuple[EvidenceRecord, ...] = (),
) -> ResolvedCatalog
validate_catalog(catalog: ResolvedCatalog) -> ValidationReport
make_build_plan(catalog: ResolvedCatalog) -> BuildPlan
stage_build_kit(plan: BuildPlan, out_root: Path) -> BuildKitReceipt
verify_build_kit(path: Path) -> VerificationReport
audit_catvba(path: Path, expected: BuildKitManifest) -> AuditReport
```

模型使用冻结 dataclass 和 enum。可预期的源码/配置问题进入排序稳定的 `ValidationReport`；只有 I/O、锁竞争和内部不变量破坏抛异常。

### 4.3 编码与扫描

- `.bas/.cls/.frm` 先严格 UTF-8 解码，失败后严格 CP936；无法唯一解码即失败。
- 既有源码进入 staging 时原字节复制；FRX 始终二进制原样复制。
- 只对生成模块使用 CP936、CRLF；B28 首轮必须验证该选择，失败则通过 `project.yml` 的显式目标编码迁移，不改原始 `Src`。
- 扫描记录相对路径、VB_Name、组件类型、编码、原始/逻辑 SHA-256、FRX 配对、标签、过程和引用风险。
- 绝对路径、当前时间和用户名不得进入可复现摘要。

### 4.4 Manifest 优先级

1. 与精确 `kit_id` 和制品哈希绑定的目标机证据决定 `verified` 状态。
2. `packages/capabilities/tools/policies` 决定包归属、能力和安全策略。
3. 源码的实际 VB_Name、过程、标签和 `%UI` 是不可覆盖事实；清单冲突即失败。
4. CLI 只允许覆盖输入、输出和报告格式，不能覆盖包归属或许可证结论。
5. 生成文件没有真源优先级。

`tools.yml` 为每个工具定义显式稳定 `tool_id`。模块或入口改名时通过 alias 保留旧 ID；不得从 Caption 或模块名临时推导生产 ID。

### 4.5 CLI 和退出码

```text
macro-menu-build inventory
macro-menu-build validate
macro-menu-build plan
macro-menu-build build-kit --channel dev|candidate
macro-menu-build verify-kit <kit>
macro-menu-build audit-catvba <returned.catvba> --expect <kit-manifest.json>
```

- `0` 成功；
- `1` 校验或策略失败；
- `2` CLI/schema/config 错误；
- `3` 编码、组件或标签解析失败；
- `4` I/O、锁或 staging 失败；
- `5` 生成物自校验/哈希失败；
- `6` 回传 CATVBA/证据不匹配；
- `7` 内部错误。

问题码使用 `CFG/SRC/TAG/PKG/CAP/GEN/STG/AUD` 域前缀。报告只使用仓库相对路径，不包含客户模型数据。

### 4.6 不可变 Build Kit

`kit_id` 由规范化 BuildPlan、schema/generator 版本和所有输入哈希计算。生成过程先写同卷临时目录，完成全量自校验后写 `KIT_COMPLETE`，再原子重命名；最终目录已存在且摘要相同则 no-op，不同则失败，绝不覆盖。

`candidate` Kit 要求 clean、已提交的 Git tree；`dev` Kit 允许 dirty，但必须记录 diff hash 并固定 `release_eligible=false`。两者都明确记录：

```json
{
  "target_build_required": true,
  "catvba_artifacts": [],
  "compile_status": "not-run",
  "release_eligible": false
}
```

完成目录后生成排序固定、时间戳固定的 ZIP；目录和 ZIP 均写 SHA-256。Build Kit 不含旧 CATVBA、许可证、客户数据、私钥或本机绝对路径。

## 5. 首个 Core 运行时

### 5.1 首批五个 `core-candidate`

1. `core.healthcheck`：构建/协议版本、R28/x64 环境、Core 包状态、活动文档类型和基础对象可访问性；不枚举 VBIDE References，不修改许可证。
2. `core.document-summary`：活动文档通用类型、保存/只读状态和基础统计；名称、路径只允许显示，不写生产日志。
3. `core.product-tree-audit`：遍历当前已可访问的 Product 树，统计实例/引用、空 Part Number 和 Part Number 重复度；不调用 ApplyWorkMode、不打开文档、不清空 Selection。
4. `core.part-structure-audit`：统计 Body/HybridBody 等普通结构；不访问测量、参数公式、KWA/EKL，不 Update。
5. `core.drawing-structure-audit`：统计普通 CATDrawing 的 Sheet/View/Table；源码不得声明 Layout2D/LO1 类型。

五项在 B28 三 profile 证据完成前均为 candidate。任一工具在一个 profile 失败，该工具移出 Core 或进入 Baseline Extension；菜单、HealthCheck 和其他已通过工具不受拖累。

所有遍历默认最大 10,000 个节点、最大深度 128；超限返回明确的 `LIMIT_REACHED`，不继续访问模型。

### 5.2 模块边界

```text
MM_Entry.bas             唯一 CATMain/Core_Invoke 入口
MM_Protocol.bas          MM/1 请求响应校验
MM_Dispatch.bas          生成的 Select Case 白名单
MM_BuildInfo.bas         生成的版本、kit、Debug/Prod 常量
MM_Error.bas             结果码和错误映射
MM_Log.bas               脱敏最小日志
MM_TryGet.bas            极小 Resume Next 探测包装
C_MMContext.cls          每次调用的 CATIA 上下文
C_MMStateGuard.cls       调用前后状态比较/恢复
C_MMResult.cls           Core 内部结果对象
MM_HealthCheck.bas
MM_DocumentSummary.bas
MM_ProductAudit.bas
MM_PartAudit.bas
MM_DrawingAudit.bas
cls_MnUI.cls             保留数据职责，输入改为静态目录
Cls_allBTNEVT.cls        按 tool_id 调用，不拼宏名
Cat_Macro_Menu_View.frm  保留现有资产，修复合法 Name 和启动副作用
```

Core staging 不包含 A00_Menu 的源码扫描路径、KCL、Cls_DynaWD、Cls_PDM、Cls_XLM、Cls_VbaMdlMgr、DevTools 或 Optional 模块。

### 5.3 协议与 Dispatcher

同一 Core 工程内的菜单直接调用固定入口：

```vb
Public Function Core_Invoke(ByVal request As Variant) As Variant
```

协议为零基 Variant 数组：

```text
Request  = ["MM/1", requestId, commandId, clientVersion, options]
Response = ["MM/1", requestId, status, code, displayMessage, data, meta]
```

`options/data/meta` 只允许 Empty、Boolean、Long、Double、String 和嵌套 Variant 数组。禁止 COM 对象、Dictionary、Collection、自定义类、Error Variant 和任意库/模块/过程定位信息。协议限制嵌套深度 4、单字符串 4,096 字符、返回行数 1,000；超限返回协议错误。

未来 Optional 包暴露同一协议，通过固定受管路径和固定入口由 `SystemService.ExecuteScript` 调用；该跨 CATVBA 调用必须先在 B28 单独验证，首个里程碑不加载 Optional。

### 5.4 状态、错误与日志

Core 原则上不改 CATIA 状态。每次调用局部取得对象，不缓存可失效 COM 引用，不使用 `As New` 全局对象。

`C_MMStateGuard` 记录活动文档、活动窗口、Selection 数量，以及框架实际触碰的应用属性。所有入口采用单一 `CleanExit` 模拟 finally；恢复失败追加诊断，不覆盖原始错误。窄小 `TryGet*` 以外禁止 `On Error Resume Next`。

结果码固定为：

```text
0  OK
10 CANCELLED
20 NOT_APPLICABLE
30 CAPABILITY_UNAVAILABLE
40 VALIDATION_FAILED
50 STATE_CHANGED
60 TOOL_FAILED
70 INTERNAL_ERROR
80 LIMIT_REACHED
```

生产日志目录为 `%LOCALAPPDATA%\MacroMenu\logs`，最多保留 7 天且总量不超过 5 MB。仅记录 UTC、build/kit、request/tool、结果码、耗时、计数和通用文档类型；不记录用户名、完整路径、文档名、对象名、PN、参数值或模型内容。日志写入失败不得导致工具失败。

### 5.5 Debug 与 Production

- Debug 和 Production 由生成的 `MM_BuildInfo` 编译时常量区分，Production 不能运行时切换到 Debug。
- Debug 允许阶段信息、协议转储和更详细但仍脱敏的错误，日志上限 14 天/20 MB。
- Production 只保留静态命令白名单和最小日志，不显示原始 Err.Description。
- 两种构建均禁止 VBProject/CodeModule、Office、网络、Shell、SPA/KWA 和许可证修改。
- VBE 工程保护只能防误编辑，不作为保密、签名或完整性控制。

首个里程碑复用现有菜单 Form，不新增无法在本地可靠生成的 FRX 设计器资产。工具先以短摘要对话框显示结果；完整结构化 Response 保留给目标机测试和后续报告 UI，首轮不把客户数据写文件。

## 6. 安全与失败策略

- 未分类模块、未知标签、编码歧义、包重复/遗漏、Core 禁止引用或危险 API 均 fail-closed。
- 未安装或不可用工具入口保持可见但禁用，并显示缺失包/profile/能力原因。
- 许可证检查区分类型库、API/工作台、DSLS 权益、当前会话 checkout；不得调用 `SetLicense(..., False)` 探测。
- `LicenseReset.catvbs`、模块自修改、PowerShell、WScript、外部 Google/微信访问、硬编码工具路径和旧备份模块不得进入 Build Kit。
- 首个里程碑没有写模型、保存、删除、改名、复制、导出或数据外发功能。
- 后续破坏性工具必须另建规格，采用全量预检、预览、提交、逆序回滚和文档备份。

## 7. 测试与状态门

### 7.1 本地自动化

Python 实现严格 TDD：先写失败测试、确认因缺失行为失败，再写最小实现。覆盖：

- UTF-8/CP936/非法字节及原字节复制；
- VB_Name、重复模块、FRM/FRX 配对、路径大小写冲突；
- GP/EP/%UI、入口、稳定 tool ID、合法唯一 MSForms Name；
- 未分配/重复包、非法共享、Optional→Optional、DevTools 泄漏、Core 禁止 API；
- 三 profile 缺一、组合会话误判、证据哈希不匹配；
- 生成顺序、VBA 字符串转义、CP936/CRLF、跨目录确定性；
- staging 写入故障、并发锁、原子 rename、同摘要 no-op、路径穿越；
- CLI 全部退出码和 text/JSON 报告一致性；
- 正常/损坏 CFB、模块/引用/FRX/签名漂移。

本地无法执行 VBA。每个 VBA 工具先写目标测试条目和离线结构/golden 失败测试，再写源码；真正行为只有 B28 测试可转为 PASS。本地永远不能以结构测试替代 Compile/运行。

### 7.2 状态门

```text
G0 INPUT-FROZEN
G1 KIT-READY
G2 B28-ENV-ATTESTED
G3 BUILT-UNVERIFIED
G4 CORE-MATRIX-PASS
G5 SECURITY-PACKAGE-PASS
G6 PILOT-READY
G7 RELEASE-APPROVED
```

每门状态只能是 `NOT_RUN/PASS/FAIL/BLOCKED/EXPIRED`。输入、源码、manifest、schema、generator 或冻结策略变化使 G0-G7 失效；SP/HF/引用/构建环境变化使 G2 以后失效；候选二进制变化使 G3 以后失效；DSLS/profile 变化使 G4-G7 失效。任一上游门失效时，所有下游门都必须重新计算，不得继续显示有效 `PASS`。

G1 要求 clean Git tree、完整静态检查、不可变 Kit 和哈希。G2-G7 必须在目标/企业环境执行；当前没有精确 SP/HF、三套隔离 profile、审批人或制品库信息时，保持 BLOCKED，不猜测。

### 7.3 B28 Core 矩阵

对每个 Core 工具分别在 AB3-only、MD2-only、HD2-only 验证：

- 无文档、CATPart、CATProduct、CATDrawing；
- 未保存、已保存、只读；
- 空对象、空集合、Unicode/超长名称和遍历超限；
- 执行、取消、不适用、异常、重复执行、CATIA 重启；
- 调用前后活动文档、窗口、Selection、工作台和应用属性一致；
- 无 Office、断网、禁 PowerShell/WSH；
- References 无 MISSING，无 B30/x86/Temp/用户目录路径；
- Compile、保存、关闭宿主、重新打开、再次 Compile/HealthCheck。

## 8. B28 交接、安装与回滚

Build Kit 至少包含：kit manifest、分包源码、生成模块、导入顺序、Reference 允许清单、测试计划、证据模板、构建/安装/回滚手册和 SHA256SUMS。B28 端必须从空白工程导入，禁止 Save As 旧 CATVBA。

Production 默认安装到 `%ProgramData%\MacroMenu\<version>\`，普通用户只读，只有受管发布账号/管理员可写；Debug 使用 `%LOCALAPPDATA%\MacroMenu\debug\<build-id>\`，带到期清理。若 R2018 实测能可靠验证 VBA 签名，则最终保存后签名再计算哈希；否则采用企业签名安装包或 ACL+哈希+双人审批例外。

版本并存安装，切换受管宏库注册，不覆盖旧目录。正式回滚只切回以前具有完整 G7 发布记录、哈希仍匹配且未撤回的 R28 制品；模型数据恢复另依赖文档备份。现场禁止热改 Production CATVBA，修复必须回到源码并重跑状态门。

## 9. Git 与远端同步

- 以 `origin/dev` 为唯一代码上游；每次同步先 fetch 并记录 old/new SHA，在临时 `intake/dev-YYYYMMDD` 分支审查，再用显式 merge commit 吸收到 refactor 分支。
- 已形成 Build Kit 或目标证据的提交不 rebase。
- `origin/main` 不合入 refactor；只观察发布/workflow/docs，确需修复时逐项 port 或 cherry-pick。
- 每个 Kit 固定 `upstream-dev-cutoff`；远端后续更新不会静默改变 Kit。安全阻断修复到来时撤销旧 Kit并重建。
- 未来远端治理优先新建共享 dev 历史的受保护 `release/r28`，再决定是否替换旧 main；当前任务不修改远端分支。

## 10. 文档与上下文恢复

- 每个设计节确认后更新 `Docs/CATVBA重构调查与决策记录.md`。
- 完整设计存放在 `Docs/superpowers/specs`，任务计划存放在 `Docs/superpowers/plans`。
- 项目级当前状态与压缩恢复入口统一使用 `Docs/STATUS.md`；任务级进度写入日期化实施计划或独立证据记录。每个通过双重 review 的任务写入提交范围。
- 每个实现阶段开始/结束记录输入 SHA、测试命令/输出、风险和下一动作。
- 每次 upstream intake、Build Kit、B28 build/profile 会话生成独立、不可覆盖的 sync/kit/build/evidence 记录。
- 只有 Git 中的设计、计划、提交和证据可决定是否重做任务；不依赖对话记忆。

## 11. 验收标准

本地里程碑完成必须同时满足：

- 离线测试全部通过且有真实 RED→GREEN 证据；
- 扫描前后原始 `Src`/FRX 哈希一致；
- 77 个现有文本组件全部被唯一分类或 Quarantine；
- Core staging 不含禁用引用/API/模块；
- 相同输入两次产生相同 kit_id、目录摘要和 ZIP SHA-256；
- Build Kit 明确 `compile_status=not-run`、`release_eligible=false`；
- 五个 Core 工具的目标测试条目、协议和源码进入 Kit；
- 文档、CLI 帮助、schema 和实际输出一致；
- 当前两个旧 CATVBA 仍保持原哈希且未被改写。

只有有效的 G0-G6 全部通过（其中 G2-G6 在目标/企业环境执行）后，才能把 CATVBA 称为 `pilot-ready`；只有 G7 通过后，才能称为 `release-approved` 或 Production 制品。

## 12. 草案采用的默认值与外部阻塞（整体待书面复核）

草案默认：YAML+JSON Schema、显式稳定 tool ID、candidate Kit 必须 clean、目录与确定性 ZIP同时生成、本地最小日志 7 天/5 MB、Production 只读本机安装、Debug 与 Production 物理分离、首轮无 Optional。这些默认值随整体设计一起待书面复核。

外部阻塞不会妨碍本地实现，但会阻止 G2 以后状态：正式 Windows/R2018 SP/HF、B28 References GUID/版本、三套真正隔离的 profile、DSLS L3/L4 证据、企业签名/ACL方案、脱敏测试数据、审批人和制品库。
