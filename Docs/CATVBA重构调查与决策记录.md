# CATVBA 重构调查与设计决策记录

> 文档性质：持续追加的调查、证据与决策台账
>
> 初版日期：2026-07-12
>
> 工作分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`
>
> 初版仓库快照：`def9ce212f7c19ac3c1a04bc7d22f151d9aac183`
>
> 目标环境：CATIA V5-6R2018（R28/B28）、VBA7 64 位 Windows
>
> 当前阶段：用户已书面确认恢复总架构与四份子规格；离线 Build Kit 实施计划已编写，等待选择执行方式；项目仍为 NO-GO，G0-G7 状态未因文档批准而提升

本文记录本轮重构开始前已经完成的调查过程、证据边界、独立复核结果和用户确认的设计决策。它不是“当前 CATVBA 已经修复”的证明，也不替代 R2018 目标机的编译、运行和许可证验收。

相关长文档：

- [当前分支深度审查报告](dev分支审查报告.md)：以源码增量、运行时缺陷和发布分支为重点；
- [CATIA V5-6R2018 / VBA7 64 位恢复、依赖与安全交付指南](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md)：以二进制、引用、许可证、目标机恢复和交付为重点。

---

## 1. 已确认的任务约束

| ID | 约束 | 对设计的直接影响 |
|---|---|---|
| RQ-01 | 当前工作区没有 CATIA | 本地只承担源码编写、静态分析、离线测试、清单生成、二进制审计和打包准备；不得声称已在 CATIA 中编译通过 |
| RQ-02 | 正式目标为 CATIA V5-6R2018 / VBA7 64 位 | 目标构建必须使用干净 B28 环境，不能继承现有 B30 References 或用 Office VBA 代替 CATIA 宿主验证 |
| RQ-03 | 正式目标每台至少有 AB3、HD2、MD2 中一种，并额外保证 SPA、FTA | 最小 profile 固定为 P-AB3/P-HD2/P-MD2，三者都包含 SPA+FTA；不能只测三种 base 同时存在的会话 |
| RQ-04 | Core 取三种最小目标 profile 的严格能力交集，但自身不得早绑定 SPA/FTA | 只有在 P-AB3、P-HD2、P-MD2 都通过，且没有 SPA/FTA Reference/API 污染的能力才可进入 Core |
| RQ-05 | 超出 Core 的能力必须隔离 | 部分基线配置可用的能力进入 Baseline Extensions；需要其他产品代码的能力进入 Licensed Optional |
| RQ-06 | 额外许可证能力必须提供风险与替代方案 | 每个可选包都要记录许可证证据、隔离方式、失败行为和无额外许可证的降级实现 |
| RQ-07 | 重构只针对个人工作分支 | 只写 `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`；不写 fork `main/dev` 或上游仓库 |
| RQ-08 | fork `main/dev` 镜像上游并会继续更新 | 初期保留现有 `Src` 平面文件结构，通过 namespaced overlay 与审定 intake 降低同步冲突 |

**DR-011 当前解释：** RQ-01 的“本地源码编写”不授权直接修改 upstream `Src/`；详细设计和
日期化计划获批后，本地实现只进入 `catvba_refactor/`。RQ-08 的“保留现有 `Src`”落实为
intake-only upstream mirror；显式整组件 override 和外部清单位于唯一 namespaced root。此处为后续
决策解释，不改写原始任务约束。

---

## 2. 证据分层与结论用语

本项目必须把“静态可见”与“CATIA 中已经可用”严格分开。

| 证据层 | 当前可取得 | 可以证明 | 不能证明 |
|---|---|---|---|
| E1 Git/文本源码 | 是 | 文件、模块、声明、调用链、危险 API、确定性 VBA 语言错误 | CATIA 类型库能否解析、目标宿主是否成功编译和执行 |
| E2 CATVBA OLE/CFB | 是 | 模块流、PROJECT 保护字段、References、签名流、内嵌源码、哈希 | CATIA 是否信任签名、p-code 是否能由第三方工具完全正确解释 |
| E3 仓库与发布流程 | 是 | 分支拓扑、工作流、预置二进制、发布树构造方式 | GitHub/企业环境中的最终审批和现场安装行为 |
| E4 官方资料 | 是 | VBA7、VBA 语言规则、产品代码和公开产品能力 | 客户实际 DSLS 权益、R2018 具体报价配置内容 |
| E5 R2018 目标机 | 当前没有 | Compile、References、UI、真实 API、许可证 checkout、重启后行为 | 尚未执行前不得推定 |

本文使用以下状态：

- **已确认**：由当前源码、二进制或可重复离线命令直接支持；
- **高可信推断**：证据链较完整，但仍需要目标 CATIA 最终确认；
- **待目标机验证**：没有 R2018/B28 或许可证 profile 就不能完成；
- **设计决策**：项目主动选择的边界，不表示底层 CATIA 能力已经验证。

---

## 3. 已完成的调查过程

### 3.1 仓库、分支与发布基线

已检查当前分支、HEAD、工作树、远端引用、根提交、merge-base、增量提交和发布工作流。记录快照为：

| 对象 | 快照 |
|---|---|
| 当前工作分支 | `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report` |
| 本文初版 HEAD | `def9ce212f7c19ac3c1a04bc7d22f151d9aac183` |
| fork `doylenehemiah6893-afk/Macro_menu:dev` | `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad` |
| fork `doylenehemiah6893-afk/Macro_menu:main` | `efbcb6e200d68089bfe7b6324daa75b0f177b6c8` |
| 工作树 | 初版写入前干净 |
| `main` 与 `dev` | 当前本地引用无共同祖先 |

已经隔离复现：现有发版说明使用 squash 后 `checkout --theirs -- .`，不会自动删除 `main` 独有路径，因此生成的发布树不等于 `dev` 的精确快照。详见[当前分支深度审查报告第 3.5、F-07](dev分支审查报告.md#35-隔离复现发布流程)。

这些 SHA 是本轮调查快照，不代表远端以后不会变化。后续每次同步都必须重新记录 fetch 时间、远端 SHA 和差异清单。

### 3.2 源码与资产清点

当前 `Src` 中有 77 个 VBA 文本模块：

| 类型 | 数量 |
|---|---:|
| `.bas` | 64 |
| `.cls` | 9 |
| `.frm` | 4 |
| `.frx` 配套文件 | 4 |

离线复核还确认：

- 77 个文本模块中 35 个存在活动的 `Option Explicit`，42 个缺失；
- 5 个模块可用严格 UTF-8 解码，72 个模块需要 CP936 回退；
- 4 组 FRM/FRX 文件配对存在；
- 当前没有自动化测试目录，`pytest --collect-only` 没有收集到测试；
- `.gitignore` 的 GBK/尾部反斜杠会使 `rg` 报无效 glob 和非法 UTF-8；
- `.gitattributes` 声明了自定义 diff/merge driver，但仓库内没有可移植的驱动配置。

编码事实要求构建链明确区分“仓库规范编码”和“CATIA 导入编码”。在没有验证 CATIA R2018 对 UTF-8 导入行为前，不能直接批量转码并假定 FRM/非 ASCII 字符不受影响。

### 3.3 主菜单和动态 UI 调用链

已追踪当前主路径：

```text
A00_Menu.CATMain
  -> KCL.GetApc / MSAPC.Apc.7.1
  -> ExecutingProject / VBComponents / CodeModule
  -> 解析模块中的 {GP}/{EP}/{Caption}
  -> cls_MnUI 组织分组
  -> Cat_Macro_Menu_View 动态创建页面和按钮
  -> Cls_allBTNEVT
  -> CATIA.SystemService.ExecuteScript 调用入口
