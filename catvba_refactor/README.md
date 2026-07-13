# catvba_refactor

本目录是 `codex/dev-review-report` 的唯一本地 CATVBA 恢复实现命名空间。

离线 Build Kit 工具、manifest/schema 和 pytest 已实现。Runtime VBA 仍只有所有权边界；没有仓库级
Build Kit、可信 CATVBA、CATIA Compile 或许可证证据。

## 所有权

- `Src/`、`resources/` 仍由 `verysolecd/Macro_menu:dev` 上游 intake 管理；本目录不得回写它们。
- 本地新增/替代 VBA、配置、schema、Python 工具和测试进入本目录。
- 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 项目与依赖真源；本目录不得再建第二套项目或锁文件。
- 只允许在 fork 的 `codex/dev-review-report` 修改；不得由本目录工具自动写 `main/dev`。

## 当前结构

```text
vba/new/               本地新增完整 VBA 组件（后续计划）
vba/overrides/         绑定上游基线的完整组件替代（后续计划）
vba/shared_contracts/  经批准的小型跨包协议组件（后续计划）
resources/             本地受管资源
config/                project/components/packages/tools JSON manifests
schemas/               对应四份严格 JSON Schema
macro_build/            离线 Python 实现与 CLI
tests/                  A 环境 pytest 与端到端 fixture
build/                  可再生目录输出，不入 Git
dist/                   可再生归档，不入 Git
```

任何文件进入实现前都必须符合 `Docs/superpowers/specs/` 中获批的对应子规格和后续实施计划。

## 快速检查

```bash
uv sync --frozen
uv run pytest -q
uv run macro-menu-build --help
uv run macro-menu-build check --worktree --format json
```

命令必须从仓库根项目运行。当前 clone 缺本地 `dev` ref，最后一条会返回基础设施退出码 4；这是明确的
fail-closed 状态，不应以 `HEAD` 或自动写 `dev` 绕过。fixture 的 worktree check 会返回 0 且
`formal_eligible=false`，但不会生成 Kit。
