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

delivery record 已提交为 `657d1f51ff18d8374e2e685d8b6797c334a5ebed`，其父提交精确为 evidence
`0b28548e5ebe1ee6f5c174122d56c92c2e6005ed`。提交后在新目录以 `core.autocrlf=true`、
`core.quotepath=true`、`--no-local` 克隆，原子建立批准的本地 `refs/heads/dev`，并得到以下结果：

- Development doctor 与 Delivery doctor 均 `ok=true`；严格 selector 唯一选择
  `bundle-64084c5ea0dfd63e24d861cb`；
- source clone 与 fresh clone 的 CURRENT、active ledger、provenance、handoff、Kit ZIP 和 collector pyz
  SHA-256 逐项相同；克隆工作树保持干净；
- 当前托管执行环境无法解析 `files.pythonhosted.org`，因此不能把这里的在线依赖下载作为额外证据；这项网络路径留给
  GitHub Hosted Linux/Windows runner，正式 evidence receipt 已在冻结 Python 3.12 环境完成全部 1672 tests。

下一步只允许一次普通 fast-forward 推送，确认远端 Linux/Windows CI 与 GitHub URL fresh clone。完成前 B28 仍不得
执行。G0/G1 为 A 环境离线 `PASS`，G2–G7 保持 `BLOCKED`；其余 NO-GO 事实不变。

## 6. 第二次远端运行与再次退回 preparation

delivery 与 clone QA 记录提交为 `55cbef2ec3afc63d876c624ee174df8798ef2dbc` 后，普通 fast-forward 推送成功；
GitHub 分支 SHA 与本地精确一致。新 Fresh-clone reproducibility run 为 `29649284949`：

| job | GitHub ID | 结果 |
|---|---:|---|
| Linux reproducibility | `88092722622` | SUCCESS；说明本轮 Linux fresh-clone 全链已闭合 |
| Windows native collector | `88092722616` | FAILURE；setup-python=3.12.10、setup-uv=0.9.25 成功，bootstrap 仍报 pinned uv |

独立日志审查确认，现有单一错误消息混合了路径发现、进程启动、返回码和版本不符，不能把根因只归因于
`shutil.which("uv.exe")`。修订合同使用固定 setup-uv action 已声明的 `uv-path` output，通过专用环境变量传入；代码仍
要求存在的绝对文件路径和精确 `uv 0.9.25`。变量存在但为空/相对/非文件时 fail-closed，不得 PATH fallback；Windows
版本检查保留 `PATHEXT/TEMP/TMP/UV_CACHE_DIR` 等受控 runtime 环境，后续 native pytest 也使用同一显式路径。

该修改触及 workflow、bootstrap 和 resume doctor，属于 evidence 后实现输入变化。故 `handoff-80d8cb2c06104fcf3c74`
已撤回，CURRENT 移除，ledger active 清空，state 回到 `complete-evidence-implementation`；不得沿用上一 Kit/bundle。

## 7. R9B clean evidence 与刷新 delivery

最终独立复审 Critical=0、Important=0。clean evidence commit 为
`982ce2bd11ad971b9614e12d38a6830b5a7789ba`，tree 为 `b4e423ac2faccbcc0c11e65e8a10917ece862c88`。
从该精确提交运行正式 receipt：

