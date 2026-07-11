# dev 分支深度审查报告

> 审查日期：2026-07-11<br>
> 审查分支：`dev`<br>
> 当前提交：`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`<br>
> 对比基线：`158a0760c3e9027b9a76e8721caf7e717ba244c6`<br>
> 审查方式：只读 Git 审查、源码静态检查、CATVBA 二进制符号核对<br>
> 结论：审查时当前分支与远端同步且工作区干净，但存在 4 项 P1 和 3 项 P2 问题，暂不建议合入或发版。

## 1. 技术摘要

本次审查确认本地 `dev`、本地远端跟踪分支 `origin/dev` 和 GitHub 远端 `dev` 均指向 `abce8ff`。工作区在审查开始和结束时均无未提交源码改动。

由于 `main` 与 `dev` 没有共同祖先，不能使用通常的 `main...dev` 三点比较作为审查基线。本报告采用 `main` 最新发布提交中明确记录的源提交 `158a076` 作为功能基线，审查 `158a076..dev` 的三次增量提交，并以 `main` 和该源提交的直接树比较补充核对发布流程。

主要结论如下：

- 新增的实例名管理与现有零件号管理都在 `Option Explicit` 下使用未声明变量，后缀路径无法通过 VBA 编译。
- 子产品“复制后黏贴”对未初始化的选择对象调用 `Add/Copy`，功能必然失败；取消路径也没有完成状态恢复。
- 当前无共同祖先的发版方法不会删除 `main` 独有文件；上一发布版本已经累积 263 个不属于对应 `dev` 源提交的过期文件。
- VBA 源码导入会先删除全部模块，再静默忽略导入错误，存在把项目留在残缺状态的风险。
- 材料颜色工具栏存在重复控件名；反选隐藏工具栏存在回调名不匹配，且公共事件分发器会隐藏执行错误。
- 翻译重命名会同步向第三方服务发送结构树名称，并将翻译失败统计为成功。
- 主 CATVBA 二进制能检出全部 77 个源码模块名及本次新增入口，但符号存在不等于 VBA 编译成功或源码逐字一致。
- 仓库没有自动化测试，审查环境也未运行 CATIA，因此本报告不能替代 CATIA/VBA 动态回归。

## 2. 审查范围、定义与基线

### 2.1 分支状态

| 项目 | 审查结果 |
| --- | --- |
| 当前本地分支 | `dev` |
| 本地 HEAD | `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad` |
| 本地 `origin/dev` | `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad` |
| 远端 `refs/heads/dev` | `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad` |
| 远端 `refs/heads/main` | `efbcb6e200d68089bfe7b6324daa75b0f177b6c8` |
| 工作区 | 审查时干净；成文后仅新增本报告 |
| `main` 与 `dev` 的 merge-base | 不存在 |

### 2.2 功能增量

`main@efbcb6e` 的提交信息为：

> 发版 v0.1.12 | 源DEV提交: 158a0760c3e9027b9a76e8721caf7e717ba244c6

因此，本次功能审查使用 `158a076..abce8ff`，包含以下提交：

| 提交 | 内容 |
| --- | --- |
| `6480657` | 修改发版说明 |
| `1e6d741` | 修改当前文件路径打开逻辑 |
| `abce8ff` | 新增实例名批量修改并调整子产品管理 |

增量规模为：

| 指标 | 数值 |
| --- | ---: |
| 变更文件 | 14 |
| 新增行 | 248 |
| 删除行 | 87 |
| 新增源码模块 | 1：`OTH_INSNAME` |

### 2.3 严重级别

| 级别 | 定义 |
| --- | --- |
| P1 | 会阻断核心功能、编译、发布一致性，或可能造成破坏性结果；合入或发版前应修复 |
| P2 | 会造成局部功能失效、静默错误、错误统计或明显运维风险；建议在同一修复周期处理 |

## 3. 审查过程

### 3.1 确认分支、远端和工作区

执行：

~~~powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/dev
git ls-remote --heads origin dev main
~~~

结果确认：

- 当前分支为 `dev`；
- 本地 HEAD、本地 `origin/dev`、远端 `dev` 三者 SHA 完全一致；
- `git status --short --branch` 除分支跟踪信息外没有文件记录。

### 3.2 检查分支拓扑

执行：

~~~powershell
git merge-base main dev
git rev-list --max-parents=0 main
git rev-list --max-parents=0 dev
~~~

