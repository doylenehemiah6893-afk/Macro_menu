# CATVBA B28 Discovery 原生 Windows 完整操作手册

日期：2026-07-15

状态：SUPERSEDED — 不得执行本文件中的历史命令；尚无目标机结果

> 本文在 Task 10 已被发现为不完整的历史草案：若命令失败，它的部分段落只打印错误码，且过早复制后续
> Reference 输入。唯一批准的目标机执行入口是随已签发 bundle 提供的
> [`b28-target/QUICKSTART_B28.md`](b28-target/QUICKSTART_B28.md)，并必须先阅读其同目录的
> `README_TARGET_B28.md` 与 `SECURITY_AND_REDACTION.md`。本文件仅保留历史背景，任何代码块均不可执行。

范围：CATIA V5-6R2018 / R28 / B28、VBA7、Win64、原生 CPython 3.12

本手册只采集 Discovery 原始观察。它不使用 WSL，不使用 PowerShell，不调用 COM/WSH/SendKeys，不自动点击 CATIA、
VBE 或 DSLS。**禁止 Compile**，禁止运行 30 个 target cases，禁止生成、保存或回传 CATVBA 作为发布制品；固定结论
为 `compile_status=not-run`、cases 全部 `not-run`、`artifact_status=not-produced`、
`release_eligible=false`。Windows 产物始终标为 `raw/untrusted`，Gate、approval、seal 只能由 A 环境完成。

## 1. 开始前角色、机器与信任边界

需要一名标准用户操作员和两名彼此不同的脱敏复核者。使用批准的 blank VM snapshot；确认 CATIA 完全关闭、没有
旧 CATVBA、客户文档、个人宏目录或 Production 宏库挂载。目标资格只读观察为：

```text
(AB3 OR HD2 OR MD2) AND SPA AND FTA
```

禁止调用 `SetLicense`、LicenseReset、修改 DSLS/Licensing Repository、安装缺失 DLL 或勾选 References 来制造通过。
bundle、control、inputs、capture、return 必须在管理员预建、仅操作员可写的本地 NTFS 非敌对根目录；不得位于
网络共享、同步盘、Temp、客户路径，不得含 symlink、junction、reparse point 或 hard link。Windows ACL 是操作前提，
不是受攻击 root 下的原子可信保证；因此任何 Windows 输出仍为 `raw/untrusted`。

从仓库交付的 immutable bundle 必须包含 `target-discovery.pyz`、`run-discovery.cmd`、handoff、Kit、skeleton、源码、
schema、模板与 `SHA256SUMS`。另从仓库同级取得最新 `CURRENT.json` 和 `active-handoff-ledger.json`；bundle 内的发行时
snapshot 不能证明之后未撤回。ledger `captured_at` 超过 24 小时、来自未来、handoff 不 active/已撤回/过期均停止。

## 2. 顶部变量与预检

打开普通 `cmd.exe`，逐条复制；路径使用本次专用固定目录，不用尖括号占位符：

```bat
set "ROOT=C:\B28Discovery"
set "BUNDLE=%ROOT%\bundle"
set "CONTROL=%ROOT%\control"
set "INPUT=%ROOT%\inputs"
set "CAPTURE=%ROOT%\capture-session-01"
set "RAW=%ROOT%\return-session-01"
cd /d "%BUNDLE%"
set "PY312_MODE="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY312_MODE=py"
)
if not defined PY312_MODE (
  where python >nul 2>&1
  if not errorlevel 1 python -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY312_MODE=python"
)
if not defined PY312_MODE (echo ERROR: native CPython 3.12 is required. 1>&2 & exit /b 9009)
echo Verified launcher mode: %PY312_MODE%
dir /a "%BUNDLE%"
```

必须输出 `py` 或 `python` verified mode。存在可用 `py -3.12` 时不要求 PATH 中另有 `python`；只有 launcher 不存在或
其 3.12 解释器严格检查失败才尝试 fallback。两者都不是原生 Windows CPython 3.12、经兼容层运行、路径不明或
系统时间无法由操作员见证时停止。先与 `SHA256SUMS` 人工比对关键文件：

```bat
certutil -hashfile "%BUNDLE%\target-discovery.pyz" SHA256
certutil -hashfile "%BUNDLE%\handoff.json" SHA256
certutil -hashfile "%CONTROL%\CURRENT.json" SHA256
certutil -hashfile "%CONTROL%\active-handoff-ledger.json" SHA256
call run-discovery.cmd preflight --bundle "%BUNDLE%" --current "%CONTROL%\CURRENT.json" --revocation-ledger "%CONTROL%\active-handoff-ledger.json"
echo %ERRORLEVEL%
```

