from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build import cli
from catvba_refactor.macro_build.audit import AuditReport, PCodeSignal
from catvba_refactor.macro_build.errors import (
    ConfigError,
    EvidenceError,
    ExitCode,
    GateError,
    InfrastructureError,
    SourceError,
    VerificationError,
)
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.handoff import HandoffReceipt, HandoffRequest
from catvba_refactor.macro_build.model import (
    BuildKitInspection,
    BuildKitReceipt,
    Diagnostic,
    GeneratedSourceSet,
    InputSnapshot,
    Inventory,
    ResolvedCatalog,
    ResolvedSourceSet,
    SnapshotMode,
    ValidationReport,
    VerificationReport,
)
from catvba_refactor.macro_build.target_evidence.model import (
    ComputedOutcome,
    EvidencePhase,
    GateEvaluation,
    GateId,
    PayloadMember,
    SessionMode,
    TargetEvidenceBundleReceipt,
    TargetEvidenceReport,
    TargetSessionReceipt,
)


_EVIDENCE_COMMANDS = (
    "init-target-session",
    "validate-target-evidence",
    "evaluate-target-gate",
    "record-target-approval",
    "pack-target-evidence",
)
_TARGET_COMMANDS = ("create-target-handoff", *_EVIDENCE_COMMANDS)


def _manifest(report: ValidationReport = ValidationReport()) -> ManifestSet:
    return ManifestSet(
        project={},
        components={},
        packages={},
        tools={},
        digest="1" * 64,
        report=report,
    )


def _snapshot(*, worktree: bool = False) -> InputSnapshot:
    return InputSnapshot(
        mode=SnapshotMode.WORKTREE if worktree else SnapshotMode.CANDIDATE,
        upstream_repository="verysolecd/Macro_menu",
        upstream_ref="dev",
        upstream_commit="1" * 40,
        fork_repository="doylenehemiah6893-afk/Macro_menu",
        fork_dev_commit="1" * 40,
        work_repository="doylenehemiah6893-afk/Macro_menu",
        work_branch="codex/dev-review-report",
        work_commit="2" * 40,
        work_tree="3" * 40,
        manifest_digest="1" * 64,
        tool_version="0.1.0",
        formal_eligible=not worktree,
    )


def _diagnostic(code: str = "Z_LAST", path: str = "z/path") -> Diagnostic:
    return Diagnostic(
        code=code,
        path=path,
        message=f"message for {code}",
        details={"token": code.casefold()},
    )


def _install_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    worktree: bool = False,
    manifest_report: ValidationReport = ValidationReport(),
    inventory_report: ValidationReport = ValidationReport(),
    validation_report: ValidationReport = ValidationReport(),
) -> tuple[list[Any], ResolvedCatalog]:
    calls: list[Any] = []
    manifests = _manifest(manifest_report)
    snapshot = _snapshot(worktree=worktree)
    inventory = Inventory((), inventory_report, formal_eligible=not worktree)
    resolved = ResolvedSourceSet((), (), inventory_report)
    generated = GeneratedSourceSet((), inventory_report)
    assembled = ResolvedCatalog(snapshot, (), (), (), inventory_report)

    def load(config_dir: Path, schema_dir: Path) -> ManifestSet:
        calls.append(("load", config_dir, schema_dir))
        return manifests

    class Repository:
        def resolve_commit(self, ref: str) -> str:
            assert ref == "HEAD"
            return snapshot.work_commit

    def repository(root: Path) -> object:
        calls.append(("repo", root))
        return Repository()

    def freeze(
        repo: object,
        project: dict[str, Any],
        digest: str,
        version: str,
        worktree: bool = False,
        expected_work_commit: str | None = None,
    ) -> InputSnapshot:
        assert expected_work_commit == (None if worktree else snapshot.work_commit)
        calls.append(("freeze", worktree, version))
        return replace(snapshot, mode=SnapshotMode.WORKTREE if worktree else snapshot.mode)

    def generate(
        selected: ResolvedSourceSet,
        loaded: ManifestSet,
        frozen: InputSnapshot,
    ) -> GeneratedSourceSet:
        assert selected is resolved
        assert loaded is manifests
        assert frozen == snapshot
        calls.append("generate")
        return generated

    monkeypatch.setattr(cli, "load_and_validate_config", load, raising=False)
    monkeypatch.setattr(
        cli,
        "_load_authenticated_formal_config",
        lambda repo_root, config_dir, schema_dir: (
            load(config_dir, schema_dir),
            snapshot.work_commit,
        ),
        raising=False,
    )
    monkeypatch.setattr(cli, "GitRepository", repository, raising=False)
    monkeypatch.setattr(cli, "freeze_snapshot", freeze, raising=False)
    monkeypatch.setattr(
        cli,
        "scan_inputs",
        lambda snap, loaded, repo: calls.append("scan") or inventory,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "resolve_sources",
        lambda scanned, loaded: calls.append("resolve") or resolved,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "generate_sources",
        generate,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "assemble_catalog",
        lambda snap, selected, made, loaded: calls.append("assemble") or assembled,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "validate_catalog",
        lambda catalog: calls.append("validate") or validation_report,
        raising=False,
    )
    return calls, assembled


def test_console_help_lists_all_commands() -> None:
    help_text = cli.build_parser().format_help()
    for command in (
        "inventory",
        "check",
        "build-kit",
        "verify-kit",
        "audit-catvba",
        "doctor",
        "build-operator-bundle",
        "create-discovery-skeleton",
        *_TARGET_COMMANDS,
    ):
        assert command in help_text


def test_doctor_defaults_fail_closed_and_accepts_development_scope() -> None:
    default = cli.build_parser().parse_args(["doctor", "--state", "resume/state.json"])
    development = cli.build_parser().parse_args(
        [
            "doctor",
            "--state",
            "resume/state.json",
            "--scope",
            "development",
        ]
    )

    assert default.scope == "delivery"
    assert development.scope == "development"