| 项目 | 固定结果 |
|---|---|
| lock / Development doctor | 24 packages resolved / PASS |
| 完整 pytest | `1678 passed, 19 warnings in 252.17s` |
| inventory / check | 90 records / 16 components、2 tools；零 diagnostics，formal eligible |
| Kit / ZIP SHA-256 | `kit-a235b5dd5fc27d09b7de` / `cee08464bf22024f733b2277e61defdf448e76f41b18082225ffb880fec7fe45` |
| Kit tree / sidecar SHA-256 | `772699f6df4b56d507c996116848d4c515112d7166835ab65c2836835bc6930b` / `5575207cef866ffaac6ca7202d4a69ea020c7fd9a7b7d9995a3971a00888b494` |
| 四 verifier / collector smoke | 全通过；collector pyz SHA-256 `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` |
| pre-issuance snapshot SHA-256 | `4f33ce6b2e07a91929563f9bb5bec6816d2a8a10782fe704284dadeb27567c7b`；active 为空、五份历史 handoff withdrawn |
| handoff / SHA-256 | `handoff-be908ee37a9b5beba0b5` / `d7b87d0ee40ac3dc8c4ead0425014723b926fcbeb52923e37e91d54ea0c5c4d9` |
| created / expires | `2026-07-18T15:33:27Z` / `2026-07-25T14:33:26Z` |
| active ledger | captured `2026-07-18T15:33:33Z`；SHA-256 `feb03d9ddd3508cc82e947a2de78bba016a1d64ab116f02c3309a7b09143b281` |
| operator bundle | `bundle-44c7a1ae951d2917309fc9d5`；两次完整目录相同，61 files、约 700 KiB |
| provenance / content SHA-256 | `44c7a1ae951d2917309fc9d5d5aea8bf583b080254a512dc8b8e7d789430c5de` / `b144330c4517407927152295c7510a283c953f09c3df0b9d566c14cde51bf092` |

两个 Discovery skeleton 与两个 operator bundle 分别逐字节相同；公开 bundle 不含 CATVBA、用户/主机/DSLS 标识、
客户路径或真实现场数据。delivery record 已提交为 `8dac3a48a060566b3fc5b2ab8cb287066f141b62`，其父提交精确为
evidence `982ce2bd11ad971b9614e12d38a6830b5a7789ba`。随后以 `core.autocrlf=true`、
`core.quotepath=true`、`--no-local` 新克隆：Development/Delivery doctor、严格 selector 均通过，source 与 clone 的
CURRENT、ledger、provenance、handoff、Kit ZIP、collector pyz SHA-256 全部一致，工作树干净。

G0/G1 仅为 A 环境离线 `PASS`；远端 Linux/Windows 与 GitHub URL fresh clone 完成前，B28 继续 BLOCKED，
G2–G7 与 release 继续 BLOCKED。

## 8. 第三次远端运行与 Windows extensionless action output

evidence/delivery/clone 记录推送后，远端精确为 `768a4d1ac4f9c96f9586944c8596f723d3394efc`，run
`29650442197` 的 Linux job `88095767311` SUCCESS，Windows job `88095767287` FAILURE。Windows 日志提供了新的
精确事实：setup-uv 0.9.25 成功，官方 `uv-path` output 为
`C:\hostedtoolcache\windows\uv\0.9.25\x86_64\uv`，即省略 `.exe`；代码按“原样路径必须存在”正确 fail-closed，
但没有实现 Windows command extension 语义。

R9C 只允许以下窄修复：显式路径必须绝对；仅当 `os.name == "nt"` 且路径无后缀时，检查同目录同名 `.exe`；不得
搜索 PATH、其他目录或其他扩展名；解析后继续执行精确 `uv 0.9.25` 校验。Linux 与带后缀路径行为不变。新增脚本层和
doctor 层 extensionless Windows action-output 回归。

该修改再次触及 evidence 输入，故 `handoff-be908ee37a9b5beba0b5` 已撤回，CURRENT 移除，ledger active 清空，
state 回到 preparation。上一 `982ce2b` Kit/bundle 只保留历史审计身份，不能继续授权 B28。

## 9. R9C clean evidence 与本地 delivery

窄修复完成后的 clean evidence commit 为
`7477c28759fcb6a7188caba8dc5386264b90fe2b`，tree 为
`c1642f2bdccee8f7ca2bd3d0bc6b5d06dfb524ae`。独立复审结论为 Critical=0、Important=0；两个 Minor 是
Windows 分支在 Linux 上通过 monkeypatch 模拟，以及解析仍服从普通文件系统的 symlink/reparse 语义，均不扩大
显式路径合同，不阻断 A 环境签发。

从该精确提交运行正式 receipt：

