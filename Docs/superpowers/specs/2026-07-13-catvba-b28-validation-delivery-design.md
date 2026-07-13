# CATVBA B28 验证、许可证与交付设计

> 状态：DRAFT — 待用户书面复审
>
> 上位规格：[CATVBA R2018 恢复总架构设计](2026-07-13-catvba-r2018-recovery-design.md)

## 1. 目标

定义只有 CATIA V5-6R2018/VBA7 64 目标环境才能执行的空工程构建、References、许可证矩阵、证据回传、
安装、试点与回滚要求。A 环境输出的 Build Kit 到达本规格前始终 `release_eligible=false`。

## 2. 许可证事实与状态

目标机保证：

```text
(AB3 OR HD2 OR MD2) AND SPA AND FTA
```

必须分别记录：

1. configuration/product entitlement；
2. 类型库/Reference 是否存在且 Compile；
3. API/工作台是否可取得；
4. 当前会话是否实际 checkout；
5. 对应功能是否完成运行、失败恢复和重启复测。

不得通过 `SetLicense(..., False)`、脚本勾选或修改 Licensing Repository 探测能力。

## 3. Profile 矩阵

| ID | 最小权益 | 必测 |
|---|---|---|
| P-AB3 | AB3 + SPA + FTA | Core、Fleet-SPA、Fleet-FTA |
| P-HD2 | HD2 + SPA + FTA | Core、Fleet-SPA、Fleet-FTA |
| P-MD2 | MD2 + SPA + FTA | Core、Fleet-SPA、Fleet-FTA |
| P-ALL | AB3 + HD2 + MD2 + SPA + FTA | 补充兼容，不替代三个最小 profile |
| P-PROD | 现场实际组合 + SPA + FTA | 安装、兼容、试点、回滚 |

每套最小 profile 必须真正隔离；三种 configuration 同时存在的会话不能替代三个最小 profile。

## 4. 包与许可证处置

| 包 | 部署 | 失败行为 |
|---|---|---|
| Core | 必装 | 任一最小 profile 失败的工具移出 Core |
| Fleet-SPA | 默认安装 | 类型库/API/checkout 失败只禁用 SPA 功能，Core 不受影响 |
| Fleet-FTA | 默认安装 | 类型库/API/checkout 失败只禁用 FTA 功能，Core 不受影响 |
| Baseline Extension | 仅匹配 profile | UI 明确说明所需 configuration |
| CATIA Licensed Optional | 仅有额外权益席位 | 未安装/无权益时 fail-closed |
| External Integration | 仅有外部软件环境 | 不描述为 CATIA 许可证问题 |
| DevTools | 构建/调试账号 | 永不发布给普通用户 |

候选映射：

- 测量、`SPAWorkbench`、空间分析 → Fleet-SPA；
- `AnnotationSets/CreateFlagNote` → Fleet-FTA；
- `Marker3Ds` 不因已有 SPA/FTA 自动成立，保持 Optional-DMN candidate；
- ST1、DL1、LO1、DMN、KWA 保持目标机候选；
- Excel 为 External Integration，正式降级为待实现 CSV/TSV。

公开产品代码只支持名称和能力方向，不能替代客户 R2018 configuration 组成或 API 归属证据。

Fleet-SPA 与 Fleet-FTA 必须分别形成独立 CATVBA、Reference allowlist、制品和证据。每个扩展首轮只要求
固定 `Fleet_Invoke` 与无持久修改的 `extension.healthcheck`；具体安全 probe 由 B28 类型库审查后批准。

## 5. B28 环境证明

构建前记录：

- Windows 版本和补丁；
- CATIA R28/B28 的 GA/SP/HF、安装目录和环境文件；
- DS VBA/VBE 版本与 Win64 probe；
- DSLS 客户端/服务器信息和 profile 建立方式；
- B28 References GUID、major/minor、解析路径、MISSING 状态；
- 构建账号、普通用户、Office/网络/PowerShell/WSH 状态；
- Build Kit ID、ZIP SHA-256、Git 输入和批准记录。

不得通过安装 B30、复制 B30 TLB、x86 VBIDE/VBA6、SysWOW64 控件、Temp COM 或来历不明 DLL 补引用。

## 6. 空工程构建

每个包分别：

1. 在干净 B28 新建空 CATVBA；
2. 只加入该包 Reference allowlist；
3. 按 Kit 导入顺序导入 `.bas/.cls/.frm+.frx`；
4. `Debug > Compile`；
5. 保存，关闭 CATIA 和残留宿主；
6. 重开 CATIA，再次 Compile/运行 HealthCheck；
7. 记录最终模块、FRX、References、签名相关流和 CATVBA SHA-256；
8. 把制品和证据作为只读回传物交给 A 环境审计。

