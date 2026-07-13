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
