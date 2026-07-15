# CATVBA B28 Core Discovery、G2 与 G3-C 现场操作手册

日期：2026-07-14
状态：已批准规格的人工执行手册；尚无真实 B28 执行结果

本手册只覆盖 `package_id=core`，目标为 CATIA R2018/VBA7 64（B28）。正式 session 的最低许可条件固定为：

```text
(AB3 OR HD2 OR MD2) AND SPA AND FTA
```

工作区没有 CATIA，只能编写、分析、测试和打包离线工具。本文中的 CATIA、VBE、DSLS、Compile、Reference
和 CATVBA 结果必须由目标机操作员与独立见证人在现场真实记录；不得把本地测试、synthetic fixture、空白草稿或
`not-run` 写成现场 PASS。完整合同见
[evidence harness 设计](../superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md)和
[实施计划](../superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md)。

## 0. 角色、目录和硬边界

至少使用三个不同角色：隔离构建操作员、隔离标准用户、独立复核者。独立复核者的 `review_record_id` 不得复用
capture 内任何 record、handoff prepared/review record、Reference contract approval record，也不得复用嵌套
G2 的 approval record。G3-C 外层必须创建新的 review ID。

在开始前为下列占位符填写本次值；命令中的尖括号不是字面字符：

| 占位符 | 含义 |
|---|---|
| `<KIT_ZIP>` | 当前唯一 active handoff 指定的 Kit ZIP |
| `<KIT_SHA256>` | handoff/sidecar 记录的 Kit ZIP SHA-256 |
| `<HANDOFF_JSON>` | detached handoff JSON |
| `<CAPTURE_DIR>` | `init-target-session` 返回的 session 目录 |
| `<GATE_RECEIPT>` | `evaluate-target-gate` 返回的 receipt 路径 |
| `<APPROVAL_JSON>` | `record-target-approval` 返回的 approval 路径 |
| `<EVIDENCE_ROOT>` | Kit 与 capture 之外的只写一次证据输出根 |
| `<SCHEMA_ROOT>` | 仓库的 `catvba_refactor/schemas` 目录 |
| `<PROFILE>` | `P-AB3`、`P-HD2` 或 `P-MD2`，与实际基线许可一致 |

所有命令在普通 `cmd.exe` 中运行，不依赖 PowerShell、WSH、COM、SendKeys 或 GUI 自动化。禁止脚本勾选
Reference、调用 `SetLicense`、修改 DSLS/Licensing Repository、写 Production 宏库或自动驱动 CATIA/VBE。
不得将一次性 CATVBA 注册到 Production macro library；不得 Save As 旧工程或客户工程。

证据只能含匿名 host/VM/snapshot ID、通用文档类型、稳定 Reference ID、GUID/version、脱敏路径分类与哈希。
禁止客户/用户名、机器全名、完整本地路径、PN、零件/产品/图纸名称、模型/参数名、截图中的标题栏和最近文件列表。
建议 operator record 命名：

```text
record-<session-short-id>-<category>-<ordinal>
operator-records/record-<session-short-id>-<category>-<ordinal>.txt
```

文本记录使用 ASCII 或 UTF-8、通用描述和 `<CATIA_INSTALL>`、`<EVIDENCE_ROOT>` 等占位符。截图必须先裁剪和
两人脱敏复核；原始含客户数据的截图不得进入 capture。每次人工更新 JSON 后，必须保持 schema 要求的 exact
字段、ASCII portable path、UTC、canonical JSON，并立即执行 capture validator；validator 非零时不得继续 Gate。

## 阶段 1：确认唯一 handoff、Kit、撤回状态和干净快照

本阶段在 A 环境签发 handoff，在目标机核对。A 环境必须从两个独立输出根中各取且只取一个同 ID 的 completed
Kit directory/ZIP/sidecar，不能由操作员在多个候选中手选。

Discovery handoff：

```bat
macro-menu-build create-target-handoff "<PRIMARY_BUILD_ROOT>" ^
  --compare-build-root "<SECOND_BUILD_ROOT>" --purpose discovery ^
  --revocation-snapshot "<REVOCATION_SNAPSHOT_JSON>" ^
  --prepared-record-id "<HANDOFF_PREPARED_RECORD_ID>" ^
  --review-record-id "<HANDOFF_REVIEW_RECORD_ID>" ^
  --created-at "<UTC>" --expires-at "<UTC>" ^
  --output-root "<DETACHED_HANDOFF_ROOT>" --format json
```