必须 `ok=true`、`exit_code=0`。外部状态缺失、CURRENT/bundle/handoff 不一致、hash 不一致、ledger stale/future、
handoff withdrawn/not-active/not-yet-valid/expired、时钟无时区或任何 provenance/schema/member/path 错误都立即停止。

## 3. 建立一次性 capture 与输入

确认 `%CAPTURE%` 和 `%RAW%` 均不存在，然后初始化：

```bat
call run-discovery.cmd init-capture --bundle "%BUNDLE%" --current "%CONTROL%\CURRENT.json" --revocation-ledger "%CONTROL%\active-handoff-ledger.json" --capture "%CAPTURE%"
echo %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
echo %ERRORLEVEL%
```

把 bundle `templates` 复制到新建的 `%INPUT%`，只编辑副本；任一目标已存在则回答 No 并停止：

```bat
mkdir "%INPUT%"
copy "%BUNDLE%\templates\environment-input.json" "%INPUT%\environment-input.json"
copy "%BUNDLE%\templates\entitlements-input.csv" "%INPUT%\entitlements-input.csv"
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-blank-project.csv"
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-form-import.csv"
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-all-import.csv"
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-save.csv"
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-restart.csv"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\environment-observation.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\entitlement-observation.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-blank-project.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-form-import.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-all-import.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-save.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-restart.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\session-observation.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\redaction-review-first.txt"
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\redaction-review-second.txt"
```

`environment-input.json` 中 Windows edition/build 必须来自
系统只读观察；CATIA/VBE About 必须显示 V5-6R2018/R28/B28、VBA7、Win64。污染扫描 B30、x86、VBA6、Temp、
user-profile 必须全部 absent；否则记录原因并停止。不得写机器名、用户名、完整路径、DSLS server 或客户信息。

```bat
call run-discovery.cmd record-environment --capture "%CAPTURE%" --input "%INPUT%\environment-input.json"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category environment --input "%INPUT%\environment-observation.txt"
echo %ERRORLEVEL%
```

## 4. 五项许可证逐项观察

只读打开获准的 CATIA/DSLS licensing UI。严格按 AB3、HD2、MD2、SPA、FTA 五行填写
`entitlements-input.csv`，每项分别记录 `availability` 与 `checkout`；unknown 是允许的真实观察，不能把“已安装”写成
checked-out。满足条件也只代表观察，不是 Gate PASS；不满足不得修改许可证补齐。

```bat
call run-discovery.cmd record-entitlements --capture "%CAPTURE%" --input "%INPUT%\entitlements-input.csv"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category entitlement --input "%INPUT%\entitlement-observation.txt"
echo %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
```

license set 不是恰好五项、顺序错误、availability/checkout 组合矛盾或含敏感信息时停止。

## 5. 创建全新空白工程并记录 blank-project

1. 从 blank VM 启动 CATIA，以标准用户新建一次性空白 VBA project；不从旧工程 `Save As`，不注册到 Production。
2. 在 VBE References UI 逐项只读记录 GUID、major/minor、display name、MISSING、architecture、source class。
3. 路径只写 `CATIA_INSTALL`、`WINDOWS_INSTALL` 或 `SYSTEM` root kind、ASCII 相对路径、basename 和文件 SHA-256；
   禁止完整绝对路径、用户目录和未知 DLL。发现 MISSING、B30、x86、VBA6、Temp、user-profile 立即停止。
4. 为本点填写独立 `references-blank-project.csv`，不得从后续点回填。

```bat
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point blank-project --input "%INPUT%\references-blank-project.csv"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-blank-project.txt"
echo %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
```

## 6. 严格导入与五个 Reference 点

仅按 Kit 的 `import-order/core.txt` 顺序通过 VBE 人工导入。不得重新排序、跳项、混入 Fleet/optional 组件。遇到
`.frm` 时把该 FRM 与同目录、同 basename 的 `.frx` 视为一个原子对：只在 VBE 选择 FRM，确认 FRX sidecar 同时
被读取；不得单独打开、编辑、转换、复制或导入 FRX。配对缺失、hash 不符或 VBE 报错则停止并恢复干净 VM。

完成所有 form pair 后，只读观察并填写第二份 CSV：

