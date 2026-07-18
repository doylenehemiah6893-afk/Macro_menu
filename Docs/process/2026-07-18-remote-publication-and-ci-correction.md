# 远端首次发布与 CI 修正记录

状态：CORRECTIVE LOCAL DELIVERY BUILT / REMOTE VERIFICATION PENDING

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
`shutil.which("uv.exe")` 解析绝对路径，版本检查与 frozen sync 各自在进入受控子进程前固定该绝对路径；sync 子进程保留 Windows 必要的
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

首次 corrective commit `952c922adda97f0fdff80bdaf42e5940afdf2a64` 的完整 evidence receipt 虽为 `ok=true`，
但独立审查发现 selector 组合状态可隐藏 future/畸形 ledger、Windows CMD 多命令未逐条 fail-fast、发布文档状态漂移和
覆盖不足，故明确判定 **不可签发**；没有创建 handoff，也没有激活 ledger。修复必须形成后续 clean evidence commit，
重新运行整份 receipt，不能复用 `952c922` 的 Kit。

阻断项修复后的聚焦套件为 `126 passed in 84.34s`；pre-evidence 完整回归为
`1672 passed, 19 warnings in 268.01s`。新增组合回归明确覆盖 expired+future、expired+畸形 ledger、inactive 模式下
bundle tamper、Windows `uv.exe` preflight/sync、Windows CMD fail-fast 和 preparation 控制完整性。

后续完成条件：

1. 精确 uv/CPython 3.12 下完整 pytest、lock、diff 与 clean evidence commit；
2. 从 evidence commit 运行 `verify_resume.py`，完成 inventory/check、双 Kit、四 verifier 与 collector smoke；
3. 生成 fresh issuance snapshot、七日内 handoff、active ledger 和两次一致的 operator bundle；
4. delivery commit 只改 `Docs/`、`RESUME.md`、`artifacts/`、`resume/`；
5. 本地 autocrlf/quotepath fresh clone、两种 doctor 与严格 selector通过；
6. 一次 fast-forward 推送 evidence+delivery，远端 Linux/Windows CI 与 GitHub fresh clone 通过。

签发前 preparation 结论为 **NO-GO**：G0=`PASS`，G1–G7=`BLOCKED`。下节完成新 A 环境 delivery 后只允许
G1 回到 `PASS`；`compile_status=not-run`、30 个 target case 全部 `not-run`、CATVBA=`not-produced`、
`release_eligible=false` 始终不变。

## 5. 可签发 evidence 与新 delivery

复审后的 clean evidence commit 为 `0b28548e5ebe1ee6f5c174122d56c92c2e6005ed`，tree 为
`cbcac84169c75133fdb2de1b984ef62645edd5b7`。它在已复审 `e254b33` 上只把根 README 改为时间稳定入口；
再次独立复审 Critical=0、Important=0。唯一 Minor 是未单独直接观察
doctor 内部 uv 版本子进程参数，但同型路径已有测试，且 Windows CI 已对 doctor 可靠 fail-fast，不阻断签发。

从该精确提交重新运行正式 receipt：

| 项目 | 固定结果 |
|---|---|
| lock / Development doctor | 24 packages resolved / PASS；local dev 保持批准 cutoff，未采用 floating origin/dev |
| 完整 pytest | `1672 passed, 19 warnings in 250.99s` |
| inventory / check | 90 records / 16 components、2 tools；零 diagnostics，均 formal eligible |
| Kit / ZIP SHA-256 | `kit-d5ea863e68ba6af1cefa` / `db46b7c1e09741b71097554e9383356b90a1d77ef90fc3d910f1387344ade977` |
| Kit tree / sidecar SHA-256 | `7f962e8890caa0cbc332017775fa61e8494c9e017b5d9c16713bd143c1f4f3d2` / `c72da27158d0dcbf9399673781bedfff75a1fc0bcf3c383b00be08a12ad256ba` |
| 四 verifier / collector smoke | directory/ZIP × primary/comparison 全通过；pyz help 与 synthetic expected-fail-closed 通过 |
| pre-issuance snapshot SHA-256 | `1e992f6b67cc41d8bbb8f0d196febab781896a8378fb84bd514ba74ee199dff4`；active 为空，四份旧 handoff withdrawn |
| handoff / SHA-256 | `handoff-80d8cb2c06104fcf3c74` / `0964ef2f00d2d370f7583616b45df7ea6a78b6ebc1556110caa3547fbb5b6681` |
| created / expires | `2026-07-18T13:38:11Z` / `2026-07-25T12:38:11Z` |
| active ledger | captured `2026-07-18T13:38:17Z`；SHA-256 `fd9045791c151d43b201a8a1ce3a99f973927d7c48d269d75f685e8559e64761` |
| operator bundle | `bundle-64084c5ea0dfd63e24d861cb`；两次完整目录相同，61 files、约 700 KiB |
| provenance / content SHA-256 | `64084c5ea0dfd63e24d861cbf948b05a4af3e33a7268290eb8ecca8158373ffe` / `6e546677d55b74be0f52367695c4f709055a48c604b5073abb36a1e3f569fe7a` |
| collector pyz SHA-256 | `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` |

两个 raw Discovery skeleton 的三个成员与完整目录逐字节相同；它们只含 `not-run` 模板，未提交 raw fixture 或现场数据。
两个 operator bundle 构建目录逐字节相同，公开 bundle 不含 CATVBA、用户/主机/DSLS 标识或客户路径。

本地 delivery record 尚待提交和 autocrlf/quotepath fresh-clone 验证；随后必须一次 fast-forward 推送 evidence+delivery，
确认远端 Linux/Windows CI 与 GitHub fresh clone。完成前 B28 仍不得执行。G0/G1 可在提交后为 A 环境离线 `PASS`，
G2–G7 保持 `BLOCKED`；其余 NO-GO 事实不变。
