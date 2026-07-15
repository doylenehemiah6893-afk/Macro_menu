# CATVBA B28 G2/G3 证据工具与操作交接设计

> 状态：APPROVED — 用户已于 2026-07-14 书面确认
>
> 上位规格：
> [CATVBA B28 验证、许可证与交付设计](2026-07-13-catvba-b28-validation-delivery-design.md)
>
> 当前输入状态：G0/G1 仅有 A 环境证据；G2-G7 仍为 `BLOCKED`

## 1. 目的

本设计把上位规格中的 B28 环境证明、空工程构建和证据包要求落实为可执行、可验证的 G2/G3-C
工作流。它解决四个当前阻断：

1. Core 的 `reference_allowlist=[]` 尚未描述 B28 宿主默认 Reference 和 MSForms 实际合同；
2. Build Kit 中的 `target-test-plan` 是不可变测试合同，不是可填写的结果文件；
3. 现有 `target-verification.json` 只是占位模板，不能闭合上位规格要求的证据文件；
4. 缺少从 Kit 初始化会话、验证回传证据、审计 returned CATVBA 和计算 Gate 候选结论的离线工具。

本设计不在 A 环境声称执行 CATIA，不自动控制 CATIA/VBE，不实现 Fleet-SPA/Fleet-FTA，不改变
G4-G7 的验收要求。

## 2. 范围与非目标

### 2.1 本轮范围

- 生成并验证 Core-only 的 B28 discovery、G2 和 G3-C 会话证据包；
- 建立 B28 Reference discovery → A 环境批准 → 重建 Kit → 正式验证的两阶段闭环；
- 对环境、权益、Reference、Compile、测试、状态差异和制品建立严格 JSON Schema；
- 将不可变 target case 与独立结果记录绑定；
- 增强 returned CATVBA 的 Reference 合同比对；
- 提供逐步人工操作手册、停止条件、脱敏规则和 VM 快照恢复要求；
- 修复会误导操作员的陈旧状态文档；
- 工具实现后重新执行 G0/G1，先生成唯一 discovery handoff Kit；Reference 事实获批并进入 manifest 后，
  再生成唯一正式 handoff Kit。

### 2.2 明确非目标

- 不通过 COM、SendKeys、PowerShell、WSH 或 GUI 自动化驱动 CATIA/VBE；
- 不自动勾选 Reference，不修改 DSLS/Licensing Repository，不调用 `SetLicense`；
- 不把 discovery 会话升级为 G2/G3 PASS；
- 不实现 SPA/FTA extension source、`Fleet_Invoke` 或跨 CATVBA 临时文件通信；
- 不执行 G4 三 profile 矩阵、G5 故障注入、G6 安装试点或 G7 发布；
- 不把旧 CATVBA 用作构建种子、回滚制品或正确性证据；
- 不在本轮固定 Production 安装根、签名策略或宏库注册方式。

## 3. 核心决策

### 3.1 两阶段 Reference 流程

正式 G3-C 之前必须经过：

```text
B28 discovery（只观察，不升 Gate）
  -> A 环境复核 Reference 事实
  -> 批准并提交结构化 Reference 合同
  -> 重新执行 G0/G1、双构建和双路径 verifier
  -> 唯一 handoff receipt
  -> 正式 G2
  -> Core-only G3-C
```

discovery 可以使用当时有效的 G1 Kit 绑定环境事实，但不得把其 returned CATVBA 当作合格 G3 制品。
若 discovery 导致源码、manifest、schema、generator、Reference 合同或审计规则变化，旧 Kit 只保留为历史
证据，新 Gate 链必须绑定新 Kit。

### 3.2 package-scoped Gate

当前只有 Core 具有非空源码和工具。G3 本轮只能产生 `G3-C`：

```text
gate_id = G3-C
package_id = core
```

`G3-C` 不等于完整 Fleet build，不使 G5 或 G7 前进。未来 Fleet-SPA/Fleet-FTA 各自建立独立 G3/G5
收据；空 import-order 不能作为“空包通过”。

### 3.3 不可变合同与可变观察分离

- Kit 内 `target-test-plan/target-test-plan.json` 保持不可变，全部 `status=not-run`；
- 操作结果写入会话包的 `test-results.json`，不得回写 Kit；
- 每条结果通过 `case_id`、case definition SHA-256、Kit identity 和 session identity 绑定；
- 修改 Kit 内 target plan 为 `pass`、添加/删除/重排 case 均继续由 Kit verifier 阻断。

### 3.4 自动验证不等于事实证明

离线工具只能证明证据包内部一致、哈希闭合、字段满足门槛，不能证明操作员填写内容真实。Gate 输出分为：

```text
computed_outcome = eligible | fail | blocked
approval_status = pending | approved | rejected
```

只有 `computed_outcome=eligible`、独立复核记录为 `approved`，并且最终 sealed directory/ZIP 再验证通过时，
状态文档才可把对应 Gate 更新为 `PASS`。工具不得直接生成自称 `PASS` 的操作员输入。

## 4. 唯一身份与 handoff

### 4.1 Handoff receipt

每次目标机交接只允许一个 `handoff.json`，至少包含：

- schema version；
- handoff ID、purpose `discovery|formal`、创建 UTC、有效期或撤回状态；
- Kit ID、catalog SHA-256、manifest SHA-256、manifest digest；
- ZIP SHA-256、ZIP sidecar SHA-256；
- work commit、work tree、work branch；
- upstream/fork dev cutoff；
- package ID，本轮固定为 `core`；
- target `CATIA R2018/VBA7 64`；
- `compile_status=not-run`、`release_eligible=false`；
- 生成命令、目录/ZIP verifier 结果；
- 准备者与复核者记录 ID。

