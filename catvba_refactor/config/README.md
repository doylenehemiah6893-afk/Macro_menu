# Build manifests

规划存放 `project.json`、`components.json`、`packages.json`、`tools.json` 四份 JSON manifest。

当前没有获批 schema，因此本目录只建立所有权，不放置空配置或占位假数据。实现必须通过根 Python 项目
加载并使用 `schemas/` 中的严格 JSON Schema 验证。组件来源/隔离归入 components，能力与不可放宽政策
归入 packages，稳定工具目录归入 tools。
