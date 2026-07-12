# CATIA V5-6R2018 / VBA7 64 位恢复、依赖与安全交付指南

> 审查日期：2026-07-11
>
> 审查分支：`codex/dev-review-report`
>
> 审查快照：`c584202`
>
> 目标环境：CATIA V5-6R2018（R28/B28）、DS VBA 7.1、64 位 Windows，许可证基线 AB3 / MD2 / HD2
>
> 当前结论：**NO-GO。现有 CATVBA 不能作为 R2018 正式产物继续安装或分发。**

本文是针对“CATIA 中编译报错、CATVBA 工程保护、R2018 可用性与安全性存疑、当前无法使用”的专项恢复文档。通用分支审查见 [dev 分支审查报告](dev分支审查报告.md)。本文没有修改业务源码，也没有声称已经在 R2018 中完成编译；它给出已核实的根因、依赖、许可证边界、恢复架构、实机步骤和验收门槛。

---

## 1. 结论先行

当前“无法使用”不是一个 DLL 或一个语法错误造成的，而是至少五个相互独立的阻断叠加：

1. **发布二进制来自错误的 CATIA 代际。**正式 CATVBA 有 105 个直接 References，其中 89 个绝对路径固定到 `Dassault Systemes\B30`；目标 R2018 是 B28。Microsoft 明确说明，只要存在 MISSING 引用，VBA 就不能运行代码。
2. **源码本身存在必然编译错误。**已确认 2 处 `Option Explicit` 下未声明变量，以及 4 个类公共接口非法暴露标准模块 UDT；解决引用后仍会继续报错。
3. **“工程加锁”与核心运行机制互相冲突。**CATVBA 被 VBE 保护，但主菜单和动态 UI 必须在运行时读取自身 `VBComponents/CodeModule` 注释；锁定状态或企业禁用 VBA 工程对象模型访问时，主路径可能直接失败。
4. **菜单即使编译，也会在创建 UI 时失败。**页面和控件把 `R&W`、`3`、`4` 等业务标识直接用作 MSForms `Name`，不符合对象名规则。
5. **所有 77 个模块被装进一个工程。**Excel、SPA、Layout2D、FTA、STEP、DL1 等任一可选域的缺引用或编译错误，都能拖垮整个菜单；项目没有许可证/能力门禁。

因此，不建议通过“在 R2018 机器继续安装各种旧 DLL”来救活当前 CATVBA。正确路线是：

```text
仓库源码
  -> 修复确定性编译错误
  -> 构建期生成静态 Menu/UI manifest
  -> 按 Core / Assembly / Part / Drawing / Optional 拆包
  -> 在干净 R2018/B28 构建机创建新 CATVBA
  -> 只绑定 B28 白名单引用
  -> Compile + 重启 + 冒烟 + 三许可证矩阵
  -> 源码/FRX/引用/p-code 核验
  -> 签名或受管安装 + SHA-256 + 可回滚发布
```

首个可用版本的目标不是“一次恢复 77 个模块”，而是交付一个在无 Office、无网络、无 PowerShell、无 VBE 自省时仍可运行的最小 Core，再逐包恢复业务能力。

---

## 2. 审查范围、方法与证据边界

### 2.1 已做的核实

- 全量阅读 `Src` 下 64 个 `.bas`、9 个 `.cls`、4 个 `.frm` 及 4 个 `.frx` 的结构和关键调用链。
- 检查两个 CATVBA 的 OLE/CFB 结构、PROJECT 元数据、保护字段、签名流、模块流和直接 References。
- 按 MS-OVBA 解压正式 CATVBA 内 77 个模块源码并与 `Src` 对照。
- 检查 Windows API `Declare`、早绑定类型、COM ProgID、文件/网络/外部进程、自修改、许可证修改和发布链。
- 独立核对仓库内 `artifacts` 文档；其中架构描述可作参考，但若与当前文件或二进制冲突，以当前分支和二进制取证为准。
- 查阅 Microsoft、Dassault Systèmes、CATIA V5 帮助及 Git 官方资料。

### 2.2 当前环境不能证明的事项

当前审查机没有 CATIA V5-6R2018/B28，不能在本机完成以下动作：

- 打开 VBE 的 `Tools > References` 并记录实际 `MISSING:` 顺序；
- 执行 `Debug > Compile CAT_MENU`；
- 在加锁状态下复现 `A00_Menu.CATMain` 的首个 CATIA/MSAPC 错误号；
- 验证 AB3、MD2、HD2 各自单独启用时的工作台/API 能力；
- 验证正式 SP/HF、Windows 版本和企业安全策略下的行为；
- 对 FRX 设计器对象、p-code/PerformanceCache 做最终一致性判定。

这些不是可忽略的尾项，而是正式放行前必须在目标机完成的验收。本文会明确区分“已经静态/二进制证实”和“必须实机验证”。

---

## 3. CATVBA 二进制取证

### 3.1 正式与旧产物