目标机先做只读验证：

```bat
macro-menu-build verify-kit "<KIT_ZIP>" --format json
certutil -hashfile "<KIT_ZIP>" SHA256
```

将 `certutil` 的 SHA-256 与 handoff、`.sha256` sidecar 精确比较。若现场政策禁止 `certutil`，使用获准的企业文件
完整性 UI 显示 SHA-256，并人工记录 UI 名称、文件字节数、SHA-256 和见证 record；Windows Explorer“属性”可用于
记录字节数和只读状态，但不能代替 SHA-256。若现场没有任何获准的 SHA-256 UI，结论只能 `blocked`，必须停止。

逐项确认：handoff ID 唯一且 active、未撤回、未过期；Kit ID/ZIP/sidecar/catalog/manifest/branch/commit/tree 与
handoff 一致；目标机时钟可解释；CATIA 完全关闭；已恢复批准的干净 VM snapshot；Production 宏库未注册本次
工程；输出根不在 Kit、handoff、capture 或 prerequisite 内。初始化命令会再次认证 Kit 与 handoff；任何不一致都
停止，不允许手改 handoff。

记录实际许可组合但不改变它。`<PROFILE>` 选择规则：实际基线为 AB3/HD2/MD2 时分别选择
`P-AB3`/`P-HD2`/`P-MD2`；SPA 与 FTA 还必须同时可用。仅“已安装”不等于本 session 已观察到 checkout。
缺少任一 SPA/FTA 或三个基线均不可用时，本轮正式 Gate 必须 `blocked`，不得调用 `SetLicense` 补齐。

## 阶段 2：初始化 discovery，记录环境和 entitlement

Discovery 使用一次性标准用户 session，不选正式 profile：

```bat
macro-menu-build init-target-session "<DISCOVERY_KIT_ZIP>" ^
  --mode discovery --package core --profile DISCOVERY ^
  --handoff "<DISCOVERY_HANDOFF_JSON>" ^
  --session-id "<DISCOVERY_SESSION_ID>" --created-at "<UTC>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<DISCOVERY_CAPTURE_ROOT>" ^
  --format json
```

把返回的 `session_dir` 作为 `<DISCOVERY_CAPTURE_DIR>`。通过 CATIA/VBE/DSLS 的人工 UI 记录：Windows edition/build/
patch、CATIA V5-6R2018/R28/B28 GA/SP/HF、DS VBA/VBE version、VBA7/Win64、匿名 CATIA environment ID、匿名 DSLS
client/server 与 connection mode、干净 snapshot ID、安全状态、污染扫描结果。许可页只读观察
AB3/HD2/MD2、SPA、FTA 的 availability/checkout；禁止修改 License Server、Licensing Repository 或 session
license。每个观察都绑定独立 operator record，`additional_required=["SPA","FTA"]` 只是要求，不能预填为已观察。

更新 capture 后执行：

```bat
macro-menu-build validate-target-evidence "<DISCOVERY_CAPTURE_DIR>" ^
  --kit "<DISCOVERY_KIT_ZIP>" --phase capture ^
  --schema-dir "<SCHEMA_ROOT>" --format json
```

只有 `ok=true` 才可进入下一阶段。结构有效不代表 Gate PASS。

## 阶段 3：新建一次性空白 CATVBA，采集 blank Reference

1. 从已批准的干净 snapshot 启动 CATIA，使用标准用户创建全新的空 CATVBA/VBA project。
2. 不从客户文档、旧 CATVBA、个人宏目录或 Production 宏库复制；不执行 Save As，不注册为 Production 宏库。
3. 在 VBE References UI 读取 blank-project 集合。逐项记录 GUID、major/minor、显示名/描述、MISSING、x64/x86、
   source classification、release provenance、脱敏 root kind/basename/relative path 和 canonical path hash。
4. 完整路径不得进入证据；只写 `<CATIA_INSTALL>` 等 root kind、允许的 basename/relative path 与 SHA-256。
5. 对 Reference UI 和路径属性生成两人脱敏 operator record；发现 `MISSING`、B30、x86、VBA6、Temp、user-profile
   或无法识别 DLL 时立即转阶段 8。

再次运行 discovery capture validator。此时仍不得 Compile、运行 target cases 或把 discovery 标为 eligible。

## 阶段 4：严格导入 Core，并采集五个 Reference 点

