# 环境复刻与仓库治理修订记录

状态：HISTORICAL EVIDENCE AND DELIVERY RECORD / REMOTE FOLLOW-UP RECORDED 2026-07-18

日期：2026-07-16

范围：`codex/dev-review-report` 的开发环境合同、恢复脚本、CI、状态机、文档与仓库同步边界。本文记录 A 环境事实，不是 B28/CATIA 执行或发布证据。

> 2026-07-18 更新：本文记录的远端阻塞后来已解除，分支发布到 `2098484`。首轮远端 CI 的反馈与下一 evidence
> 周期见 `2026-07-18-remote-publication-and-ci-correction.md`；本文中的旧 active handoff 已撤回，不再授权 B28。

## 1. 复现的根因

- Git for Windows `core.autocrlf=true` 的 clean clone 会改变 `uv.lock`、intake、CURRENT、ledger 和 bundle provenance 的工作树 bytes，导致 lock/bootstrap/doctor 不可复刻。
- Development bootstrap/doctor 误依赖 24 小时 ledger freshness 和 handoff expiry，导致源码未变时仍随墙钟失效。
- Windows CI 用 `python -m catvba_refactor.macro_build.cli` 调用没有模块入口的文件，doctor 实际未执行。
- bootstrap 在验证精确 uv 版本之前就可能改写 `.venv`；Python 项目又没有明确拒绝 3.13。
- 仓库跟踪了无效 Antigravity/Gemini/Cursor/IDE 配置、GBK 全局设置和本机绝对路径样例；日期化计划引用不存在的外部 skills。
- 根 `build/` 未忽略，多层 README、状态和发版文档仍复制旧候选数、旧 bundle/handoff 与旧任务描述。
- 首轮最终 delivery fresh clone 暴露 Git path 展示层缺陷：`git diff --name-only` 在 `core.quotepath=true` 下会把 `Docs/发版.md` 转义并加引号，合法的 docs-only delivery 因而被误判为实现输入变更。

## 2. 已实施的修订

- `.gitattributes` 固定文本 LF，并对 `artifacts/b28-discovery/**` 使用 byte-preserved 属性；新增对应回归。
- Python 合同统一为 `>=3.12,<3.13`，lock 与项目元数据一致；bootstrap 在 sync/`.venv` 变更前验证 `uv 0.9.25`。
- `doctor --scope development|delivery` 分层：开发范围不因 ledger/handoff 时效失败，交付范围默认且继续 fail-closed。
- preparation/无 active bundle 时，Development doctor 可验证源码环境，Delivery doctor 必须返回 `RESUME_DELIVERY_NOT_ISSUED`。
- bootstrap、verify-resume 和 Linux/Windows CI 使用 development scope；Windows CI 改为实际 console entrypoint。
- 删除无效代理/IDE个人配置；忽略 `.context/`、`.antigravity/`、`.cursorrules`、`.vscode/`、根 `build/` 与 `user_data.json`，新增无绝对路径的 `user_data.example.json`。
- 建立当前开发规格、唯一活动计划、环境复刻指南和日期化审查；同步根入口、STATUS、RESUME、发版、项目结构、子目录 README、历史计划状态和决策台账。
- 受管输入变化后把 `resume/state.json` 返回 preparation：移除 CURRENT，清空 ledger active 集，将上一 handoff 列入 withdrawn；无 active bundle/Kit/handoff，G0=`PASS`、G1–G7=`BLOCKED`、`release_eligible=false`。
- delivery 边界改用 `git diff --name-only -z` 与原始路径解码，新增 `core.quotepath=true`、中文文档名和 evidence 后提交的真实 Git 回归；允许路径集合保持不变。

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
| 完整 `pytest -q` | 最终修订后 `1664 passed, 19 warnings in 226.04s` |
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

## 6. Clean evidence、fresh clone 与新 delivery

最终 evidence commit 为 `f2c9d8d8cd1e448444dd43aadb5e4fa57b5c86d0`，tree 为
`6d9e36b85b5f8d1294c9934dff625497bc2441c9`。它没有采用浮动 `origin/dev`。从该精确 commit 运行
`verify_resume.py` 的 receipt 为 `ok=true`：