操作员不得在多个 Kit 中自行选择。若 handoff 被撤回、过期、哈希不匹配或 Git identity 不同，必须停止。
每个阶段只允许一个 active handoff；formal handoff 签发时必须撤回 discovery handoff，并把撤回记录纳入
A 环境状态文档。离线 verifier 只能证明随包 revocation snapshot 在签发时一致，不能声称证明签发后的远端
撤回状态；runbook 因而必须要求交接前在 A 环境重新确认 active handoff。

### 4.2 当前 Kit 的处置

实现本设计会改变受治理 Git tree，因此当前历史 Kit 不直接成为后续 handoff。工具实现完成后必须重新：

1. frozen sync 和全量测试；
2. inventory/check；
3. 两个独立输出根的 Build Kit；
4. 两目录+两 ZIP verifier；
5. 比较 Kit ID、catalog bytes、manifest SHA、ZIP SHA 和 ZIP bytes；
6. 在 Reference 合同仍为 `discovery-required` 时只生成 discovery `handoff.json`；
7. 更新 G0/G1 A 环境证据，但保持 G2-G7 `BLOCKED`。

discovery 回传并由 A 环境批准结构化 Reference 合同后，合同变更会再次改变 manifest digest、catalog 和
Kit identity；因此必须再执行上述 1-5，并生成另一份 formal `handoff.json`。discovery Kit 与 formal Kit
不得复用 handoff ID，也不得让操作员自行选择。

## 5. Target session 目录合同

`init-target-session` 从已验证 Kit 生成 Kit 外部的可写草稿目录：

```text
target-session-<session_id>/
├─ session.json
├─ handoff.json
├─ environment.json
├─ entitlements.json
├─ references.json
├─ compile-result.json
├─ test-results.json
├─ state-diff.json
├─ artifact-manifest.json
├─ operator-records/
│  ├─ index.json
│  └─ <脱敏截图或人工记录>
├─ returned-catvba/
│  └─ core.catvba                 # g3-c 必需，discovery 可选，g2 禁止
├─ prerequisites/                 # 仅 g3-c 必需
│  └─ g2-evidence.zip             # 完整、已验证的 sealed G2 包
├─ gate-receipt.json
├─ approval.json
├─ SHA256SUMS
└─ SESSION_COMPLETE
```

会话生命周期固定为：

```text
可写 capture draft
  -> 操作员标记 capture complete
  -> validator 计算 evidence payload digest
  -> evaluator 生成绑定 payload digest 的 detached gate receipt
  -> 独立复核者生成绑定 payload/gate receipt digest 的 detached approval
  -> packer 复制内容并生成 sealed directory、SHA256SUMS、SESSION_COMPLETE 和 ZIP
  -> 对 sealed directory/ZIP 再验证
```

capture draft 不含 `gate-receipt.json`、`approval.json`、`SHA256SUMS` 和 `SESSION_COMPLETE`；G3-C draft
包含已批准的 G2 prerequisite 副本。evaluator 和复核者都不得原地修改 draft，packer 也只写新输出根。
initializer 只建立 `capture_status=in-progress`、`ended_at=null` 的草稿；在尚未发生目标机采集时，host/VM/
snapshot、environment 和 operator witness 使用 `null|unknown|not-run`，不得以模板值冒充现场事实。初始
operator index 为空，handoff 的 prepared/review ID 是 detached provenance，不复制成当前 session record。
`SHA256SUMS` 覆盖除自身和 `SESSION_COMPLETE` 外的全部普通文件；完成标记绑定 SHA 清单、payload digest、
gate receipt digest 和 approval digest。seal 后禁止原地修改；更正必须创建新 session，并通过
`supersedes_session_id` 指向旧 session，旧包本身保持不变。

capture validator 只判断结构、绑定、哈希和 mode 状态是否合法，不要求业务步骤成功。`computed_outcome` 为
`fail|blocked` 的 receipt 也允许经复核后 seal，以保留失败历史；只有 `eligible + approved + sealed-valid`
可以更新 Gate PASS。

`artifact-manifest.json` 在三种 mode 都存在：G2 固定 `artifact_status=not-produced` 且禁止 returned 文件；
G3-C 和 discovery 允许 `not-produced|returned`，只有 `returned` 时才允许且要求恰好一个 `core.catvba`。
这使导入/Compile 提前失败的 G3-C 仍可封存；但 G3-C `eligible` 必须有 returned artifact。discovery returned
文件永远不能成为正式 G3 制品。

模式文件矩阵固定如下；“必需”表示文件必须存在且满足该 mode 的字段约束，“禁止”表示目录中出现即失败：

| 文件/目录 | discovery | g2 | g3-c |
|---|---|---|---|
| 八份 session evidence JSON、handoff、operator index | 必需 | 必需 | 必需 |
| returned `core.catvba` | 可选 | 禁止 | 可选；`returned` 时恰好一个 |
| 完整 sealed G2 prerequisite ZIP | 禁止 | 禁止 | 必需且恰好一个 |
| 当前 gate receipt + approval | 仅 sealed 必需 | 仅 sealed 必需 | 仅 sealed 必需 |
| `SHA256SUMS` + `SESSION_COMPLETE` | 仅 sealed 必需 | 仅 sealed 必需 | 仅 sealed 必需 |

