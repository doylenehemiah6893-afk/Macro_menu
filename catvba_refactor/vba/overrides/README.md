# VBA component overrides

存放对上游完整组件的本地替代。

每个 override 必须显式绑定 upstream repository/ref/commit/path/blob/raw SHA-256、组件类型和 `VB_Name`。
FRM/FRX 必须成对替代，base 漂移时 fail-closed。禁止同名路径自动阴影、fuzzy patch 和只更新哈希消红。

当前包含一个已批准的 `Cat_Macro_Menu_View.frm/.frx` 原子 override，精确绑定批准 cutoff 的上游 Form base。
浮动 `origin/dev` 已改变该 Form；本分支不得只更新 blob/hash 消红或自动三方合并，后续 intake 必须人工选择退役、重做并重绑或 quarantine。
