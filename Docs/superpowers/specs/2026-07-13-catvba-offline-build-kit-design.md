# CATVBA 离线 Build Kit 设计

> 状态：APPROVED — 用户已于 2026-07-13 书面确认
>
> 上位规格：[CATVBA R2018 恢复总架构设计](2026-07-13-catvba-r2018-recovery-design.md)
>
> 执行环境：无 CATIA 的 A 环境

## 1. 目标与非目标

目标是在没有 CATIA 的工作区，对固定 Git 输入完成清点、解析、静态政策校验、源码生成、不可变 staging、
确定性归档和回传 CATVBA 只读审计，生成可交给 B28 的 Build Kit。

本规格不生成可信 CATVBA，不执行 VBA，不证明 References/API/许可证或 UI 行为，也不实现业务宏。

## 2. Python 项目与目录

根文件是唯一 Python 真源：

```text
pyproject.toml
uv.lock
.python-version
catvba_refactor/
  macro_build/
  tests/
  config/
  schemas/
  vba/
  resources/
  build/        # generated, ignored
  dist/         # generated, ignored
```

不得创建 `catvba_refactor/pyproject.toml` 或第二个 `uv.lock`。未来 CLI 通过根项目注册
`macro-menu-build`；测试路径指向 `catvba_refactor/tests/`。

现有 `olefile/oletools/pcodedmp` 用于只读审计，`pytest` 属于开发/测试依赖。首版 manifest 推荐 JSON，
并使用 JSON Schema；若采用该方案，实施计划必须把 `jsonschema` 加入根项目并更新唯一 lock。若改回 YAML，
还必须选择安全 YAML 解析器并写入同一依赖真源，不能依赖环境偶然安装。

## 3. 输入模型

正式 `build-kit` 只支持 candidate `InputSnapshot`：

```text
upstream_repository  verysolecd/Macro_menu
upstream_ref         dev
upstream_commit      exact Git OID
fork_dev_commit      exact Git OID
work_repository      doylenehemiah6893-afk/Macro_menu
work_branch          codex/dev-review-report（仅用于报告）
work_commit/tree     exact Git OID
manifest_digest
tool_version
```

- candidate 只读固定、已提交 Git blobs，并要求 fork dev 与所声明 upstream cutoff 一致；
- `inventory/check --worktree` 可用于开发诊断，但不生成正式 snapshot、Kit 或可升级 receipt；
- `build-kit` 拒绝受管路径存在 modified/deleted/untracked 内容；
- 首个 Build Kit 不以复杂 accepted-sync-record 链作为前置条件；intake 证据由独立规格逐步引入。

## 4. 配置与 schema

规划的 JSON 文件：

```text
config/project.json
config/components.json
config/packages.json
config/tools.json
schemas/*.schema.json
```

所有配置必须：

- UTF-8、对象 key 语义明确；规范摘要使用排序稳定的 canonical JSON；
- 拒绝未知字段、重复 source/tool/package ID 和相互矛盾状态；
- 不含密钥、绝对机器路径、客户数据或运行时许可证修改；
- `components.json` 同时表达 upstream/new/override/shared/quarantine；
- package policy/capability 归入 `packages.json`，稳定工具目录归入 `tools.json`；
- Core 最低禁令由版本化代码强制，配置只能收紧，不能放宽；
- 许可证结论只能是 candidate/verified/blocked 等证据状态，manifest 不能自报目标机 PASS。

## 5. 源码解析

### 5.1 组件类型

```text
standard_module  .bas
class_module     .cls
user_form        .frm + .frx
```

FRM/FRX 是不可拆分 bundle。override 必须同时绑定 upstream/local 每个成员的 path、Git OID、原始
SHA-256、role、组件类型和 `VB_Name`；resolver 只能整体选择一侧，禁止组合本地 FRM 与上游 FRX。

### 5.2 编码

对 `.bas/.cls/.frm` 按原始 bytes 分类：

1. UTF-8 BOM；
2. 纯 ASCII（UTF-8/CP936 逻辑文本相同）；
3. 仅严格 UTF-8；
4. 仅严格 CP936；
5. UTF-8 与 CP936 均成功但文本不同：`ENC_AMBIGUOUS`，必须由显式清单裁决；
6. 均失败：阻断。