```

另一路动态窗口由 `Cls_DynaWD` 读取模块 `%UI` 注释创建控件。两条路径都把生产运行依赖建立在读取自身 VBA 工程源码之上，与工程保护、VBIDE/MSAPC 可用性和企业安全策略直接冲突。

已确认菜单元数据扫描结果包含 49 个 `{GP:...}` 模块，其中 43 个组号有效；一个有效组模块的入口被注释，因此当前预期有效菜单入口为 42 个。该数字只表示静态入口映射，不表示入口能编译或运行。

### 3.4 确定性编译阻断

源码和独立复核均确认以下 6 处不依赖 CATIA 运行环境即可判定的编译阻断：

| ID | 位置 | 原因 |
|---|---|---|
| C01 | `Src/OTH_INSNAME.bas:87` | `Option Explicit` 下使用未声明变量 `purePN` |
| C02 | `Src/OTH_PrePn.bas:88` | 同上 |
| C03 | `Src/Cls_PDM.cls:85` | Class 的 Public Function 返回标准模块中定义的 Public UDT `Bomline` |
| C04 | `Src/Cls_PDM.cls:140` | Class 的 Public Function 返回 `Bomline()` |
| C05 | `Src/Cls_PDM.cls:212` | Class 的 Public Function 返回 `Bomline()` |
| C06 | `Src/Cls_XLM.cls:269` | Class 的 Public Sub 以 `Bomline()` 作为公共参数 |

`Bomline` 定义在 `Src/KCL.bas:20-33`。Microsoft VBA 的公共 UDT/Class 接口规则与 C03-C06 一致。移除污染引用后，SPA、Excel、Layout2D 和 Knowledgeware 的早绑定类型还会形成下一层包级编译问题，因此不能只修 6 行后重新生成一个包含全部模块的单体 CATVBA。

### 3.5 CATVBA 二进制取证

两个根目录 CATVBA 的本轮复核结果：

| 文件 | 大小 | SHA-256 | 模块数 | 定位 |
|---|---:|---|---:|---|
| `CATIA_V5_SimpleMacroMenu.catvba` | 4,161,536 B | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` | 77 | 历史正式候选；当前仅作 legacy evidence，状态 NO-GO |
| `CAT_menu.catvba` | 4,007,424 B | `1C8EC220F3D97F84D5404F24225938B2A8E2821D3F16BFEF5964E97023CA2FCA` | 72 | 旧分叉产物，不能作为可信回滚 |

