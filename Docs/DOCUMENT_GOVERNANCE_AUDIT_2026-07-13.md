# 项目文档与结构治理审计记录（2026-07-13）

> **Status:** HISTORICAL AUDIT RECORD
>
> **Evidence baseline:** `codex/dev-review-report@7425d31e57ecd798812607b43fcf42a1d17e7a94`
>
> **Result snapshot:** 由包含本文及本轮历史文档修改的 Git 提交确定
>
> **Execution boundary:** 本轮只修改文档；未移动项目目录、未修改 VBA 业务源码、未生成 CATVBA、未访问 CATIA、未推送远端

> [!NOTE]
> **Subsequent design update:** 后续 DR-011 将本记录中的根级 Overlay 规划细化为
> `catvba_refactor/` 唯一命名空间，并把 `Src/` 定义为 intake-only upstream mirror。本文其余内容保留为
> `24f81a7` 前后文档治理的历史快照；当前结构以 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) 为准。

## 1. 审计结论

项目文档原先同时存在“旧二进制可直接安装”“缺依赖就补 .NET/Excel”“危险 Git 发版命令”、
“新设计仍待批准”和“当前 CATVBA 已不可用/NO-GO”等互相冲突的入口。历史分析、临时聊天抓取、
参考代码和当前恢复规范也没有稳定的状态边界。

本轮完成以下治理收口：

- 建立 `README.md` → `Docs/README.md` → `Docs/STATUS.md` 的唯一入口链；
- 建立事实证据 → 已批准 DR → 已批准 spec → runbook → 历史/参考材料的权威链；
- 把当前状态统一为 `NO-GO / release_eligible=false`；
- 把 Core 固定为 AB3-only、MD2-only、HD2-only 三套隔离 profile 分别通过的严格能力交集；
- 把本地 Overlay 的高层边界记录为已批准，同时把 schema、intake 步骤、发布器和实施顺序保留为 DRAFT；
- 把旧 CATVBA、危险脚本、旧计划、来源不明参考代码和未来发布流程分开；
- 统一项目 Markdown 为严格 UTF-8，并修复全部指向仓库外 `D:\catia\Macro_menu` 的 `file:` 绝对文档链接；
- 以本地提交 `7425d31` 保存第一阶段主干文档检查点，没有修改或推送远端。

该结论不证明 CATVBA 已修复、已编译或可运行。工作区没有 CATIA，G0/G1 尚未执行，G2-G7 仍阻塞。

## 2. 范围与方法

### 2.1 范围

基线中共有 23 份 tracked Markdown：

- 20 份项目文档；
- 3 份 `.context/`、`.antigravity/` 下的本地代理配置文档，不属于产品权威链。

本文加入后共有 24 份 tracked Markdown，其中 21 份属于项目文档。另审查了：

- `.github/workflows/auto-release.yml`；
- `.gitignore`、`.gitattributes`；
- 根目录、`Src/`、`resources/`、`artifacts/`、`DrawFunc/`、`ref_project/` 和计划中的 Overlay 目录；
- 本地 Git 分支与缓存的 `origin/dev` / `origin/main` 拓扑结论；
- 两个根目录 CATVBA 的固定哈希和文档定位。

### 2.2 方法

1. 主线程读取所有项目文档、结构和 Git 状态；
2. 三个只读子审查分别检查入口/权威性、历史/参考材料、发布/workflow；
3. 主线程合并冲突结论并写主干文档；
4. 独立复核主干文档，先修复 2 个阻断和 4 个重要问题再提交；
5. 三个隔离写入任务分别整理旧分析/BOM、EKL/DrawFunc、`ref_project`；
6. 主线程统一复核编码、链接、状态、差异范围和哈希。

没有执行 CATIA、VBE、目标许可证、宏代码、历史危险 Git 流程或现有 release workflow。

## 3. 文档权威与状态模型

冲突解决顺序：

1. 目标机原始证据、Git/tree SHA、输入与制品 SHA-256；
2. [决策台账](CATVBA重构调查与决策记录.md) 中明确为已批准的 DR；
3. 状态为 `APPROVED` 的日期化规格；
4. 已核验的恢复指南、runbook 和操作记录；
5. 历史、替代、参考和隔离材料。

状态词统一为 `CURRENT / APPROVED / DRAFT / HISTORICAL / SUPERSEDED / REFERENCE / QUARANTINE`。
`STATUS.md` 只能汇总当前状态，不能创造批准；日期化 spec 写入仓库也不等于批准。

严重度、工作阶段和证据门必须分别写 `severity:P0`、`phase:P0`、`gate:G0`，不再使用无前缀的 `P0`。

## 4. 逐文档处置