证据包成员路径只允许 portable ASCII。`SHA256SUMS` 使用 ASCII relative path、bytewise 排序、LF 和小写
SHA-256，格式与 Kit 的确定性清单规则一致。`SESSION_COMPLETE` 是 canonical JSON，至少绑定 session ID、
SHA 清单所覆盖文件集合形成的 bundle content digest、evidence payload digest、`SHA256SUMS` SHA-256、
gate receipt SHA-256 和 approval SHA-256；completion marker 自身不进入任何自引用 digest。

不允许 symlink、hardlink、路径穿越、Windows 保留名、大小写/Unicode portable collision、额外未声明文件
或 ZIP 非普通文件。

## 6. 通用绑定模型

每个 session evidence JSON 顶层都必须包含完全相同的 `binding`：

```text
schema_version
session_id
session_mode = discovery | g2 | g3-c
package_id = core
profile_id = P-AB3 | P-HD2 | P-MD2 | P-ALL | P-PROD | DISCOVERY
kit_id
catalog_sha256
manifest_sha256
manifest_digest
work_commit
work_tree
handoff_id
target = CATIA R2018/VBA7 64
```

这里的 session evidence JSON 指 `session/environment/entitlements/references/compile-result/test-results/
state-diff/artifact-manifest/operator-records/index`。handoff、detached Gate/approval 和嵌套 G2 evidence
各自使用其原始 binding，并通过 digest/ID 与当前 session 交叉绑定，不能伪装成当前 session evidence。

validator 对适用文件执行逐字段相等比较，不允许缺失、额外、大小写折叠或宽松 ID 匹配。所有时间为带
`Z` 的 RFC 3339 UTC，开始/结束/重启/封包必须满足单调时序。

mode/profile 交叉约束为：discovery 只能使用 `DISCOVERY`；G2/G3-C 只能使用一个明确的
`P-AB3|P-HD2|P-MD2|P-ALL|P-PROD`，且 entitlements 必须证明该 session 满足
`(AB3 OR HD2 OR MD2) AND SPA AND FTA`。G3-C 必须与其 G2 prerequisite 的 profile、匿名 host/VM、
CATIA SP/HF 和 Reference contract digest 精确相等。单个 profile 的 G2/G3-C 不能被描述为 G4-C，也不能
替代三个隔离最小 profile。

discovery mode 只接受 `purpose=discovery` 且合同为 `discovery-required` 的 handoff；G2/G3-C 只接受
`purpose=formal` 且合同为 `approved` 的 handoff。G3-C 必须复用其 G2 prerequisite 的 formal handoff ID，
不能在两个 formal Kit 之间跨接 Gate。

## 7. 证据 Schema

Schema 放在 `catvba_refactor/schemas/target_evidence/`，与四份输入 manifest schema 物理隔离。

### 7.1 `session.json`

记录 session mode、capture status `in-progress|complete`、VM/主机匿名 ID、快照 ID、构建账号/普通用户角色、
开始结束 UTC、是否触及 Production 宏库、supersedes 关系和备注记录 ID。禁止用户名、客户名、机器全名、
完整用户路径和凭据。

初始化 draft 的三个匿名环境 ID 和 `ended_at` 均为 `null`；操作员完成采集时才写入实际匿名 ID、结束 UTC
并把 status 改为 `complete`。capture validator 接受这一 draft，Gate receipt 和 sealed evidence 只接受
`complete`。

### 7.2 `environment.json`

记录：

- Windows edition/build/patch；
- CATIA V5-6R2018/R28/B28、GA/SP/HF；
- CATIA environment 名称或匿名 ID、安装根类别与哈希；
- DS VBA/VBE 版本、VBA7/Win64 probe；
- DSLS client/server 匿名 ID、连接模式；
- Office、网络、PowerShell、WSH 状态；
- 构建账号和普通用户是否隔离；
- B30、x86、VBA6、SysWOW64、Temp/user COM 污染扫描结果。

初始化时没有现场观察，因此 Windows/CATIA/CATIA environment/VBA/DSLS、账号隔离、fingerprint 和
environment operator record 均为 `null`，security 为 `unknown`，pollution scan 为 `not-run`。非空
fingerprint 必须具备完整稳定投影并可复算，禁止部分填充。

路径证据使用：允许根类别、相对路径、basename、规范化路径 SHA-256。CATIA/Windows 公共安装根可以记录
规范化路径；用户目录、客户目录和 Temp 路径只记录类别、hash 和脱敏显示值。

`environment_fingerprint` 定义为以下 canonical JSON 的 SHA-256：匿名 host ID、VM/snapshot lineage ID、
Windows edition/build/patch、CATIA R28/B28 GA/SP/HF、VBA/VBE/VBA7/Win64、安装根类别/hash、DSLS 连接类别、
profile ID 和 Reference contract body digest。开始/结束时间、operator record ID、自由备注和 checkout 瞬态
状态不进入 fingerprint。G3-C 必须与 G2 的 fingerprint 精确相等；任一输入变化都必须重新执行 G2。
G3-C initializer 从 sealed G2 继承该 fingerprint 的稳定投影和 host/VM/snapshot identity；为保持匿名
容器结构，可保留 CATIA environment 与 DSLS endpoint 的匿名 ID，但继承判定只比较 fingerprint 投影。security、
账号隔离、pollution scan 和 operator record 属于当前 G3-C 瞬态观察，必须重新置为
`unknown|null|not-run`，不得复制成当前 session 事实。
G3-C `started_at` 不得早于 prerequisite 的 `sealed_at`；否则即使内容有效也属于时间倒序，初始化必须停止。

