# 当前分支深度审查报告

> [!NOTE]
> **Status:** HISTORICAL SNAPSHOT — evidence as of 2026-07-11
>
> **Authority:** 保留本报告原日期、分支、SHA、问题编号和当时工具限制；当前状态见 [STATUS.md](STATUS.md)
> **Subsequent evidence:** 后续已完成更深的 CATVBA 源码/引用取证，并形成 [恢复指南](CATIA_V5_R2018_VBA7_64恢复与依赖指南.md) 与 [决策台账](CATVBA重构调查与决策记录.md)。本提示不改写历史正文。

> 审查日期：2026-07-11
> 工作分支：`codex/dev-review-report`
> 审查开始时 HEAD：`c584202aad38909c27e745e38b8d2f6b4168c689`
> 业务代码目标：`dev@abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`
> 功能增量基线：`158a0760c3e9027b9a76e8721caf7e717ba244c6`
> 发布分支：`main@efbcb6e200d68089bfe7b6324daa75b0f177b6c8`
> 审查方式：Git 拓扑与远端核对、逐文件静态审查、独立规则扫描、隔离发布复现、CATVBA 符号核对、一手文档交叉验证
> 总体结论：确认 8 项 P1、5 项 P2；在 P1 修复并完成 CATIA/VBA 动态回归前，不建议合入、重建源码产物或发布。

## 1. 结论摘要

当前分支包含两层改动：

1. `dev..HEAD` 只有本报告这一份文档；
2. 真正需要评审的业务增量是 `158a076..dev`，共 3 个提交、14 个变更文件、248 行新增、87 行删除。

现有报告中的核心判断大部分成立，但独立复核后需要补充和纠正：

- 文本源码的主菜单会把 `R&W` 当作 Page.Name，并把数值组号当作每个按钮的 Name；两者均违反 MSForms 命名规则，源码重建后的主入口会在构建菜单时失败。
- 两个批量改名模块的 `purePN` 未声明，VBA 完整编译失败；其中零件号问题是基线遗留，新增实例名模块复制了同类错误。
- 即使补上 `purePN`，不含 `_._` 的名称仍会在 `StrBF` 中因 `IIf` 双边求值触发 `Left(..., -1)`。
- 普通子产品复制继续对未初始化的 `osel` 调用 `Add/Copy`；该缺陷也已存在于基线。
- 复制流程在结束和异常时调用 `CATquick(True)`，实际会关闭刷新、切到手动更新、关闭 HSO 同步并降低显示精度。原报告只写“取消未清理”，没有准确描述方向相反且更严重的状态污染。
- 批量改名边遍历边写入，没有全量目标预检、冲突检测或回滚；后续节点失败时会留下半改名模型。
- 当前无共同祖先的发版命令经隔离复现后，确认会在发布树中额外保留 263 个 `main` 独有路径。
- 模块导入风险比原报告更确定：导入前已删除工程模块，而正常存在的 `.frx` 文件会让文件枚举在任何导入发生前报错；覆盖导出也会先删除源码目录再尝试导出。
- 现有 CATVBA 能检出全部 77 个文本模块名和新增入口符号，但符号存在不能证明内嵌源码与导出文本一致。由于没有 CATIA/VBA 编译环境，本报告没有声称当前二进制动态失败或通过。

问题汇总：

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P1 | 8 | 主路径阻断、编译错误、破坏性部分结果、发布树不一致或非事务式模块同步 |
| P2 | 5 | 局部功能静默失效、错误成功提示、跨文档状态失效或外部服务风险 |

## 2. 审查范围与基线

### 2.1 分支状态

| 项目 | 结果 |
| --- | --- |
| 当前工作分支 | `codex/dev-review-report` |
| 当前 HEAD | `c584202` |
| 本地 `dev` | `abce8ff` |
| 本地 `origin/dev` | `abce8ff` |
| 远端 `refs/heads/dev` | `abce8ff` |
| 本地 `main` | `efbcb6e` |
| 远端 `refs/heads/main` | `efbcb6e` |
| 审查开始时工作区 | 干净 |
| `main` 与 `dev` 的 merge-base | 不存在 |
| `main` 根提交 | `bc98927` |
| `dev` 根提交 | `3bca1d2` |

远端 SHA 使用 `git ls-remote --heads --tags origin` 在本次审查中重新核对，不依赖旧报告记录。

### 2.2 为什么不使用 `main...HEAD`

`main` 与 `dev` 来自不同根提交，`git merge-base main dev` 无结果。因此：

- 三点比较 `git diff main...dev` 不成立；
- 普通 PR/merge 无法基于共同祖先描述功能增量；
- 需要使用明确记录的源提交或直接比较树。

`main@efbcb6e` 的提交信息记录：

> 发版 v0.1.12 | 源DEV提交: 158a0760c3e9027b9a76e8721caf7e717ba244c6

因此本次业务增量使用 `158a076..abce8ff`，同时对 `main` 与源 `dev` 树进行直接比较。

### 2.3 功能增量

| 提交 | 内容 |
| --- | --- |
| `6480657` | 修改发版说明 |
| `1e6d741` | 修改当前文件路径打开逻辑 |
| `abce8ff` | 新增实例名批量修改并调整子产品管理 |

增量统计：

