# 项目结构与上游同步规划

> **Status:** APPROVED — Overlay、唯一命名空间与 `Src/` 上游所有权；DRAFT — manifest schema、intake 记录和自动化细节
>
> **Approved direction:** 2026-07-13
>
> **Scope:** 仅规划本地 `codex/*` 分支；不修改远端，不立即创建目录或迁移源码。本文不授权绕过 [STATUS.md](STATUS.md) 的唯一下一动作进入实现。

## 1. 结论与当前证据

所有新的产品源码、替代源码、配置、schema、工具、测试和派生输出统一收进
`catvba_refactor/`。`Src/` 与 `resources/` 定义为 `origin/dev` 的上游镜像区，重构分支不得直接
修改；只有审定的 upstream intake 可以改变它们。

2026-07-13 实时核对：

- `origin/dev = abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；
- 当前 HEAD 的 `Src/` 相对该 cutoff 差异为 0；
- 当前 HEAD 的 `resources/` 相对该 cutoff 差异为 0；
- `origin/dev` 当前不存在 `catvba_refactor/`。

因此现在建立所有权边界不会覆盖已有本地源码修改。未来 upstream 若创建同名保留命名空间，intake
必须 fail-closed，不能自动合并或改名躲避。

## 2. 方案取舍

| 方案 | 结论 | 原因 |
|---|---|---|
| 在根目录新增 `config/`、`schemas/`、`tests/` 等 | 拒绝 | 未来 upstream 可能创建同名路径，不能满足唯一本地命名空间目标 |
| 用同名相对路径自动遮蔽 `Src/` | 拒绝 | 上游变化会被静默隐藏，无法证明最终组件来源 |
| 保存 Git patch 并 fuzzy apply | 拒绝作为真源 | rename、编码、FRM/FRX 和上下文漂移会产生不确定结果 |
| 显式绑定的整组件 Overlay | 采用 | 每个替代都绑定上游路径、Git blob、SHA-256 和组件身份；漂移即阻断 |

## 3. 规划目录

```text
Macro_menu/
├─ Src/                              # upstream-owned Git tree mirror；candidate bytes 从 cutoff blob 读取
├─ resources/                        # upstream-owned；本地新资源不得写入
├─ catvba_refactor/                  # 唯一本地实现命名空间，当前尚不存在
│  ├─ README.md                      # 命名、所有权和禁止写入规则
│  ├─ pyproject.toml
│  ├─ uv.lock
│  ├─ vba/
│  │  ├─ new/<source-id>/            # 本地新增整组件；包归属不编码在路径中
│  │  ├─ overrides/<source-id>/      # 绑定 upstream 基线的整组件替代
│  │  └─ shared_contracts/<source-id>/
│  ├─ resources/                     # 本地新增的受管资源
│  ├─ config/
│  │  ├─ project.yml
│  │  ├─ source_overlays.yml
│  │  ├─ packages.yml
│  │  ├─ capabilities.yml
│  │  ├─ tools.yml
│  │  ├─ policies.yml
│  │  └─ legacy.yml
│  ├─ schemas/
│  ├─ macro_build/                   # 离线 inventory/resolver/generator/audit CLI
│  ├─ tests/
│  │  └─ fixtures/
│  ├─ build/                         # 派生物；Git ignore
│  │  ├─ resolved/<plan-id>/
│  │  └─ kits/<kit-id>/
│  └─ dist/                          # 派生物；Git ignore
│     └─ build-kit/<kit-id>.zip
├─ Docs/                             # 既有治理例外；规范、状态、计划和证据
│  └─ evidence/upstream-intake/      # 规划：post-merge sync records；不属于产品输入
├─ README.md                         # 既有治理例外
├─ .gitignore .gitattributes         # 既有仓库治理例外；须单独审查
├─ DrawFunc/ ref_project/ artifacts/ # reference/history；release=false
├─ CATIA_V5_SimpleMacroMenu.catvba  # legacy evidence only
├─ CAT_menu.catvba                  # legacy evidence only
├─ LicenseReset.catvbs              # quarantine
└─ user_data.json                   # devtool-local legacy config
```

路径按稳定 `source_id` 组织，不按 Core/Optional 包名组织。三 profile 验证可能改变包归属，但不应因此
移动源码并制造无意义 Git rename。

## 4. 所有权与写入边界

| 区域 | 所有者 | 允许写入 | 禁止行为 |
|---|---|---|---|
| `Src/`、`resources/` | `origin/dev` | 审定 intake merge | 本地修复、格式化、转码、生成代码、诊断试改 |
| `catvba_refactor/vba/new/` | local overlay | 本地新增整组件 | 与现有 `VB_Name` 隐式重名 |
| `catvba_refactor/vba/overrides/` | local overlay | 显式绑定的整组件替代 | 同名路径阴影、缺 base hash、自动跟随 rename |
| `catvba_refactor/vba/shared_contracts/` | local overlay | 经清单批准的小型协议组件 | 业务实现或 Optional 类型泄漏 |
| namespaced `config/`、`schemas/` | local overlay | 机器可验证的策略和契约 | 密钥、绝对机器路径、客户数据 |
| namespaced `macro_build/`、`tests/` | local overlay | 离线只读工具和测试 | 假装执行 CATIA Compile |
| namespaced `build/`、`dist/` | generated | 全新、可再生输出 | 人工维护真源、覆盖不同摘要目录 |
| 根 `README.md`、`Docs/`、Git 元数据 | governance exception | 小步审查的治理变更 | 混入业务实现或生成物 |

安全修复即使紧急，只要尚未进入 `origin/dev`，也必须先作为 override。若要向上游贡献补丁，应在
独立贡献分支准备；该分支不得作为 Build Kit 输入。补丁进入 `origin/dev` 后，再通过 intake 更新
`Src/` 并显式退役 override。

## 5. 真源与解析模型

正式构建真源不是单独的 `Src/`，而是：

```text
origin/dev@cutoff 的 Git blobs
+ catvba_refactor/ 中已提交的本地整组件和 manifests
+ schema/generator/tool versions
= 可复算的输入真源
```

`overlay_tree_oid` 指 `catvba_refactor/` 中已跟踪、已提交输入的 Git tree；被忽略的 `build/`、`dist/`
永不参与 overlay tree，另外按派生制品计算哈希。

每次 inventory/validate/plan/build 都必须从不可变 `InputSnapshot` 开始。snapshot 固定
`mode`、upstream commit/tree、overlay identity、manifest digest，以及 accepted sync record chain head
`R` 的 path/blob OID/raw SHA-256/evidence commit；`snapshot_id` 必须覆盖这些字段，后续阶段不得切换
字节来源或 lineage。
`candidate` 只接受 committed Git blobs 与 `overlay_tree_oid`；`dev` 可以把 allowlist 内的 tracked、
modified、deleted 和 untracked overlay 文件纳入排序固定的 synthetic tree digest，但该摘要不是 Git OID，
且对应计划永远不能升级或复用为 candidate。

派生目录满足：

```text
ResolvedCatalog =
  未被替代的 upstream components
  + 通过精确绑定的 overrides
  + 无身份冲突的 new components
  + 获批 shared contracts
  + build-time generated modules