### 7.3 `entitlements.json`

分开记录：

1. configuration/product entitlement；
2. 类型库/Reference 可见性；
3. API/Workbench 可取得性；
4. 当前 session checkout；
5. 工具运行结果。

`baseline_any_of` 对 P-AB3/P-HD2/P-MD2/P-ALL 表示所选 profile；DISCOVERY 和尚未观察现场组合的
P-PROD 初始化为 `[]`。`additional_required=[SPA, FTA]` 是要求，不等于已观察到 entitlement。

每一层都有独立 `not-run|observed|available|unavailable|blocked|failed` 状态和 operator record ID。不得从
上层状态推导下层通过，不得把产品名称当作 API 或 checkout 证据。记录必须声明未使用 `SetLicense`、
脚本勾选或 Licensing Repository 修改。

### 7.4 `references.json`

在以下 observation points 记录完整集合，并为每个 point 提供 `not-run|observed|blocked|failed` 状态：

```text
blank-project
post-form-import
post-all-import
post-save
post-restart
```

每个 Reference 至少包含：

- observation record ID、stable reference ID；
- name、description；
- canonical GUID；
- major/minor；
- builtin/host-default/package-added/import-introduced 分类；
- `missing`；
- resolved path kind、basename、relative path 或脱敏值、path SHA-256；
- architecture `x64|x86|unknown`；
- release provenance `B28|B30|unknown`；
- operator record ID。

五个 point 记录必须始终存在。G2 的 blank-project 允许 `observed|failed|blocked|not-run`，其余固定
`not-run`；G3-C/discovery 的每个 point 允许 `observed|failed|blocked|not-run`，以便如实封存中途失败。
每个集合必须确定排序，observation record ID 必须唯一，并在 `observed` 时与适用 Reference 合同中对应
point 的精确集合及允许 transition 比较。Gate evaluator 只有在 G2 blank 或 G3-C 五点均为 `observed` 时才
可能给出 `eligible`；`failed` 映射 `fail`，`blocked|not-run` 映射 `blocked`。
同一 stable reference ID 的重复观察必须保留为不同 observation record，不能因去重而隐藏；正式结果为
`fail`。

已观察到 B30、x86、VBA6、SysWOW64、Temp、user profile 或 MISSING 污染时，正式 G2/G3 结果为 `fail`；
architecture、release provenance 或 DLL 身份仍为 `unknown` 时结果为 `blocked`。两类情况都不得自动修复。

### 7.5 `compile-result.json`

分别记录：

```text
blank-project
post-import
post-save
post-restart
```

每条包含独立且唯一的 Compile record ID、`not-run|passed|failed|blocked`、开始/结束 UTC、CATIA/VBE
operator record ID、错误阶段、模块和脱敏错误摘要。Compile record ID 标识 Compile 事件本身，不得复用
CATIA/VBE witness ID。四条记录始终存在；G2 全部为 `not-run`，discovery 按实际步骤记录。G3-C evidence 可如实
记录四种状态；只有 post-import、post-save 和 post-restart Compile 均为 `passed` 才可能 `eligible`。Kit manifest 中的 `compile_status` 仍保持
`not-run`，不得反向改写。

### 7.6 `test-results.json`

每条结果包含：

- case ID、case definition SHA-256；
- session/profile/package/tool identity；
- execution point `not-run|post-restart`；
- execution-point Compile record ID；
- `not-run|passed|failed|blocked`；
- expected result code/state；
- observed result code/state；
- 开始/结束 UTC；
- operator record ID；
- state-diff record ID；
- failure classification。

结果文件必须恰好包含 Kit 内全部 30 个 case，并保持 target plan 的 canonical 顺序和不可变 case definition；
“本阶段不执行”由结果状态 `not-run` 表示，不能省略记录。discovery/G2 的 30 项全部为 `not-run`。G3-C 的
`context.core.healthcheck.none` 允许 `not-run|passed|failed|blocked`：实际执行时固定
`execution_point=post-restart`，绑定 post-restart Compile record，且测试开始 UTC 严格晚于该 Compile 的结束
UTC；未执行时 `execution_point=not-run`。其余 29 项固定 `not-run/execution_point=not-run`。
所有 `not-run` 项的 Compile/operator/state-diff record IDs 和 observed fields 必须为 `null`，不能保留陈旧值。
Gate evaluator 把 smoke `passed` 作为 eligibility 条件、`failed` 映射为 `fail`、`blocked|not-run` 映射为
`blocked`。
完整 context/lifecycle/profile case 保留给 G4-C。缺失、重复、额外、未知、重排、跨 Kit 或不允许状态必须
阻断封包。

### 7.7 `state-diff.json`

只记录脱敏、通用状态：

- active document generic type；
- saved/read-only/dirty 候选状态；
- selection count；
- alerts/refresh/interactivity 进入前后状态；
- opened/closed document count；
- error/cancel/restart 后是否恢复；
- 操作前后 scalar hash 或计数。

禁止记录文档名、完整路径、PN、对象名、参数值、模型内容或截图中的客户数据。

文件包含总体状态和按 case ID 绑定的 records。discovery/G2 固定为 `not-run` 且 records 为空；G3-C records
允许为空或只包含 `context.core.healthcheck.none` 的 post-restart state record；存在时必须与对应 test
result/operator record 双向绑定，G3-C `eligible` 时该 record 必须存在且状态为 `observed`。

### 7.8 `artifact-manifest.json`