| 文档 | 本轮后状态 | 处置摘要 |
|---|---|---|
| `README.md` | `CURRENT` 入口 | 删除直接安装/补依赖建议，显示 NO-GO、目标、许可证和入口链 |
| `Docs/README.md` | `CURRENT` 索引 | 建立权威链、状态词、维护规则和全量分类 |
| `Docs/STATUS.md` | `CURRENT` | 保存停止条件、事实快照、G0-G7 保守状态和唯一下一动作 |
| `Docs/PROJECT_STRUCTURE.md` | 高层 `APPROVED` / 细节 `DRAFT` | 规划零搬迁 Overlay、实际根目录分类、上游边界和延期的 ignore 修复 |
| `Docs/CATVBA重构调查与决策记录.md` | 已批准 DR 的规范台账 | 新增 DR-010；澄清 DR-007/008 和详细 spec 仍待复核 |
| 日期化恢复 spec | `DRAFT` | 明示写入不等于批准；修复门禁失效、pilot/release、回滚和状态页矛盾 |
| R2018 恢复指南 | `CURRENT` evidence/runbook | 分离证据日期、决策叠加和交付状态；说明 phase 与 gate 正交 |
| `Docs/发版.md` | `CURRENT` NO-GO / `DRAFT` future process | 删除旧危险发布操作；未来发布链、publisher、receipt 和回滚仍待批准 |
| `Docs/dev分支审查报告.md` | `HISTORICAL` | 保留原日期/SHA/限制，增加后续证据入口，不改写历史结论 |
| `Docs/bom_reflactor.md` | `SUPERSEDED` | 标记旧 UDT/BOM 设计已失效，修正当前符号映射和链接，禁止执行 |
| `Docs/EKL.md` | `REFERENCE` | 用达索公开资料和帮助镜像核对语法；KWA 暂作 Optional 候选，要求 B28 Language Browser/DSLS 验证 |
| `Docs/EKL计算体积.md` | `QUARANTINE` | 保留历史片段，补 Action 输入/消息勘误，禁止执行并给出无 KWA 时的禁用策略 |
| `artifacts/analysis_results.md` | `SUPERSEDED` | 列出旧类名、旧入口和不存在模块，不把历史扫描模型当成当前设计 |
| `artifacts/implementation_plan.md` | `SUPERSEDED` | 记录已完成/未完成/已不存在项，禁止再次执行旧删除迁移步骤 |
| `DrawFunc/VB.md` | `SUPERSEDED` | 指向当前 Drawing 源码，列副作用、来源缺失和 do-not-execute |
| `ref_project/Frame.md` | `REFERENCE` | .NET ArrayList/Scripting Dictionary 的位数、注册、来源和许可待验证 |
| `ref_project/temp_new function/Frame.md` | `SUPERSEDED` | 标记为历史重复副本，不继续维护 |
| `ref_project/temp_new function/getsize.md` | `QUARANTINE` | 临时聊天抓取；会修改过滤器并批量保存/关闭，禁止执行 |
| `ref_project/temp_new function/getsize2_flow.md` | `QUARANTINE` | Drawing 创建/删除副作用和确定性代码缺陷，禁止执行 |
| `ref_project/temp_new function/new getsize.md` | `QUARANTINE` | Excel/KWA/模型批量写入和无回滚风险，禁止执行 |
| 本文 | `HISTORICAL AUDIT RECORD` | 保存本轮文档治理过程、证据与延期项 |

`.context/` 和 `.antigravity/` 的 3 份 tracked Markdown 是本地代理配置，`release=false`，未纳入上述项目权威文档表。

## 5. 已修正的主要矛盾

### 5.1 当前可用性

- 撤销旧 README 的“下载正式 CATVBA并直接添加宏库即可安装完成”；
- 撤销“运行错误通常靠安装 .NET/Excel/VBA 引用解决”；
- 两个 CATVBA 统一为 `legacy evidence`，不是 seed、回滚或发布制品；
- 普通/生产/未授权运行被禁止，但保留另行批准的隔离取证会话例外。

### 5.2 草案与批准

- 详细恢复 spec 保持 `DRAFT`；
- `Docs/发版.md` 只有 NO-GO policy 当前有效，未来流程是 DRAFT；
- `PROJECT_STRUCTURE.md` 只有高层 Overlay 边界获批，`legacy.yml`、intake 格式、ignore、实施顺序仍待批准；
- 五个首批 Core 工具仍是候选，不因出现在 spec 中自动获批。

### 5.3 门禁

- 输入、源码、manifest、schema、generator 或冻结策略变化使 G0-G7 失效；
- SP/HF、引用或构建环境变化使 G2-G7 失效；
- 候选二进制变化使 G3-G7 失效；
- DSLS/profile 变化使 G4-G7 失效；
- `pilot-ready` 要求有效 G0-G6 全部通过，G7 后才是 `release-approved`。

### 5.4 上游

- `origin/dev` 是唯一分支级代码上游；
- `origin/main` 仅作旧发布/workflow/安全观察，不整体合并，也不成为第二集成基线；
- main-only 修复只能逐项比较后形成有来源记录的本地 patch；
- `main/dev` 无共同祖先的历史证据保持不变。

## 6. 编码、链接与重复材料

### 6.1 编码

初始审查发现 5 份项目 Markdown 为 CP936：

