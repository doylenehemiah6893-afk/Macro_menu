# JSON schemas

本目录实现离线 Build Kit 四份输入 manifest 的 JSON Schema：

```text
project.schema.json
components.schema.json
packages.schema.json
tools.schema.json
```

schema 固定 `schema_version=1`、必填字段、枚举/格式/长度和 `additionalProperties=false`。根项目锁定的
`jsonschema` 负责结构验证；Python 语义层继续检查重复 ID、portable path、member binding、package/tool
交叉引用和禁止自报 PASS。

schema 文件存在或配置通过只证明输入格式可判定，不表示 G0/G1、CATIA Compile、许可证或发布通过。

`target_evidence/` 是与 Build Kit 输入 manifest 物理隔离的 Draft 2020-12 schema family：

```text
common.schema.json             session.schema.json
environment.schema.json        entitlements.schema.json
references.schema.json         compile-result.schema.json
test-results.schema.json       state-diff.schema.json
artifact-manifest.schema.json  operator-index.schema.json
handoff.schema.json            payload-manifest.schema.json
gate-receipt.schema.json       approval.schema.json
session-complete.schema.json
```

这些 schema 固定 evidence binding、session mode/profile、UTC、ID 和小写 SHA-256 语法，并通过
`if/then` 区分 discovery、G2 和 G3-C。它们只允许 `release_eligible=false`；discovery 只允许 observation
approval，不能自报 Gate PASS。`common.schema.json` 是公共 `$defs` 和 binding 的唯一来源；loader 会先对
全部十五份 schema 执行 Draft 2020-12 meta-validation，要求每个文件使用唯一、与文件名严格对应的 canonical
`$id`，并在返回 validator 前解析全部 `$ref`；之后产生稳定 JSON Pointer 诊断。

`payload-manifest.json` 的认证格式严格为 `schema_version` 与按路径排序的 `members`；payload digest 是这份
canonical JSON bytes 的 SHA-256，不写回 manifest 本身。handoff 另外绑定 revocation snapshot 和两目录、
两 ZIP 的四份 verifier report digest，不能用可编辑的 `passed` 字符串替代认证报告身份。

证据 schema 只保证单份文档的严格形状。跨文件 identity、时间单调性、payload 文件闭合、30-case 与特定
Kit plan 的逐项相等、Gate 重算和 sealed directory/ZIP 验证由后续语义层执行，schema 通过本身不构成目标机
事实证明或 Gate 批准。

`approval.schema.json` 为独立历史记录保留 `pending` 语法兼容；normalizer、packer 和 sealed validator 只接受
最终 `approved|rejected`。`approved` 的 `fail|blocked` 表示批准保存该计算结论，不表示 Gate PASS。
