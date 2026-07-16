import copy
import hashlib
import importlib.util
import json
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from catvba_refactor.macro_build.errors import ConfigError, EvidenceError
from catvba_refactor.macro_build import resume
from catvba_refactor.macro_build.resume import (
    APPROVED_CUTOFF,
    StrictDraft202012Validator,
    bootstrap_repository,
    doctor_repository,
    approved_repository_remote,
    load_resume_state,
    validate_raw_capture_manifest,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas"
GIT = "a" * 40
TREE = "b" * 40
SHA = "c" * 64
SHA_B = "d" * 64
UTC = "2026-07-15T18:00:00Z"
CURRENT_REMOTE_DEV = "688911522f88e2283231fb59232ea43edd3174a5"


def _validator(filename: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return StrictDraft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def valid_resume_state() -> dict:
    return {
        "schema_version": 1,
        "repository": "doylenehemiah6893-afk/Macro_menu",
        "branch": "codex/dev-review-report",
        "evidence_commit": GIT,
        "evidence_tree": TREE,
        "delivery_parent_commit": GIT,
        "approved_cutoff": "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad",
        "intake_record_path": "Docs/process/2026-07-14-initial-baseline-intake.md",
        "intake_record_digest": SHA,
        "python_requirement": "CPython 3.12",
        "uv_requirement": "uv 0.9.25",
        "lock_digest": SHA_B,
        "gate_statuses": {
            "G0": "PASS",
            "G1": "PASS",
            "G2": "BLOCKED",
            "G3": "BLOCKED",
            "G4": "BLOCKED",
            "G5": "BLOCKED",
            "G6": "BLOCKED",
            "G7": "BLOCKED",
        },
        "active_bundle_path": None,
        "bundle_digest": None,
        "active_kit_id": None,
        "kit_zip_digest": None,
        "active_handoff_id": None,
        "handoff_digest": None,
        "expiry": None,
        "revocation_status": "preparation",
        "last_full_test_count": 1306,
        "last_reproducibility_receipt": None,
        "release_eligible": False,
        "next_action": "Build and verify the B28 discovery operator bundle.",
    }


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=check, capture_output=True, text=True
    ).stdout.strip()


def _fresh_clone(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[2]
    clone = tmp_path / "fresh clone"
    subprocess.run(
        (
            "git", "clone", "--no-local", "--single-branch", "--branch",
            "codex/dev-review-report", str(source), str(clone),
        ),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        (
            "git", "fetch", str(source),
            "refs/remotes/origin/dev:refs/remotes/origin/dev",
        ),
        cwd=clone,
        check=True,
        capture_output=True,
    )
    _git(clone, "remote", "set-url", "origin", "https://github.com/doylenehemiah6893-afk/Macro_menu.git")
    state = valid_resume_state()
    state["evidence_commit"] = _git(clone, "rev-parse", "HEAD")
    state["evidence_tree"] = _git(clone, "rev-parse", "HEAD^{tree}")
    state["delivery_parent_commit"] = state["evidence_commit"]
    state["intake_record_path"] = "catvba_refactor/intake/records/2026-07-13-initial-baseline.json"
    intake = clone / state["intake_record_path"]
    state["intake_record_digest"] = hashlib.sha256(intake.read_bytes()).hexdigest()
    state["lock_digest"] = hashlib.sha256((clone / "uv.lock").read_bytes()).hexdigest()
    state_path = clone / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return clone, state_path


def _bootstrap_script_module():
    script = Path(__file__).parents[2] / "scripts/bootstrap_resume.py"
    spec = importlib.util.spec_from_file_location("bootstrap_resume_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _minimal_clone_without_cutoff(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[2]
    clone = tmp_path / "minimal clone"
    intake_relative = Path(
        "catvba_refactor/intake/records/2026-07-13-initial-baseline.json"
    )
    (clone / intake_relative).parent.mkdir(parents=True)
    shutil.copyfile(source / "uv.lock", clone / "uv.lock")
    shutil.copyfile(source / intake_relative, clone / intake_relative)
    _git(clone, "init", "--initial-branch=codex/dev-review-report")
    _git(clone, "config", "user.name", "Resume Tests")
    _git(clone, "config", "user.email", "resume@example.invalid")
    _git(clone, "add", "uv.lock", intake_relative.as_posix())
    _git(clone, "commit", "-m", "fixture: minimal clone")
    _git(
        clone,
        "remote",
        "add",
        "origin",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git",
    )
    state = valid_resume_state()
    state["evidence_commit"] = _git(clone, "rev-parse", "HEAD")
    state["evidence_tree"] = _git(clone, "rev-parse", "HEAD^{tree}")
    state["delivery_parent_commit"] = state["evidence_commit"]
    state["intake_record_path"] = intake_relative.as_posix()
    state["intake_record_digest"] = hashlib.sha256(
        (clone / intake_relative).read_bytes()
    ).hexdigest()
    state["lock_digest"] = hashlib.sha256((clone / "uv.lock").read_bytes()).hexdigest()
    state_path = clone / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return clone, state_path


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/doylenehemiah6893-afk/Macro_menu",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git",
        "git@github.com:doylenehemiah6893-afk/Macro_menu",
        "git@github.com:doylenehemiah6893-afk/Macro_menu.git",
    ],
)
def test_repository_identity_accepts_only_explicit_github_forms(remote: str):
    assert approved_repository_remote(remote)


@pytest.mark.parametrize(
    "remote",
    [
        "https://evil.example/github.com/doylenehemiah6893-afk/Macro_menu.git",
        "https://github.com@evil.example/doylenehemiah6893-afk/Macro_menu.git",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git/extra",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git?ref=dev",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git#fragment",
        "ssh://git@evil.example/github.com/doylenehemiah6893-afk/Macro_menu.git",
        "git@evil.example:github.com/doylenehemiah6893-afk/Macro_menu.git",
    ],
)
def test_repository_identity_rejects_spoofed_hosts_paths_and_suffixes(remote: str):
    assert not approved_repository_remote(remote)


@pytest.mark.parametrize(
    "failure",
    ["missing-git", "shallow", "missing-cutoff", "wrong-branch", "wrong-repo"],
)
def test_stdlib_bootstrap_rejects_invalid_clone_before_uv_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
):
    if failure == "missing-cutoff":
        clone, state_path = _minimal_clone_without_cutoff(tmp_path)
    else:
        clone, state_path = _fresh_clone(tmp_path)
    if failure == "missing-git":
        (clone / ".git").rename(clone / ".git-hidden")
    elif failure == "shallow":
        (clone / ".git/shallow").write_text(
            _git(clone, "rev-parse", "HEAD") + "\n", encoding="ascii"
        )
    elif failure == "wrong-branch":
        _git(clone, "branch", "-m", "wrong-branch")
    elif failure == "wrong-repo":
        _git(
            clone,
            "remote",
            "set-url",
            "origin",
            "https://evil.example/github.com/doylenehemiah6893-afk/Macro_menu.git",
        )

    module = _bootstrap_script_module()
    sync_calls: list[Path] = []
    monkeypatch.setattr(
        module,
        "_sync_dependencies",
        lambda root: sync_calls.append(root),
    )

    monkeypatch.setattr(module, "_running_locked_interpreter", lambda root: False)
    monkeypatch.setattr(
        module,
        "_run_locked",
        lambda root, state: pytest.fail("invalid clone must not exec"),
    )
    with pytest.raises(SystemExit):
        module._bootstrap_process(clone.resolve(), state_path.resolve())

    assert sync_calls == []


