# Macro_menu 新环境续作入口

状态：CURRENT / R9D local delivery / remote verification pending / **NO-GO for B28 and release**

唯一仓库：`doylenehemiah6893-afk/Macro_menu`
唯一工作分支：`codex/dev-review-report`
当前开发动作：推送已完成 local clone QA 的 R9D delivery，再复跑远端双平台 CI/GitHub clone

当前目标机动作：BLOCKED；新 local bundle 已签发，但尚未通过远端验证

机器状态首先以 `resume/state.json` 为准；只有 `active_bundle_path` 非空时，CURRENT 与 bundle provenance 才能
共同选择活动制品。本文件不把 A 环境验证说成 CATIA 验证。

> GitHub 远端已普通 fast-forward 到 `cfb9b0908c5368f91bc31ac5fd76fa38707ad3ad`。run `29651458545`
> 的 Linux job 成功；Windows 已启动解析后的 uv.exe，但 `--version` 的 build metadata 被精确整行校验拒绝。
> R9D 改用官方稳定短格式 `uv -V`；delivery `105bfad` 与 local clone QA 已闭合，但尚未推送。

## 1. 当前机器状态

| 项目 | 固定值 |
|---|---|
| remote published HEAD | `cfb9b0908c5368f91bc31ac5fd76fa38707ad3ad` |
| current evidence / tree | `957d0f23c40513a9b82d583e8428d7c85d1710c5` / `fe3d79dedfeb282e5e80f8ebf0a345b927811b35` |
| active bundle / provenance | `bundle-e4d5b791d8ce5dd442529605` / `e4d5b791d8ce5dd442529605337da0e36712ecb9858365673703d89820bdf35c` |
| active Kit / handoff | `kit-1ce7c253b8220c5aa53b` / `handoff-abb194d469d790637ab1`；expires `2026-07-25T19:00:38Z` |
| ledger | captured `2026-07-18T20:01:40Z`；只激活新 handoff，七份历史 handoff withdrawn |
| Gate / next action | G0/G1=`PASS`，G2–G7=`BLOCKED`；`run-b28-discovery` |
| remote CI | run `29651458545`：Linux `88098390129` SUCCESS；Windows `88098390116` 因 `--version` build metadata 精确校验失败 |
| 本轮本地测试 | 独立复审 0 findings；正式 receipt `1683 passed, 19 warnings`；双 Kit/四 verifier/双 bundle 全通过 |
| local clone QA | `105bfad` autocrlf/quotepath `--no-local` clone：两种 doctor、严格 selector、六项 byte compare 全通过 |

`bundle-95bce...`、`bundle-6b7518...` 与 `bundle-ab5205...` 仍保留供审计，但其 handoff 均已撤回；更早的
`handoff-6ed312...` 也保持 withdrawn。不得因历史 expiry 尚未到达就直接复用，也不得手改 JSON 延期或恢复。

所有 target truth 仍为：`compile_status=not-run`、30 个 target case 全部 `not-run`、
`artifact_status=not-produced`、`release_eligible=false`。G2–G7 全部 `BLOCKED`。

## 2. 取得与开发续作

开发续作必须完整 clone，不能使用 GitHub Download ZIP；后者没有 object/ref 历史，无法验证 approved cutoff 与
intake baseline。当前远端可取得已发布 HEAD `cfb9b09`；本轮 `uv -V` 修复推送前，外部 clone 不包含当前修复。

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
`bundle-e4d5b791...` 已签发，但目标机不得开始。只有 delivery commit、远端双平台 CI、GitHub fresh clone 与
Delivery doctor 全部通过后，才可在批准的 blank VM、标准用户和原生 `cmd.exe` 中执行它；历史 bundle 均不可执行。

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
- 试图把远端已发布 `cfb9b09` 说成本轮 `uv -V` 修复，或用 API 重建提交 SHA。

发生任一项时保留现有日志和 hash，停止并回到本文件与 `resume/state.json`，不要自行扩大授权。