def test_build_operator_bundle_cli_accepts_the_documented_inputs(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args([
        "build-operator-bundle", str(tmp_path / "primary"),
        "--compare-build-root", str(tmp_path / "comparison"),
        "--handoff", str(tmp_path / "handoff.json"),
        "--ledger", str(tmp_path / "active-ledger.json"),
        "--issuance-revocation-snapshot", str(tmp_path / "issuance.json"),
        "--session-skeleton", str(tmp_path / "skeleton"),
        "--tutorial-dir", str(tmp_path / "tutorials"),
        "--run-script", str(tmp_path / "run.cmd"),
        "--output-root", str(tmp_path / "output"),
    ])

    assert args.command == "build-operator-bundle"
    assert args.primary_build_root == tmp_path / "primary"
    assert args.compare_build_root == tmp_path / "comparison"
    assert args.output_root == tmp_path / "output"


def test_create_discovery_skeleton_cli_writes_one_exact_static_tree(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "skeleton"

    assert cli.main([
        "create-discovery-skeleton", "--output-root", str(output), "--format", "json"
    ]) == 0

    document = json.loads(capsys.readouterr().out)
    assert document["command"] == "create-discovery-skeleton"
    assert document["ok"] is True
    assert document["skeleton_dir"] == str(output)
    assert {path.name for path in output.iterdir()} == {
        "compile-result.json", "test-results.json", "artifact-manifest.json"
    }

    assert cli.main([
        "create-discovery-skeleton", "--output-root", str(output), "--format", "json"
    ]) == ExitCode.INFRASTRUCTURE
    assert json.loads(capsys.readouterr().err)["error"]["message"] == "DISCOVERY_SKELETON_OUTPUT_EXISTS"


def test_build_operator_bundle_dispatch_uses_exact_repository_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[object] = []

    def build(request: object) -> object:
        captured.append(request)
        return SimpleNamespace(
            bundle_id="bundle-" + "1" * 24,
            bundle_dir=tmp_path / "output" / ("bundle-" + "1" * 24),
            bundle_sha256="2" * 64,
            bundle_content_sha256="2" * 64,
            provenance_sha256="2" * 64,
            pyz_sha256="3" * 64,
            kit_id="kit-" + "4" * 20,
            handoff_id="handoff-example",
            active_ledger_sha256="5" * 64,
            active_ledger_captured_at="2026-07-15T12:01:00Z",
            active_ledger_source="repository-active-handoff-ledger",
        )

    monkeypatch.setattr(cli, "build_operator_bundle", build)
    handoff = tmp_path / "handoffs" / "handoff.json"
    result = cli.main([
        "build-operator-bundle", str(tmp_path / "primary"),
        "--compare-build-root", str(tmp_path / "comparison"),
        "--handoff", str(handoff),
        "--ledger", str(tmp_path / "active-ledger.json"),
        "--session-skeleton", str(tmp_path / "skeleton"),
        "--repo-root", str(tmp_path),
        "--output-root", str(tmp_path / "output"),
        "--format", "json",
    ])

    assert result == 0
    request = captured[0]
    assert request.issuance_revocation_snapshot == handoff.parent / "revocation-snapshot.json"
    assert request.tutorials == tmp_path / "Docs" / "runbooks" / "b28-target"
    assert request.run_script == tmp_path / "scripts" / "run-discovery.cmd"
    assert json.loads(capsys.readouterr().out)["active_ledger_sha256"] == "5" * 64


def test_candidate_build_rejects_external_config_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(
        ["build-kit", "--config-dir", os.fspath(tmp_path / "config"), "--format", "json"]
    )

    assert result == ExitCode.CONFIG
    assert "CONFIG_DIRECTORY_EXTERNAL" in capsys.readouterr().err


def test_candidate_build_rejects_external_schema_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(
        ["build-kit", "--schema-dir", os.fspath(tmp_path / "schemas"), "--format", "json"]
    )

    assert result == ExitCode.CONFIG
    assert "SCHEMA_DIRECTORY_EXTERNAL" in capsys.readouterr().err


def _formal_input_clone(tmp_path: Path) -> Path:
    source = Path(__file__).parents[2]
    clone = tmp_path / "formal input clone"
    subprocess.run(
        ("git", "clone", "--no-local", str(source), str(clone)),
        check=True,
        capture_output=True,
    )
    return clone


def _same_tree_alternate_commit(clone: Path) -> tuple[str, str]:
    base = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Formal Input Test",
            "-c",
            "user.email=formal-input@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "same tree alternate",
        ),
        cwd=clone,
        check=True,
        capture_output=True,
    )
    alternate = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "reset", "--hard", base),
        cwd=clone,
        check=True,
        capture_output=True,
    )
    return base, alternate


def test_formal_inputs_accept_clean_head_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone = _formal_input_clone(tmp_path)
    cli._authenticate_formal_inputs(
        clone,
        clone / "catvba_refactor/config",
        clone / "catvba_refactor/schemas",
    )
    monkeypatch.chdir(clone)
    cli._authenticate_formal_inputs(
        Path("."), Path("catvba_refactor/config"), Path("catvba_refactor/schemas")
    )


def test_formal_config_pins_one_commit_across_successive_blob_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone = _formal_input_clone(tmp_path)
    base, alternate = _same_tree_alternate_commit(clone)
    original = cli.GitRepository.read_blob
    commits: list[str] = []

    def move_head_during_reads(repository, commit: str, path: str) -> bytes:
        commits.append(commit)
        result = original(repository, commit, path)
        if len(commits) == 2:
            subprocess.run(
                ("git", "update-ref", "HEAD", alternate),
                cwd=clone,
                check=True,
                capture_output=True,
            )
        return result

    monkeypatch.setattr(cli.GitRepository, "read_blob", move_head_during_reads)
    with pytest.raises(ConfigError, match="FORMAL_INPUT_HEAD_CHANGED"):
        cli._load_authenticated_formal_config(
            clone,
            clone / "catvba_refactor/config",
            clone / "catvba_refactor/schemas",
        )

    assert commits
    assert set(commits) == {base}