def test_bootstrap_creates_only_the_approved_local_dev_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    synced: list[Path] = []
    monkeypatch.setattr(resume, "_frozen_sync", lambda root: synced.append(root) or None)

    report = bootstrap_repository(clone, state_path)

    assert report.ok
    assert _git(clone, "rev-parse", "refs/heads/dev") == APPROVED_CUTOFF
    assert _git(clone, "rev-parse", "refs/remotes/origin/dev") == CURRENT_REMOTE_DEV
    assert synced == [clone.resolve()]


def test_bootstrap_refuses_conflicting_local_dev(tmp_path: Path):
    clone, state_path = _fresh_clone(tmp_path)
    _git(clone, "update-ref", "refs/heads/dev", CURRENT_REMOTE_DEV)

    report = bootstrap_repository(clone, state_path)

    assert not report.ok
    assert [item.code for item in report.diagnostics] == ["RESUME_BASELINE_REF_CONFLICT"]
    assert _git(clone, "rev-parse", "refs/heads/dev") == CURRENT_REMOTE_DEV


def test_bootstrap_refuses_replace_refs_without_creating_dev(tmp_path: Path):
    clone, state_path = _fresh_clone(tmp_path)
    _git(clone, "update-ref", f"refs/replace/{CURRENT_REMOTE_DEV}", CURRENT_REMOTE_DEV)

    report = bootstrap_repository(clone, state_path)

    assert [item.code for item in report.diagnostics] == ["RESUME_REPLACE_REFS_PRESENT"]
    assert _git(clone, "show-ref", "--verify", "--quiet", "refs/heads/dev", check=False) == ""


