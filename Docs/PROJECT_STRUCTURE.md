# 项目结构与上游同步规划

> **Status:** APPROVED — 高层 Overlay 边界；DRAFT — 目录契约与执行细节
>
> **Approved:** 2026-07-13
> **Scope:** 仅规划本地 `codex/*` 分支；不修改远端，不立即搬迁遗留目录。本文不授权绕过 [STATUS.md](STATUS.md) 的唯一下一动作进入实现。

## 1. 结构决策

已批准的高层决策是采用本地 **Overlay**：保留远端 `dev` 仍在维护的平面源码和遗留材料原位置，
在其外增加配置、schema、构建工具、测试和状态文档。首阶段不做大规模移动、重命名或批量转码，
避免后续吸收 `origin/dev` 时产生大量 rename/delete 冲突。

下面的具体目录职责、`legacy.yml` 字段、intake 记录格式和阶段顺序是 **DRAFT**；需随详细设计
书面复核后才能转成实施计划。

```text
Macro_menu/
├─ Src/                    # upstream-compatible legacy source zone
├─ resources/              # 现有资源；先保留原位置
├─ .github/                # 现有 workflow；当前发布资格不合格
├─ .agents/ .vscode/       # 本地代理/编辑器辅助；release=false
├─ .context/ .antigravity/ # 本地代理辅助；release=false
├─ .venv/                  # 本地 Python 环境；release=false，当前未由根 ignore 可靠覆盖
├─ DrawFunc/               # 未核验参考材料，不进入发布
├─ ref_project/            # 未核验参考材料，不进入发布
├─ artifacts/              # 历史分析材料，不是构建输出
├─ Docs/                   # 规范、状态、计划、证据与历史记录
│  ├─ README.md
│  ├─ STATUS.md
│  ├─ PROJECT_STRUCTURE.md
│  └─ superpowers/
│     ├─ specs/
│     └─ plans/            # 获批设计后创建日期化实施计划
├─ config/                 # 计划新增：项目、包、能力、工具、遗留分类策略
├─ schemas/                # 计划新增：机器可验证的数据契约
├─ macro_build/            # 计划新增：离线 CLI、生成器、审计和打包工具
├─ tests/                  # 计划新增：离线测试、fixtures、golden 与策略门
├─ build/                  # 计划新增：可再生中间物/Kit staging；ignore 尚未实施
├─ dist/                   # 计划新增：不可变 Build Kit 输出；ignore 尚未实施
├─ main.py pyproject.toml uv.lock .python-version
│                          # 现有 Python/audit bootstrap，不等于获批 macro_build 工具链
├─ CATIA_V5_SimpleMacroMenu.catvba  # legacy evidence only
├─ CAT_menu.catvba                  # legacy evidence only
├─ LicenseReset.catvbs              # quarantine
└─ user_data.json                   # devtool-local legacy config
```

目录存在不代表实现已开始。当前实际状态以 [STATUS.md](STATUS.md) 为准。

## 2. 目录职责与写入边界（DRAFT）

| 区域 | 允许内容 | 禁止内容 |
|---|---|---|
| `Src/` | 原始文本 VBA/FRM/FRX、后续小步修复 | Build 输出、目标机 CATVBA、自动生成缓存 |
| `config/` | 包、能力、工具、引用、遗留分类和策略清单 | 密钥、机器特定绝对路径、许可证凭据 |
| `schemas/` | config/manifest/evidence JSON Schema | 运行时数据和生成结果 |
| `macro_build/` | 只读扫描、校验、生成、staging、审计 CLI | CATIA/VBE 自动化假装本地 Compile |
| `tests/` | 单元/集成、fixtures、golden、规则与确定性测试 | 真实客户模型、许可证数据、Production CATVBA |
| `build/` | 可删除、可重建的中间目录 | 人工维护的真源 |
| `dist/` | 由获批流程生成的 Build Kit；本地默认不提交 | 未校验的根目录 glob、旧 CATVBA 混入 |
| `Docs/` | 规范、计划、状态、同步/Kit/build/evidence 记录 | 密钥、原始客户数据、不可追溯结论 |

当前 `.gitignore` 仍是遗留内容：没有覆盖 `build/`、`dist/`、`.venv/`，且对 `.context`、
`.antigravity` 使用的反斜杠规则尚未证明有效。创建 Overlay 目录前必须在独立元数据批次中修复并用
`git check-ignore` 验证；本文中的“计划忽略”不是当前事实。

## 3. 上游兼容区与本地 Overlay

### 上游兼容区

