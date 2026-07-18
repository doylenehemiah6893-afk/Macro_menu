# 远端首次发布与 CI 修正记录

状态：CORRECTIVE EVIDENCE PREPARATION

日期：2026-07-18

范围：`codex/dev-review-report` 首次真实 GitHub 发布、远端 Actions 反馈、跨平台根因修复与第三个
clean evidence/delivery 周期。本记录是 A/CI 环境事实，不是 B28、CATIA、Compile 或发布通过证据。

## 1. 首次远端发布

- 发布前远端：`037ab40696744678a57781d5197c152687520d84`。
- 本地发布 HEAD：`2098484d2bc0e9159293f65a31e0724b17ea5809`。
- 方式：普通、非 force 的 fast-forward，只写 `codex/dev-review-report`；没有写 `main`、`dev`、tag 或 Release。
- 发布后以 GitHub 连接器独立确认远端分支与本地 SHA 相同。
- 首次发布使用 GitHub 官方 CLI classic OAuth device flow，批准 scopes 为
  `gist,read:org,repo,workflow`。成功 push 后对该 exact token 的撤销接口返回 HTTP 204，并删除 `/tmp` 临时凭据和
  helper。token 从未写入 remote URL、仓库、日志或提交。

## 2. 远端首轮 CI 的实际结果

| 项目 | GitHub ID | 结果 |
|---|---:|---|
| Fresh-clone reproducibility | run `29644483056` | FAILURE，两个平台都提供了可诊断反馈 |
| Linux job | `88080312533` | Development doctor、1665 tests、inventory/check、双 Kit、四 verifier 与 collector smoke 全部通过；最终 selector 因 `ACTIVE_CONTROL_STALE` 退出 4 |
| Windows job | `88080312522` | setup-python 得到 CPython 3.12.10，setup-uv 得到 uv 0.9.25；bootstrap 随即误报 `bootstrap requires the pinned uv`，`.venv` 和 local `dev` 的后续错误只是 bootstrap 未执行的次生结果 |
| comments-only auto-release | run `29644481596` | startup failure，无 job；comments-only YAML 解析为 `null`，不是合法 GitHub Actions workflow |

Linux 结果证明已发布 Development 实现链可在 GitHub fresh clone 中完成。它不证明陈旧 handoff 仍可用，也不证明
B28/CATIA。旧 ledger captured-at 为 `2026-07-16T15:52:25Z`，运行时已超过 24 小时；严格 Delivery/selector 拒绝它是
正确安全行为，错误在于 Development CI 把这种预期时效状态当成实现失败。

## 3. 根因与修复合同

### Windows uv

生产路径 `scripts/bootstrap_resume.py` 和 `catvba_refactor/macro_build/resume.py` 过去把裸 `uv` 交给裁剪后的子进程
环境二次发现。GitHub Hosted Windows 已安装精确版本，但该启动方式不可靠。修复先在完整父环境中用
`shutil.which("uv.exe")` 解析绝对路径，版本检查与 frozen sync 复用该路径；sync 子进程保留 Windows 必要的
`PATHEXT`、`TEMP`、`TMP` 等变量。回归路径是 `catvba_refactor/tests/test_resume.py`。

### CI selector

`scripts/select_operator_bundle.py` 默认继续 fail-closed。新增的 `--inactive-as-unavailable` 只允许 GitHub Actions 把
stale、expired、withdrawn 或 inactive 映射为 `available=false`；future timestamp、schema/hash/content/tamper 错误仍失败。
回归路径是 `catvba_refactor/tests/test_verify_resume.py`，workflow 显式启用该模式。Delivery doctor 和 B28 操作不使用它。

### 无效 workflow

删除 `.github/workflows/auto-release.yml`。发布历史和 NO-GO 规则继续由 `Docs/发版.md` 保存；布局回归要求
`.github/workflows/` 只存在有效的 `repro.yml`。

## 4. 当前验证与状态转换

使用 CPython 3.12 临时环境和精确 `uv 0.9.25` 运行：

```text
pytest catvba_refactor/tests/test_resume.py
       catvba_refactor/tests/test_project_layout.py
       catvba_refactor/tests/test_verify_resume.py
=> 122 passed in 86.73s
```

随后在同一冻结环境运行 `uv lock --check` 与完整套件：24 packages resolved，
`1668 passed, 19 warnings in 261.37s`。19 条均为 oletools 对 pyparsing 旧 API 的第三方 deprecation，
没有产品失败。

实现输入已变化，因此上一 handoff `handoff-07bbe55bc7552489cd55` 已加入 withdrawn，ledger active 集清空，
`CURRENT.json` 移除，`resume/state.json` 返回 preparation。历史 bundle bytes 保留供审计，不再授权目标机使用。

后续完成条件：

1. 精确 uv/CPython 3.12 下完整 pytest、lock、diff 与 clean evidence commit；
2. 从 evidence commit 运行 `verify_resume.py`，完成 inventory/check、双 Kit、四 verifier 与 collector smoke；
3. 生成 fresh issuance snapshot、七日内 handoff、active ledger 和两次一致的 operator bundle；
4. delivery commit 只改 `Docs/`、`RESUME.md`、`artifacts/`、`resume/`；
5. 本地 autocrlf/quotepath fresh clone、两种 doctor 与严格 selector通过；
6. 一次 fast-forward 推送 evidence+delivery，远端 Linux/Windows CI 与 GitHub fresh clone 通过。

当前结论保持 **NO-GO**：G0=`PASS`，G1–G7=`BLOCKED`，`compile_status=not-run`，30 个 target case
全部 `not-run`，CATVBA=`not-produced`，`release_eligible=false`。