`git merge-base main dev` 没有返回提交并以失败状态退出。两个分支分别有不同根提交，因此：

- 普通三点差异 `git diff main...dev` 不成立；
- 普通 merge/rebase/PR 比较不能按共同祖先计算；
- 审查必须选取显式源提交或直接比较两棵树。

### 3.3 确定增量审查面

执行：

~~~powershell
git diff --stat 158a076..HEAD
git diff --name-status 158a076..HEAD
git diff --numstat 158a076..HEAD
git show --stat --summary abce8ff
git show --stat --summary 1e6d741
git show --stat --summary 6480657
~~~

随后逐文件读取 GBK/CP936 或 UTF-8 源码，重点审查：

- `Src/OTH_INSNAME.bas`
- `Src/OTH_PrePn.bas`
- `Src/ASM_ChildMng.bas`
- `Src/CAT_Filepath.bas`
- `Src/A00_Menu.bas`
- `Src/Cls_allBTNEVT.cls`
- `Src/Cls_DynaWD.cls`
- `Src/KCL.bas`
- `Docs/发版.md`

### 3.4 执行全分支静态检查

静态检查覆盖：

- 模块 `Attribute VB_Name`；
- `{GP:}`、`{EP:}` 菜单标签和入口过程；
- `%UI` 控件名重复；
- `ShowToolbar` 默认的 `按钮名 + "_click"` 回调约定；
- `Option Explicit` 覆盖情况；
- `On Error Resume Next` 使用数量；
- 最近增量的 `git diff --check`。

结果摘要：

| 检查项 | 结果 | 说明 |
| --- | ---: | --- |
| `Src` 文本模块 | 77 | `.bas/.cls/.frm` |
| 带菜单标签模块 | 47 | 静态正则统计 |
| 静态入口点异常候选 | 2 | `MDL_WeldColor:Yellow_Weld`、`RW_Revise:EditorToolbar` |
| 缺少 `Option Explicit` | 42 | 技术债务指标，不代表全部存在运行错误 |
| `On Error Resume Next` | 168 | 大量错误可能被隐藏 |
| 重复 UI 控件名 | 1 | 手工确认 `MDL_MaterialColors.lb_steel` |
| 默认工具栏缺失回调候选 | 8 | 手工确认本报告列出的失效按钮 |
| `git diff --check` | 失败 | 9 处尾随空格或文件尾空行 |

回调和入口点扫描属于启发式检查：使用自定义映射的工具栏可能形成静态误报，因此只有经代码路径手工确认的问题进入正式发现。

### 3.5 核对源码与 CATVBA 二进制

对根目录主二进制 `CATIA_V5_SimpleMacroMenu.catvba` 执行 ASCII/UTF-16LE 模块名与关键符号扫描：

| 指标 | 结果 |
| --- | --- |
| 文件大小 | 4,161,536 字节 |
| SHA-256 | `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5` |
| 源码模块数 | 77 |
| 二进制中检出的模块名 | 77 |
| `OTH_INSNAME` | 已检出 |
| `PNMmgr` | 已检出 |
| `btn_leafcopy_click` | 已检出 |
| `CAT_Filepath.findme` | 已检出 |

该检查只能证明二进制目录中存在相应名称，不能证明：

- 模块源码与导出文件逐字一致；
- VBA 工程可完整编译；
- CATIA COM 调用能够成功；
- 用户操作路径没有运行时错误。

### 3.6 检查测试和运行环境

执行文件扫描及 CATIA 进程检查后确认：

- 没有自动化测试文件；
- 唯一 GitHub Actions 工作流只负责发布，没有编译或测试门禁；
- 审查时没有 `CNEXT`/CATIA 进程；
- 未调用 Google 翻译接口；
- 未执行会修改 CATIA 文档或 VBA 工程的宏。

本报告使用精确计数表而没有绘制图表，因为数据量小且目的为代码审计，表格更利于逐项复核。

## 4. 关键发现

### F-01 [P1] 实例名和零件号后缀功能无法编译

**证据**

