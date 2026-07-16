# B28 Discovery Operator Bundle 实施审查记录

日期：2026-07-16

记录：`record.task10-implementation-review.381bf7c`、`record.task11-skeleton-contract.760896d`
范围：`eb64766d99e09b1ea901708d5fd793f4ca92a9de..760896da2b0a2e0c5c4928480f5a37ed1e0e1331`

## 结论

Task 1–9 的实现、回归修复与 Task 10 审查已完成到可构建交付候选的状态。实现仍然只是 A 环境离线准备：
`compile_status=not-run`、target cases=`not-run`、CATVBA=`not-produced`、`release_eligible=false`，G2–G7 均保持
`BLOCKED`。本记录不是 B28/CATIA、VBE、DSLS、Reference、Compile 或发布通过的声明。

## 固定合同

- 工作分支只为 `codex/dev-review-report`；批准 cutoff 是
  `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`。当前 `origin/dev`
  `688911522f88e2283231fb59232ea43edd3174a5` 未被采用。
- `CURRENT.json.bundle_sha256` 统一表示 canonical `provenance.json` 的 SHA-256；bundle ID 是该摘要的 24 位前缀。
- `provenance.bundle_content_sha256` 是所有 regular 成员的 canonical member-record digest，固定排除
  `provenance.json` 与 `SHA256SUMS`；`SHA256SUMS` 再覆盖 provenance 和所有非自身成员。生成器、CI 选择器和原生
  Windows 采集器以相同顺序验证该闭环。
- issued state 只有完整的 bundle/Kit/handoff/expiry/receipt 字段集合才有效；doctor、verify-resume 和 CI 选择器均要求
  CURRENT、handoff、fresh ledger 与 state 绑定同一 active、未撤回、未过期 handoff。

## 已修复的审查问题

1. `bundle_sha256` 曾被目标采集器解释为 provenance 摘要、被 CI 解释为 bundle tree 摘要，真实交付无法双端接受。
   现已拆分语义，新增实际构建的端到端回归：同一 `CURRENT.json` 同时通过 CI selector 和模拟原生 Windows
   preflight；篡改 payload 即使重写 `SHA256SUMS` 也被两端拒绝。
2. B28 preflight 现验证完整 regular tree、portable path、reparse/symlink/hard link、forbidden CATVBA payload、成员数和
   大小、content digest、全量 checksum、Kit ZIP/sidecar、collector pyz/sidecar、skeleton、handoff 与外部 ledger。
3. resume state schema 拒绝半激活状态；doctor 要求 state、CURRENT、provenance、handoff、ledger 和 bundle 内 receipt
   交叉绑定。CI selector 也拒绝缺失、future、stale、withdrawn 或 inactive ledger 以及 expired handoff。
4. `status` 不再始终建议 `record-environment`，而是报告 environment、entitlements、Reference observation points、
   operator-record index 与 `ready_to_finalize_raw`；它不推导任何 Gate。
5. bootstrap Git 子进程已禁用 global/system Git configuration 与 replace objects。历史 2026-07-15 操作手册已明确
   `SUPERSEDED`，所有入口改为 bundle 内 `b28-target/README_TARGET_B28.md` 与 fail-closed `QUICKSTART_B28.md`。
6. 最终复审还确认：`status` 以与 finalizer 相同的完整 raw validator 判定 readiness，已签发 state 能如实保留
   `active`/`withdrawn`/`expired`/`unavailable`，且 doctor/verify-resume 会重算 active bundle content digest、完整
   `SHA256SUMS`、Kit/pyz sidecar；后续撤回或到期不能被误记为 preparation。
7. 实际交付预演发现 `init-target-session` 的完整 target-evidence 会话与原生 collector 的 raw skeleton 是两个刻意不同的
   合同：前者包含可信的 `started_at`、session binding 和完整 30-case plan，后者只能包含三个固定 raw/untrusted `not-run`
   文档。把前者直接放入 bundle 会被 fail-closed raw validator 拒绝。`760896d` 因而新增
   `macro-menu-build create-discovery-skeleton`；它使用目标 collector 自身的 canonical factory，生成并自校验唯一允许的
   `compile-result.json`、`test-results.json` 和 `artifact-manifest.json`，拒绝覆盖已有输出。该接口不产生任何 B28 事实，
   也不替代目标机的 `init-capture`。

