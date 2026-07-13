# VBA component overrides

存放对上游完整组件的本地替代。

每个 override 必须显式绑定 upstream repository/ref/commit/path/blob/raw SHA-256、组件类型和 `VB_Name`。
FRM/FRX 必须成对替代，base 漂移时 fail-closed。禁止同名路径自动阴影、fuzzy patch 和只更新哈希消红。

当前目录仅为脚手架，尚无已批准 override。

