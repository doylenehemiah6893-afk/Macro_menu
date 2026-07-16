# B28 Discovery Operator Bundle 构建记录

日期：2026-07-16
范围：Task 11 public delivery；仅 A 环境离线构建，不是 B28/CATIA 执行记录。

## 证据输入与边界

- evidence commit：`68022541bf8cacd1db012128daf4cdef1048af8d`
- evidence tree：`405f24751ddabecced9b547680e6dbdefdeb80be`
- approved cutoff：`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`
- `origin/dev`：`688911522f88e2283231fb59232ea43edd3174a5`，未采用。

在 CPython 3.12.13 / uv 0.9.25 中，bootstrap 与 doctor 均为 `ok=true`。冻结环境完整测试记录为
`1659 passed, 19 warnings`；warnings 是 oletools 的第三方 pyparsing deprecation warnings。它们不证明
CATIA、VBE、DSLS、References、Compile、UI、运行或发布。

## 可复现构建与签发

两个独立输出根的 Kit 完整树、ZIP 和 sidecar 逐字节相同；四次 directory/ZIP verifier 均 `ok=true`、零 diagnostics。

| 项目 | 值 |
|---|---|
| Kit ID | `kit-e93a2e7f48c3f4d2f179` |
| Kit catalog SHA-256 | `e93a2e7f48c3f4d2f17977e5ecf0b01c1d5ffa241c4569ceeed20be7c1d1d736` |
| manifest SHA-256 | `9ecb5f9d91317bf2076054433590bcee0b7661a62bf958df37ee6a0b1556508a` |
| Kit ZIP SHA-256 | `d763b3e1a1a2e33d994a5c030e0fa3b541e8a46648f11378870c6a86711cf012` |
| handoff | `handoff-b8d9d535604e78551423` |
| handoff SHA-256 | `6d889446c62e0de338e6469784166f4d72dd3144618969a2b286748e10e44192` |
| active ledger capture | `2026-07-16T11:12:07Z` |
| expiry | `2026-07-23T11:11:06Z` |

签发前 snapshot 的 active 集为空，withdrawn 集固定包含旧的不可取得 handoff
`handoff-6ed312ee18b254cb3c13`。签发后 public ledger 只激活新 handoff，且保留旧 ID 为 withdrawn。

`create-discovery-skeleton` 在两个根产生完全相同的三个 raw/untrusted `not-run` 文档。它不是
`init-target-session` 产物，不含目标机时间、主机、许可证或 Reference 事实。

两个 operator bundle 也逐字节相同：

| 项目 | 值 |
|---|---|
| bundle ID | `bundle-ab5205f4f37e8ec467a9800a` |
| canonical provenance SHA-256 | `ab5205f4f37e8ec467a9800afb986bc2290ae7235820d38423cfde2b7c89d895` |
| authenticated content SHA-256 | `e0970c54f7f4ea2004afcbd0b7867b13467a590d658b4c527b6cc0a033edf91c` |
| collector pyz SHA-256 | `e11da8de8147fbbaab5217f56dde7eea7636cacf8993230c85484b1ef6358301` |
| `SHA256SUMS` SHA-256 | `5c78ea12626544e8e329be865b22d5de967aa33e8737ab17944f59a1734d8c33` |

公开 Git 仅包含 immutable bundle、canonical `CURRENT.json` 和 active ledger。它不包含临时 raw skeleton、空 target
session、合成 host/DSLS/Reference fixture 或任何现场数据。bundle 内的 `target-collector-tests.json` 仅记录
offline test scope 与 `target_execution=not-run`。

## 交付结论

bundle 内 collector 的 `--help` smoke 成功，且其 pyz 摘要与 provenance 相同。目标机执行仍必须由 B28 操作员在
原生 Windows `cmd.exe` 按 bundle 内 `QUICKSTART_B28.md` 人工完成；不可使用 WSL。当前仍为
`compile_status=not-run`、30 case=`not-run`、CATVBA=`not-produced`、`release_eligible=false`，G2–G7=`BLOCKED`。
