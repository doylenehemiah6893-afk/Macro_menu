# 环境复刻与仓库治理修订记录

状态：EVIDENCE IMPLEMENTATION RECORD

日期：2026-07-16

范围：`codex/dev-review-report` 的开发环境合同、恢复脚本、CI、状态机、文档与仓库同步边界。本文记录 A 环境事实，不是 B28/CATIA 执行或发布证据。

## 1. 复现的根因

- Git for Windows `core.autocrlf=true` 的 clean clone 会改变 `uv.lock`、intake、CURRENT、ledger 和 bundle provenance 的工作树 bytes，导致 lock/bootstrap/doctor 不可复刻。
- Development bootstrap/doctor 误依赖 24 小时 ledger freshness 和 handoff expiry，导致源码未变时仍随墙钟失效。
- Windows CI 用 `python -m catvba_refactor.macro_build.cli` 调用没有模块入口的文件，doctor 实际未执行。
- bootstrap 在验证精确 uv 版本之前就可能改写 `.venv`；Python 项目又没有明确拒绝 3.13。
- 仓库跟踪了无效 Antigravity/Gemini/Cursor/IDE 配置、GBK 全局设置和本机绝对路径样例；日期化计划引用不存在的外部 skills。
- 根 `build/` 未忽略，多层 README、状态和发版文档仍复制旧候选数、旧 bundle/handoff 与旧任务描述。

## 2. 已实施的修订

- `.gitattributes` 固定文本 LF，并对 `artifacts/b28-discovery/**` 使用 byte-preserved 属性；新增对应回归。
- Python 合同统一为 `>=3.12,<3.13`，lock 与项目元数据一致；bootstrap 在 sync/`.venv` 变更前验证 `uv 0.9.25`。
- `doctor --scope development|delivery` 分层：开发范围不因 ledger/handoff 时效失败，交付范围默认且继续 fail-closed。
- bootstrap、verify-resume 和 Linux/Windows CI 使用 development scope；Windows CI 改为实际 console entrypoint。
- 删除无效代理/IDE个人配置；忽略 `.context/`、`.antigravity/`、`.cursorrules`、`.vscode/`、根 `build/` 与 `user_data.json`，新增无绝对路径的 `user_data.example.json`。
- 建立当前开发规格、唯一活动计划、环境复刻指南和日期化审查；同步根入口、STATUS、RESUME、发版、项目结构、子目录 README、历史计划状态和决策台账。
- 受管输入变化后把 `resume/state.json` 返回 preparation：移除 CURRENT，清空 ledger active 集，将上一 handoff 列入 withdrawn；无 active bundle/Kit/handoff，G0=`PASS`、G1–G7=`BLOCKED`、`release_eligible=false`。

## 3. 验证环境

```text
CPython 3.12.13
uv 0.9.25
Git 2.51.1
approved cutoff abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad
origin/dev observed 688911522f88e2283231fb59232ea43edd3174a5 (not adopted)
```

托管工作区会把仓库内 `.venv/bin/python3` 重写为 rsyncd-munged 断链。因此验证使用
`UV_PROJECT_ENVIRONMENT=/tmp/macro-menu-reorg-venv` 与 `UV_CACHE_DIR=/tmp/uv-cache`。该临时环境不属于仓库；
这也验证了每个 clone 必须从 lock 重建 `.venv`，不能复制本地虚拟环境。

## 4. 已通过检查

| 检查 | 结果 |
|---|---|
| `uv lock --check` | PASS；24 packages resolved |
| focused resume/layout/CLI/verify tests | PASS |
| 完整 `pytest -q` | `1664 passed, 19 warnings in 218.83s` |
| warnings | 仅 oletools 对 pyparsing 旧 API 的第三方 deprecation |
| `inventory --worktree` | `ok=true`、零 diagnostics；13 candidate + 77 quarantine；worktree 模式不具 formal eligibility |
| `check --worktree` | `ok=true`、零 diagnostics；16 components、2 tools；worktree 模式不具 formal eligibility |
| secret/path/无效 skill 静态扫描 | 未发现 token、private key、用户绝对路径或不存在 skill 依赖 |

dirty 工作树上的 development doctor 按设计返回 `RESUME_GOVERNED_TREE_DIRTY`；这是 evidence commit 前的
fail-closed 结果，不是缺陷。clean commit 的 development doctor、`core.autocrlf=true` fresh clone、正式
inventory/check、双 Kit/四 verifier 和 delivery 构建结果必须在后续 delivery record 中绑定精确 commit/tree。

## 5. 发布与目标机边界

审查时本地基线为 `2e3be7442734c57af6cde39f5f6f51025095de4f`，GitHub 分支为
`037ab40696744678a57781d5197c152687520d84`；当前容器没有 `gh`、HTTPS/SSH Git 写凭据或 credential helper。
因此远端 publication、GitHub Actions 与 GitHub 第二 fresh clone 仍被阻塞。连接器 API 不得重建本地 commits，
因为 SHA 变化会破坏 evidence/state/bundle 绑定。

B28 已有原生 CPython 3.12，但不能使用 WSL、PowerShell、uv 或 CATIA/VBE/DSLS 自动化。重新签发并推送 fresh
delivery control 前不得执行旧 QUICKSTART；Compile、30 target cases、CATVBA 生成和 G2–G7 全部保持 not-run/BLOCKED。