裁决后的 `encoding_decision` 是组件身份的一部分，必须进入 canonical catalog、source-resolution receipt
和 member hash receipt，并参与 kit ID。policy、Kit verify 和回传审计只允许使用该单一 strict decoder；
不得在后续阶段重新猜测或枚举另一种解释。

未覆盖 upstream 和完整 override 原始 bytes 复制到 staging；只有生成模块按待 B28 验证的 CP936/CRLF
输出。生成文本含 CP936 不可编码字符时失败，不做静默替换。

### 5.3 身份与路径

- portable path key 统一 `/`，检查 UTF-8、NFC/NFKC、casefold、尾点/空格、Windows 保留名、file/dir 冲突和穿越；
- `VB_Name`、输出文件名、生成保留名在目标 CATVBA 内唯一；
- override 继承 upstream 组件身份，改名按退役旧组件 + new 组件；
- 同名阴影、fuzzy patch、rename 猜测和 base 漂移后的静默回退全部禁止。

## 6. 流水线

```text
InputSnapshot
  -> UpstreamInventory + OverlayInventory
  -> ResolvedSourceSet
  -> GeneratedSourceSet
  -> ResolvedCatalog
  -> BuildKit
```

生成模块在进入 catalog 前必须完成同样的路径、组件名、包和政策检查，不得在 staging 临时插入。

建议公共接口保持小而明确：

```python
freeze_snapshot(...) -> InputSnapshot
load_and_validate_config(...) -> ManifestSet
scan_inputs(...) -> Inventory
resolve_sources(...) -> ResolvedSourceSet
generate_sources(...) -> GeneratedSourceSet
assemble_catalog(...) -> ResolvedCatalog
validate_catalog(...) -> ValidationReport
stage_build_kit(...) -> BuildKitReceipt
verify_build_kit(...) -> VerificationReport
audit_catvba(path, expected_manifest=None, *, package_id=None) -> AuditReport
```

可预期配置/源码问题进入排序稳定的报告；I/O、锁和内部不变量失败才抛异常。

## 7. 静态政策

首版至少检查：

- `VB_Name`、组件类型、FRM/FRX、入口和菜单标签；
- `Option Explicit`、Windows Declare、危险 API 和已知公共 UDT/Class 接口风险；
- Core 中的 Office、VBIDE/MSAPC、Shell/PowerShell/WSH、网络、许可证修改、SPA/FTA/Optional 类型；
- package/source/tool 的唯一归属；
- MSForms Name 以字母开头、仅字母数字下划线、最长 40、目标 Form 内唯一；
- 绝对路径、当前时间、用户名和客户标识不得进入可复现摘要。

这些检查是结构/政策证据，不是 VBA 编译器；报告必须使用 `compile_status=not-run`。

## 8. CLI

```text
macro-menu-build inventory [--worktree]
macro-menu-build check [--worktree]
macro-menu-build build-kit
macro-menu-build verify-kit <kit>
macro-menu-build audit-catvba <returned.catvba> --expect <kit-manifest.json> [--package <package-id>]
```

`inventory/check --worktree` 只输出诊断；`build-kit` 必须重新从 clean committed Git blobs 完整执行检查。
CLI 只允许覆盖 repo/ref、输出路径和报告格式，不允许覆盖 cutoff、binding、package 或安全政策。
`--package` 是从已验证 Kit 选择独立目标包，不是覆盖包归属：仅一个非空包时可省略；多个非空包时
必须显式给出。未知包、空包以及没有 `--expect` 时使用 `--package` 均失败关闭。

```text
0 success
2 CLI/config/schema failure
3 source/encoding/resolver/policy failure
4 Git object/I/O/lock/staging failure
5 Kit/CATVBA verification failure
```

## 9. Build Kit 与确定性

Kit 至少包含：

```text
kit-manifest.json
catalog.json
receipts/source-resolution.json
receipts/hashes.json
packages/<package-id>/source/...
import-order/<package-id>.txt
references/<package-id>.json
target-test-plan/
evidence-templates/
SHA256SUMS
KIT_COMPLETE
```