记录 artifact status。`not-produced` 时禁止任何 returned file/hash/Compile 绑定；`returned` 时记录 CATVBA
文件名、package ID、SHA-256、size、Compile/restart record IDs、模块集合、Form/FRX 身份、Reference
observation hash、签名流观测、Kit source receipt hash、readonly return 状态。不得预填
`release_eligible=true`。

### 7.9 `operator-records/index.json`

每项包含 record ID、类别、相对路径、SHA-256、UTC、采集者角色和 redaction status。截图必须先经过人工
脱敏复核；若无法保证无客户数据，使用两人签字的纯文本操作记录替代，不把原图放入一般回传包。
index 只解析当前 session 实际采集的 payload。handoff prepared/review ID 属于 handoff envelope 的 detached
provenance，不要求、也禁止 initializer 合成同名当前记录。

### 7.10 Envelope 与决策 Schema

handoff、canonical payload manifest、gate receipt、approval 和 `SESSION_COMPLETE` 各有独立 schema；所有
schema 都固定版本、required fields、`additionalProperties=false`、ID/digest/time grammar 和 mode-dependent
条件。它们不复用 session evidence binding。`target-test-plan` case definition hash 明确定义为单条 immutable
case canonical JSON 的 SHA-256，结果 schema 只能引用该 hash，不能复制后改写 expected 字段。

## 8. Reference 合同模型

### 8.1 两层语义

`packages.json` 中保留：

- `reference_allowlist`：操作员允许显式加入的 Reference stable IDs；
- 新增 `reference_contract`：最终工程 Reference 的结构化精确合同，包括 host defaults。

二者不能混用：allowlist 为空表示“不允许人工新增”，不表示最终工程必须没有宿主默认 Reference。

`reference_contract` 不在五个 point 重复对象，而是包含：

- 顶层 `reference_definitions`：stable ID 到完整定义的有序表；
- `observation_points.<point>`：引用 stable ID 的精确有序数组；
- `transitions`：四个相邻 point 之间精确允许新增/删除的 stable ID 数组。

每个定义至少固定 GUID、major/minor、允许名称/description、来源分类、architecture、release 和路径 policy。
这样 stable ID 只在 definitions 中定义一次，却可在多个 point 合法出现；blank-project 的宿主基线与 Form
导入后合法出现的 MSForms 不会被误判为同一集合，也不能借“导入会加引用”放宽为任意新增。

stable ID 必须符合 package stable-ID 语法并在 `reference_definitions` 中全局唯一；GUID 统一为大写花括号
格式，major/minor 为非负整数，不接受拼接的自由文本 version；别名按明确的 Unicode/case policy 精确匹配；path policy 使用
枚举根类别、允许 basename/relative-path pattern 和可选 canonical path hash，不接受任意正则或自由文本。

resolved stable ID 由 canonical GUID 去括号/连字符并转小写后，与十进制 major/minor 组成
`ref.<32hex>.<major>.<minor>`，不依赖本地化 name。discovery 若无法取得 GUID/version，只能使用
`unresolved.<raw-identity-sha256-prefix>` 的 observation ID 并把 stable reference ID 置为 `null`；该包可以回传，
但正式合同禁止 unresolved definition。重复 stable ID 的 observation record ID 再绑定 path hash 和稳定 ordinal，
以便原样保留污染证据。

合同 schema 使用两个互斥 variant，禁止半填状态：

- `discovery-required`：固定合同 ID/version，`observations=null`、`transitions=null`，且禁止任何 approval 字段；
- `approved`：五个 observation 集合和四个相邻 transition 全部必需，且 approval provenance 全部必需。

discovery evaluator 在第一种 variant 下只做采集完整性、污染和 schema 检查，不把空合同当作 Reference 匹配
成功；formal initializer 遇到第一种 variant 必须拒绝。

`contract_body_digest` 是 definitions、observation points、transitions 和 path policy canonical body 的
SHA-256，不包含 approval metadata，避免自引用。discovery 之前合同状态为 `discovery-required`，只允许生成
discovery handoff；A 环境批准后改为 `approved`，同时记录 Reference approval record ID、reviewer role、
approved-at、discovery session ID、已 sealed 且复核通过的 discovery bundle SHA-256、其
`computed_outcome=blocked/discovery-only` receipt SHA-256、`approval_scope=observation` approval SHA-256 和
被批准的 contract body digest；这些字段一并进入 manifest digest、catalog、Kit ID 和 audit expected
identity。Core 在本轮必须具有合同；尚无源码的 Fleet package 可保持 `discovery-required`，但不能因此生成
Fleet 正式 handoff。单独把 status 文本改成
`approved` 而缺少批准证据时，manifest/schema 检查必须失败。

只有 discovery 五点全部 `observed`、transition 可解释、无污染/unresolved/duplicate Reference，且 sealed
bundle 与 observation approval 验证通过时，A 环境才能批准 contract body；否则必须修复环境后创建新的
discovery session，不能靠编辑合同绕过。

### 8.2 audit 增强

`audit-catvba` 对 returned CATVBA 至少比较：

- Reference 集合精确相等；
- GUID、major/minor；
- name/description 的批准别名；
- MISSING；
- x64/B28 provenance；
- resolved path policy；
- module/source/FRX 语义 hash；
- CATVBA/stream hash 和签名流观测。

Reference path 无法从 CATVBA 容器可靠恢复时，audit 必须把容器 Reference 与外部 `references.json`
observation 通过 GUID/version/hash 交叉绑定，并明确输出 `verified|partial|unavailable`，不得假装已验证路径。

