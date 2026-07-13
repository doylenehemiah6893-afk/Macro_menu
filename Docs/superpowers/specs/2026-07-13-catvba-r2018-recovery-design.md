# CATVBA R2018 恢复总架构设计

> 状态：DRAFT — 已按复核意见重写，待用户书面复审
>
> 日期：2026-07-13
>
> 唯一工作分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`
>
> 目标宿主：CATIA V5-6R2018（R28/B28）、VBA7、64 位 Windows

本文只定义恢复工程的总边界、仓库拓扑、许可证模型、子规格和状态门。离线工具链、Core 运行时、
B28 验证以及上游 intake 分别由独立子规格约束，避免一份设计同时承担多个实施计划。

写入本文不表示 CATIA 已编译、可运行或可发布；只有目标机证据和批准记录可以改变门禁状态。

## 1. 目标

把当前不可作为可信 R2018 制品使用的单体 CATVBA，恢复为：

- 源码优先且来源可追溯；
- 当前无 CATIA 的工作区可以编写、静态分析、测试和生成 Build Kit；
- 能在干净 B28 环境从空白工程重新构建；
- Core、固定 SPA/FTA 扩展和其他许可证/外部依赖物理隔离；
- 现场调试、证据回传、安装和回滚边界明确；
- fork 的 `main`、`dev` 与个人重构分支互不干扰。

## 2. 不可妥协约束

1. 当前工作区没有 CATIA。本地不得声称完成 CATIA Compile、运行、许可证 checkout 或发布验收。
2. 正式目标为 CATIA V5-6R2018、VBA7、64 位；Windows API 声明必须按 `PtrSafe/LongPtr` 审查。
3. 旧 `CATIA_V5_SimpleMacroMenu.catvba` 与 `CAT_menu.catvba` 仅作遗留证据，不作 seed、回滚或发布制品。
4. 正式 B28 CATVBA 必须从空白工程导入审定源码，不得从旧 CATVBA `Save As`。
5. Core 禁止 Office、网络、Shell、PowerShell、WSH、VBIDE/MSAPC、运行时源码扫描、许可证修改和额外类型库污染。
6. `Src/`、`resources/` 是上游 intake 区，本地修复和新增实现只能进入 `catvba_refactor/`。
7. 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 项目与依赖真源；命名空间内不得再建第二套项目或锁文件。
8. 只允许写个人分支 `codex/dev-review-report`；本文及后续实现不得写 fork 的 `main`、`dev` 或上游仓库。

## 3. 仓库与分支拓扑

规格使用仓库身份和分支名，不依赖某台机器的 remote 别名：

| 角色 | 固定身份 | 用途 | 写入策略 |
|---|---|---|---|
| 逻辑上游 | `verysolecd/Macro_menu:dev` | `Src/`、`resources/` 的权威代码来源 | 本项目只读 |
| 上游发布观察 | `verysolecd/Macro_menu:main` | 发布/workflow/安全差异观察 | 本项目只读 |
| fork 镜像 | `doylenehemiah6893-afk/Macro_menu:main,dev` | 跟随对应上游分支 | 由独立同步流程维护 |
| 个人重构 | `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report` | 文档、工具、测试和本地 overlay | 本项目唯一写分支 |

Build Kit 必须固定上游仓库、上游 commit、fork dev 镜像 commit 和工作分支 commit/tree。若 fork `dev`
未与所声明的上游 cutoff 一致，candidate 构建阻断；但同步 fork `main/dev` 本身不属于 Build Kit 命令的职责。

## 4. 三类环境

| 环境 | 允许 | 禁止或不能证明 |
|---|---|---|
| A：无 CATIA 工作区 | 编写、静态分析、pytest、manifest/schema、Build Kit、旧/回传 CATVBA 只读审计 | CATIA Compile、真实 API、许可证和 UI 行为 |
| B：受控 B28 构建/调试机 | 空工程导入、Compile、保存重启、References、profile 验证、生成候选 CATVBA | 直接修补生产 CATVBA、绕过许可证 |
| C：目标用户/试点机 | 受管安装、冒烟、业务验收、回滚演练 | VBE 热改 Production、使用未验收包 |

## 5. 许可证与包模型

目标机资格条件为：

```text
Eligible = (AB3 OR HD2 OR MD2) AND SPA AND FTA
```

`SPA`、`FTA` 被视为每台目标机保证具备的舰队扩展权益，但仍与 Core 物理隔离。这样类型库、API 或
当前会话 checkout 异常只禁用相应功能，不拖垮 Core。

### 5.1 最小 profile

```text
P-AB3 = AB3 + SPA + FTA
P-HD2 = HD2 + SPA + FTA
P-MD2 = MD2 + SPA + FTA
P-PROD = 现场实际组合 + SPA + FTA
```

`AB3/HD2/MD2` 表示由许可证管理员确认的 configuration 及其必要组成，不是“只出现一个 DSLS token”。
每个 profile 都必须记录精确权益、SP/HF、Reference、API/工作台取得和当前会话 checkout 证据。

### 5.2 包分类

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

- Core 源码不得声明 SPA/FTA 类型；Core 必须在三个最小 profile 中分别通过。
- SPA/FTA 包默认随目标部署，但分别编译、安装、测试和失败隔离。
- 只在 AB3/HD2/MD2 的部分 profile 通过的能力进入 Baseline Extension。
- ST1、DL1、LO1、DMN、KWA 等保持许可证候选，直到客户 R2018 权益和 API 实测确认。
- Excel 属于外部软件依赖，不得归类为 CATIA Licensed Optional。
- 产品代码名称、类型库存在、API 可取得、DSLS 权益和会话 checkout 是不同证据，不得互相替代。

## 6. 源码与目录所有权

```text
根 pyproject.toml / uv.lock / .python-version   repo-level Python toolchain truth
Src/ resources/                                upstream-owned intake mirror
catvba_refactor/vba/                           local new/override/shared contracts
catvba_refactor/config/                        manifests（规划）
catvba_refactor/schemas/                       JSON Schema（规划）
catvba_refactor/macro_build/                   Python 实现（规划）
catvba_refactor/tests/                         离线测试（规划）
catvba_refactor/build/ dist/                   ignored generated output
Docs/                                          设计、状态、计划和证据
```

现阶段只创建目录说明，不创建虚假的实现、配置、schema、测试结果或候选 CATVBA。完整 override 必须绑定
上游 path/blob/hash/组件身份；FRM/FRX 必须作为原子 bundle。

## 7. 运行时总边界

1. 菜单元数据由构建期静态目录生成；Production 不读取 `VBProject/VBComponents/CodeModule`。
2. 复用现有 `Cat_Macro_Menu_View.frm/.frx` 只能通过完整 override：删除 `Cls_PDM/pdm/KCL` 启动依赖。
3. 运行时动态创建 MSForms 控件仍可使用，但 Name 必须以字母开头、全局唯一、稳定且不超过 40 字符；Caption 与 Name 分离。
4. 同一 Core 工程内按稳定 `tool_id` 直接调用生成 dispatcher，不使用 `SystemService.ExecuteScript` 自调用。
5. 跨 CATVBA 调用协议在 B28 spike 通过前不是已批准接口；首个里程碑不加载 Optional/Fleet 包。
6. 首轮只交付 `core.healthcheck` 和 `core.document-summary`；Product/Part/Drawing 三项审计进入第二个目标机回合。
7. 所有功能默认只读；首个里程碑不写模型、不保存、不导出、不修改许可证或 CATIA 全局策略。

## 8. 子规格与批准顺序

1. [离线 Build Kit 设计](2026-07-13-catvba-offline-build-kit-design.md)
2. [Core Runtime MVP 设计](2026-07-13-catvba-core-runtime-mvp-design.md)
3. [B28 验证、许可证与交付设计](2026-07-13-catvba-b28-validation-delivery-design.md)
4. [上游 intake 与 fork 同步设计](2026-07-13-catvba-upstream-intake-design.md)

每份子规格单独批准、单独形成实施计划；批准总架构不自动批准子规格中的 DRAFT 细节。

## 9. 状态门

```text
G0 INPUT-FROZEN
G1 KIT-READY
G2 B28-ENV-ATTESTED
G3 BUILT-UNVERIFIED
G4 BASE-PROFILE-MATRIX-PASS
G5 FLEET-SPA-FTA-PASS
G6 SECURITY-PILOT-READY
G7 RELEASE-APPROVED
```

- A 环境最高只能形成 G0/G1 证据；不得把离线检查称为 Compile 或运行通过。
- G4 要求 P-AB3、P-HD2、P-MD2 的 Core 矩阵分别通过。
- G5 要求 SPA、FTA 扩展在三个最小 profile 中分别通过，并证明失败不影响 Core。
- G6/G7 还需要现场安全、安装、试点和回滚审批。
- 输入源码、manifest、generator 或制品变化时，相应下游门必须重新执行。

## 10. 总体验收标准

- 所有本地输出都标明 `target_build_required=true`、`compile_status=not-run`、`release_eligible=false`；
- Core staging 不含 KCL、Cls_PDM、Cls_XLM、VBIDE/MSAPC、SPA/FTA 或其他可选类型污染；
- 根 Python 项目和命名空间源码不存在第二套 lock/project；
- Build Kit 可以从固定 Git 输入复算，且来源、编码、FRM/FRX、package/capability 全部 fail-closed；
- B28 从空白工程构建，References 无 MISSING/B30/x86/Temp/用户目录污染；
- Core、SPA、FTA 和其他包具有独立编译、安装、禁用、证据和回滚边界；
- fork `main/dev` 与个人工作分支职责明确，任何工具都不会自动写 `main/dev`；
- 没有有效 G7 记录时，项目继续保持 NO-GO。

## 11. 外部阻塞与待决项

- 正式 Windows、R2018 SP/HF、DS VBA/VBE 版本；
- P-AB3/P-HD2/P-MD2 的精确 DSLS entitlement 与隔离方式；
- B28 References GUID/版本/路径；
- 脱敏 CATPart/CATProduct/CATDrawing；
- 企业签名、ACL、制品库、证据保留和审批人；
- Production 安装根、宏库注册方式和跨 CATVBA 调用可靠性。

这些阻塞不妨碍获批后的 A 环境实现，但会阻止 G2 及以后状态。