只读取 Kit 中的 `import-order/core.txt`，逐行人工导入，不自行排序、不跳项、不混入 Fleet/optional 模块：

1. 已完成 `blank-project` 采集。
2. 遇到 `.frm` 时，只通过 VBE 导入该 `.frm`；确认 Kit 中紧邻的同 basename `.frx` 作为原子 sidecar 被带入，
   不单独打开、转换或导入 `.frx`。完成全部 form pair 后采集 `post-form-import`。
3. 继续按清单导入全部 Core source，采集 `post-all-import`。
4. 保存一次性工程，采集 `post-save`。
5. 完全关闭 CATIA、VBE 和残留宿主进程，再重新启动并打开该一次性工程，采集 `post-restart`。

每个 point 都记录完整 Reference 集合及 operator record；重复 stable ID 保留为不同 observation，不能静默去重。
Discovery 中不执行 30 个 target cases，不把 compile/test status 写成 `passed`，不批准 Reference contract，不生成
Gate PASS。若导入顺序、FRM/FRX、文件 hash 或 Reference 集合有任何异常，转阶段 8。

## 阶段 5：回传并封存 discovery observation，恢复快照

将 `session.json` 标为完整并填写真实 ended UTC 后先验证，再计算 discovery Gate：

```bat
macro-menu-build validate-target-evidence "<DISCOVERY_CAPTURE_DIR>" ^
  --kit "<DISCOVERY_KIT_ZIP>" --phase capture ^
  --schema-dir "<SCHEMA_ROOT>" --format json

macro-menu-build evaluate-target-gate "<DISCOVERY_CAPTURE_DIR>" ^
  --gate DISCOVERY --kit "<DISCOVERY_KIT_ZIP>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<DISCOVERY_GATE_ROOT>" ^
  --format json
```

合法结果固定为 exit `7`、`computed_outcome=blocked`、`reason=discovery-only`，同时写出 receipt；这不是错误也不是
PASS。独立复核者只批准或拒绝“观察记录”，不能批准 Gate：

```bat
macro-menu-build record-target-approval "<DISCOVERY_CAPTURE_DIR>" ^
  --kit "<DISCOVERY_KIT_ZIP>" --gate-receipt "<DISCOVERY_GATE_RECEIPT>" ^
  --scope observation --status approved ^
  --reviewer-role "<INDEPENDENT_REVIEWER_ROLE>" ^
  --review-record-id "<NEW_DISCOVERY_REVIEW_RECORD_ID>" ^
  --approved-at "<UTC>" --schema-dir "<SCHEMA_ROOT>" ^
  --output-root "<DISCOVERY_APPROVAL_ROOT>" --format json

macro-menu-build pack-target-evidence "<DISCOVERY_CAPTURE_DIR>" ^
  --kit "<DISCOVERY_KIT_ZIP>" ^
  --gate-receipt "<DISCOVERY_GATE_RECEIPT>" ^
  --approval "<DISCOVERY_APPROVAL_JSON>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<DISCOVERY_SEALED_ROOT>" ^
  --format json
```

对返回的 sealed directory 和 ZIP 分别执行同一 Kit 绑定的 sealed 验证：

```bat
macro-menu-build validate-target-evidence "<DISCOVERY_SEALED_DIR>" ^
  --kit "<DISCOVERY_KIT_ZIP>" --phase sealed ^
  --schema-dir "<SCHEMA_ROOT>" --format json

macro-menu-build validate-target-evidence "<DISCOVERY_EVIDENCE_ZIP>" ^
  --kit "<DISCOVERY_KIT_ZIP>" --phase sealed ^
  --schema-dir "<SCHEMA_ROOT>" --format json
```

可选计算回传 ZIP：

```bat
certutil -hashfile "<DISCOVERY_EVIDENCE_ZIP>" SHA256
```

使用企业 SHA-256 UI 的人工替代规则同阶段 1。命令成功且 directory/ZIP 均 sealed-valid 后才视为一个完成 bundle。
随后完全关闭 CATIA，隔离并标记一次性 discovery CATVBA 为“不得复用”，恢复阶段 1 的干净 snapshot。即使回传了
CATVBA，它也只能作为 observation，不得用于正式 G2/G3-C。

## 阶段 6：A 环境只批准干净五点事实，重建 formal Kit/handoff

