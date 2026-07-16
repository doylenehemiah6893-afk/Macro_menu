# 故障与停止规则

任何命令 `exit_code` 非 0、`ok=false` 或 diagnostic 均是停止，不是提示。保留原输出和哈希，关闭 CATIA，不删除或
手改 capture，不重跑已关闭 observation point；通知 A 环境。尤其：

- `COLLECTOR_EXTERNAL_STATE_REQUIRED`、`COLLECTOR_LEDGER_STALE`、withdrawn/not-active/expired：取得新的 sibling
  `CURRENT.json` 与 active ledger 后，从新的 blank VM/session 重来。
- provenance、handoff、hash、member、skeleton、current mismatch：隔离 bundle，重新从仓库取得；禁止换 hash。
- Python/clock/native Windows 错误：修复目标环境或时钟见证后，从头重来。
- environment、license、Reference forbidden/invalid：记录现场事实并停止；不得勾选 Reference、调用 SetLicense、
  安装 B30/x86/VBA6/未知 DLL 或改 DSLS。
- point order/closed、output exists/update conflict：当前 session 作废，换新 capture 名并恢复 blank VM。
- path/file/size/member/collision/unsafe、atomic publish failed：隔离目录，交给 A 环境检查，不要复制部分 staging。
- `COLLECTOR_CAPTURE_BUSY`：先确认没有另一进程；不得删除 lock。stale-lock 恢复只由获准维护人员离线调用源码中的
  `recover_stale_record_lock`，且必须证明 PID 已死、进程 identity 一致、没有 `.record-staging-*`。任一条件不满足，
  当前 session 作废。正常操作不存在“强制解锁”命令。
- redaction/operator/capture incomplete：补充新的合规记录；若涉及已关闭不可变点，则从头重来。

exit 2 仅表示 argparse 参数/usage 错误；exit 3 表示输入、工作区、记录、封装以及外部
current/ledger/handoff/bundle 信任状态失败；exit 4 仅表示 preflight 的 `COLLECTOR_CPYTHON_REQUIRED`、
`COLLECTOR_PYTHON_312_REQUIRED` 或 `COLLECTOR_NATIVE_WINDOWS_REQUIRED`。wrapper 无可用解释器/pyz 返回 9009。
0 只表示该本地步骤完成，不代表 Gate PASS。Discovery 永远禁止 Compile、无 CATVBA、30 cases
`not-run`、`release_eligible=false`。