```

任一 binding 失效时不得生成 `ResolvedCatalog`，也不得退回使用新版 upstream 文件继续构建。
生成阶段必须显式位于 `ResolvedSourceSet -> GeneratedSourceSet -> ResolvedCatalog` 之间；生成模块完成
保留名/路径/`VB_Name` 碰撞检查并进入 catalog 和 kit 摘要后，才能产生 BuildPlan。

### 5.1 整组件绑定

`source_overlays.yml` 的精确 schema 仍为 DRAFT，但每个条目至少要表达：

```yaml
source_id: menu.static-entry
mode: override                  # override | new | shared_contract
component_type: standard_module
expected_vb_name: A00_Menu
members:
  - role: source
    local_path: catvba_refactor/vba/overrides/menu.static-entry/A00_Menu.bas
    local_sha256: <sha256>
    upstream_path: Src/A00_Menu.bas # 仅 override 必须
    upstream_blob_oid: <git-oid>    # 仅 override 必须
    upstream_sha256: <sha256>       # 原始 blob bytes
reason: remove-runtime-vbe-scan
```

- `new`/`shared_contract` 禁止声明 upstream binding，并必须声明唯一 `output_filename`；文件名、扩展名、
  组件类型和实际 `VB_Name` 必须一致；
- `override` 的 resolved component key 和每个 member 的 output path 永远继承对应 upstream member，
  不能从 `local_path` 或本地 basename 推导；同一 `expected_vb_name` 必须同时匹配 upstream 与 local 源码；
  组件改名按“退役旧组件 + 新增 new 组件”处理，禁止把 rename 隐藏在 override 内；
- `override` 的每个 member 都必须同时绑定 upstream/local path、Git blob OID（upstream）、原始字节
  SHA-256 和 role；candidate receipt 另外从 overlay tree 记录 local blob OID；dirty dev member 只能记录
  worktree content digest，不能伪称 Git blob；
- FRM/FRX 是一个原子 `members` bundle，角色分别为 `form_source`/`form_binary`；upstream-only 与
  `new`/`shared_contract` 各自必须提供完整单侧 bundle；override 才同时绑定双端，resolver 只能整体
  选择 upstream bundle 或 local bundle，禁止组合两侧成员，并必须核对 `OleObjectBlob`；
- package/capability 由其他 manifest 按 `source_id` 唯一映射，不在物理路径重复编码；
- manifest 最多声明 `CORE_CANDIDATE` 意图，不能声明三 profile 已通过。

### 5.2 路径和身份门

resolver 必须在 checkout 前扫描 Git tree，并为每条路径计算 portable key：统一 `/`、合法 UTF-8、
Unicode NFC/NFKC、casefold，同时拒绝尾随点/空格、Windows 保留名、file/dir 冲突和路径穿越。

源组件的 portable key、`VB_Name` 和生成保留名默认全局唯一；显式 `shared_contract` 是唯一例外，
可以把同一 source ID 的相同字节复制到不同包，但每个目标 CATVBA 内仍必须唯一。case-only rename
不可依赖 `core.ignorecase=true` 的工作区行为判断。

### 5.3 字节来源

- candidate Build Kit 的 upstream 与 overlay 输入必须从固定、已提交的 Git tree blob 读取；
- 不把 clean worktree 等同于原始 blob，因为 `core.autocrlf` 可能改变换行字节；
- dev 模式可读取 snapshot allowlist 内未提交的 overlay 工作文件，但必须记录完整 path/status/content
  digest（包括 untracked 与 deleted），且永远 `release_eligible=false`；upstream `Src` 仍从 cutoff blob 读取；
- BuildPlan 固定 `mode` 与 `snapshot_id`；candidate build 必须重新从 Git blobs 解析 candidate snapshot，
  并拒绝 dev snapshot、dev plan 或任何 worktree-derived manifest/source；
- resolver/staging 前后 `Src/` 与 `catvba_refactor/` 的版本化输入哈希必须不变。

## 6. Fail-closed 条件

| 条件 | 结果码/动作 |
|---|---|
| upstream 出现 `catvba_refactor/**` | `OVL_RESERVED_NAMESPACE_COLLISION`，停止 intake |
| 工作区 `Src` tree 不等于记录的 cutoff | `OVL_SRC_TREE_DRIFT`，禁止 plan/staging |
| 已 fetch 的 `origin/dev` 不等于记录 cutoff | `GIT_UPSTREAM_UPDATE_PENDING`，普通 build 阻断，先完成 intake |
| intake 后某个绑定 member 的 path/blob/SHA 变化 | 仅该 override 标记 `OVL_STALE_BASE`；未变化 binding 不机械改写 |
| upstream 删除、改名或大小写变更 | `OVL_UPSTREAM_PATH_MISSING`，人工决定退役/重绑/隔离 |
| 本地文件变化但 manifest hash 未更新 | `OVL_LOCAL_HASH_MISMATCH` |
| 两个 override 绑定同一组件 | `OVL_DUPLICATE_BINDING` |
| new 组件与最终路径或 `VB_Name` 冲突 | `OVL_IMPLICIT_SHADOW` |
| FRM/FRX 不完整、混用两侧成员或双方修改任一成员 | `OVL_INCOMPLETE_BUNDLE`，人工解决 |
| candidate 接收 dev/worktree snapshot 或 plan | `OVL_SNAPSHOT_MODE_MISMATCH`，禁止升级 |
| 生成器写入 upstream/versioned overlay | `STG_WRITE_BOUNDARY` |
| `.frx`/`.catvba` 依赖未知 `merge=theirs` | intake 前阻断，禁止自动选边 |

禁止自动跟随 rename、fuzzy patch、只更新哈希消红、`-X theirs`、批量选择一侧或“合并干净即语义安全”。

## 7. Upstream intake（DRAFT）

`origin/dev` 是 `Src/` 与 `resources/` 的唯一分支级上游。intake 采用三树模型：旧 cutoff `B`、
新 upstream `U`、本地 intake 前提交 `O`。

1. `O` 必须是 clean、已提交的 pre-intake HEAD；`B` 必须等于 `O` 最新 accepted sync record（首次为
   initial baseline receipt）引用的 cutoff，且同时是 `O` 与 `U` 的祖先，否则按 lineage/force-push 阻断；
2. 在 raw Git tree 上检查保留命名空间、portable path、`VB_Name` 和 FRM/FRX；
3. rename 仅作提示，政策上按 delete+add；显式记录 `rename_map`；
4. add/add、rename/delete、rename/rename、delete/modify、目标路径碰撞和 manifest 孤儿引用均阻断；
5. upstream 改到任一 override base 时，普通 build 继续阻断，逐项选择退役、重新实现、重绑或 Quarantine；
6. Git 文本冲突人工解决后仍审查公共签名、tool ID/alias、package/capability、References 和许可证影响；
7. intake merge commit 只吸收 upstream 和必要的 binding 更新，不混入新的业务功能；
8. 先生成 intake merge `M`：第一父提交必须为 `O`、第二父提交为 `U`；`M` 只包含 upstream 结果与
   必要 binding 适配，不包含宣称绑定自身 commit/tree 的 sync record；
9. 再生成单父、仅证据的 commit `E`（parent=`M`），在 `Docs/evidence/upstream-intake/` 写 post-merge
   record `R`。R 绑定 M、双亲、最终 tree、upstream/overlay identity、manifest SHA、验证、审批和不再
   适用于新 lineage 的 Kit；R 不内嵌自身 commit/tree/hash。E 不得修改产品源码、overlay 或 manifest；
10. 已产生 Kit/目标证据的提交不 rebase。cutoff 或 overlay tree 变化必须建立新的 snapshot 和 G0-G7
   运行；旧 Kit/receipt 对其原输入元组仍是不可变历史证据，但不得复用于新候选。只有明确的安全撤回
   或有效期决定才能把旧记录标为 `withdrawn`/`expired`；单纯被新版本取代只标 `superseded`。

只有当 E 位于后续 `O` 的祖先链，R 的 schema/验证/审批为 accepted，且 R 的 path、Git blob OID 和
raw SHA-256 唯一可复算时，该 cutoff 才是 `last accepted`。R 通过 `previous_record` 的 blob/hash 串成
单链；下次 `InputSnapshot` 必须记录所选 R。禁止用可变 Git notes、仅文件名或 record 自报哈希代替。

`origin/main` 只观察。main-only 修复只能重新形成有来源记录的 namespaced override 或治理 patch，
不能直接写入 `Src/`，也不能把 main 作为第二条集成基线。

## 8. `.gitattributes` 前置风险

当前 `*.frx`、`*.catvba` 声明 `binary merge=theirs`，但仓库没有可移植的
`merge.theirs.driver`。字符串 `theirs` 是自定义 driver 名，不是可依赖的内建安全策略；其他机器的
全局配置还可能静默吞掉一侧。[Git 官方 `gitattributes` 文档](https://git-scm.com/docs/gitattributes)
明确区分内建 `binary` driver 与必须在 Git config 中定义的自定义 driver。

首次正式 intake 前必须在独立元数据批次中移除/替换该规则并验证。FRX/CATVBA 双方变化一律保持
unresolved，旧 CATVBA 继续按固定哈希 evidence 处理，不能自动合并。

## 9. 规划的本地验收

- `Src/` 和 `resources/` 与精确 upstream cutoff tree 零漂移；
- candidate 全链只接受 candidate `InputSnapshot`；dev tracked/modified/deleted/untracked 输入均进入
  synthetic digest，且 dev plan 不能升级为 candidate；
- 相同 Git inputs 产生相同 ResolvedCatalog、BuildPlan、kit ID 和 ZIP SHA-256；
- stale cutoff、删除、rename、blob/SHA 变化、namespace collision 均 fail-closed；
- Windows case/Unicode/保留名/file-dir 冲突在 raw tree 阶段被检出；
- override 继承 upstream resolved identity 且 upstream/local `VB_Name` 和 binding 匹配；new 的
  output filename 显式唯一；
- FRM/FRX 的 upstream-only/new 单侧 bundle 完整，override 双端 member binding 匹配，
  `OleObjectBlob` 核对通过且不能混用两侧成员；
- generated 文件只进入 namespaced `build/`；
- 所有组件恰好属于一个包或 Quarantine；
- Core candidate 不含 Optional References、模块或禁止 API；
- Build Kit 记录 upstream cutoff/tree、overlay tree/manifest、resolver 最终组件清单和逐文件哈希；
- accepted sync record chain head 作为 snapshot/kit/G0 必填身份，可由 evidence commit、record path/blob
  OID/raw SHA-256 复算，且不存在自引用；
- Form bundle receipt 记录每个 member 的 role、选中侧、resolved path、适用的 upstream/local
  path/blob/SHA 和 `OleObjectBlob` 核对结果；
- 本地结果保持 `compile_status=not-run`、`target_build_required=true`、`release_eligible=false`。

## 10. 分阶段落地顺序（DRAFT）

1. 更新设计与文档；不创建实现目录。
2. 独立修复 `.gitignore`、`.gitattributes` 和根路径 allowlist，并验证 Git 行为。
3. 创建 namespaced schema、只读 Git inventory 和 `Src` 零漂移门；不迁移业务模块。
4. TDD 实现 resolver，并用合成 fixture 覆盖所有 stale/collision/FRM-FRX 条件。
5. 迁移一个低耦合整组件为 override golden，再迁移本地新 Core candidate。
6. 生成 namespaced staging/Build Kit；本地最高状态仍为 `KIT-READY`。
7. 在 B28 完成 Compile、重启、三 profile、安全包装、试点和回滚门禁。

该顺序只有在更新后的详细 spec 经书面复核并形成日期化实施计划后才能执行。
