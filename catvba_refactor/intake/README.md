# Intake evidence boundary

`../schemas/intake-initial-baseline.schema.json` 只定义首次、无内容变化的 `initial_baseline`
证据合同。它固定在 accepted cutoff `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`，并固定
`verysolecd/Macro_menu:dev`、`doylenehemiah6893-afk/Macro_menu:dev` 以及该 cutoff 的
`Src/`、`resources/` Git tree OID。合同拒绝未知字段，不能通过放宽常量复用于后续 intake。

该首次 baseline 的前提是 cutoff 已是 intake 前工作 commit 的祖先，并且工作 commit 的
`Src/`、`resources/` tree 与 cutoff 完全一致。因此它不制造空 merge，record 必须使用
`merge_commit=null`、`merge_reason=initial-baseline/no-content-intake`，并将 changed paths、
override decisions 和 superseded Kit IDs 记录为空。

经批准的证据 record 规划存放在 `catvba_refactor/intake/records/`；本目录当前没有 baseline
record。此证据 schema 和未来 record 都不属于四份 Build Kit input manifest，也不得为了建立
baseline 而改动这些 manifest。未来 upstream 出现内容变化时，必须采用新的 record type/schema，
并按 approved intake spec §7 生成两父 merge commit。
