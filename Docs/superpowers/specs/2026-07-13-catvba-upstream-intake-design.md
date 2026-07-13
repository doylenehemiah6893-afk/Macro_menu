# CATVBA 上游 Intake 与 Fork 同步设计

> 状态：DRAFT — 待用户书面复审
>
> 上位规格：[CATVBA R2018 恢复总架构设计](2026-07-13-catvba-r2018-recovery-design.md)

## 1. 目标

让 fork 的 `main/dev` 跟随上游，而个人 `codex/dev-review-report` 保持独立开发；同时让 Build Kit 能固定、
复算并审查每次吸收的上游 `Src/`、`resources/`，避免同步过程静默覆盖本地 overlay。

## 2. 固定角色

```text
UPSTREAM_DEV  = verysolecd/Macro_menu:dev
UPSTREAM_MAIN = verysolecd/Macro_menu:main
FORK_DEV      = doylenehemiah6893-afk/Macro_menu:dev
FORK_MAIN     = doylenehemiah6893-afk/Macro_menu:main
WORK_BRANCH   = doylenehemiah6893-afk/Macro_menu:codex/dev-review-report
```

本规格不使用 `origin/upstream` 作为权威身份；remote 名只是本地操作别名。

## 3. 分支职责

- FORK_DEV 镜像 UPSTREAM_DEV；FORK_MAIN 镜像 UPSTREAM_MAIN；同步由独立人工或 GitHub 自动化维护。
- WORK_BRANCH 只在明确 intake 时吸收 UPSTREAM_DEV，不自动跟随、不被镜像任务覆盖。
- CATVBA 重构、文档、Python 工具、测试和 overlay 只写 WORK_BRANCH。
- WORK_BRANCH 不整体合并 UPSTREAM_MAIN/FORK_MAIN；main 只作发布/workflow/安全观察。
- Build Kit 工具只检查同步状态和固定 cutoff，不自动 push、force-push 或写 `main/dev`。

## 4. Intake 输入

```text
B = 上次 accepted upstream dev cutoff
U = 本次拟吸收 UPSTREAM_DEV commit
O = intake 前 WORK_BRANCH clean committed HEAD
```

首次 intake 可以用经过人工核对的 initial baseline record 建立 B，不要求预先存在复杂自引用证据链。

前置条件：

- O clean 且已提交；
- U 可由上游仓库读取；
- FORK_DEV 与 U 一致，或记录 fork 镜像尚未同步并阻断 candidate；
- `Src/`、`resources/` 与 B 的 Git tree 一致；
- upstream 未占用保留的 `catvba_refactor/**`。

## 5. 三树检查

在 raw Git trees 上比较 B/U/O：

- add/delete/modify/rename 提示；政策上 rename 按 delete+add 审核；
- portable path、Unicode/case、Windows 保留名和 file/dir 冲突；
- `VB_Name`、FRM/FRX 配对和目标组件身份；
- override base 的 path/blob/raw SHA 是否变化；
- package/capability/tool ID 和 Reference 影响。

以下阻断自动 intake：

- upstream 创建 `catvba_refactor/**`；
- add/add、rename/delete、rename/rename、delete/modify 或目标路径碰撞；
- FRM/FRX 任一侧同时变化；
- override base 变化或被删除/改名；
- manifest 指向孤儿组件；
- `.gitattributes` 试图用未知 `merge=theirs` 自动处理 FRX/CATVBA。

禁止 fuzzy patch、自动只选 theirs/ours、只改 hash 消红或静默回退新版 upstream。

## 6. Override 处置

上游未触及的 override 保持原 binding。被触及的 override 标记 `STALE_BASE`，逐项选择：

1. 上游已包含修复：退役 override；
2. 本地意图仍需要：基于 U 重新实现并重新绑定；
3. 功能不再进入候选：Quarantine；
4. 无法判断：阻断 intake。

不得自动三方合并 CP936 VBA、FRM/FRX 或安全敏感模块。

## 7. Git 历史策略

- 尚未产生 Build Kit/目标证据的早期个人提交，可在用户明确同意时整理；
- 一旦 commit 已绑定 Kit 或目标证据，不 rebase、不 force-push；
- 正式 intake 使用可审查 merge commit，第一父为 O、第二父为 U 或经证明等价的 FORK_DEV；
- intake commit 只包含上游吸收和必要 binding 处置，不混入新业务功能；
- 后续单独提交简化的 intake record，避免记录自引用自身 commit/hash。

## 8. Intake Record

记录至少包含：

```text
upstream_repository/ref/old_commit/new_commit
fork_dev_commit
work_pre_intake_commit
merge_commit
changed_paths
override_decisions
portable_path/FRM-FRX/reference checks
tests and results
approver/status
superseded kit IDs（如有）
```

record 的文件 path、blob OID 和 raw SHA-256 由包含它的后续提交复算；首个 Build Kit 只需固定已批准 record，
不要求额外构造复杂链式身份协议。未来确有审计需求时再通过独立 ADR 扩展。

## 9. 验收

- FORK_MAIN/FORK_DEV 同步流程不会触碰 WORK_BRANCH；
- WORK_BRANCH intake 不写或重写 fork `main/dev`；
- Build Kit 固定的 upstream/fork/work commit 可复算；
- upstream 更新不会静默覆盖 overlay；
- stale override、路径冲突、FRM/FRX 双方变化均 fail-closed；
- intake 与业务功能分批提交；
- 已绑定证据的历史不被 rebase/force-push；
- 同步失败只阻断新的 candidate，不破坏旧 Kit 的历史可验证性。

