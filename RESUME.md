# Macro_menu 新环境续作入口

状态：CURRENT / issued discovery bundle / **NO-GO for release**

唯一仓库：`doylenehemiah6893-afk/Macro_menu`
唯一工作分支：`codex/dev-review-report`
唯一下一动作：`run-b28-discovery`

机器可读事实以 `resume/state.json`、`artifacts/b28-discovery/CURRENT.json` 和 bundle 内
`provenance.json` 为准。本文件不把 A 环境验证说成 CATIA 验证。

## 1. 当前已签发制品

| 项目 | 固定值 |
|---|---|
| evidence commit / tree | `68022541bf8cacd1db012128daf4cdef1048af8d` / `405f24751ddabecced9b547680e6dbdefdeb80be` |
| active bundle | `artifacts/b28-discovery/bundles/bundle-ab5205f4f37e8ec467a9800a/` |
| provenance SHA-256 | `ab5205f4f37e8ec467a9800afb986bc2290ae7235820d38423cfde2b7c89d895` |
| Kit / ZIP SHA-256 | `kit-e93a2e7f48c3f4d2f179` / `d763b3e1a1a2e33d994a5c030e0fa3b541e8a46648f11378870c6a86711cf012` |
| active handoff / expiry | `handoff-b8d9d535604e78551423` / `2026-07-23T11:11:06Z` |
| active ledger | `artifacts/b28-discovery/active-handoff-ledger.json`；captured `2026-07-16T11:12:07Z` |
| A 环境完整测试 | `1659 passed, 19 warnings`；非 CATIA 证据 |

该 handoff 仅可在未过期、未撤回且外部 ledger 不超过 24 小时时使用。离线包只能证明取得时的
ledger 状态；不能证明之后没有撤回。若已过期、撤回、缺失、摘要不符或 ledger 过期，立即停止并从本分支取得新的
控制文件；不得手改 JSON 延期或恢复。

所有 target truth 仍为：`compile_status=not-run`、30 个 target case 全部 `not-run`、
`artifact_status=not-produced`、`release_eligible=false`。G2–G7 全部 `BLOCKED`。

## 2. 取得与开发续作

开发续作必须完整 clone，不能使用 GitHub Download ZIP；后者没有 object/ref 历史，无法验证 approved cutoff 与
intake baseline。Download ZIP 仅可用于获取已发布的目标机 bundle，不能作为开发工作树。

```bash
git clone --branch codex/dev-review-report --single-branch https://github.com/doylenehemiah6893-afk/Macro_menu.git
cd Macro_menu
python3.12 scripts/bootstrap_resume.py --repo-root . --state resume/state.json
uv run macro-menu-build doctor --state resume/state.json --format json
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root build/resume-verification
```

只写 `codex/dev-review-report`；不得 merge/rebase/cherry-pick `main` 或 `dev`、force-push、创建 tag/Release、或写
Production 宏库。批准 cutoff 固定为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；当前 `origin/dev` 已前进且
不得跟随。bootstrap 只会在本地缺失时建立 `refs/heads/dev` 到该 cutoff，绝不 checkout、merge、reset 浮动 dev。

开发/A 环境使用 CPython 3.12、`uv 0.9.25` 和根 `uv.lock`。Windows 开发机使用 `cmd.exe` 等价入口：

```bat
scripts\bootstrap-resume.cmd
uv run macro-menu-build doctor --state resume\state.json --format json
python scripts\verify_resume.py --repo-root . --state resume\state.json --output-root build\resume-verification
```

## 3. B28 目标机唯一入口

目标 B28 机已有 Python 3.12，**不得使用 WSL、PowerShell、uv 或任何脚本自动化 CATIA/VBE/DSLS**。只在批准的
blank VM、标准用户、原生 `cmd.exe` 中将 active bundle、`CURRENT.json` 和 fresh ledger 放入互不重叠的本地 NTFS
目录，然后严格执行 bundle 内：

- `artifacts/b28-discovery/bundles/bundle-ab5205f4f37e8ec467a9800a/QUICKSTART_B28.md`
- `artifacts/b28-discovery/bundles/bundle-ab5205f4f37e8ec467a9800a/README_TARGET_B28.md`
- `artifacts/b28-discovery/bundles/bundle-ab5205f4f37e8ec467a9800a/SECURITY_AND_REDACTION.md`

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
- 试图把 G2–G7 或 `release_eligible` 改为通过，或复活旧 handoff `handoff-6ed312ee18b254cb3c13`。

发生任一项时保留现有日志和 hash，停止并回到本文件与 `resume/state.json`，不要自行扩大授权。