def test_doctor_reports_dirty_governed_paths_but_ignores_egg_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    monkeypatch.setattr(resume, "_frozen_sync", lambda root: None)
    assert bootstrap_repository(clone, state_path).ok
    (clone / "macro_menu.egg-info").mkdir()
    (clone / "macro_menu.egg-info/PKG-INFO").write_text("generated", encoding="utf-8")
    (clone / "Src/dirty.bas").write_text("dirty", encoding="utf-8")

    report = doctor_repository(clone, state_path, now=datetime.fromisoformat(UTC.replace("Z", "+00:00")))

    assert [item.code for item in report.diagnostics] == ["RESUME_GOVERNED_TREE_DIRTY"]


def test_doctor_rejects_dirty_tracked_non_governed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    monkeypatch.setattr(resume, "_frozen_sync", lambda root: None)
    assert bootstrap_repository(clone, state_path).ok
    (clone / "README.md").write_text("dirty", encoding="utf-8")

    report = doctor_repository(
        clone,
        state_path,
        now=datetime.fromisoformat(UTC.replace("Z", "+00:00")),
    )

    assert [item.code for item in report.diagnostics] == ["RESUME_TRACKED_TREE_DIRTY"]


def test_bootstrap_sync_failure_never_creates_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    monkeypatch.setattr(
        resume,
        "_frozen_sync",
        lambda root: resume.ResumeDiagnostic(
            "RESUME_FROZEN_SYNC_FAILED", "uv.lock", "expected failure"
        ),
    )

    report = bootstrap_repository(clone, state_path)

    assert [item.code for item in report.diagnostics] == ["RESUME_FROZEN_SYNC_FAILED"]
    assert _git(clone, "for-each-ref", "--format=%(refname)", "refs/heads/dev") == ""


def test_bootstrap_wrappers_are_thin_and_pinned_to_repo_state():
    root = Path(__file__).parents[2]
    assert (root / "scripts/bootstrap-resume.cmd").read_text(encoding="utf-8").splitlines() == [
        "@echo off",
        "setlocal",
        'py -3.12 "%~dp0bootstrap_resume.py" --repo-root "%~dp0.." --state "%~dp0..\\resume\\state.json"',
        "if errorlevel 1 exit /b %errorlevel%",
    ]
    shell = (root / "scripts/bootstrap-resume.sh").read_text(encoding="utf-8")
    assert "bootstrap_resume.py" in shell
    assert "resume/state.json" in shell
    assert "git fetch" not in shell


def test_bootstrap_python_reexecutes_with_the_locked_project_interpreter():
    source = (Path(__file__).parents[2] / "scripts/bootstrap_resume.py").read_text(
        encoding="utf-8"
    )

    assert '"Scripts" / "python.exe"' in source
    assert '"bin" / "python"' in source
    assert '"--locked"' not in source
    assert '"--no-install-project"' in source
    assert '"GIT_NO_REPLACE_OBJECTS": "1"' in source
    assert '"remote", "get-url", "origin"' in source
    assert "def _bootstrap_process" in source


def test_system_interpreter_is_not_mistaken_for_venv_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _bootstrap_script_module()
    repo_root = tmp_path / "repo"
    interpreter = repo_root / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    try:
        interpreter.symlink_to(Path(module.sys.executable))
    except OSError:
        pytest.skip("interpreter symlinks are unavailable")

    assert not module._running_locked_interpreter(repo_root)