```bat
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-form-import --input "%INPUT%\references-post-form-import.csv"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-form-import.txt"
```

继续导入其余 Core 源码后记录第三点；仍然禁止 Compile：

```bat
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-all-import --input "%INPUT%\references-post-all-import.csv"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-all-import.txt"
```

保存一次性工程后记录第四点。保存仅用于观察 Reference transition，不代表产出 CATVBA：

```bat
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-save --input "%INPUT%\references-post-save.csv"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-save.txt"
```

完全退出 CATIA/VBE，确认无残留宿主进程；重新启动并只打开该一次性工程，记录第五点：

```bat
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-restart --input "%INPUT%\references-post-restart.csv"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-restart.txt"
echo %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
```

五点必须严格为 `blank-project`、`post-form-import`、`post-all-import`、`post-save`、`post-restart`。点序错误、重复、
已关闭点被替换、stable ID 重复、集合为空或 Reference transition 异常时 session 作废；禁止手改 capture 或跳点。

## 7. Operator record 与双人脱敏复核

文本只写匿名观察事实、观察 UI 类型和 `not-run` 状态；禁止机器/人员/客户身份、DSLS endpoint/IP、完整路径、最近
文件、PN、文档/模型/参数名、token 或密码。每个文件先由操作员自检，再由两名不同人员双人复核。

截图不是必需证据。确需截图时，先在批准工具中裁剪、遮挡并再次检查元数据；先把两份不同的 review 文本以
`--category review` 加入 capture，取得两个不同 record ID。再计算图片 SHA-256，并在图片旁创建同 basename 的
`.redaction-review.json`，其 decision 为 `approved-redacted`、image hash 精确匹配、两个 review ID 不同；之后才可
`add-operator-record`。原始未脱敏图片永不进入 capture/return/Git。任何复核者不确定时停止。

```bat
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category review --input "%INPUT%\redaction-review-first.txt" > "%INPUT%\redaction-review-first-receipt.json"
echo %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category review --input "%INPUT%\redaction-review-second.txt" > "%INPUT%\redaction-review-second-receipt.json"
echo %ERRORLEVEL%
if /i "%PY312_MODE%"=="py" py -3.12 -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); assert d['ok'] is True; print(d['facts']['record_id'])" "%INPUT%\redaction-review-first-receipt.json"
if /i "%PY312_MODE%"=="python" python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); assert d['ok'] is True; print(d['facts']['record_id'])" "%INPUT%\redaction-review-first-receipt.json"
if errorlevel 1 exit /b %ERRORLEVEL%
if /i "%PY312_MODE%"=="py" py -3.12 -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); assert d['ok'] is True; print(d['facts']['record_id'])" "%INPUT%\redaction-review-second-receipt.json"
if /i "%PY312_MODE%"=="python" python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); assert d['ok'] is True; print(d['facts']['record_id'])" "%INPUT%\redaction-review-second-receipt.json"
if errorlevel 1 exit /b %ERRORLEVEL%
certutil -hashfile "%INPUT%\screen-redacted.png" SHA256 > "%INPUT%\screen-redacted.certutil-sha256.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
if /i "%PY312_MODE%"=="py" py -3.12 -c "import pathlib,re,sys; xs=[re.sub(rb'\s',b'',x).lower() for x in pathlib.Path(sys.argv[1]).read_bytes().splitlines()]; xs=[x for x in xs if re.fullmatch(rb'[0-9a-f]{64}',x)]; assert len(xs)==1; print(xs[0].decode('ascii'))" "%INPUT%\screen-redacted.certutil-sha256.txt"
if /i "%PY312_MODE%"=="python" python -c "import pathlib,re,sys; xs=[re.sub(rb'\s',b'',x).lower() for x in pathlib.Path(sys.argv[1]).read_bytes().splitlines()]; xs=[x for x in xs if re.fullmatch(rb'[0-9a-f]{64}',x)]; assert len(xs)==1; print(xs[0].decode('ascii'))" "%INPUT%\screen-redacted.certutil-sha256.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\redaction-review.md" "%INPUT%\redaction-review-instructions.md"
if /i "%PY312_MODE%"=="py" py -3.12 -c "import hashlib,json,pathlib,re,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); b=json.load(open(sys.argv[2],encoding='utf-8')); lines=[re.sub(rb'\s',b'',x).lower() for x in pathlib.Path(sys.argv[4]).read_bytes().splitlines()]; hs=[x.decode('ascii') for x in lines if re.fullmatch(rb'[0-9a-f]{64}',x)]; image=pathlib.Path(sys.argv[3]).read_bytes(); digest=hashlib.sha256(image).hexdigest(); assert len(hs)==1 and hs[0]==digest; ids=[a['facts']['record_id'],b['facts']['record_id']]; assert a['ok'] is True and b['ok'] is True and ids[0]!=ids[1]; doc={'decision':'approved-redacted','image_sha256':digest,'review_record_ids':ids,'schema_version':1}; pathlib.Path(sys.argv[5]).write_text(json.dumps(doc,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')" "%INPUT%\redaction-review-first-receipt.json" "%INPUT%\redaction-review-second-receipt.json" "%INPUT%\screen-redacted.png" "%INPUT%\screen-redacted.certutil-sha256.txt" "%INPUT%\screen-redacted.redaction-review.json"
if /i "%PY312_MODE%"=="python" python -c "import hashlib,json,pathlib,re,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); b=json.load(open(sys.argv[2],encoding='utf-8')); lines=[re.sub(rb'\s',b'',x).lower() for x in pathlib.Path(sys.argv[4]).read_bytes().splitlines()]; hs=[x.decode('ascii') for x in lines if re.fullmatch(rb'[0-9a-f]{64}',x)]; image=pathlib.Path(sys.argv[3]).read_bytes(); digest=hashlib.sha256(image).hexdigest(); assert len(hs)==1 and hs[0]==digest; ids=[a['facts']['record_id'],b['facts']['record_id']]; assert a['ok'] is True and b['ok'] is True and ids[0]!=ids[1]; doc={'decision':'approved-redacted','image_sha256':digest,'review_record_ids':ids,'schema_version':1}; pathlib.Path(sys.argv[5]).write_text(json.dumps(doc,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')" "%INPUT%\redaction-review-first-receipt.json" "%INPUT%\redaction-review-second-receipt.json" "%INPUT%\screen-redacted.png" "%INPUT%\screen-redacted.certutil-sha256.txt" "%INPUT%\screen-redacted.redaction-review.json"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\screen-redacted.png"
echo %ERRORLEVEL%
```