已确认的二进制事实：

- 历史正式候选内嵌的 77 个规范化源码模块与当前 `Src` 对应，已确认的源码缺陷已经进入二进制；
- 历史正式候选还包含没有对应文本模块的旧设计器 storage，说明它不是干净空工程重建结果；
- PROJECT 存在 `CMG/DPB/GC` 工程保护字段，但 Microsoft MS-OVBA 明确把该机制定义为混淆而不是安全边界；
- 签名流没有发现可验证的证书/PKCS#7 负载，交付上必须按未签名处理；
- References 总量大且混入 B30、Office、VBA6/VBIDE x86、SysWOW64/临时目录等路径；
- 第三方工具报告可能存在 VBA stomping/p-code 不一致信号，但 CATVBA cache 的工具解释存在局限，不能据此直接判定恶意代码。

p-code 的正式结论必须来自：干净 B28 工程导入、Compile、保存、关闭宿主、重新打开、再次运行和重新提取审计。旧 cache 不进入信任链。

### 3.6 安全与可用性审查

已确认的主要风险域：

| 风险 | 代表位置 | 当前处理方向 |
|---|---|---|
| 运行时 VBA 工程自省/自修改 | `A00_Menu.bas`、`Cls_DynaWD.cls`、`Cls_VbaMdlMgr.cls` | 正式运行时移除，改为构建期静态目录；开发工具隔离 |
| CATIA 全局状态泄漏 | `KCL.CATquick` 及调用方 | 使用显式状态快照和所有出口恢复 |
| 静默吞错 | `Cls_allBTNEVT.cls` | 结构化结果、脱敏日志和用户可见失败 |
| 非事务式改名/复制/删除/保存 | 多个 Assembly/Part 工具 | 收集、全量验证、预览、提交、逆序回滚 |
| 外部命令与命令注入 | `ASM_1ex2stp.bas` | Core 禁止；压缩移出 CATIA，或只调用受管签名 helper |
| 网络数据外发 | `MDL_translateRename.bas`、KCL 外链 | Core 禁止；离线术语表或受管内网服务 |
| 许可证持久化修改 | `LicenseReset.catvbs` | 从正式交付排除；不得用 `SetLicense` 探测 |
| Office/可选 CATIA 类型污染 | Excel、SPA、Layout2D、FTA、KWA 等 | 物理分包，不允许进入 Core References |

静态扫描没有发现私钥、常见云密钥、下载后执行或持久化启动项，但这只表示当前规则没有命中，不能替代完整 FRX/目标宿主动态审计。

### 3.7 许可证调查

公开资料可以确认产品代码和产品能力方向，但 R2018 Licensed Program Specifications 把实际 configuration 内容留给产品组合/报价资料。历史配置矩阵可用于形成候选假设，不能代替客户 R2018 DSLS 权益和三个独立 profile 的现场验证。

当前许可证分类候选：

| 能力/API | 候选包 | 证据状态 | 无额外许可证降级；其他替代须注明权益 |
|---|---|---|---|
| 基础 Product/Part/CATDrawing、菜单基础设施 | Core candidate | 必须 P-AB3、P-HD2、P-MD2 均通过，且不早绑定 SPA/FTA | 不通过的具体功能移出 Core |
| 只在一或两个基线配置通过的能力 | Baseline Extension | 待三 profile 实测 | 入口可见但禁用并说明 profile，或采用更基础的数据/几何操作 |
| `SPAWorkbench`、`OptimizerWorkBench/PartComps`、测量 | Fleet-SPA | 正式目标保证 SPA，但具体 API/Reference 仍需 R2018 实测 | 树、PN、实例、数量、文件版本和普通属性比较；不宣称几何等价 |
| STEP 导出 | Optional-ST1 | 产品代码明确，需权益验证 | 无额外权益时保留原生 CATPart/CATProduct；外部转换端仍需 ST1 |
| `HybridShapeUnfold` | Optional-DL1 | 高可信映射，需实测 | 禁用自由曲面展开；不得把近似算法宣称为等价 |
| `Layout2DView` | Optional-LO1 | 产品能力明确 | 仅保留标准 CATDrawing 图框路径 |
| `Marker3Ds` | Optional-DMN | 高可信映射，需实测 | UserRefProperties、CSV 或普通 Drawing 文本 |
| `AnnotationSets/CreateFlagNote` | Fleet-FTA | 正式目标保证 FTA，但具体 API/Reference 仍需实测 | UserRefProperties、普通 CATDrawing 文本或待实现 CSV；不保留语义标注等价性 |
| `CreateProgram/CreateFormula` | Optional-KWA | 产品能力明确，配置包含关系待验证 | VBA 即时计算并写普通属性；失去关联更新 |
| Excel Workbook/Range/Shape | External Integration | 非 CATIA 许可证；属于额外部署与安全依赖 | CSV/TSV 是待实现的正式降级，不是当前已有能力 |