def test_formal_config_rejects_head_move_after_load_before_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clone = _formal_input_clone(tmp_path)
    _base, alternate = _same_tree_alternate_commit(clone)
    original = cli._load_authenticated_formal_config

    def load_then_move(repo_root: Path, config_dir: Path, schema_dir: Path):
        result = original(repo_root, config_dir, schema_dir)
        subprocess.run(
            ("git", "update-ref", "HEAD", alternate),
            cwd=clone,
            check=True,
            capture_output=True,
        )
        return result

    monkeypatch.setattr(cli, "_load_authenticated_formal_config", load_then_move)
    args = cli.build_parser().parse_args(
        ["--repo-root", os.fspath(clone), "inventory"]
    )
    with pytest.raises(ConfigError, match="FORMAL_INPUT_HEAD_CHANGED"):
        cli._load_source_context(args, worktree=False)


@pytest.mark.parametrize(
    "mutation",
    ["directory-symlink", "file-symlink", "dirty-file", "untracked-file"],
)
def test_formal_inputs_reject_links_and_dirty_namespaces(
    tmp_path: Path, mutation: str
):
    clone = _formal_input_clone(tmp_path)
    config = clone / "catvba_refactor/config"
    schemas = clone / "catvba_refactor/schemas"
    if mutation == "directory-symlink":
        moved = tmp_path / "moved config"
        config.rename(moved)
        try:
            config.symlink_to(moved, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlinks are unavailable")
    elif mutation == "file-symlink":
        target = tmp_path / "project.json"
        shutil.copyfile(config / "project.json", target)
        (config / "project.json").unlink()
        try:
            (config / "project.json").symlink_to(target)
        except OSError:
            pytest.skip("file symlinks are unavailable")
    elif mutation == "dirty-file":
        (config / "project.json").write_text("{}\n", encoding="utf-8")
    else:
        (schemas / "unexpected.schema.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="FORMAL_INPUTS_UNTRUSTED"):
        cli._authenticate_formal_inputs(clone, config, schemas)


def _target_command_arguments(
    command: str,
    tmp_path: Path,
    *,
    include_output_root: bool = True,
) -> list[str]:
    output = ["--output-root", os.fspath(tmp_path / "target output")]
    arguments = {
        "create-target-handoff": [
            "create-target-handoff",
            "primary build",
            "--compare-build-root",
            "comparison build",
            "--purpose",
            "discovery",
            "--revocation-snapshot",
            os.fspath(tmp_path / "revocations.json"),
            "--prepared-record-id",
            "record-handoff-prepared",
            "--review-record-id",
            "record-handoff-reviewed",
            "--expires-at",
            "2026-07-21T12:00:00Z",
        ],
        "init-target-session": [
            "init-target-session",
            "kit.zip",
            "--mode",
            "g2",
            "--package",
            "core",
            "--profile",
            "P-AB3",
            "--handoff",
            "formal-handoff.json",
            "--revocation-ledger",
            "active-handoff-ledger.json",
            "--session-id",
            "session-cli-contract",
        ],
        "validate-target-evidence": [
            "validate-target-evidence",
            "capture",
            "--kit",
            "kit.zip",
            "--phase",
            "capture",
        ],
        "evaluate-target-gate": [
            "evaluate-target-gate",
            "capture",
            "--gate",
            "G2",
            "--kit",
            "kit.zip",
        ],
        "record-target-approval": [
            "record-target-approval",
            "capture",
            "--kit",
            "kit.zip",
            "--gate-receipt",
            "gate-receipt.json",
            "--scope",
            "gate",
            "--status",
            "rejected",
            "--reviewer-role",
            "independent-reviewer",
            "--review-record-id",
            "record-independent-review",
            "--approved-at",
            "2026-07-14T13:00:00Z",
        ],
        "pack-target-evidence": [
            "pack-target-evidence",
            "capture",
            "--kit",
            "kit.zip",
            "--gate-receipt",
            "gate-receipt.json",
            "--approval",
            "approval.json",
        ],
    }[command]
    if include_output_root and command != "validate-target-evidence":
        arguments.extend(output)
    return arguments


@pytest.mark.parametrize("command", _TARGET_COMMANDS)
@pytest.mark.parametrize("position", ("before", "after"))
def test_target_commands_accept_global_options_before_or_after_subcommand(
    command: str,
    position: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revocations = tmp_path / "revocations.json"
    revocations.write_bytes(b"{}\n")
    captured: list[argparse.Namespace] = []
    monkeypatch.setattr(
        cli,
        "dispatch",
        lambda args: captured.append(args) or int(ExitCode.SUCCESS),
    )
    global_options = [
        "--repo-root",
        os.fspath(tmp_path / "repo"),
        "--config-dir",
        os.fspath(tmp_path / "config"),
        "--schema-dir",
        os.fspath(tmp_path / "schemas"),
        "--output-root",
        os.fspath(tmp_path / "global output"),
        "--format",
        "json",
    ]
    command_arguments = _target_command_arguments(
        command, tmp_path, include_output_root=False
    )
    arguments = (
        global_options + command_arguments
        if position == "before"
        else command_arguments + global_options
    )

    assert cli.main(arguments) == 0
    assert len(captured) == 1
    assert captured[0].command == command
    assert captured[0].schema_dir == tmp_path / "schemas"
    assert captured[0].output_root == tmp_path / "global output"
    assert captured[0].format == "json"


@pytest.mark.parametrize(
    ("command", "option", "bad_value"),
    [
        ("init-target-session", "--mode", "G2"),
        ("init-target-session", "--package", "fleet-spa"),
        ("init-target-session", "--profile", "P-UNKNOWN"),
        ("validate-target-evidence", "--phase", "draft"),
        ("evaluate-target-gate", "--gate", "g2"),
        ("record-target-approval", "--scope", "decision"),
        ("record-target-approval", "--status", "pending"),
    ],
)
def test_target_commands_reject_unknown_enum_values_as_usage_errors(
    command: str,
    option: str,
    bad_value: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = _target_command_arguments(command, tmp_path)
    arguments[arguments.index(option) + 1] = bad_value

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    error_message = capsys.readouterr().err.rsplit("error:", 1)[-1]
    assert option in error_message
    assert bad_value in error_message


@pytest.mark.parametrize(
    "command",
    (
        "create-target-handoff",
        "init-target-session",
        "evaluate-target-gate",
        "record-target-approval",
        "pack-target-evidence",
    ),
)
def test_target_mutating_commands_require_an_explicit_output_root(
    command: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = _target_command_arguments(
        command, tmp_path, include_output_root=False
    )

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    error_message = capsys.readouterr().err.rsplit("error:", 1)[-1]
    assert command in error_message
    assert "requires --output-root" in error_message


@pytest.mark.parametrize(
    ("command", "option"),
    [
        ("create-target-handoff", "--compare-build-root"),
        ("init-target-session", "--profile"),
        ("validate-target-evidence", "--phase"),
        ("evaluate-target-gate", "--gate"),
        ("record-target-approval", "--status"),
        ("pack-target-evidence", "--approval"),
    ],
)
def test_target_commands_reject_abbreviated_scalar_options(
    command: str,
    option: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = _target_command_arguments(command, tmp_path)
    index = arguments.index(option)
    abbreviation = option[:-1]
    arguments[index] = abbreviation

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    error_message = capsys.readouterr().err.rsplit("error:", 1)[-1]
    assert abbreviation in error_message


_TARGET_SCALAR_OPTIONS = {
    "init-target-session": {
        "--mode": "g2",
        "--package": "core",
        "--profile": "P-AB3",
        "--handoff": "formal-handoff.json",
        "--revocation-ledger": "active-handoff-ledger.json",
        "--prerequisite-evidence": "g2-evidence.zip",
        "--session-id": "session-cli-contract",
        "--output-root": "target-output",
    },
    "validate-target-evidence": {
        "--kit": "kit.zip",
        "--phase": "capture",
    },
    "evaluate-target-gate": {
        "--gate": "G2",
        "--kit": "kit.zip",
        "--output-root": "target-output",
    },
    "record-target-approval": {
        "--kit": "kit.zip",
        "--gate-receipt": "gate-receipt.json",
        "--scope": "gate",
        "--status": "rejected",
        "--reviewer-role": "independent-reviewer",
        "--review-record-id": "record-independent-review",
        "--approved-at": "2026-07-14T13:00:00Z",
        "--output-root": "target-output",
    },
    "pack-target-evidence": {
        "--kit": "kit.zip",
        "--gate-receipt": "gate-receipt.json",
        "--approval": "approval.json",
        "--output-root": "target-output",
    },
}


@pytest.mark.parametrize(
    ("command", "option", "value"),
    [
        (command, option, value)
        for command, options in _TARGET_SCALAR_OPTIONS.items()
        for option, value in options.items()
    ],
)
def test_evidence_commands_reject_every_duplicate_scalar_option(
    command: str,
    option: str,
    value: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = _target_command_arguments(command, tmp_path)
    if option in arguments:
        arguments.extend((option, value))
    else:
        arguments.extend((option, value, option, value))

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    error_message = capsys.readouterr().err.rsplit("error:", 1)[-1]
    assert f"{option} may be specified at most once" in error_message


def _authenticated_kit() -> BuildKitInspection:
    return BuildKitInspection(
        files=(),
        kit_id="kit-0123456789abcdef0123",
        catalog_sha256="a" * 64,
        manifest_sha256="b" * 64,
        manifest_digest="c" * 64,
        upstream_commit="1" * 40,
        fork_dev_commit="2" * 40,
        work_commit="3" * 40,
        work_tree="4" * 40,
        work_branch="codex/dev-review-report",
        canonical_zip_sha256="d" * 64,
        report=VerificationReport(True, ()),
    )


def _install_authenticated_kit(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[BuildKitInspection, list[Path]]:
    inspection = _authenticated_kit()
    inspected: list[Path] = []
    monkeypatch.setattr(
        cli,
        "inspect_build_kit",
        lambda path: inspected.append(path) or inspection,
        raising=False,
    )
    return inspection, inspected


def test_init_target_session_dispatches_one_authenticated_kit_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection, inspected = _install_authenticated_kit(monkeypatch)
    calls: list[tuple[Any, ...]] = []

    def initialize(
        kit: BuildKitInspection,
        handoff: Path,
        output_root: Path,
        **options: Any,
    ) -> TargetSessionReceipt:
        calls.append((kit, handoff, output_root, options))
        return TargetSessionReceipt(
            session_id="session-cli-contract",
            session_dir=os.fspath(output_root / "target-session-session-cli-contract"),
            mode=SessionMode.G2,
            kit_id=inspection.kit_id or "",
            evidence_payload_digest="e" * 64,
        )

    monkeypatch.setattr(cli, "init_target_session", initialize, raising=False)
    arguments = _target_command_arguments("init-target-session", tmp_path)
    arguments.extend(
        ("--schema-dir", os.fspath(tmp_path / "schemas"), "--format", "json")
    )

    assert cli.main(arguments) == 0
    assert inspected == [Path("kit.zip")]
    assert calls == [
        (
            inspection,
            Path("formal-handoff.json"),
            tmp_path / "target output",
            {
                "mode": SessionMode.G2,
                "package_id": "core",
                "profile_id": "P-AB3",
                "schema_dir": tmp_path / "schemas" / "target_evidence",
                "revocation_ledger": Path("active-handoff-ledger.json"),
                "prerequisite_evidence": None,
                "session_id": "session-cli-contract",
            },
        )
    ]
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "command": "init-target-session",
        "diagnostics": [],
        "evidence_payload_digest": "e" * 64,
        "kit_id": inspection.kit_id,
        "mode": "g2",
        "ok": True,
        "session_dir": os.fspath(
            tmp_path / "target output" / "target-session-session-cli-contract"
        ),
        "session_id": "session-cli-contract",
    }


def test_validate_target_evidence_dispatches_and_emits_the_domain_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection, inspected = _install_authenticated_kit(monkeypatch)
    calls: list[tuple[Any, ...]] = []
    member = PayloadMember("session.json", "e" * 64, 123)

    def validate(
        evidence: Path,
        kit: BuildKitInspection,
        **options: Any,
    ) -> TargetEvidenceReport:
        calls.append((evidence, kit, options))
        return TargetEvidenceReport(
            EvidencePhase.CAPTURE,
            "session-cli-contract",
            "f" * 64,
            (member,),
            (),
        )

    monkeypatch.setattr(cli, "validate_target_evidence", validate, raising=False)
    arguments = _target_command_arguments("validate-target-evidence", tmp_path)
    arguments.extend(
        ("--schema-dir", os.fspath(tmp_path / "schemas"), "--format", "json")
    )

    assert cli.main(arguments) == 0
    assert inspected == [Path("kit.zip")]
    assert calls == [
        (
            Path("capture"),
            inspection,
            {
                "phase": EvidencePhase.CAPTURE,
                "schema_dir": tmp_path / "schemas" / "target_evidence",
            },
        )
    ]
    assert json.loads(capsys.readouterr().out) == {
        "command": "validate-target-evidence",
        "diagnostics": [],
        "evidence_payload_digest": "f" * 64,
        "ok": True,
        "payload_members": [
            {"path": "session.json", "sha256": "e" * 64, "size": 123}
        ],
        "phase": "capture",
        "session_id": "session-cli-contract",
    }


def test_invalid_evidence_report_is_stdout_and_exit_six(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authenticated_kit(monkeypatch)
    finding = _diagnostic("TARGET_EVIDENCE_BINDING_MISMATCH", "session.json")
    monkeypatch.setattr(
        cli,
        "validate_target_evidence",
        lambda *args, **kwargs: TargetEvidenceReport(
            EvidencePhase.CAPTURE,
            "session-cli-contract",
            None,
            (),
            (finding,),
        ),
        raising=False,
    )
    arguments = _target_command_arguments("validate-target-evidence", tmp_path)
    arguments.extend(("--format", "json"))

    assert cli.main(arguments) == 6
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    assert document["command"] == "validate-target-evidence"
    assert document["ok"] is False
    assert document["diagnostics"] == [
        {
            "code": finding.code,
            "details": finding.details,
            "message": finding.message,
            "path": finding.path,
        }
    ]


@pytest.mark.parametrize(
    ("outcome", "reason", "expected_exit"),
    [
        (ComputedOutcome.ELIGIBLE, "eligible", ExitCode.SUCCESS),
        (ComputedOutcome.FAIL, "compile-failed", ExitCode.GATE),
        (ComputedOutcome.BLOCKED, "discovery-only", ExitCode.GATE),
    ],
)
def test_evaluate_target_gate_dispatches_and_classifies_normal_outcomes(
    outcome: ComputedOutcome,
    reason: str,
    expected_exit: ExitCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection, inspected = _install_authenticated_kit(monkeypatch)
    calls: list[tuple[Any, ...]] = []
    receipt_path = tmp_path / "target output" / "gate-receipt.json"

    def evaluate(
        capture: Path,
        kit: BuildKitInspection,
        output_root: Path,
        **options: Any,
    ) -> GateEvaluation:
        calls.append((capture, kit, output_root, options))
        return GateEvaluation(
            GateId.G2,
            outcome,
            reason,
            "e" * 64,
            os.fspath(receipt_path),
            "f" * 64,
            (),
        )

    monkeypatch.setattr(cli, "evaluate_target_gate", evaluate, raising=False)
    arguments = _target_command_arguments("evaluate-target-gate", tmp_path)
    arguments.extend(
        ("--schema-dir", os.fspath(tmp_path / "schemas"), "--format", "json")
    )

    assert cli.main(arguments) == int(expected_exit)
    assert inspected == [Path("kit.zip")]
    assert calls == [
        (
            Path("capture"),
            inspection,
            tmp_path / "target output",
            {
                "gate_id": GateId.G2,
                "schema_dir": tmp_path / "schemas" / "target_evidence",
            },
        )
    ]
    document = json.loads(capsys.readouterr().out)
    assert document["command"] == "evaluate-target-gate"
    assert document["ok"] is (outcome is ComputedOutcome.ELIGIBLE)
    assert document["computed_outcome"] == outcome.value
    assert document["reason"] == reason
    assert document["receipt_path"] == os.fspath(receipt_path)
    assert document["receipt_sha256"] == "f" * 64


def test_record_target_approval_dispatches_rejected_decision_and_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection, inspected = _install_authenticated_kit(monkeypatch)
    calls: list[tuple[Any, ...]] = []
    approval_path = tmp_path / "target output" / "approval-decision.json"

    def record(
        capture: Path,
        kit: BuildKitInspection,
        gate_receipt: Path,
        output_root: Path,
        **options: Any,
    ) -> Path:
        calls.append((capture, kit, gate_receipt, output_root, options))
        return approval_path

    monkeypatch.setattr(cli, "record_target_approval", record, raising=False)
    arguments = _target_command_arguments("record-target-approval", tmp_path)
    arguments.extend(
        ("--schema-dir", os.fspath(tmp_path / "schemas"), "--format", "json")
    )

    assert cli.main(arguments) == 0
    assert inspected == [Path("kit.zip")]
    assert calls == [
        (
            Path("capture"),
            inspection,
            Path("gate-receipt.json"),
            tmp_path / "target output",
            {
                "scope": "gate",
                "status": "rejected",
                "reviewer_role": "independent-reviewer",
                "review_record_id": "record-independent-review",
                "approved_at": "2026-07-14T13:00:00Z",
                "schema_dir": tmp_path / "schemas" / "target_evidence",
            },
        )
    ]
    assert json.loads(capsys.readouterr().out) == {
        "approval_id": "approval-decision",
        "approval_path": os.fspath(approval_path),
        "approval_status": "rejected",
        "command": "record-target-approval",
        "diagnostics": [],
        "ok": True,
    }


def test_pack_target_evidence_dispatches_and_emits_bundle_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection, inspected = _install_authenticated_kit(monkeypatch)
    calls: list[tuple[Any, ...]] = []
    output = tmp_path / "target output"

    def pack(
        capture: Path,
        kit: BuildKitInspection,
        gate_receipt: Path,
        approval: Path,
        output_root: Path,
        **options: Any,
    ) -> TargetEvidenceBundleReceipt:
        calls.append((capture, kit, gate_receipt, approval, output_root, options))
        return TargetEvidenceBundleReceipt(
            "session-cli-contract",
            os.fspath(output / "target-session-session-cli-contract"),
            os.fspath(output / "target-session-session-cli-contract.zip"),
            "e" * 64,
            "f" * 64,
            "a" * 64,
        )

    monkeypatch.setattr(cli, "pack_target_evidence", pack, raising=False)
    arguments = _target_command_arguments("pack-target-evidence", tmp_path)
    arguments.extend(
        ("--schema-dir", os.fspath(tmp_path / "schemas"), "--format", "json")
    )

    assert cli.main(arguments) == 0
    assert inspected == [Path("kit.zip")]
    assert calls == [
        (
            Path("capture"),
            inspection,
            Path("gate-receipt.json"),
            Path("approval.json"),
            output,
            {"schema_dir": tmp_path / "schemas" / "target_evidence"},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {
        "bundle_content_digest": "a" * 64,
        "bundle_dir": os.fspath(output / "target-session-session-cli-contract"),
        "command": "pack-target-evidence",
        "diagnostics": [],
        "evidence_payload_digest": "f" * 64,
        "ok": True,
        "session_id": "session-cli-contract",
        "zip_path": os.fspath(output / "target-session-session-cli-contract.zip"),
        "zip_sha256": "e" * 64,
    }


def test_invalid_authenticated_kit_maps_to_verification_error_before_domain_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finding = _diagnostic("KIT_HASH_MISMATCH", "catalog.json")
    invalid = replace(
        _authenticated_kit(), report=VerificationReport(False, (finding,))
    )
    monkeypatch.setattr(cli, "inspect_build_kit", lambda path: invalid, raising=False)
    monkeypatch.setattr(
        cli,
        "init_target_session",
        lambda *args, **kwargs: pytest.fail("invalid Kit must stop before dispatch"),
        raising=False,
    )
    arguments = _target_command_arguments("init-target-session", tmp_path)
    arguments.extend(("--format", "json"))

    assert cli.main(arguments) == 5
    captured = capsys.readouterr()
    assert not captured.out
    document = json.loads(captured.err)
    assert document["command"] == "init-target-session"
    assert document["error"]["exit_code"] == 5
    assert document["error"]["type"] == VerificationError.__name__


@pytest.mark.parametrize(
    ("error", "expected_exit"),
    [
        (InfrastructureError("TARGET_EVIDENCE_PUBLISH_FAILED"), ExitCode.INFRASTRUCTURE),
        (EvidenceError("TARGET_EVIDENCE_CAPTURE_INVALID"), ExitCode.EVIDENCE),
    ],
)
def test_target_domain_errors_remain_canonical_stderr_errors(
    error: Exception,
    expected_exit: ExitCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authenticated_kit(monkeypatch)
    monkeypatch.setattr(
        cli,
        "pack_target_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
        raising=False,
    )
    arguments = _target_command_arguments("pack-target-evidence", tmp_path)
    arguments.extend(("--format", "json"))

    assert cli.main(arguments) == int(expected_exit)
    captured = capsys.readouterr()
    assert not captured.out
    document = json.loads(captured.err)
    assert document["command"] == "pack-target-evidence"
    assert document["error"]["exit_code"] == int(expected_exit)


def test_create_target_handoff_forwards_exact_frozen_request_and_emits_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    revocations = tmp_path / "revocation snapshot.json"
    supersedes = tmp_path / "discovery handoff.json"
    revocation_bytes = b'{"schema_version":1}\n'
    supersedes_bytes = b'{"handoff_id":"handoff-old"}\n'
    revocations.write_bytes(revocation_bytes)
    supersedes.write_bytes(supersedes_bytes)
    output = tmp_path / "detached handoffs"
    calls: list[tuple[Any, ...]] = []

    def issue(
        primary: Path,
        comparison: Path,
        request: HandoffRequest,
        output_root: Path,
    ) -> HandoffReceipt:
        calls.append((primary, comparison, request, output_root))
        return HandoffReceipt(
            handoff_id="handoff-0123456789abcdef0123",
            handoff_path=os.fspath(output / "handoff-0123456789abcdef0123.json"),
            handoff_sha256="a" * 64,
            kit_id="kit-0123456789abcdef0123",
            kit_zip_sha256="b" * 64,
        )

    monkeypatch.setattr(cli, "issue_target_handoff", issue, raising=False)
    monkeypatch.setattr(cli, "_current_utc", lambda: "2026-07-14T12:00:00Z")
    result = cli.main(
        [
            "create-target-handoff",
            "primary root",
            "--compare-build-root",
            "comparison root",
            "--purpose",
            "formal",
            "--supersedes-handoff",
            os.fspath(supersedes),
            "--revocation-snapshot",
            os.fspath(revocations),
            "--prepared-record-id",
            "record-handoff-prepared",
            "--review-record-id",
            "record-handoff-reviewed",
            "--expires-at",
            "2026-07-21T12:00:00Z",
            "--output-root",
            os.fspath(output),
            "--format",
            "json",
        ]
    )

    assert result == 0
    assert calls == [
        (
            Path("primary root"),
            Path("comparison root"),
            HandoffRequest(
                purpose="formal",
                created_at="2026-07-14T12:00:00Z",
                expires_at="2026-07-21T12:00:00Z",
                revocation_snapshot=revocation_bytes,
                prepared_record_id="record-handoff-prepared",
                review_record_id="record-handoff-reviewed",
                supersedes_handoff=supersedes_bytes,
            ),
            output,
        )
    ]
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "command": "create-target-handoff",
        "diagnostics": [],
        "handoff_id": "handoff-0123456789abcdef0123",
        "handoff_path": os.fspath(
            output / "handoff-0123456789abcdef0123.json"
        ),
        "handoff_sha256": "a" * 64,
        "kit_id": "kit-0123456789abcdef0123",
        "kit_zip_sha256": "b" * 64,
        "ok": True,
    }


def _handoff_arguments(tmp_path: Path) -> list[str]:
    revocations = tmp_path / "revocations.json"
    revocations.write_bytes(b"{}\n")
    return [
        "create-target-handoff",
        "primary",
        "--compare-build-root",
        "comparison",
        "--purpose",
        "discovery",
        "--revocation-snapshot",
        os.fspath(revocations),
        "--prepared-record-id",
        "record-prepared",
        "--review-record-id",
        "record-reviewed",
        "--expires-at",
        "2026-07-21T12:00:00Z",
        "--output-root",
        os.fspath(tmp_path / "output"),
    ]


def test_create_target_handoff_requires_output_root_after_parsing(
    tmp_path: Path,
) -> None:
    arguments = _handoff_arguments(tmp_path)
    index = arguments.index("--output-root")
    del arguments[index : index + 2]

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


def test_create_target_handoff_rejects_abbreviated_scalar_options(
    tmp_path: Path,
) -> None:
    arguments = _handoff_arguments(tmp_path)
    arguments[arguments.index("--compare-build-root")] = "--compare-build"

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "option",
    [
        "--compare-build-root",
        "--purpose",
        "--revocation-snapshot",
        "--prepared-record-id",
        "--review-record-id",
        "--expires-at",
        "--output-root",
    ],
)
def test_create_target_handoff_rejects_duplicate_scalar_options(
    tmp_path: Path, option: str
) -> None:
    arguments = _handoff_arguments(tmp_path)
    value = arguments[arguments.index(option) + 1]
    arguments.extend((option, value))

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


def test_create_target_handoff_rejects_duplicate_supersedes_option(
    tmp_path: Path,
) -> None:
    arguments = _handoff_arguments(tmp_path)
    arguments[arguments.index("discovery")] = "formal"
    supersedes = tmp_path / "old handoff.json"
    supersedes.write_bytes(b"{}\n")
    arguments.extend(
        (
            "--supersedes-handoff",
            os.fspath(supersedes),
            "--supersedes-handoff",
            os.fspath(supersedes),
        )
    )

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


def test_unknown_arguments_remain_argparse_usage_errors() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["inventory", "--unknown"])

    assert error.value.code == 2


def test_exit_code_values_and_error_boundaries_are_stable() -> None:
    assert [int(code) for code in ExitCode] == [0, 2, 3, 4, 5, 6, 7]
    assert EvidenceError.exit_code is ExitCode.EVIDENCE
    assert GateError.exit_code is ExitCode.GATE


@pytest.mark.parametrize(
    "argv",
    [
        ["--for", "json", "inventory"],
        ["inventory", "--work"],
        ["inventory", "--format", "json", "--format", "text"],
    ],
)
def test_abbreviated_or_duplicate_options_are_usage_errors(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(argv)

    assert error.value.code == 2


def test_inventory_worktree_json_uses_repo_relative_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, _catalog = _install_pipeline(monkeypatch, worktree=True)

    result = cli.main(
        ["inventory", "--worktree", "--repo-root", os.fspath(tmp_path), "--format", "json"]
    )

    assert result == 0
    document = json.loads(capsys.readouterr().out)
    assert document["command"] == "inventory"
    assert document["ok"] is True
    assert document["formal_eligible"] is False
    assert document["diagnostics"] == []
    assert ("load", tmp_path / "catvba_refactor/config", tmp_path / "catvba_refactor/schemas") in calls
    assert ("repo", tmp_path) in calls
    assert any(call[:2] == ("freeze", True) for call in calls if isinstance(call, tuple))


@pytest.mark.parametrize(
    "argv",
    [
        ["--format", "json", "inventory", "--worktree"],
        ["inventory", "--worktree", "--format", "json"],
    ],
)
def test_global_format_is_accepted_before_or_after_subcommand(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_pipeline(monkeypatch, worktree=True)

    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["command"] == "inventory"


def test_manifest_report_uses_config_exit_and_stops_before_git(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finding = _diagnostic("INVALID_SCHEMA", "components.json")
    calls, _catalog = _install_pipeline(
        monkeypatch, manifest_report=ValidationReport((finding,))
    )

    result = cli.main(["--format", "json", "check"])

    assert result == 2
    document = json.loads(capsys.readouterr().out)
    assert document["diagnostics"][0]["code"] == "INVALID_SCHEMA"
    assert not any(call[0] == "repo" for call in calls if isinstance(call, tuple))


def test_inventory_source_diagnostics_are_sorted_and_exit_three(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = ValidationReport(
        (_diagnostic("Z_LAST", "z"), _diagnostic("A_FIRST", "a"))
    )
    _install_pipeline(monkeypatch, inventory_report=report)

    result = cli.main(["--format", "json", "inventory"])

    assert result == 3
    document = json.loads(capsys.readouterr().out)
    assert [item["code"] for item in document["diagnostics"]] == [
        "A_FIRST",
        "Z_LAST",
    ]


def test_check_runs_complete_chain_but_never_stages(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, _catalog = _install_pipeline(monkeypatch, worktree=True)
    monkeypatch.setattr(
        cli,
        "stage_build_kit",
        lambda *args: pytest.fail("check must not stage a Kit"),
        raising=False,
    )

    result = cli.main(["check", "--worktree", "--format", "json"])

    assert result == 0
    assert calls[-5:] == ["scan", "resolve", "generate", "assemble", "validate"]
    assert json.loads(capsys.readouterr().out)["formal_eligible"] is False


def test_build_kit_passes_validated_catalog_and_emits_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, assembled = _install_pipeline(monkeypatch)
    validated = ValidationReport()
    monkeypatch.setattr(
        cli,
        "validate_catalog",
        lambda catalog: calls.append("validate") or validated,
        raising=False,
    )
    staged: list[ResolvedCatalog] = []

    def stage(catalog: ResolvedCatalog, output_root: Path) -> BuildKitReceipt:
        calls.append(("stage", output_root))
        staged.append(catalog)
        return BuildKitReceipt(
            "kit-" + "a" * 20,
            os.fspath(output_root / ("kit-" + "a" * 20)),
            os.fspath(output_root / ("kit-" + "a" * 20 + ".zip")),
            "b" * 64,
            "c" * 64,
        )

    monkeypatch.setattr(cli, "stage_build_kit", stage, raising=False)

    result = cli.main(
        [
            "build-kit",
            "--repo-root",
            os.fspath(tmp_path),
            "--output-root",
            os.fspath(tmp_path / "out"),
            "--format",
            "json",
        ]
    )

    assert result == 0
    assert staged == [replace(assembled, report=validated)]
    assert ("stage", tmp_path / "out") in calls
    document = json.loads(capsys.readouterr().out)
    assert document["kit_id"] == "kit-" + "a" * 20
    assert document["compile_status"] == "not-run"
    assert document["release_eligible"] is False


def test_build_kit_validation_failure_never_calls_staging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finding = _diagnostic("POLICY", "source.bas")
    _install_pipeline(
        monkeypatch, validation_report=ValidationReport((finding,))
    )
    monkeypatch.setattr(
        cli,
        "stage_build_kit",
        lambda *args: pytest.fail("invalid catalog must not be staged"),
        raising=False,
    )

    assert cli.main(["--format", "json", "build-kit"]) == 3
    document = json.loads(capsys.readouterr().out)
    assert document["diagnostics"][0]["code"] == "POLICY"


def test_build_kit_source_failure_does_not_create_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_pipeline(monkeypatch)
    output = tmp_path / "dist"
    monkeypatch.setattr(
        cli,
        "stage_build_kit",
        lambda catalog, root: (_ for _ in ()).throw(
            SourceError("NO_BUILDABLE_COMPONENTS")
        ),
        raising=False,
    )

    result = cli.main(
        ["--format", "json", "--output-root", os.fspath(output), "build-kit"]
    )

    assert result == 3
    assert not output.exists()
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["exit_code"] == 3
    assert error["error"]["message"] == "NO_BUILDABLE_COMPONENTS"


def test_verify_mismatch_has_text_json_diagnostic_parity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finding = _diagnostic("KIT_HASH_MISMATCH", "catalog.json")
    monkeypatch.setattr(
        cli,
        "verify_build_kit",
        lambda path: VerificationReport(False, (finding,)),
        raising=False,
    )

    assert cli.main(["--format", "json", "verify-kit", "kit"]) == 5
    json_output = json.loads(capsys.readouterr().out)
    assert cli.main(["verify-kit", "kit", "--format", "text"]) == 5
    text_output = capsys.readouterr().out

    assert json_output["diagnostics"] == [
        {
            "code": finding.code,
            "details": finding.details,
            "message": finding.message,
            "path": finding.path,
        }
    ]
    for value in (finding.code, finding.path, finding.message, "token"):
        assert value in text_output


def test_verify_diagnostics_fail_closed_even_if_report_ok_is_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finding = _diagnostic("KIT_HASH_MISMATCH", "catalog.json")
    monkeypatch.setattr(
        cli,
        "verify_build_kit",
        lambda path: VerificationReport(True, (finding,)),
        raising=False,
    )

    assert cli.main(["--format", "json", "verify-kit", "kit"]) == 5
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_audit_forwards_package_and_binds_selected_package_in_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[Any, ...]] = []

    def audit(path: Path, expected_manifest: Path, *, package_id: str) -> AuditReport:
        calls.append((path, expected_manifest, package_id))
        return AuditReport(
            file_sha256="a" * 64,
            streams=(),
            modules=(),
            references=(),
            pcode=PCodeSignal("ok", 0, "b" * 64, "c" * 64),
            diagnostics=(),
            package_id="core",
        )

    monkeypatch.setattr(cli, "audit_catvba", audit, raising=False)

    result = cli.main(
        [
            "audit-catvba",
            "returned.catvba",
            "--expect",
            "kit/kit-manifest.json",
            "--package",
            "fleet-spa",
            "--format",
            "json",
        ]
    )

    assert result == 0
    assert calls == [
        (Path("returned.catvba"), Path("kit/kit-manifest.json"), "fleet-spa")
    ]
    document = json.loads(capsys.readouterr().out)
    assert document["package_id"] == "core"
    assert document["reference_verification"] == {
        "status": "unavailable",
        "contract_body_digest": None,
        "observation_sha256": None,
        "matched_stable_ids": [],
    }


def test_audit_package_without_expected_manifest_is_usage_error() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["audit-catvba", "returned.catvba", "--package", "core"])

    assert error.value.code == 2


def test_infrastructure_error_maps_only_at_main_and_keyboard_interrupt_escapes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "verify_build_kit",
        lambda path: (_ for _ in ()).throw(InfrastructureError("disk unavailable")),
        raising=False,
    )
    assert cli.main(["--format", "json", "verify-kit", "kit"]) == 4
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["exit_code"] == 4

    monkeypatch.setattr(
        cli,
        "verify_build_kit",
        lambda path: (_ for _ in ()).throw(KeyboardInterrupt()),
        raising=False,
    )
    with pytest.raises(KeyboardInterrupt):
        cli.main(["verify-kit", "kit"])


@pytest.mark.parametrize("profile", ["P-ALL", "P-PROD"])
def test_formal_cli_rejects_aggregate_profiles(profile: str) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "init-target-session", "kit.zip",
                "--mode", "g2",
                "--package", "core",
                "--profile", profile,
                "--handoff", "handoff.json",
                "--revocation-ledger", "active-handoff-ledger.json",
            ]
        )


def test_production_cli_does_not_expose_created_at() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "create-target-handoff", "primary",
                "--compare-build-root", "comparison",
                "--purpose", "discovery",
                "--revocation-snapshot", "revocations.json",
                "--prepared-record-id", "record-prepared",
                "--review-record-id", "record-reviewed",
                "--created-at", "2026-07-14T12:00:00Z",
                "--expires-at", "2026-07-21T12:00:00Z",
            ]
        )