A 环境复核 sealed discovery bundle、receipt、observation approval 和五点集合。只在五点 identity/path policy/
transition 都干净、脱敏充分且 provenance 闭合时，修改 `catvba_refactor/config/packages.json` 中 Core 的结构化
Reference contract，把状态从 `discovery-required` 改为 `approved`；approval 必须绑定 discovery session、bundle
SHA、receipt SHA、observation approval SHA 和 contract body digest。不得把现场 CATVBA 热改反写为源码。

编辑、复核并提交 contract 后，从新 commit 在两个输出根重建不同 Kit；新 formal Kit ID/hash 不得等于 discovery
Kit。然后签发 formal handoff，并在同一 revocation snapshot 中撤回 discovery handoff：

```bat
macro-menu-build build-kit --repo-root "<REPO_ROOT>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<FORMAL_BUILD_ROOT_1>" ^
  --format json

macro-menu-build build-kit --repo-root "<REPO_ROOT>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<FORMAL_BUILD_ROOT_2>" ^
  --format json

macro-menu-build create-target-handoff "<FORMAL_BUILD_ROOT_1>" ^
  --compare-build-root "<FORMAL_BUILD_ROOT_2>" --purpose formal ^
  --supersedes-handoff "<DISCOVERY_HANDOFF_JSON>" ^
  --revocation-snapshot "<FORMAL_REVOCATION_SNAPSHOT_JSON>" ^
  --prepared-record-id "<FORMAL_HANDOFF_PREPARED_RECORD_ID>" ^
  --review-record-id "<FORMAL_HANDOFF_REVIEW_RECORD_ID>" ^
  --created-at "<UTC>" --expires-at "<UTC>" ^
  --output-root "<FORMAL_HANDOFF_ROOT>" --format json
```

目标机必须恢复干净 snapshot 后重新接收 formal Kit/handoff；不能在 discovery 工程上继续。

## 阶段 7：正式 G2，然后以已封存 G2 执行 G3-C

### 7.1 G2：只记录 blank environment/Reference

按实际可用的单一基线选择 `<PROFILE>`，同时真实观察 SPA、FTA；不得用 `P-ALL` 假装完成三个最小 profile
矩阵。初始化：

```bat
macro-menu-build init-target-session "<FORMAL_KIT_ZIP>" ^
  --mode g2 --package core --profile "<PROFILE>" ^
  --handoff "<FORMAL_HANDOFF_JSON>" ^
  --session-id "<G2_SESSION_ID>" --created-at "<UTC>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<G2_CAPTURE_ROOT>" ^
  --format json
```

在全新空白 CATVBA 中只重复阶段 2 环境/entitlement 和阶段 3 blank-project Reference 记录。G2 不导入、不 Compile、
不运行 target cases，后四个 Reference point 维持 `not-run`。完成 capture 后：

```bat
macro-menu-build validate-target-evidence "<G2_CAPTURE_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --phase capture ^
  --schema-dir "<SCHEMA_ROOT>" --format json

macro-menu-build evaluate-target-gate "<G2_CAPTURE_DIR>" ^
  --gate G2 --kit "<FORMAL_KIT_ZIP>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<G2_GATE_ROOT>" ^
  --format json
```

只有 `computed_outcome=eligible` 才能作为 G3-C prerequisite；仍需新的独立 Gate review：

```bat
macro-menu-build record-target-approval "<G2_CAPTURE_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --gate-receipt "<G2_GATE_RECEIPT>" ^
  --scope gate --status approved --reviewer-role "<INDEPENDENT_REVIEWER_ROLE>" ^
  --review-record-id "<NEW_G2_REVIEW_RECORD_ID>" --approved-at "<UTC>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<G2_APPROVAL_ROOT>" ^
  --format json

macro-menu-build pack-target-evidence "<G2_CAPTURE_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --gate-receipt "<G2_GATE_RECEIPT>" ^
  --approval "<G2_APPROVAL_JSON>" --schema-dir "<SCHEMA_ROOT>" ^
  --output-root "<G2_SEALED_ROOT>" --format json
```

用同一 formal Kit 验证 G2 sealed directory 和 ZIP；完全关闭 CATIA，不复用空白 G2 工程：

```bat
macro-menu-build validate-target-evidence "<G2_SEALED_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --phase sealed ^
  --schema-dir "<SCHEMA_ROOT>" --format json

macro-menu-build validate-target-evidence "<G2_SEALED_ZIP>" ^
  --kit "<FORMAL_KIT_ZIP>" --phase sealed ^
  --schema-dir "<SCHEMA_ROOT>" --format json
```

