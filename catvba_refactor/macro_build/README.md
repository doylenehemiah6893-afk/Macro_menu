# Offline build tooling

这里实现无 CATIA 的离线流水线：固定 Git snapshot、strict manifest/schema、inventory、resolver、静态
policy、generated catalog、不可变 Kit/ZIP、完整 verifier 和回传 CATVBA 只读审计。

Python 代码属于根 `macro-menu` 项目，不在本目录建立第二个 `pyproject.toml` 或 `uv.lock`。

## CLI

```text
macro-menu-build inventory [--worktree]
macro-menu-build check [--worktree]
macro-menu-build build-kit
macro-menu-build verify-kit <kit-directory-or-zip>
macro-menu-build audit-catvba <returned.catvba> --expect <kit-manifest.json> [--package <package-id>]
macro-menu-build create-target-handoff <primary-build-root> --compare-build-root <second-build-root> ... --output-root <dir>
macro-menu-build init-target-session <kit> --mode discovery|g2|g3-c --package core --profile <id> --handoff <json> --output-root <dir>
macro-menu-build validate-target-evidence <evidence> --kit <kit> --phase capture|sealed
macro-menu-build evaluate-target-gate <capture> --gate DISCOVERY|G2|G3-C --kit <kit> --output-root <dir>
macro-menu-build record-target-approval <capture> --kit <kit> --gate-receipt <json> --scope observation|gate --status approved|rejected ... --output-root <dir>
macro-menu-build pack-target-evidence <capture> --kit <kit> --gate-receipt <json> --approval <json> --output-root <dir>
```

公共选项 `--repo-root`、`--config-dir`、`--schema-dir`、`--output-root` 和 `--format text|json` 可放在
子命令前后；重复或缩写选项会被拒绝。报告由同一 canonical record 生成，diagnostic 顺序稳定，源码
bytes 不进入 JSON。

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | CLI、manifest 或 schema |
| 3 | source、encoding、resolver 或 policy |
| 4 | Git object、I/O、锁或 staging 基础设施 |
| 5 | Kit 或 CATVBA 验证 |
| 6 | evidence 结构、容器、哈希或 binding 无效 |
| 7 | 合法计算出的 Gate `fail` 或 `blocked`；receipt 仍写出 |

## 模式与输出边界

- candidate 只读 exact committed Git blobs，要求 clean governed tree、fork/upstream cutoff 相等；
- `inventory/check --worktree` 读取 filesystem bytes，只作诊断，始终 `formal_eligible=false`；
- `build-kit` 会重新走 candidate 全链，不接受 worktree，也不输出空/失败 Kit；
- Kit 在全量 preflight、自校验和完成标记之后原子 rename，ZIP 使用固定元数据与排序；
- `verify-kit` 对目录或 ZIP 做 no-follow、完整图、hash、身份和 policy 复验；
- `audit-catvba` 先验证 expected Kit，再在受限只读副本中检查一个 package；p-code 只作 diagnostic。
- target evidence 命令各自只消费一次 authenticated Kit snapshot；capture、receipt、approval 和 sealed
  directory/ZIP 分层验证，`fail|blocked` 也可作为历史结论封存，但不能升级 Gate；
- mutating target 命令必须显式给出 `--output-root`，不会修改 Kit、handoff 或 capture。

当前 clone 已由独立 intake 流程接受精确 cutoff 并原子建立本地 `refs/heads/dev`；仓库已有获批 Core
candidate、可复算的历史 G0/G1 Kit 证据和完整 evidence harness。下一步仍须从当前干净提交生成新的
discovery Kit/handoff，再到 B28 采集真实证据。不得回退 `HEAD`、猜测 remote 或自动写 fork `main/dev`。
这些工具不调用 CATIA，不执行 VBA，也不能产生 Compile、References、许可证或 UI 事实；未有真实目标证据前
始终保持 `compile_status=not-run`、`release_eligible=false`。
