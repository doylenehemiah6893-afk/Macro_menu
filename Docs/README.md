# Macro_menu 文档索引

> 状态：CURRENT
>
> 当前分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`

## 权威顺序

1. 目标机原始证据、Git/tree/制品 SHA；
2. [调查与决策台账](CATVBA重构调查与决策记录.md)中明确批准的 DR；
3. 状态为 APPROVED 的日期化规格；
4. 当前状态、结构、runbook；
5. 历史、参考、superseded 和 quarantine 材料。

写入仓库不等于批准；目录存在不等于实现；离线测试不等于 CATIA Compile。

## 当前入口

- [当前状态与唯一下一动作](STATUS.md)
- [项目结构、所有权与分支规划](PROJECT_STRUCTURE.md)
- [CATVBA 重构调查与决策记录](CATVBA重构调查与决策记录.md)
- [R2018 恢复、依赖与安全交付指南](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md)
- [B28 discovery、G2 与 Core-only G3-C 操作手册](runbooks/2026-07-14-catvba-b28-g2-g3-core.md)

## 已批准规格

- [恢复总架构](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
- [离线 Build Kit](superpowers/specs/2026-07-13-catvba-offline-build-kit-design.md)
- [Core Runtime MVP](superpowers/specs/2026-07-13-catvba-core-runtime-mvp-design.md)
- [B28 验证、许可证与交付](superpowers/specs/2026-07-13-catvba-b28-validation-delivery-design.md)
- [上游 intake 与 fork 同步](superpowers/specs/2026-07-13-catvba-upstream-intake-design.md)
- [B28 G2/G3 证据工具链](superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md)

用户已书面确认上述规格。实施计划：
[离线 Build Kit 实施计划](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)、
[B28 G2/G3 证据工具链实施计划](superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md)。

## 当前许可证模型

```text
Eligible = (AB3 OR HD2 OR MD2) AND SPA AND FTA
```

Core 不早绑定 SPA/FTA；SPA、FTA 作为默认部署、物理隔离的 Fleet Extensions。ST1/DL1/LO1/DMN/KWA
等保持目标机许可证候选；Excel 属于 External Integration。

## 文档状态词

```text
CURRENT
APPROVED
DRAFT
HISTORICAL
SUPERSEDED
REFERENCE
QUARANTINE
```

`STATUS.md` 只汇总状态，不能自行创造批准。历史文档中的旧 profile、旧目录或旧包模型若与当前已批准
DR 冲突，以决策台账和后续批准规格为准。

## 历史与参考材料

- `dev分支审查报告.md`：历史审计快照；
- `DOCUMENT_GOVERNANCE_AUDIT_2026-07-13.md`：历史治理记录；
- `bom_reflactor.md`、`artifacts/`：superseded；
- `EKL.md`：reference；
- `EKL计算体积.md`、部分 `ref_project/`：quarantine；
- `发版.md`：当前 NO-GO 与未来发布草案。
