# CATVBA R2018 恢复状态

> 状态：CURRENT
>
> 更新日期：2026-07-13
>
> 分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`
>
> 交付结论：**NO-GO**
>
> `release_eligible=false`

本文是当前状态与上下文恢复入口。详细事实以 Git 文件、固定哈希和目标机证据为准。

## 1. 立即停止条件

- 不普通/生产安装、运行、回滚或分发根目录旧 CATVBA；
- 不从旧 CATVBA `Save As` 创建 B28 工程；
- 不声称本地完成 CATIA Compile、运行、许可证或发布验证；
- 不安装 B30/x86/Temp/未知 DLL 来补污染引用；
- 不执行 `LicenseReset.catvbs` 或持久化修改许可证；
- 不写 fork `main/dev` 或上游仓库；
- 不打正式 tag/Release，不使用现有 workflow 发布旧二进制。

## 2. 当前事实

| 项目 | 状态 |
|---|---|
| 本地 CATIA | 无；只能编写、静态分析、pytest、Build Kit 和审计准备 |
| 目标宿主 | CATIA V5-6R2018（R28/B28）、VBA7、64 位 |
| 目标资格 | `(AB3 OR HD2 OR MD2) AND SPA AND FTA` |
| Core | 不早绑定 SPA/FTA；在 P-AB3/P-HD2/P-MD2 分别通过的能力交集 |
| SPA/FTA | 目标机保证权益；物理隔离为默认部署 Fleet Extensions |
| 上游 | `verysolecd/Macro_menu:dev` 是 Src/resources 逻辑来源 |
| fork | main/dev 镜像上游；个人实现只写 codex/dev-review-report |
| Python | 根 pyproject.toml/uv.lock/.python-version 为唯一真源 |
| 目录 | `catvba_refactor/` 已建立说明性脚手架；无实现文件 |
| 设计 | 总架构和四份子规格已于 2026-07-13 获用户书面确认 |
| 实施计划 | 离线 Build Kit 日期化计划已编写，尚未开始执行 |
| CATIA 证据 | 缺 B28 Compile、重启、三最小 profile、SPA/FTA、试点与回滚 |

## 3. 遗留证据

| 文件 | SHA-256 | 定位 |
|---|---|---|
| `CATIA_V5_SimpleMacroMenu.catvba` | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` | legacy evidence only |
| `CAT_menu.catvba` | `1C8EC220F3D97F84D5404F24225938B2A8E2821D3F16BFEF5964E97023CA2FCA` | legacy evidence only |

## 4. 设计入口

- [恢复总架构](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
- [离线 Build Kit](superpowers/specs/2026-07-13-catvba-offline-build-kit-design.md)
- [Core Runtime MVP](superpowers/specs/2026-07-13-catvba-core-runtime-mvp-design.md)
- [B28 验证、许可证与交付](superpowers/specs/2026-07-13-catvba-b28-validation-delivery-design.md)
- [上游 intake 与 fork 同步](superpowers/specs/2026-07-13-catvba-upstream-intake-design.md)
- [离线 Build Kit 实施计划](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)
- [项目结构](PROJECT_STRUCTURE.md)
- [调查与决策台账](CATVBA重构调查与决策记录.md)

## 5. 状态门

| Gate | 状态 | 原因 |
|---|---|---|
| G0 INPUT-FROZEN | `NOT_RUN` | 实施未开始，manifest/schema 和固定输入 receipt 未实现 |
| G1 KIT-READY | `NOT_RUN` | Build Kit 工具和测试未实现 |
| G2 B28-ENV-ATTESTED | `BLOCKED` | 缺正式 SP/HF、References、环境证据 |
| G3 BUILT-UNVERIFIED | `BLOCKED` | 未从空白 B28 工程构建 |
| G4 BASE-PROFILE-MATRIX-PASS | `BLOCKED` | 缺 P-AB3/P-HD2/P-MD2 |
| G5 FLEET-SPA-FTA-PASS | `BLOCKED` | 缺 SPA/FTA 分包与三个 profile 证据 |
| G6 SECURITY-PILOT-READY | `BLOCKED` | 缺回传审计、安全包装、试点和回滚 |
| G7 RELEASE-APPROVED | `BLOCKED` | 缺全部上游门和正式审批 |

目录或文档存在不表示任何 Gate 通过。

## 6. 当前唯一下一动作

复审[离线 Build Kit 实施计划](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)，并选择
Subagent-Driven 或 Inline Execution。执行前不创建真实 config/schema/Python/VBA 实现，不生成候选
CATVBA；计划执行完成也只形成 A 环境离线证据。

## 7. 外部阻塞

- 正式 Windows、R2018 SP/HF、DS VBA/VBE；
- P-AB3/P-HD2/P-MD2 精确 DSLS entitlement 和隔离方式；
- B28 References GUID/版本/路径；
- 脱敏测试数据；
- 企业签名/ACL、制品库、审批人和证据保留；
- Production 安装根、宏库注册、试点和回滚流程。
