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

## 模式与输出边界

- candidate 只读 exact committed Git blobs，要求 clean governed tree、fork/upstream cutoff 相等；
- `inventory/check --worktree` 读取 filesystem bytes，只作诊断，始终 `formal_eligible=false`；
- `build-kit` 会重新走 candidate 全链，不接受 worktree，也不输出空/失败 Kit；
- Kit 在全量 preflight、自校验和完成标记之后原子 rename，ZIP 使用固定元数据与排序；
- `verify-kit` 对目录或 ZIP 做 no-follow、完整图、hash、身份和 policy 复验；
- `audit-catvba` 先验证 expected Kit，再在受限只读副本中检查一个 package；p-code 只作 diagnostic。

当前 clone 无本地 `dev` ref，所以仓库 `check/build-kit` 返回退出码 4，并向 stderr 写规范错误 JSON，但不
生成 Kit 或输出目录。不得回退 `HEAD`、猜测 remote 或自动写 fork `main/dev`。这些工具不调用 CATIA，
不执行 VBA，也不能产生 Compile、References、许可证或 UI 证据；成功 Kit 仍固定
`compile_status=not-run`、`release_eligible=false`。