上面两个 receipt 中的 `facts.record_id` 是机器生成的真实绑定；sidecar 文件名必须精确为
`screen-redacted.redaction-review.json`，且 strict JSON 只能有 `decision`、`image_sha256`、
`review_record_ids`、`schema_version` 四个字段。两名复核者的身份由两个不同 review record 的受控分配记录证明，
不能向 sidecar 自行增加 `reviewers`、姓名或其它字段。若 `py` launcher 不可用，先确认 fallback `python` 已通过
本手册 CPython 3.12 检查；以上每项辅助命令会按 `%PY312_MODE%` 只执行已验证分支，不要求人工替换，也不得使用
其它解释器。

## 8. 状态、finalize、hash 与回传

先确认状态列出环境、五项 entitlement、五个 observed Reference point 和必要 operator records；compile、tests、
artifact 必须仍为 not-run/not-produced：

```bat
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category session --input "%INPUT%\session-observation.txt"
echo %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
echo %ERRORLEVEL%
call run-discovery.cmd finalize-raw --capture "%CAPTURE%" --output-root "%RAW%"
echo %ERRORLEVEL%
dir /a "%RAW%"
certutil -hashfile "%RAW%\raw-discovery-capture.zip" SHA256
certutil -hashfile "%RAW%\raw-capture-manifest.json" SHA256
certutil -hashfile "%RAW%\SHA256SUMS" SHA256
```

`finalize-raw` 只接受完整、canonical、预算内且未污染的 capture，并拒绝覆盖现有 `%RAW%`。把整个 `%RAW%` 目录、
三项 hash 的人工见证记录，通过批准的离线通道返回 A 环境；不得只返回 ZIP，不得返回工作 CATVBA，不得提交公开
Git。回传完成后关闭 CATIA，隔离一次性 capture/工程，**恢复干净 VM** snapshot；该工程绝不能续作 G2/G3。

## 9. 所有停止代码与受控恢复

JSON 中 `ok=false`、任何 diagnostic 或退出码非零都立即停止。exit 2 仅是 argparse 参数/usage 错误；exit 3 是输入、
路径、记录、capture/finalize 以及 external state/current/ledger/handoff/bundle 信任失败；exit 4 仅是 preflight 的
CPython、Python 3.12 或 native Windows runtime/platform 失败；0 仅表示本步骤完成。wrapper 找不到受支持解释器或
pyz 时返回 9009，不伪装成 collector exit 2。

