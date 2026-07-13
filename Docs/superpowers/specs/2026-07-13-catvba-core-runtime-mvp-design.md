# CATVBA Core Runtime MVP 设计

> 状态：APPROVED — 用户已于 2026-07-13 书面确认
>
> 上位规格：[CATVBA R2018 恢复总架构设计](2026-07-13-catvba-r2018-recovery-design.md)

## 1. 范围

本规格定义第一套不读取自身源码、不依赖 KCL/Cls_PDM/Cls_XLM、不早绑定 SPA/FTA/Office/Optional
类型的 Core 候选源码。A 环境可以生成和静态测试源码，但只有 B28 可以把候选转为 Compile/运行证据。

首轮工具：

1. `core.healthcheck`
2. `core.document-summary`

第二个目标机回合：

3. `core.product-tree-audit`
4. `core.part-structure-audit`
5. `core.drawing-structure-audit`

拆成 2+3 是为了先验证菜单、References、Compile、重启和调用闭环，再扩大 CATIA 对象模型表面。

## 2. 组件边界

新增组件规划：

```text
MM_Entry.bas
MM_MenuCatalog.bas              generated descriptors
MM_MenuPresenter.bas            runtime MSForms construction
MM_Protocol.bas
MM_Dispatch.bas                 generated allowlist
MM_BuildInfo.bas                generated constants
MM_Error.bas
MM_Log.bas
MM_TryGet.bas
C_MMButtonHandler.cls
C_MMContext.cls
C_MMResult.cls
C_MMStateGuard.cls
MM_HealthCheck.bas
MM_DocumentSummary.bas
MM_ProductAudit.bas             cycle 2
MM_PartAudit.bas                cycle 2
MM_DrawingAudit.bas             cycle 2
```

完整 override：

```text
Cat_Macro_Menu_View.frm + Cat_Macro_Menu_View.frx
```

Core staging 明确排除：`A00_Menu` 动态源码扫描路径、`KCL`、`Cls_DynaWD`、`Cls_PDM`、`Cls_XLM`、
`Cls_VbaMdlMgr`、`Cls_allBTNEVT`、`cls_MnUI`、DevTools、SPA、FTA 和其他 Optional 模块。

## 3. 菜单策略

复用现有 FRX 资产，但必须以 FRM+FRX 原子 override 导入。Form override 必须：

- 删除 `Private WithEvents prdObserver As Cls_PDM`、`Set prdObserver = pdm`、`toMP` 及所有 KCL/global 依赖；
- 从生成的静态目录接收工具清单，不访问 APC/VBProject/CodeModule；
- 允许运行时创建 MultiPage/Button，但控件 Name 由 `tool_id` 生成；
- Name 以字母开头、仅 `[A-Za-z0-9_]`、不超过 40 字符、目标 Form 内唯一；
- Caption/提示/分组与 Name 分离；碰撞在构建期阻断；
- 按钮事件只保存稳定 `tool_id`，不保存模块名、过程名或 CATVBA 路径。
- 事件对象使用内建 `Collection` 保持生命周期，不调用 `KCL.Initlst()`。

固定规则：

```text
canonical_id = lower(stable tool_id)
slug         = 非 [a-z0-9_] 替换为 "_"
control_name = "btn_" + Left(slug, 26) + "_" + SHA256_UTF8(canonical_id)[0:8]
```

Page 使用同类 `pg_..._<hash8>` 规则。handler 显式保存 canonical tool ID，不从 Name 反推命令。生成器
必须以 golden tests 覆盖中文、长 ID、大小写、标点、排序变化和碰撞。

## 4. Dispatcher 与调用

同一 Core 工程内直接调用：

```vb
Public Function Core_Invoke(ByVal request As Variant) As Variant
```

生成的 `Select Case commandId` 是唯一允许清单；未知 ID 返回 `UNKNOWN_COMMAND`。Core 内禁止使用
`SystemService.ExecuteScript` 自调用，禁止从 manifest 接受任意 module/procedure/path。

首轮协议：

```text
Request  = ["MM/1", requestId, commandId, clientVersion, options]
Response = ["MM/1", requestId, status, code, displayMessage, data, meta]
```

只允许 Empty、Boolean、Long、Double、String 和嵌套 Variant 数组。禁止 COM 对象、Dictionary、
Collection、自定义类、Error Variant 和任意可执行定位信息。深度、字符串和行数上限必须由离线测试覆盖。
`options/meta` 中的键值数据用排序稳定、key 唯一的 `[key,value]` 数组表达，不使用 Dictionary。

跨 CATVBA 调用不是本规格验收项；只有 B28 spike 证明 `SystemService.ExecuteScript` 的参数、返回、错误和
路径行为可靠后，才能在 Fleet/Optional 规格中批准。