## 9. CLI 合同

新增命令：

```text
macro-menu-build create-target-handoff <primary-build-root> \
  --compare-build-root <second-build-root> --purpose discovery|formal \
  [--supersedes-handoff <discovery-handoff.json>] \
  --revocation-snapshot <revocation-snapshot.json> \
  --prepared-record-id <id> --review-record-id <id> \
  [--created-at <utc>] --expires-at <utc> \
  --output-root <dir>

macro-menu-build init-target-session <kit> --mode discovery|g2|g3-c \
  --package core --profile <profile-id> --handoff <handoff.json> \
  [--prerequisite-evidence <g2-sealed-dir-or-zip>] \
  [--session-id <id> --created-at <utc>] --output-root <dir>

macro-menu-build validate-target-evidence <capture-dir-or-sealed-dir-or-zip> \
  --kit <kit-dir-or-zip> --phase capture|sealed

macro-menu-build evaluate-target-gate <capture-dir> --gate DISCOVERY|G2|G3-C \
  --kit <kit-dir-or-zip> --output-root <dir>

macro-menu-build record-target-approval <capture-dir> \
  --kit <kit-dir-or-zip> --gate-receipt <gate-receipt.json> --scope observation|gate \
  --status approved|rejected --reviewer-role <role> \
  --review-record-id <id> --approved-at <utc> --output-root <dir>

macro-menu-build pack-target-evidence <capture-dir> \
  --kit <kit-dir-or-zip> --gate-receipt <gate-receipt.json> \
  --approval <approval.json> --output-root <dir>
```

共同要求：

- 每条命令先完整 `verify-kit`，并把 Kit directory/ZIP identity 与 handoff 精确匹配；
- 不接受 worktree Kit、空包、未知 package、重复/缩写选项；
- 输出 canonical JSON，diagnostic 顺序稳定；
- stdout 只输出报告，stderr 输出错误；
- exit code 复用既有分类并为 evidence/gate failure 增加明确代码；
- 不联网、不启动 CATIA、不修改传入 Kit/capture/receipt/approval；
- directory/ZIP 两种输入验证语义一致；
- 所有输入失败在写输出前 fail-closed；封包以临时 sibling staging、no-replace 发布、发布后验证和
  identity-safe rollback 构成一次命令级事务。

`create-target-handoff` 在两个输出根中各要求且只接受一个同 ID 的 completed Kit directory/ZIP/sidecar，
执行两目录+两 ZIP verifier，并比较 catalog、manifest、Kit ID、ZIP bytes/hash 后才生成 detached handoff。
formal purpose 必须绑定并撤回 discovery handoff；discovery purpose 禁止 `--supersedes-handoff`。操作员不得
手写或从多个 Kit 中自行选择 handoff。

默认 session ID/UTC 可以安全生成；确定性测试必须注入固定 `--session-id`/`--created-at`。相同显式输入产生
byte-identical skeleton；随机默认值不参与“相同输入确定性”声明。

capture validator 计算 canonical payload manifest：按 portable path 排序的 `{path, sha256, size}` 列表；
`evidence_payload_digest` 是该 canonical manifest 的 SHA-256。它覆盖全部 session evidence、handoff、operator
records、returned artifact 和适用的 prerequisite，但不包含尚未生成的当前 Gate/approval/seal 文件。evaluator 输出
detached `gate-receipt.json`，至少绑定 payload digest、Gate ID、规则版本、computed outcome 和稳定排序诊断；
它不修改 `Docs/STATUS.md`。`record-target-approval` 只在独立复核者完成实际复核后把结论规范化为 canonical
`approval.json`，不得自动批准；文件至少绑定 payload digest、gate receipt SHA-256、approval scope
`observation|gate`、status、复核者 role/record ID 和 UTC。Discovery 只能使用
`approval_scope=observation`，不得使用 Gate approval。

`review_record_id` 是 Gate receipt 生成后的 detached 独立复核 provenance，不由不可变 capture 的 current
operator index 解析，也不得复用 capture operator、handoff prepared/review 或 Reference approval record ID；
复核者 role 不得等于本 session 的 builder/standard-user role。schema 保留 `pending` 以解析独立历史记录，但
`record-target-approval`、packer 和 sealed closure 只接受已完成复核的 `approved|rejected`。G3 外层复核 ID
还不得复用嵌套 G2 的 capture/approval provenance。`approved` 的 `fail|blocked` 只表示批准保存该计算结论，
不表示 Gate PASS。

Gate receipt 还必须绑定 Kit ZIP SHA-256、Kit verifier report digest、audit rule/version 和 canonical audit report
digest。G3-C 对 returned artifact 必须使用传入 Kit 重跑 `audit-catvba`，以 Kit 内 approved Reference contract、
source/import/FRX receipts 为期望，并把完整报告摘要纳入 computed outcome；无 returned artifact 时 audit 状态为
`not-run`，G3-C 只能 `fail|blocked`。sealed validator 使用同一 Kit 重算 Gate/audit，不接受只凭 receipt 文本。

