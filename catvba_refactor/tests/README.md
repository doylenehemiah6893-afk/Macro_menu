# Offline tests

本目录保存 A 环境 pytest、攻击面 fixture 和端到端构建证明。

本地测试只能验证 Python、manifest、源码结构、政策、确定性打包和只读审计；VBA Compile、CATIA API、
许可证和 UI 行为必须保持 `NOT_RUN/BLOCKED`，直到 B28 返回证据。

2026-07-14 evidence harness 提交 `2082419` 的完整离线验证：

```text
uv run pytest -q
1306 passed, 19 warnings
```

`test_end_to_end.py` 以临时 Git fixture 验证严格双构建、目录/ZIP verifier、dirty candidate、worktree
失败关闭，以及完整 synthetic discovery→formal G2→Core-only G3-C 链。该链验证 blocked discovery/G3
仍可审批封存、eligible G2、formal supersede/provenance 和内外层 review ID 隔离，但不生成 CATVBA，也不升级
目标机状态。此外，真实仓库证据提交 `2645033a25e770fe9855b67e05bdefce42bc1c6a`
的 16 个 Core component 和 2 个 Core tool 已在两个独立 `/tmp` 输出根构建。两次的 Kit ID、catalog bytes、
manifest SHA-256、ZIP SHA-256 和 ZIP bytes 全部相同；两目录+两 ZIP 均由 CLI verifier 返回
`ok=true`、零 diagnostics。精确收据、哈希和清单见 `Docs/STATUS.md`。

其余测试覆盖 snapshot/cutoff、schema/语义校验、UTF-8/CP936、Windows portable path、FRM/FRX、
override、Core/Fleet policy、generator、锁/原子 staging、恶意 Kit/ZIP、bounded/TOCTOU CATVBA 审计和
CLI 退出码，并锁定 Core Runtime 静态结构、目标 test-plan 和 Form bundle staging。测试不启动 CATIA、
不联系网络、不修改 `Src/resources`、不写 CATVBA。因此 G0/G1 仅在 A 环境为 `PASS`；30 个目标
case 全部 `not-run`、`compile_status=not-run`、`release_eligible=false`，G2–G7 仍为 `BLOCKED`。