上述表格描述目标边界，不表示当前源码已经隔离。当前至少存在五条会污染 Core 编译边界或阻止物理分包的依赖：

1. `Src/KCL.bas:46` 声明 `Public pdm As New Cls_PDM`；`RW_3initme:10-49` 经 `Cls_PDM.initPrd/iniPrt` 自动调用 `ApplyEngineeringLogic/CreateProgram/CreateFormula`。需要把入口拆为基础初始化和 Optional-KWA writer，不能只取消全局单例；
2. `Src/KCL.bas:43-47` 声明 Excel 全局对象和 `Public xlm As New Cls_XLM`；`Cls_XLM` 又持有 `Cls_WsEvt` 并早绑定 `Workbook/Range/Shape`。`DRW_VIewBOM` 只有 `AsmConv2xl:87-110` 属于 Excel，不能整模块迁移；`ZZ_BCK` 的无菜单 Excel 遗留代码不发布；
3. `Src/KCL.bas:1261-1276` 的 `GetMeas/getlength` 直接取得 `SPAWorkbench`，SPA helper 仍位于共享工具模块；
4. `Src/Drw_myframe.bas` 和 `Src/Drw_myframe2.bas` 都混合普通 CATDrawing 与 `CAT2DL_ViewLayout/Layout2DSheet/LAY/Layout2DView` 路径，LO1 不是现成可关闭的旁路；
5. `Src/OTH_3Dmark.bas` 的 DMN 和 FTA 过程同处一个标准模块，物理分成两个 CATVBA 前必须先拆模块；DMN 路径对 `Cls_PDM.getBomLine/Bomline` 的依赖还要改为 Core-safe DTO/reader。

首轮物理拆包必须先切断这四条依赖，再讨论把模块分配到不同 staging。仅隐藏菜单按钮或在入口处检查许可证，不能解决 VBA 工程级编译污染。

禁止通过 `SetLicense(..., False)`、自动勾选或修改 Licensing Repository 来验证能力。能力门禁必须分别记录：类型库可编译、API/工作台可取得、DSLS 有权益、当前会话实际 checkout。

### 3.8 离线测试现状

当前仓库没有可收集的自动化测试，因此“离线可测试”仍是目标而不是现状。当前已经完成的是静态规则和二进制取证；尚未形成版本化、可在 CI 中重复执行的测试套件。

离线工具未来至少要覆盖：

- 模块、VB_Name、FRM/FRX 配对和编码清单；
- `Option Explicit`、未声明变量启发式检查和 64 位 Declare 规则；
- `{GP}/{EP}/%UI` 标签、入口、回调、对象 Name 合法性和唯一性；
- 包归属、Core 引用允许清单和危险 API 策略；
- 生成静态菜单/UI 目录；
- CATVBA 源码、模块、FRX、References、签名流、哈希和构建元数据审计。

---

## 4. 风险台账

| ID | 风险 | 严重度 | 当前状态 | 放行条件 |
|---|---|---:|---|---|
| RK-01 | 当前 CATVBA 不能在目标环境可信使用 | P0 | 已确认 NO-GO | 干净 B28 重建、Compile、重启和完整审计 |
| RK-02 | 6 个确定性源码编译阻断 | P0 | 已确认 | 离线回归 + CATIA 全工程 Compile 零错误 |
| RK-03 | 单体工程被可选 References/许可证拖垮 | P0 | 已确认架构风险 | Core 和可选能力物理分包，References 白名单 |
| RK-04 | 工程保护与运行时源码扫描冲突 | P0 | 已确认设计冲突 | 静态 manifest；生产运行不访问 VBProject/CodeModule |
| RK-05 | 破坏性业务过程无事务和回滚 | P1 | 已确认 | 预检、预览、提交、逆序回滚、脱敏日志和副本测试 |
| RK-06 | 许可证归属被类型库存在所误判 | P1 | 已确认方法风险 | 三 profile + 四层能力证据记录 |
| RK-07 | p-code/cache 可信度不足 | P1 | 待目标机验证 | 干净重建、重启后复测和二进制复审 |
| RK-08 | `main/dev` 无共同历史造成发布/同步漂移 | P1 | 已确认 | 后续批准精确快照/同步治理设计并自动验证树哈希 |
| RK-09 | 无测试和发布证明 | P1 | 已确认 | 离线测试、目标机测试包、哈希、构建元数据和审批证据 |
| RK-10 | 共享 KCL 反向依赖 Cls_PDM/Cls_XLM 并内含 SPA helper；LO1、DMN/FTA 仍混合模块 | P0 | 已确认 | 先切断 KWA/Excel/SPA 反向依赖，抽取 LO1 adapter，拆分 DMN/FTA 与 Core-safe DTO，再生成 Core staging |

