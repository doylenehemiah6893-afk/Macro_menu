# Macro_menu 当前开发计划

状态：CURRENT / corrective evidence and delivery rebuilt / final clone pending / remote publication blocked

日期：2026-07-16

本文件是唯一活动计划。旧日期化计划保留实现历史和测试设计，不再以未勾选步骤表示当前状态，也不依赖任何外部命名 skill。

## 1. 已核实的历史任务状态

| 工作包 | 状态 | 证据边界 |
|---|---|---|
| Discovery Task 1–9 | 本地完成 | schema、bootstrap、collector、raw finalizer、bundle builder、教程、CI 已实现 |
| Task 10 | 本地完成 | 实施审查与回归关闭记录已提交 |
| Task 11 | 本地重新完成 | quoted-path 修复后已从新 evidence 双构建并签发 public discovery bundle；不是 B28 执行完成 |
| Task 12 | BLOCKED | 远端仍落后；缺 Git 推送凭据，远端 CI 与 GitHub fresh-clone 未验证 |
| B28 Discovery | BLOCKED | 本地 fresh delivery control 已重新签发；需先完成最终 clone、推送并由目标机从仓库重新取得，再人工操作 |
| G2–G7 | BLOCKED | Compile、References、权益、profile、试点和发布证据均未取得 |

## 2. 当前复刻与文档治理工作包

| ID | 任务 | 状态 | 完成定义 |
|---|---|---|---|
| R1 | 全面核查本地代码、环境、远端和文档 | DONE | 记录 local/remote、环境版本、autocrlf、ledger expiry、无效配置和文档漂移证据 |
| R2 | 移除无效 agent/skill/IDE 配置 | DONE | 删除 Antigravity/Gemini/Cursor 伪指令和全局 GBK；本机 user data 样例化并忽略 |
| R3 | 修复跨平台环境合同 | DONE | Python 范围与 bootstrap 一致；uv 前置校验；LF/不可变 bundle 属性；root build ignored |
| R4 | 拆分 Development 与 Delivery doctor | DONE | stale/expired 只阻止 delivery；bootstrap/verify/CI 使用 development scope；默认 doctor 仍 fail-closed |
| R5 | 同步当前规格、计划、状态和各层 README | DONE | 当前入口唯一；旧计划加历史状态；无不存在的 skill 引用；不再声称远端已发布 |
| R6 | 完整本地验证并形成新 evidence commit | HISTORICAL DONE | `f2c9d8d`、1664 tests、autocrlf evidence clone、inventory/check、双 Kit/四 verifier 全通过 |
| R7 | 重新构建、签发并提交新 delivery record | WITHDRAWN AFTER CLONE QA | `bundle-6b7518...` 本身双构建一致；最终 delivery clone 因 Git quoted path 误判不能 bootstrap，handoff 已撤回 |
| R7A | 修复非 ASCII delivery 路径验证并形成新 evidence/delivery | FINAL CLONE PENDING | `4327491`、1665 tests、新 Kit/bundle/handoff 已闭合；等待 delivery commit 的 autocrlf/quotepath fresh clone |
| R8 | 推送并验证 GitHub | BLOCKED | 需要外部 HTTPS/SSH/gh 认证；仅 fast-forward 本分支；远端 HEAD=本地 HEAD |
| R9 | Linux/Windows CI 与第二 fresh clone | BLOCKED BY R8 | 两平台 Development 复刻通过；Delivery selector 对过期控制只标 unavailable |
| R10 | 原生 B28 Discovery | BLOCKED BY R8 | 推送后取得 fresh ledger + 未过期 handoff，再人工完成五点 Reference observation；仍禁止 Compile |

## 3. 当前执行顺序

1. 提交第二周期 delivery record，并以 `core.autocrlf=true` / `core.quotepath=true` 做最终 local fresh clone。
2. 取得 GitHub 认证后只 fast-forward 推送 `codex/dev-review-report`；不使用 API 重建提交。
3. 验证远端 HEAD、监控 Linux/Windows CI，并从 GitHub 新目录 clone 复核。
4. 仅在新 clone 的 Delivery doctor 仍通过时，把 active bundle/CURRENT/fresh ledger 转运到 B28。
5. 按 bundle 内 quick-start 在原生 Windows `cmd.exe` 人工执行 Discovery，并回传 raw/untrusted 证据。

## 4. 停止条件

- remote old SHA 与预期不符、推送不是 fast-forward、要求改写 main/dev 或 evidence history；
- lock、intake、bundle bytes 因行尾或路径变化而不一致；
- Development scope 放宽 immutable Git/lock/bundle 校验，或 Delivery scope忽略 stale/expiry/revocation；
- 真实目标数据、凭据或本机绝对路径进入 staged changes；
- 任何文档/代码把 A 环境结果表述为 CATIA、Compile、Reference、许可证或 release PASS。

发生任一项时保留诊断与哈希，停止扩大授权。
