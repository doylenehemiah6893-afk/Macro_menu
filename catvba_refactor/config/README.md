# Build manifests

本目录保存四份版本化 JSON manifest：

- `project.json`：仓库身份、`dev` cutoff 名称、唯一工作分支和 governed paths；
- `components.json`：source roots、精确 member path/blob OID/raw SHA-256/role、组件身份和 disposition；
- `packages.json`：Core、Fleet-SPA、Fleet-FTA 的物理包分类和可收紧政策；
- `tools.json`：稳定 tool ID、caption、package、module/entrypoint、document type 和 capability。

所有文件先由 `schemas/` 的 JSON Schema 拒绝未知字段，再执行重复 ID、交叉引用、许可证声明和安全政策
校验。Core 最低禁令由代码强制，manifest 只能收紧，不能自报 CATIA/许可证 PASS。

当前 `components` 精确批准 13 个固定 Core candidate，generator 再加入 3 个确定生成 component；`tools`
批准 `core.healthcheck` 和 `core.document-summary`。其余上游 `Src/` 保持 Quarantine，Fleet 包继续物理隔离且
import-order 为空。正式 candidate 仍要求本地只读 `dev` ref、clean governed tree 和批准 cutoff；工具不会跟随浮动 remote。

首次 baseline record 已接受 upstream/fork `dev` 的共同 cutoff
`abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`，本地 `refs/heads/dev` 已由独立 intake 流程原子建立。
当前 committed candidate 模式的 `inventory/check` 与确定性 `build-kit` 已通过 A 环境验证，G0/G1 仅在绑定的
离线 evidence 上为 `PASS`。这不证明 CATIA Compile、References、权益或运行；G2–G7 仍 `BLOCKED`。
