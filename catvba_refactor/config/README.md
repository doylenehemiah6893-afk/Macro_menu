# Build manifests

本目录保存四份版本化 JSON manifest：

- `project.json`：仓库身份、`dev` cutoff 名称、唯一工作分支和 governed paths；
- `components.json`：source roots、精确 member path/blob OID/raw SHA-256/role、组件身份和 disposition；
- `packages.json`：Core、Fleet-SPA、Fleet-FTA 的物理包分类和可收紧政策；
- `tools.json`：稳定 tool ID、caption、package、module/entrypoint、document type 和 capability。

所有文件先由 `schemas/` 的 JSON Schema 拒绝未知字段，再执行重复 ID、交叉引用、许可证声明和安全政策
校验。Core 最低禁令由代码强制，manifest 只能收紧，不能自报 CATIA/许可证 PASS。

当前 `components` 和 `tools` 列表为空：上游 `Src/` 默认 Quarantine，三个包只声明隔离边界。因此配置
有效但没有获批 candidate，不能升级 G0/G1 或生成空 Kit。正式 candidate 还要求本地只读 `dev` ref、
clean governed tree，以及 fork/upstream cutoff 相等；工具不会创建或更新该 ref。
