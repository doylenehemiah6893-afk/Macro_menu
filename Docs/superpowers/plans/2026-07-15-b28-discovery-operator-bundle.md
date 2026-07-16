# B28 Discovery Operator Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可在原生 Windows CATIA B28 + Python 3.12 目标机采集 Discovery 证据、可由 A 环境严格验证封存、并能从完整 Git clone 恢复工作的仓库内操作包。

**Architecture:** Windows 端使用仅依赖 Python 标准库的有限状态机采集器，输出明确标记为 `raw/untrusted` 的 canonical capture；现有 POSIX A 环境继续承担 Kit 构建、严格容器验证、Gate、审批和封存。代码提交与制品记录提交分离：先形成 clean evidence implementation commit，再双构建和签发新 handoff，最后仅在非治理路径加入可公开 bundle 与续作记录。

**Tech Stack:** Python 3.12、标准库 `argparse/csv/hashlib/json/pathlib/zipfile`、现有 `jsonschema`/Build Kit/evidence harness、pytest、uv、Windows `cmd.exe`、GitHub Actions Linux/Windows runners。

## Global Constraints

- 唯一工作仓库/分支：`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`。
- 批准 cutoff 固定为 `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`；不得接收 `dev@688911522f88e2283231fb59232ea43edd3174a5`。
- 不 merge、rebase 或 cherry-pick `main/dev`；不 force-push，不创建 tag/Release，不写 Production 宏库。
- 目标机固定为 CATIA V5-6R2018 / R28 / B28、VBA7、Win64、Python 3.12；不得依赖 WSL 或 PowerShell。
- 资格条件固定为 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`。
- Discovery 固定 `compile_status=not-run`、30 个 target case 全部 `not-run`、`artifact_status=not-produced`、`release_eligible=false`。
- Windows 输出始终是 `raw/untrusted`；Gate、approval、seal 只允许在 A 环境运行。
- 目标机完整代码、`.pyz/.cmd`、模板、中文教程、Kit、handoff、skeleton、公开摘要和过程记录必须推送仓库。
- 真实 environment/DSLS/Reference/operator record/returned CATVBA/sealed evidence 不进入公开 Git；只提交人工复核后的 public attestation 和摘要。
- 所有生产行为先写失败测试并观察预期失败，再写最小实现；每个任务单独提交。

---

## File Structure

### 新增生产代码

- `catvba_refactor/macro_build/resume.py`：加载/验证续作状态、Git baseline、bundle 与 handoff 状态。
- `catvba_refactor/macro_build/operator_bundle.py`：构建 pyz、session skeleton、provenance 与 immutable operator bundle。
- `catvba_refactor/target_collector/__init__.py`：目标采集器版本与公共常量。
- `catvba_refactor/target_collector/__main__.py`：zipapp 入口。
- `catvba_refactor/target_collector/cli.py`：有限状态机 CLI。
- `catvba_refactor/target_collector/canonical.py`：无第三方依赖的 canonical JSON/hash。
- `catvba_refactor/target_collector/workspace.py`：Windows raw capture 安全边界与状态转换。
- `catvba_refactor/target_collector/records.py`：环境、权益、Reference、operator record 规范化。
- `catvba_refactor/target_collector/finalize.py`：raw manifest、SHA256SUMS、deterministic ZIP。
- `scripts/bootstrap_resume.py`：fresh clone 固定 baseline bootstrap。
- `scripts/verify_resume.py`：一键全量复现和 receipt。
- `scripts/bootstrap-resume.cmd`、`scripts/bootstrap-resume.sh`：薄 wrapper。

### 新增 schema/template/state

- `catvba_refactor/schemas/resume-state.schema.json`
- `catvba_refactor/schemas/revocation-snapshot.schema.json`
- `catvba_refactor/schemas/active-handoff-ledger.schema.json`
- `catvba_refactor/schemas/operator-bundle-provenance.schema.json`
- `catvba_refactor/schemas/raw-capture-manifest.schema.json`
- `catvba_refactor/schemas/collector-environment-input.schema.json`
- `catvba_refactor/schemas/collector-entitlements-input.schema.json`
- `catvba_refactor/templates/target_operator/*`
- `resume/state.json`
- `RESUME.md`

### 新增测试

- `catvba_refactor/tests/test_resume.py`
- `catvba_refactor/tests/test_target_collector_workspace.py`
- `catvba_refactor/tests/test_target_collector_records.py`
- `catvba_refactor/tests/test_target_collector_finalize.py`
- `catvba_refactor/tests/test_operator_bundle.py`
- `catvba_refactor/tests/test_verify_resume.py`

### 文档与 CI

- `Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md`
- `Docs/process/2026-07-15-b28-discovery-operator-bundle-build.md`
- `.github/workflows/repro.yml`
- `.github/workflows/auto-release.yml`：移除 tag 触发并改成不可执行的历史说明，或删除后在文档记录原因。

### 生成制品（Delivery record commit 才加入）

- `artifacts/b28-discovery/CURRENT.json`
- `artifacts/b28-discovery/active-handoff-ledger.json`
- `artifacts/b28-discovery/bundles/${BUNDLE_ID}/*`

---

### Task 1: Resume、revocation 与 bundle schema

**Files:**
- Create: `catvba_refactor/schemas/resume-state.schema.json`
- Create: `catvba_refactor/schemas/revocation-snapshot.schema.json`
- Create: `catvba_refactor/schemas/active-handoff-ledger.schema.json`
- Create: `catvba_refactor/schemas/operator-bundle-provenance.schema.json`
- Create: `catvba_refactor/schemas/raw-capture-manifest.schema.json`
- Create: `catvba_refactor/tests/test_resume.py`
- Modify: `catvba_refactor/tests/test_target_evidence_schemas.py`

**Interfaces:**
- Produces: strict schema documents consumed by `resume.py`, `operator_bundle.py` and target collector fixtures.
- Produces: `load_resume_state(path: Path, schema_dir: Path) -> dict[str, Any]` contract for Task 2.
- Produces: `validate_active_ledger(document: Mapping[str, Any], *, effective_at: datetime) -> ValidationReport`.

- [ ] **Step 1: Write failing strict-schema tests**

```python
def test_resume_state_schema_rejects_unknown_and_self_referential_fields(schema_dir):
    state = valid_resume_state()
    state["state_commit"] = "a" * 40
    errors = validate_document(schema_dir / "resume-state.schema.json", state)
    assert [error.validator for error in errors] == ["additionalProperties"]


def test_active_ledger_requires_each_handoff_in_exactly_one_set(schema_dir):
    ledger = valid_active_ledger()
    ledger["active_handoff_ids"] = ["handoff-example"]
    ledger["withdrawn_handoff_ids"] = ["handoff-example"]
    with pytest.raises(EvidenceError, match="HANDOFF_LEDGER_ID_OVERLAP"):
        validate_active_ledger(ledger, effective_at="2026-07-15T18:00:00Z")
```

- [ ] **Step 2: Run tests and observe RED**

Run:

```bash
uv run pytest -q catvba_refactor/tests/test_resume.py catvba_refactor/tests/test_target_evidence_schemas.py
```

Expected: FAIL because the five schema files and active-ledger validator do not exist.

- [ ] **Step 3: Add strict schema documents**

All schemas must use:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version"],
  "properties": {"schema_version": {"const": 1}}
}
```

Extend the actual documents with the exact fields from the approved design. Use 40-lowercase-hex patterns for Git OIDs,
64-lowercase-hex for SHA-256, `date-time` plus terminal `Z` for UTC, and enums for all Gate/revocation statuses. Add semantic
validation for active/withdrawn overlap and future `captured_at`; schema alone must not attempt cross-array uniqueness.

- [ ] **Step 4: Run schema tests and full schema suite**

```bash
uv run pytest -q catvba_refactor/tests/test_resume.py catvba_refactor/tests/test_target_evidence_schemas.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catvba_refactor/schemas catvba_refactor/tests/test_resume.py catvba_refactor/tests/test_target_evidence_schemas.py
git commit -m "feat: define discovery delivery state contracts"
```

### Task 2: Fresh-clone bootstrap and doctor

**Files:**
- Create: `catvba_refactor/macro_build/resume.py`
- Create: `scripts/bootstrap_resume.py`
- Create: `scripts/bootstrap-resume.cmd`
- Create: `scripts/bootstrap-resume.sh`
- Modify: `catvba_refactor/macro_build/cli.py`
- Modify: `catvba_refactor/macro_build/git_objects.py`
- Modify: `catvba_refactor/config/project.json`
- Modify: `catvba_refactor/tests/test_resume.py`
- Modify: `catvba_refactor/tests/test_cli.py`
- Modify: `catvba_refactor/tests/test_git_objects.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `bootstrap_repository(repo_root: Path, state_path: Path) -> ResumeReport`.
- Produces: `doctor_repository(repo_root: Path, state_path: Path, *, now: datetime) -> ResumeReport`.
- Produces CLI: `macro-menu-build doctor --state resume/state.json`.
- Hardens every Git subprocess with `GIT_NO_REPLACE_OBJECTS=1` and `GIT_LITERAL_PATHSPECS=1`.

- [ ] **Step 1: Write failing bootstrap tests**

```python
APPROVED_CUTOFF = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
CURRENT_REMOTE_DEV = "688911522f88e2283231fb59232ea43edd3174a5"


def test_bootstrap_creates_only_the_approved_local_dev_ref(fresh_clone, state_file):
    report = bootstrap_repository(fresh_clone, state_file)
    assert report.ok
    assert git(fresh_clone, "rev-parse", "refs/heads/dev") == APPROVED_CUTOFF
    assert git(fresh_clone, "rev-parse", "refs/remotes/origin/dev") == CURRENT_REMOTE_DEV


def test_bootstrap_refuses_conflicting_local_dev(fresh_clone, state_file):
    git(fresh_clone, "branch", "dev", CURRENT_REMOTE_DEV)
    report = bootstrap_repository(fresh_clone, state_file)
    assert not report.ok
    assert [item.code for item in report.diagnostics] == ["RESUME_BASELINE_REF_CONFLICT"]
```

Also add tests for missing `.git`, shallow clone, missing cutoff object, wrong branch/repository, replace refs, dirty governed
paths and untracked `macro_menu.egg-info/`.

Add Git subprocess and external-config regression tests:

```python
def test_git_environment_disables_replace_refs_and_pathspec_magic(repo):
    environment = repo.command_environment()
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_LITERAL_PATHSPECS"] == "1"


def test_candidate_build_rejects_external_config_directory(tmp_path):
    result = cli.main(["build-kit", "--config-dir", str(tmp_path / "config")])
    assert result == ExitCode.CONFIG
```

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_resume.py catvba_refactor/tests/test_cli.py catvba_refactor/tests/test_git_objects.py
```

Expected: FAIL because `resume.py`, bootstrap scripts and `doctor` do not exist.

- [ ] **Step 3: Implement the minimal report and Git checks**

Use immutable records:

```python
@dataclass(frozen=True, order=True)
class ResumeDiagnostic:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ResumeReport:
    ok: bool
    diagnostics: tuple[ResumeDiagnostic, ...]
    facts: Mapping[str, Any]
```

`bootstrap_repository` must execute `git update-ref refs/heads/dev APPROVED_CUTOFF ZERO_OID` only when the ref is absent,
and only after verifying repository identity, intake record digest, commit object and `Src/resources` tree OIDs. Do not use
`git checkout`, `reset`, `fetch`, `merge` or a floating remote ref.

Change both configured baseline refs to the fully qualified literal `refs/heads/dev`. Reject any `refs/replace/*` before snapshot
freeze, disable replacement objects and pathspec magic in every Git subprocess, and validate governed paths as repository-relative
portable literals. Candidate `build-kit` must reject external `--config-dir/--schema-dir`; diagnostic `inventory/check --worktree`
may retain explicit fixture paths but always remains `formal_eligible=false`.

- [ ] **Step 4: Add doctor CLI and wrappers**

Parser contract:

```python
doctor = commands.add_parser("doctor", parents=[common], allow_abbrev=False)
doctor.add_argument("--state", required=True, type=Path)
```

`scripts/bootstrap-resume.cmd` must contain only:

```bat
@echo off
setlocal
py -3.12 "%~dp0bootstrap_resume.py" --repo-root "%~dp0.." --state "%~dp0..\resume\state.json"
if errorlevel 1 exit /b %errorlevel%
```

The shell wrapper calls the same Python file. Add `*.egg-info/` to `.gitignore`.

- [ ] **Step 5: Verify GREEN**

```bash
uv run pytest -q catvba_refactor/tests/test_resume.py catvba_refactor/tests/test_cli.py catvba_refactor/tests/test_git_objects.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .gitignore scripts catvba_refactor/config/project.json catvba_refactor/macro_build/resume.py catvba_refactor/macro_build/cli.py catvba_refactor/macro_build/git_objects.py catvba_refactor/tests/test_resume.py catvba_refactor/tests/test_cli.py catvba_refactor/tests/test_git_objects.py
git commit -m "feat: bootstrap and diagnose resume environments"
```

### Task 3: Discovery evidence and handoff hardening

**Files:**
- Modify: `catvba_refactor/macro_build/cli.py`
- Modify: `catvba_refactor/macro_build/handoff.py`
- Modify: `catvba_refactor/macro_build/target_evidence/session.py`
- Modify: `catvba_refactor/macro_build/target_evidence/validator.py`
- Modify: `catvba_refactor/macro_build/target_evidence/gate.py`
- Modify: `catvba_refactor/schemas/target_evidence/entitlements.schema.json`
- Modify: `catvba_refactor/tests/test_handoff.py`
- Modify: `catvba_refactor/tests/test_target_session.py`
- Modify: `catvba_refactor/tests/test_target_evidence_validator.py`
- Modify: `catvba_refactor/tests/test_target_gate.py`
- Modify: `catvba_refactor/tests/test_cli.py`

**Interfaces:**
- Produces: production handoff time from injected clock, not arbitrary CLI timestamp.
- Produces: target session preflight binding to a fresh external ledger.
- Produces: per-license evidence for AB3/HD2/MD2/SPA/FTA.
- Restricts formal profiles to `P-AB3|P-HD2|P-MD2`.

- [ ] **Step 1: Write failing security regression tests**

```python
def test_discovery_rejects_any_compile_attempt(valid_discovery_capture):
    valid_discovery_capture["compile-result.json"]["attempts"] = [{"phase": "post-import", "status": "passed"}]
    report = validate_fixture(valid_discovery_capture)
    assert "DISCOVERY_COMPILE_FORBIDDEN" in codes(report)


@pytest.mark.parametrize("profile", ["P-ALL", "P-PROD"])
def test_formal_cli_rejects_aggregate_profiles(profile):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(formal_session_args(profile))


def test_target_session_rejects_stale_or_withdrawn_external_ledger(valid_inputs):
    report = init_with_ledger(valid_inputs, captured_at="2026-07-13T00:00:00Z", withdrawn=True)
    assert codes(report) == ["HANDOFF_LEDGER_STALE", "HANDOFF_WITHDRAWN"]
```

Add a trusted-clock test proving production issuance ignores caller-supplied historical time; retain deterministic timestamps only
behind a private/injected test clock, not a public `--created-at` production option.

- [ ] **Step 2: Run focused tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_handoff.py catvba_refactor/tests/test_target_session.py catvba_refactor/tests/test_target_evidence_validator.py catvba_refactor/tests/test_target_gate.py catvba_refactor/tests/test_cli.py
```

Expected: FAIL for all new cases.

- [ ] **Step 3: Implement minimal hardening**

Use explicit license records:

```json
"licenses": {
  "AB3": {"availability": "observed-available", "checkout": "observed-checked-out"},
  "HD2": {"availability": "observed-unavailable", "checkout": "not-checked-out"},
  "MD2": {"availability": "observed-unavailable", "checkout": "not-checked-out"},
  "SPA": {"availability": "observed-available", "checkout": "observed-checked-out"},
  "FTA": {"availability": "observed-available", "checkout": "observed-checked-out"}
}
```

Formal Gate eligibility requires exactly one selected baseline profile matching an observed available/checked-out baseline and both
SPA/FTA observed available/checked-out. Discovery may record unknown/unavailable but can never become eligible.

Add `--revocation-ledger` to target init and collector preflight. Enforce `captured_at <= now`, maximum age 24 hours, active ID
membership, withdrawn absence and source identity. Keep `--created-at` only in a test-only Python API; CLI production timestamps come
from `datetime.now(UTC)` and TTL is exactly seven days unless a stricter configured expiry is supplied.

- [ ] **Step 4: Verify focused and full evidence tests**

```bash
uv run pytest -q catvba_refactor/tests/test_handoff.py catvba_refactor/tests/test_target_session.py catvba_refactor/tests/test_target_evidence_validator.py catvba_refactor/tests/test_target_gate.py catvba_refactor/tests/test_cli.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catvba_refactor/macro_build catvba_refactor/schemas/target_evidence catvba_refactor/tests
git commit -m "fix: enforce discovery and handoff trust boundaries"
```

### Task 4: Target collector workspace and canonical core

**Files:**
- Create: `catvba_refactor/target_collector/__init__.py`
- Create: `catvba_refactor/target_collector/__main__.py`
- Create: `catvba_refactor/target_collector/canonical.py`
- Create: `catvba_refactor/target_collector/workspace.py`
- Create: `catvba_refactor/target_collector/cli.py`
- Create: `catvba_refactor/tests/test_target_collector_workspace.py`

**Interfaces:**
- Produces: `python -m catvba_refactor.target_collector` and zipapp-compatible `main()`.
- Produces: `preflight`, `init-capture`, `status`.
- Consumes immutable bundle paths and external `CURRENT.json`/active ledger.

- [ ] **Step 1: Write failing platform/workspace tests**

```python
def test_preflight_requires_windows_cpython_312(bundle_fixture, monkeypatch):
    monkeypatch.setattr(platform, "python_implementation", lambda: "PyPy")
    result = run_collector("preflight", bundle_fixture)
    assert result.exit_code == 4
    assert result.codes == ("COLLECTOR_CPYTHON_REQUIRED",)


def test_init_capture_never_modifies_bundle(bundle_fixture, tmp_path):
    before = tree_digest(bundle_fixture)
    result = init_capture(bundle_fixture, tmp_path / "capture")
    assert result.ok
    assert tree_digest(bundle_fixture) == before
    assert read_json(result.session_dir / "session.json")["capture_status"] == "in-progress"
```

Add negative cases for absolute/UNC/traversal paths, symlink/reparse indicators, existing output, non-regular files, oversize and
hash mismatch. Use monkeypatched platform facts on Linux; Windows CI supplies the native smoke later.

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_target_collector_workspace.py
```

Expected: import failure because target collector package does not exist.

- [ ] **Step 3: Implement standard-library canonical and workspace APIs**

```python
def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def parse_canonical_json_bytes(data: bytes) -> object:
    value = json.loads(data.decode("ascii"), object_pairs_hook=require_unique_keys)
    if canonical_json_bytes(value) != data:
        raise CollectorError("COLLECTOR_NONCANONICAL_JSON")
    return value


def sha256_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise CollectorError("COLLECTOR_FILE_TOO_LARGE")
            digest.update(chunk)
    return digest.hexdigest(), size

@dataclass(frozen=True)
class CollectorResult:
    ok: bool
    exit_code: int
    diagnostics: tuple[CollectorDiagnostic, ...]
    facts: Mapping[str, object]
```

Do not import `jsonschema`, `macro_build.target_evidence.container` or any non-stdlib package. Copy only the authenticated skeleton
members listed by `provenance.json`; use exclusive-create mode for every output. Mark `trust_level=raw-untrusted` in session state.

- [ ] **Step 4: Add CLI and verify GREEN**

```bash
uv run pytest -q catvba_refactor/tests/test_target_collector_workspace.py
uv run python -m catvba_refactor.target_collector --help
```

Expected: PASS and help lists `preflight`, `init-capture`, `status`.

- [ ] **Step 5: Commit**

```bash
git add catvba_refactor/target_collector catvba_refactor/tests/test_target_collector_workspace.py
git commit -m "feat: add windows discovery collector core"
```

### Task 5: Environment, entitlement and Reference record commands

**Files:**
- Create: `catvba_refactor/target_collector/records.py`
- Create: `catvba_refactor/schemas/collector-environment-input.schema.json`
- Create: `catvba_refactor/schemas/collector-entitlements-input.schema.json`
- Create: `catvba_refactor/templates/target_operator/environment-input.json`
- Create: `catvba_refactor/templates/target_operator/entitlements-input.csv`
- Create: `catvba_refactor/templates/target_operator/references-input.csv`
- Create: `catvba_refactor/templates/target_operator/operator-record.txt`
- Create: `catvba_refactor/templates/target_operator/redaction-review.md`
- Create: `catvba_refactor/tests/test_target_collector_records.py`
- Modify: `catvba_refactor/target_collector/cli.py`

**Interfaces:**
- Produces: `record-environment`, `record-entitlements`, `import-reference-csv`, `add-operator-record`.
- Produces deterministic `environment.json`, `entitlements.json`, `references.json`, `operator-records/index.json`.

- [ ] **Step 1: Write failing record-normalization tests**

```python
REFERENCE_CSV = io.StringIO(
    "guid,major,minor,display_name,missing,architecture,source_class,root_kind,basename,relative_path,path_sha256\n"
    "{00020430-0000-0000-C000-000000000046},2,0,VBA,false,x64,system,CATIA_INSTALL,vbe7.dll,win_b64/code/bin/vbe7.dll," + "1" * 64 + "\n"
)
CSV_WITH_C_DRIVE_PATH = io.StringIO(
    "guid,major,minor,display_name,missing,architecture,source_class,root_kind,basename,relative_path,path_sha256\n"
    "{00020430-0000-0000-C000-000000000046},2,0,VBA,false,x64,system,CATIA_INSTALL,vbe7.dll,C:\\Users\\operator\\vbe7.dll," + "1" * 64 + "\n"
)


def test_reference_csv_produces_stable_ids_and_fixed_point_order(capture):
    import_reference_csv(capture, point="blank-project", source=REFERENCE_CSV)
    document = read_json(capture / "references.json")
    assert document["observations"][0]["point_id"] == "blank-project"
    observed = [item["stable_reference_id"] for item in document["observations"][0]["references"]]
    assert observed == sorted(observed)


def test_collector_rejects_reference_path_and_customer_text(capture):
    result = import_reference_csv(capture, point="blank-project", source=CSV_WITH_C_DRIVE_PATH)
    assert result.codes == ("COLLECTOR_SENSITIVE_PATH_FORBIDDEN",)
```

Add cases for observation point order, duplicate stable IDs, `MISSING`, B30/x86/VBA6/Temp/user-profile classifications,
AB3/HD2/MD2/SPA/FTA exact names, operator record size/type and immutable closed points.

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_target_collector_records.py
```

Expected: FAIL because record commands do not exist.

- [ ] **Step 3: Implement exact record APIs**

```python
POINT_ORDER = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
LICENSE_IDS = ("AB3", "HD2", "MD2", "SPA", "FTA")

def stable_reference_id(guid: str, major: int, minor: int) -> str:
    body = f"{guid.upper()}|{major}|{minor}".encode("ascii")
    return "reference-" + hashlib.sha256(body).hexdigest()[:24]
```

Paths in public JSON are limited to approved root kind, portable relative path/basename and hash. Reject raw drive letters, UNC,
user profile tokens and unapproved absolute paths before canonicalization. Operator images require a same-basename
`.redaction-review.json` naming two distinct reviewer record IDs.

- [ ] **Step 4: Verify GREEN and CLI help**

```bash
uv run pytest -q catvba_refactor/tests/test_target_collector_records.py
uv run python -m catvba_refactor.target_collector --help
```

Expected: PASS and all four record commands appear.

- [ ] **Step 5: Commit**

```bash
git add catvba_refactor/target_collector catvba_refactor/schemas/collector-* catvba_refactor/templates/target_operator catvba_refactor/tests/test_target_collector_records.py
git commit -m "feat: collect b28 discovery observations"
```

### Task 6: Raw finalizer and A-environment ingestion

**Files:**
- Create: `catvba_refactor/target_collector/finalize.py`
- Create: `catvba_refactor/tests/test_target_collector_finalize.py`
- Modify: `catvba_refactor/target_collector/cli.py`
- Modify: `catvba_refactor/macro_build/target_evidence/container.py`
- Modify: `catvba_refactor/macro_build/target_evidence/validator.py`
- Modify: `catvba_refactor/tests/test_target_evidence_container.py`
- Modify: `catvba_refactor/tests/test_target_evidence_validator.py`

**Interfaces:**
- Produces: `finalize-raw --capture PATH --output-root PATH`.
- Produces: deterministic `raw-discovery-capture.zip` and `raw-capture-manifest.json`.
- A environment consumes raw ZIP as a distinct phase before converting to an authenticated capture snapshot.

- [ ] **Step 1: Write failing finalize tests**

```python
def test_finalize_raw_is_deterministic_and_never_sealed(complete_capture, tmp_path):
    first = finalize_raw(complete_capture, tmp_path / "one")
    second = finalize_raw(complete_capture, tmp_path / "two")
    assert first.zip_sha256 == second.zip_sha256
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    assert "SESSION_COMPLETE" not in zip_members(first.zip_path)
    assert read_zip_json(first.zip_path, "raw-capture-manifest.json")["trust_level"] == "raw-untrusted"


def test_a_environment_rejects_raw_capture_claiming_compile(complete_capture):
    mutate_compile_status(complete_capture, "passed")
    report = validate_raw_capture(complete_capture)
    assert "DISCOVERY_COMPILE_FORBIDDEN" in codes(report)
```

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_target_collector_finalize.py catvba_refactor/tests/test_target_evidence_container.py catvba_refactor/tests/test_target_evidence_validator.py
```

Expected: FAIL because raw phase/finalizer do not exist.

- [ ] **Step 3: Implement deterministic raw ZIP**

Use sorted ASCII paths, fixed ZIP timestamp `(1980, 1, 1, 0, 0, 0)`, stored compression, external attributes for regular read-only
files, and exclusive output creation. `SHA256SUMS` excludes itself and is covered by `raw-capture-manifest.json`; neither file may
use `SESSION_COMPLETE`, `approval.json` or `gate-receipt.json`.

Add an explicit A-environment raw reader that applies the existing no-follow/container budgets after extraction to a new private
temporary root. It must never accept raw ZIP as `EvidencePhase.SEALED`.

- [ ] **Step 4: Verify GREEN**

```bash
uv run pytest -q catvba_refactor/tests/test_target_collector_finalize.py catvba_refactor/tests/test_target_evidence_container.py catvba_refactor/tests/test_target_evidence_validator.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catvba_refactor/target_collector catvba_refactor/macro_build/target_evidence catvba_refactor/tests
git commit -m "feat: finalize and ingest raw discovery captures"
```

### Task 7: Operator bundle builder and zipapp

**Files:**
- Create: `catvba_refactor/macro_build/operator_bundle.py`
- Create: `catvba_refactor/tests/test_operator_bundle.py`
- Modify: `catvba_refactor/macro_build/cli.py`
- Modify: `pyproject.toml`
- Modify: `.gitattributes`

**Interfaces:**
- Produces CLI: `macro-menu-build build-operator-bundle BUILD_ROOT --compare-build-root BUILD_ROOT --handoff FILE --ledger FILE --session-skeleton DIR --output-root DIR`.
- Produces deterministic target `target-discovery.pyz`, immutable bundle directory and `SHA256SUMS`.

- [ ] **Step 1: Write failing deterministic bundle tests**

```python
def test_operator_bundle_contains_complete_target_code_and_tutorials(bundle_fixture):
    receipt = build_operator_bundle(bundle_fixture.request)
    members = tree_members(receipt.bundle_dir)
    assert "source/target_collector/cli.py" in members
    assert "schemas/raw-capture-manifest.schema.json" in members
    assert "README_TARGET_B28.md" in members
    assert "target-discovery.pyz" in members


def test_operator_bundle_rejects_mismatched_dual_builds(bundle_fixture):
    corrupt(bundle_fixture.compare_root / "kit-test.zip")
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_BUILD_MISMATCH"):
        build_operator_bundle(bundle_fixture.request)
```

Add tests for bundle ID determinism, pyz/source parity, handoff/ledger identity, issuance snapshot, sidecar, skeleton, schema/tutorial
digests, existing output and absence of CATVBA.

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_operator_bundle.py catvba_refactor/tests/test_cli.py
```

Expected: FAIL because builder/CLI do not exist.

- [ ] **Step 3: Implement builder**

Use `zipapp.create_archive(source, target, interpreter="/usr/bin/env python3", main="catvba_refactor.target_collector.cli:main")`
only on a deterministic staging tree. Normalize generated pyz member timestamps after construction, or build the zip directly with
fixed metadata; the final test must prove two independent builds byte-identical.

`provenance.json` binds the evidence commit/tree, cutoff, Kit/handoff/skeleton/collector/tutorial/schema digests and all
`not-run/false` boundaries. `bundle-id` is `bundle-` plus the first 24 hex characters of canonical provenance SHA-256.

- [ ] **Step 4: Verify GREEN**

```bash
uv run pytest -q catvba_refactor/tests/test_operator_bundle.py catvba_refactor/tests/test_cli.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .gitattributes pyproject.toml catvba_refactor/macro_build/operator_bundle.py catvba_refactor/macro_build/cli.py catvba_refactor/tests/test_operator_bundle.py
git commit -m "feat: build deterministic b28 operator bundles"
```

### Task 8: Complete target tutorials, templates and resume entry

**Files:**
- Create: `Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md`
- Create: `RESUME.md`
- Create: `resume/state.json`
- Modify: `Docs/runbooks/2026-07-14-catvba-b28-g2-g3-core.md`
- Modify: `Docs/STATUS.md`
- Modify: `Docs/README.md`
- Modify: `catvba_refactor/README.md`
- Modify: `catvba_refactor/tests/test_project_layout.py`

**Interfaces:**
- Produces complete Chinese target tutorial and single resume entry.
- State initially records `active_bundle_path=null`, `revocation_status=preparation`, G2-G7 BLOCKED; Task 11 fills actual artifact fields.

- [ ] **Step 1: Write failing documentation contract tests**

```python
def test_target_runbook_contains_every_mandatory_stop_and_command(repo_root):
    text = (repo_root / "Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md").read_text("utf-8")
    for required in ("Python 3.12", "禁止 Compile", "blank-project", "post-form-import", "post-all-import", "post-save", "post-restart", "finalize-raw", "恢复干净 VM"):
        assert required in text


def test_resume_state_matches_schema_and_never_claims_release(repo_root):
    state = load_resume_state(repo_root / "resume/state.json", repo_root / "catvba_refactor/schemas")
    assert state["release_eligible"] is False
    assert state["gate_statuses"]["G2"] == "BLOCKED"
```

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_project_layout.py catvba_refactor/tests/test_resume.py
```

Expected: FAIL because runbook, resume entry and state do not exist.

- [ ] **Step 3: Write the complete tutorial**

The runbook must contain numbered, copy/paste-ready commands for preflight, init, each record command, status, finalize, hash and
return. It must explain blank VM, CATIA/VBE/DSLS/license observation, atomic FRM/FRX import, five points, redaction, two-person review,
raw/untrusted meaning, A-environment follow-up and every stop condition from the design. No angle-bracket placeholders are allowed;
use environment variables initialized at the top of the `.cmd` example.

- [ ] **Step 4: Write RESUME/state and update status docs**

State uses the current evidence implementation parent dynamically only after Task 10; until then its artifact fields are null and
`next_action="complete-evidence-implementation"`. Do not preserve stale claims that the old handoff bytes are available.

- [ ] **Step 5: Verify GREEN and links**

```bash
uv run pytest -q catvba_refactor/tests/test_project_layout.py catvba_refactor/tests/test_resume.py
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add RESUME.md resume Docs catvba_refactor/README.md catvba_refactor/tests/test_project_layout.py catvba_refactor/tests/test_resume.py
git commit -m "docs: add b28 operator and resume guides"
```

### Task 9: One-command reproducibility and CI

**Files:**
- Create: `scripts/verify_resume.py`
- Create: `catvba_refactor/tests/test_verify_resume.py`
- Create: `.github/workflows/repro.yml`
- Modify/Delete: `.github/workflows/auto-release.yml`
- Modify: `catvba_refactor/tests/test_project_layout.py`

**Interfaces:**
- Produces: `python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root PATH`.
- Produces canonical `reproducibility-receipt.json`.

- [ ] **Step 1: Write failing orchestrator tests**

```python
def test_verify_resume_runs_required_stages_in_order(monkeypatch, fixture_repo, tmp_path):
    calls = install_fake_commands(monkeypatch)
    receipt = verify_resume(fixture_repo, tmp_path / "out")
    assert calls == ["lock-check", "pytest", "inventory", "check", "build-1", "build-2", "verify-dir-1", "verify-zip-1", "verify-dir-2", "verify-zip-2", "compare", "collector-smoke"]
    assert receipt["ok"] is True


def test_release_workflow_cannot_trigger_on_tags(repo_root):
    workflows = list((repo_root / ".github/workflows").glob("*.yml"))
    assert all("tags:" not in path.read_text("utf-8") for path in workflows)
```

- [ ] **Step 2: Run tests and observe RED**

```bash
uv run pytest -q catvba_refactor/tests/test_verify_resume.py catvba_refactor/tests/test_project_layout.py
```

Expected: FAIL because orchestrator/CI do not exist and tag workflow remains.

- [ ] **Step 3: Implement verify_resume and workflows**

The script must use `subprocess.run(..., check=False, capture_output=True)` with explicit argv, a new output root, bounded stdout/stderr
capture and stable stage diagnostics. It must compare full Kit trees, ZIP bytes and sidecars, not only IDs.

`repro.yml` uses `actions/checkout`, `actions/setup-python` and `astral-sh/setup-uv` pinned to immutable commit SHAs. Linux runs full
suite/double build; Windows runs bootstrap doctor portability, target collector tests, `run-discovery.cmd` help and pyz smoke. Upload
only JSON receipts and the operator bundle candidate; never glob `*.catvba`.

Remove tag triggers from `auto-release.yml`; retain its historical intent in `Docs/发版.md` without an executable release job.

- [ ] **Step 4: Verify GREEN**

```bash
uv run pytest -q catvba_refactor/tests/test_verify_resume.py catvba_refactor/tests/test_project_layout.py
python scripts/bootstrap_resume.py --repo-root . --state resume/state.json
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root /tmp/macro-menu-plan-verification
```

Expected: tests and the real verification command PASS; preparation state remains `release_eligible=false` and may have no active
bundle yet.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_resume.py catvba_refactor/tests/test_verify_resume.py catvba_refactor/tests/test_project_layout.py .github/workflows Docs/发版.md
git commit -m "ci: verify fresh-clone discovery delivery"
```

### Task 10: Full review and evidence implementation commit

**Files:**
- Create: `Docs/process/2026-07-15-b28-discovery-operator-bundle-build.md` with implementation-phase facts through the evidence commit.
- Any review correction must name its exact production path and paired regression-test path in that process record before editing.

**Interfaces:**
- Produces the clean Git commit to which the new Kit/handoff binds.

- [ ] **Step 1: Run complete validation before review**

```bash
uv lock --check
uv sync --frozen
uv run pytest -q
uv run macro-menu-build doctor --state resume/state.json --format json
git diff --check
git status --porcelain=v1
```

Expected: lock/sync/tests/diff PASS. Doctor may report `active_bundle_path=null` only; all Git/toolchain/baseline checks must PASS.

- [ ] **Step 2: Request code review**

Review the complete diff from `eb64766d99e09b1ea901708d5fd793f4ca92a9de` to current HEAD against the approved design. Critical
and Important findings must be fixed with new failing tests before continuing. Re-run the full suite after every fix.

- [ ] **Step 3: Record implementation facts and commit**

The process document records exact commands, Python/uv versions, test counts, review record ID, known warnings and remaining external
CATIA blockers. Then:

```bash
git add Docs/process/2026-07-15-b28-discovery-operator-bundle-build.md
git commit -m "docs: record b28 operator implementation review"
git status --porcelain=v1
```

Expected: clean output. Save `EVIDENCE_COMMIT=$(git rev-parse HEAD)` and `EVIDENCE_TREE=$(git rev-parse HEAD^{tree})` in the
process shell; do not write a self-referential SHA into a file before the commit exists.

### Task 11: Build, issue, bundle and verify from the evidence commit

**Files:**
- Generated outside Git first: two Kit roots, handoff, skeleton, operator bundle candidate and JSON receipts.
- Modify after generation: `resume/state.json`, `Docs/STATUS.md`, process document.
- Create: `artifacts/b28-discovery/CURRENT.json`
- Create: `artifacts/b28-discovery/active-handoff-ledger.json`
- Create: `artifacts/b28-discovery/bundles/${BUNDLE_ID}/*`

**Interfaces:**
- Consumes the exact Task 10 evidence commit with local
  `dev@abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`.
- Produces the target-machine deliverable and delivery record commit.

- [ ] **Step 1: Bootstrap the fixed approved baseline**

```bash
python scripts/bootstrap_resume.py --repo-root . --state resume/state.json
test "$(git rev-parse refs/heads/dev)" = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
test -z "$(git status --porcelain=v1)"
```

Expected: PASS; `origin/dev` remains `688911522f88e2283231fb59232ea43edd3174a5` and is not checked out.

- [ ] **Step 2: Run full reproducibility into two fresh roots**

```bash
EVIDENCE_COMMIT=$(git rev-parse HEAD)
OUT=$(mktemp -d /tmp/macro-menu-b28-delivery.XXXXXX)
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root "$OUT/repro"
uv run macro-menu-build build-kit --output-root "$OUT/build-1" --format json > "$OUT/build-1.json"
uv run macro-menu-build build-kit --output-root "$OUT/build-2" --format json > "$OUT/build-2.json"
```

Read `kit_id` from `build-1.json` with the pinned project Python `json` module, not `jq`; assert both receipts and all directory/ZIP
bytes match. Run four explicit `verify-kit` commands and save their canonical JSON.

- [ ] **Step 3: Create current revocation records and new handoff**

Use a small checked-in helper/API from Tasks 1–3 to create canonical ledger records with:

```text
withdrawn_handoff_ids = [handoff-6ed312ee18b254cb3c13]
active_handoff_ids = [] before issuance
captured_at = trusted A-environment now
source = repository-active-handoff-ledger
```

Issue a new discovery handoff using the production trusted clock and seven-day TTL. Then write a second ledger record whose only active
ID is the newly returned handoff ID and whose withdrawn set still contains the old ID. Validate both records and the new handoff.

- [ ] **Step 4: Initialize skeleton and build operator bundle**

Initialize a deterministic Discovery skeleton using:

```bash
SESSION_ID="session-$(date -u +%Y%m%d)-discovery-$(git rev-parse --short=12 "$EVIDENCE_COMMIT")"
```

Use `macro-menu-build build-operator-bundle` with both build roots, new handoff, active ledger and skeleton. Build twice into separate
roots and require identical bundle ID, tree, pyz, Kit ZIP and SHA256SUMS. Run the target collector fixture flow and A-environment raw
ingestion; computed Discovery result must be exit 7 with `blocked/discovery-only`.

- [ ] **Step 5: Copy only public artifacts into Git paths**

Read `bundle_id` from the verified builder receipt into `BUNDLE_ID`, then copy the already-verified immutable bundle into
`artifacts/b28-discovery/bundles/${BUNDLE_ID}/`. Write `CURRENT.json` and the
active ledger as canonical JSON. Update `resume/state.json` with the evidence commit/tree, actual bundle/Kit/handoff IDs/digests,
expiry, test count, receipt path and `next_action="run-b28-discovery"`. Update `Docs/STATUS.md` without claiming CATIA execution.

Do not copy raw fixture data that contains synthetic host/DSLS/Reference facts into the public bundle; store only the sanitized test
receipt.

- [ ] **Step 6: Verify delivery-record boundary**

Before commit:

```bash
git diff --name-only "$EVIDENCE_COMMIT" -- Src resources catvba_refactor pyproject.toml uv.lock .python-version
```

Expected: no output. Then run:

```bash
uv run macro-menu-build doctor --state resume/state.json --format json
uv run pytest -q
git diff --check
```

Expected: PASS; G2-G7 BLOCKED and `release_eligible=false`.

- [ ] **Step 7: Commit the delivery record**

```bash
git add artifacts/b28-discovery resume/state.json Docs/STATUS.md Docs/process/2026-07-15-b28-discovery-operator-bundle-build.md
git commit -m "artifacts: publish b28 discovery operator bundle"
git status --porcelain=v1
```

Expected: clean output.

### Task 12: Remote publication and post-push verification

**Files:**
- No new local files unless remote CI reveals a defect; any defect follows a new RED/GREEN commit.

**Interfaces:**
- Produces remote branch with all source, process and artifact commits.
- Produces successful Linux/Windows reproducibility workflow evidence.

- [ ] **Step 1: Verify intended publication scope**

```bash
git status -sb
git log --oneline eb64766d99e09b1ea901708d5fd793f4ca92a9de..HEAD
git diff --stat eb64766d99e09b1ea901708d5fd793f4ca92a9de..HEAD
git diff --name-only eb64766d99e09b1ea901708d5fd793f4ca92a9de..HEAD -- main dev
```

Expected: clean branch; final command empty; no unrelated user changes.

- [ ] **Step 2: Push only `codex/dev-review-report`**

Preferred when authenticated:

```bash
git push origin codex/dev-review-report
```

If the environment still lacks HTTPS/SSH credentials, use the connected GitHub application to create the same ordered commits on
`doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`, fast-forward the ref only after verifying its old SHA, fetch the remote,
confirm tree equality, and align the local branch with `git update-ref`. Never write `main/dev`.

- [ ] **Step 3: Monitor and fix CI scientifically**

Inspect Linux and Windows jobs for the pushed head. If a job fails, use systematic debugging: capture the exact command/error, reproduce
locally or in a minimal platform fixture, add a failing regression test, implement one fix, rerun the focused and full suite, commit and
push. Do not rerun blindly or weaken security checks to make Windows green.

- [ ] **Step 4: Final fresh-clone verification**

In a new temporary directory:

```bash
git clone --branch codex/dev-review-report --single-branch https://github.com/doylenehemiah6893-afk/Macro_menu.git macro-menu-final
cd macro-menu-final
python scripts/bootstrap_resume.py --repo-root . --state resume/state.json
uv sync --frozen
uv run macro-menu-build doctor --state resume/state.json --format json
python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root /tmp/macro-menu-final-repro
```

Expected: bootstrap/doctor/verify PASS, local `dev=abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`, working tree clean, bundle hash valid, handoff active and unexpired,
all CATIA target cases still `not-run`, G2-G7 BLOCKED.

- [ ] **Step 5: Final handoff summary**

Report remote commit, evidence commit/tree, bundle path/ID/SHA, Kit/handoff ID and expiry, full test count, Linux/Windows CI URLs,
fresh-clone verification result, target quick-start path and remaining B28 human actions. Do not claim CATIA, Compile, Reference or
license PASS before real target evidence returns.
