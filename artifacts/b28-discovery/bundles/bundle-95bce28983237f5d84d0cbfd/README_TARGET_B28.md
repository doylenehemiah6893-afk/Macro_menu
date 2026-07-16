# B28 Discovery 目标机操作包

本目录用于原生 Windows `cmd.exe` + CPython 3.12 的 CATIA V5-6R2018 / R28 / B28
Discovery 观察。它不使用 WSL，不使用 PowerShell，不自动化 CATIA/VBE，不执行 Compile，也不生成 CATVBA。

先读 `SECURITY_AND_REDACTION.md`，再逐条执行 `QUICKSTART_B28.md`。遇到任何非零退出码立即停止，按
`TROUBLESHOOTING.md` 处理；不得改 JSON、handoff、ledger 或采集器代码来绕过错误。

本包输出永远是 `raw/untrusted`。Gate、approval、seal 只能在受信 A 环境完成。资格表达式仅用于观察：
`(AB3 OR HD2 OR MD2) AND SPA AND FTA`；禁止用脚本申请、修改或重置许可证。

当前发布状态固定为 `compile_status=not-run`、30 个 target case 全部 `not-run`、
`artifact_status=not-produced`、`release_eligible=false`。

## 完整执行边界

在管理员预建的本地 NTFS 非敌对根目录使用批准的 blank VM snapshot、标准用户和普通 `cmd.exe`。bundle、外部
`CURRENT.json`、fresh `active-handoff-ledger.json`、inputs、capture、return 互不重叠；不得使用网络共享、同步盘、
Temp、junction、reparse point、symlink 或 hard link。开始前 CATIA/VBE 全部关闭，旧 CATVBA、客户文档、个人宏库
和 Production 宏库均不挂载。Windows ACL 只是操作前提，不能让 raw 输出成为可信 seal。

`QUICKSTART_B28.md` 是本 bundle 的完整命令入口；它先验证 `py -3.12`，失败时才验证 PATH `python`，然后复制模板、
要求人工编辑并 fail-close 检查 placeholder。所有非零退出码立即停止，含义见本目录 `TROUBLESHOOTING.md`。任何命令
不得为通过而手改 handoff、ledger、JSON 或采集器。

## 必须人工填写的观察

1. `environment-input.json`：从 Windows System/About、CATIA About、VBE About 只读记录 Windows edition/build、
   V5-6R2018/R28/B28、VBA7、Win64；B30、x86、VBA6、Temp、user-profile 污染项必须全为 absent。
2. `entitlements-input.csv`：在 CATIA/DSLS licensing UI 分别观察 AB3、HD2、MD2、SPA、FTA 的 availability 与
   checkout。unknown 可以是真实事实；禁止 `SetLicense`、LicenseReset 或修改 DSLS。资格只是
   `(AB3 OR HD2 OR MD2) AND SPA AND FTA` 的观察，不是 Gate PASS。
3. 新建全新空白一次性 VBA project，不 Save As 旧项目，不注册 Production。VBE References 逐项记录 GUID、版本、
   display name、MISSING、architecture、source class、允许 root kind、相对路径/basename 和文件 SHA-256。完整本地路径、
   机器/用户/客户身份、DSLS endpoint 不得写入。
4. 五份 CSV 必须在当时分别观察并填写，严格顺序为 `blank-project`、`post-form-import`、`post-all-import`、
   `post-save`、`post-restart`，不得复制上一点。MISSING、B30、x86、VBA6、Temp、user-profile 或未知 DLL 立即停止。

## 导入、保存、重启与回传

只按 Kit `import-order/core.txt` 人工导入 Core。FRM 与同 basename FRX 是原子对：VBE 只选择 FRM，确认 FRX sidecar
随入；FRX 不单独打开、修改或导入。完成 form 后观察第二点，全部 Core 后第三点，保存一次性工程后第四点，完全
退出 CATIA/VBE/残留宿主再重开后第五点。全过程禁止 Compile、禁止运行 target cases、禁止生成发布 CATVBA。

按 `SECURITY_AND_REDACTION.md` 完成两名不同复核者和图片 sidecar（如使用图片），再执行 status/finalize/hash。
整个 return 目录和 hash receipt 经批准通道送回 A 环境。目标机输出始终是 `raw/untrusted`；A 环境才可严格 ingest、
Gate/approval/seal。最后关闭 CATIA，隔离一次性工程与 capture，恢复干净 VM snapshot；本工程不得续作 G2/G3。
