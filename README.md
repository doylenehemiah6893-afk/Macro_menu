# CATIA V5 宏菜单（R2018 恢复工程）

> [!CAUTION]
> **当前交付状态：NO-GO。**
>
> 根目录两个 CATVBA 仅为遗留取证样本，不是普通/生产安装、运行、回滚或分发制品。当前没有 B28
> Compile、重启、许可证矩阵或发布批准证据。

本分支正在把原有单体 CATVBA 恢复为源码优先、可离线审查、可在 CATIA V5-6R2018（R28/B28）和
VBA7 64 位目标机从空白工程重建与现场调试的交付体系。A 环境离线 Build Kit 引擎、CLI、严格
manifest/schema、只读 CATVBA 审计和 Core Runtime MVP 已实现。证据提交 `2645033a` 的真实
Core Kit 已完成双构建、四路 verifier 和字节确定性校验；目标机 Compile/运行证据仍未实现。

## 当前目标环境

```text
CATIA V5-6R2018 / VBA7 / 64-bit Windows
Eligible license = (AB3 OR HD2 OR MD2) AND SPA AND FTA
```

- Core 不早绑定 SPA/FTA，必须在 P-AB3/P-HD2/P-MD2 分别通过；
- SPA、FTA 是所有目标机保证具备、默认部署但物理隔离的 Fleet Extensions；
- 其他 CATIA 产品代码单独列许可证候选、隔离和无额外许可证替代；
- Excel 是外部软件集成，不是 CATIA 许可证。

## 从这里开始

- [新环境唯一续作入口](RESUME.md)
- [当前状态](Docs/STATUS.md)
- [文档索引](Docs/README.md)
- [恢复总架构](Docs/superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
- [项目结构](Docs/PROJECT_STRUCTURE.md)
- [调查与决策](Docs/CATVBA重构调查与决策记录.md)
- [R2018 恢复指南](Docs/CATIA_V5_R2018_VBA7_64恢复与依赖指南.md)
- [B28 Discovery 原生 Windows 操作手册](Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md)

## 仓库边界

| 路径/分支 | 定位 |
|---|---|
| `verysolecd/Macro_menu:dev` | `Src/resources` 逻辑上游 |
| fork `main/dev` | 对应上游镜像，不承载个人重构 |
| fork `codex/dev-review-report` | 唯一重构写分支 |
| 根 `pyproject.toml/uv.lock/.python-version` | 唯一 Python 项目与依赖真源 |
| `Src/`、`resources/` | intake-only 上游镜像 |
| `catvba_refactor/` | 本地离线工具、配置、schema、测试和 VBA overlay 实现命名空间 |
| 根目录两个 `.catvba` | legacy evidence only |
| `LicenseReset.catvbs` | quarantine |
| `ref_project/`、`DrawFunc/`、`artifacts/` | reference/history，release=false |

当前工作区没有 CATIA，只能编写、静态分析、pytest、Build Kit 和只读审计。任何“已编译、可运行、
许可证通过、可发布”必须由受控 B28 目标机证据支持。

## 离线工具

依赖只取根 [pyproject.toml](pyproject.toml) 和 `uv.lock`：

```bash
uv sync --frozen
uv run macro-menu-build inventory --format json
uv run macro-menu-build check --worktree --format json
uv run macro-menu-build build-kit --format json
uv run macro-menu-build verify-kit <kit-directory-or-zip> --format json
uv run macro-menu-build audit-catvba <returned.catvba> --expect <kit-manifest.json> --package <package-id> --format json
uv run pytest -q
```

当前 manifest 精确批准 13 个固定 Core candidate component 和两个首回合只读工具：
`core.healthcheck` 与 `core.document-summary`。Generator 加入 3 个确定生成 component，所以 checked/built
catalog 为 16 个 component、2 个 tool。历史 Kit 标识和 hash 只作 receipt 摘要，实际 bytes 当前不可取得，不能作为
active artifact；完整边界见 [Docs/STATUS.md](Docs/STATUS.md)。当前 operator bundle 仍在 preparation，active
bundle/Kit/handoff 均为 null。G0/G1 只有 A 环境离线 `PASS` 证据，`compile_status=not-run`、
`release_eligible=false`，30 个目标 case 全部 `not-run`；G2–G7 仍 `BLOCKED`。
