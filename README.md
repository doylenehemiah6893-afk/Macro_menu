# CATIA V5 宏菜单（R2018 恢复工程）

> [!CAUTION]
> **当前交付状态：NO-GO。**
>
> 根目录中的 `CATIA_V5_SimpleMacroMenu.catvba` 与 `CAT_menu.catvba` 仅为遗留取证样本，
> 不是获准普通/生产安装、运行、回滚或分发的 CATIA R2018 制品；只有另行批准的隔离取证会话
> 才能按恢复指南使用只读副本。当前尚无 B28 Compile、重启、
> AB3-only / MD2-only / HD2-only 三套隔离许可证验收或正式发布批准证据。

本仓库正在把原有单体 CATVBA 恢复为源码优先、可离线审查、可在 CATIA
V5-6R2018（R28/B28）与 VBA7 64 位目标机重建和现场调试的交付体系。

## 先从这里开始

- [当前状态与唯一下一动作](Docs/STATUS.md)
- [项目文档索引与权威规则](Docs/README.md)
- [本地 Overlay 结构与上游同步规划](Docs/PROJECT_STRUCTURE.md)
- [恢复调查与已批准决策](Docs/CATVBA重构调查与决策记录.md)
- [R2018 恢复、依赖与安全交付指南](Docs/CATIA_V5_R2018_VBA7_64恢复与依赖指南.md)
- [当前 NO-GO 发布政策与未来流程草案](Docs/发版.md)

## 目标与边界

- 正式目标：CATIA V5-6R2018（R28/B28）、VBA7、64 位 Windows。
- 许可证基线：AB3、MD2、HD2。
- Core：只包含在 AB3-only、MD2-only、HD2-only 三套 profile 中分别通过的能力交集。
- 超出交集：物理隔离为 Baseline Extension 或 Licensed Optional，并单独记录许可证风险、
  隔离方式和无额外许可证的替代实现。
- 当前工作区没有 CATIA：这里只能编写、分析、离线测试和准备 Build Kit；任何 CATIA
  Compile、运行、许可证或发布结论都必须来自受控 B28 目标环境证据。
- 重构只发生在本地 `codex/*` 分支；`origin/dev` 是唯一代码上游，`origin/main` 仅作旧发布观察源。

## 当前仓库材料如何使用

| 路径 | 当前定位 | 是否进入正式发布 |
|---|---|---:|
| `Src/` | 遗留文本源码与后续迁移输入；首阶段保持原位置 | 仅经清单筛选、生成和目标机验证后 |
| 根目录两个 `.catvba` | legacy evidence，保留原哈希 | 否 |
| `LicenseReset.catvbs` | quarantine；禁止以修改许可证方式探测能力 | 否 |
| `ref_project/`、`DrawFunc/` | 来源和适用性待核验的参考材料 | 否 |
| `artifacts/` | 历史分析材料，不是发布制品目录 | 否 |
| `Docs/` | 当前设计、状态、证据和历史记录 | 按发布清单决定 |

旧版 README 中“下载 CATVBA 后直接添加宏库”“缺引用时安装 .NET/Excel”等操作已撤销。
只有当 [Docs/STATUS.md](Docs/STATUS.md) 指向未过期的 G7 `PASS` 记录、不可变制品和
SHA-256 时，才能把某个 CATVBA 称为正式可安装版本。
