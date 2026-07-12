# EKL 计算体积（历史片段）

> **Status: QUARANTINE / do-not-execute**
>
> 该片段的 Action 上下文、原始编码、目标 CATIA 版本、知识包/许可证和对象类型均未验证。不得将它复制到真实模型或视为 B28 可用实现。
>
> **许可证/隔离：** Action 路径不能预设属于 Core，暂按 `Optional-KWA candidate` 隔离；最终分类由三个基线 profile 与客户 R2018 DSLS 证据决定。无已验证能力时不自动执行 EKL；仅可引导用户使用其当前 profile 已实际提供的只读属性/惯量界面，若界面不可用则禁用并明确报告。

## 最小勘误

- `PartBody` 是未声明且依赖文档的对象引用；Action 应在输入区明确声明对象，例如 `B: BodyFeature`，并在脚本中使用 `B`。
- EKL `Message` 的参数替换使用 `#` 占位符；对应形式是 `Message("体积是 #", V)`。
- 可公开访问的 3DEXPERIENCE 帮助文档镜像示例，是对 Action 输入 `B: BodyFeature` 查询 `Pad`，再计算 `smartVolume`。该镜像不是本项目的一手 R28 权威；下方历史片段的 `Query("Solid", "")`、`Compute` 类型和返回结果仍须在 R28/B28 KWA 中确认。
- 参考镜像：[Engineering Rules Capture - Creating an Action](https://help-3dexperience.aesvietnam.com/English/KwaUserMap/kwa-t-ActionFreatureUse.htm)

## 历史正文（保留，禁止执行）

let V(Volume)

V = 0m3
PartBody.Query("Solid","").Compute("+","Solid","smartVolume(x)",V)

Message("体积是",V)