| 代码族 | 处理 |
|---|---|
| `COLLECTOR_CPYTHON_REQUIRED`、`COLLECTOR_PYTHON_312_REQUIRED`、`COLLECTOR_NATIVE_WINDOWS_REQUIRED` | preflight exit 4；修正批准 runtime/platform，从头开始 |
| `COLLECTOR_CLOCK_INVALID`、`COLLECTOR_TIME_INVALID` | exit 3；修正时钟见证，从头开始 |
| `COLLECTOR_EXTERNAL_STATE_REQUIRED`、`COLLECTOR_CURRENT_INVALID`、`COLLECTOR_CURRENT_BUNDLE_MISMATCH` | 从仓库取得新 sibling current/ledger，从头开始 |
| `COLLECTOR_LEDGER_INVALID`、`COLLECTOR_LEDGER_SOURCE_MISMATCH`、`COLLECTOR_LEDGER_CAPTURED_IN_FUTURE`、`COLLECTOR_LEDGER_STALE` | 停止，A 环境刷新 ledger |
| `COLLECTOR_HANDOFF_INVALID`、`COLLECTOR_HANDOFF_ID_MISMATCH`、`COLLECTOR_HANDOFF_TIME_MISMATCH`、`COLLECTOR_HANDOFF_NOT_YET_VALID`、`COLLECTOR_HANDOFF_EXPIRED`、`COLLECTOR_HANDOFF_WITHDRAWN`、`COLLECTOR_HANDOFF_NOT_ACTIVE`、`COLLECTOR_HANDOFF_BINDING_MISMATCH`、`COLLECTOR_HANDOFF_HASH_MISMATCH`、`COLLECTOR_CURRENT_HANDOFF_MISMATCH` | 隔离旧包，禁止绕过，取得新签发状态 |
| `COLLECTOR_PROVENANCE_INVALID`、`COLLECTOR_SKELETON_HASH_MISMATCH`、所有 `MEMBER`/`SKELETON`/hash/size/count/collision 错误 | bundle 作废，重新从仓库取得 |
| 所有 `PATH`/`FILE`/overlap/unsafe/read/write/atomic publish/staging cleanup 错误 | 隔离目录，A 环境调查；不用复制或重命名 staging 补救 |
| 所有 `INPUT`/`JSON`/`CSV`/noncanonical/environment/license/reference/operator/redaction/capture invalid/incomplete 错误 | 保留原始事实，按本手册修正新输入；已关闭点出错则新 session |
| `COLLECTOR_POINT_INVALID`、`COLLECTOR_POINT_ORDER_INVALID`、`COLLECTOR_POINT_CLOSED`、`COLLECTOR_REFERENCE_DUPLICATE`、`COLLECTOR_OUTPUT_EXISTS`、`COLLECTOR_UPDATE_CONFLICT`、`COLLECTOR_UPDATE_BUSY` | 禁止覆盖或回写，当前 session 作废 |
| `COLLECTOR_CAPTURE_BUSY` | 确认无并发进程；不得手删 lock |
| `COLLECTOR_STALE_LOCK_INVALID`、`COLLECTOR_STALE_LOCK_IDENTITY_MISMATCH`、`COLLECTOR_STALE_LOCK_STAGING_PRESENT` | 不恢复，当前 session 作废 |

stale-lock 没有日常 CLI 强制解锁。仅获准维护人员可在隔离副本调用源码
`recover_stale_record_lock`，并必须同时证明记录 PID 已死亡、process identity 匹配、lock 文件 identity 未变、没有
`.record-staging-*`；任一条件不满足就恢复 blank VM 新建 session。禁止删除 lock 后继续原 capture。

## 10. A 环境接力

A 环境接收后先核对通道记录与 SHA256SUMS，在只读临时根重新解包和执行严格 raw ingestion；独立确认 canonical、
member allowlist、Kit/handoff/bundle identity、五点 transition、脱敏与 operator index。只有 A 环境才可计算 Discovery
blocked receipt、observation approval 和 sealed evidence。Discovery 合法结果仍不是 PASS；随后才能人工批准 clean
Reference contract、提交新 evidence implementation、双构建 formal Kit、刷新 active ledger 并安排新的 blank VM
正式 G2。任何阶段不得把本次 raw capture 或一次性 CATVBA 当作 active artifact。
