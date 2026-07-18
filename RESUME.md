# Macro_menu 新环境续作入口

状态：CURRENT / corrective evidence preparation / **NO-GO for release**

唯一仓库：`doylenehemiah6893-afk/Macro_menu`
唯一工作分支：`codex/dev-review-report`
当前开发动作：完成远端 CI 缺陷修复、新 evidence/delivery 重签发，再 fast-forward 推送并验证双平台 CI 与 GitHub fresh clone

当前目标机动作：BLOCKED，当前没有 active delivery；等待新签发控制完成远端验证

机器状态首先以 `resume/state.json` 为准；只有 `active_bundle_path` 非空时，CURRENT 与 bundle provenance 才能
共同选择活动制品。本文件不把 A 环境验证说成 CATIA 验证。

> GitHub 远端已从 `037ab40696744678a57781d5197c152687520d84` 普通 fast-forward 到
> `2098484d2bc0e9159293f65a31e0724b17ea5809`。首轮 CI 已真实运行；当前 corrective worktree 尚未形成并发布新的
> evidence/delivery，因此远端可以复刻已发布基线，但不能代表本轮修复已验证。

## 1. 当前机器状态

| 项目 | 固定值 |
|---|---|
| remote published HEAD | `2098484d2bc0e9159293f65a31e0724b17ea5809` |
| corrective state | evidence/tree/delivery parent 均为 `null`；`revocation_status=preparation` |
| active bundle / Kit / handoff | 全部 `null`；`CURRENT.json` 已移除 |
| ledger | active 为空；`handoff-07bbe55bc7552489cd55` 与更早 handoff 全部 withdrawn |
| Gate / next action | G0=`PASS`，G1–G7=`BLOCKED`；`complete-evidence-implementation` |
| remote CI | run `29644483056`：Linux Development 全链通过后被 stale selector 阻断；Windows bootstrap 未能启动裸 `uv`；无效 workflow startup run `29644481596` |
| 本轮本地测试 | 独立审查修复后聚焦 `126 passed`；pre-evidence 完整回归 `1672 passed, 19 warnings`；clean evidence receipt 待提交后执行 |

`bundle-95bce...`、`bundle-6b7518...` 与 `bundle-ab5205...` 仍保留供审计，但其 handoff 均已撤回；更早的
`handoff-6ed312...` 也保持 withdrawn。不得因历史 expiry 尚未到达就直接复用，也不得手改 JSON 延期或恢复。

所有 target truth 仍为：`compile_status=not-run`、30 个 target case 全部 `not-run`、
`artifact_status=not-produced`、`release_eligible=false`。G2–G7 全部 `BLOCKED`。

## 2. 取得与开发续作

开发续作必须完整 clone，不能使用 GitHub Download ZIP；后者没有 object/ref 历史，无法验证 approved cutoff 与
intake baseline。当前远端可取得已发布 HEAD `2098484`；本轮 corrective 提交再次推送前，外部 clone 不包含当前修复。

```bash
git clone --branch codex/dev-review-report --single-branch https://github.com/doylenehemiah6893-afk/Macro_menu.git
cd Macro_menu
export UV_CACHE_DIR="${TMPDIR:-/tmp}/macro-menu-uv-cache"
python3.12 scripts/bootstrap_resume.py --repo-root . --state resume/state.json
uv run macro-menu-build doctor --state resume/state.json --scope development --format json
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root catvba_refactor/build/resume-verification
```

只写 `codex/dev-review-report`；不得 merge/rebase/cherry-pick `main` 或 `dev`、force-push、创建 tag/Release、或写
Production 宏库。批准 cutoff 固定为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；当前 `origin/dev` 已前进且
不得跟随。bootstrap 只会在本地缺失时建立 `refs/heads/dev` 到该 cutoff，绝不 checkout、merge、reset 浮动 dev。

开发/A 环境使用 CPython 3.12、`uv 0.9.25` 和根 `uv.lock`。Windows 开发机使用 `cmd.exe` 等价入口：

```bat
scripts\bootstrap-resume.cmd
uv run macro-menu-build doctor --state resume\state.json --scope development --format json
py -3.12 scripts\verify_resume.py --repo-root . --state resume\state.json --output-root catvba_refactor\build\resume-verification
```

bootstrap 会先在完整父环境解析 Windows `uv.exe` 的绝对路径，再执行精确版本检查和 frozen sync。Development
验证不因 ledger/handoff 过期而失败。准备转运到 B28 前必须另跑
`uv run macro-menu-build doctor --state resume/state.json --scope delivery --format json`；该范围继续严格检查 freshness、expiry 和 revocation。完整网络/cache、Windows 与仓库同步说明见 `Docs/ENVIRONMENT_REPRODUCTION.md`。

## 3. B28 目标机唯一入口

目标 B28 机已有 Python 3.12，**不得使用 WSL、PowerShell、uv 或任何脚本自动化 CATIA/VBE/DSLS**。当前没有
active bundle。只有新的 evidence/delivery、远端同步、GitHub fresh clone 与 Delivery doctor 全部通过后，才可在批准的
blank VM、标准用户、原生 `cmd.exe` 中将新 active bundle、`CURRENT.json` 和 fresh ledger 放入互不重叠的本地 NTFS
目录，然后严格执行新 bundle 内三份教程；历史 `bundle-95bce...` 不再是可执行入口。

仓库中的 `Docs/runbooks/b28-target/README_TARGET_B28.md` 仅保留为源教程/审查入口；目标机执行时以已签发 bundle
内同名文件为准，避免把源工作树、控制文件与现场 capture 混在一起。

该 quick-start 只用 bundle 内的 `run-discovery.cmd` 与 CPython 3.12，先做完整 preflight，再人工记录环境、DSLS
观察和五个 VBE Reference observation point。禁止 Compile、运行 target cases、生成/发布 CATVBA、修改许可证、把
raw/untrusted 当作 PASS 或 sealed evidence。完成后只通过批准通道回传 raw return 目录及其 hash；不要回传工作 CATVBA。

## 4. A 环境回传后的接力

1. 在完整 clone 中核对 bundle/CURRENT/ledger/handoff 哈希及 expiry/revocation。
2. 严格 ingest raw；它仍是 untrusted，任何缺失、污染、路径泄露、时间/摘要不符都 fail-closed。
3. 进行独立脱敏复核；只允许提交脱敏 public attestation，不提交客户数据、用户名、机器名、DSLS endpoint 或完整本地路径。
4. 仅在 A 环境计算 blocked Discovery result、approval/seal。真实 Reference、许可、Compile 与运行证据返回前，G2–G7
   和 release eligibility 不变。

## 5. 停止条件

- Git repository/branch/cutoff/intake/tree/hash/state/lock 不一致，存在 replace ref、shallow clone 或脏受管路径；
- bundle、handoff 或 ledger 缺失、过期、stale、withdrawn、inactive 或摘要不符；
- 试图在 B28 使用非原生 Python 3.12、WSL/PowerShell、脚本控制 CATIA/VBE/DSLS；
- 试图 Compile、运行 30 cases、生成 CATVBA，或把 raw/untrusted 当 sealed/PASS；
- 试图记录/提交客户路径、主机/用户标识、DSLS server 或未脱敏数据；
- 试图把 G2–G7 或 `release_eligible` 改为通过，或复活旧 handoff `handoff-6ed312ee18b254cb3c13` / `handoff-b8d9d535604e78551423`。
- 试图把远端已发布 `2098484` 说成本轮 corrective 修复，或用 API 重建提交 SHA。

发生任一项时保留现有日志和 hash，停止并回到本文件与 `resume/state.json`，不要自行扩大授权。