| 文件 | 大小 | SHA-256 | 模块 | 结论 |
|---|---:|---|---:|---|
| `CATIA_V5_SimpleMacroMenu.catvba` | 4,161,536 B | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` | 77 | 当前正式文件，但不可用于 R2018 生产 |
| `CAT_menu.catvba` | 4,007,424 B | `1C8EC220F3D97F84D5404F24225938B2A8E2821D3F16BFEF5964E97023CA2FCA` | 72 | 旧且分叉，不能作为回滚产物 |

正式 CATVBA 的 77 个模块与 `Src` 名称 77/77 对应；规范化比较中 64 个完全一致，另 13 个仅有 Class/UserForm 导出隐藏元数据差异，业务代码一致。因此本文列出的 `purePN`、UDT、菜单命名、`IIf`、Selection 等缺陷，已经进入正式二进制，不是“只存在于尚未发布文本源码”的风险。

旧 `CAT_menu.catvba` 只有 72 个模块：相对当前 `Src` 缺 9 个现模块、另含 4 个旧模块名，且只有少数模块与当前业务代码一致。它不能承担回滚。

### 3.2 工程保护不是源码加密

两个 CATVBA 均有：

- `CMG` 解码值 `0x00000004`：`fVBEProtected = True`；
- `DPB` 非空：存在工程密码哈希；
- `GC = 0xFF`：工程可见；
- 两者使用同一弱口令哈希；有界常见口令核验已证明口令强度不足。

Microsoft MS-OVBA 规范明确说明，这套所谓 Encryption 的设计目标是 **obfuscation，而不是 security**。本次也在不知道工程口令的前提下完整提取了 77 个源码流。结论是：

- 它只能减少误编辑，不能提供源码保密；
- 它不证明发布者身份；
- 它不证明文件没有被篡改；
- 它不能替代代码签名、受管安装、ACL 和哈希清单；
- 当前口令应视为已失效，且不得在其他系统复用。

### 3.3 没有有效数字签名证据

两个文件的 `VBA Project Signature` 流均只有 10 字节：

```text
CD010400000000000000
```

其值为零，未发现证书、PKCS#7 或 `MsoDigitalSignatureEx` 负载。应按“未签名”管理，除非 R2018 实机的 VBE/证书链校验能给出相反证据。

Microsoft 的 VBA 签名文档适用于 Office 宿主，不能直接假定 CATIA R2018 会以相同方式验证。建议在 R2018 试点机确认 VBE 是否提供 `Tools > Digital Signature`、保存后签名流是否出现、目标机是否真正阻止未知发布者。如果 CATIA 不能可靠验证，则使用企业签名 MSI/软件分发、只读安装目录、SHA-256 清单和构建证明补足。

### 3.4 p-code 边界

正式 CATVBA 存在 `_VBA_PROJECT`、`__SRP_*` 和 PerformanceCache。源码流一致不自动证明 p-code 一致。最终构建必须：

1. 在干净 R2018/B28 工程从源码重新导入并 Compile；
2. 保存、关闭 CATIA、重新打开后再次运行；
3. 离线提取源码、FRX、引用和 p-code；
4. 若工具无法可靠解释 R2018 cache，则以干净重建 + 重启重编译作为信任根，不继续继承旧 cache。

---

## 4. 为什么 R2018 首先会报引用/编译错误

### 4.1 105 个直接 References，89 个固定到 B30

按 MS-OVBA 的 `REFERENCE` 记录解析，两个 CATVBA 的直接引用集合相同：

- 105 个逻辑直接 References；
- 其中 104 个 `REFERENCEREGISTERED`、1 个 MSForms `REFERENCECONTROL`；
- 89 个路径固定为 `C:\Program Files\Dassault Systemes\B30\win_b64\code\bin\...`；
- 16 个非 CATIA 引用；
- `PROJECTSYSKIND = 3`（64 位 Windows），代码页 936。

目标 CATIA V5-6R2018 是 R28/B28。不能通过把 B30 TLB 复制到 B28、手工 `regsvr32` 或同时安装 B30 来修复；这会把构建环境和运行环境进一步混合。应在只安装 B28 的干净 VM 中创建全新 CATVBA，并从 VBE 重新选择 B28 的实际类型库。

绝对路径是严重的构建来源和可移植性证据，但不表示 89 项在每台 B28 机器上都会逐项 MISSING：若 GUID/版本兼容且 B28 已正确注册，VBA 可能重新解析其中一部分。最终以目标机 `Tools > References` 的实际 `MISSING:` 和解析路径为准；无论能否自动重绑，105 个大而杂的引用集合都不符合可控交付要求。

Microsoft 对 `Can't find project or library` 的说明是：只要引用缺失，代码就不能运行；不需要的引用应取消，需要的引用必须绑定到目标平台的正确对象库。

### 4.2 已确认的 6 处必然源码编译错误

