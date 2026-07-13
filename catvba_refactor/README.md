# catvba_refactor

本目录是 `codex/dev-review-report` 的唯一本地 CATVBA 恢复实现命名空间。

离线 Build Kit 工具、manifest/schema、pytest 和首个 Core Runtime MVP 已实现。已有仓库级源码 Kit、
但没有返回 CATVBA、CATIA Compile、References、许可证 checkout 或运行证据。

## 所有权

- `Src/`、`resources/` 仍由 `verysolecd/Macro_menu:dev` 上游 intake 管理；本目录不得回写它们。
- 本地新增/替代 VBA、配置、schema、Python 工具和测试进入本目录。
- 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 项目与依赖真源；本目录不得再建第二套项目或锁文件。
- 只允许在 fork 的 `codex/dev-review-report` 修改；不得由本目录工具自动写 `main/dev`。

## 当前结构

```text
vba/new/               本地新增的 12 个完整 Core VBA 固定组件
vba/overrides/         绑定上游基线的 Core Form `.frm/.frx` 完整替代
vba/shared_contracts/  经批准的小型跨包协议组件（当前无生产 candidate）
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
uv run macro-menu-build inventory --format json
uv run macro-menu-build check --format json
uv run macro-menu-build build-kit --format json
```

命令必须从仓库根项目运行。当前固定证据提交 `2645033a` 生成
`kit-134ecc68d131cdff743b`：16 个 component、2 个 tool，目录/ZIP verifier 均通过，双构建字节一致。
该 Kit 只包含 Core 源码；`fleet-spa`/`fleet-fta` 是隔离的 package 政策记录，当前 import-order 为空。
目标机要求至少一项 AB3/HD2/MD2，并额外具备 SPA 和 FTA；这些权益和隔离行为仍待 B28 证据。
详细哈希、清单、命令和证据上限见 `Docs/STATUS.md`。
