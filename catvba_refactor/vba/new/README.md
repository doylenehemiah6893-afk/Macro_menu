# New VBA components

存放没有上游对应组件的本地新增完整 `.bas/.cls/.frm+.frx` 组件。

- 每个组件使用稳定 `source_id` 子目录；
- 包归属由 manifest 定义，不编码在路径中；
- `VB_Name`、输出文件名和目标包内身份必须唯一；
- 当前包含 12 个已批准、由 manifest 精确绑定 Git object/hash 的首轮 Core 固定组件；generator 组件不存放在此目录。
- 这些源码只具备 A 环境静态/打包证据，尚无 B28 Compile 或运行通过结论。