| ID | 位置 | 编译原因 | 最小修复 | 长期修复 |
|---|---|---|---|---|
| C01 | [OTH_INSNAME.bas:87](../Src/OTH_INSNAME.bas#L87) | `Option Explicit` 下使用未声明 `purePN` | 声明并明确赋值/删除错误引用 | 用纯函数返回规范化 PN，并加用例 |
| C02 | [OTH_PrePn.bas:88](../Src/OTH_PrePn.bas#L88) | 同上 | 同上 | 同上 |
| C03 | [Cls_PDM.cls:85](../Src/Cls_PDM.cls#L85) | Class 的 Public Function 返回标准模块 UDT `Bomline` | 若仅工程内部使用，改为 `Friend` | 把 `Bomline` 改为 `Cls_BomLine` 类 |
| C04 | [Cls_PDM.cls:140](../Src/Cls_PDM.cls#L140) | Public Function 返回 `Bomline()` | 改 `Friend` | 类集合/DTO |
| C05 | [Cls_PDM.cls:212](../Src/Cls_PDM.cls#L212) | Public Function 返回 `Bomline()` | 改 `Friend` | 类集合/DTO |
| C06 | [Cls_XLM.cls:269](../Src/Cls_XLM.cls#L269) | Public Sub 参数是 `Bomline()` | 改 `Friend` | 类集合/二维 Variant 边界 |

Microsoft 对该 UDT 编译错误的定义与这里完全匹配：标准模块中的 Public UDT 不能直接作为 Class 公共过程的参数或返回值。

### 4.3 消除引用后会出现的下一层错误

- [ASM_CMP.bas:14-15](../Src/ASM_CMP.bas#L14) 早绑定 `OptimizerWorkBench` / `PartComps`；移除 `SPATypeLib` 后会出现 `User-defined type not defined`。该模块应进入 SPA 可选包，不能污染 Core。
- [Cls_WsEvt.cls:10](../Src/Cls_WsEvt.cls#L10) 早绑定 Excel `Workbook`；[Cls_XLM.cls:299-300](../Src/Cls_XLM.cls#L299) 早绑定 `Range` / `Shape`。不装 Excel 时全工程会被拖垮。
- [Drw_myframe.bas:680](../Src/Drw_myframe.bas#L680) 早绑定 `Layout2DView`；即使只想使用普通 CATDrawing 图框，也会要求 Layout2D 类型库。
- [OTH_Minibox.bas:249](../Src/OTH_Minibox.bas#L249) 和 `:458` 早绑定 `Length`，需要 Knowledgeware 类型库。
- 当前 77 个模块中只有 34 个声明 `Option Explicit`，43 个没有。把门禁补齐后还会暴露更多未声明变量；这应按功能包逐步完成，不能一次盲目全开后不处理新增错误。

### 4.4 VBA7/64 位声明结论

项目中的活动 Windows API `Declare` 基本已使用 `PtrSafe`，指针/句柄主要使用 `LongPtr`；以目标 VBA7 为前提，没有发现旧式无 `PtrSafe` 的活动 Windows 分支直接阻断编译。仍需注意：

- `PtrSafe` 只声明“已考虑 64 位”，不会自动修正错误的参数类型；Microsoft 要求所有指针、句柄和相应返回值都逐项审查。
- `KCL.bas`、`Cls_DynaWD.cls`、`ZZ_BACK2.bas`、`ZZ_BCK.bas` 有重复的剪贴板 API；后两个历史备份模块不应进入生产包。
- `Cls_JsonConverter` 的 `popen/libc.dylib` 仅在 Mac 条件分支，Windows R2018 不编译该路径。
- 必须在实际 CATIA VBA 宿主里记录 `VBA7`、`Win64` 条件常量，不用 Office 的行为代替 CATIA 实测。

---

## 5. 保护状态为什么会让菜单不可用

### 5.1 主菜单自省调用链

[A00_Menu.bas:43-63](../Src/A00_Menu.bas#L43) 的核心链路是：

```text
CATMain
  -> KCL.GetApc / MSAPC.Apc.7.1
  -> ExecutingProject
  -> ProjectItems.VBComponents
  -> comp.CodeModule
  -> CountOfDeclarationLines / Lines / ProcBodyLine
  -> 解析 {GP}/{EP}/{Caption}
```

它没有对 `GetApc = Nothing`、工程锁、CodeModule 拒绝访问或安全策略阻断提供可靠错误处理。

### 5.2 动态 UI 同样读取自身源码

[Cls_DynaWD.cls:493-539](../Src/Cls_DynaWD.cls#L493) 再次通过 MSAPC 读取指定模块的 `CodeModule`，从 `%UI` 注释动态生成控件。也就是说，即使把主菜单改成静态列表，业务窗体仍会因工程锁/对象模型策略失败。

### 5.3 恢复策略

短期调试版：

- 在隔离 R2018 构建机上使用**未保护** CATVBA；
- 记录 `CreateObject("MSAPC.Apc.7.1")`、`ExecutingProject`、`VBProject`、`CodeModule` 每一步的错误号；
- 仅为定位问题临时验证对象模型访问，不把全局“信任 VBA 工程对象模型”设为生产依赖。

正式版：

- 构建期解析标签并生成只读 `MenuManifest`；
- 构建期解析 `%UI` 并生成 `UiManifest`；
- 运行时不访问 `VBProject/VBComponents/CodeModule`；
- 生产包移除 MSAPC、VBIDE、模块管理器和源码导入导出；
- 完成上述重构后，才讨论是否为了防误编辑再次锁定工程。

---

## 6. 其他确定性运行阻断

| ID | 证据 | 后果 | 修复方向 |
|---|---|---|---|
| R01 | [A00_Menu.bas:9](../Src/A00_Menu.bas#L9)、[Cat_Macro_Menu_View.frm:67](../Src/Cat_Macro_Menu_View.frm#L67)、`:198` | `R&W` 被用作 Page Name，含 `&`；组号又被用作动态控件 Name，数字开头非法 | `Name` 使用 `pg_1` / `btn_3_001`，Caption 单独保存业务文字 |
| R02 | [KCL.bas:865-868](../Src/KCL.bas#L865) | `IIf` 会同时求值；没有 `_._` 时仍执行 `Left(...,-1)`，Error 5 | 改普通 `If...Then...Else` |
| R03 | [ASM_ChildMng.bas:47-55](../Src/ASM_ChildMng.bas#L47) | 局部 `osel` 未 `Set` 就 Add/Copy/Paste | 显式绑定 ActiveDocument.Selection，所有出口 Clear/恢复 |
| R04 | [KCL.bas:1232-1246](../Src/KCL.bas#L1232) 及调用方 | `CATquick(True/False)` 语义与调用方相反，错误/取消后可能留下手动更新、隐藏 HSO、低精度 | 令牌化保存原状态，`Finally` 风格恢复 |
| R05 | [Cls_VbaMdlMgr.cls:197-212](../Src/Cls_VbaMdlMgr.cls#L197)、`:260-277` | 先删模块，再因 `.frx` 进入 `Filter/UBound` 空数组而失败；项目被部分清空 | 生产移除；开发版使用快照、临时工程、校验、原子替换 |
| R06 | [OTH_INSNAME.bas](../Src/OTH_INSNAME.bas)、[OTH_PrePn.bas](../Src/OTH_PrePn.bas) | 批量改名边遍历边写，无全量冲突/非法字符预检、无回滚 | 计划-预览-提交-逆序回滚 |
| R07 | [Cls_allBTNEVT.cls:90-101](../Src/Cls_allBTNEVT.cls#L90) | `ExecuteScript` 错误被无条件清除，用户把失败当成功 | 返回结构化结果并写脱敏日志 |
| R08 | [ASM_1ex2stp.bas:119](../Src/ASM_1ex2stp.bas#L119) | `Fasle` 拼写错误因缺 `Option Explicit` 被当 Empty，掩盖质量问题 | 全模块启用 `Option Explicit`，添加静态门禁 |

---

## 7. 安全审查结论

### 7.1 生产包必须移除的能力

- [A00_backmeup.bas:11-41](../Src/A00_backmeup.bas#L11)：改写当前工程 CodeModule；
- [Cls_VbaMdlMgr.cls](../Src/Cls_VbaMdlMgr.cls)：枚举、删除、导入和导出已加载 VBProject；
- `VbaModuleManegerView`：模块管理 UI；
- `VBProject/VBComponents/CodeModule` 访问；
- PowerShell、WScript.Shell 外部命令；
- 公共 Google 翻译；
- 微信外链/硬编码跟踪 token；
- [LicenseReset.catvbs](../LicenseReset.catvbs)；
- 测试、历史备份和诊断 Public Sub。

这些可以存在于隔离的 `MacroMenu.DevTools.catvba`，但不得进入面向普通用户的 Release。

### 7.2 外部命令与命令注入

[ASM_1ex2stp.bas:97-111](../Src/ASM_1ex2stp.bas#L97)：

- 优先执行硬编码 `D:\for use\7-Zip\7z.exe`，未验证签名或哈希；
- 否则把文档路径/Part Number 派生路径拼入隐藏 PowerShell 脚本；
- Windows 路径允许单引号和分号，现有单引号包裹没有正确转义，可形成命令注入；
- 成功后删除原 STP。

首版应只导出、不压缩。若必须压缩，调用受管只读目录中的签名 helper，以参数传值，不拼接脚本文本；或者由发布/文件服务在 CATIA 外完成。

### 7.3 网络与数据外发

[MDL_translateRename.bas:23-40](../Src/MDL_translateRename.bas#L23)、`:81-112` 会把非中文 HybridBody/HybridShape 名称作为 Google GET 查询参数同步外发。名称可能包含客户、项目或设计语义；失败时函数返回原文，赋值仍可能被计为成功。该模块没有 `{GP}`，不会默认出现在菜单，但 Public Sub 可手工执行。

生产包应移除。替代优先级：离线术语表 > 企业内网翻译服务 > 经数据治理批准、显式确认并具备超时/审计的服务。

### 7.4 许可证脚本

[LicenseReset.catvbs:30-49](../LicenseReset.catvbs#L30) 关闭全部活动许可证，`:59-84` 接受任意名称并持久化，没有 AB3/MD2/HD2 保护、快照、允许清单和回滚。它不会绕过 DSLS 权益，却可能造成重启后 CATIA 不可用、错误占用并发许可证或影响其他用户。

它不在两个 CATVBA 模块内，现有 Release glob 也不会上传 `.catvbs`，但位于仓库根目录，仍容易被误运行。正式交付应排除；许可证选择由管理员通过 CATIA Licensing UI/DSLS 管理。宏最多做只读 capability preflight，不能调用 `SetLicense(..., False)`。

### 7.5 发布链

现有 workflow 只上传仓库中预置的 `*Menu*.catvba`，不构建、不编译、不核对源码/p-code、不签名、不生成哈希或证明；Actions 还使用可变 major tag。正式链应：

1. Actions 固定到完整 commit SHA；
2. 通过受保护 R2018 构建机从审定提交重建；
3. 生成模块/FRX/引用/SP-HF/许可证/Git SHA 清单；
4. Compile、重启、冒烟、三许可证测试；
5. 签名或受管安装；
6. 生成 SHA-256 和 provenance/attestation；
7. 经环境审批后发布不可变版本名。

### 7.6 未发现的行为及边界

静态扫描没有发现活动的注册表读写、`ExecuteGlobal/Eval/ScriptControl`、下载后执行、计划任务/启动项、私钥或常见云密钥。FRX 基础字符串扫描未发现 URL/PE 标记，但尚未做完整设计器对象取证。“未发现”不等于已证明无恶意代码。

---

## 8. AB3 / MD2 / HD2 与额外许可证矩阵

### 8.1 基线原则

- AB3：Automotive Body In White Design 3 Configuration；
- MD2：Mechanical Design 2 Configuration；
- HD2：Hybrid Design 2 Configuration。

三者是 configuration，不应由宏取消。现场究竟是“三者都存在”还是“不同用户只拿到其中一种”，必须分别测试。最保守的 Core 应以三者共同的基础文档、Product、Part 和标准 Drawing 能力为边界，并在按钮显示前做只读 capability probe。

许可证门禁必须区分：

1. 类型库是否安装/引用可编译；
2. 工作台/API 是否可取得；
3. DSLS 是否有权益；
4. 当前会话是否实际取得许可证。

不能因为 `As SomeType` 能编译就认定许可证可用，也不能通过脚本任意勾选来“解决”授权。

### 8.2 已确认或高概率超出基线的功能

| 功能/模块 | 额外产品/能力 | 处理 | 无额外许可证的替代 |
|---|---|---|---|
| [ASM_CMP.bas](../Src/ASM_CMP.bas) `OptimizerWorkBench/PartComps` | **SPA：DMU Space Analysis 2**；Part Comparison 示例属于 Space Analysis。API 名称易被误认为 DMO，不能据名字购买 DMO | 独立 SPA 包，启动前 probe；无 SPA 默认隐藏 | 比较 Product 树、PN、实例名、数量、文件版本、质量/惯量；不能声称等价于 Added/Removed 几何图 |
| [MDL_BdyDel.bas](../Src/MDL_BdyDel.bas)、[MDL_Shapeinfo.bas](../Src/MDL_Shapeinfo.bas)、[OTH_Minibox.bas](../Src/OTH_Minibox.bas)、`KCL.GetMeas` | SPAWorkbench/测量，按 **SPA** 门禁 | 从 Core 移到 Measurement 包 | 使用已有 Part Analyze/参数的只读质量、体积或包围信息；精确距离不可用时明确禁用 |
| [ASM_1ex2stp.bas](../Src/ASM_1ex2stp.bas) | **ST1：STEP Core Interface 1** | 独立 Export 包；同时移除 PowerShell 压缩 | 保存 CATPart/CATProduct；由有 ST1 的受控工作站或服务转换 |
| [OTH_unfoldme.bas](../Src/OTH_unfoldme.bas) `HybridShapeUnfold` | **DL1：Developed Shapes 1**（或现场配置中明确包含的等价能力） | 独立 DL1 包，实机 probe | 有 Sheet Metal 许可时走对应工作台；否则提示人工处理并禁用，不能绕过许可 |
| [Drw_myframe.bas:680](../Src/Drw_myframe.bas#L680) `Layout2DView` | **LO1：2D Layout for 3D Design** | 把 Layout2D 分支与普通 CATDrawing 图框拆开 | 保留标准 CATDrawing 图框，不创建 Layout2DView |
| [OTH_3Dmark.bas:54-64](../Src/OTH_3Dmark.bas#L54) `Marker3Ds` | **DMN：DMU Navigator 2**，并需在实际 configuration 中确认 | 默认菜单入口 `newlabel` 必须独立 probe | 写 UserRefProperties、CSV 或普通 Drawing 文本；不创建 3D Marker |
| [OTH_3Dmark.bas:77-98](../Src/OTH_3Dmark.bas#L77) AnnotationSets | **FTA：3D Functional Tolerancing and Annotation 2** | 该过程不是当前菜单入口，移入 FTA 包 | 输出 CSV/Marker 文本或禁用 3D Annotation 创建 |
| [Cls_PDM.cls:403-432](../Src/Cls_PDM.cls#L403) `CreateProgram/CreateFormula` | **KWA：Knowledge Advisor 2**，需核实 AB3/MD2/HD2 现场配置是否已含权益 | 把持久 EKL 逻辑从基础 PDM 读取链分离 | 在 VBA 中即时计算并写经确认的普通属性，不创建 EKL Program/Formula |
| [OTH_Flower.bas](../Src/OTH_Flower.bas) 高级曲面 | AB3/HD2/GSD 具体能力需逐 API 验证，MD2 不应默认假定 | 作为实验/参考，不进入 MVP | 简化为基础曲线/实体流程；不满足则隐藏 |
| Excel 事件与导出 | 非 CATIA 许可证；需兼容 Excel 安装 | 独立 Excel 包 | CSV/TSV 为正式降级路径 |

DMO（DMU Optimizer 2）和 PEO（Product Engineering Optimizer 2）是不同产品。目前没有充分证据证明本项目必须购买它们；不要仅因 `OptimizerWorkBench` 名称而采购。`ASM_CMP` 应先按 SPA 在 R2018 实测。

### 8.3 建议首版保留/禁用

首版可考虑保留：

- 菜单、版本、HealthCheck；
- 当前文档类型、路径、只读属性；
- 结构/PN 的只读检查；
- 可逆显示、颜色操作，但必须恢复 CATIA 全局状态；
- 标准 CATDrawing PDF 导出，含路径和覆盖确认；
- CSV BOM、CSV 坐标输出，不依赖 Excel。

首版禁用：

- `ASM_ChildMng`、`OTH_PrePn`、`OTH_INSNAME`；
- `ASM_3LocalSave`、`MDL_Part2Product`；
- 删除、批量改名、跨文档复制；
- 模块导入/覆盖导出；
- 所有网络、PowerShell、许可证修改入口；
- SPA/ST1/DL1/LO1/FTA 未通过 capability test 的入口。

---

## 9. 依赖总表：必须区分三类机器

### 9.1 A 类：工作区分析、测试、文档和打包机

这类机器用于当前仓库的修改、静态测试、CATVBA 取证和报告生成。它可以安装 Python/OLE 工具，但这些工具**不能进入正式 CATIA 工位或 Release**。

#### 必装顶层工具

| 依赖 | 建议版本/位数 | 用途 | 是否进入生产机 |
|---|---|---|---|
| Git for Windows | x64，固定企业批准版本 | 源码、tag、diff、树一致性 | 否 |
| PowerShell 7 | x64 | 审查脚本、哈希、门禁 | 否；生产通常已有 Windows PowerShell 但 Core 不依赖 |
| Python | **CPython 3.12 x64** | OLE/MS-OVBA 解析、测试生成器 | 否 |
| `olefile` | `0.47` | 读取 OLE/CFB 流 | 否 |
| `oletools` | `0.60.2` | `olevba/oleid`、VBA 源码提取与指标扫描 | 否 |
| `pcodedmp` | `1.2.6`，可选但建议 | p-code/PerformanceCache 辅助核验 | 否 |
| pytest | 安装时锁定企业批准版本 | 测试 manifest 生成、规则、引用解析 | 否 |
| ripgrep | x64，可选 | 快速源码检索 | 否 |
| 7-Zip | x64，可选 | 审计/归档，不作为 CATIA 内宏依赖 | 否 |
| Windows SDK SignTool | 可选 | 签名 MSI/目录清单/发布辅助 | 否 |

选择 Python 3.12 是因为 `olefile/oletools` 的 PyPI classifier 明确覆盖到 3.12；当前审查机虽在 Python 3.14.4 成功安装，但不应把未正式声明的组合定为长期 CI 基线。

#### 本次已验证可安装的 OLE 工具依赖闭包

安装 `oletools==0.60.2` 时，本次环境解析出的闭包如下。正式使用应在 Python 3.12 干净 venv 中重新生成 lock，并从内部镜像按哈希安装：

| 包 | 本次解析版本 | 来源 |
|---|---:|---|
| `olefile` | 0.47 | 直接/oletools |
| `oletools` | 0.60.2 | 直接 |
| `pcodedmp` | 1.2.6 | oletools |
| `pyparsing` | 3.3.2 | oletools |
| `easygui` | 0.98.3 | oletools |
| `colorclass` | 2.2.2 | oletools |
| `msoffcrypto-tool` | 6.0.0 | oletools |
| `cryptography` | 49.0.0 | msoffcrypto-tool |
| `cffi` | 2.1.0 | cryptography |
| `pycparser` | 3.0 | cffi |
| `win-unicode-console` | 0.5 | pcodedmp |

`olefile` 具有写能力，`oletools/pcodedmp` 解析不可信二进制。审计必须在低权限、无网络、只读副本中运行；脚本只允许读取，不得“修复”或解锁被测 CATVBA。

#### 手动安装示例

```powershell
py -3.12 -m venv .venv-audit
.\.venv-audit\Scripts\python.exe -m pip install --upgrade pip
.\.venv-audit\Scripts\python.exe -m pip install `
  olefile==0.47 oletools==0.60.2 pcodedmp==1.2.6 pytest
.\.venv-audit\Scripts\python.exe -m pip freeze
```

建议把 wheel 下载到企业制品库，审查 SHA-256 后离线安装；不要让构建脚本在每次发布时从公网拉取最新版本。

### 9.2 B 类：R2018 构建与正式调试机

这是唯一允许生成候选 CATVBA 的环境，应与正式现场尽可能一致。

#### 必装

| 依赖 | 要求 | 验证方式 |
|---|---|---|
| Windows | R2018 官方支持、且与现场一致的 64 位版本；优先 Windows 10 Enterprise/Pro | 记录 `winver` |
| CATIA V5-6R2018 | **R28/B28 x64**，精确 GA/SP/HF | About/环境文件/安装目录三者一致 |
| DS VBA | **从同一 R2018 安装介质安装 DS VBA 7.1** | VBE 可打开；运行 VBA7/Win64 probe；APC 7.1 可创建 |
| Microsoft Forms 2.0 | 应由 DS VBA/受支持 Office 安装提供，不从第三方下载 FM20.DLL | References 无 MISSING；4 个 UserForm 可打开 |
| DSLS 客户端 | 与企业服务器/策略兼容 | 登录、借用/并发状态由管理员确认 |
| AB3、MD2、HD2 | 按真实部署分别测试，基线不允许脚本取消 | 只读记录当前 configuration；逐一冒烟 |
| B28 CATIA 类型库 | 由 CATIA 安装提供，禁止复制 B30 TLB | 引用路径只允许 B28 |
| 脱敏测试数据 | CATPart/CATProduct/CATDrawing，多种状态 | 测试夹具只读副本 |

不要在同一构建 VM 并排安装 B30。历史 CATIA/VBA 宿主存在多版本注册互相覆盖问题；一台干净 VM 对应一个 CATIA release/SP/HF 最可控。

#### 按功能可选

| 依赖 | 何时安装/启用 | 备注 |
|---|---|---|
| Excel/Office | 只测 `MacroMenu.Excel` 包时 | 当前源码有 Excel 16.0 早绑定；重构后改 Object + 自定义常量。版本/位数必须与现场一致 |
| SPA | 只测 Compare/Measurement 包 | 需 DSLS 实际权益；不是普通 DLL 安装问题 |
| ST1 | 只测 STEP Export 包 | 没有权益就禁用，不提供绕过 |
| DL1 | 只测 Unfold 包 | `HybridShapeUnfold` |
| LO1 | 只测 Layout2D 包 | 普通 CATDrawing 不应被拖入此依赖 |
| DMN | 只测 3D Marker 包 | 默认 `newlabel` 入口使用 `Marker3Ds` |
| FTA | 只测 Annotation 包 | 与 Marker/普通文本分开 |
| KWA | 只测持久 EKL/Formula 包 | 基础只读 PDM 不应依赖 KWA |
| 7-Zip | 仅外部受管打包或专项测试 | 不使用硬编码 `D:\for use`；不由 CATIA 隐藏执行未知副本 |

#### 不要安装来“补错引用”

- B30/R2020 CATIA 或 B30 TLB；
- SysWOW64 `msscript.ocx`；
- x86 VBIDE 5.3/VBA6；
- x86 AddInDesigner；
- 用户临时 `MSForms.exd`；
- 来历不明的 FM20.DLL/APC DLL；
- COMAdmin、COMSVCS、ActiveDs、EventSystem 等仅因旧工程引用而额外部署。

这些是应从工程删除的污染项，不是目标机依赖。

### 9.3 C 类：正式 CATIA 用户机

修复后的 Core 正式机只需要：

- 与认证一致的 CATIA V5-6R2018/B28 x64 + SP/HF；
- 同介质 DS VBA 7.1 和可用的 Microsoft Forms；
- DSLS 与 AB3/MD2/HD2 中现场规定的 configuration；
- IT 管理的只读、版本化 CATVBA 安装目录；
- `%LOCALAPPDATA%` 下独立的脱敏日志/用户配置目录。

正式机**不安装**：

- Python、pip、olefile、oletools、pcodedmp、pytest；
- Git、编译/导出模块工具；
- x86 Script Control/VBIDE；
- 为 Core 安装的 Excel、PowerShell 7、7-Zip；
- 任何允许普通用户修改生产 CATVBA 的工具。

Windows 自带但应做策略预检、而非单独下载的组件：

- `Scripting.Dictionary` / `FileSystemObject`；
- `VBScript.RegExp`；
- `MSXML2.XMLHTTP`、`ADODB.Stream`（仅可选包）；
- `Shell.Application` / `WScript.Shell`（Core 应不依赖）；
- `user32`、`kernel32`、`winmm`。

如果企业策略禁用 WSH、PowerShell、外网或 COM 自动化，Core 仍应正常；可选按钮显示“能力不可用及原因”，而不是启动后报错。

---

## 10. 16 个非 CATIA 直接引用的处理决定

| 引用 | 当前源码是否必须早绑定 | 决定 |
|---|---|---|
| MSForms 2.0 / FM20 | 是：UserForm、CommandButton 等 | Core 保留，在 B28/VBA7 环境重新生成引用；删除临时 EXD 依赖 |
| ADODB 6.1 | 否：只有 `CreateObject("ADODB.Stream")` | 移除 Reference；翻译包若保留则运行期 probe |
| MSAPC 7.1 | 编译否、当前运行强依赖 | 短期调试依赖；静态 manifest 后从生产移除 |
| COMAdmin | 无源码命中 | 移除 |
| COMSVCSLib | 无源码命中 | 移除 |
| AddInDesignerObjects | 无命中且 x86 | 移除 |
| Excel 16.0 | 当前是：Workbook/Range/Shape、xl* 常量 | 从 Core 拆出；重构迟绑定。未重构前，Excel 包需现场 Excel typelib |
| Office 16.0 | 仅 `msoTrue` | 用 `True`/自定义常量，移除 |
| MSScriptControl | 无命中且 SysWOW64/x86 | 移除，禁止替代安装 |
| Scripting Runtime | 调用均可迟绑定 | 移除 Reference，运行期 probe |
| OLEDBError | 无命中 | 移除 |
| VBScript RegExp 5.5 | 调用均 `CreateObject` | 移除 Reference，运行期 probe |
| mscorlib | 无早绑定；但项目用 `System.Collections.*` ProgID | 移除 Reference，并用 VBA Collection/数组替代 ProgID |
| EventSystemLib | 无命中 | 移除 |
| ActiveDs | 无命中 | 移除 |
| VBIDE 5.3 | 代码均 As Object，且引用是 VBA6/x86 | 移除；正式架构删除 VBE 自省 |

外部引用最终应收敛到 MSForms；如果 Excel 包暂未完成迟绑定，则该独立包额外保留目标机实际 Excel typelib。APC 应由 CATIA/VBA 宿主提供，但不需要作为普通业务早绑定 Reference。

---

## 11. B28 CATIA 类型库白名单候选

以下 10 个是从 89 个 B30 引用按当前源码早绑定初筛后的**候选**，不是要求 Core 全部勾选。必须按拆包结果在 B28 VBE 中逐个最小化：

| 域 | 候选 B28 类型库 |
|---|---|
| 基础 | `InfTypeLib.tlb`、宿主隐式 `CATIAAppTypeLib/CATIA_APP_ITF` |
| Product/Assembly | `PSTypeLib.tlb`、`CATAssemblyTypeLib.tlb` |
| Part | `MecModTypeLib.tlb`、`PartTypeLib.tlb`、`CATGSMIDLItfTypeLib.tlb` |
| Knowledge | `KweTypeLib.tlb` |
| Drawing | `DraftingTypeLib.tlb` |
| Optional | `Layout2DTypeLib.tlb`、`SPATypeLib.tlb` |

`VBA/VBE7` 和 CATIA Application 宿主库可能是隐式引用；仍须记录版本和路径。白名单门禁拒绝：

- B30 或任何非 B28 CATIA 路径；
- 用户目录、Temp、EXD；
- `Program Files (x86)` / `SysWOW64`；
- 未属于当前功能包的专业域 TLB；
- Office/Excel/ADODB 出现在 Core；
- VBIDE/VBA6/MSScriptControl。

---

## 12. 其余 79 个 B30 引用：全部先移除

下列文件在当前源码未见必须的早绑定证据。它们不应被“照单安装”，而应从新工程 References 排除；如果某个拆分功能编译时确实需要，再以 B28 实际库、源码证据和许可证测试逐项加入。

```text
BehaviorTypeLib.tlb
CATIdeSettingsTypeLib.tlb
CATInstantCollabItfTypeLib.tlb
CATMatTypeLib.tlb
CATAnnotationTypeLib.tlb
CclTypeLib.tlb
GenKweTypeLib.tlb
CATStrSettingsTypeLib.tlb
StrTypeLib.tlb
AECRTypeLib.tlb
CATCompositesTypeLib.tlb
CAT3DXmlTypeLib.tlb
CATAnalysisTypLib.tlb
CATArrangementTypeLib.tlb
CATDataExchTypeLib.tlb
CATEdbTypeLib.tlb
CATFunctSystemTypeLib.tlb
CATHASTypeLib.tlb
CATHumanPackagingTypeLib.tlb
CATV4IInteropTypeLib.tlb
CATImmTypeLib.tlb
DNBIPDTypeLib.tlb
CATMultiCADTypeLib.tlb
CATOBMTypeLib.tlb
CATPspPlantShipTypeLib.tlb
CATRdgTypeLib.tlb
CATRpmReporterTypeLib.tlb
CATRmaTypeLib.tlb
CATRscTypeLib.tlb
CATSchematicTypeLib.tlb
CATSdeSettingTypeLib.tlb
CATShfTypeLib.tlb
CATSmarTeamIntegTypeLib.tlb
CATSmInterfacesTypeLib.tlb
CATStkTypeLib.tlb
CATSfmTypeLib.tlb
CATToolingTypeLib.tlb
ProcessTypeLib.tlb
DNBAsyTypeLib.tlb
DNBD5ITypeLib.tlb
DNBDeviceActivityTypeLib.tlb
DNBDeviceTypeLib.tlb
DNBBIWTypeLib.tlb
DNBDpmTypeLib.tlb
DNBFastenerTypeLib.tlb
DNBPertTypeLib.tlb
SWKHumanModelingTypeLib.tlb
DNBIgpSetupTypeLib.tlb
DNBIgripSimTypeLib.tlb
DNBManufacturingLayoutItfTypeLib.tlb
DNBMHIItfTypeLib.tlb
DNBReportingTypeLib.tlb
DNBIgpResourceProgramTypeLib.tlb
DNBRobotTypeLib.tlb
DNBSimActivityTypeLib.tlb
DNBSimIOTypeLib.tlb
DNBSimulationTypeLib.tlb
DNBStateTypeLib.tlb
DPMSettingsTypeLib.tlb
ElecSchematicTypeLib.tlb
ElectricalTypeLib.tlb
V6TypeLib.tlb
CD5IntegTypeLib.tlb
mxcatiav5integrationTypeLib.tlb
UPSTypeLib.tlb
FittingTypeLib.tlb
KinTypeLib.tlb
MfgTypeLib.tlb
NavigatorTypeLib.tlb
OSMInterfacesTypeLib.tlb
PCBTypeLib.tlb
PPRTypeLib.tlb
PmgTypeLib.tlb
CATRscTypeLib2.tlb
SIMTypeLib.tlb
SimulationTypeLib.tlb
SMTypeLib.tlb
SurfaceMachiningTypeLib.tlb
CATStiWIPBridgeSurrogateCOMExe.exe
```

---

## 13. 目标架构

### 13.1 建议拆包

```text
MacroMenu.Core.catvba
MacroMenu.Assembly.catvba
MacroMenu.Part.catvba
MacroMenu.Drawing.catvba
MacroMenu.Measurement-SPA.catvba
MacroMenu.Exchange-ST1.catvba
MacroMenu.Optional-Excel.catvba
MacroMenu.Optional-DL1-LO1-FTA.catvba
MacroMenu.DevTools.catvba        # 永不发布到普通用户
```

VBA 是工程级编译。拆包后 Excel 或 SPA 失败不会拖垮主菜单，许可证差异也能在库级隔离。

### 13.2 静态 manifest

构建工具从源码标签生成一个标准模块或只读资源：

```text
tool_id
caption
group_id
module_name
entrypoint
document_types
required_capabilities
risk_level
ui_schema
```

运行时只读取 manifest，不扫描 CodeModule。Dispatcher 使用生成的精确 allowlist；每次调用返回成功/失败/错误号/耗时。可选库不可用时按钮禁用并显示原因。

### 13.3 KCL 拆分

当前 `KCL.bas` 同时承担状态、UI、路径、集合、Shell、测量、Clipboard、业务规则和全局单例。建议至少拆为：

- `CoreCatiaContext`：文档类型和 CATIA 状态；
- `CoreError`：统一错误和日志；
- `CorePath`：规范化/允许根/安全文件名；
- `CoreCollections`：VBA Collection/Dictionary 适配；
- `CoreUi`：合法对象名、Caption、manifest；
- `CapabilityRegistry`：许可证/工作台/COM probe；
- `CatiaStateGuard`：RefreshDisplay、DisplayFileAlerts、UpdateMode、HSO 等保存和恢复。

### 13.4 破坏性操作事务化

批量改名、复制、删除、保存必须采用：

```text
收集 -> 全量验证 -> 冲突检测 -> 预览 -> 用户确认
     -> 保存原值/快照 -> 提交 -> 每步记录
     -> 失败逆序回滚 -> 明确报告未恢复项
```

`On Error Resume Next` 只能包围预期、极小的探测语句，随后立即检查并恢复错误模式；不能覆盖完整业务过程。

---

## 14. 分阶段恢复计划

| 阶段 | 目标 | 出口条件 |
|---|---|---|
| P0 取证冻结 | 停止分发当前/旧 CATVBA，保存哈希和环境 | 两个二进制只读归档；旧文件不再作为回滚 |
| P1 干净 B28 seed | 新建 R2018 CATVBA、最小引用 | 无 B30/x86/Temp/MISSING 引用 |
| P2 Compile-zero | 修 C01-C06、Excel/SPA/LO1 隔离、Option Explicit | 每个候选库 `Debug > Compile` 零错误 |
| P3 Core 可启动 | 静态 MenuManifest、合法 MSForms Name | 无 VBE 自省、菜单在无文档状态启动 |
| P4 UI 可运行 | 静态 UiManifest | 工程锁定与否不影响 UI；不要求信任 VBProject |
| P5 MVP 功能 | 恢复 5-10 个只读/可逆高价值功能 | AB3/MD2/HD2 分别通过 |
| P6 安全收口 | 移除模块管理、Shell、网络、许可证修改 | Core 无 Office/PowerShell/网络仍通过 |
| P7 产物核验 | 源码/FRX/引用/p-code/哈希/签名 | 构建清单与 Git SHA 可追溯 |
| P8 试点发布 | 新旧并存、受管切换、回滚 | 新用户配置和试点机通过 |

MVP 粗估 20-35 人日；完整恢复 77 个模块约 50-90 人日。估算取决于正式 SP/HF、最重要业务流程、测试数据和许可证可用性。

---

## 15. R2018 实机首轮操作单

### 15.1 先记录，不修改

1. 记录 Windows 版本、CATIA R28/B28、SP、HF、DS VBA 版本、VBE 版本。
2. 记录当前启用的 AB3/MD2/HD2；不得运行 `LicenseReset.catvbs`。
3. 复制正式 CATVBA 到隔离测试目录，记录 SHA-256。
4. 不覆盖原文件，不使用旧 `CAT_menu.catvba`。

### 15.2 复现现有产物

1. 添加现有 CATVBA 库，但先不要保存任何修改。
2. 打开 VBE `Tools > References`，导出所有勾选项、GUID、版本、路径、是否 MISSING。
3. 截图/记录首个 MISSING 项；不要通过复制 B30 文件修复。
4. 在副本中逐项取消明显无关引用，直到只剩目标候选；每一步记录。
5. 执行 `Debug > Compile CAT_MENU`，按出现顺序记录完整错误、模块和行号。
6. 验证 C01-C06 是否与静态结论一致。
7. 在未保护调试副本运行 APC probe；逐步记录 `GetApc`、`ExecutingProject`、`VBProject`、`VBComponents`、`CodeModule`。
8. 在保护副本重复，确认第一处差异。

### 15.3 创建新 B28 工程

1. 在干净 B28 VM 新建空 CATVBA，不从旧 CATVBA Save As。
2. 只加入当前功能包需要的 B28 类型库。
3. 按固定顺序导入 `.bas`、`.cls`、`.frm + .frx`。
4. Compile，修到零错误。
5. 保存、关闭 CATIA、结束残留 CATVBA host，重新打开。
6. 再次 Compile/运行 HealthCheck。
7. 在新 Windows 用户配置重复加载。

---

## 16. 测试矩阵与放行门槛

### 16.1 环境轴

- CATIA：正式 R2018 SP/HF；
- 许可证：AB3、MD2、HD2 分别单独测试，再测现场组合；
- UI：中文和英文；
- 用户：构建账号、新普通用户；
- Office：未安装；Excel 包另测现场 Office；
- 网络：完全阻断；
- PowerShell/WSH：企业策略禁用；
- 文档：无文档、CATPart、CATProduct、CATDrawing；
- 状态：未保存、已保存、只读、脏文档；
- 路径：ASCII、空格、中文、单引号、只读、UNC；
- 会话：首次加载、重启、重复执行、跨文档切换。

### 16.2 Core 放行门槛

- References 无 `MISSING:`；
- 无 B30、x86、Temp、用户目录引用；
- 全项目 Compile 零错误；
- 重启后仍能运行；
- 不访问 VBE/CodeModule；
- 所有 MSForms Name 合法且唯一；
- AB3/MD2/HD2 三种测试均启动成功；
- 无 Office、无网络、禁 PowerShell 时 Core 正常；
- 取消/错误后 CATIA 全局状态与进入前一致；
- Dispatcher 不吞错；
- 二进制模块/源码/FRX/引用清单对应审定提交；
- SHA-256、Git SHA、SP/HF、许可证测试结果齐全。

### 16.3 破坏性功能额外门槛

- 第一次写入前完成全量冲突检测；
- 有明确变更预览；
- 取消不产生任何修改；
- 任一步失败可完整逆序回滚；
- 回滚失败项被明确列出；
- 原文档有可恢复备份；
- 测试只在脱敏副本执行；
- 日志记录操作结果但不泄露模型名称/客户数据。

---

## 17. 构建、发布与回滚

建议不可变文件名：

```text
MacroMenu.Core-0.2.0-R28-x64.catvba
MacroMenu.Assembly-0.2.0-R28-x64.catvba
manifest-0.2.0.json
checksums-0.2.0.txt
build-metadata-0.2.0.json
```

`build-metadata` 至少包含：

- Git commit/tree；
- CATIA R28、SP、HF；
- DS VBA/VBE 版本；
- 功能包与许可证测试；
- 直接 References GUID/版本/路径；
- 每个规范化源码和 FRX 哈希；
- CATVBA SHA-256；
- Compile/重启/冒烟结果；
- 签名/证书或外部受管安装证明。

发布时新旧版本并存，CATIA 宏库注册切换到新路径；回滚只切回上一个**已验证 R28 产物**。软件回滚不能恢复已经被宏改坏的 CATPart/CATProduct，破坏性功能必须另有文档备份和事务日志。

当前 `main/dev` 无共同历史的 squash + `checkout --theirs` 发版方式也应停止。Release 树必须与记录的 Git tree 完全一致。

---

## 18. 建议维护者补充的现场信息

后续实现前应固定：

1. 正式 Windows 版本、R2018 SP/HF；
2. AB3、MD2、HD2 是同时可用，还是不同用户/席位只具备一种；
3. 首版最重要的 5-10 个业务流程；
4. 是否接受 CSV/TSV 作为 Excel 的正式降级；
5. 是否允许任何网络请求、PowerShell 或 WSH；建议 Core 全部不允许；
6. 是否有企业代码签名证书/受管软件分发；
7. 可否提供脱敏 CATPart、CATProduct、CATDrawing 和冲突样例；
8. 是否必须锁定 VBA 源码；如必须，应先完成静态 manifest；
9. 是否接受按功能/许可证拆成多个 CATVBA；
10. SPA、ST1、DL1、LO1、DMN、FTA、KWA 在 DSLS 中是否实际有权益。

---

## 19. 参考资料

### Microsoft / Git

- [64 位 VBA：PtrSafe、LongPtr 与 Win64](https://learn.microsoft.com/zh-cn/office/vba/language/concepts/getting-started/64-bit-visual-basic-for-applications-overview)
- [Can't find project or library](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/can-t-find-project-or-library)
- [Class Public 接口使用 UDT 的编译错误](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/only-public-user-defined-types-defined-in-public-object-modules-can-be-used-as-p)
- [Option Explicit](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/option-explicit-statement)
- [IIf 会计算 truepart 和 falsepart](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/iif-function)
- [MSForms 合法对象名](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/not-a-legal-object-nameitem)
- [MS-OVBA ProjectProtectionState](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ovba/55e770e2-e1a4-4d1c-a8a4-dcfca27d6663)
- [MS-OVBA Encryption Method：仅用于 obfuscation](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ovba/b5bb7e87-c7a2-4cd2-99e9-c54e8282c155)
- [MS-OVBA Versioning and Performance Caches](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ovba/4d20e95c-0c17-47d6-84b9-8da95d8ea129)
- [VBA 数字签名](https://support.microsoft.com/en-US/Office/vba/digitally-sign-your-vba-macro-project)
- [GitHub Actions 固定完整 SHA](https://docs.github.com/en/organizations/managing-organization-settings/disabling-or-limiting-github-actions-for-your-organization)
- [GitHub Artifact Attestations](https://docs.github.com/en/enterprise-cloud@latest/actions/concepts/security/artifact-attestations)

### Dassault Systèmes / CATIA

- [V5-6R2018 Licensed Program Specifications](https://www.3ds.com/assets/Terms/LicensedProgramSpecifications/V5%20PLM/V5-6R2018.pdf)
- [AB3 / DMO / SPA / ST1 等 V5 产品代码表](https://www.3ds.com/assets/invest/2024-02/eccn-february-2024.pdf)
- [DMU Space Analysis 2 (SPA)](https://3dswym.3dexperience.3ds.com/wiki/catia-user-community/dmu-space-analysis-2-spa_flovf6rkRk6M1du00iqaNA)
- [STEP Core Interface 1 (ST1)](https://3dswym.3dexperience.3ds.com/wiki/catia-user-community/catia-step-core-interface-1-st1_TA4xh3-qQdihOyZjCPWCkg)
- [Developed Shapes 1 (DL1)](https://3dswym.3dexperience.3ds.com/wiki/catia-user-community/catia-developed-shapes-1-dl1_F3L5lPEUTv-p0a8FmUQ8aw)
- [2D Layout for 3D Design (LO1), R28 课程资料](https://www.3ds.com/assets/edu/document/course-catalog-v5-6r2018-to-v5-6r2023.pdf)
- [3D Functional Tolerancing and Annotation 2 (FTA)](https://3dswym.3dexperience.3ds.com/wiki/catia-user-community/catia-3d-functional-tolerancing-and-annotations-2-fta_g6WGTlSlT1ii20jkZdd6sQ)
- [CATIA 编辑 CATVBA 宏](https://maruf.ca/files/catiahelp/basug_C2/basugbt1904.htm)
- [CATIA Licensing：静态许可证变更需按流程并重启](https://catia-v5-help.anarkia333data.center/online/basil_C2/basilLicensingReserveStatic.htm)

### 审计工具

- [olefile 0.47](https://pypi.org/project/olefile/)
- [oletools 0.60.2](https://pypi.org/project/oletools/)
- [pcodedmp 1.2.6](https://pypi.org/project/pcodedmp/)
- [pytest](https://pypi.org/project/pytest/)

---

## 20. 最终判定

现有 `CATIA_V5_SimpleMacroMenu.catvba` 的问题不能靠“补装一个依赖”解决。B30 引用污染、6 个必然编译错误、受保护工程与源码自省冲突、非法 UI Name、可选许可证未隔离和高风险外部能力，任何一项都足以阻断可信生产使用。

建议立即停止分发现有二进制，以仓库源码为唯一修复输入，在干净 R2018/B28 环境先交付无 VBE 自省、无外部命令、无网络、无 Office 强依赖的 Core。只有通过本文的 Compile、三许可证、重启、引用、源码/p-code、签名/哈希和回滚门槛后，才能把状态从 NO-GO 改为可试点。
