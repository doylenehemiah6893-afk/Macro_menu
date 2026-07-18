# B28 Discovery 快速执行表

仅在批准的 blank VM snapshot、普通标准用户和原生 `cmd.exe` 中执行。将完整 bundle 复制到
`C:\B28Discovery\bundle`；外部最新 `CURRENT.json` 与 `active-handoff-ledger.json` 放在
`C:\B28Discovery\control`。先在窗口顶部逐条设置：

```bat
set "ROOT=C:\B28Discovery"
set "BUNDLE=%ROOT%\bundle"
set "CONTROL=%ROOT%\control"
set "CAPTURE=%ROOT%\capture-session-01"
set "RAW=%ROOT%\return-session-01"
set "INPUT=%ROOT%\inputs"
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
mkdir "%INPUT%"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\environment-input.json" "%INPUT%\environment-input.json"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\entitlements-input.csv" "%INPUT%\entitlements-input.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\session-observation.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\environment-observation.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\entitlement-observation.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\redaction-review-first.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\redaction-review-second.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
```

必须显示 verified mode。`py -3.12` 通过时不要求 PATH 有 `python`；只有 `py` 缺失或严格检查失败才验证 fallback。
现在只编辑并人工复核 environment、五项 entitlement、session/review 文本；不得创建或预填任何未来 Reference
CSV。禁止把模板示例 hash 或示例 Windows 字段当成现场事实。保存后执行 placeholder fail-close：

```bat
findstr /S /I "REPLACE_" "%INPUT%\environment-input.json" "%INPUT%\entitlements-input.csv"
if not errorlevel 1 (echo ERROR: unresolved template placeholder. 1>&2 & exit /b 3)
```

确认编辑并人工复核完成后按顺序执行；每条命令的下一行都失败关闭：

```bat
call run-discovery.cmd preflight --bundle "%BUNDLE%" --current "%CONTROL%\CURRENT.json" --revocation-ledger "%CONTROL%\active-handoff-ledger.json"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd init-capture --bundle "%BUNDLE%" --current "%CONTROL%\CURRENT.json" --revocation-ledger "%CONTROL%\active-handoff-ledger.json" --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd record-environment --capture "%CAPTURE%" --input "%INPUT%\environment-input.json"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category environment --input "%INPUT%\environment-observation.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd record-entitlements --capture "%CAPTURE%" --input "%INPUT%\entitlements-input.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category entitlement --input "%INPUT%\entitlement-observation.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
```

## 人工阶段 A：blank-project

在 blank VM 中人工新建全新空白一次性 VBA project，只读观察当时 VBE References。观察完成后才复制本点模板：

```bat
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-blank-project.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-blank-project.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
```

只填写本次观察并人工复核；不得复制上一点或创建后续 CSV。然后关闭本点：

```bat
findstr /I "REPLACE_" "%INPUT%\references-blank-project.csv"
if not errorlevel 1 (echo ERROR: unresolved blank-project placeholder. 1>&2 & exit /b 3)
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point blank-project --input "%INPUT%\references-blank-project.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-blank-project.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
```

## 人工阶段 B：post-form-import

仅按 Kit import order 人工导入 form；FRM 与同 basename FRX 必须原子成对，FRX 不单独打开或导入。完成并观察后：

```bat
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-form-import.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-form-import.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
findstr /I "REPLACE_" "%INPUT%\references-post-form-import.csv"
if not errorlevel 1 (echo ERROR: unresolved post-form-import placeholder. 1>&2 & exit /b 3)
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-form-import --input "%INPUT%\references-post-form-import.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-form-import.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
```

## 人工阶段 C：post-all-import

继续按清单人工导入全部剩余 modules/forms，仍禁止 Compile。完成并观察后：

```bat
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-all-import.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-all-import.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
findstr /I "REPLACE_" "%INPUT%\references-post-all-import.csv"
if not errorlevel 1 (echo ERROR: unresolved post-all-import placeholder. 1>&2 & exit /b 3)
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-all-import --input "%INPUT%\references-post-all-import.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-all-import.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
```

## 人工阶段 D：post-save

人工保存这一个一次性工程；保存不代表生成发布 CATVBA。完成保存并观察后：

```bat
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-save.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-save.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
findstr /I "REPLACE_" "%INPUT%\references-post-save.csv"
if not errorlevel 1 (echo ERROR: unresolved post-save placeholder. 1>&2 & exit /b 3)
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-save --input "%INPUT%\references-post-save.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-save.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
```

## 人工阶段 E：post-restart

彻底退出 CATIA、VBE 和残留宿主，再重新启动并打开同一一次性工程；此时不得先恢复 VM。完成重启观察后：

```bat
copy "%BUNDLE%\templates\references-input.csv" "%INPUT%\references-post-restart.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
copy "%BUNDLE%\templates\operator-record.txt" "%INPUT%\reference-post-restart.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
findstr /I "REPLACE_" "%INPUT%\references-post-restart.csv"
if not errorlevel 1 (echo ERROR: unresolved post-restart placeholder. 1>&2 & exit /b 3)
call run-discovery.cmd import-reference-csv --capture "%CAPTURE%" --point post-restart --input "%INPUT%\references-post-restart.csv"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\reference-post-restart.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
```

五点全部关闭后，按 `SECURITY_AND_REDACTION.md` 完成可选图片及双人复核。只有此时才可 finalize：

```bat
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category session --input "%INPUT%\session-observation.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd status --capture "%CAPTURE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd finalize-raw --capture "%CAPTURE%" --output-root "%RAW%"
if errorlevel 1 exit /b %ERRORLEVEL%
certutil -hashfile "%RAW%\raw-discovery-capture.zip" SHA256
if errorlevel 1 exit /b %ERRORLEVEL%
certutil -hashfile "%RAW%\raw-capture-manifest.json" SHA256
if errorlevel 1 exit /b %ERRORLEVEL%
certutil -hashfile "%RAW%\SHA256SUMS" SHA256
if errorlevel 1 exit /b %ERRORLEVEL%
```

五份 Reference CSV 都必须由当时的 VBE References 只读观察单独填写，不得复制上一点冒充。FRM 与同 basename
FRX 必须作为一对从 Kit 原子导入；FRX 不单独打开或修改。全过程禁止 Compile，30 个 case 不运行。

将整个 `%RAW%` 目录和另行记录的 hash 通过批准通道返回 A 环境；不要返回工作 CATVBA。完成后关闭 CATIA，
隔离 capture，恢复干净 VM snapshot。