### 7.2 G3-C：从空白导入、Compile、重启和唯一 smoke

G3-C 必须使用同一 formal Kit/handoff、同一 `<PROFILE>`、相同匿名 host/VM/snapshot lineage，并把已验证的 eligible+
approved G2 ZIP 作为 prerequisite。`created-at` 不得早于 G2 `sealed_at`：

```bat
macro-menu-build init-target-session "<FORMAL_KIT_ZIP>" ^
  --mode g3-c --package core --profile "<PROFILE>" ^
  --handoff "<FORMAL_HANDOFF_JSON>" ^
  --prerequisite-evidence "<G2_SEALED_ZIP>" ^
  --session-id "<G3_SESSION_ID>" --created-at "<UTC>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<G3_CAPTURE_ROOT>" ^
  --format json
```

从新的空白 Core CATVBA 开始，禁止 Save As，严格执行阶段 4 的 import order/FRM+FRX 原子步骤。按顺序记录
post-form/post-all Reference；执行 post-import Compile，保存并记录 post-save，完全关闭 CATIA/VBE/残留宿主，
重开后记录 post-restart 并再次 Compile。只在 post-restart Compile 通过后运行唯一 smoke：

```text
context.core.healthcheck.none
```

不得运行其余 29 个 case，它们保持 `not-run`。记录 smoke result code、前后状态、error/cancel/restart 恢复状态；
只回传恰好一个 `returned-catvba/core.catvba`，设为只读，不注册 Production。可选计算制品 hash：

```bat
certutil -hashfile "<RETURNED_CORE_CATVBA>" SHA256
```

若用企业 UI 代替，必须记录真实 SHA-256；仅文件大小不足以继续。然后验证、计算 Gate：

```bat
macro-menu-build validate-target-evidence "<G3_CAPTURE_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --phase capture ^
  --schema-dir "<SCHEMA_ROOT>" --format json

macro-menu-build evaluate-target-gate "<G3_CAPTURE_DIR>" ^
  --gate G3-C --kit "<FORMAL_KIT_ZIP>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<G3_GATE_ROOT>" ^
  --format json
```

`eligible` 仍不代表 release；`release_eligible` 必须保持 `false`，G4-G7 不自动前进。独立复核后封包，外层 review
ID 必须与嵌套 G2 不同：

```bat
macro-menu-build record-target-approval "<G3_CAPTURE_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --gate-receipt "<G3_GATE_RECEIPT>" ^
  --scope gate --status approved --reviewer-role "<INDEPENDENT_REVIEWER_ROLE>" ^
  --review-record-id "<NEW_OUTER_G3_REVIEW_RECORD_ID>" --approved-at "<UTC>" ^
  --schema-dir "<SCHEMA_ROOT>" --output-root "<G3_APPROVAL_ROOT>" ^
  --format json

macro-menu-build pack-target-evidence "<G3_CAPTURE_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --gate-receipt "<G3_GATE_RECEIPT>" ^
  --approval "<G3_APPROVAL_JSON>" --schema-dir "<SCHEMA_ROOT>" ^
  --output-root "<G3_SEALED_ROOT>" --format json
```

对 G3 sealed directory/ZIP 分别验证：

```bat
macro-menu-build validate-target-evidence "<G3_SEALED_DIR>" ^
  --kit "<FORMAL_KIT_ZIP>" --phase sealed ^
  --schema-dir "<SCHEMA_ROOT>" --format json

macro-menu-build validate-target-evidence "<G3_SEALED_ZIP>" ^
  --kit "<FORMAL_KIT_ZIP>" --phase sealed ^
  --schema-dir "<SCHEMA_ROOT>" --format json
```

A 环境再对 returned CATVBA 执行只读 audit。audit 的 Reference path 若只能部分恢复，必须与
`references.json` 的 GUID/version/hash 交叉绑定，并保留 `partial|unavailable`，不能伪称 verified。

```bat
macro-menu-build audit-catvba "<RETURNED_CORE_CATVBA>" ^
  --expect "<FORMAL_KIT_DIR>\kit-manifest.json" --package core ^
  --format json
```

## 阶段 8：停止、隔离、封存历史和恢复

下列任一情况立即停止后续 CATIA 操作：handoff/Kit/hash/expiry/revocation 不符；许可不足；出现 B30/x86/VBA6/
Temp/user/MISSING/unknown Reference；客户数据泄露；导入顺序或 FRM/FRX 异常；Compile/test 失败；CATVBA 或证据
hash 不闭合；Production 宏库被触及；机器/快照/环境漂移。

