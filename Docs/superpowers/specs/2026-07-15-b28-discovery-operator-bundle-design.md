# CATVBA B28 Discovery 目标机操作包与续作恢复设计

> 状态：APPROVED — 用户已于 2026-07-15 书面确认
>
> 目标分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`
>
> 当前基线：`f20ad755d28f3b3f2ec15a781a0d23a6ebee1bd9`
>
> 批准 intake cutoff：`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`
>
> 目标宿主：CATIA V5-6R2018 / R28 / B28、VBA7、Win64、Python 3.12；禁止依赖 WSL
>
> 资格条件：`(AB3 OR HD2 OR MD2) AND SPA AND FTA`

## 1. 目的

本设计把现有 Core Build Kit 和 target-evidence harness 转化为一个能在原生 Windows B28 目标机使用的
Discovery 操作包，并使完整 Git clone 能在新开发环境恢复到可继续工作的状态。

交付必须同时满足：

1. 目标机取得完整代码、只读 Kit、操作脚本、采集器、模板和详细中文教程；
2. 目标机不需要 WSL，不使用 PowerShell、WSH、COM 或 GUI 自动化驱动 CATIA/VBE；
3. 目标机仅采集环境、许可证和五个 Reference 点，不 Compile、不运行 target case；
4. 目标机输出只是一份待验证的 raw capture，不自行宣称 Gate PASS；
5. 可信验证、Gate、独立审批和封存仍在 A 环境执行；
6. 代码、通用模板、可公开制品、生成过程和复现记录全部推送到
   `codex/dev-review-report`，不合并或回写 `main/dev`；
7. 新环境通过完整 Git clone、固定 cutoff bootstrap 和自动 doctor/verify 命令继续工作；
8. 任何真实主机、DSLS、客户或模型信息不得因“尽量推送”进入公开 Git 历史。

## 2. 已确认的阻断与设计依据

### 2.1 原生 Windows 不能运行现有可信容器层

现有 target-evidence container 和 publication 实现依赖 POSIX `dir_fd`、`O_DIRECTORY`、`O_NOFOLLOW`、
`renameat2(RENAME_NOREPLACE)` 和硬链接发布。Runbook 却要求操作员在原生 `cmd.exe` 调用初始化、验证、Gate、
审批和封存命令。Windows 不提供这些 POSIX 原语，因此现有命令链在目标机上 fail-closed，而不是可执行交付。

本轮不尝试在无 Windows 安全验证环境的前提下重写完整 Win32 文件系统信任后端。目标机仅运行一个不承担
Gate 信任的采集器；A 环境保留现有严格容器、验证和发布边界。

### 2.2 Fresh clone 缺少固定的本地 `dev` ref

Build Kit 当前解析裸 ref `dev`。标准 single-branch clone 只有
`origin/dev@688911522f88e2283231fb59232ea43edd3174a5`，没有本地 `refs/heads/dev`；而最新远端
`dev` 已改变 `Src` 和 Form bundle，不能静默作为已批准 cutoff。

续作 bootstrap 必须从已提交的 initial intake record 读取并验证 `abce8ffe...`，确认 Git object 存在后，
仅为历史批准基线创建本地 `refs/heads/dev`。它不得 fetch 后跟随浮动 `origin/dev`，不得将此动作描述为对
当前 upstream/fork 的重新认证。

### 2.3 历史 active artifact 只有摘要、没有字节

历史记录中的 `kit-feb504676720445f729c`、`handoff-6ed312ee18b254cb3c13`、revocation snapshot 和
session skeleton 保存在已消失的临时目录。Git 中只有 ID 和摘要，不能仅凭摘要安全地恢复原字节，也不能把
重新生成但未匹配原摘要的文件冒充历史 active artifact。

旧 Kit/handoff 保留为历史记录并标记 `unavailable`。本轮实现完成后，从新的 clean evidence commit 双构建
新的 Discovery Kit，使用真实当前 UTC 和新的 revocation snapshot 签发新 handoff；旧 handoff ID 在新 ledger
中明确记为 withdrawn。批准 cutoff 仍为 `abce8ffe...`，不接收 `688911...`。

### 2.4 Git Download ZIP 不能恢复受治理工作

Build Kit 需要 Git commit、tree、blob 和 ref。GitHub Download ZIP 没有 `.git`，只能阅读文档或取得已提交的
目标机操作包，不能作为开发续作输入。`RESUME.md` 必须明确要求完整 `git clone`。

## 3. 方案比较与选型

### 3.1 完整 Win32 可信后端

优点是目标机可运行现有全部命令；缺点是必须正确实现 Windows reparse-point 防护、handle-relative traversal、
原子 no-replace 发布、TOCTOU 防护和跨版本行为，并需要真实 Windows 安全测试。该工作明显超出本轮 Discovery
交付，不采用。

### 3.2 Windows 采集、A 环境验证封存

目标机使用 Python 3.12 标准库采集器生成 canonical raw capture；A 环境将其视为不可信输入，重新验证 Kit、
handoff、schema、摘要、状态和隐私边界，再计算 Gate、审批和封存。该方案保留现有安全实现，目标机无 WSL
依赖，故选为本轮方案。

### 3.3 模板加人工编辑

只提供 JSON 模板虽然改动最少，但操作员容易破坏 canonical JSON、stable ID、operator index 和摘要，且难以
证明 Discovery 未 Compile/运行。该方案只保留为紧急人工取证参考，不作为正式交付。

## 4. 信任边界与总体数据流

### 4.1 A 环境职责

A 环境是唯一能执行以下信任动作的环境：

- 固定 Git snapshot 和批准 cutoff；
- frozen dependency sync、全量 pytest、inventory/check；
- 两个独立输出根构建同一 Kit；
- 两目录、两 ZIP verifier 和字节一致性比较；
- handoff 与 revocation snapshot 签发；
- raw capture 的严格 schema/语义/容器验证；
- Discovery Gate receipt、独立 observation approval；
- sealed directory/ZIP 生成和复验；
- 对外生成仅含脱敏事实与摘要的 public attestation。

### 4.2 目标机职责

目标机只执行：

- 校验 Python 3.12、Windows、Kit ZIP、sidecar、bundle SHA 和 handoff 有效期；
- 人工确认 current ledger/revocation snapshot 的取得时间与状态；
- 人工观察 Windows、CATIA、VBA/VBE、DSLS 和许可证状态；
- 从空白 CATVBA 依次采集五个完整 Reference 集合；
- 严格按 `import-order/core.txt` 导入源码和原子 FRM/FRX bundle；
- 保存、完全关闭并重启 CATIA，采集 `post-restart`；
- 生成 canonical raw capture、operator index、SHA256SUMS 和 raw ZIP；
- 恢复批准的干净 VM snapshot。

目标机不执行 Gate、审批、sealed publication、Compile、target case、许可证修改、Reference 自动勾选、CATIA
自动化、Production 宏库注册或旧 CATVBA Save As。

### 4.3 数据流

```text
Git evidence commit
  -> A 环境双构建与四路验证
  -> 新 Discovery Kit + handoff + session skeleton
  -> Git 跟踪的 B28 operator bundle
  -> Windows B28 人工观察 + Python 采集器
  -> raw-discovery-capture.zip（不可信、未封存）
  -> A 环境验证与独立复核
  -> blocked/discovery-only receipt + observation approval
  -> sealed Discovery evidence
  -> 后续 Reference contract promotion（本轮之后）