`--prerequisite-evidence` 仅允许且强制用于 g3-c；initializer 必须先完整验证 G2 sealed directory/ZIP，再以
canonical ZIP 形式复制到 capture。G3-C evaluator 必须递归验证该包的 SHA/complete/receipt/approval，且其中
`computed_outcome=eligible`、`approval_scope=gate`、`approval_status=approved`。G2 与当前 session 的 Kit、
handoff、environment fingerprint、package 和 profile 必须满足明确的继承规则。嵌套验证具有独立 size、entry、
compression ratio 和 depth=1 限制。packer 在复制后重新计算所有 digest，任何 detached 文件或 prerequisite
不匹配都禁止封包。directory capture/prerequisite 的认证快照必须携带当次 pinned scan 的目录身份；其与
`output_root` 或最终输出的包含/身份重叠必须在写入前通过 canonical no-follow 路径和该快照身份拒绝，不得
通过重新打开可交换的源路径来建立身份。initializer、approval 和 packer 均不得把输出写进不可变输入树。
handoff 读取上限为 4 MiB，必须在读取前按文件大小 fail-closed，不得先按通用容器上限读入内存再拒绝。

session mode 与 Gate 参数必须精确对应：`discovery -> DISCOVERY`、`g2 -> G2`、`g3-c -> G3-C`，不允许
拿 discovery capture 请求 G2/G3-C 结论。

packer 不读取当前时钟：`SESSION_COMPLETE.sealed_at` 取 approval UTC，ZIP 使用固定元数据。相同 capture、
receipt、approval 和 prerequisite 必须产生 byte-identical sealed directory/ZIP。
directory 与 ZIP 以 no-replace sibling 形式发布；任一 stage、发布后完整验证或 root identity 复核失败时，
必须按已发布 inode 回滚本次创建的两个产物且清理临时项。由于两个 sibling 无法通过一次 filesystem rename
同时出现，外部消费者只可在命令成功返回且 directory/ZIP 均通过 sealed validator 后把它们视为完成 bundle。

## 10. G2/G3-C 计算规则

输入先分层处理，避免同一事实有时 `fail`、有时 `blocked`：

| 情况 | 处理 |
|---|---|
| 非法 schema、危险容器、非 canonical JSON、哈希/identity 被篡改 | invalid input，命令非零退出，不生成 Gate receipt |
| 必需观察未执行、证据缺失、能力不可验证、前置 Gate 不成立 | `blocked` |
| 已观察到污染 Reference、Compile/测试失败、期望与实际不符 | `fail` |
| discovery mode | 固定 `blocked/discovery-only` |
| 全部适用规则满足 | `eligible`，仍需独立 Gate approval |

规则表必须版本化、顺序稳定并由独立 test oracle 覆盖；任何未分类的新状态 fail-closed 为 `blocked`，不能由
调用方选择 `fail` 或 `blocked`。

判定优先级固定为：invalid input 直接拒绝；其余合法 capture 中只要存在明确失败即 `fail`；没有明确失败但
存在未执行/不可验证/blocked 条件则 `blocked`；最后才可能 `eligible`。因此失败后尚未执行的下游步骤不会把
已有 `fail` 降级为 `blocked`。

### 10.1 Discovery

discovery 只能得到：

```text
computed_outcome = blocked
reason = discovery-only
```

允许生成结构化观察包，但禁止 approval 为 Gate PASS。

### 10.2 G2

G2 `eligible` 至少要求：

- handoff/Kit/commit/tree/hash 全部匹配；
- Windows、B28 GA/SP/HF、VBA/VBE/VBA7/Win64 完整；
- DSLS/profile 构建方式和 entitlement 记录完整；
- 正式批准的 Reference contract；
- blank-project Reference 集合满足合同；
- 无 B30/x86/VBA6/Temp/user/MISSING/unknown DLL 污染；
- 操作账号、安全状态、VM snapshot 和回传边界完整；
- session 未触及 Production 宏库；
- 所有目标机操作均有 witness/operator record。

这里的 witness/operator record 只证明采集步骤有人见证，不等于最终 Gate approval；最终状态仍按 3.4 的
computed outcome 与 detached approval 双条件决定。

### 10.3 G3-C

G3-C `eligible` 至少要求：

- 同一 Kit 和环境具有已批准 G2 receipt；
- 从空白 Core CATVBA 构建，未使用 Save As/legacy binary；
- import set/order 与 Kit 完全一致，FRM/FRX 原子；
- post-import、post-save、post-restart Compile 均通过；
- post-restart HealthCheck smoke 结果 code 0；
- Reference 在各 observation point 满足批准合同；
- `artifact_status=returned` 且恰好一个 `core.catvba`；
- returned CATVBA、artifact manifest 和 capture payload hash 闭合；
- `audit-catvba` 的 module/source/FRX/Reference 检查无阻断诊断；
- 目标机和 A 环境均未把现场热改作为源码；
- `release_eligible=false`，G4-G7 仍不自动前进。

## 11. B28 人工操作手册最低内容

Runbook 必须逐项列出：

1. 核对 handoff ID、Kit ZIP/sidecar/hash 和撤回状态；
2. 建立/确认隔离 VM snapshot，证明未注册 Production 宏库；
3. 记录环境和 blank CATVBA Reference；
4. discovery mode 在一次性工程中严格按 `import-order/core.txt` 导入；到达 `.frm` 并连同相邻 `.frx` 完成后
   采集 post-form-import，继续到末尾、保存并重启，依次采集其余 point；不运行行为 case、不产生 `passed`、
   不批准 Reference、不升 Gate，完成后停止并回传；即使回传 CATVBA，也只作 observation，随后恢复
   snapshot，工程和制品不得用于正式 G2/G3-C；
