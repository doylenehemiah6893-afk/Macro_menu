# Offline tests

本目录保存 A 环境 pytest、攻击面 fixture 和端到端构建证明。

本地测试只能验证 Python、manifest、源码结构、政策、确定性打包和只读审计；VBA Compile、CATIA API、
许可证和 UI 行为必须保持 `NOT_RUN/BLOCKED`，直到 B28 返回证据。

当前 discovery evidence 精确绑定 clean commit
`2c3d501eaf017a41d838bf2ce39214fd1291802c`、tree
`42447cc3ae72d657f76be39355fa134230b1ff28`；本状态文档提交不是被构建输入。完整离线验证为：

```text
UV_NO_SYNC=1 UV_PYTHON=<pinned-python> UV_CACHE_DIR=/tmp/uv-cache .venv/bin/python -m pytest -q
1306 passed, 19 warnings
```

`test_end_to_end.py` 以临时 Git fixture 验证严格双构建、目录/ZIP verifier、dirty candidate、worktree
失败关闭，以及完整 synthetic discovery→formal G2→Core-only G3-C 链。该链验证 blocked discovery/G3
仍可审批封存、eligible G2、formal supersede/provenance 和内外层 review ID 隔离，但不生成 CATVBA，也不升级
目标机状态。

同一 clean commit 的仓库 inventory 为 90 个 discovered（13 candidate + 77 quarantine），check 为 16 个
component、2 个 tool；均 `ok=true`、`formal_eligible=true`、零 diagnostics。两个独立输出根生成完全相同的
`kit-feb504676720445f729c`：catalog SHA-256
`feb504676720445f729c91075f9a8cd40d2a75f35defe2821a297b02b2dd6a5b`，manifest SHA-256
`fa4feb560f07368c64f0115f9575ae5d38d6e4e85de8f65f9ef7125705436fa5`，manifest digest
`ca28e71f310505463f382f2affe18d5d96f4fc747d66a1eb8e20a730c1d83240`，ZIP SHA-256
`acecc6c8aeb62bc54e7fddbb8975e9fba2652deb8935d6351817b5fcbc1de571`。两套完整目录、ZIP 和 sidecar
逐字节一致，目录/ZIP 四次 verifier 均 `ok=true`、零 diagnostics，并经独立复核通过。

唯一 discovery handoff 为 `handoff-6ed312ee18b254cb3c13`，SHA-256
`a27b0a0ae1ff0e0ac819c0458c040fa0788437ac44a2c7ce61fe86861ef0f0f5`，到期 UTC
`2026-07-22T09:00:00Z`，无 supersedes。相同输入在两个输出根生成逐字节一致的
`session-20260715-discovery-2c3d501` 空 skeleton，payload digest 为
`6f178b23f6dcbcf4a9afeea784db848ab399b7a0d1d936a433bcfd82350865a3`，两次 capture validation 均
`ok=true`。它没有目标 observation、Gate、approval、sealed evidence 或 CATVBA。完整身份与证据边界见
`Docs/STATUS.md`。

其余测试覆盖 snapshot/cutoff、schema/语义校验、UTF-8/CP936、Windows portable path、FRM/FRX、
override、Core/Fleet policy、generator、锁/原子 staging、恶意 Kit/ZIP、bounded/TOCTOU CATVBA 审计和
CLI 退出码，并锁定 Core Runtime 静态结构、目标 test-plan 和 Form bundle staging。测试不启动 CATIA、
不联系网络、不修改 `Src/resources`、不写 CATVBA。当前结论只能是：绑定 discovery Kit 的 G0/G1 在 A 环境
为 `PASS`；30 个目标 case 全部 `not-run`、`compile_status=not-run`、`release_eligible=false`，G2–G7 仍为
`BLOCKED`。
