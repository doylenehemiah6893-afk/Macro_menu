# Macro_menu 当前开发规格

状态：APPROVED WORKING BASELINE

日期：2026-07-16

适用分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`

本文件是当前实现与续作的稳定合同。日期化历史规格保留设计依据，但不再承担当前任务进度、环境复刻或远端发布状态。仓库执行不依赖任何外部命名 skill、IDE persona 或代理配置。

## 1. 不可变约束

- 只写 `codex/dev-review-report`；不得 merge、rebase、cherry-pick `main/dev`，不得 force-push、tag、Release 或写 Production 宏库。
- 批准的 intake cutoff 固定为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；不得采用浮动 `dev@688911522f88e2283231fb59232ea43edd3174a5`。
- 目标宿主固定为 CATIA V5-6R2018 / R28 / B28、VBA7、Win64；资格为 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`。
- B28 使用原生 Windows CPython 3.12 与 `cmd.exe`；不得使用 WSL、PowerShell、COM/GUI 自动化驱动 CATIA、VBE 或 DSLS。
- 当前仍为 NO-GO：`compile_status=not-run`、30 个 target case 全部 `not-run`、CATVBA=`not-produced`、`release_eligible=false`、G2–G7=`BLOCKED`。

## 2. 三层环境模型

| 层 | 长期性 | 验证内容 | 失败影响 |
|---|---|---|---|
| Development | 稳定 | 完整 Git clone、分支/cutoff/tree、CPython 3.12、uv 0.9.25、lock、源码、测试、不可变 bundle bytes | 阻止开发/构建 |
| Delivery control | 时效性 | CURRENT、active ledger、handoff freshness/expiry/revocation、bundle 与 Kit binding | 只阻止 B28 使用该签发包 |
| B28 target | 现场证据 | 原生 Windows、CATIA/VBE/References/DSLS 人工观察及回传 | G2–G7 保持 BLOCKED |

`bootstrap_resume.py` 只依赖 Development 层。`doctor --scope development` 可在 ledger 或 handoff 过期后继续验证开发环境；`doctor --scope delivery` 必须继续严格拒绝 stale、expired、withdrawn、inactive 或摘要不符的操作授权。

## 3. 可复刻开发环境

唯一 Python 真源为根 `.python-version`、`pyproject.toml` 与 `uv.lock`。合同为 CPython `>=3.12,<3.13`、uv `0.9.25`；最后验证的 A 环境为 CPython 3.12.13，但其他 CPython 3.12 patch 由测试和 CI 证明兼容性。

复刻要求：

1. 使用完整 Git clone，不使用 GitHub Download ZIP 或 shallow clone；
2. 通过批准的软件渠道预装 Git、CPython 3.12 和精确 uv 0.9.25；
3. 允许访问 PyPI、批准的包镜像或已预热 uv cache，再运行 frozen sync；
4. 受限 HOME 环境显式把 `UV_CACHE_DIR` 指向可写临时目录；
5. `.venv`、cache、build、egg-info 和本机配置由仓库重新生成，绝不复制或提交；
6. Git for Windows 的行尾设置不得改变受哈希保护的文件；`.gitattributes` 固定 LF，并将已签发 bundle 作为字节不透明内容。
7. evidence 与 delivery commit 之间的路径边界必须用 `git diff --name-only -z` 的原始 NUL 分隔路径解析；不得依赖会受 `core.quotepath`、非 ASCII 文件名或换行文件名影响的展示文本。

仓库目前没有 wheelhouse，因此“仅 clone 即可完全断网安装依赖”不成立。若未来要求断网复刻，必须另建按操作系统/架构签名并带哈希的 wheelhouse 制品和验证清单，不能放宽 frozen lock。

## 4. 入库与排除边界

必须入库：源码、manifest/schema、测试、脚本、Python/uv 版本与 lock、CI、当前规格/计划/状态、脱敏且确定性的公开 bundle、SBOM、哈希与收据。

禁止入库：

- `.venv`、uv/pip/pytest cache、`__pycache__`、egg-info、build/dist/tmp/log；
- IDE/代理个人配置、token/PAT/SSH key、credential helper、绝对本机路径；
- 未脱敏 B28 raw capture、客户/用户/主机/DSLS 数据、工作 CATVBA 或 sealed 私有证据；
- Git config、reflog、临时 refs 或任何用于伪造 freshness/expiry 的控制文件改写。

本机 `user_data.json` 由 `user_data.example.json` 复制后在本地填写，并被 Git 忽略。

## 5. 仓库与远端同步合同

- 本地提交必须形成现有远端分支的 fast-forward；推送前验证 remote old SHA，推送后验证 remote HEAD 等于本地 HEAD。
- 不在连接器/API 中重建已有本地提交；重建会改变 commit SHA，破坏 evidence、bundle 和 state 绑定。
- 凭据只配置在外部 credential manager、SSH agent 或已认证 GitHub CLI 中，不写仓库。
- 在远端包含全部提交之前，文档必须明确标记“local-only / remote publication blocked”，不得声称 GitHub fresh clone 可取得当前制品。
- 推送后必须从第二个临时目录真正 clone GitHub 分支，并分别在 Linux 与原生 Windows 验证。

## 6. 文档权威与变更规则

机器状态首先以 `resume/state.json` 为准；只有它的 `active_bundle_path` 非空时，`artifacts/b28-discovery/CURRENT.json` 和对应 bundle `provenance.json` 才共同构成活动选择器。preparation 状态必须移除 CURRENT、清空 ledger active 集并撤回上一 handoff；历史 bundle 只作审计，不授权目标机使用。当前人类状态以 `Docs/STATUS.md` 为准；任务进度只在 `Docs/CURRENT_DEVELOPMENT_PLAN.md` 维护；外部复刻命令只在 `Docs/ENVIRONMENT_REPRODUCTION.md` 与根 `RESUME.md` 维护。

日期化规格/计划是历史合同，不得继续引用不存在的 agent skills。若代码、配置、runbook 源或受管输入变化，必须形成新的 evidence implementation commit，并重新构建/签发 bundle、handoff、ledger、state 和过程记录；不能把旧 bundle 解释为新代码的产物。

## 7. 验收标准

- Linux 与原生 Windows fresh clone 均通过 Development bootstrap/doctor；`core.autocrlf=true` 不改变 lock、intake、state 或 bundle bytes。
- evidence 后仅包含 `Docs/`、`artifacts/`、`resume/` 和 `RESUME.md` 的 delivery commit，在 `core.quotepath=true` 且含中文文件名时仍通过 bootstrap；任何其他路径仍 fail-closed。
- 模拟 ledger 超过 24 小时或 handoff 过期：Development doctor 仍通过，Delivery doctor 稳定失败。
- `uv lock --check`、完整 pytest、inventory/check、双 Kit 构建、四路 verifier 和 collector smoke 全部通过。
- Git 跟踪列表不含本地代理/IDE配置、secret、本机路径或未脱敏目标数据。
- 远端分支 HEAD 与本地一致，Linux/Windows CI 成功，第二次 GitHub fresh clone 可复刻。
- B28 未回传真实证据前，任何整理、测试或 CI 都不得升级 G2–G7 或 `release_eligible`。