禁止从旧 CATVBA Save As，禁止把现场热改 Production 当作源码真源。

## 7. 测试轴

- profile：P-AB3、P-HD2、P-MD2、P-PROD；
- 包：Core、Fleet-SPA、Fleet-FTA 及被批准的 Extension/Optional；
- 文档：无文档、CATPart、CATProduct、CATDrawing；
- 状态：未保存、已保存、只读、脏文档；
- 会话：首次加载、重启、重复执行、跨文档切换；
- 安全：无 Office、断网、PowerShell/WSH 禁用；
- 路径：ASCII、空格、中文、长路径、只读位置；
- 用户：构建账号、新普通用户。

Core 必须在 SPA/FTA 包未安装、文件损坏、类型库不可解析或 checkout 失败的专项环境中仍能启动并说明扩展不可用。

## 8. 证据包

每个 build/profile session 至少包含：

```text
environment.json
entitlements.json
references.json
compile-result.json
test-results.json
state-diff.json
artifact-manifest.json
SHA256SUMS
screenshots-or-operator-records/
returned-catvba/
```

证据绑定 kit ID、Git SHA、SP/HF、profile ID 和制品哈希。日志必须脱敏，不记录客户模型名、完整路径、
PN、对象名、参数值或设计内容，除非数据治理另行批准。

## 9. 门禁

```text
G2 B28-ENV-ATTESTED
G3 BUILT-UNVERIFIED
G4 BASE-PROFILE-MATRIX-PASS
G5 FLEET-SPA-FTA-PASS
G6 SECURITY-PILOT-READY
G7 RELEASE-APPROVED
```

- G4：Core 在三个最小 profile 完整通过；
- G5：Fleet-SPA/FTA 在三个 profile 通过且故障不影响 Core；
- G6：回传审计、安全包装、普通用户试点和回滚演练通过；
- G7：全部证据、审批、制品库和发布记录完成。

SP/HF、Reference、profile、输入源码、manifest、generator 或二进制变化时，按影响范围重跑下游门。

G4/G5 使用独立收据：

```text
G4-C  Core profile/tool matrix
G5-S  SPA Compile/restart/healthcheck matrix
G5-F  FTA Compile/restart/healthcheck matrix
G5-P  Core -> extension fixed-entry MM/1 round trip
G5-I  missing/reference/load/checkout failure isolation
```

扩展失败不能改写已成立的 G4-C 历史结论，但默认 Fleet release 的 G5/G7 必须 FAIL/BLOCKED。

故障隔离最低要求：

| 注入故障 | Core | SPA | FTA |
|---|---|---|---|
| SPA 未安装、Reference 或 checkout 失败 | PASS | UNAVAILABLE | PASS |
| FTA 未安装、Reference 或 checkout 失败 | PASS | PASS | UNAVAILABLE |
| 两扩展同时失败 | PASS | UNAVAILABLE | UNAVAILABLE |

MISSING Reference 只能在隔离验证机用不可发布 fixture 注入并恢复快照；没有安全注入方案时 G5-I 保持 BLOCKED。

## 10. 安装与回滚

以下是必须在 P-PROD 验证后批准的策略，不在 A 环境预先固定：

- Production 安装根和 CATIA 宏库注册方式；
- Debug/Production 物理隔离和到期清理；
- VBA 签名是否在 R2018 可靠，或采用企业签名安装包 + ACL + 哈希；
- 版本并存、受管切换和只读权限；
- 不可变制品库、双人审批和证据保留期。

候选 release set 为物理三文件、逻辑原子发布：Core、Fleet-SPA、Fleet-FTA 版本必须匹配，不允许混装。
具体 `%ProgramData%` 路径、宏库注册和惰性加载语义仍须 B28/P-PROD 验证；若 `ExecuteScript` 对 Function
返回 Variant 数组不可靠，G5-P 保持 BLOCKED，不得用临时文件交换绕过。

回滚只能切回仍具有有效 G7、哈希匹配且未撤回的 R28 制品；模型数据恢复依赖独立文档备份。旧仓库
CATVBA 不属于合格回滚制品。

## 11. 验收

- B28 从空白工程重建，无污染 Reference；
- 三个最小 profile 分别通过 Core；
- SPA、FTA 默认扩展分别通过且故障隔离；
- Optional/External 包缺失不会破坏 Core；
- 保存、关闭、重启后结果仍成立；
- 返回 CATVBA 与 Build Kit 源码/FRX/Reference/哈希一致；
- 普通用户试点、受管安装和回滚完成；
- 只有 G7 后才可称为 Production/release-approved。