运行时分别维护：

```text
core.status  = READY | BLOCKED
spa.status   = NOT_PROBED | READY | UNAVAILABLE | BROKEN
fta.status   = NOT_PROBED | READY | UNAVAILABLE | BROKEN
fleet.status = READY | DEGRADED | BLOCKED
```

Core 启动不得主动 probe 或装载 SPA/FTA。扩展不可用时 Core 仍为 READY，Fleet 为 DEGRADED，对应调用
返回 `CAPABILITY_UNAVAILABLE`，另一扩展和全部 Core 工具继续可用。

## 5. 上下文和状态

- 每次调用局部取得 CATIA 对象，不缓存跨调用 COM 引用，不使用全局 `As New`；
- `C_MMContext` 只保存本次调用需要的 Object 引用和文档类型；
- `C_MMStateGuard` 记录活动文档/窗口、Selection 数量以及本次框架实际触碰的应用属性；
- 只恢复本次代码明确修改的属性，不盲目强制恢复用户在 modeless 菜单期间主动切换的文档；
- 所有入口使用单一 `CleanExit`；恢复失败追加诊断，不覆盖原始错误；
- `On Error Resume Next` 只允许在极小 `TryGet*` 包装内，并立即读取/清除错误。

Core 工具原则上不修改状态，因此状态变化默认为失败信号而非“自动修复一切”。

## 6. 错误和日志

```text
0  OK
10 CANCELLED
20 NOT_APPLICABLE
30 CAPABILITY_UNAVAILABLE
40 VALIDATION_FAILED
50 STATE_CHANGED
60 TOOL_FAILED
70 INTERNAL_ERROR
80 LIMIT_REACHED
90 UNKNOWN_COMMAND
```

Production 日志只记录 UTC、build/kit、request/tool、结果码、耗时、计数和通用文档类型；不记录用户名、
完整路径、文档名、对象名、PN、参数值或模型内容。日志写失败不能导致工具失败。日志目录、保留期和总量
属于 B28/企业策略待决项，不能在 A 环境直接宣称 `%ProgramData%` 或 `%LOCALAPPDATA%` 已获批准。

## 7. 工具行为

### 7.1 `core.healthcheck`

- 显示协议、构建和 kit 版本；
- 确认 VBA7/Win64 条件和 CATIA release 信息的可取得性；
- 报告活动文档通用类型和 Core 包状态；
- 不枚举 VBIDE References、不修改许可证、不声称识别当前 DSLS profile；
- 许可证/profile 信息由目标机证据工具和管理员记录提供。

### 7.2 `core.document-summary`

- 无文档时返回正常 `NOT_APPLICABLE`；
- 读取通用文档类型、保存/只读候选状态和有限统计；
- 文档名/路径只允许当前 UI 显示，不进入生产日志；
- 不 Update、不 Save、不打开其他文档、不清空 Selection。

### 7.3 第二回合审计

- Product：只遍历当前已加载树，不 `ApplyWorkMode`、不打开引用；
- Part：只读普通 Body/HybridBody 等结构，不测量、不访问 KWA/EKL、不 Update；
- Drawing：只读标准 CATDrawing Sheet/View/Table，不声明 Layout2D/LO1 类型；
- 默认最大节点 10,000、深度 128，超限返回 `LIMIT_REACHED`。

## 8. Debug 与 Production

- 编译时常量区分 Debug/Production，Production 不能运行时切换到 Debug；
- 两者都禁止 VBProject/CodeModule、Office、网络、Shell、SPA/FTA 和许可证修改；
- Debug 可增加阶段和协议诊断，但仍必须脱敏；
- VBE 工程保护只防误编辑，不作为完整性或保密控制。

## 9. 测试与验收

### A 环境

- 静态目录和 dispatcher 生成确定；
- 控件 Name 的合法性、唯一性和 40 字符上限有 golden tests；
- Core catalog 不含被排除模块/类型/API；
- 协议类型、大小、未知命令和错误码有测试；
- 每个 VBA 工具具有目标测试条目，但行为状态仍是 `NOT_RUN`。

### B28 首轮

- 空工程导入 Core，References 无 MISSING/B30/x86/Temp/用户路径；
- Compile、保存、关闭 CATIA、重启、再次 Compile；
- 无文档与 CATPart/CATProduct/CATDrawing 下启动菜单；
- P-AB3/P-HD2/P-MD2 分别执行两个首轮工具；
- 无 Office、断网、禁 PowerShell/WSH 时通过；
- 重复执行、错误、取消和跨文档切换不泄漏状态；
- Core 在 SPA/FTA 包缺失、损坏或 checkout 失败的专项测试中仍能启动。

只有上述证据完成后，才批准第二回合三个结构审计进入目标机构建。