目录先写同卷临时路径，全量自校验后写完成标记并原子 rename；已存在同 kit ID 且摘要相同则 no-op，
不同则失败，禁止覆盖。

确定性 ZIP 使用 Python `zipfile.ZIP_STORED`，固定排序后的 NFC/POSIX entry name、`1980-01-01 00:00:00`
时间戳、`create_system=3`、`0644` 权限，且不写目录项、extra field 或 comment。ZIP SHA-256 写在归档外部，
避免自哈希循环。相同固定输入需两次产生相同 catalog、kit ID、目录清单和 ZIP SHA-256。

```json
{
  "target_build_required": true,
  "catvba_artifacts": [],
  "compile_status": "not-run",
  "release_eligible": false
}
```

## 10. CATVBA 只读审计

`olefile/oletools/pcodedmp` 只在低权限、无网络、只读副本中运行。审计比较模块、规范化源码、FRX、
References、签名相关流和哈希，并拒绝没有源码模块绑定的孤立 Form storage。expected Kit 必须通过同一
no-follow 根目录快照上的完整 Kit 验证（catalog、receipts、所有包、hashes、`SHA256SUMS`、
`KIT_COMPLETE` 和 extra/missing entry）；随后只提取所选 package 的 modules/FRX/References/hashes。
Core/Fleet 的同名共享运行时按包分别允许，但单个目标 CATVBA 不得聚合多个包。第三方工具对
p-code/cache 的解释只能作为诊断信号，不能替代 B28 Compile、保存、重启和复测。

源码比较必须区分两个方向：Kit 内 staged `.cls/.frm` 必须保留规范导出头，并拒绝
`VB_Base`、`VB_TemplateDerived`、`VB_Customizable` 等只由提取器补出的元数据；实际 CFB 提取结果
不得带导出头，只能剥离格式和值均通过严格校验的上述提取元数据。`VB_PredeclaredId` 等行为属性始终
参与语义哈希。输入 CATVBA 与 expected Kit 仅接受 no-follow regular file/目录，并分别实施文件大小、
总字节、entry 数和目录深度上限；达到上限即失败关闭，不能先无界读入内存。

## 11. 测试

严格 TDD，覆盖：

- candidate snapshot、dirty governed path 拒绝和 worktree 诊断不得产出 Kit；
- upstream/fork cutoff 不一致；
- JSON Schema、未知字段、重复/遗漏 ID；
- UTF-8/CP936/ASCII/歧义/非法字节；
- override base 漂移、rename/delete/case-only rename；
- Windows portable path 与 `VB_Name` 冲突；
- FRM/FRX 原子 bundle 和 `OleObjectBlob`；
- Core 禁止引用/API 和 SPA/FTA 物理隔离；
- 生成顺序、字符串转义、CP936/CRLF；
- staging 故障、并发锁、no-op、路径穿越；
- 确定性目录/ZIP；
- 正常/损坏 CFB、孤立 Form storage、FRX 外层封装污染与回传不匹配；
- 单/多/空 package 选择、跨包同名、非选中包篡改和 catalog-bound 编码裁决；
- staged/实际提取源码的单向归一化、行为属性篡改和 bounded/FIFO/TOCTOU 输入；
- CLI 退出码和 text/JSON 报告一致。

VBA 行为测试在本地只能保持 `NOT_RUN/BLOCKED`，不能以 golden 文本替代。

## 12. 本地验收

- 根 Python 项目是唯一环境真源，`uv sync --frozen` 所需 lock 一致；
- candidate 只读固定 Git blobs，dirty/untracked governed input 阻断正式 Kit；
- 所有参与 Kit 的组件具有唯一来源、身份、包和 capability 状态；
- 任何编码、路径、FRM/FRX、binding、package 或禁止 API 问题 fail-closed；
- 两次固定输入构建得到相同结果；
- Kit 不含旧 CATVBA、许可证、客户数据、密钥或绝对路径；
- `pytest` 全部通过并保存命令与输出；
- 结果明确保持 `compile_status=not-run`、`release_eligible=false`。