| 指标 | 数值 |
| --- | ---: |
| 变更文件 | 14 |
| 新增行 | 248 |
| 删除行 | 87 |
| 新增模块 | `Src/OTH_INSNAME.bas` |
| 二进制变更 | 主 CATVBA 与 4 个 FRX |

### 2.4 严重级别与归因

| 级别 | 定义 |
| --- | --- |
| P1 | 阻断主路径/编译/发布一致性，或可能产生破坏性部分结果；合入或发版前必须处理 |
| P2 | 局部功能失效、静默错误、错误统计、跨文档状态或明显运维/合规风险 |

“当前分支问题”不等于“本次三次提交新引入”。每项发现均标注：

- **增量新增**：`158a076..abce8ff` 引入；
- **基线遗留**：`158a076` 已存在，但当前分支仍受影响；
- **全分支风险**：与本次功能增量无直接关系，但影响当前源码或发布可信度。

## 3. 审查与核实过程

### 3.1 Git 拓扑、远端与差异

执行：

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse dev
git rev-parse main
git rev-parse origin/dev
git rev-parse origin/main
git ls-remote --heads --tags origin
git merge-base main dev
git rev-list --max-parents=0 main
git rev-list --max-parents=0 dev
git diff --stat 158a076..abce8ff
git diff --name-status 158a076..abce8ff
git diff --check 158a076..abce8ff
```

确认：

- 本地与远端 `dev/main` SHA 一致；
- `main/dev` 根不同；
- 增量有 9 处尾随空格或文件尾空行；
- 当前工作分支只比 `dev` 多一份报告文档。

### 3.2 逐文件审查

对增量文件逐行审查，重点包括：

- `Src/A00_Menu.bas`
- `Src/ASM_ChildMng.bas`
- `Src/CAT_Filepath.bas`
- `Src/Cls_DynaWD.cls`
- `Src/Cls_allBTNEVT.cls`
- `Src/KCL.bas`
- `Src/OTH_INSNAME.bas`
- `Src/OTH_PrePn.bas`
- `Docs/发版.md`

同时沿调用链扩展到：

- `Src/Cat_Macro_Menu_View.frm`
- `Src/CAT_springWD.frm`
- `Src/Cls_VbaMdlMgr.cls`
- `Src/VbaModuleManegerView.frm`
- `Src/MDL_MaterialColors.bas`
- `Src/MDL_eleRename.bas`
- `Src/OTH_ivhideshow.bas`
- `Src/MDL_translateRename.bas`

### 3.3 独立静态扫描

扫描使用当前源码重新计算，不复用旧报告数字：

| 检查项 | 结果 | 说明 |
| --- | ---: | --- |
| `Src` 文本模块 | 77 | `.bas/.cls/.frm` |
| 带 `{GP:}` 的标准模块 | 47 | 菜单候选 |
| 组号与入口均静态有效 | 42 | 足以进入主菜单构建链 |
| 缺少 `Option Explicit` | 42 | 技术债务指标 |
| 活跃 `On Error Resume Next` | 168 | 排除 6 个纯注释匹配 |
| `%UI` 控件定义 | 113 | 逐模块解析 |
| 重复 `%UI` 名称 | 1 | `MDL_MaterialColors.lb_steel` |
| 增量格式问题 | 9 | `git diff --check` |

默认工具栏回调规则由 [`Cls_DynaWD.cls:456`](../Src/Cls_DynaWD.cls#L456) 至 [`:468`](../Src/Cls_DynaWD.cls#L468) 定义为 `按钮名 + "_click"`。人工沿真实调用路径确认 3 个失效按钮，见 F-12。

### 3.4 主 CATVBA 符号核对

对 `CATIA_V5_SimpleMacroMenu.catvba` 进行 ASCII/UTF-16LE 名称扫描：

| 指标 | 结果 |
| --- | --- |
| 文件大小 | 4,161,536 字节 |
| SHA-256 | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` |
| 文本模块名 | 77 |
| 二进制中检出 | 77/77 |
| `OTH_INSNAME` | 检出 |
| `PNMmgr` | 检出 |
| `btn_leafcopy_click` | 检出 |
| `CAT_Filepath.findme` | 检出 |

该结果只说明二进制目录/字符串中存在相应符号，不能证明：

- 内嵌源码与文本导出逐字一致；
- `Cat_Macro_Menu_View.frm` 中的当前实现已进入二进制；
- VBA 工程可以完整编译；
- CATIA COM 路径能成功执行。

尝试使用 OLE/VBA 解压工具做源码级比对时，审查环境无法完成其依赖安装，因此没有把符号扫描提升为源码一致性结论。

### 3.5 隔离复现发布流程

