# 本地环境、代码与仓库同步审查

日期：2026-07-16

范围：`codex/dev-review-report` 本地工作树、GitHub 远端、Python/uv、CI、恢复脚本、文档和已签发 discovery bundle。

## 结论

现有离线工具与 bundle 架构可保留，但审查时还不能从 GitHub 复刻当前本地环境：远端分支停在 `037ab40696744678a57781d5197c152687520d84`，本地交付 HEAD 为 `2e3be7442734c57af6cde39f5f6f51025095de4f`，本地领先 22 个提交，且当前执行环境没有 HTTPS/SSH/gh 推送凭据。

另有两个已复现的代码级 P0：Windows `core.autocrlf=true` 会在 clean clone 中改写 lock、intake 和 bundle 控制 bytes；Development doctor 又被 24 小时 ledger 与七天 handoff 时效阻断。两者都会使外部 fresh clone 随平台或时间失败。本轮已由 `f2c9d8d` 的新 evidence cycle 和实际 autocrlf clone 关闭。

首轮最终 delivery commit 的 fresh clone 又发现第三个 P0：Git 对 `Docs/发版.md` 的 quoted-path 展示使 bootstrap 误判合法交付路径。该问题不会影响 evidence commit clone，却会阻断包含中文文档更新的最终交付 clone；当前已撤回对应 handoff，并以 NUL 分隔路径解析和真实 commit 回归进入第二修正周期。

## 审查事实

- A 环境：CPython 3.12.13、uv 0.9.25、Git 2.51.1；根 `.venv` 是托管容器产生的 rsyncd-munged 断链，属于 ignored 本机生成物。
- 锁：审查前 `uv.lock` SHA-256 为 `d52656bec3aa50218f22df7a02f16dd0b9e7868ad0c51b8d22959109e694e177`；当前修订后为 `d85f1942b70a3605642bdbf1c8bea5bbc5ff78b9eb85e7f07b64f280affd75fc`；冻结依赖可在独立 venv 安装。
- `core.autocrlf=true` 实际 clone 中，Git 状态仍 clean，但 lock、intake、provenance、CURRENT/ledger bytes 被改写，bootstrap 和 doctor 均失败。
- 模拟 2026-07-17 以后，旧 doctor 因 ledger stale 失败；2026-07-24 以后再因 handoff expiry 失败，即使源码与依赖未变。
- Windows CI 曾用 `python -m ...cli` 调用一个没有模块入口的文件，实际没有执行 doctor。
- tracked 的 Antigravity/Gemini/Cursor 配置引用不存在的 mission、tools 和 skills；`.vscode` 又把全仓默认编码强制为 GBK。
- 多个 README/计划仍保留旧 Kit、旧 handoff、零 candidate、无 baseline record 或“等待实施”等陈旧描述。

## 本轮处置

- 删除无效代理/IDE配置；`user_data.json` 改为 ignored 本机文件并提供无绝对路径的 example。
- 用 `.gitattributes` 固定跨平台行尾并把签发 bundle 作为 byte-preserved 内容；增加环境合同测试。
- 将 Python 范围固定为 `>=3.12,<3.13`，bootstrap 在改写 `.venv` 前先拒绝非 0.9.25 的 uv。
- 拆分 `doctor --scope development|delivery`；bootstrap、verify 和 CI 使用 development，默认 delivery 保持 fail-closed。
- Windows CI 改为实际 console entrypoint；root build 输出进入 ignore。
- 建立当前规格、唯一活动计划和环境复刻指南，并同步入口/状态/子目录 README。

## 当前状态与仍未关闭

本轮代码与文档回归达到 `1664 passed, 19 warnings`；warnings 仅来自 oletools/pyparsing 的第三方 deprecation。机器状态曾安全回到 preparation 并撤回旧 handoff，随后从 `f2c9d8d` 重新双构建并签发 `bundle-6b7518a2e3c969d2383fcb60`。最终 clone QA 暴露 quoted-path 缺陷后，该 handoff 已撤回，bundle 仅保留审计；第二修正周期尚未重新签发。

1. 本地所有提交仍需 GitHub 认证后 fast-forward 推送；在此之前，远端 fresh clone 仍无法取得当前工作。
2. 推送后必须取得真实 Linux/Windows Actions 结果，并从 GitHub 第二次 clone 验证。
3. 仓库没有离线 wheelhouse；依赖复刻仍需网络、批准镜像或预热 cache。
4. B28 人工 Discovery 尚未执行，G2–G7 与 release 状态完全不变。
