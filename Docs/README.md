# Macro_menu 文档索引

> 状态：CURRENT
>
> 当前分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`

## 权威顺序

1. `resume/state.json`；仅当其 `active_bundle_path` 非空时，再联合 `CURRENT.json`、bundle provenance 与目标机原始证据；
2. [当前状态](STATUS.md)、[当前开发规格](CURRENT_DEVELOPMENT_SPEC.md)和[当前开发计划](CURRENT_DEVELOPMENT_PLAN.md)；
3. [调查与决策台账](CATVBA重构调查与决策记录.md)中明确批准的 DR；
4. 状态为 APPROVED 的日期化规格与 process records；
5. 历史、参考、superseded 和 quarantine 材料。

写入仓库不等于批准；目录存在不等于实现；离线测试不等于 CATIA Compile。

## 当前入口

- [当前状态与唯一下一动作](STATUS.md)
- [新环境唯一续作入口](../RESUME.md)
- [当前开发规格](CURRENT_DEVELOPMENT_SPEC.md)
- [当前开发计划与任务状态](CURRENT_DEVELOPMENT_PLAN.md)
- [开发环境复刻与仓库同步指南](ENVIRONMENT_REPRODUCTION.md)
- [项目结构、所有权与分支规划](PROJECT_STRUCTURE.md)
- [CATVBA 重构调查与决策记录](CATVBA重构调查与决策记录.md)
- [R2018 恢复、依赖与安全交付指南](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md)
- [B28 Discovery 原生 Windows 唯一执行入口](runbooks/b28-target/README_TARGET_B28.md)
- [历史 B28 G2/G3-C 手册（SUPERSEDED）](runbooks/2026-07-14-catvba-b28-g2-g3-core.md)

## 已批准规格

- [恢复总架构](superpowers/specs/2026-07-13-catvba-r2018-recovery-design.md)
- [离线 Build Kit](superpowers/specs/2026-07-13-catvba-offline-build-kit-design.md)
- [Core Runtime MVP](superpowers/specs/2026-07-13-catvba-core-runtime-mvp-design.md)
- [B28 验证、许可证与交付](superpowers/specs/2026-07-13-catvba-b28-validation-delivery-design.md)
- [上游 intake 与 fork 同步](superpowers/specs/2026-07-13-catvba-upstream-intake-design.md)
- [B28 G2/G3 证据工具链](superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md)
- [B28 Discovery operator bundle](superpowers/specs/2026-07-15-b28-discovery-operator-bundle-design.md)

用户已书面确认上述规格。`superpowers/` 是历史目录名，不代表仓库依赖任何同名外部 skill；
所有当前执行只使用仓库内命令和 [当前开发计划](CURRENT_DEVELOPMENT_PLAN.md)。历史实施计划：
[离线 Build Kit 实施计划](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)、
[B28 G2/G3 证据工具链实施计划](superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md)。
[B28 Discovery operator bundle 实施计划](superpowers/plans/2026-07-15-b28-discovery-operator-bundle.md)。

## 审查与过程记录

- [2026-07-18 远端首次发布与 CI 修正](process/2026-07-18-remote-publication-and-ci-correction.md)
- [2026-07-16 本地环境、代码与仓库同步审查](reviews/2026-07-16-local-environment-and-repository-audit.md)
- [2026-07-16 环境复刻与仓库治理修订](process/2026-07-16-environment-reproducibility-refresh.md)
- [B28 operator 实施审查](process/2026-07-16-b28-discovery-operator-implementation-review.md)
- [B28 operator bundle 构建记录](process/2026-07-16-b28-discovery-operator-bundle-build.md)

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