`Src/`、`resources/`、根目录遗留文件以及远端已有路径先不移动。对它们的修改应：

- 小步、语义明确、避免格式化噪声；
- 保持遗留 VBA 原字节，除非转码方案已单独批准并有字节级测试；
- 每次 intake 先区分上游业务变化与本地恢复变化；
- 不把 overlay 生成文件回写到遗留源码目录。

### 本地 Overlay 区

`config/`、`schemas/`、`macro_build/`、`tests/` 及新增治理文档由本地重构维护。
它们通过 manifest 引用遗留源码，不要求上游采用同一目录结构。这样远端继续更新平面 `Src/` 时，
大部分变化仍能按原路径审查和合并。

## 4. 遗留材料分类（DRAFT 机器化细节）

建议后续由 `config/legacy.yml` 机器化记录；文件名、schema 和字段仍待详细设计批准。在该文件创建前，
下表只是便于审查的规划，不授权实现：

| 路径/模式 | 分类 | `release` | 处理 |
|---|---|---:|---|
| `*.catvba`（根目录现有文件） | `legacy-evidence` | `false` | 固定大小/哈希，只读保留；不得作 seed/回滚 |
| `LicenseReset.catvbs` | `quarantine` | `false` | 不执行、不打包、不用于能力探测 |
| `user_data.json` | `devtool-local` | `false` | 当前含机器路径；未来改用模板/本地忽略配置 |
| `.context/`、`.antigravity/`、`.cursorrules` | `agent-tooling` | `false` | 本地辅助，不属于产品交付 |
| `.agents/`、`.vscode/`、`.venv/` | `local-dev-tooling` | `false` | 代理、编辑器和本地环境，不进入 Kit/发布 |
| `.github/workflows/auto-release.yml` | `legacy-workflow-ineligible` | `false` | 当前不具备发布资格；不得以 tag 试运行 |
| `main.py`、`pyproject.toml`、`uv.lock`、`.python-version` | `legacy-audit-bootstrap` | `false` | 现有开发材料，不等于获批工具链 |
| `ref_project/`、`DrawFunc/` | `unverified-reference` | `false` | 来源、许可和目标适用性确认前隔离 |
| `artifacts/` | `historical-analysis` | `false` | 保留追溯，不当作 build/dist |

## 5. 跟进 `origin/dev` 的本地流程（高层边界已批准，步骤 DRAFT）

`origin/dev` 是唯一**分支级代码上游**，这是已批准边界。以下 intake 命名和步骤是待批准草案：

1. fetch 后记录远端旧/新 SHA、时间和操作者；
2. 从新 `origin/dev` 建本地 `intake/dev-YYYYMMDD[-N]`；
3. 审查 Git 拓扑、路径变化、VBA 编译风险、包/许可证影响和发布风险；
4. 更新 overlay manifest 对新增/删除/改名模块的分类；
5. 运行全部离线测试与静态门；
6. 用显式 merge commit 吸收到重构分支，保留 upstream cutoff；
7. 已形成 Build Kit 或目标证据的提交不 rebase；输入变化使相应 Kit 失效并重建。

禁止用 `git pull` 把未知远端变化直接混入正在审查的工作树。禁止无共同祖先 squash、全树
`--theirs` 或把旧 `main` 整体混入重构分支。

`origin/main` 只观察旧发布、workflow 和安全补丁；与 `dev` 没有共同祖先时不合并。
确需参考的 main-only 修复必须逐项比较后重新形成有来源记录的本地 patch，不能把 main 当成第二条集成基线。
未来发布线可在详细治理设计批准后，从共享 `dev` 历史建立
受保护的 `release/r28`；这不是当前本地结构批次的操作范围。

## 6. 分阶段落地顺序（DRAFT）

1. **文档治理**：统一入口、状态、结构、发布禁令和历史材料分类。
2. **Overlay 元数据**：创建 `config/`、`schemas/`、`.gitignore` 与机器化 legacy/package/capability 清单。
3. **离线工具链**：TDD 创建 `macro_build/` 与 `tests/`，只读扫描并生成确定性 Build Kit。
4. **Core 源码迁移**：按获批计划修复编译边界、生成静态菜单/协议和少量只读候选工具。
5. **B28 交接**：目标机构建、Compile、重启、三 profile、安全包装、试点与回滚。
6. **可选包迁移**：Baseline Extension 和 Licensed Optional 分别建规格、证据与替代实现。

该顺序只有在详细设计和日期化实施计划获批后才能执行。每阶段结束都应更新
[STATUS.md](STATUS.md) 并形成只包含该阶段范围的本地检查点提交。