## 验证记录

执行环境：CPython 3.12.13、uv 0.9.25。由于工作容器遗留 `.venv` 是无效的 rsync-munged symlink，验证使用独立
`/tmp/macro-menu-task10-venv`；这不是仓库文件或目标机缺陷。

已通过的针对性回归包括：

```text
test_operator_bundle.py                    32 passed
test_target_collector_workspace.py         44 passed
test_project_layout.py + test_cli.py      122 passed
test_operator_bundle.py + test_cli.py     145 passed（skeleton contract 修复后）
```

最新完整冻结环境测试为 `1659 passed, 19 warnings in 215.66s`。`verify_resume.py` 双 Kit 重现、Task 11 双根 operator
bundle 构建及全新 clone 验证将继续保留
各自的机器可读 receipt，并在交付提交中精确引用。本记录本身不写 evidence commit/tree，以避免自引用；Task 11
将在本记录提交后解析并绑定它们。当前受控执行容器会在命令间复原一个无效的、被 `.gitignore` 排除的 `.venv`；bootstrap
在单一进程内已用 CPython 3.12.13 成功重建该环境，完整测试则使用同一冻结的临时 CPython 3.12 环境。该容器行为不是
仓库内容，也不会作为目标机要求或交付物的一部分。

## 独立复审

两项独立只读审查覆盖 Windows 文件安全、collector 状态机、bundle/ledger 控制、state/CI、文档和 bootstrap Git 环境。
初审发现 1 个 Critical 与多项 Important，已在 `96a2c07` 关闭；最终复审额外发现 operator-record index、raw skeleton
完整性、issued state 生命周期和 doctor bundle integrity 的缺口，已在 `686d98a` 与 `c1d0706` 关闭。末次独立复审确认
`c1d0706` 没有 Critical/Important；`381bf7c` 仅将原先允许的 partial-expiry 测试更新为正确的 schema 拒绝断言。任何
新增 Critical/Important 都会阻止 Task 11。

## 仍然禁止与下一步

不得执行 CATIA、VBE、DSLS 或 Compile；不得生成/发布 CATVBA；不得把 raw 当成 sealed evidence。下一步仅是从本记录
提交生成的 evidence commit 出发，在两个独立输出根重建 Kit、签发新的 discovery handoff、构建 immutable bundle，并
只把认证后的 public artifact/control 文件纳入 Git。

## Task 11 交付结果

上述下一步已由后续 evidence commit `68022541bf8cacd1db012128daf4cdef1048af8d`（tree
`405f24751ddabecced9b547680e6dbdefdeb80be`）完成。该提交只强化了 preparation/issued lifecycle 的公开状态测试；
构建输入没有采用浮动 `origin/dev`。两个 Kit 与两个 bundle 输出根均逐字节一致，四种 Kit verifier 均通过。实际 public
identity、expiry、ledger 与收据路径由 `resume/state.json`、`artifacts/b28-discovery/CURRENT.json` 及
`Docs/process/2026-07-16-b28-discovery-operator-bundle-build.md` 固定。

这表示 Task 11 的 A 环境交付完成，而不是 B28 执行完成。新 bundle 仍为 Discovery-only：
`compile_status=not-run`、30 个 target case=`not-run`、CATVBA=`not-produced`、`release_eligible=false`，G2–G7
仍为 `BLOCKED`。Task 12 只能推送本分支、监控 CI 并以新 clone 复核；现场操作仍必须在 fresh active ledger 与未到期
handoff 下由人按 bundle 内 Windows `cmd.exe` 快速表执行。

## 2026-07-16 环境复刻复审叠加

后续全面环境审查实际复现两个 P0：Git for Windows `core.autocrlf=true` 会改写 lock/intake/bundle 控制 bytes；
Development bootstrap/CI 又会在 ledger 超过 24 小时或 handoff 到期后失败。另发现无效 agent/IDE 配置、uv 前置版本
校验和 Windows CI doctor 调用缺口。因此 Task 12 在推送前新增一个 evidence refresh cycle；旧 evidence/bundle 仍是其
原提交的有效历史产物，但不能解释修订后的代码。当前任务与状态见 `Docs/CURRENT_DEVELOPMENT_PLAN.md`。
