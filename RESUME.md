# Macro_menu 新环境续作入口

状态：CURRENT / refreshed delivery clone-verified / remote verification pending / **NO-GO for B28 and release**

唯一仓库：`doylenehemiah6893-afk/Macro_menu`
唯一工作分支：`codex/dev-review-report`
当前开发动作：fast-forward 推送新 evidence/delivery，并复跑远端双平台 CI 与 GitHub clone

当前目标机动作：BLOCKED；新 local delivery 已 clone-verified，但远端双平台与 GitHub clone 尚未通过

机器状态首先以 `resume/state.json` 为准；只有 `active_bundle_path` 非空时，CURRENT 与 bundle provenance 才能
共同选择活动制品。本文件不把 A 环境验证说成 CATIA 验证。

> GitHub 远端已普通 fast-forward 到 `55cbef2ec3afc63d876c624ee174df8798ef2dbc`。run `29649284949`
> 的 Linux job 成功，Windows job 仍在 bootstrap uv preflight 失败。该 handoff 已撤回；显式 uv-path 修复已形成新的
> clean evidence 与本地 delivery，但远端尚未包含它们。

## 1. 当前机器状态

| 项目 | 固定值 |
|---|---|
| remote published HEAD | `55cbef2ec3afc63d876c624ee174df8798ef2dbc` |
| current evidence / tree | `982ce2bd11ad971b9614e12d38a6830b5a7789ba` / `b4e423ac2faccbcc0c11e65e8a10917ece862c88` |
| local delivery commit | `8dac3a48a060566b3fc5b2ab8cb287066f141b62`；父提交精确为 evidence |
| active bundle / provenance | `bundle-44c7a1ae951d2917309fc9d5` / `44c7a1ae951d2917309fc9d5d5aea8bf583b080254a512dc8b8e7d789430c5de` |
| active Kit / ZIP | `kit-a235b5dd5fc27d09b7de` / `cee08464bf22024f733b2277e61defdf448e76f41b18082225ffb880fec7fe45` |
| active handoff / expiry | `handoff-be908ee37a9b5beba0b5` / `2026-07-25T14:33:26Z` |
| ledger | captured `2026-07-18T15:33:33Z`；只激活新 handoff，五份旧 handoff withdrawn |
| Gate / next action | G0/G1=`PASS`，G2–G7=`BLOCKED`；`run-b28-discovery` |
| remote CI | run `29649284949`：Linux success，Windows job `88092722616` 在 bootstrap uv preflight 失败；上一 run `29644483056` 亦为 failure |
| 本轮本地测试 | 最终独立复审 Critical/Important=0；clean evidence receipt `1678 passed, 19 warnings`；双 Kit/四 verifier/collector smoke/双 bundle；autocrlf/quotepath clone 两种 doctor、strict selector 与关键摘要全部通过 |

`bundle-95bce...`、`bundle-6b7518...` 与 `bundle-ab5205...` 仍保留供审计，但其 handoff 均已撤回；更早的
`handoff-6ed312...` 也保持 withdrawn。不得因历史 expiry 尚未到达就直接复用，也不得手改 JSON 延期或恢复。

所有 target truth 仍为：`compile_status=not-run`、30 个 target case 全部 `not-run`、
`artifact_status=not-produced`、`release_eligible=false`。G2–G7 全部 `BLOCKED`。

## 2. 取得与开发续作

开发续作必须完整 clone，不能使用 GitHub Download ZIP；后者没有 object/ref 历史，无法验证 approved cutoff 与
intake baseline。当前远端可取得已发布 HEAD `55cbef2`；本轮 uv-path 修复推送前，外部 clone 不包含当前修复。

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

bootstrap 会优先接收经版本校验的显式绝对 uv 路径；没有显式路径的普通 clone 才从父 PATH 解析。Development
验证不因 ledger/handoff 过期而失败。准备转运到 B28 前必须另跑
`uv run macro-menu-build doctor --state resume/state.json --scope delivery --format json`；该范围继续严格检查 freshness、expiry 和 revocation。完整网络/cache、Windows 与仓库同步说明见 `Docs/ENVIRONMENT_REPRODUCTION.md`。

## 3. B28 目标机唯一入口

目标 B28 机已有 Python 3.12，**不得使用 WSL、PowerShell、uv 或任何脚本自动化 CATIA/VBE/DSLS**。新 local
bundle 为 `bundle-44c7a1...`，但目标机仍不得开始。只有 delivery commit、远端双平台 CI、GitHub fresh clone 与
Delivery doctor 全部通过后，才可在批准的 blank VM、标准用户和原生 `cmd.exe` 中执行它；所有历史 bundle 均不可执行。

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
- 试图把远端已发布 `55cbef2` 说成本轮 uv-path 修复，或用 API 重建提交 SHA。

发生任一项时保留现有日志和 hash，停止并回到本文件与 `resume/state.json`，不要自行扩大授权。
