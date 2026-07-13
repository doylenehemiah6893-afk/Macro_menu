# JSON schemas

规划存放离线 Build Kit 输入、输出和目标证据的 JSON Schema。

当前尚未实现 schema。后续 schema 必须拒绝未知字段，版本化并由根 `pyproject.toml/uv.lock` 管理的
验证器执行；不得通过文件存在推定 G0/G1 已通过。