| 项目 | 结果 |
|---|---|
| lock / Development doctor | PASS / PASS |
| 完整 pytest | `1664 passed, 19 warnings in 223.71s` |
| inventory / check | 90 records、零 diagnostics / 16 components、2 tools、零 diagnostics；均 `formal_eligible=true` |
| 双 Kit | `kit-a09bfd3dcb7264c8bc0e`；目录、ZIP、sidecar 逐字节一致 |
| Kit ZIP SHA-256 | `87a0e4f283ee46d220a2e4d297f6de62a31c70a845af48ededacdab3723f8333` |
| 四 verifier | directory/ZIP × primary/comparison 全部 `ok=true` |
| collector smoke | pyz help PASS；synthetic fixture expected-fail-closed PASS；target/compile 均 not-run |

另以 `git clone -c core.autocrlf=true --no-local` 真实检出 `f2c9d8d`：工作树 clean，lock、state、intake、
撤回 ledger 与历史 provenance bytes 与源 clone 相同；从空 `.venv` frozen bootstrap 和 Development doctor 均 PASS。
此前同代码提交 `9990b4f` 的 autocrlf clone 还完整执行 `verify_resume.py`：1664 tests、双 Kit、四 verifier 与 collector
smoke 全部 PASS。两次都没有复制本地 `.venv`。

在签发前 canonical snapshot 中，`active_handoff_ids=[]`，旧 `handoff-6ed312ee18b254cb3c13` 与
`handoff-b8d9d535604e78551423` 均为 withdrawn。新 handoff/bundle 结果：

| 项目 | 固定值 |
|---|---|
| handoff / SHA-256 | `handoff-56097be57a37a63c7644` / `ad6ca230bab403077f0fba8ea6ae11157b555d6605613fb862fe9c0818c4a141` |
| created / expires | `2026-07-16T15:20:31Z` / `2026-07-23T15:19:09Z` |
| active ledger captured | `2026-07-16T15:20:36Z`；只激活新 handoff，SHA-256 `f48e03b8ec77b3d18ad1596e3a2be0ea3dce06ad424f8572a19f473b004a4721` |
| operator bundle | `bundle-6b7518a2e3c969d2383fcb60`；两次构建完整目录相同 |
| provenance SHA-256 | `6b7518a2e3c969d2383fcb60429cb0c584389e06fada95b6342b70736abcd1ac` |
| authenticated content SHA-256 | `0b9c0d4bd45513657304632a4b091a1ea502931954c30262039a4dfdd264b93f` |
| collector pyz SHA-256 | `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` |
| CI selector snapshot ZIP SHA-256 | `83a06dac4a159a57f35a4426cb7526bf0ab5a7affe3e52c661184e694a6072fb`；`available=true` |
| public tree | 61 regular files，约 700 KiB；不含 raw capture、客户数据或 CATVBA |

本地 Delivery doctor 在 current state/CURRENT/bundle/fresh ledger 上必须 PASS。远端仍停在 `037ab406...`，所以这份
local delivery 在 fast-forward push、GitHub CI 和 GitHub fresh clone 完成前不得交给 B28。签发不改变
`compile_status=not-run`、30 cases=`not-run`、CATVBA=`not-produced`、G2–G7=`BLOCKED`、`release_eligible=false`。

## 7. 最终 delivery clone 反馈与第二修正周期

对 `08daced43c7cf423d9b4f5bebb6fc83e3fd80384` 做 `core.autocrlf=true` 的全新克隆时，commit/tree、lock、intake、
CURRENT、ledger 和 bundle provenance bytes 均正确，但 bootstrap 返回 `delivery commits changed implementation inputs`。
根因不是制品越界，而是 Git 把中文路径输出成带引号的转义展示文本，旧代码的 `startswith("Docs/")` 无法识别。

