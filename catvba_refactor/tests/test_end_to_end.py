from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build import cli


_SCHEMA_NAMES = (
    "components.schema.json",
    "packages.schema.json",
    "project.schema.json",
    "tools.schema.json",
)


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _blob_oid(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _binding(path: str, role: str, data: bytes) -> dict[str, str]:
    return {
        "path": path,
        "blob_oid": _blob_oid(data),
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "role": role,
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _invoke_json(
    capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> tuple[int, dict[str, Any], str, str]:
    return_code = cli.main(arguments)
    captured = capsys.readouterr()
    serialized = captured.out or captured.err
    return return_code, json.loads(serialized), captured.out, captured.err


def _create_fixture_repository(tmp_path: Path) -> tuple[Path, Path, bytes]:
    repo = tmp_path / "fixture repository"
    inputs = repo / "fixture_inputs"
    config = repo / "catvba_refactor" / "config"
    schemas = repo / "catvba_refactor" / "schemas"
    inputs.mkdir(parents=True)
    config.mkdir(parents=True)
    schemas.mkdir(parents=True)

    module = (
        b'Attribute VB_Name = "SafeModule"\r\n'
        b"Option Explicit\r\n"
        b"Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
        b"End Function\r\n"
    )
    form = (
        b"VERSION 5.00\r\n"
        b"Begin VB.UserForm SafeForm\r\n"
        b'   Caption = "Safe Form"\r\n'
        b"End\r\n"
        b'Attribute VB_Name = "SafeForm"\r\n'
        b'OleObjectBlob = "SafeForm.frx":0000\r\n'
        b"Option Explicit\r\n"
    )
    frx = b"\x00\x01COMPLETE-FORM-RESOURCE\xff"
    module_path = inputs / "SafeModule.bas"
    module_path.write_bytes(module)
    (inputs / "SafeForm.frm").write_bytes(form)
    (inputs / "SafeForm.frx").write_bytes(frx)

    canonical_schemas = Path(__file__).resolve().parents[1] / "schemas"
    for name in _SCHEMA_NAMES:
        (schemas / name).write_bytes((canonical_schemas / name).read_bytes())

    _write_json(
        config / "project.json",
        {
            "schema_version": 1,
            "upstream_repository": "fixture/upstream",
            "upstream_ref": "dev",
            "fork_repository": "fixture/fork",
            "fork_dev_ref": "dev",
            "work_repository": "fixture/work",
            "work_branch": "codex/dev-review-report",
            "governed_paths": [
                "catvba_refactor/config",
                "catvba_refactor/schemas",
                "fixture_inputs",
            ],
        },
    )
    _write_json(
        config / "components.json",
        {
            "schema_version": 1,
            "source_roots": [
                {
                    "root_id": "fixture-inputs",
                    "origin": "new",
                    "path": "fixture_inputs",
                    "extensions": [".bas", ".cls", ".frm", ".frx"],
                    "default_disposition": "quarantine",
                }
            ],
            "components": [
                {
                    "source_id": "core.safe-form",
                    "origin": "new",
                    "component_type": "user_form",
                    "vb_name": "SafeForm",
                    "package_id": "core",
                    "disposition": "candidate",
                    "encoding_decision": "utf-8",
                    "members": [
                        _binding("fixture_inputs/SafeForm.frm", "frm", form),
                        _binding("fixture_inputs/SafeForm.frx", "frx", frx),
                    ],
                },
                {
                    "source_id": "core.safe-module",
                    "origin": "new",
                    "component_type": "standard_module",
                    "vb_name": "SafeModule",
                    "package_id": "core",
                    "disposition": "candidate",
                    "encoding_decision": "utf-8",
                    "members": [
                        _binding("fixture_inputs/SafeModule.bas", "source", module)
                    ],
                },
            ],
        },
    )
    _write_json(
        config / "packages.json",
        {
            "schema_version": 1,
            "packages": [
                {"package_id": "core", "classification": "CORE_CANDIDATE"}
            ],
        },
    )
    _write_json(
        config / "tools.json",
        {
            "schema_version": 1,
            "tools": [
                {
                    "tool_id": "core.safe",
                    "caption": "Safe",
                    "tooltip": "Run the safe tool",
                    "group_id": "core.general",
                    "group_caption": "General",
                    "package_id": "core",
                    "module_name": "SafeModule",
                    "entrypoint": "Run",
                    "document_types": ["none"],
                    "required_capabilities": [],
                    "risk_level": "read-only",
                }
            ],
        },
    )

    _git(repo, "init", "--initial-branch=codex/dev-review-report")
    _git(repo, "config", "user.name", "Macro Menu End-to-End Tests")
    _git(repo, "config", "user.email", "macro-menu-e2e@example.invalid")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "fixture: add complete candidate inputs")
    _git(repo, "branch", "dev")
    assert _git(repo, "rev-parse", "dev") == _git(repo, "rev-parse", "HEAD")
    return repo, module_path, module


def test_candidate_kit_is_deterministic_and_dirty_tree_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, module_path, module = _create_fixture_repository(tmp_path)
    output_roots = (tmp_path / "output one", tmp_path / "output two")
    receipts: list[dict[str, Any]] = []

    for output_root in output_roots:
        return_code, receipt, stdout, stderr = _invoke_json(
            capsys,
            [
                "--repo-root",
                os.fspath(repo),
                "--output-root",
                os.fspath(output_root),
                "--format",
                "json",
                "build-kit",
            ],
        )
        assert return_code == 0
        assert stdout and not stderr
        assert receipt["ok"] is True
        assert receipt["formal_eligible"] is True
        assert receipt["compile_status"] == "not-run"
        assert receipt["release_eligible"] is False
        assert Path(receipt["kit_dir"]).parent == output_root
        receipts.append(receipt)

    for receipt in receipts:
        for kit_path in (receipt["kit_dir"], receipt["zip_path"]):
            return_code, verified, stdout, stderr = _invoke_json(
                capsys, ["--format", "json", "verify-kit", kit_path]
            )
            assert return_code == 0
            assert stdout and not stderr
            assert verified == {
                "command": "verify-kit",
                "ok": True,
                "diagnostics": [],
            }

    first, second = receipts
    first_kit = Path(first["kit_dir"])
    second_kit = Path(second["kit_dir"])
    first_zip = Path(first["zip_path"])
    second_zip = Path(second["zip_path"])
    assert first["kit_id"] == second["kit_id"]
    assert (first_kit / "catalog.json").read_bytes() == (
        second_kit / "catalog.json"
    ).read_bytes()
    assert (first_kit / "SHA256SUMS").read_bytes() == (
        second_kit / "SHA256SUMS"
    ).read_bytes()
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["zip_sha256"] == second["zip_sha256"]
    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert hashlib.sha256(first_zip.read_bytes()).hexdigest() == first["zip_sha256"]

    dirty_module = module + b"' diagnostic worktree change\r\n"
    module_path.write_bytes(dirty_module)
    components_path = repo / "catvba_refactor" / "config" / "components.json"
    components = json.loads(components_path.read_text(encoding="utf-8"))
    module_record = next(
        record
        for record in components["components"]
        if record["source_id"] == "core.safe-module"
    )
    module_record["members"][0]["raw_sha256"] = hashlib.sha256(
        dirty_module
    ).hexdigest()
    _write_json(components_path, components)

    dirty_output = tmp_path / "dirty output"
    return_code, error, stdout, stderr = _invoke_json(
        capsys,
        [
            "--repo-root",
            os.fspath(repo),
            "--output-root",
            os.fspath(dirty_output),
            "--format",
            "json",
            "build-kit",
        ],
    )
    assert return_code == 3
    assert not stdout and stderr
    assert error["error"]["exit_code"] == 3
    assert error["error"]["message"] == (
        "candidate snapshot requires a clean governed tree"
    )
    assert not dirty_output.exists()

    return_code, checked, stdout, stderr = _invoke_json(
        capsys,
        [
            "--repo-root",
            os.fspath(repo),
            "--format",
            "json",
            "check",
            "--worktree",
        ],
    )
    assert return_code == 0
    assert stdout and not stderr
    assert checked["ok"] is True
    assert checked["formal_eligible"] is False
    assert checked["mode"] == "worktree"
    assert not {"kit_id", "kit_dir", "zip_path"} & checked.keys()
