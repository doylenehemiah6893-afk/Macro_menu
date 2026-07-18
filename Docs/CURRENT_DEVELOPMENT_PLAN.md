# Macro_menu 当前开发计划

状态：CURRENT / corrective local delivery verified / remote CI rerun pending

日期：2026-07-18

本文件是唯一活动计划。旧日期化计划保留实现历史和测试设计，不再以未勾选步骤表示当前状态，也不依赖任何外部命名 skill。

## 1. 已核实的历史任务状态

| 工作包 | 状态 | 证据边界 |
|---|---|---|
| Discovery Task 1–9 | 本地完成 | schema、bootstrap、collector、raw finalizer、bundle builder、教程、CI 已实现 |
| Task 10 | 本地完成 | 实施审查与回归关闭记录已提交 |
| Task 11 | 本地重新完成 | quoted-path 修复后已从新 evidence 双构建并签发 public discovery bundle；不是 B28 执行完成 |
| Task 12 | IN PROGRESS | 首次 fast-forward 已发布到 `2098484`；缺陷修复和新 evidence/delivery 已本地提交并通过 clone QA，等待远端复验 |
| B28 Discovery | BLOCKED | 新 local delivery 已签发并提交；等待远端双平台 CI、GitHub fresh clone 与 fresh Delivery doctor 后再由目标机取得 |
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
| R7A | 修复非 ASCII delivery 路径验证并形成新 evidence/delivery | DONE | `4327491`、1665 tests、新 Kit/bundle/handoff；`29e9d49` 的 autocrlf/quotepath final clone、两种 doctor 与 selector 全通过 |
| R8 | 推送并验证 GitHub | DONE FOR INITIAL PUBLICATION | remote 从 `037ab406` 普通 fast-forward 到 `2098484`，本地/远端精确一致；临时 OAuth token 已撤销并删除 |
| R9 | Linux/Windows CI 与第二 fresh clone | CORRECTIVE IN PROGRESS | run `29644483056`：Linux 完整 Development 1665 tests 通过后被 stale selector 阻断；Windows 因裁剪环境中裸 `uv` 发现失败；comments-only workflow 另产生 startup failure `29644481596` |
| R9A | 远端 CI 缺陷修复并重签发 | LOCAL DONE / REMOTE PENDING | `0b28548` 独立复审 Critical/Important=0；1672 tests、双 Kit/四 verifier、`bundle-64084c...` 与 fresh handoff 已闭合；delivery `657d1f5` 及 autocrlf/quotepath clone QA 通过，待 push 和远端双平台复跑 |
| R10 | 原生 B28 Discovery | BLOCKED BY R9A | 从通过 CI/fresh-clone 的新签发包取得 fresh ledger + 未过期 handoff，再人工完成五点 Reference observation；仍禁止 Compile |

## 3. 当前执行顺序

1. 只 fast-forward 推送 `codex/dev-review-report`，验证远端 HEAD，监控 Linux/Windows CI，并从 GitHub 新目录 clone 复核。
2. 仅在 GitHub clone 的 Delivery doctor 仍通过时，把新 active bundle/CURRENT/fresh ledger 转运到 B28。
3. 按 bundle 内 quick-start 在原生 Windows `cmd.exe` 人工执行 Discovery，并回传 raw/untrusted 证据。

## 4. 停止条件

- remote old SHA 与预期不符、推送不是 fast-forward、要求改写 main/dev 或 evidence history；
- lock、intake、bundle bytes 因行尾或路径变化而不一致；
- Development scope 放宽 immutable Git/lock/bundle 校验，或 Delivery scope忽略 stale/expiry/revocation；
- 真实目标数据、凭据或本机绝对路径进入 staged changes；
- 任何文档/代码把 A 环境结果表述为 CATIA、Compile、Reference、许可证或 release PASS。

发生任一项时保留诊断与哈希，停止扩大授权。
