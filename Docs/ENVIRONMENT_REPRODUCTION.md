# 开发环境复刻与仓库同步指南

状态：CURRENT

适用范围：A 环境开发/验证与原生 Windows 开发机；B28 现场执行另见 bundle 内 quick-start。

## 1. 前提

- 完整 Git 客户端；禁止 shallow clone 与 GitHub Download ZIP；
- CPython 3.12.x；项目拒绝 3.11 与 3.13+；
- 精确 `uv 0.9.25`；
- 首次依赖安装可访问 PyPI、批准镜像或已预热的 uv cache；仓库当前不含离线 wheelhouse；
- 对 `doylenehemiah6893-afk/Macro_menu` 的读取权限；推送另需外部 GitHub 凭据。

本指南不会要求复制 `.venv`。虚拟环境包含平台、解释器路径和本机软链接，必须在每个 clone 中从 lock 重建。

## 2. Linux / A 环境

```bash
git clone --branch codex/dev-review-report --single-branch https://github.com/doylenehemiah6893-afk/Macro_menu.git
cd Macro_menu
export UV_CACHE_DIR="${TMPDIR:-/tmp}/macro-menu-uv-cache"
python3.12 scripts/bootstrap_resume.py --repo-root . --state resume/state.json
uv run macro-menu-build doctor --state resume/state.json --scope development --format json
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root catvba_refactor/build/resume-verification
```

若 `$HOME/.cache` 不可写，必须保留上述 `UV_CACHE_DIR`。输出放在已忽略的 `catvba_refactor/build/`，不要写到未忽略的任意目录。

## 3. 原生 Windows 开发机

在 `cmd.exe` 中执行；这里是开发验证，不是 CATIA 自动化：

```bat
git clone --branch codex/dev-review-report --single-branch https://github.com/doylenehemiah6893-afk/Macro_menu.git
cd Macro_menu
set "UV_CACHE_DIR=%TEMP%\macro-menu-uv-cache"
py -3.12 --version
uv --version
scripts\bootstrap-resume.cmd
uv run macro-menu-build doctor --state resume\state.json --scope development --format json
py -3.12 scripts\verify_resume.py --repo-root . --state resume\state.json --output-root catvba_refactor\build\resume-verification
```

`uv --version` 必须精确输出 `uv 0.9.25`。`.gitattributes` 已使常见 `core.autocrlf=true` clone 仍保持受哈希文件的稳定 bytes；不要手工批量转换行尾。bootstrap 使用 NUL 分隔的 Git 原始路径核对 evidence 后的 delivery 边界，因此 `core.quotepath=true` 与中文文档名不会被误判；这不放宽允许路径集合。
普通 clone 的 bootstrap 从完整父 PATH 固定 uv 绝对路径；GitHub Actions 则使用固定 setup-uv action 官方
`uv-path` output 显式设置 `MACRO_MENU_UV_EXECUTABLE`。两条路径都再次验证绝对文件与精确版本，并用保留
`PATHEXT/TEMP/TMP/UV_CACHE_DIR` 的受控环境执行。显式变量存在但为空、相对或非文件时不会回退 PATH。

## 4. Delivery control 单独验证

开发环境通过不表示当前 bundle 仍获准在 B28 使用。准备目标机转运前另行运行：

```bash
uv run macro-menu-build doctor --state resume/state.json --scope delivery --format json
```

Windows 将斜杠改为反斜杠即可。若返回 ledger stale、handoff expired/withdrawn/inactive 或摘要错误，开发工作可继续，但目标机必须停止并重新签发控制文件；不得手改 JSON 延期。
preparation 或 `active_bundle_path=null` 时，Delivery doctor 必须返回 `RESUME_DELIVERY_NOT_ISSUED`；这表示没有可转运制品，不是开发环境失败。

## 5. 原生 B28 目标机

B28 已安装 Python 3.12，不安装或使用 uv。只取得签发 bundle、`CURRENT.json` 与 fresh ledger，在原生 Windows `cmd.exe` 中执行 bundle 内 `run-discovery.cmd` 和 `QUICKSTART_B28.md`。禁止 WSL、PowerShell 和任何脚本自动控制 CATIA/VBE/DSLS；Discovery 也禁止 Compile、运行 target cases 或生成 CATVBA。

## 6. 本地配置

`user_data.json` 只属于本机 legacy 配置：

```bash
cp user_data.example.json user_data.json
```

Windows 可用 `copy user_data.example.json user_data.json`。填写本机值后文件仍应保持 ignored。不要提交 token、用户名、机器名、DSLS endpoint 或绝对客户路径。

## 7. 与远端同步

推送前：

```bash
git status --short --branch
git fetch origin codex/dev-review-report
git rev-list --left-right --count origin/codex/dev-review-report...HEAD
git diff --check
```

确认只有本分支的预期提交且远端没有未知前进后，使用外部 credential manager、SSH agent 或已认证 GitHub CLI 执行 fast-forward push：

```bash
git push origin codex/dev-review-report
```

凭据不得进入 remote URL、脚本、环境清单或提交。禁止推送 `main/dev`、force-push、tag 或 Release。连接器 contents/commit API 不能替代 Git push，因为重新创建提交会改变 SHA 并破坏 evidence 绑定。

推送后从第二临时目录重新 clone GitHub URL，重复第 2 或第 3 节，并确认：

```bash
git rev-parse HEAD
git status --porcelain=v1
git rev-parse refs/heads/dev
```

HEAD 必须等于已推送本地提交，工作树为空，本地 `dev` 必须等于批准 cutoff `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`。

GitHub Actions 中的 selector 显式使用 `--inactive-as-unavailable`：控制文件仅因 stale、expired、withdrawn 或 inactive
而不再可交付时，Development CI 继续成功并令 `available=false`，不上传 operator bundle。该模式不用于 B28 转运；
future timestamp、结构/摘要/内容错误仍使 CI 失败。B28 前必须使用严格 Delivery doctor 和默认 selector。

## 8. 故障判断

| 现象 | 含义 | 动作 |
|---|---|---|
| `.venv` 解释器断链 | 本机/容器生成物损坏 | 删除后由 bootstrap 重建；不提交 |
| uv cache 只读 | HOME/缓存权限问题 | 指定可写 `UV_CACHE_DIR` |
| Development doctor 失败 | Git/lock/toolchain/immutable bytes 不可复刻 | 停止构建并修复根因 |
| Delivery doctor 失败 | 当前操作授权不可用 | 停止 B28，重新获取或签发控制文件 |
| CI Development 全部通过但 bundle `available=false` | 已发布代码可复刻，但当前交付控制因时效/撤回不可用 | 不重跑开发测试冒充授权；从新 evidence 正式重签发 |
| Windows 报 pinned uv，但 `uv --version` 正确 | 显式 action output 为空/无效、受控 runtime 不完整，或使用旧提交 | 停止；核对 setup-uv `uv-path`、`where uv` 与精确版本，不能改用裸 PATH 绕过 |
| GitHub clone 缺当前 bundle | 本地提交尚未推送 | 取得认证并 fast-forward 推送本分支 |
| `delivery commits changed implementation inputs` | evidence 后确有越界路径，或使用了未修复的旧 bootstrap | 查看 NUL 安全的 commit diff；不得靠关闭 `core.quotepath` 绕过，升级到含回归修复的提交 |
| 断网且 cache 为空 | 仓库没有依赖 wheelhouse | 使用批准镜像或另行构建受控 wheelhouse |