---

## 5. 已批准的设计决策

### DR-001：采用源码优先、分包渐进重构

**状态：已批准，2026-07-12。**

比较过三种路线：

1. 原地修补单体 CATVBA；
2. 源码优先、静态生成、物理分包、干净 B28 重建；
3. 外部 COM/CAA/Add-in 重写。

选择路线 2。原因是它能同时处理编译、引用、许可证、安全和远端同步问题，又能保留现有 VBA 业务逻辑逐步迁移。路线 1 只适合作为短期诊断；路线 3 可作为未来演进，但当前部署和重写成本过高。

### DR-002：Core 使用严格交集

**状态：交集原则已批准，2026-07-12；旧 profile 命名于 2026-07-13 被 DR-013 取代。**

当前定义：

```text
Core = Verified(P-AB3) ∩ Verified(P-HD2) ∩ Verified(P-MD2)
```

其中三个最小 profile 都包含 SPA+FTA，但 Core 自身仍不得早绑定 SPA/FTA 类型、Reference 或 API。

准入必须同时满足：

- 在三种 profile 各自独立环境中 References 无缺失；
- 全工程 Compile；
- 启动、入口执行、取消、失败和重复执行均通过；
- 不依赖 Office、网络、PowerShell、WSH、VBIDE/MSAPC 或额外 CATIA 产品；
- 操作结束后 CATIA 全局状态与进入前一致；
- 测试证据绑定到 R2018 SP/HF、DSLS profile、Git SHA 和构建物哈希。

任一 profile 未通过，功能就不能进入 Core。三个许可证同时存在时通过，不足以证明属于 Core。

### DR-003：增加 Baseline Extensions 层

**状态：已批准，2026-07-12；profile 组成以 DR-013 为准。**

对属于 AB3/MD2/HD2 并集、但不属于严格交集的能力，不错误标记为“额外许可证”，也不塞进 Core。它们按能力形成 Baseline Extension，并记录三 profile 的实测矩阵。

### DR-004：源码和 manifest 是真源

**状态：已批准，2026-07-12。**

- 文本源码、包清单、能力清单和生成规则是版本化真源；
- CATVBA 是从审定真源生成的派生产物；
- 现有两个 CATVBA 冻结为遗留证据，不再原地修补；
- 生成的菜单目录、UI schema 和 dispatcher 不手工编辑。

### DR-005：运行时禁止读取或修改自身源码

**状态：已批准，2026-07-12。**

现有 `{GP}/{EP}/%UI` 注释可以暂时保留为作者输入格式，但必须在构建期解析、校验并生成静态代码。生产运行时不访问 `VBProject`、`VBComponents` 或 `CodeModule`。

### DR-006：物理包边界采用 fail-closed

**状态：物理隔离原则已批准，2026-07-12；SPA/FTA 的默认 Fleet 地位于 2026-07-13 被 DR-013 细化。**

```text
MacroMenu.Core.catvba
MacroMenu.Baseline-<Capability>.catvba
MacroMenu.Fleet-SPA.catvba
MacroMenu.Optional-ST1.catvba
MacroMenu.Optional-DL1.catvba
MacroMenu.Optional-LO1.catvba
MacroMenu.Optional-DMN.catvba
MacroMenu.Fleet-FTA.catvba
MacroMenu.Optional-KWA.catvba
MacroMenu.Optional-Excel.catvba
MacroMenu.DevTools.catvba            # 永不进入普通用户正式发布
```

Core 不早绑定可选类型，也不建立跨 CATVBA VBA Project Reference。可选包缺失、证据不足或能力检查失败时，入口保持可见但禁用，并显示缺失包、profile、能力或兼容性原因。少量公共运行时代码由构建工具复制到各包的 staging，避免跨工程引用成为新的单点故障。

### DR-007：本地只生成不可变 Build Kit

**状态：已批准，2026-07-12。**

