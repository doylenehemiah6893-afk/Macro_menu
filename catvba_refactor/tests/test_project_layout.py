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
    assert "b28-target/README_TARGET_B28.md" in docs_index
    assert "2026-07-15-catvba-b28-discovery-operator-bundle.md" not in docs_index
    assert "b28-target/README_TARGET_B28.md" in status
    assert "b28-target/README_TARGET_B28.md" in resume
    assert "complete-evidence-implementation" in status
    assert "resume/state.json" in resume
    runbook = (
        ROOT / "Docs/runbooks/2026-07-15-catvba-b28-discovery-operator-bundle.md"
    ).read_text("utf-8")
    assert "状态：SUPERSEDED" in runbook
    assert "任何代码块均不可执行" in runbook
    quickstart = (
        ROOT / "Docs/runbooks/b28-target/QUICKSTART_B28.md"
    ).read_text("utf-8")
    assert "python --version" not in quickstart
    assert quickstart.index("where py") < quickstart.index("where python")
    assert "sys.implementation.name == 'cpython'" in quickstart
    assert "sys.version_info[:2] == (3, 12)" in quickstart
    assert 'set "PY312_MODE=py"' in quickstart
    assert 'set "PY312_MODE=python"' in quickstart
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


def test_repro_workflow_is_pinned_native_and_never_publishes_catvba() -> None:
    workflow = (ROOT / ".github/workflows/repro.yml").read_text("utf-8")
    action_refs = re.findall(r"uses:\s*([^\s]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref) for ref in action_refs)
    for action in ("actions/checkout", "actions/setup-python", "astral-sh/setup-uv"):
        assert any(ref.startswith(action + "@") for ref in action_refs)
    assert "windows-latest" in workflow
    assert "pull_request:" not in workflow
    assert "python-version: '3.12'" in workflow
    assert "bootstrap_resume.py" in workflow and " doctor " in workflow
    assert "git branch dev" not in workflow
    assert "py -3.12 scripts\\bootstrap_resume.py --repo-root . --state resume\\state.json" in workflow
    assert ".venv\\Scripts\\python.exe -m catvba_refactor.macro_build.cli doctor" in workflow
    assert "run-discovery.cmd --help" in workflow
    assert "target-discovery.pyz --help" in workflow
    assert "wsl" not in workflow.lower()
    assert "powershell" not in workflow.lower()
    assert "*.catvba" not in workflow.lower()
    uploads = re.findall(r"(?ms)uses:\s*actions/upload-artifact@[0-9a-f]{40}.*?(?=\n\s*- uses:|\n\s*- name:|\Z)", workflow)
    assert len(uploads) == 4
    assert all("**" not in block and "*.catvba" not in block.lower() for block in uploads)
    assert "linux-reproducibility-receipt" in workflow
    assert "windows-collector-smoke-receipt" in workflow
    assert "if-no-files-found: ignore" not in workflow
    assert "operator-bundle-candidate" not in workflow
    assert workflow.count("id: bundle") == 2
    assert workflow.count("steps.bundle.outputs.path") == 2
    assert workflow.count("steps.bundle.outputs.available == 'true'") == 2
    assert workflow.count("--snapshot-root") == 2
    assert "operator-bundle-upload.zip" not in workflow


def test_release_workflow_cannot_trigger_on_tags() -> None:
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    assert all("tags:" not in path.read_text("utf-8") for path in workflows)
    assert "历史" in (ROOT / "Docs/发版.md").read_text("utf-8")


def test_resume_documents_the_available_fail_closed_verifier() -> None:
    resume = (ROOT / "RESUME.md").read_text("utf-8")
    assert "verify_resume.py` 由下一实现任务加入" not in resume
    assert "python scripts/verify_resume.py --repo-root . --state resume/state.json --output-root" in resume
    assert "fail-closed" in resume