5. 正式模式仅使用 A 环境重新批准的 Kit；
6. 新建空 CATVBA，禁止 Save As；
7. 按 `import-order/core.txt` 导入，`.frx` 只作为相邻 sidecar；
8. 每一步记录 Reference snapshot 和 operator record；
9. Compile、保存、完全关闭 CATIA/残留宿主、重开、再次 Compile；
10. 只运行批准的 HealthCheck smoke；
11. 计算 CATVBA 和证据文件 SHA-256，设为只读后回传；
12. 出现污染 Reference、导入异常、Compile 错误、哈希不符或客户数据时立即停止、隔离输出并恢复快照。

Runbook 不能依赖 PowerShell/WSH；可以给出 `certutil` 等系统工具的可选命令，但必须同时提供人工 UI/记录
路径。任何辅助脚本都不能修改 CATIA 许可证或工程 Reference。

## 12. 测试策略

### 12.1 A 环境 TDD

- schema 正向 golden tests；
- missing/extra/type/status/ID/path/time-order 负测；
- discovery 冒充 pass 负测；
- target plan/result 缺失、重复、额外、重排和跨 Kit 负测；
- 同名错误 Kit、handoff/Kit 不匹配、缺少外部 Kit 的负测；
- handoff 撤回、过期、Kit/hash/branch/commit 不一致；
- Reference GUID/version/MISSING/path/provenance/architecture 攻击；
- returned artifact/hash/SHA256SUMS 不闭合；
- directory/ZIP parity、symlink、zip bomb、portable collision、TOCTOU；
- Gate evaluator 对 eligible/fail/blocked 的独立 oracle；
- structurally valid 的 failed/blocked capture 可 seal，且不能升级 PASS；
- audit subprocess timeout/child cleanup 稳定回归；
- 两次 session skeleton/pack 输出确定性测试；
- 完整 pytest、inventory/check、双 Build Kit 和四路径 verifier。

这些测试只能证明离线工具，不得把 target case 改为 passed。

### 12.2 B28 验证

本轮目标机只完成 discovery、G2 和 G3-C。MSForms 实际创建、事件生命周期、CATIA 属性兼容、完整
document/profile/lifecycle matrix 仍属于 G4-C。

## 13. 文档与状态治理

实施时同步：

- 更新 `catvba_refactor/macro_build/README.md`，删除“零 candidate/无 Kit”的陈旧状态；
- 更新 `Docs/发版.md` 的 G0/G1 当前值；
- 为本设计增加日期化实施计划；
- discovery 后只记录观察，不更新 G2 PASS；
- 新 G0/G1 Kit 生成后记录其唯一 handoff identity；
- G2/G3-C 只有在 sealed evidence、validator、gate evaluator 和独立复核全部满足后更新；
- 所有状态继续明确 `release_eligible=false`。

状态权威顺序保持：当前 `Docs/STATUS.md` > 本规格与上位规格 > runbook/README > 历史调查文档。

## 14. 错误处理与失效规则

- discovery 发现需要新 Reference/源码/manifest/audit 规则：回 A 环境，新 G0/G1；
- SP/HF、Windows、Reference、profile、Kit 或 CATVBA 变化：按上位规格重跑受影响 Gate；
- target hotfix：证据保留但候选 FAIL/BLOCKED，修复只能回 A 环境；
- 无安全 Reference fault injection：G5-I 继续 BLOCKED，不在本轮规避；
- audit 只能部分验证 resolved path：G2/G3 依赖外部 observation 交叉绑定并保留 partial 边界；
- 证据缺失或冲突：computed outcome 必须 `blocked`，不能猜测；
- 证据明确失败：computed outcome `fail`，不能用新 session 覆盖历史失败；
- seal 后修改：bundle invalid；更正使用 superseding session。

## 15. 实施顺序

设计获批后，实施计划按以下顺序拆分：

1. 证据领域模型和 JSON Schema；
2. target session 初始化与 canonical skeleton；
3. handoff 和 Reference contract；
4. evidence directory/ZIP verifier；
5. target plan/result 绑定；
6. returned audit Reference 增强；
7. gate evaluator；
8. deterministic evidence packer；
9. B28 operator runbook 与文档漂移修复；
10. 全量验证、双构建和新 G0/G1 handoff receipt。

每项采用 TDD、独立审阅和提交后全量验证；不得在本计划内执行 CATIA 或填写 target PASS。

## 16. 验收标准

- 操作员只能得到一个明确 handoff Kit；
- discovery 与正式 Gate 物理、语义分离；
- Reference allowlist 不再与最终宿主 Reference 集合混淆；
- 七类证据、operator records、returned CATVBA 和 SHA 清单形成完整闭环；
- 30 个不可变 case 与独立结果文件严格绑定；
- directory/ZIP evidence 均可结合相同 handoff Kit 离线验证；
- G2/G3-C 计算结果不能由单个可编辑 `status` 字段伪造；
- returned CATVBA 的模块、源码、FRX、Reference 和 artifact hash 可复核；
- 所有离线测试通过并产生新的确定性 G0/G1 Kit；
- 在真实 B28 evidence 回传前，G2-G7、target cases、Compile 和 release 状态不被提前升级。

## 17. 明确延后

- G4-C 三个最小 profile 的完整 context/lifecycle/state matrix；
- Fleet-SPA/Fleet-FTA source、Reference contract、positive/round-trip/isolation cases；
- P-ALL/P-PROD 补充测试；
- MISSING Reference 安全故障注入；
- 企业签名、ACL、安装根、宏库注册、普通用户试点和回滚；
- Product/Part/Drawing 第二回合审计；
- Optional、External Integration、DevTools、tag 和 Release。