- 当前无 CATIA 的工作区只负责清点、静态校验、目录生成、分包 staging、测试、哈希和回传审计；
- `Src` 首阶段不移动、不批量转码，读取时严格尝试 UTF-8 后回退 CP936，既有源码和 FRX 原字节复制到 staging；
- 只有生成的 VBA 模块使用待 B28 确认的 CP936/CRLF，生成物不进入 `Src`，也不构成源码真源；
- Build Kit 由规范化输入和工具版本形成稳定 `kit_id`，使用不可变目录、完整哈希和完成标记；失败不留下可误用的半成品；
- 本地最高状态是 `KIT-READY`，不得把离线通过描述为“CATIA 编译通过”或“可发布”；
- 正式 CATVBA 必须在干净 R2018/B28 构建机从空工程导入、Compile、保存、重启和三 profile 验收后生成。

DR-007 只批准上述职责边界；manifest schema、CLI/API、错误码、生成器细节和运行时协议仍属于待书面复核的设计内容。

### DR-008：首个目标机里程碑采用范围 B

**状态：已批准，2026-07-12；具体只读工具清单待下一节确认。**

首个交给 R2018/B28 的 Build Kit 包含可信基础壳和少量低风险只读工具。首轮明确排除写模型、删除、改名、复制、保存/导出、网络、Shell、PowerShell/WSH、Office 和额外许可证能力。只读工具不得调用 `ApplyWorkMode`、加载未打开引用、清空 Selection 或改变 CATIA 全局状态。

### DR-009：阶段性文档检查点是交付要求

**状态：已批准，2026-07-12。**

- 每个设计节确认后更新本决策台账；
- 每个实现阶段开始和结束时记录输入 SHA、范围、测试命令/结果、未决风险和下一动作；
- 每批子代理结束后先把采用的结论和被拒绝的冲突建议写入文档，再进入下一批；
- 每次吸收 `verysolecd/Macro_menu:dev` 前后记录 old/new SHA、冲突、选择性处理和验证结果；
- 每个 Build Kit、B28 构建和许可证 profile 会话生成不可覆盖的 kit/build/evidence 记录；
- 对话或上下文摘要只用于导航，仓库文档、Git 提交和不可变证据才是持续工作的真源。

### DR-010：采用本地 Overlay 与统一文档入口

**状态：已批准，2026-07-13。**

- 首阶段保留 `Src/`、`resources/`、根目录遗留 CATVBA、`ref_project/`、`DrawFunc/` 和 `artifacts/` 的物理位置，不做批量搬迁、重命名或转码；
- 本地逐步新增 `config/`、`schemas/`、`macro_build/`、`tests/`、忽略的 `build/`/`dist/`，由 manifest 覆盖遗留平面源码；
- 文档入口统一为 `README.md` → `Docs/README.md` → `Docs/STATUS.md`，历史材料只加状态/勘误，不改写原证据；
- `verysolecd/Macro_menu:dev` 是逻辑代码上游；fork `main/dev` 只镜像对应上游，个人工作分支经审定 intake 吸收变化；
- Overlay 批准不等于其 schema、CLI、运行时或五个 Core 候选工具已批准，也不授权当前生成候选 CATVBA。

**后续修订：** DR-011 保留 DR-010 的 Overlay 与零搬迁原则，但取代其“根级新增六个目录”的物理
放置方式；这些目录统一收进 `catvba_refactor/`。

### DR-011：唯一命名空间、上游镜像和显式整组件 Override

**状态：方向已批准，2026-07-13；精确 manifest schema、错误码和 intake record 仍待详细 spec 书面复核。**

- `Src/` 与 `resources/` 只由 `verysolecd/Macro_menu:dev` 的审定 intake 更新；本地重构、修复、格式化、转码和生成器不得直接写入；
- 除既有 `README.md`、`Docs/`、`.gitignore`、`.gitattributes` 等治理例外外，所有新增实现只进入 `catvba_refactor/`；
- 本地新增组件位于 `catvba_refactor/vba/new/<source-id>/`；遗留组件修改使用
  `catvba_refactor/vba/overrides/<source-id>/` 的完整组件副本；FRM/FRX 必须成对；
- override 必须显式绑定 upstream path、Git blob OID、原始 SHA-256、组件类型和 `VB_Name`；任何
  upstream 漂移都使 binding 过期并 fail-closed，禁止静默使用新版 upstream 文件；
- 配置、schema、Python 工具源码、测试、build 和 dist 全部位于同一 namespaced root；根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 项目/锁/版本真源，不在命名空间内复制；
- candidate 从固定 Git blobs 构建，不把 clean worktree 当成原始字节证明；
- intake 与新的业务功能不得混在同一提交；上游改变 override base 时必须人工退役、重新实现、重绑或 Quarantine；
- upstream 若创建 `catvba_refactor/**`、产生 Windows portable path 冲突或破坏 FRM/FRX 配对，intake 立即阻断。

未采用的方案：

- 同名路径阴影覆盖会静默隐藏上游变化；
- fuzzy Git patch 对 rename、编码和 FRM/FRX 不确定；
- 根级 `config/`、`tests/` 等仍可能与未来 upstream 撞路径。

