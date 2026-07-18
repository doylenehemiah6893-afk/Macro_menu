# 安全与脱敏

目标输出是 `raw/untrusted`：采集器可减少误操作，但 Windows 标准用户目录不是敌对 root 下的可信发布边界。
将 bundle、control、input、capture、return 放在管理员预建、仅本次操作员可写的本地 NTFS 目录；禁止网络共享、
同步盘、junction、reparse point、symlink、hard link、用户 Temp 和客户目录。Windows ACL 只能建立非敌对 root 的
操作前提，不能让 raw 输出变成 sealed evidence。

不得记录机器全名、用户名、账号、客户/项目/PN/模型名称、DSLS server/endpoint/IP、完整绝对路径、最近文件、
token/口令。Reference 只写获准的 root kind、相对路径、basename 与 SHA-256。DSLS 只观察五项 license ID 的
availability/checkout；不得截取服务端身份。

文本先由操作员自检，再由两名不同人员独立复核。图片必须先在批准工具中裁剪/脱敏，计算图片 SHA-256，并建立
同 basename 的 `.redaction-review.json`；其中两个 review record ID 必须来自先前已加入 capture 的不同复核记录。
任何人无法确认无敏感信息时，不加入 capture。原始未脱敏图片不得进入 bundle、capture、return 或 Git。

两条 review 文本已由 QUICKSTART 复制且必须由不同复核者编辑。以下命令分别保存机器 JSON receipt，以已验证的
`%PY312_MODE%` 读取 `facts.record_id`。图片以 `certutil -hashfile` 产生独立 hash receipt，再由 Python `hashlib`
复算并要求相等。sidecar 必须与图片同 basename；例如 `screen-redacted.png` 只能配
`screen-redacted.redaction-review.json`。其 canonical JSON 只能含四个 exact 字段：`schema_version=1`、
`decision=approved-redacted`、实际 `image_sha256`、两个不同真实 ID 的 `review_record_ids`。不得加入 reviewer 姓名、
`reviewers` 或任何未知字段。

```bat
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category review --input "%INPUT%\redaction-review-first.txt" > "%INPUT%\redaction-review-first-receipt.json"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category review --input "%INPUT%\redaction-review-second.txt" > "%INPUT%\redaction-review-second-receipt.json"
if errorlevel 1 exit /b %ERRORLEVEL%
certutil -hashfile "%INPUT%\screen-redacted.png" SHA256 > "%INPUT%\screen-redacted.certutil-sha256.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
if /i "%PY312_MODE%"=="py" py -3.12 -c "import hashlib,json,pathlib,re,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); b=json.load(open(sys.argv[2],encoding='utf-8')); lines=[re.sub(rb'\s',b'',x).lower() for x in pathlib.Path(sys.argv[4]).read_bytes().splitlines()]; hs=[x.decode('ascii') for x in lines if re.fullmatch(rb'[0-9a-f]{64}',x)]; digest=hashlib.sha256(pathlib.Path(sys.argv[3]).read_bytes()).hexdigest(); ids=[a['facts']['record_id'],b['facts']['record_id']]; assert a['ok'] is True and b['ok'] is True and len(hs)==1 and hs[0]==digest and ids[0]!=ids[1]; doc={'decision':'approved-redacted','image_sha256':digest,'review_record_ids':ids,'schema_version':1}; pathlib.Path(sys.argv[5]).write_text(json.dumps(doc,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')" "%INPUT%\redaction-review-first-receipt.json" "%INPUT%\redaction-review-second-receipt.json" "%INPUT%\screen-redacted.png" "%INPUT%\screen-redacted.certutil-sha256.txt" "%INPUT%\screen-redacted.redaction-review.json"
if /i "%PY312_MODE%"=="python" python -c "import hashlib,json,pathlib,re,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); b=json.load(open(sys.argv[2],encoding='utf-8')); lines=[re.sub(rb'\s',b'',x).lower() for x in pathlib.Path(sys.argv[4]).read_bytes().splitlines()]; hs=[x.decode('ascii') for x in lines if re.fullmatch(rb'[0-9a-f]{64}',x)]; digest=hashlib.sha256(pathlib.Path(sys.argv[3]).read_bytes()).hexdigest(); ids=[a['facts']['record_id'],b['facts']['record_id']]; assert a['ok'] is True and b['ok'] is True and len(hs)==1 and hs[0]==digest and ids[0]!=ids[1]; doc={'decision':'approved-redacted','image_sha256':digest,'review_record_ids':ids,'schema_version':1}; pathlib.Path(sys.argv[5]).write_text(json.dumps(doc,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')" "%INPUT%\redaction-review-first-receipt.json" "%INPUT%\redaction-review-second-receipt.json" "%INPUT%\screen-redacted.png" "%INPUT%\screen-redacted.certutil-sha256.txt" "%INPUT%\screen-redacted.redaction-review.json"
if errorlevel 1 exit /b %ERRORLEVEL%
call run-discovery.cmd add-operator-record --capture "%CAPTURE%" --category reference --input "%INPUT%\screen-redacted.png"
if errorlevel 1 exit /b %ERRORLEVEL%
```

若没有截图，跳过本段图片命令；两份文本复核记录仍应保留。任何命令失败立即停止，不得手工编造 record ID/hash。

公开仓库只接收经过人工复核的 public attestation/摘要；真实 environment、DSLS、Reference、operator record、
returned CATVBA 或 sealed evidence 均不得提交。