该结果按停止条件处理：移除 CURRENT，把 `handoff-56097be57a37a63c7644` 加入 withdrawn，state 回到 preparation，
并开启第二个 clean evidence/delivery 周期。修复不得通过关闭 `core.quotepath` 或扩大 allowlist 绕过；必须以 NUL 分隔
原始路径、真实 Git commit 回归、完整测试和最终 delivery commit fresh clone 共同关闭。

第二周期 pre-evidence 完整回归为 `1665 passed, 19 warnings in 234.14s`。首次在仓库内 `.venv` 运行得到 4 个
`sys.executable` 找不到的环境失败；同一 lock 在 `/tmp/macro-menu-reorg-venv` 重建后 4 项全部通过，确认失败来自托管
工作区反复改写 ignored `.venv` 链接，而不是产品代码。正式 evidence receipt 仍必须从 clean commit 重新生成。

## 8. 第二周期 clean evidence 与重新签发

修正后的 evidence commit 为 `43274914149a67c3f076e5322e86060e3b1d1cc1`，tree 为
`190494ac751fff8b51b925413f46b426f4e5eb25`。从该精确提交运行 `verify_resume.py` 得到 `ok=true`：

| 项目 | 固定结果 |
|---|---|
| 完整 pytest | `1665 passed, 19 warnings in 235.33s` |
| inventory / check | 90 records / 16 components、2 tools；零 diagnostics，均 `formal_eligible=true` |
| Kit / ZIP SHA-256 | `kit-87ecc7bcf3d8f9deaf99` / `165d044494a583cebf292e3e3df0f438cb4c3918d2d7ee7bb87055893d719af1` |
| Kit tree / sidecar SHA-256 | `f48f37ce9b6d612785fd4e417e2f6d5d7aae105a85c99278e85a7f95caae52f6` / `4aec1bc19d4e61b6d26b91fc97b0a9c8ff7581901bf965faeb404eaca5efcd8b` |
| 四 verifier / collector smoke | directory/ZIP × primary/comparison 全部通过；pyz help 与 synthetic expected-fail-closed 通过 |
| pre-issuance ledger | active 为空；三份旧 handoff withdrawn；SHA-256 `65670c6ba2759c4504b80ef8cb807cf4551e44db32d0ab342aedde279e9295ee` |
| 新 handoff / SHA-256 | `handoff-07bbe55bc7552489cd55` / `f301e8b4a89de22add30a6ebc7092de5013824dd81c81c2ffa582dd71639d3fa` |
| created / expires | `2026-07-16T15:52:15Z` / `2026-07-23T15:51:52Z` |
| active ledger | captured `2026-07-16T15:52:25Z`；SHA-256 `94324963be7d1a74fac30896c4574dcda595139feb0287ab9a3a62f0fee73425` |
| operator bundle | `bundle-95bce28983237f5d84d0cbfd`；两次完整目录相同，61 files、约 700 KiB |
| provenance / content SHA-256 | `95bce28983237f5d84d0cbfd1aadc762f93948a84f16364359f2ebd002f170ba` / `ba089f0859bdcac85185423f861b0c57f3d08e544b694ec26cc836dfb737e00b` |
| collector pyz / selector ZIP SHA-256 | `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` / `ab9fc80cd5cdadcbc2c01318804ebd38b2af2329faaeba43d6de0d94299aca6c` |

artifact delivery commit `29e9d492b31d45f5b7f48360ecabc9b0538a7c04`（tree
`715651c3c779b6d83f1ff15477836b8be045dee5`）已在 `core.autocrlf=true`、`core.quotepath=true` 的全新 clone 中验证：
所有上表关键 bytes 不变，空 `.venv` frozen bootstrap、Development doctor、Delivery doctor 与 selector 均通过；selector
仍选择同一 bundle，ZIP SHA-256 为 `ab9fc80cd5cdadcbc2c01318804ebd38b2af2329faaeba43d6de0d94299aca6c`。
模拟远端 `origin/dev=688911522f88e2283231fb59232ea43edd3174a5` 时，本地 `dev` 仍为批准 cutoff，未采用浮动 dev。

因此 local final-clone 阻断已关闭。远端推送、GitHub Actions 与真正 GitHub fresh clone 继续受外部认证阻塞；这些完成前仍不交给 B28。
