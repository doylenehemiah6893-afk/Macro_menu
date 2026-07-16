# Offline tests

本目录保存 A 环境 pytest、攻击面 fixture、fresh-clone 环境合同和端到端确定性构建证明。

测试只能验证 Python、Git/manifest/source binding、源码结构、政策、确定性打包、只读审计、evidence container、
resume/doctor 与原生 collector 合同；VBA Compile、CATIA API、许可证和 UI 行为必须保持
`NOT_RUN/BLOCKED`，直到 B28 返回真实证据。

## 当前执行方式

先按仓库根 `RESUME.md` 或 `Docs/ENVIRONMENT_REPRODUCTION.md` 创建冻结 Development 环境：

```bash
uv run macro-menu-build doctor --state resume/state.json --scope development --format json
uv run pytest -q
```

准备 B28 转运时必须另外执行 `doctor --scope delivery`；ledger/handoff 过期只阻止 Delivery，不得让长期
Development 复刻和 CI 假失败。

## 覆盖范围

- snapshot/cutoff/intake/branch/replace-ref/clean-tree 与跨平台行尾；
- strict schema、canonical JSON、portable path、UTF-8/CP936、FRM/FRX 原子性与 override base；
- Core/Fleet policy、generator、Kit/ZIP staging、四路 verifier 和恶意 archive；
- bounded/TOCTOU CATVBA 只读审计；
- discovery/G2/G3-C session、Gate、approval、seal 与 raw/untrusted collector；
- operator bundle、CURRENT/ledger/handoff、development/delivery doctor、bootstrap 和 CI selector；
- Linux/Windows wrapper、pyz smoke、敏感数据和本机配置排除合同。

最新已提交 evidence identity、完整测试数、Kit/handoff/bundle 摘要只在 `resume/state.json`、
`artifacts/b28-discovery/CURRENT.json`、`Docs/STATUS.md` 和 process record 中维护，本 README 不复制易过期标识。

测试不启动 CATIA、不修改 `Src/resources`、不写 Production CATVBA。无论 pytest 数量多少，真实目标证据返回前
始终保持 30 个 target case=`not-run`、`compile_status=not-run`、`release_eligible=false`、G2–G7=`BLOCKED`。