def test_windows_runtime_path_normalization_is_case_insensitive(
):
    module = _bootstrap_script_module()

    assert module._normalized_runtime_path(
        "C:\\Work\\Repo\\.VENV", windows=True
    ) == (
        module._normalized_runtime_path("c:\\work\\repo\\.venv", windows=True)
    )


def test_bootstrap_parser_rejects_removed_locked_bypass():
    module = _bootstrap_script_module()
    with pytest.raises(SystemExit):
        module._parser().parse_args(
            ["--repo-root", ".", "--state", "state.json", "--locked"]
        )


def test_bootstrap_rechecks_after_sync_before_locked_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    module = _bootstrap_script_module()
    events: list[str] = []

    def mutate_lock(root: Path) -> None:
        events.append("sync")
        (root / "uv.lock").write_text("mutated during sync", encoding="utf-8")

    monkeypatch.setattr(module, "_sync_dependencies", mutate_lock)
    monkeypatch.setattr(
        module,
        "_run_locked",
        lambda root, state: events.append("exec") or 0,
    )

    with pytest.raises(SystemExit):
        module._bootstrap_process(clone.resolve(), state_path.resolve())

    assert events == ["sync"]


@pytest.mark.parametrize("relative", ["uv.lock", "catvba_refactor/macro_build/resume.py"])
@pytest.mark.parametrize("restore", [False, True])
def test_bootstrap_sync_mutation_is_rechecked_before_project_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    restore: bool,
):
    clone, state_path = _fresh_clone(tmp_path)
    module = _bootstrap_script_module()
    path = clone / relative
    original = path.read_bytes()
    events: list[str] = []

    def mutate(root: Path) -> None:
        events.append("sync")
        path.write_bytes(original + b"\nmutation")
        if restore:
            path.write_bytes(original)

    monkeypatch.setattr(module, "_running_locked_interpreter", lambda root: False)
    monkeypatch.setattr(module, "_sync_dependencies", mutate)
    monkeypatch.setattr(
        module,
        "_run_locked",
        lambda root, state: events.append("exec") or 0,
    )

    if restore:
        assert module._bootstrap_process(clone.resolve(), state_path.resolve()) == 0
        assert events == ["sync", "exec"]
    else:
        with pytest.raises(SystemExit):
            module._bootstrap_process(clone.resolve(), state_path.resolve())
        assert events == ["sync"]


def test_locked_interpreter_reentry_syncs_and_postflights_before_authenticated_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    module = _bootstrap_script_module()
    events: list[str] = []
    monkeypatch.setattr(
        module,
        "_stdlib_preflight",
        lambda root, state: events.append("preflight"),
    )
    monkeypatch.setattr(
        module,
        "_sync_dependencies",
        lambda root: events.append("sync"),
    )
    monkeypatch.setattr(module, "_running_locked_interpreter", lambda root: True)
    monkeypatch.setattr(
        module,
        "_run_authenticated_bootstrap",
        lambda root, state: events.append("import") or 0,
    )

    assert module._bootstrap_process(clone.resolve(), state_path.resolve()) == 0
    assert events == ["preflight", "sync", "preflight", "import"]


def test_locked_interpreter_sync_failure_never_imports_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    module = _bootstrap_script_module()
    events: list[str] = []
    monkeypatch.setattr(
        module,
        "_stdlib_preflight",
        lambda root, state: events.append("preflight"),
    )
    monkeypatch.setattr(module, "_running_locked_interpreter", lambda root: True)

    def fail_sync(root: Path) -> None:
        events.append("sync")
        raise SystemExit("sync failed")

    monkeypatch.setattr(module, "_sync_dependencies", fail_sync)
    monkeypatch.setattr(
        module,
        "_run_authenticated_bootstrap",
        lambda root, state: pytest.fail("sync failure must prevent project import"),
    )

    with pytest.raises(SystemExit, match="sync failed"):
        module._bootstrap_process(clone.resolve(), state_path.resolve())
    assert events == ["preflight", "sync"]