| 项目 | 固定结果 |
|---|---|
| lock / Development doctor | 24 packages resolved / PASS |
| 完整 pytest | `1682 passed, 19 warnings in 248.98s` |
| inventory / check | 90 records / 16 components、2 tools；零 diagnostics，formal eligible |
| Kit / ZIP SHA-256 | `kit-256c8986f4a57bc0942f` / `a81d39cc596dff18e84be70f5b910f765a8538d3ed912d8d2c9aeb10cd7e327f` |
| Kit tree / sidecar SHA-256 | `06f18a766c5769b7c68da963ea590a1992fcca3244add738586fdcbe462fd252` / `7cfb3e72720720e7c74994a885c4bcbe3990b5483f0e6bb81f4389a2f424ce08` |
| 四 verifier / collector smoke | 全通过；collector pyz SHA-256 `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` |
| pre-issuance snapshot SHA-256 | `d1b33e9d37d0fae8db5ea5bc8b69026e7a6744536b577bbd9bfdc1b4375a4fe7`；active 为空、六份历史 handoff withdrawn |
| handoff / SHA-256 | `handoff-bc6d14adc7f50224591e` / `8cfc6c442abe985f6f3c7f08e28022603552c6c7cb33c601b262a3c18712875b` |
| created / expires | `2026-07-18T15:59:00Z` / `2026-07-25T14:59:00Z` |
| active ledger | captured `2026-07-18T15:59:07Z`；SHA-256 `042c16aba8e28202ebb514c7c94fada709b47c29432de96b8cdbb1e77fefa561` |
| operator bundle | `bundle-9474bfe2ad5dda7fc64f5ce2`；两次完整目录相同，61 files |
| provenance / content SHA-256 | `9474bfe2ad5dda7fc64f5ce2c87198589d9297ce69ac84c989b6505c6d0a3ba9` / `2beedfefade73206f2b3e1a9381c3c54cfc73615a39fa5e0e965f50f231d7356` |

两个 raw Discovery skeleton 与两个 operator bundle 分别逐字节相同；公开 bundle 不含 CATVBA、用户/主机/DSLS
标识、客户路径或真实现场数据。当前只允许认定 G0/G1 为 A 环境离线 `PASS`；delivery commit、本地
autocrlf/quotepath clone QA、远端 Linux/Windows CI 与 GitHub URL fresh clone 完成前，B28 继续 BLOCKED，
G2–G7 与 release 继续 BLOCKED。

delivery record 已提交为 `b6a3bbf3f901c5e53c2d532da6f4c65762961dee`，其父提交精确为 evidence
`7477c28759fcb6a7188caba8dc5386264b90fe2b`。随后以 `core.autocrlf=true`、
`core.quotepath=true`、`--no-local` 新克隆并原子建立批准的本地 `dev`：Development/Delivery doctor 均
`ok=true`，严格 selector 唯一选择 `bundle-9474bfe2ad5dda7fc64f5ce2`；source 与 clone 的 CURRENT、ledger、
provenance、handoff、Kit ZIP、collector pyz 逐字节相同，克隆工作树干净。

bootstrap 已通过 Git/控制文件预检，但当前托管环境无法解析 `files.pythonhosted.org`，故 fresh clone 的在线
`uv sync --frozen` 停在依赖下载。该网络限制不计作仓库通过，也不计作实现失败；GitHub Hosted Linux/Windows runner
必须从零完成在线安装和后续测试，成功前远端状态保持 pending。

## 10. 第四次远端运行与稳定版本输出根因

R9C evidence/delivery/clone 记录普通 fast-forward 推送后，远端精确为
`cfb9b0908c5368f91bc31ac5fd76fa38707ad3ad`。Fresh-clone reproducibility run `29651458545` 的 Linux job
`88098390129` SUCCESS：在线 frozen install、完整 suite、确定性双构建、selector 与 artifact upload 全部通过。
Windows job `88098390116` 在 bootstrap 版本校验失败；日志显示 setup-uv 0.9.25 成功，extensionless
`MACRO_MENU_UV_EXECUTABLE` 已不再报 path unavailable，而是 `bootstrap pinned uv version does not match state`。

