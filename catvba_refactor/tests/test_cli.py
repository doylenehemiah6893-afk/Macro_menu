from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build import cli
from catvba_refactor.macro_build.audit import AuditReport, PCodeSignal
from catvba_refactor.macro_build.errors import (
    EvidenceError,
    ExitCode,
    GateError,
    InfrastructureError,
    SourceError,
)
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import (
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

    def repository(root: Path) -> object:
        calls.append(("repo", root))
        return object()

    def freeze(
        repo: object,
        project: dict[str, Any],
        digest: str,
        version: str,
        worktree: bool = False,
    ) -> InputSnapshot:
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
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["UV_CACHE_DIR"] = "/tmp/uv-cache"

    completed = subprocess.run(
        ["uv", "run", "macro-menu-build", "--help"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    for command in (
        "inventory",
        "check",
        "build-kit",
        "verify-kit",
        "audit-catvba",
    ):
        assert command in completed.stdout


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
    assert json.loads(capsys.readouterr().out)["package_id"] == "core"


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
