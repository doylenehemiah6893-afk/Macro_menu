# 项目结构、所有权与分支规划

> 状态：IMPLEMENTED A-ENVIRONMENT SLICE — 离线工具已实现；Core Runtime 与目标机工作未开始
>
> 更新日期：2026-07-13
>
> 适用分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`

## 1. 结论

- `verysolecd/Macro_menu:dev` 是 `Src/`、`resources/` 的逻辑上游；
- fork 的 `main/dev` 只镜像对应上游分支，不承载个人重构；
- `codex/dev-review-report` 是唯一重构写分支；
- 所有本地 VBA、Python、配置、schema、测试和派生输出进入 `catvba_refactor/`；
- 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 项目与依赖真源，不在命名空间内重复；
- 离线 Python、manifest/schema、CLI 和 pytest 已实现；没有获批 Runtime VBA、候选 CATVBA 或目标机证据。

## 2. 仓库拓扑

| 角色 | 身份 | 所有权 |
|---|---|---|
| 逻辑开发上游 | `verysolecd/Macro_menu:dev` | 上游维护者 |
| 逻辑发布上游 | `verysolecd/Macro_menu:main` | 上游维护者 |
| fork 镜像 | `doylenehemiah6893-afk/Macro_menu:main,dev` | 独立同步流程 |
| 个人重构 | `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report` | 本项目 |

规格和证据使用上述完整身份，不把 `origin/upstream` 等本机 remote 名称写成权威事实。

## 3. 当前与规划目录

```text
Macro_menu/
├─ .python-version                    # repo-level Python version truth
├─ pyproject.toml                     # 唯一 Python project/dependency truth
├─ uv.lock                            # 唯一 lock
├─ Src/                               # upstream dev intake mirror
├─ resources/                         # upstream dev intake mirror
├─ catvba_refactor/                   # 唯一本地实现命名空间
│  ├─ README.md                       # 所有权、命令和状态
│  ├─ vba/
│  │  ├─ new/README.md                # Runtime 后续计划；当前仅边界
│  │  ├─ overrides/README.md
│  │  └─ shared_contracts/README.md
│  ├─ resources/README.md
│  ├─ config/*.json                   # 四份严格 manifest；当前无 candidate component/tool
│  ├─ schemas/*.schema.json           # 四份输入 JSON Schema
│  ├─ macro_build/*.py                # snapshot/inventory/resolver/policy/Kit/audit/CLI
│  ├─ tests/test_*.py                 # A 环境单元、攻击面和端到端测试
│  ├─ build/                          # 按需生成、Git ignored
│  └─ dist/                           # 按需生成、Git ignored
├─ Docs/
│  ├─ STATUS.md
│  ├─ CATVBA重构调查与决策记录.md
│  └─ superpowers/specs/
├─ CATIA_V5_SimpleMacroMenu.catvba   # legacy evidence only
├─ CAT_menu.catvba                   # legacy evidence only
├─ LicenseReset.catvbs               # quarantine
└─ ref_project/ DrawFunc/ artifacts/ # reference/history, release=false
```

Git 不保存空目录，所以 `build/`、`dist/` 不通过 `.gitkeep` 伪装成当前制品目录；根 `.gitignore` 已覆盖
两者，工具只在完整 preflight 通过后按需创建。

## 4. 写入边界

| 区域 | 允许 | 禁止 |
|---|---|---|
| `Src/`、`resources/` | 审定 upstream intake | 本地修复、转码、格式化、生成物 |
| 根 Python 元数据 | Python 版本、依赖、CLI/pytest 配置 | 第二套环境或私有 index 凭据 |
| `catvba_refactor/vba/new` | 本地新增完整组件 | 隐式覆盖上游同名身份 |
| `catvba_refactor/vba/overrides` | 精确绑定的完整替代 | fuzzy patch、自动跟随 rename、缺 base hash |
| `shared_contracts` | 小型无业务协议 | KCL、Optional 业务、许可证类型污染 |
| `config/schemas` | 获批 manifest/schema | 空配置冒充 G0、客户数据/密钥 |
| `macro_build/tests` | 离线 Python 和 pytest | 假装执行 CATIA Compile |
| `build/dist` | 全新可再生输出 | 人工维护为真源、入 Git |
| `Docs` | 规格、状态、证据和历史 | 产品二进制、客户模型 |

## 5. 真源模型

```text
upstream dev cutoff Git blobs
+ committed catvba_refactor VBA/resources/config/schema/tooling
+ root pyproject/uv.lock/.python-version
= 可复算的 Build Kit 输入
```

candidate 只接受干净、已提交的工作分支 tree，并固定上游仓库/commit、fork dev commit、工作分支
commit/tree 和 manifest/tool digest。`inventory/check --worktree` 只提供开发诊断；即使 dirty overlay 能形成
synthetic digest，也不得生成正式 snapshot、Build Kit 或 candidate。

首个 Kit 不强制依赖复杂的 accepted-record 链；上游 intake 记录按独立规格建立。任何 upstream/fork
cutoff 不一致都会阻断新的 candidate，但不会使旧 Kit 的历史证据消失。

当前 clone 只有个人分支 ref，没有本地 `dev` ref。因此仓库 `check/build-kit` 以基础设施退出码 4
失败关闭；工具不会猜 remote 别名、回退 `HEAD` 或创建 `dev`。临时端到端 fixture 显式创建隔离的本地
`dev`，只验证引擎确定性，不能替代仓库 G0/G1 receipt。

## 6. 组件与包

FRM/FRX 是原子 bundle。override 同时绑定两端 path/blob/raw SHA-256/role/组件身份，resolver 只能整体
选择一侧。改名按退役旧组件 + new 组件处理。

包分类：

```text
CORE_CANDIDATE
FLEET_EXTENSION_SPA
FLEET_EXTENSION_FTA
BASELINE_EXTENSION_CANDIDATE
CATIA_LICENSED_OPTIONAL_CANDIDATE
EXTERNAL_INTEGRATION_OPTIONAL
DEVTOOLS
QUARANTINE
```

目标资格是 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`。SPA/FTA 默认部署但不进入 Core Reference；Excel
是 External Integration，不是 CATIA Licensed Optional。

## 7. Fail-closed 条件

- upstream 创建 `catvba_refactor/**`；
- fork dev 与固定 upstream cutoff 不一致；
- `Src/resources` 偏离 cutoff；
- override base path/blob/hash/identity 漂移；
- Unicode/case/尾点空格/Windows 保留名/file-dir/path traversal 冲突；
- `VB_Name` 或输出文件名碰撞；
- FRM/FRX 不完整、混用两侧或双方变化；
- Core 含 KCL/Cls_PDM/Cls_XLM、VBIDE/MSAPC、SPA/FTA、Office 或其他禁止类型/API；
- candidate 接受 dev/worktree snapshot；
- 工具尝试自动写 fork `main/dev`。

## 8. 规格与实施顺序

1. 已完成恢复总架构和四份子规格复审；
2. 已按 TDD 实现离线 Build Kit 计划：根项目、snapshot、schema、inventory、resolver、policy、generator、
   staging/verifier、只读 audit、CLI 和端到端 fixture；
3. 当前四份 manifest 保持零 candidate component/tool，G0/G1 均为 `NOT_RUN`；
4. 下一独立计划建立最小 Core Form override 与两个首轮工具；
5. 取得只读 cutoff ref 后，从固定输入生成仓库 Build Kit；A 环境最高到 G1；
6. 在 B28 完成 profile、SPA/FTA、安装和回滚门禁。

离线实现不创建候选 CATVBA。Core Runtime、B28 与交付工作必须分别按已批准子规格继续。