官方 uv 帮助文档明确：`uv --version` 与 `uv self version` 同输出，可包含 build commit/date；`uv -V` 明确不包含
build commit/date。根因不是版本错误，而是把跨平台非稳定展示格式用于整行身份校验。R9D 采用最窄合同：两条生产路径
都调用 `uv -V`，仍要求 stdout 整行精确等于 state 的 `uv 0.9.25`；不做前缀匹配、不截断输出、不放宽显式路径、
版本、PATH 或受控环境要求。

该修改再次改变 evidence 输入，故 `handoff-bc6d14adc7f50224591e` 已加入 withdrawn，CURRENT 移除，ledger
active 清空，state 回到 preparation。`bundle-9474bfe2...` 只保留历史审计身份；新完整 receipt、Kit、handoff、
delivery、双平台 CI 与 GitHub fresh clone 完成前，B28 继续禁止执行。

本地聚焦回归为 `137 passed`；固定 uv 0.9.25 下 `uv lock --check` 通过，pre-evidence 完整回归为
`1683 passed, 19 warnings in 269.57s`。19 条仍全部来自 oletools/pyparsing 第三方 deprecation。

首个 formal verifier 调用在父环境保留 `MACRO_MENU_UV_EXECUTABLE` 时，使三个本应验证 PATH 分支的测试误走显式
路径分支；生产 doctor 已通过，失败属于 fixture 环境隔离。三个测试现显式清除该变量后再验证 PATH 行为，不改生产合同。

## 11. R9D clean evidence 与本地 delivery

最终 clean evidence commit 为 `957d0f23c40513a9b82d583e8428d7c85d1710c5`，tree 为
`fe3d79dedfeb282e5e80f8ebf0a345b927811b35`；独立复审 Critical/Important/Minor 均为 0。正式 verifier：

| 项目 | 固定结果 |
|---|---|
| lock / Development doctor / pytest | PASS / PASS / `1683 passed, 19 warnings in 254.89s` |
| inventory / check | 90 records / 16 components、2 tools；零 diagnostics，formal eligible |
| Kit / ZIP SHA-256 | `kit-1ce7c253b8220c5aa53b` / `8f5b213c7194092d425959c42d4254df941cccbc4b0708568c935b542adf8544` |
| Kit tree / sidecar SHA-256 | `c9650449cadea0220c9b944849209f36e998104c708fa41ba9aca88ab0e0cf8b` / `ec4255eb2b47095bb3c6b36925b8b8d7190ab430c1a1c4577b48cf3095349141` |
| issuance snapshot SHA-256 | `735d333e2f492f07776bd6f78bc5e75858a28fc712065aa01737fbef300e1834` |
| handoff / SHA-256 | `handoff-abb194d469d790637ab1` / `31cb3a4c5659715601f03e8484e1731337523ae53e7b6a62514c00c874c484f9` |
| created / expires | `2026-07-18T20:01:32Z` / `2026-07-25T19:00:38Z` |
| active ledger | captured `2026-07-18T20:01:40Z`；SHA-256 `388951eed48e88861206d86457cb04546a61a935e5bd79faafc48f383e09d6f5` |
| operator bundle | `bundle-e4d5b791d8ce5dd442529605`；两次目录一致，61 files |
| provenance / content SHA-256 | `e4d5b791d8ce5dd442529605337da0e36712ecb9858365673703d89820bdf35c` / `c0769c5fe635584e178cc3c249d4be4405c0504551273cc40e3773020d5b5de8` |
| skeleton / collector pyz SHA-256 | `db1dbbb06cd64240671d32a1a522368af2b40479ff3b73fa72a2a55841456f53` / `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` |

所有 target truth 仍为 not-run/not-produced，`release_eligible=false`。delivery commit、clone QA、远端双平台与
GitHub URL fresh clone 完成前，B28 继续 BLOCKED。

delivery record 已提交为 `105bfadac76aad96307166d39b2f2c05a1f91c56`，其父提交精确为 evidence
`957d0f23c40513a9b82d583e8428d7c85d1710c5`。autocrlf/quotepath `--no-local` 新克隆中，Development/Delivery
doctor、严格 selector 与 CURRENT/ledger/provenance/handoff/Kit ZIP/collector pyz 六项 byte compare 全通过；
工作树干净，唯一选择 `bundle-e4d5b791d8ce5dd442529605`。