没有在真实工作区或远端执行发布。审查在系统临时目录创建本地隔离克隆，按 [`Docs/发版.md:1`](发版.md#L1) 的步骤执行：

```powershell
git switch --create main origin/main
git merge --squash origin/dev --allow-unrelated-histories
git checkout --theirs -- .
git add -A
git diff --cached --shortstat origin/dev
git diff --cached --no-renames --name-status origin/dev
git write-tree
git rev-parse "origin/dev^{tree}"
```

结果：

- 合并产生 14 个增量文件的冲突/变化；
- `checkout --theirs` 解决冲突后，`main` 独有路径仍保留；
- 暂存树相对 `origin/dev` 多出 **263 个文件、38,947 行**；
- 暂存树哈希 `57ca4826...` 与 `dev` 树哈希 `69d0c991...` 不同。

这使 F-07 从 Git 语义推断升级为当前仓库数据的隔离实证。

### 3.6 外部资料交叉验证

本次只把外部资料用于核对语言/工具契约，缺陷本身仍由当前仓库代码和可复现实验确认。

| 事实 | 参考 |
| --- | --- |
| `Option Explicit` 下未声明变量是编译错误 | [Microsoft VBA Option Explicit](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/option-explicit-statement) |
| `IIf` 总是求值 true/false 两侧 | [Microsoft VBA IIf](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/iif-function) |
| `Replace` 的 find 为空时返回原表达式 | [Microsoft VBA Replace](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/replace-function) |
| MSForms Name 必须以字母开头且只含字母、数字、下划线 | [Microsoft Forms 合法对象名](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/not-a-legal-object-nameitem) |
| `Controls.Add`/`Pages.Add` 的 Name 与 Caption 是不同参数 | [Microsoft Forms Add](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/add-method-microsoft-forms) |
| `Filter` 返回匹配元素数组，`UBound` 需要有效数组维度 | [Microsoft VBA Filter](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/filter-function)、[UBound](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/ubound-function) |
| `--allow-unrelated-histories` 只允许无共同祖先合并 | [Git merge](https://git-scm.com/docs/git-merge) |
| `--theirs` 只取索引中的 unmerged stage 3 路径 | [Git checkout](https://git-scm.com/docs/git-checkout.html) |
| CATIA `HSOSynchronized=False` 后必须恢复 True；`RefreshDisplay=False` 禁用脚本回放刷新 | [CATIA Application Automation](https://catiadesign.org/_doc/V5Automation/generated/interfaces/InfInterfaces/interface_Application_17729.htm) |
| 同层实例名必须唯一，`!`、`:`、空名和前导空格不应作为实例名/零件号 | [CATIA Product Structure：修改组件属性](https://catia-v5-help.anarkia333data.center/online/pstug_C2/pstugbt0307.htm) |
| 同文档同 Part Number 会产生冲突 | [CATIA Product Structure：插入已有组件](https://catia-v5-help.anarkia333data.center/online/pstug_C2/pstugbt0304.htm) |

CATIA 链接为公开的 Dassault Systèmes V5 帮助镜像；页面本身标注 Dassault Systèmes 版权。动态行为仍需在项目支持的 CATIA 版本中验证。

## 4. P1 发现

### F-01 [P1] 文本源码的主菜单使用非法且重复的 MSForms 对象名

**归因：基线遗留；现有报告漏报。**

证据：

- [`A00_Menu.bas:9`](../Src/A00_Menu.bas#L9) 定义页面显示名 `R&W`；
- [`Cat_Macro_Menu_View.frm:67`](../Src/Cat_Macro_Menu_View.frm#L67) 将显示名赋给 `pName`；
- [`Cat_Macro_Menu_View.frm:198`](../Src/Cat_Macro_Menu_View.frm#L198) 同时把 `pName` 作为 Page.Name 和 Caption；
- [`Cat_Macro_Menu_View.frm:71`](../Src/Cat_Macro_Menu_View.frm#L71) 把数值组号 `key` 传给 `Init_Button`；
- [`Cat_Macro_Menu_View.frm:150`](../Src/Cat_Macro_Menu_View.frm#L150) 将该 Long 直接作为 `Controls.Add` 的 Name；
- 同一页内每个按钮都使用同一个组号，因此即使数值名被宿主容忍，第二个按钮也会重名。

Microsoft Forms 要求对象名以字母开头，仅包含字母、数字和下划线；Name 与 Caption 是不同参数。当前代码同时违反合法字符、首字符和唯一性约束。

静态扫描确认有 42 个有效菜单入口，`A00_Menu.CATMain` 会实际进入此构建路径。`Set_FormInfo` 没有错误处理，失败会直接中止主菜单。

**影响**

- 从当前文本源码重新导入/构建的主菜单无法可靠创建；
- 这是主入口级阻断，高于局部工具栏问题；
- 已有 CATVBA 是否包含同一实现尚未做源码级解压，因此本报告不把此结论扩展为“现有二进制已动态失败”。

**建议**

- Page.Name 使用稳定合法 ID，例如 `pg_1`；`R&W` 只作为 Caption；
- 按钮 Name 使用唯一合法 ID，例如 `btn_<module_name>`，必要时追加序号；
- 构建前静态验证 `^[A-Za-z][A-Za-z0-9_]{0,39}$` 和同一容器内唯一性；
- 在 CATIA 中从文本源码重建后执行 `A00_Menu.CATMain` 冒烟测试。

### F-02 [P1] 两个后缀模块在 `Option Explicit` 下使用未声明的 `purePN`

**归因：`OTH_INSNAME` 为增量新增；`OTH_PrePn` 为基线遗留。**

证据：

- [`OTH_INSNAME.bas:87`](../Src/OTH_INSNAME.bas#L87) 使用 `purePN`，该过程只声明 `pn/newPn`；
- [`OTH_PrePn.bas:88`](../Src/OTH_PrePn.bas#L88) 存在同样问题；
- 两个模块均启用 `Option Explicit`；
- 没有可供这两个私有过程使用的模块级或公共 `purePN` 声明。

**影响**

VBA 完整编译产生 “Variable not defined”。实例名后缀和零件号后缀路径不可用，并可能阻止整个项目完成编译。

**建议**

在两个 `c_pn_suffix` 中声明 `Dim purePN As String`，随后继续修复 F-03；仅补声明不足以使无分隔符路径可用。

### F-03 [P1] 无 `_._` 的名称会让后缀批改触发运行时错误

**归因：当前调用在新增实例名功能中扩大；帮助函数为基线遗留。**

证据：

- [`KCL.bas:865`](../Src/KCL.bas#L865) 至 [`:868`](../Src/KCL.bas#L868)：

```vb
pos = InStr(istr, ikey)
StrBF = IIf(pos > 0, Left(istr, pos - 1), istr)
```

- `pos=0` 时 true 分支变成 `Left(istr, -1)`；
- VBA `IIf` 即使返回 false 分支，也会求值两侧；
- 两个后缀过程分别在 [`OTH_INSNAME.bas:87`](../Src/OTH_INSNAME.bas#L87) 和 [`OTH_PrePn.bas:88`](../Src/OTH_PrePn.bas#L88) 调用 `StrBF`。

**触发**

补好 F-02 后，对任一不包含 `_._` 的实例名或零件号执行后缀模式。

**影响**

触发 Error 5；若前序节点已改名，递归会中断并留下部分修改结果。

**建议**

不要用 `IIf` 包裹可能失败的表达式：

```vb
If pos > 0 Then
    StrBF = Left$(istr, pos - 1)
Else
    StrBF = istr
End If
```

增加含分隔符、不含分隔符、空字符串、分隔符位于首尾的单元级测试。

### F-04 [P1] 子产品“复制后黏贴”对未初始化对象调用 `Add/Copy`

**归因：基线遗留；增量修改该过程但未修复。**

证据：

- [`ASM_ChildMng.bas:33`](../Src/ASM_ChildMng.bas#L33) 只声明局部 `osel`；
- [`:47`](../Src/ASM_ChildMng.bas#L47)、[`:49`](../Src/ASM_ChildMng.bas#L49)、[`:55`](../Src/ASM_ChildMng.bas#L55) 直接调用 `osel.Add/Copy/Paste`；
- 该过程没有任何 `Set osel = ...`；
- `btn_delete_click` 中的同名局部对象是另一个过程作用域，不能复用。

**影响**

第一次 `osel.Add` 即产生 Object required，普通复制路径必然失败。

**建议**

- 每次回调绑定并验证当前活动文档的 Selection；
- 明确复制“直接子项”还是“搜索到的整棵子树”，不要在同一个 Selection 中同时叠加两套语义；
- 普通复制、叶子复制、源选择取消、目标选择取消、跨文档切换分别做 CATIA 冒烟测试。

### F-05 [P1] 复制结束/异常把 CATIA 留在禁刷新、手动更新状态

**归因：普通复制为基线遗留；新增叶子复制复制了同一模式；原报告描述方向不准确。**

证据：

- [`ASM_ChildMng.bas:36`](../Src/ASM_ChildMng.bas#L36) 和 [`:98`](../Src/ASM_ChildMng.bas#L98) 在开始时调用 `CATquick(False)`；
- 成功和异常分别在 [`:60`](../Src/ASM_ChildMng.bas#L60)、[`:64`](../Src/ASM_ChildMng.bas#L64)、[`:121`](../Src/ASM_ChildMng.bas#L121)、[`:125`](../Src/ASM_ChildMng.bas#L125) 调用 `CATquick(True)`；
- [`KCL.bas:1232`](../Src/KCL.bas#L1232) 至 [`:1246`](../Src/KCL.bas#L1246) 表明：
  - True：`RefreshDisplay=False`、`AutoUpdateMode=0`、`HSOSynchronized=False`、显示精度 5；
  - False：`RefreshDisplay=True`、`AutoUpdateMode=1`、`HSOSynchronized=True`、显示精度 0.2。

因此当前顺序不是“开始快速、结束恢复”，而是开始设为正常、结束设为快速。

正常取消进入错误标签时 `Err.Number=0`，不会调用末尾 `CATquick(True)`，所以原报告“取消时没有恢复”并不准确。真正的问题是所有路径都没有保存调用前状态；成功/异常在默认正常态下会确定地污染后续 CATIA 会话。

CATIA Automation 文档明确要求使用 `HSOSynchronized=False` 后重置为 True，且建议在交互前恢复。

**影响**

后续模型可能不刷新、不自动更新，自动化 Selection 与 UI 高亮不同步，显示精度保持粗化。

**建议**

- 进入前读取并保存四项原值；
- 所有成功、取消、异常统一进入一个清理段；
- 清理段恢复原值，而不是写死 True/False；
- 不要把 `CATquick` 的返回值当作状态快照。

### F-06 [P1] 批量改名边写边走且无预检/回滚，可留下半改名装配树

**归因：实例名路径为增量新增；零件号路径为现有功能扩展。**

写入点：

- 实例名：[`OTH_INSNAME.bas:71`](../Src/OTH_INSNAME.bas#L71)、[`:89`](../Src/OTH_INSNAME.bas#L89)、[`:106`](../Src/OTH_INSNAME.bas#L106)、[`:125`](../Src/OTH_INSNAME.bas#L125)；
- 零件号：[`OTH_PrePn.bas:72`](../Src/OTH_PrePn.bas#L72)、[`:90`](../Src/OTH_PrePn.bas#L90)、[`:107`](../Src/OTH_PrePn.bas#L107)、[`:126`](../Src/OTH_PrePn.bas#L126)。

当前实现：

1. 递归到一个节点；
2. 立即计算并赋值新名称；
3. 再处理后续节点；
4. 没有统一错误处理或回滚。

输入校验只把包含占位词“字符”的输入视为无效，没有检查 CATIA 禁止字符、前导空格、空目标、同级实例名唯一性或 Part Number 冲突。

例如同级实例名 `AB` 与 `B` 执行删除 `A`，第一个目标会变成 `B`，与现有兄弟冲突。若更早节点已成功修改，后续冲突/非法目标被 CATIA 拒绝时，已完成的赋值不会自动回滚。

**影响**

模型处于部分迁移状态，用户无法仅凭“完成/失败”消息恢复原命名；关联引用与人工排查成本较高。

**建议**

- 第一阶段只收集 `对象、原值、目标值、父级/引用标识`；
- 在任何写入前验证合法字符、空值、同级实例唯一性、Part Number 冲突和目标映射碰撞；
- 第二阶段应用变更；任一失败按原值逆序回滚；
- 输出成功、跳过、失败和回滚清单；
- 对大装配先提供预览/确认。

### F-07 [P1] 无共同祖先的发布步骤不会删除 `main` 独有旧文件

**归因：全分支发布流程风险。**

[`Docs/发版.md:1`](发版.md#L1) 至 [`:5`](发版.md#L5) 使用：

```powershell
git merge --squash dev --allow-unrelated-histories
git checkout --theirs -- .
git add -A
```

Git 文档说明 `--theirs` 针对冲突索引中的 stage 3 路径；它不会凭空为仅存在于 `main` 的路径生成删除记录。

当前仓库实证：

- `main@efbcb6e` 有 486 个文件；
- 对应源 `dev@158a076` 有 223 个文件；
- `main -> 158a076` 有 263 个纯删除路径；
- 按当前发版文档在隔离克隆发布到 `dev@abce8ff` 后，暂存树相对 `dev` 仍额外包含 263 个文件、38,947 行。

**影响**

- 发布分支不再是记录源 `dev` 的可验证快照；
- 已删除的旧模块、参考工程和资源持续留在 `main`；
- 审查产生数万行伪差异；
- 普通合并/PR 仍无共同历史。

**建议**

首选让 `main/dev` 共享历史。若必须保留独立发布快照：

- 显式构造与目标 `dev` 完全相同的索引/工作树；
- 提交前执行 `git diff --cached --quiet <dev-sha> --`；
- 比较 `git write-tree` 与 `git rev-parse "<dev-sha>^{tree}"`；
- 任一不一致即停止发布。

### F-08 [P1] 模块导入与覆盖导出均“先删除、后尝试”，且导入会被正常 FRX 确定性中断

**归因：全分支工具链风险；原报告只覆盖了部分情形。**

导入路径：

- [`Cls_VbaMdlMgr.cls:210`](../Src/Cls_VbaMdlMgr.cls#L210) 先 `remove_modules`；
- [`:211`](../Src/Cls_VbaMdlMgr.cls#L211) 后 `import_modules`；
- [`:241`](../Src/Cls_VbaMdlMgr.cls#L241) 在任何 Import 前枚举目录；
- [`:274`](../Src/Cls_VbaMdlMgr.cls#L274) 对每个扩展名执行 `UBound(Filter(targetExtensions, ext))`；
- 导入允许 `cls/frm/bas`，但正常 UserForm 导出目录还包含 `.frx`；当前 `Src` 就有 4 个；
- `Filter` 对 `frx` 返回空数组，`UBound` 没有可用维度，产生下标错误；
- 即使越过枚举，[`:251`](../Src/Cls_VbaMdlMgr.cls#L251) 至 [`:253`](../Src/Cls_VbaMdlMgr.cls#L253) 仍会静默忽略逐文件导入失败。

因此对包含 UserForm 的正常导出目录，当前顺序是：

1. 删除目标工程模块；
2. 在建立导入清单时遇到 `.frx`；
3. 在任何新模块导入前中断；
4. 工具内没有回滚。

UI 在 [`VbaModuleManegerView.frm:90`](../Src/VbaModuleManegerView.frm#L90) 至 [`:92`](../Src/VbaModuleManegerView.frm#L92) 禁止对当前 `CAT_MENU` 工程点击导入，所以风险主要影响其他已登记项目或直接 API 调用；一旦用户保存受影响工程，残缺状态会持久化。

覆盖导出路径：

- [`Cls_VbaMdlMgr.cls:369`](../Src/Cls_VbaMdlMgr.cls#L369) 先删除 `cls/frm/frx/bas` 源文件；
- [`:370`](../Src/Cls_VbaMdlMgr.cls#L370) 才导出；
- [`:315`](../Src/Cls_VbaMdlMgr.cls#L315) 至 [`:323`](../Src/Cls_VbaMdlMgr.cls#L323) 任一 Export 失败即提前退出；
- [`VbaModuleManegerView.frm:42`](../Src/VbaModuleManegerView.frm#L42) 至 [`:44`](../Src/VbaModuleManegerView.frm#L44) 无条件显示覆盖完成。

**建议**

- 删除/覆盖前先建立完整清单并验证扩展名、FRM/FRX 配对、重复模块名和可读性；
- 导入到临时/备份工程，或先导出可恢复快照；
- 导出到同级临时目录，全部成功后再原子替换目标目录；
- 每个操作返回明确 Boolean/结果对象，UI 只在全部成功后提示完成；
- 成功后核对模块名、数量、必要入口和文件哈希。

## 5. P2 发现

### F-09 [P2] 改名模式可未选/多选，空查找串也会被报告为成功

**归因：替换模式为增量新增；模式选择问题由既有 CheckBox 设计延续。**

证据：

- [`OTH_INSNAME.bas:47`](../Src/OTH_INSNAME.bas#L47) 至 [`:55`](../Src/OTH_INSNAME.bas#L55)；
- [`OTH_PrePn.bas:48`](../Src/OTH_PrePn.bas#L48) 至 [`:56`](../Src/OTH_PrePn.bas#L56)；
- 四个模式是相互独立的 CheckBox，但代码用 `ElseIf` 只执行首个为 True 的分支；
- 未选择任何模式时仍执行末尾“批量修改完成”；
- 替换模式没有要求 `oldstr` 非空；
- [`OTH_INSNAME.bas:123`](../Src/OTH_INSNAME.bas#L123) 和 [`OTH_PrePn.bas:124`](../Src/OTH_PrePn.bas#L124) 调用 `Replace(pn, "", istr)` 时，VBA 按文档返回原字符串。

**影响**

- 未选模式：无修改但提示成功；
- 多选模式：静默按 `prefix > suffix > delete > replace` 取第一项；
- 替换旧串为空：整棵树不变但提示成功；
- 用户无法从成功消息判断实际变更数。

**建议**

使用 OptionButton 或在提交前校验“恰好选择一个模式”；替换模式强制非空旧串；完成消息显示实际变化、跳过、失败数量。

### F-10 [P2] 非模态普通复制持有打开工具栏时的旧 Selection

**归因：增量修改普通/叶子复制时引入不一致。**

证据：

- [`ASM_ChildMng.bas:23`](../Src/ASM_ChildMng.bas#L23) 打开工具栏时只调用一次 `initmVar`；
- [`:26`](../Src/ASM_ChildMng.bas#L26) 工具栏为 ShowToolbar；
- [`Cls_DynaWD.cls:227`](../Src/Cls_DynaWD.cls#L227) 明确使用 `vbModeless`；
- 普通复制回调 [`ASM_ChildMng.bas:32`](../Src/ASM_ChildMng.bas#L32) 不重新绑定；
- `KCL.SelectItem` 使用当前活动文档，而模块级 `msel` 仍可能属于打开工具栏时的旧文档；
- 叶子复制在 [`ASM_ChildMng.bas:94`](../Src/ASM_ChildMng.bas#L94) 重新调用 `initmVar`，行为不一致。

**触发**

在文档 A 打开工具栏，切换到文档 B 后点击普通复制。

**影响**

选择发生在文档 B，后续 Selection 操作仍指向文档 A，可能失败或操作错误文档。

**建议**

每个回调开始时重新绑定当前文档，并记录工具栏创建时文档身份；如果文档已切换，应明确拒绝或提示重新打开工具栏。

### F-11 [P2] 材料颜色工具栏包含重复控件名

**归因：基线遗留。**

证据：

- [`MDL_MaterialColors.bas:12`](../Src/MDL_MaterialColors.bas#L12) 定义 `lb_steel`；
- [`:19`](../Src/MDL_MaterialColors.bas#L19) 再次定义 `lb_steel`；
- [`CAT_springWD.frm:47`](../Src/CAT_springWD.frm#L47) 将配置名直接传给 `Controls.Add`，周围没有错误处理。

MSForms 同一容器内控件名必须唯一。创建第二个标签时工具栏构建中断。

**建议**

将第二个分隔标签改为唯一名，例如 `lb_aluminum`；把重复 `%UI` 名称检查加入静态门禁。

### F-12 [P2] 三个默认工具栏按钮没有匹配回调，且分发器静默吞错

**归因：基线遗留；现有报告漏掉 `MDL_eleRename`。**

默认规则：

- [`Cls_DynaWD.cls:468`](../Src/Cls_DynaWD.cls#L468) 映射为 `按钮名 + "_click"`。

人工确认的失效项：

| 模块 | 按钮 | 默认目标 | 实际情况 |
| --- | --- | --- | --- |
| `ASM_ChildMng` | `btn_cancel` | `btn_cancel_click` | 不存在 |
| `OTH_ivhideshow` | `ONLYsel_child_show` | `ONLYsel_child_show_click` | [`OTH_ivhideshow.bas:78`](../Src/OTH_ivhideshow.bas#L78) 实现缺少 `_click` |
| `MDL_eleRename` | `btncancel` | `btncancel_click` | 不存在 |

[`Cls_allBTNEVT.cls:90`](../Src/Cls_allBTNEVT.cls#L90) 至 [`:101`](../Src/Cls_allBTNEVT.cls#L101) 对 `ExecuteScript` 使用 `On Error Resume Next`，随后清除错误，不向用户或日志暴露模块、入口、错误号。

`MDL_BdyDel` 没有列入正式失效项：它虽然先调用 ShowToolbar，但紧接着读取 Results，内部会转入模态结果模式；这是静态候选而非同一真实路径，避免把启发式扫描结果当作缺陷。

**影响**

三个按钮表现为无响应；相同分发模式下的未来拼写错误也会被隐藏。

**建议**

- 统一按钮/回调名；
- 工具栏构建时验证目标过程存在；
- 分发器至少记录项目、模块、入口、错误号和描述；
- 取消按钮应有通用关闭行为，而不是依赖每个模块重复实现。

### F-13 [P2] 翻译失败被计为成功，且同步发送模型名称

**归因：全分支潜在工具风险；该模块没有 `{GP:}`，不是默认主菜单入口。**

证据：

- [`MDL_translateRename.bas:36`](../Src/MDL_translateRename.bas#L36) 调用翻译；
- [`:38`](../Src/MDL_translateRename.bas#L38) 赋值成功即在 [`:39`](../Src/MDL_translateRename.bas#L39) 增加 `gOK`；
- [`:83`](../Src/MDL_translateRename.bas#L83) 至 [`:89`](../Src/MDL_translateRename.bas#L89) 把名称作为 Google URL 查询参数同步发送；
- [`:110`](../Src/MDL_translateRename.bas#L110) 至 [`:111`](../Src/MDL_translateRename.bas#L111) 请求/解析失败时返回原文。

范围修正：代码跳过包含中文的名称，只发送未检测到中文的 HybridBody/HybridShape 名称；但英文项目名、客户代号和零件标识仍可能敏感。

**影响**

- 请求失败时把原名重新赋回通常仍成功，因此失败计入成功；
- 同步 HTTP 调用阻塞 CATIA；
- 没有明确超时、缓存、失败清单或数据外发说明。

**建议**

翻译函数返回 `成功状态 + 结果 + 错误`；原文等于结果或请求失败不得计成功；增加明确确认、超时、缓存、失败清单和离线模式。

## 6. 对原报告的纠正与排除项

### 6.1 已纠正

1. **`CATquick` 方向**
   原报告强调取消时未恢复；复核确认成功/异常才会在默认状态下把 CATIA 留在快速模式，取消路径反而停在开始设置的正常态。根因是没有保存/恢复原值。

2. **模块导入触发条件**
   原报告写“任意导入失败可能残缺”；复核确认包含 UserForm 的正常目录会因 `.frx + UBound(Filter())` 在任何导入前确定性中断。

3. **翻译数据范围**
   原报告笼统写“结构树名称”；当前实现只处理未检测到中文的 HybridBody/HybridShape 名称，但外发与统计问题仍成立。

4. **增量归因**
   `OTH_PrePn.purePN` 与普通复制 `osel` 在 `158a076` 已存在；本次增量复制、扩展或未修复它们，而非首次引入。

### 6.2 已排除或降级

- `CAT_Filepath` 的标签前有两个单引号，但 `cls_MnUI.InitFromCode` 是对声明区内 `{...}` 做正则扫描，不要求恰好一个注释符；不能仅凭双单引号判定菜单项消失。
- `.github/workflows/auto-release.yml` 和 `Docs/发版.md` 为 GBK 而非 UTF-8，严格 UTF-8 解码失败，且 [YAML 1.2.2 编码规范](https://yaml.org/spec/1.2.2/#52-character-encodings) 不定义 GBK；但[远端仓库主页](https://github.com/verysolecd/Macro_menu)显示已有 `v0.1.12` Release，因此没有把“工作流必然不运行”列为正式缺陷，只保留为可移植性风险。
- CATVBA 中能找到模块/入口符号，不代表源码一致或编译通过；同样，文本源码中的 F-01 也不能在未解压/未运行二进制时直接外推为现有 CATVBA 已动态失败。

## 7. 其他质量与可维护性观察

以下不单独定为阻断项，但会提高误报、漏报和维护成本：

- 77 个文本模块中 42 个缺少 `Option Explicit`；
- 168 个活跃 `On Error Resume Next`；
- 增量有 9 处 `git diff --check` 问题；
- 没有自动化测试目录或可执行测试；
- 唯一 GitHub Actions 工作流只创建 Release，没有静态检查、编译检查或测试门禁；
- `.gitignore` 使用 GBK 与尾部反斜杠，`rg` 报 “dangling '\'” 和非法 UTF-8；应改为 UTF-8 与正斜杠模式；
- 源码、Markdown、YAML 混用 GBK/UTF-8，标准工具读取结果不一致；
- 4 个 FRX 在增量中变化，但对应 FRM 文本未变化；无法仅凭二进制差异解释具体设计器变化；
- 根目录同时存在 `CATIA_V5_SimpleMacroMenu.catvba` 与 `CAT_menu.catvba`，正式产物边界不够明确。

## 8. 已完成与未完成的验证

### 8.1 已完成

- 当前分支、HEAD、本地/远端 `dev/main` SHA；
- 工作区初始干净状态；
- 根提交与 merge-base；
- 增量提交、逐文件差异、格式检查；
- 主菜单 Page/Button 名称完整调用链；
- `Option Explicit/purePN` 编译规则；
- `IIf/Replace/Filter/UBound` 语言契约；
- 子产品复制对象初始化与 CATquick 状态流；
- 批量改名目标写入顺序和 CATIA 命名约束；
- 默认工具栏回调映射；
- 模块导入、覆盖导出删除/失败顺序；
- 主 CATVBA 模块名和关键符号；
- 发布命令的隔离端到端树复现；
- 远端仓库主页与最新 Release 的只读核对。

### 8.2 未完成，不能据此声称通过

- CATIA V5 中加载当前 CATVBA；
- VBA 编辑器“调试 → 编译”；
- 从 `Src` 全量导入并重建 CATVBA；
- 主菜单真实渲染；
- 普通复制、叶子复制、删除、源/目标取消、跨文档切换；
- 实例名与零件号四种模式的完整回归；
- 冲突改名的回滚；
- 材料颜色与三个缺失回调按钮；
- 模块导入/覆盖导出的失败恢复；
- Google 翻译成功、超时、失败和隐私确认；
- GitHub 标签发布的全链路重跑。

审查时没有运行 CNEXT/CATIA 进程，也没有修改 CATIA 文档、VBA 工程、业务源码、CATVBA 或远端状态。

## 9. 修复顺序

### 第一阶段：恢复可构建和主路径

1. 修复 F-01 的 Page/Button Name；
2. 修复 F-02 的两个 `purePN`；
3. 修复 F-03 的 `StrBF`；
4. 在 CATIA VBA 编辑器完整编译；
5. 从文本源码重建后验证主菜单。

### 第二阶段：阻止破坏性部分结果

1. 修复 F-04 的 Selection 初始化与复制语义；
2. 按 F-05 保存并恢复 CATIA 原状态；
3. 把批量改名改成预计算、验证、应用、回滚两阶段流程；
4. 把模块导入/覆盖导出改成可验证、可回滚流程。

### 第三阶段：恢复发布可信度

1. 让 `main/dev` 共享历史，或明确实现精确快照发布；
2. 发布前比较目标树哈希；
3. 在 GitHub Actions 增加静态检查、编码检查、模块清单和人工 CATIA 冒烟确认；
4. 明确唯一正式 CATVBA 产物及其 SHA-256。

### 第四阶段：局部功能与可观测性

1. 修复 F-09 至 F-13；
2. 所有动态 UI 构建前验证名称与回调；
3. 将静默 `On Error Resume Next` 替换为局部捕获和可追踪日志；
4. 统一仓库文本编码。

## 10. 最低验收清单

- [ ] 从 `Src` 导入后 VBA 工程完整编译；
- [ ] `A00_Menu.CATMain` 能创建全部页面和 42 个有效入口；
- [ ] 所有 Page/Control Name 合法且唯一；
- [ ] 有/无 `_._` 的前缀、后缀均通过；
- [ ] 替换旧串为空、未选模式、多选模式被明确拒绝；
- [ ] 冲突/非法目标在任何写入前被发现；
- [ ] 中途失败能恢复所有原名称；
- [ ] 普通复制和叶子复制的层级、数量正确；
- [ ] 源/目标选择取消、异常和跨文档切换后状态正确；
- [ ] 复制前后 `RefreshDisplay/AutoUpdateMode/HSOSynchronized/显示精度` 与进入前一致；
- [ ] 材料颜色工具栏可打开；
- [ ] 三个缺失回调按钮有响应；
- [ ] 模块导入能处理 FRM/FRX 配对，失败可恢复；
- [ ] 覆盖导出失败不会删除上一份完整源码；
- [ ] 发布暂存树与记录的 `dev` 树哈希一致；
- [ ] CATVBA 模块数、必要入口、SHA-256 和版本已记录；
- [ ] GitHub Actions 至少执行静态检查和发布树一致性检查；
- [ ] 完成人工 CATIA 冒烟测试并保留版本/引用库矩阵。

## 11. 待项目维护者确认

1. `main` 是否被有意设计为无共同祖先的发布快照分支？
2. `CATIA_V5_SimpleMacroMenu.catvba` 是否是唯一正式产物？`CAT_menu.catvba` 的定位是什么？
3. 发布 CATVBA 是否确实由当前 `Src` 全量导入生成，还是设计器内另有未导出的代码？
4. 目标 CATIA V5 版本、VBA7/64 位环境和引用库组合是什么？
5. 批量改名是否有正式命名规范，`_._` 与 `_Rev..._` 是否为强制格式？
6. 是否允许把非中文几何名称发送到 Google 服务？
7. 模块管理器是否允许操作正在执行的工程；正式备份/回滚策略是什么？

## 12. 最终结论

当前分支的文档增量本身不改变业务代码，但其目标 `dev@abce8ff` 仍有主菜单源码构建阻断、明确编译错误、复制对象错误、CATIA 全局状态污染、非事务式批量改名、发布树不一致和模块同步破坏风险。

最少应完成 F-01 至 F-08 的修复，并在 CATIA 中完成“全项目编译、源码重建主菜单、复制/改名回归、发布树哈希验证”后，再考虑合入或发版。现有 CATVBA 的符号清单完整，但在缺少源码级解压和 CATIA 动态执行的情况下，不能把它视为通过验证的可发布产物。
