# Offline tests

本目录保存 A 环境 pytest、攻击面 fixture 和端到端构建证明。

本地测试只能验证 Python、manifest、源码结构、政策、确定性打包和只读审计；VBA Compile、CATIA API、
许可证和 UI 行为必须保持 `NOT_RUN/BLOCKED`，直到 B28 返回证据。

2026-07-13 的完整验证：

```text
uv run pytest -q
405 passed
```

`test_end_to_end.py` 在临时 Git 仓库创建一个安全 module、完整 FRM/FRX、strict manifests、一个 Core
package 和一个 tool；两次独立构建必须得到相同 kit ID、catalog、SHA256SUMS、manifest/ZIP hash 和
ZIP bytes，并分别通过目录与 ZIP verifier。随后 dirty candidate 必须 exit 3、向 stderr 写错误 JSON
且不创建输出目录；worktree check 必须 exit 0、`formal_eligible=false` 且没有 Kit path。

其余测试覆盖 snapshot/cutoff、schema/语义校验、UTF-8/CP936、Windows portable path、FRM/FRX、
override、Core/Fleet policy、generator、锁/原子 staging、恶意 Kit/ZIP、bounded/TOCTOU CATVBA 审计和
CLI 退出码。测试不启动 CATIA、不联系网络、不修改 `Src/resources`、不写 CATVBA；所以 G1 仍为
`NOT_RUN`，G2–G7 仍为 `BLOCKED`。