def test_bootstrap_expiry_after_sync_never_creates_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone, state_path = _fresh_clone(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["expiry"] = "2026-07-15T18:00:01Z"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(resume, "_frozen_sync", lambda root: None)
    times = iter(
        [
            datetime.fromisoformat("2026-07-15T18:00:00+00:00"),
            datetime.fromisoformat("2026-07-15T18:00:02+00:00"),
        ]
    )

    report = bootstrap_repository(clone, state_path, clock=lambda: next(times))

    assert [item.code for item in report.diagnostics] == ["RESUME_HANDOFF_EXPIRED"]
    assert _git(clone, "for-each-ref", "--format=%(refname)", "refs/heads/dev") == ""


@pytest.mark.parametrize("failure", ["missing", "non-utf8"])
def test_intake_read_failures_return_stable_diagnostic(
    tmp_path: Path, failure: str
):
    clone, state_path = _fresh_clone(tmp_path)
    intake = clone / "catvba_refactor/intake/records/2026-07-13-initial-baseline.json"
    if failure == "missing":
        intake.unlink()
    else:
        intake.write_bytes(b"\xff")

    report = doctor_repository(
        clone,
        state_path,
        now=datetime.fromisoformat("2026-07-15T18:00:00+00:00"),
    )

    assert "RESUME_INTAKE_READ_FAILED" in {
        item.code for item in report.diagnostics
    }


def valid_bundle_provenance() -> dict:
    return {
        "schema_version": 1,
        "repository": "doylenehemiah6893-afk/Macro_menu",
        "branch": "codex/dev-review-report",
        "evidence_commit": GIT,
        "evidence_tree": TREE,
        "approved_cutoff": "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad",
        "kit_id": "kit-0123456789abcdef0123",
        "catalog_sha256": SHA,
        "manifest_sha256": SHA_B,
        "manifest_digest": SHA,
        "kit_zip_sha256": SHA_B,
        "kit_sidecar_sha256": SHA,
        "handoff_id": "handoff-0123456789abcdef0123",
        "handoff_sha256": SHA_B,
        "handoff_created_at": UTC,
        "handoff_expires_at": "2026-07-22T18:00:00Z",
        "issuance_revocation_snapshot_sha256": SHA,
        "active_ledger_schema_version": 1,
        "active_ledger_source": "macro-menu-repository",
        "collector_source_commit": GIT,
        "collector_source_sha256": SHA_B,
        "collector_pyz_sha256": SHA,
        "python_requirement": "CPython 3.12",
        "session_skeleton_sha256": SHA_B,
        "session_skeleton_members": [
            {"path": "templates/readme.txt", "sha256": SHA, "size": 23}
        ],
        "tutorials_sha256": SHA,
        "templates_sha256": SHA_B,
        "schemas_sha256": SHA,
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
        "generation_record_id": "record-bundle-generation",
        "test_record_id": "record-target-collector-tests",
        "review_record_id": "record-bundle-independent-review",
    }


def valid_raw_capture_manifest() -> dict:
    return {
        "schema_version": 1,
        "session_id": "session-20260715-001",
        "created_at": UTC,
        "trust_level": "raw-untrusted",
        "mode": "discovery",
        "package_id": "core",
        "profile_id": "DISCOVERY",
        "bundle_id": "bundle-0123456789abcdef01234567",
        "kit_id": "kit-0123456789abcdef0123",
        "handoff_id": "handoff-0123456789abcdef0123",
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
        "members": [
            {"path": "session.json", "sha256": SHA, "size": 123},
            {"path": "references.json", "sha256": SHA_B, "size": 456},
            {"path": "SHA256SUMS", "sha256": "e" * 64, "size": 789},
        ],
    }


def valid_revocation_document() -> dict:
    return {
        "schema_version": 1,
        "captured_at": UTC,
        "source": "macro-menu-repository",
        "active_handoff_ids": ["handoff-current-example"],
        "withdrawn_handoff_ids": ["handoff-historical-example"],
    }


@pytest.mark.parametrize(
    ("filename", "document"),
    [
        ("resume-state.schema.json", valid_resume_state()),
        ("operator-bundle-provenance.schema.json", valid_bundle_provenance()),
        ("raw-capture-manifest.schema.json", valid_raw_capture_manifest()),
    ],
)
def test_delivery_state_schemas_accept_canonical_documents(filename, document):
    assert list(_validator(filename).iter_errors(document)) == []


def test_resume_state_schema_rejects_unknown_and_self_referential_fields():
    state = valid_resume_state()
    state["state_commit"] = "a" * 40
    errors = list(_validator("resume-state.schema.json").iter_errors(state))
    assert [error.validator for error in errors] == ["additionalProperties"]


def test_load_resume_state_reads_a_strict_valid_document(tmp_path: Path):
    state = valid_resume_state()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert load_resume_state(state_path, SCHEMA_DIR) == state


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"schema_version":', "RESUME_STATE_JSON_INVALID"),
        (b'{"schema_version":1,"schema_version":1}', "RESUME_STATE_JSON_INVALID"),
        (b"\xff", "RESUME_STATE_READ_ERROR"),
    ],
)
def test_load_resume_state_rejects_malformed_or_non_utf8_json(
    tmp_path: Path, payload: bytes, code: str
):
    state_path = tmp_path / "state.json"
    state_path.write_bytes(payload)
    with pytest.raises(ConfigError, match=code):
        load_resume_state(state_path, SCHEMA_DIR)