DR-011 细化 DR-004 的“文本源码”：它是 upstream cutoff blobs 与 namespaced local components 的组合，
不是允许直接修改 `Src/`。本轮历史核对 `verysolecd/Macro_menu:dev@abce8ff` 与当时 `Src/`、`resources/` 差异均为 0；该结论只绑定该 cutoff。

---

### DR-012：固定仓库拓扑与唯一根 Python 项目

**状态：方向已批准，2026-07-13；实现尚未开始。**

- 逻辑开发上游固定为 `verysolecd/Macro_menu:dev`，逻辑发布上游为 `verysolecd/Macro_menu:main`；
- fork 的 `doylenehemiah6893-afk/Macro_menu:main,dev` 只镜像对应上游，不承载个人重构；
- 唯一重构写分支为 `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`；
- 规格、证据和工具输出必须记录完整仓库/分支/commit/tree，不把本机 `origin/upstream` remote 名称当权威身份；
- 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python 依赖与运行环境真源；
- `catvba_refactor/` 保存实现源码、配置、schema、测试和派生输出，但不得建立第二套 Python project/lock；
- 正式 Build Kit 只接受干净、已提交的 candidate tree；worktree 模式只做诊断，不能生成正式 snapshot 或 Kit。

### DR-013：正式许可证模型与 Fleet-SPA/Fleet-FTA

**状态：用户条件已确认，2026-07-13；B28 实测仍未执行。**

正式目标资格定义为：

```text
Eligible = (AB3 OR HD2 OR MD2) AND SPA AND FTA
```

- 最小验收 profile 为 P-AB3、P-HD2、P-MD2，三者分别只含一种 base configuration，并都含 SPA+FTA；
- P-ALL 与现场实际 P-PROD 只作补充，不能替代三个最小 profile；
- Core 必须在三个最小 profile 都通过，同时不建立 SPA/FTA 早绑定 Reference、类型或启动依赖；
- SPA 与 FTA 是正式 Fleet 默认交付能力，但分别进入 `MacroMenu.Fleet-SPA.catvba` 与
  `MacroMenu.Fleet-FTA.catvba`，独立构建、Reference、证据、加载和故障隔离；
- Fleet-SPA 或 Fleet-FTA 缺失/加载/checkout 失败时，Core 和另一扩展必须可继续启动；但完整 Fleet
  release-set 的对应门禁不得 PASS；
- ST1、DL1、LO1、DMN、KWA 等仍是 CATIA Licensed Optional Candidate；Excel/网络/外部 COM 属于
  External Integration，不以 CATIA 许可证包表述；
- 旧文档中的 AB3-only/HD2-only/MD2-only 与 Optional-SPA/Optional-FTA 只保留为历史术语，当前设计
  一律以本决策为准。


### DR-014：批准总架构与四份子规格

**状态：已批准，2026-07-13。**

用户已书面确认以下设计：

1. `2026-07-13-catvba-r2018-recovery-design.md`；
2. `2026-07-13-catvba-offline-build-kit-design.md`；
3. `2026-07-13-catvba-core-runtime-mvp-design.md`；
4. `2026-07-13-catvba-b28-validation-delivery-design.md`；
5. `2026-07-13-catvba-upstream-intake-design.md`。

该批准使设计状态从 DRAFT 变为 APPROVED，并授权编写分阶段实施计划；它不等于已经执行计划、生成
Build Kit/CATVBA、完成 CATIA Compile 或通过任何许可证/发布门禁。第一份计划只覆盖 A 环境离线
Build Kit 工具链，见 [`2026-07-13-catvba-offline-build-kit.md`](superpowers/plans/2026-07-13-catvba-offline-build-kit.md)；Core Runtime、B28/Fleet 验证和 intake 执行继续使用各自独立计划。开始实现前仍需选择 Subagent-Driven 或 Inline Execution。

---

## 6. 已批准的总体架构边界（DR-013 后）

```text
verysolecd/Macro_menu:dev@cutoff Src/resources blobs
                    +
doylenehemiah6893-afk/Macro_menu:codex/dev-review-report
  catvba_refactor/{vba,config,schemas,macro_build,tests}
                    +
repo root pyproject.toml / uv.lock / .python-version
                    |
                    v
          fail-closed source resolver
                    |
                    v
 Core        Fleet-SPA       Fleet-FTA       Other candidates
   |              |               |                 |
   +--------- immutable Build Kit / evidence -------+

DevTools / Quarantine 与正式发布完全分离
现有 CATVBA 仅作为 legacy evidence
```

Core 内可以按 Assembly、Part、Drawing 组织代码和菜单，但这些业务名称本身不构成许可证证明。每个具体工具都必须单独通过严格交集门禁。

