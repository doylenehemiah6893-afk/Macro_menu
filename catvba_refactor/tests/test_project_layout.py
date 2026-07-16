from pathlib import Path
import json
import re
import subprocess
import tomllib

from catvba_refactor.macro_build.resume import load_resume_state

ROOT = Path(__file__).parents[2]


def test_root_project_is_the_only_python_project() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["scripts"]["macro-menu-build"] == (
        "catvba_refactor.macro_build.cli:main"
    )
    assert not (ROOT / "catvba_refactor/pyproject.toml").exists()
    assert not (ROOT / "catvba_refactor/uv.lock").exists()


def test_generated_paths_are_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "catvba_refactor/build/probe"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_vba_attributes_preserve_bytes() -> None:
    result = subprocess.run(
        ["git", "check-attr", "text", "--", "probe.bas", "probe.frx"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "probe.bas: text: unset" in result.stdout
    assert "probe.frx: text: unset" in result.stdout


def test_target_runbook_contains_every_mandatory_stop_and_command() -> None:
    runbook = ROOT / "Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md"
    text = runbook.read_text("utf-8")
    for required in (
        "Python 3.12", "禁止 Compile", "blank-project", "post-form-import",
        "post-all-import", "post-save", "post-restart", "finalize-raw",
        "恢复干净 VM", "raw/untrusted", "COLLECTOR_CAPTURE_BUSY",
        "双人复核", "不使用 WSL", "不使用 PowerShell",
    ):
        assert required in text
    for command in (
        "preflight", "init-capture", "record-environment",
        "record-entitlements", "import-reference-csv", "add-operator-record",
        "status", "finalize-raw", "certutil -hashfile",
    ):
        assert command in text
    assert "raw-discovery-capture.zip" in text
    assert not re.search(r"<[A-Z][A-Z0-9_-]*>", text)


def test_target_bundle_document_sources_and_cmd_wrapper_exist() -> None:
    required = (
        "Docs/runbooks/b28-target/README_TARGET_B28.md",
        "Docs/runbooks/b28-target/QUICKSTART_B28.md",
        "Docs/runbooks/b28-target/SECURITY_AND_REDACTION.md",
        "Docs/runbooks/b28-target/TROUBLESHOOTING.md",
        "scripts/run-discovery.cmd",
        "RESUME.md",
        "resume/state.json",
    )
    for relative in required:
        assert (ROOT / relative).is_file(), relative
    wrapper = (ROOT / "scripts/run-discovery.cmd").read_text("utf-8")
    assert "py -3.12 -c" in wrapper
    assert 'py -3.12 "%COLLECTOR%" %*' in wrapper
    assert "sys.implementation.name == 'cpython'" in wrapper
    assert "sys.version_info[:2] == (3, 12)" in wrapper
    assert 'python "%COLLECTOR%" %*' in wrapper
    assert "for /f" not in wrapper.lower()
    assert "powershell" not in wrapper.lower()
    assert "wsl" not in wrapper.lower()
    docs_index = (ROOT / "Docs/README.md").read_text("utf-8")
    status = (ROOT / "Docs/STATUS.md").read_text("utf-8")
    resume = (ROOT / "RESUME.md").read_text("utf-8")
    assert "2026-07-15-catvba-b28-discovery-operator-bundle.md" in docs_index
    assert "complete-evidence-implementation" in status
    assert "resume/state.json" in resume
    runbook = (
        ROOT / "Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md"
    ).read_text("utf-8")
    quickstart = (
        ROOT / "Docs/runbooks/b28-target/QUICKSTART_B28.md"
    ).read_text("utf-8")
    for guide in (runbook, quickstart):
        assert "python --version" not in guide
        assert guide.index("where py") < guide.index("where python")
        assert "sys.implementation.name == 'cpython'" in guide
        assert "sys.version_info[:2] == (3, 12)" in guide
        assert 'set "PY312_MODE=py"' in guide
        assert 'set "PY312_MODE=python"' in guide
    assert 'if /i "%PY312_MODE%"=="py" py -3.12 -c' in runbook
    assert 'if /i "%PY312_MODE%"=="python" python -c' in runbook
    assert "screen-redacted.redaction-review.json" in runbook
    assert "review_record_ids" in runbook
    assert "certutil-sha256.txt" in runbook
    assert "'reviewers'" not in runbook
    assert "COLLECTOR_PYTHON_312_REQUIRED" in runbook
    assert "exit 2" in runbook and "exit 4" in runbook
    old_runbook = (
        ROOT / "Docs/runbooks/2026-07-14-catvba-b28-g2-g3-core.md"
    ).read_text("utf-8")
    assert old_runbook.count("不可执行") >= 10
    assert "当前唯一 active handoff 指定的 Kit ZIP" not in old_runbook


def test_resume_state_matches_schema_and_never_claims_release() -> None:
    state = load_resume_state(ROOT / "resume/state.json", ROOT / "catvba_refactor/schemas")
    assert state["release_eligible"] is False
    assert state["active_bundle_path"] is None
    assert state["evidence_commit"] is None
    assert state["evidence_tree"] is None
    assert state["delivery_parent_commit"] is None
    assert state["last_full_test_count"] is None
    assert state["revocation_status"] == "preparation"
    assert state["next_action"] == "complete-evidence-implementation"
    assert state["gate_statuses"]["G2"] == "BLOCKED"
    assert all(state["gate_statuses"][f"G{number}"] == "BLOCKED" for number in range(2, 8))
    raw = json.loads((ROOT / "resume/state.json").read_text("utf-8"))
    assert raw == state


def test_bundle_tutorials_are_self_contained_and_fail_closed() -> None:
    docs = ROOT / "Docs/runbooks/b28-target"
    readme = (docs / "README_TARGET_B28.md").read_text("utf-8")
    quick = (docs / "QUICKSTART_B28.md").read_text("utf-8")
    security = (docs / "SECURITY_AND_REDACTION.md").read_text("utf-8")
    trouble = (docs / "TROUBLESHOOTING.md").read_text("utf-8")
    combined = "\n".join((readme, quick, security, trouble))
    for required in (
        "blank VM", "CATIA", "DSLS", "VBE", "blank-project",
        "post-form-import", "post-all-import", "post-save", "post-restart",
        "FRM", "FRX", "record-environment", "record-entitlements",
        "finalize-raw", "raw/untrusted", "恢复干净 VM",
        "redaction-review.json", "review_record_ids",
    ):
        assert required in combined
    assert "仓库主手册" not in combined
    assert 'findstr /S /I "REPLACE_"' in quick
    assert quick.count("if errorlevel 1 exit /b %ERRORLEVEL%") >= 20
    assert "编辑并人工复核" in quick
    lines = quick.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(("call run-discovery.cmd ", "copy ", "certutil -hashfile ")):
            assert lines[index + 1] == "if errorlevel 1 exit /b %ERRORLEVEL%", line


def test_quickstart_creates_each_reference_input_only_after_human_observation() -> None:
    text = (
        ROOT / "Docs/runbooks/b28-target/QUICKSTART_B28.md"
    ).read_text("utf-8")
    points = (
        ("人工阶段 A：blank-project", "blank-project"),
        ("人工阶段 B：post-form-import", "post-form-import"),
        ("人工阶段 C：post-all-import", "post-all-import"),
        ("人工阶段 D：post-save", "post-save"),
        ("人工阶段 E：post-restart", "post-restart"),
    )
    for index, (marker, point) in enumerate(points):
        marker_at = text.index(marker)
        copy_at = text.index(f'references-{point}.csv"', marker_at)
        check_at = text.index(
            f'findstr /I "REPLACE_" "%INPUT%\\references-{point}.csv"', copy_at
        )
        import_at = text.index(f"--point {point} ", check_at)
        assert marker_at < copy_at < check_at < import_at
        if index + 1 < len(points):
            assert import_at < text.index(points[index + 1][0])
    first_marker = text.index(points[0][0])
    assert "references-blank-project.csv" not in text[:first_marker]
    assert "一次性预填五点" not in text
    assert "不得复制上一点" in text
