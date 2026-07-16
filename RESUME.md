# Macro_menu 新环境续作入口

状态：CURRENT / preparation

唯一仓库：`doylenehemiah6893-afk/Macro_menu`

唯一工作分支：`codex/dev-review-report`

唯一下一动作：`complete-evidence-implementation`

## 1. 取得方式与不可越过边界

开发续作必须完整 `git clone`，不能使用 GitHub Download ZIP；ZIP 不含完整 object/ref 历史，无法验证 approved cutoff
和 intake baseline。Download ZIP 只可用于取得已经发布在仓库中的目标机 operator bundle，不能作为开发工作树。

```bash
git clone --branch codex/dev-review-report --single-branch https://github.com/doylenehemiah6893-afk/Macro_menu.git
cd Macro_menu
git branch --show-current
git rev-parse HEAD
```

只写 `codex/dev-review-report`；不 merge/rebase/cherry-pick `main` 或 `dev`，不 force-push，不创建 tag/Release，不写
Production 宏库。批准 upstream/fork cutoff 固定为
`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`。远端 `origin/dev` 已前进至其它提交，不能跟随；bootstrap 只会把
本地 `refs/heads/dev` 原子建立在批准 cutoff，不 checkout、fetch、merge 或 reset 浮动 dev。

当前机器可读 baseline 在 `resume/state.json`。preparation 阶段的 `evidence_commit`、`evidence_tree`、
`delivery_parent_commit`、`last_full_test_count` 均为 null；这表示尚未形成可声明的 clean evidence baseline，不能拿
历史 1306 tests 摘要冒充当前结果。Task 10 只有在完整测试和独立复核后，才会把实际 clean evidence commit/tree、
delivery parent 与本轮计数一次性写入。当前 checkout 不得被预填为 evidence，也不得制造自引用 delivery SHA。

## 2. 环境与三条入口

开发/A 环境使用 CPython 3.12、`uv 0.9.25`、根 `uv.lock`。Linux/macOS 使用 shell；原生 Windows 使用
`cmd.exe`。目标 B28 机已有 Python 3.12，明确不能使用 WSL；目标机不运行 uv/Gate/approval/seal。

```bash
python3.12 scripts/bootstrap_resume.py --repo-root . --state resume/state.json
uv run macro-menu-build doctor --state resume/state.json
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root build/resume-verification
```

Windows 开发机等价入口（不是 B28 采集入口）：

```bat
scripts\bootstrap-resume.cmd
uv run macro-menu-build doctor --state resume\state.json
python scripts\verify_resume.py --repo-root . --state resume\state.json --output-root build\resume-verification
```

`scripts/verify_resume.py` 已存在；它在新输出根依次执行 lock、完整测试、inventory/check、双 Kit、四次 Kit 验证、
全树/ZIP/sidecar 比较和 collector pyz/fixture smoke，并生成 canonical receipt。任一阶段非零、输出异常、pyz 漂移或
fixture 行为变化都 fail-closed，receipt 保持 `release_eligible=false`，不得跳到签发或目标机执行。任何
bootstrap/doctor diagnostic、replace ref、shallow clone、仓库/分支不符、cutoff object 缺失、governed path 脏、
state/schema/hash 不符均停止。

## 3. 当前 Gate 与制品真相

| 项目 | 当前状态 |
|---|---|
| G0 / G1 | `PASS`，仅指绑定 approved cutoff 的 A 环境离线输入冻结和 Kit 工具链证据 |
| G2-G7 | 全部 `BLOCKED` |
| active bundle / Kit / handoff | `null`；尚在 `preparation` |
| Compile / 30 target cases | `not-run` / 全部 `not-run` |
| CATVBA artifact | `not-produced` |
| release | `release_eligible=false` |

旧 discovery 标识 `kit-feb504676720445f729c` 与 `handoff-6ed312ee18b254cb3c13` 只存在历史文档和摘要；其实际
bytes 不在仓库、当前环境不可取得，不能作为 active artifact。旧 handoff 在本轮 preparation 中按 withdrawn 处理，
不得仅凭历史 expiry `2026-07-22T09:00:00Z` 恢复使用。Task 11 必须从 clean evidence commit 双构建新的 Kit、签发
新的 handoff、生成新 bundle 与外部 active ledger，验证后才能把 state 的 null 字段改为实际仓库路径与 digest。

G0/G1 不证明 CATIA、VBE References、DSLS checkout、Compile、运行或发布。不得声称目标 B28 已验证。

## 4. 恢复后工作顺序

1. 完成 Task 8 文档合同并提交；Task 9 加入一键 verify 与 Linux/Windows CI。
2. Task 10 全量测试、独立规格/代码复核，形成 clean evidence implementation commit 并更新 state parent。
3. Task 11 在两个独立输出根构建并逐字节比较，签发新 discovery handoff，构建 immutable operator bundle，写
   public receipts/CURRENT/ledger；不运行 CATIA。
4. Task 12 只推本分支，监控 CI，再从新的完整 clone 执行 bootstrap/doctor/verify。
5. 只有 active ledger fresh 且 bundle 验证通过，才把目标包交给 B28 操作员，按
   `Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md` 采集 raw/untrusted。
6. 目标机回传后，A 环境核 hash、严格 ingest、独立脱敏复核；只在 A 环境生成 blocked Discovery receipt、
   observation approval/seal。真实 evidence 不进入公开 Git，仅提交脱敏 public attestation。

## 5. 全部停止条件

- Git 仓库/分支/cutoff/intake/tree/hash/state/lock 不一致，或出现 replace refs、shallow clone、脏受管路径；
- 试图跟随当前 `origin/dev`、写 main/dev、merge/rebase/cherry-pick、force push、tag/Release；
- active bundle/handoff/ledger 仍为空、过期、stale、withdrawn、bytes 不可取得或摘要不符；
- 试图在 B28 使用非原生 Python 3.12、WSL/PowerShell 自动化、脚本控制 CATIA/VBE/DSLS；
- 试图 Compile、运行 30 cases、生成 CATVBA、把 raw/untrusted 当 sealed/PASS；
- 记录用户名、机器名、DSLS server、客户路径/数据，或未经两人脱敏复核；
- 试图在本轮把 G2-G7、release eligibility 或旧 handoff 改为通过/active。

发生任一项时保留原日志和 hash，停止并回到本文件与 `resume/state.json`，不要自行扩大授权。