依赖方向：

- Core 可以读取“某扩展已由受管安装器部署”的静态安装清单；
- Core 只能通过一个稳定、可记录错误的执行边界按需调用扩展；
- Core 启动不能加载扩展，也不能引用它们的类型；
- 工具目录至少要能定位 `package_id/library_id/minimum_version/call_kind`；目标机构建完成后的安装清单再记录受管路径和 CATVBA SHA-256，具体 schema 在下一设计节确认；
- 扩展对 Core 只有版本化的逻辑契约依赖，公共 DTO/结果/日志代码在构建期复制或以纯 Variant/字符串跨入口传递，不引用 `KCL/Cls_DynaWD` 内部实现；
- 扩展不能隐式要求另一扩展存在；确有组合能力时必须声明组合包并单独验收；
- DevTools 不能被正式 Core 或扩展业务包引用。

---

## 7. 已批准后仍待执行或现场确认的内容

1. 离线 Build Kit 实施计划已编写，等待选择执行方式，尚未创建真实 manifest/schema/Python 实现；
2. Core Runtime、B28/Fleet 和 upstream intake 需要各自日期化实施计划；
3. Production 安装根、宏库注册和跨 CATVBA 调用仍由 B28 spike/现场证据确认；
4. 危险操作事务模型、现场调试版与正式版差异继续留在后续安全计划；
5. 在 G0-G7 对应证据完成前，不得把设计批准描述为 CATIA、许可证、试点或发布通过。

设计批准是实施输入，不是运行证据。

---

## 8. 目标机必须回传的证据包

每次 R2018 构建或现场调试至少保存：

- Windows 版本、CATIA R2018 SP/HF、VBA/VBE 版本；
- P-AB3、P-HD2、P-MD2 profile 的建立方式，AB3/HD2/MD2 与 SPA+FTA 的 DSLS checkout 记录；
- `Tools > References` 清单、GUID、版本、解析路径和 `MISSING:` 状态；
- `Debug > Compile` 结果；
- 首次启动、关闭 CATIA 后重启、重复启动的结果；
- 无 Office、网络阻断、PowerShell/WSH 禁用时的 Core 结果；
- CATPart、CATProduct、CATDrawing、无文档、只读和未保存文档矩阵；
- 每个功能的 package/capability/profile 结果；
- CATIA 状态进入值、退出值和异常恢复结果；
- 规范化源码、FRX、References、CATVBA 的哈希；
- Git commit/tree、构建日志、测试报告和发布审批记录。

现场日志必须脱敏，不记录客户模型名称、完整文件路径、零件号或设计内容，除非项目数据治理明确允许。

---

## 9. 参考依据

- [Microsoft：64 位 VBA 的 PtrSafe、LongPtr 与 Win64](https://learn.microsoft.com/zh-cn/office/vba/language/concepts/getting-started/64-bit-visual-basic-for-applications-overview)
- [Microsoft：Missing project or library 会阻止 VBA 运行](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/can-t-find-project-or-library)
- [Microsoft：Class 公共接口不能暴露标准模块 Public UDT](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/only-public-user-defined-types-defined-in-public-object-modules-can-be-used-as-p)
- [Microsoft MS-OVBA：工程 Encryption 是 obfuscation，不是 security](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ovba/b5bb7e87-c7a2-4cd2-99e9-c54e8282c155)
- [Dassault Systèmes：V5-6R2018 Licensed Program Specifications](https://www.3ds.com/assets/Terms/LicensedProgramSpecifications/V5%20PLM/V5-6R2018.pdf)
- [Dassault Systèmes：V5 产品代码公开表](https://www.3ds.com/assets/invest/2024-02/eccn-february-2024.pdf)
- 具体 SPA/ST1/DL1/LO1/DMN/FTA/KWA 链接见[恢复与依赖指南第 19 节](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md#19-参考资料)。

---

## 10. 修订记录

| 日期 | 变更 |
|---|---|
| 2026-07-12 | 建立调查与决策台账；记录已完成审计、方案 2、严格 Core 交集和 Baseline Extensions 决策 |
| 2026-07-12 | 确认离线 Build Kit 边界、首个里程碑范围 B 和阶段性文档检查点 |
| 2026-07-13 | 以 DR-011 将所有本地实现收进 `catvba_refactor/`，把 `Src/` 定义为 intake-only upstream mirror，并采用显式整组件 override |
| 2026-07-13 | 以 DR-012 固定完整仓库拓扑、唯一工作分支和唯一根 Python project/lock |
| 2026-07-13 | 以 DR-013 确认 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`，并将 SPA/FTA 改为默认但物理隔离的 Fleet 包 |
| 2026-07-13 | 以 DR-014 记录用户批准恢复总架构和四份子规格，并进入离线 Build Kit 实施计划阶段 |