def test_load_resume_state_rejects_unknown_fields(tmp_path: Path):
    state = valid_resume_state()
    state["state_commit"] = "a" * 40
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ConfigError, match="RESUME_STATE_INVALID"):
        load_resume_state(state_path, SCHEMA_DIR)


def test_load_resume_state_rejects_missing_state_and_schema_paths(tmp_path: Path):
    with pytest.raises(ConfigError, match="RESUME_STATE_READ_ERROR"):
        load_resume_state(tmp_path / "missing.json", SCHEMA_DIR)

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(valid_resume_state()), encoding="utf-8")
    with pytest.raises(ConfigError, match="RESUME_STATE_SCHEMA_READ_ERROR"):
        load_resume_state(state_path, tmp_path / "missing-schemas")


def test_load_resume_state_rejects_malformed_schema(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    (schema_dir / "resume-state.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"invalid"}',
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(valid_resume_state()), encoding="utf-8")
    with pytest.raises(ConfigError, match="RESUME_STATE_SCHEMA_INVALID"):
        load_resume_state(state_path, schema_dir)


@pytest.mark.parametrize("reference", ["#/$defs/missing", "other.schema.json"])
def test_load_resume_state_maps_unresolvable_and_external_refs_to_schema_error(
    tmp_path: Path, reference: str
):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    schema = json.loads(
        (SCHEMA_DIR / "resume-state.schema.json").read_text(encoding="utf-8")
    )
    schema["properties"]["next_action"] = {"$ref": reference}
    (schema_dir / "resume-state.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(valid_resume_state()), encoding="utf-8")

    with pytest.raises(ConfigError, match="RESUME_STATE_SCHEMA_INVALID"):
        load_resume_state(state_path, schema_dir)


@pytest.mark.parametrize("field", ["evidence_commit", "delivery_parent_commit"])
def test_resume_state_requires_lowercase_40_hex_git_oids(field):
    state = valid_resume_state()
    state[field] = "A" * 40
    errors = list(_validator("resume-state.schema.json").iter_errors(state))
    assert errors


def test_resume_state_requires_all_gate_statuses_and_blocks_release():
    state = valid_resume_state()
    del state["gate_statuses"]["G7"]
    assert [
        error.validator
        for error in _validator("resume-state.schema.json").iter_errors(state)
    ] == ["required"]

    state = valid_resume_state()
    state["release_eligible"] = True
    assert [
        error.validator
        for error in _validator("resume-state.schema.json").iter_errors(state)
    ] == ["const"]


@pytest.mark.parametrize(
    ("filename", "document", "field"),
    [
        ("operator-bundle-provenance.schema.json", valid_bundle_provenance(), "bundle_id"),
        ("raw-capture-manifest.schema.json", valid_raw_capture_manifest(), "manifest_sha256"),
    ],
)
def test_digest_documents_reject_self_referential_fields(filename, document, field):
    mutated = copy.deepcopy(document)
    mutated[field] = SHA
    errors = list(_validator(filename).iter_errors(mutated))
    assert [error.validator for error in errors] == ["additionalProperties"]


def test_raw_capture_manifest_enforces_discovery_boundaries():
    manifest = valid_raw_capture_manifest()
    manifest["compile_status"] = "passed"
    manifest["release_eligible"] = True
    assert {
        error.validator
        for error in _validator("raw-capture-manifest.schema.json").iter_errors(manifest)
    } == {"const"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("target_case_status", "passed"), ("artifact_status", "produced")],
)
def test_bundle_provenance_enforces_discovery_execution_boundaries(field, value):
    provenance = valid_bundle_provenance()
    provenance[field] = value
    assert list(
        _validator("operator-bundle-provenance.schema.json").iter_errors(provenance)
    )


def test_raw_capture_manifest_rejects_unsafe_and_duplicate_member_paths():
    manifest = valid_raw_capture_manifest()
    manifest["members"][0]["path"] = "../session.json"
    assert list(
        _validator("raw-capture-manifest.schema.json").iter_errors(manifest)
    )

    manifest = valid_raw_capture_manifest()
    manifest["members"].append(copy.deepcopy(manifest["members"][0]))
    assert [
        error.validator
        for error in _validator("raw-capture-manifest.schema.json").iter_errors(manifest)
    ] == ["uniqueItems"]


@pytest.mark.parametrize("colliding_path", ["session.json", "SESSION.JSON"])
def test_raw_capture_manifest_semantics_reject_portable_path_collisions(
    colliding_path: str,
):
    manifest = valid_raw_capture_manifest()
    manifest["members"].append(
        {"path": colliding_path, "sha256": "e" * 64, "size": 999}
    )
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_PATH_NAMESPACE_INVALID"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_reject_file_directory_collision():
    manifest = valid_raw_capture_manifest()
    manifest["members"] = [
        {"path": "a", "sha256": SHA, "size": 1},
        {"path": "a/b", "sha256": SHA_B, "size": 2},
        {"path": "SHA256SUMS", "sha256": "e" * 64, "size": 3},
    ]
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_PATH_NAMESPACE_INVALID"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_reserves_manifest_control_path():
    manifest = valid_raw_capture_manifest()
    manifest["members"].append(
        {"path": "RAW-CAPTURE-MANIFEST.JSON", "sha256": "f" * 64, "size": 3}
    )
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_CONTROL_PATH_RESERVED"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_requires_one_canonical_sha256sums_member():
    manifest = valid_raw_capture_manifest()
    assert [item["path"] for item in manifest["members"]].count("SHA256SUMS") == 1
    assert validate_raw_capture_manifest(manifest).ok

    missing = valid_raw_capture_manifest()
    missing["members"] = [
        item for item in missing["members"] if item["path"] != "SHA256SUMS"
    ]
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID"):
        validate_raw_capture_manifest(missing)

    duplicate = valid_raw_capture_manifest()
    duplicate["members"].append(
        {"path": "SHA256SUMS", "sha256": "f" * 64, "size": 999}
    )
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID"):
        validate_raw_capture_manifest(duplicate)

    wrong_case = valid_raw_capture_manifest()
    next(
        item for item in wrong_case["members"] if item["path"] == "SHA256SUMS"
    )["path"] = "sha256sums"
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID"):
        validate_raw_capture_manifest(wrong_case)


@pytest.mark.parametrize("path", ["CON.txt", "lPt1.log"])
def test_raw_capture_manifest_semantics_rejects_windows_reserved_names(path):
    manifest = valid_raw_capture_manifest()
    manifest["members"].append({"path": path, "sha256": "e" * 64, "size": 3})
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_PATH_NAMESPACE_INVALID"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_accept_disjoint_paths():
    assert validate_raw_capture_manifest(valid_raw_capture_manifest()).ok


@pytest.mark.parametrize(
    ("filename", "document"),
    [
        ("resume-state.schema.json", valid_resume_state()),
        ("revocation-snapshot.schema.json", valid_revocation_document()),
        ("active-handoff-ledger.schema.json", valid_revocation_document()),
        ("operator-bundle-provenance.schema.json", valid_bundle_provenance()),
        ("raw-capture-manifest.schema.json", valid_raw_capture_manifest()),
    ],
)
def test_delivery_schemas_reject_float_schema_version(filename, document):
    document["schema_version"] = 1.0
    assert list(_validator(filename).iter_errors(document))