```

## 5. 目标机采集器

### 5.1 交付形式

采集器源代码进入仓库，并构建为标准库 zipapp：

```text
target-discovery.pyz
run-discovery.cmd
```

`run-discovery.cmd` 先尝试 Python Launcher 的 `py -3.12`，若 launcher 不存在则尝试 `python`，但两条路径都必须
由采集器再次验证实际解释器为 CPython 3.12。等价的直接启动方式为：

```bat
py -3.12 target-discovery.pyz preflight --bundle-root "%~dp0"
```

若 `py -3.12` 不可用、Python 不是 CPython 3.12、平台不是 Windows、bundle 不完整或摘要不匹配，命令返回非零
并且不创建 capture。采集器不得安装包、修改注册表、调用 CATIA COM、运行宏或联网。

### 5.2 子命令

采集器提供有限状态机，而不是通用 JSON 编辑器：

```text
preflight
init-capture
record-environment
record-entitlements
import-reference-csv
add-operator-record
status
finalize-raw
```

- `preflight`：验证 bundle、Kit/handoff identity、目标机观测 UTC、expiry 和外部 active ledger freshness；
- `init-capture`：复制只读 skeleton 到新的本地 capture 根，不修改 bundle；
- `record-environment`：通过交互或受控 UTF-8 CSV/JSON 输入记录环境，不读取客户工程；
- `record-entitlements`：逐项记录 AB3、HD2、MD2、SPA、FTA 的 observed availability/checkout；
- `import-reference-csv`：将一个 observation point 的完整 Reference 集合规范化为 canonical JSON；
- `add-operator-record`：只接受已脱敏 UTF-8 文本或经二人复核的图像，并更新 index/hash；
- `status`：显示完成点、阻断和下一步，不推导 Gate；
- `finalize-raw`：要求五点齐全、session 完整，生成 raw manifest、SHA256SUMS 和 ZIP。

### 5.3 五个固定 Reference 点

采集器只接受并按固定顺序关闭以下点：

```text
blank-project
post-form-import
post-all-import
post-save
post-restart
```

每一点必须提交完整集合，不能只提交差异。稳定 Reference ID、GUID/version、MISSING、x64/x86、来源分类、
脱敏 root kind、basename、relative path 和 canonical path hash 均由采集器规范化。重复 stable ID 在不同点保留，
同一点冲突则 fail-closed。

### 5.4 Discovery 不变量

以下值由采集器固定，操作员没有修改接口：

```text
mode = discovery
package_id = core
profile_id = DISCOVERY
compile_status = not-run
all target cases = not-run
artifact_status = not-produced
release_eligible = false
```

如果输入文件声称 Compile、运行 target case、returned CATVBA 或 Gate eligible，采集器拒绝导入。A 环境 validator
必须再次独立执行同一语义检查。

### 5.5 Canonical 与文件安全

采集器只在新建的 session 根内写文件，拒绝：

- absolute path、`..`、drive/UNC path 和 portable collision；
- symlink、junction、reparse point、hard-link count 异常和非普通文件；
- 替换已关闭 observation point；
- 覆盖已存在 raw ZIP；
- 超过固定文件数、单文件大小和总大小预算；
- 非 UTF-8 文本、未知 JSON 字段和非 canonical 输出。

Windows 采集器不承担受攻击目录中的原子可信发布保证。因此其输出明确标记 `raw/untrusted`，并只能由 A 环境
重新读取、验证和封存。

## 6. B28 Operator Bundle

### 6.1 目录合同

可公开、可 Git 跟踪的目标机交付目录为：

```text
artifacts/b28-discovery/bundles/<bundle-id>/
├─ README_TARGET_B28.md
├─ QUICKSTART_B28.md
├─ SECURITY_AND_REDACTION.md
├─ TROUBLESHOOTING.md
├─ run-discovery.cmd
├─ target-discovery.pyz
├─ target-discovery.pyz.sha256
├─ kit-<kit-id>.zip
├─ kit-<kit-id>.zip.sha256
├─ handoff.json
├─ revocation-snapshot.json
├─ session-skeleton.zip
├─ source/
│  └─ target_collector/            # 与 pyz 同源的完整目标机采集器代码
├─ schemas/                         # 本次 bundle 使用的固定 schema 副本
├─ templates/
│  ├─ environment-input.json
│  ├─ entitlements-input.csv
│  ├─ references-input.csv
│  ├─ operator-record.txt
│  └─ redaction-review.md
├─ receipts/
│  ├─ build-reproducibility.json
│  ├─ verifier-summary.json
│  └─ target-collector-tests.json
├─ provenance.json
├─ SBOM.json
├─ THIRD_PARTY_NOTICES.md
└─ SHA256SUMS
```

所有教程、模板、脚本和源码同时存在于普通仓库路径；目标 bundle 中复制的是固定、带摘要的操作版本。

可变的当前状态不放入 immutable bundle。仓库另外维护：

```text
artifacts/b28-discovery/CURRENT.json
artifacts/b28-discovery/active-handoff-ledger.json
```

`CURRENT.json` 只指向一个 bundle ID、canonical `provenance.json` 的 SHA-256（字段名 `bundle_sha256`）和 active handoff ID；`active-handoff-ledger.json` 可在撤回或
刷新时独立更新。目标机命令必须显式传入这两个 sibling 文件，不能只信 bundle 内的 issuance snapshot。

### 6.2 Bundle 身份

`bundle-id` 是 canonical `provenance.json` 的 SHA-256 前缀。`provenance.json` 至少绑定：

- work repository、branch、evidence commit 和 tree；
- approved upstream/fork cutoff `abce8ffe...`；
- Kit ID、catalog/manifest/ZIP/sidecar digest；
- handoff ID、handoff digest、created/expires UTC；
- issuance revocation snapshot digest，以及 active ledger 的 schema/source identity；
- collector source commit、pyz digest、Python requirement；
- session skeleton digest；
-教程和模板的 digest；
- `compile_status=not-run`、`release_eligible=false`；
- 生成、测试和独立复核 record ID。

`provenance.json` 还保存 `bundle_content_sha256`：它是除 `provenance.json` 与 `SHA256SUMS` 外所有 regular bundle
成员的 canonical member-record digest。该值被 `bundle_sha256` 间接认证；选择器先验证 `CURRENT.json` 的
`bundle_sha256` 等于 provenance digest，再验证 `bundle_content_sha256` 和完整 `SHA256SUMS`，从而避免把同一字段
同时解释为 provenance 身份和完整 tree digest。

### 6.3 Handoff 与 freshness

handoff 使用签发环境的可信当前 UTC，不允许生产命令回填历史时间。默认有效期沿用七天策略。目标机 preflight
还要求外部 active ledger 的 `captured_at` 不早于操作开始前 24 小时；超过 freshness 窗口时停止并要求从仓库
取得更新后的 ledger。目标机本地时钟必须记录并由操作员见证；采集器能检查时间一致性，但不能独立证明操作员
没有篡改系统时钟，A 环境复核必须保留这一证据上限。

离线包只能证明取得 bundle 时的 ledger 状态，不能证明之后未撤回。教程必须明确这一证据上限。

## 7. 新环境续作层

### 7.1 唯一入口

仓库根新增 `RESUME.md`，内容固定覆盖：

- 只能完整 `git clone`，Download ZIP 仅可取得目标机包；
- 唯一工作分支和精确 branch HEAD；
- approved cutoff 与不得跟随 `origin/dev` 的原因；
- 当前 Gate、active bundle/handoff、expiry/revocation；
- Python/uv/平台要求；
- setup、doctor、verify-resume 三条入口命令；
- 唯一下一动作和全部停止条件；
- 目标机回传后的接力步骤。

### 7.2 机器可读状态

新增严格 schema 的 `resume/state.json`，至少记录：

```text
schema_version
repository / branch / evidence_commit / evidence_tree
delivery_parent_commit
approved_cutoff
intake_record_path / digest
python_requirement / uv_requirement / lock_digest
gate_statuses
active_bundle_path / bundle_digest
active_kit_id / kit_zip_digest
active_handoff_id / handoff_digest / expiry / revocation_status
last_full_test_count
last_reproducibility_receipt
release_eligible
next_action
```

`resume/state.json` 不尝试写入包含它自身的 delivery commit SHA，以避免自引用；`delivery_parent_commit` 固定为
生成 delivery record 前的 evidence commit，当前 checkout SHA 由 doctor 现场读取并与允许的后续非治理提交规则
比较。状态文件不得包含机器名、用户名、DSLS server、客户路径或现场证据。

### 7.3 Bootstrap

提供跨平台 Python 实现和薄 wrapper：

```text
scripts/bootstrap_resume.py
scripts/bootstrap-resume.sh
scripts/bootstrap-resume.cmd
```

bootstrap 必须：

1. 确认目录是非 shallow 的完整 Git clone；
2. 确认 remote/repository、工作分支和精确允许的起始 commit；
3. 校验 initial intake record 和 `abce8ffe...` object；
4. 仅在 ref 缺失时创建 `refs/heads/dev@abce8ffe...`；
5. 若本地 `dev` 指向其他 commit，则停止，不强制覆盖；
6. 校验 Python 3.12、锁文件摘要和 governed tree；
7. 执行 frozen sync；
8. 最终要求 tracked working tree clean。

### 7.4 Doctor 与 verify-resume

新增 `macro-menu-build doctor --state resume/state.json`，只读检查：

- Git clone、shallow 状态、remote、branch、HEAD/tree；
- local `dev`、approved cutoff、intake record；
- replace refs、governed status 和 pathspec 安全；
- Python/uv/lock；
- active bundle、Kit/handoff/ledger 的路径、摘要、expiry 和 revocation；
- `release_eligible=false` 时不存在可发布 CATVBA。

`scripts/verify_resume.py` 在新的临时输出根执行：

1. lock check；
2. 全量 pytest；
3. inventory/check；
4. 两次 Build Kit；
5. 两目录、两 ZIP verifier；
6. catalog、manifest、目录树、ZIP、sidecar 的字节一致性比较；
7. collector source/pyz parity 和 fixture smoke；
8. 生成 canonical reproducibility receipt。

## 8. Git 提交与制品持久化

### 8.1 两提交证据序列

为避免 Kit identity 自引用，生成顺序固定为：

1. **Evidence implementation commit**：提交 collector、schema、测试、教程、bootstrap、doctor、CI 和实现状态；
2. 从该 clean commit 双构建、四路验证并签发新的 Discovery handoff；
3. **Delivery record commit**：只在 `artifacts/`、`Docs/` 和 `resume/` 中加入 operator bundle、摘要和状态记录；
4. 复核第二个提交没有改变 `Src/resources/catvba_refactor/pyproject/uv.lock/.python-version` 的 evidence
   输入；否则废弃 Kit 并从新的 clean evidence commit 重建。

### 8.2 推送范围

以下内容必须直接推送到 `codex/dev-review-report`：

- 所有目标机采集器源码和构建脚本；
- `.pyz`、`.cmd`、通用模板、完整中文教程和故障排查；
- 可公开 Kit ZIP、sidecar、handoff、issuance snapshot、active ledger；
- session skeleton、SHA256SUMS、provenance 和可复算 verifier 摘要；
- specs、plans、过程记录、测试报告和续作状态；
- CI workflow 与运行结果链接/摘要。

不创建针对 unrelated `main` 的 PR，不合并、rebase 或 cherry-pick `main/dev`，不 force-push，不创建 tag 或
GitHub Release。若 GitHub 对单个文件或仓库大小施加限制，先保留源码、摘要和确定生成命令，再使用与提交绑定的
Actions artifact；不得静默丢弃产物。

### 8.3 不进入公开 Git 的现场数据

以下内容必须留在受控回传位置：

- 真实 environment、entitlements、references、state-diff 和 operator records；
- 主机/VM/snapshot/DSLS 标识；
- 客户、用户、完整路径、PN、模型、文档和参数名称；
- 原始截图、incident raw 和未完成脱敏复核的文件；
- returned CATVBA；
- sealed evidence 全包。

Git 中只提交人工复核后的 public attestation、Gate/approval/sealed digest、通用结论和状态迁移。摘要不能替代
私有完整证据，也不得用可枚举的敏感路径 hash 作为“安全公开”理由。

## 9. Schema 与状态约束

本轮新增或强化：

- `resume-state.schema.json`；
- `revocation-snapshot.schema.json`；
- `active-handoff-ledger.schema.json`；
- `operator-bundle-provenance.schema.json`；
- `raw-capture-manifest.schema.json`；
- collector input schemas；
- Discovery compile/test/artifact 的强制 `not-run/not-produced` 语义；
- AB3/HD2/MD2/SPA/FTA 逐项 observed availability/checkout；
- production handoff 的 trusted-now 与 ledger freshness；
- public attestation schema。

所有 JSON 均使用 strict object、拒绝未知字段、UTC `Z`、portable ASCII member path、canonical JSON 和确定性摘要。

## 10. 测试策略

实施必须使用 TDD。每项生产行为先有可观察失败的测试，再写最小实现。

### 10.1 单元与攻击面测试

- bootstrap 对 fresh clone、shallow clone、Download ZIP、ref 缺失/冲突和浮动 remote 的行为；
- doctor 对 replace refs、dirty governed tree、过期/撤回/stale ledger、hash mismatch 的诊断；
- collector 对 Python/platform、Kit/handoff、五点顺序、CSV 解析、canonical 输出的行为；
- Discovery compile/test/returned artifact 注入负测；
- symlink/junction/reparse/path traversal/portable collision/oversize/zip bomb 负测；
- operator record 类型、大小、索引和摘要；
- raw capture 不可被误识别为 sealed evidence；
- two-commit evidence boundary 和 bundle provenance；
- deterministic pyz、session skeleton 和 SHA256SUMS。

### 10.2 端到端测试

- 临时 Git fixture 恢复 `dev@abce8ffe...`；
- clean evidence commit 双构建与四路 verifier；
- fixture operator bundle → Windows collector raw capture → A 环境 validate/evaluate/approve/pack；
- Discovery 合法结论必须为 `blocked/discovery-only`；
- 目录和 ZIP sealed verifier parity；
- 新环境 `bootstrap -> doctor -> verify-resume`。

### 10.3 平台验证

GitHub Actions 至少包含：

- Linux Python 3.12：全量测试、双构建、四路 verifier、A 环境封存；
- Windows Python 3.12：bootstrap、doctor 的便携部分、collector、`.cmd` 和 `.pyz` smoke；
- artifact allowlist：只允许明确 bundle 路径，禁止 glob 发布 legacy CATVBA；
- 现有 `auto-release.yml` 必须禁用 tag 触发并归档为历史，不能通过修正 `base_ref` 条件使其重新发布 legacy
  CATVBA；
- `release_eligible=false` 时 release job 不存在或 fail-closed。

Actions 必须固定 action commit SHA，保留 JSON test/repro receipt。CI PASS 只能证明工具，不证明 CATIA、Reference、
许可证或目标机观察。

## 11. 目标机详细教程要求

教程必须可由未参与开发的操作员独立执行，并包含：

1. 文件完整性和版本确认；
2. Python 3.12 检查；
3. handoff expiry、ledger freshness 和停止条件；
4. 干净 VM snapshot、CATIA/VBE/Production 宏库检查；
5. 环境和五项许可证的只读观察；
6. 新建空白 CATVBA；
7. blank Reference 采集；
8. FRM/FRX 原子导入和 post-form 采集；
9. 全量 Core 导入、保存、关闭、重启和剩余三点采集；
10. 明确禁止 Compile、运行、SetLicense、Reference 自动勾选和旧工程 Save As；
11. operator record 脱敏与双人复核；
12. raw capture finalize、hash、只读介质回传和 VM 恢复；
13. 常见错误、恢复方式和不得覆盖失败历史；
14. 回传后 A 环境审核、formal 接力和证据边界。

教程同时提供完整版本、快速清单和故障排查版本，全部进入仓库和 operator bundle。

## 12. 错误处理与停止条件

出现任一情况立即停止，不生成可用 raw bundle：

- 非 Windows、非 Python 3.12、缺 `.git` 的续作环境；
- branch/commit/tree/cutoff、Kit/handoff/bundle/hash 任一不符；
- handoff 未生效、过期、withdrawn 或 ledger 超过 freshness 窗口；
- CATIA 不是 R28/B28、VBA7/Win64 不成立、SP/HF 无法辨认；
- AB3/HD2/MD2 全部不可用，或 SPA/FTA 任一无法观察；
- 检出 B30/x86/VBA6/Temp/user-profile/MISSING/未知 Reference；
- import order、FRM/FRX、source hash 不符；
- 操作员执行或证据声称 Compile/target case/returned CATVBA；
- 发现客户数据、未脱敏记录、路径泄漏或无法完成双人复核；
- capture 被链接、覆盖、超限、非 canonical 或摘要不闭合。

失败记录可作为私有 incident evidence 保留，但不得覆盖、删除或伪装成后续 PASS。

## 13. 验收标准

### 13.1 仓库与续作

- 完整 fresh clone 运行 bootstrap 后，本地 `dev` 精确为 `abce8ffe...`；
- bootstrap 不跟随 `origin/dev@688911...`，冲突时 fail-closed；
- doctor 对 Git、toolchain、Kit、handoff、ledger 和状态全部给出稳定 JSON；
- `uv lock --check`、完整 pytest、inventory/check、双构建和四路 verifier PASS；
- 两次 Kit directory/ZIP/sidecar 字节一致；
- tracked working tree clean，未留下 `*.egg-info` 或临时输出；
- `RESUME.md` 和 `resume/state.json` 指向实际可取得的 bundle。

### 13.2 目标机包

- 目标机仅需 Windows、Python 3.12、CATIA B28 和 operator bundle；
- `.cmd` 和 `.pyz` 在 Windows CI 通过；
- preflight 能拒绝篡改、过期、撤回和 stale ledger；
- 五点输入可由模板导入并生成 deterministic canonical raw capture；
- Compile、测试和 returned CATVBA 不能通过任何正常接口写入 Discovery；
- raw ZIP 可在 A 环境被读取并生成合法 `blocked/discovery-only` receipt；
- 目录、教程、模板、Kit、handoff、skeleton、摘要和过程记录全部已推送到指定分支。

### 13.3 证据边界

- G0/G1 只代表新的绑定 Kit；
- 目标机未真实执行前，G2-G7 维持 `BLOCKED`；
- Discovery 完成后仍不产生 Compile PASS、运行 PASS 或 release eligibility；
- 真实现场证据未进入公开 Git；
- `release_eligible=false`，不创建 tag、Release 或 Production CATVBA。

## 14. 后续接力

本轮结束时唯一下一动作是：在批准 B28 VM 上运行新的 operator bundle并回传 raw capture。A 环境验证、独立复核
和封存后，另立规格/计划实现 sealed Discovery → approved Reference contract promotion，并在相同
`abce8ffe...` cutoff 上生成 formal Kit/handoff，之后才进入 G2/G3-C。

最新 `dev@688911...` 的 intake、Core Form override 重放、StateGuard/Policy/HealthCheck 加固、G4-G7、Fleet、
Production 安装、签名和发布均不在本轮交付内，不得借目标机操作包隐式引入。
