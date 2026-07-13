# catvba_refactor

本目录是 `codex/dev-review-report` 的唯一本地 CATVBA 恢复实现命名空间。

当前阶段只建立所有权和目录边界，不代表工具、测试、VBA 或 Build Kit 已经实现。

## 所有权

- `Src/`、`resources/` 仍由 `verysolecd/Macro_menu:dev` 上游 intake 管理；本目录不得回写它们。
- 本地新增/替代 VBA、配置、schema、Python 工具和测试进入本目录。
- 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 项目与依赖真源；本目录不得再建第二套项目或锁文件。
- 只允许在 fork 的 `codex/dev-review-report` 修改；不得由本目录工具自动写 `main/dev`。

## 规划结构

```text
vba/new/               本地新增完整 VBA 组件
vba/overrides/         绑定上游基线的完整组件替代
vba/shared_contracts/  经批准的小型跨包协议组件
resources/             本地受管资源
config/                JSON manifests（未实现）
schemas/               JSON Schema（未实现）
macro_build/            离线 Python 工具（未实现）
tests/                  pytest（未实现）
build/                  可再生输出，不入 Git
dist/                   可再生归档，不入 Git
```

任何文件进入实现前都必须符合 `Docs/superpowers/specs/` 中获批的对应子规格和后续实施计划。