停止顺序：

1. 不修补、不删除、不覆盖已有 capture；停止导入/Compile/测试并完全关闭 CATIA/VBE。
2. 将输出移动到只读隔离区之前，先保留当次目录身份和 hash；任何含客户数据的 raw record 单独隔离，禁止进入
   可分享 evidence。记录失败阶段、模块、通用错误摘要，不写客户名/路径/PN/模型内容。
3. 如果 capture 仍可通过结构验证，把真实 ended UTC、`failed|blocked|not-run` 状态和 operator records 写全，运行
   对应 Gate。合法 `fail|blocked` receipt 的 exit 为 `7`，可由独立复核者以 `approved` 表示“批准保存该结论”或以
   `rejected` 表示拒绝该复核；两者都不是 PASS。随后可用正常 approval/packer 命令封存历史。
4. 如果 schema、identity、hash 或 canonical JSON 已损坏，Gate 不会生成 receipt；保留隔离 raw incident，不能伪造
   approval/封包。回 A 环境修复工具/contract/manifest 后创建新 Kit、handoff 和 superseding session。
5. 验证已封存历史（若有），恢复批准的干净 VM snapshot；一次性 CATVBA 和热改不得复用或回写源码。

任何恢复都不能覆盖失败历史。SP/HF、Windows、Reference、profile、Kit、CATVBA 或源码变化时，按新输入重新执行
受影响 Gate。

## 许可风险、隔离与无额外许可替代

本轮只验证 Core。SPA、FTA 是现场资格要求，不表示 Fleet-SPA/Fleet-FTA 已实现或获准导入。

| 超出范围的模块/动作 | 许可风险 | 隔离方式 | 无额外许可的替代 |
|---|---|---|---|
| Fleet-SPA source、空间分析/测量 API | 可能依赖 SPA 以外的工作台或配置；本仓库本轮未实现 | 不进入 `import-order/core.txt`；独立 package、CATVBA、Gate 和 handoff | 只运行 Core `HealthCheck`，记录“能力不可验证/blocked”，不模拟 SPA 结果 |
| Fleet-FTA source、FTA annotation/tolerance API | 可能依赖 FTA/特定 authoring 配置；本仓库本轮未实现 | 不导入 Core CATVBA；未来独立 package 和 failure-isolation session | 只做 Core read-only 健康检查；人工 UI 观察许可，不创建/修改 FTA 数据 |
| DMU、Kinematics、Drafting authoring、Knowledgeware 等未列模块 | 不在 AB3/HD2/MD2+SPA+FTA 基线保证内 | 一律不导入、不调用；单独列许可证和 API 风险后再立项 | 使用通用文档类型/只读 metadata 或标记 `not-run|blocked`，不得声称等价 |
| `SetLicense`、Licensing Repository 修改、脚本 Reference 选择 | 会改变现场授权/环境，破坏证据可比性 | 本手册全面禁止；发现即停止并恢复 snapshot | 由管理员在 session 外准备已批准环境；session 内只读观察 |

“替代”只保留 Core 安全边界，不证明扩展功能。缺少额外许可时，不允许用 UI 点击、错误吞掉或 mock 数据制造
positive result。

## 最终交接清单

- Kit/handoff/sidecar/revocation/snapshot 身份已记录且互相匹配；
- discovery、G2、G3-C 各自使用不同 session ID；所有 detached review ID 独立；
- 目标许可真实满足 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`，无 session 内许可修改；
- discovery 只有 `blocked/discovery-only`，未运行 target cases、未声称 PASS；
- formal Kit 为 A 环境批准 contract 后的新 Kit；formal handoff 已使 discovery handoff 撤回，并显式 supersede 它；
- G2 sealed evidence 为 eligible+approved 后才嵌入 G3-C；
- G3-C 只运行 `context.core.healthcheck.none`，其余 case 保持 `not-run`；
- 每个 sealed directory/ZIP 都以同一 Kit 执行 `--phase sealed` 验证；
- `release_eligible=false`，G4-G7 与 Production 安装仍未完成；
- 已恢复干净 snapshot，一次性 CATVBA 未复用，未触及 Production 宏库；
- 回传包不含客户/用户名/机器全名/完整路径/PN/模型/参数数据。