- `Docs/发版.md`；
- `Docs/EKL计算体积.md`；
- `DrawFunc/VB.md`；
- `ref_project/temp_new function/getsize.md`；
- `ref_project/temp_new function/new getsize.md`。

它们均先做机械转码，再用补丁修改。完成本文后，24 份 tracked Markdown 应全部通过严格 UTF-8 解码。
遗留 VBA/FRM/FRX 没有批量转码。

`.github/workflows/auto-release.yml` 和根 `.gitignore` 仍不是严格 UTF-8，留待独立安全/元数据批次；
不能因为 Markdown 已统一就声称整个仓库编码已统一。

### 6.2 链接

在 `7425d31` 基线精确检出 15 个指向 `D:\catia\Macro_menu` 的 `file:` 绝对 URI 匹配：

- `Docs/bom_reflactor.md`：13；
- `artifacts/implementation_plan.md`：2。

现存文件改为相对链接；不存在的历史符号保留为代码文本，并明确 `historical, absent`。
本轮后项目文档中的三斜杠 `file:` 绝对 URI 匹配为 0。

### 6.3 重复与来源

- 两份 `Frame.md` 的历史正文相同；加入不同状态头后完整文件哈希有意不同；
- `DrawFunc/VB.md` 与当前 Drawing BOM 源码功能重叠，但不是源码真源；
- 仓库没有覆盖 `ref_project/`、`DrawFunc/` 的顶层 `LICENSE` / `COPYING` / `NOTICE`；
- 来源未知的代码和文字不能推定可再分发，全部 `release=false`。

## 7. 结构治理结论

已批准的是“保留上游兼容区 + 增加本地 Overlay”的高层策略：

```text
upstream-compatible: Src/ resources/ legacy root files
local overlay:        config/ schemas/ macro_build/ tests/
generated only:       build/ dist/
governance:           Docs/
excluded:             legacy CATVBA, LicenseReset, ref_project, DrawFunc, artifacts,
                      agent/editor/venv tooling, current release workflow
```

`config/`、`schemas/`、`macro_build/`、`tests/`、`build/`、`dist/` 目前仍不存在；本文不创建它们。

根 `.gitignore` 当前存在三类问题：

- `.context\`、`.antigravity\` 规则未被 `git check-ignore` 证明有效；
- 没有根级覆盖 `build/`、`dist/`；
- 文件自身不是严格 UTF-8，`rg` 会报告 dangling glob / invalid UTF-8。

`.venv` 当前依赖其目录内 `.gitignore` 自我忽略。根 `.gitattributes` 声明了未配置的自定义
`merge=theirs`，也需单独治理。上述问题已披露但未在文档批次中实施修复。

## 8. 发布与许可证边界

- 当前 `.github/workflows/auto-release.yml` 是 `ineligible / disabled-by-policy`，但文件尚未技术禁用；
- 它仍可能在 tag 场景选择遗留 CATVBA，因此在独立安全补丁完成前不得用 tag 试运行；
- Core 只能来自 AB3-only、MD2-only、HD2-only 的实测交集；
- 部分基线 profile 可用的能力进入 Baseline Extension；
- KWA、SPA、ST1、DL1、LO1、DMN、FTA 等暂作许可证隔离候选，最终分类由三 profile 与 DSLS 证据决定；Excel 另作 `Optional-Excel` 部署依赖候选，不能把它写成 CATIA 许可证；
- 每个非 Core 包必须有独立入口、引用、安装、证据、失败行为和无额外许可证替代方案；
- 本地文件和公开资料只能形成候选映射，不能替代客户 R2018 DSLS 权益证据。

## 9. 延期项

这些项目没有被本轮文档更新“顺手实施”：

1. 详细恢复 spec 的整体书面批准；
2. 日期化实施计划；
3. `.gitignore` UTF-8/规则修复和 `.gitattributes` driver 治理；
4. 当前 release workflow 的技术禁用与未来 publisher 设计；
5. `config/legacy.yml`、package/capability/tool/reference manifest 和 schema；
6. `macro_build/`、`tests/`、Build Kit 和确定性打包；
7. 业务源码编译修复、Core 运行时和首批工具；
8. 顶层许可证/NOTICE 与参考材料来源处置；
9. B28 环境、三 profile、DSLS、签名/ACL、试点和回滚证据。

## 10. 复核要求

文档批次提交前至少验证：

```text
git diff --check
all tracked Markdown -> strict UTF-8
all local Markdown links -> target exists
absolute file URI -> zero in project docs
changed paths -> docs/reference material only
legacy CATVBA SHA-256 -> unchanged
known contradiction scan -> zero unexpected matches
```

本地不能运行 VBA 或 CATIA。任何“编译通过、可用、许可证通过、可发布”必须继续保持未证明。

## 11. 下一动作

完成并提交本文及历史材料状态批次后，回到 [STATUS.md](STATUS.md) 的唯一下一动作：
书面复核详细恢复 spec。批准、修改或拒绝结果追加到决策台账后，才创建日期化实施计划并考虑
Overlay 元数据批次。