- [`Src/OTH_INSNAME.bas:87`](../Src/OTH_INSNAME.bas#L87) 在 `c_pn_suffix` 中使用 `purePN`；
- [`Src/OTH_PrePn.bas:88`](../Src/OTH_PrePn.bas#L88) 存在同样代码；
- 两个模块都启用了 `Option Explicit`；
- 两个 `c_pn_suffix` 过程均没有声明 `purePN`，项目其他位置也没有可供这两个过程使用的公共声明。

**影响**

VBA 编译或执行到相关模块时会产生“Variable not defined”。新增的实例名管理后缀路径以及零件号管理后缀路径不可用。CATVBA 二进制包含这些模块名，但这不能消除编译错误。

**建议**

在两个 `c_pn_suffix` 过程中显式声明 `purePN As String`，然后执行完整的 VBA 工程编译，并分别验证包含和不包含 `_._` 分隔符的名称。

### F-02 [P1] 子产品“复制后黏贴”使用未初始化对象

**证据**

- [`Src/ASM_ChildMng.bas:33`](../Src/ASM_ChildMng.bas#L33) 仅声明 `osel`；
- [`Src/ASM_ChildMng.bas:47-49`](../Src/ASM_ChildMng.bas#L47) 直接调用 `osel.Add`、`osel.Copy`；
- `btn_copy_click` 内部没有任何 `Set osel = ...`；
- `btn_delete_click` 中初始化的是另一个过程作用域内的局部 `osel`，不能供复制过程使用。

**影响**

“复制后黏贴”在第一次访问 `osel` 时产生 Object required，无法完成复制。

同一模块的取消路径也存在清理缺口：

- [`Src/ASM_ChildMng.bas:42`](../Src/ASM_ChildMng.bas#L42) 和 [`Src/ASM_ChildMng.bas:52-53`](../Src/ASM_ChildMng.bas#L52) 在用户取消时跳到 `ErrorHandler`；
- [`Src/ASM_ChildMng.bas:62-67`](../Src/ASM_ChildMng.bas#L62) 只有 `Err.Number <> 0` 才执行 `CATquick(True)`；
- 正常取消没有错误号，因此不会执行预期收尾。

新增的叶子复制路径也使用同样的取消处理结构。

**建议**

- 为复制过程显式绑定活动文档的 `Selection`；
- 将正常退出、用户取消和异常退出统一汇入无条件清理段；
- 保存并恢复调用前的 CATIA 显示、自动更新和 HSO 设置，而不是假设固定状态。

### F-03 [P1] 发版流程不会删除 main 中的过期文件

**证据**

[`Docs/发版.md:1-5`](发版.md#L1) 使用：

~~~powershell
git merge --squash dev --allow-unrelated-histories
git checkout --theirs -- .
git add -A
~~~

由于两个分支没有共同祖先，`main` 独有路径会被视为本方已有内容，而不是由 `dev` 删除的内容。`checkout --theirs` 也没有可用于删除这些路径的“对方版本”。

实证比较：

~~~powershell
git diff --shortstat main 158a076
~~~

结果为：

> 263 files changed, 38947 deletions(-)

这里的方向是从 `main` 变为对应源 `dev@158a076`，因此表示 `main` 多保留了 263 个文件。

**影响**

- 正式分支源码不能准确表示发布二进制来源；
- 已从 `dev` 删除的旧模块、参考项目和资源会继续留在 `main`；
- 后续审查出现数万行伪差异；
- 普通合并和 PR 比较持续缺少共同祖先。

**建议**

重新设计 `main` 与 `dev` 的关系，优先选择同一历史上的发布分支。如果必须保留独立发布历史，发布步骤必须显式构造与目标 `dev` 提交完全相同的树，并在提交前执行树一致性检查。

### F-04 [P1] VBA 模块导入可能留下不可恢复的残缺工程

**证据**

- [`Src/Cls_VbaMdlMgr.cls:210-211`](../Src/Cls_VbaMdlMgr.cls#L210) 先执行 `remove_modules`，再执行 `import_modules`；
- [`Src/Cls_VbaMdlMgr.cls:292-295`](../Src/Cls_VbaMdlMgr.cls#L292) 删除目标项目的所有受管模块；
- [`Src/Cls_VbaMdlMgr.cls:250-253`](../Src/Cls_VbaMdlMgr.cls#L250) 对每次导入使用 `On Error Resume Next`，且不记录失败。

**影响**

任意一个 `.bas`、`.cls` 或 `.frm/.frx` 文件损坏、缺失、重名或依赖不满足，都可能在旧模块已经删除后导入失败。调用方无法知道失败模块，也没有自动回滚。

**建议**

- 删除前先枚举并验证完整导入集合；
- 导入到临时/备份工程或先导出可恢复快照；
- 收集每个导入结果，任一失败即停止并恢复；
- 成功后核对模块名、数量和必要入口点。

### F-05 [P2] 材料颜色工具栏包含重复控件名

**证据**

- [`Src/MDL_MaterialColors.bas:12`](../Src/MDL_MaterialColors.bas#L12) 定义 `lb_steel`；
- [`Src/MDL_MaterialColors.bas:19`](../Src/MDL_MaterialColors.bas#L19) 再次定义 `lb_steel`；
- [`Src/CAT_springWD.frm:47`](../Src/CAT_springWD.frm#L47) 使用配置中的名称动态执行 `Controls.Add`。

**影响**

MSForms 控件名必须唯一。创建第二个 `lb_steel` 时工具栏构建会中断，材料颜色功能可能无法打开。

**建议**

将第二个分隔标签改为唯一名称，并增加静态检查，阻止同一模块内重复的 `%UI` 名称进入二进制。

### F-06 [P2] 工具栏回调名不匹配且错误被公共分发器隐藏

**证据**

- [`Src/OTH_ivhideshow.bas:16`](../Src/OTH_ivhideshow.bas#L16) 定义按钮 `ONLYsel_child_show`；
- [`Src/Cls_DynaWD.cls:456-468`](../Src/Cls_DynaWD.cls#L456) 默认映射为 `按钮名 + "_click"`；
- 实际实现为 [`Src/OTH_ivhideshow.bas:78`](../Src/OTH_ivhideshow.bas#L78) 的 `ONLYsel_child_show`，缺少 `_click`；
- [`Src/Cls_allBTNEVT.cls:90-101`](../Src/Cls_allBTNEVT.cls#L90) 对 `ExecuteScript` 使用 `On Error Resume Next` 并无条件清除错误。

**影响**

“仅显示选定（含子树）”按钮调用不存在的过程，用户只看到按钮无响应。公共分发器隐藏错误，使这类映射问题难以诊断。静态检查还确认 `ASM_ChildMng` 的 `btn_cancel` 没有对应回调。

**建议**

- 统一按钮名和过程名；
- 在工具栏构建阶段验证目标回调是否存在；
- 分发器至少记录模块、入口、错误号和错误描述，不应无条件清除错误。

### F-07 [P2] 翻译失败被统计为成功，模型名称会发送至第三方

**证据**

- [`Src/MDL_translateRename.bas:36-40`](../Src/MDL_translateRename.bas#L36) 将翻译返回值赋给对象名称，赋值成功即增加 `gOK`；
- [`Src/MDL_translateRename.bas:83-89`](../Src/MDL_translateRename.bas#L83) 将名称作为 URL 查询参数同步发送至 Google；
- [`Src/MDL_translateRename.bas:110-111`](../Src/MDL_translateRename.bas#L110) 在请求或解析失败时返回原始名称。

**影响**

请求失败时，原名称重新赋值通常仍会成功，因此失败会被计为成功。逐名称同步 HTTP 请求还会阻塞 CATIA；结构树名称可能包含项目、零件或客户信息，当前确认提示没有明确说明数据会离开本机。

**建议**

- 让翻译函数返回“成功状态 + 翻译结果 + 错误信息”；
- 原文与译文相同或请求失败时不得增加成功数；
- 明确提示第三方数据传输并允许用户取消；
- 增加超时、缓存、批处理和失败清单；
- 对敏感项目提供完全离线的替代模式。

## 5. 其他质量指标

以下指标不单独作为阻断项，但会显著提高缺陷发现和维护成本：

- 77 个文本模块中有 42 个缺少 `Option Explicit`；
- 静态统计共有 168 处 `On Error Resume Next`；
- 最近增量存在 9 处 `git diff --check` 格式问题；
- 没有测试目录或可执行测试文件；
- 发布工作流没有源码静态检查、VBA 编译检查或 CATVBA 一致性检查；
- 根目录同时存在多个 CATVBA 文件，需持续明确哪个是唯一正式产物。

这些指标不意味着每一处都需要立即重构，但新代码不应继续增加相同技术债务。

## 6. 验证限制与稳健性说明

### 已完成的验证

- 本地、跟踪分支和远端 SHA 一致性；
- 工作区干净状态；
- 分支根和 merge-base；
- 增量提交和逐文件差异；
- 菜单标签、入口、动态 UI 和默认回调静态检查；
- 关键缺陷的过程级变量与控制流复核；
- 主 CATVBA 二进制模块名和关键符号检查；
- 发布源提交与 `main` 树差异计数。

### 未完成且不能据此声称通过的验证

- CATIA V5 中加载 CATVBA；
- VBA 菜单中的“调试 → 编译 CAT_MENU”；
- CATIA ProductDocument/PartDocument/DrawingDocument 实际操作；
- 子产品复制、叶子复制、删除和取消路径；
- 实例名、零件号四种修改模式；
- 动态工具栏真实渲染；
- Google 翻译成功、失败、超时和分段响应；
- 破坏性导入的失败恢复；
- GitHub 标签发布的完整端到端运行。

因此，本报告的确定性缺陷来自源码和 Git 对象证据；关于 CATIA UI、COM 行为和外部服务的结果必须通过动态测试补齐。

## 7. 建议修复顺序与发版门槛

### 第一阶段：解除直接阻断

1. 修复两个 `purePN` 未声明问题；
2. 初始化 `ASM_ChildMng.btn_copy_click` 的选择对象；
3. 统一复制功能的成功、取消、异常清理路径；
4. 在 CATIA VBA 编辑器中完整编译工程。

### 第二阶段：恢复发布和导入可信度

1. 让 `main` 与 `dev` 使用可比较的共同历史，或显式构造完全一致的发布树；
2. 在发版前验证发布树与记录的源 `dev` 提交一致；
3. 将模块导入改为可验证、可回滚的原子流程；
4. 把源码模块数、二进制模块名和菜单入口检查加入发版门禁。

### 第三阶段：修复局部功能和可观测性

1. 修复重复 UI 控件名；
2. 修复工具栏回调名，并在构建阶段验证回调；
3. 禁止公共事件分发器静默吞掉全部错误；
4. 修复翻译成功统计并增加隐私、超时和失败处理；
5. 逐步减少新增代码中的 `On Error Resume Next` 和隐式 Variant。

### 最低发版验收清单

- [ ] VBA 工程完整编译，无“Variable not defined”或缺失引用；
- [ ] 子产品普通复制和叶子复制均成功；
- [ ] 在源选择和目标选择阶段取消，CATIA 设置均恢复；
- [ ] 实例名和零件号的前缀、后缀、删除、替换分别通过；
- [ ] 未选择操作、选择多个操作、空查找字符串时有明确校验；
- [ ] 材料颜色工具栏能够打开并响应每个按钮；
- [ ] “仅显示选定（含子树）”和所有取消按钮能够响应；
- [ ] 翻译失败不计入成功，并展示失败清单；
- [ ] 模块导入失败可以恢复原工程；
- [ ] 发布后的 `main` 树与记录的源 `dev` 提交符合预期；
- [ ] CATVBA 正式产物的 SHA-256、模块数和版本已记录；
- [ ] 发布工作流至少包含静态检查和人工 CATIA 冒烟测试确认。

## 8. 后续需要确认的问题

1. `main` 是否被有意设计为无共同祖先的“发布快照分支”？如果是，需要定义如何保证删除同步和树一致性。
2. 根目录多个 CATVBA 文件中，是否只有 `CATIA_V5_SimpleMacroMenu.catvba` 是正式产物？其他文件是否应移入参考目录或明确标记为旧版。
3. 翻译功能是否允许把结构树名称发送到公网服务？是否存在客户或项目数据合规要求。
4. 模块管理器的“导入项目”是否允许改变正在执行的 CATVBA 工程？如果允许，需要确定正式的备份和回滚策略。
5. CATIA 版本、VBA7/64 位环境和引用库组合是否有固定的支持矩阵。

## 9. 审查结论

`dev@abce8ff` 的增量已经同步进主 CATVBA 二进制，但当前源码仍有明确的编译阻断、核心复制功能错误、发布树不一致和破坏性导入风险。应至少完成 F-01 至 F-04 的修复及 CATIA 内完整编译、复制/改名冒烟测试后，再考虑合入或发布。

本次审查阶段未修改业务源码、CATVBA 二进制或既有提交；成文后仅在本地分支 `codex/dev-review-report` 新增并提交本报告，未执行远端推送。
