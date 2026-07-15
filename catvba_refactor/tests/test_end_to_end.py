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

_CORE_NEW_COMPONENTS = (
    ("core.entry", "standard_module", "MM_Entry", "MM_Entry.bas"),
    (
        "core.menu-presenter",
        "standard_module",
        "MM_MenuPresenter",
        "MM_MenuPresenter.bas",
    ),
    ("core.protocol", "standard_module", "MM_Protocol", "MM_Protocol.bas"),
    ("core.error", "standard_module", "MM_Error", "MM_Error.bas"),
    ("core.log", "standard_module", "MM_Log", "MM_Log.bas"),
    ("core.try-get", "standard_module", "MM_TryGet", "MM_TryGet.bas"),
    (
        "core.button-handler",
        "class_module",
        "C_MMButtonHandler",
        "C_MMButtonHandler.cls",
    ),
    ("core.context", "class_module", "C_MMContext", "C_MMContext.cls"),
    ("core.result", "class_module", "C_MMResult", "C_MMResult.cls"),
    (
        "core.state-guard",
        "class_module",
        "C_MMStateGuard",
        "C_MMStateGuard.cls",
    ),
    (
        "core.healthcheck",
        "standard_module",
        "MM_HealthCheck",
        "MM_HealthCheck.bas",
    ),
    (
        "core.document-summary",
        "standard_module",
        "MM_DocumentSummary",
        "MM_DocumentSummary.bas",
    ),
)

_CORE_TOOLS = (
    (
        "core.healthcheck",
        "Health Check",
        "MM_HealthCheck",
        "RunHealthCheck",
        ["none", "CATPart", "CATProduct", "CATDrawing"],
    ),
    (
        "core.document-summary",
        "Document Summary",
        "MM_DocumentSummary",
        "RunDocumentSummary",
        ["none", "CATPart", "CATProduct", "CATDrawing"],
    ),
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


def _git_bytes(repo: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return completed.stdout


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
                {
                    "package_id": "core",
                    "classification": "CORE_CANDIDATE",
                    "reference_allowlist": [],
                    "reference_contract": {
                        "contract_id": "references.core.b28",
                        "contract_version": 1,
                        "observation_points": None,
                        "reference_definitions": None,
                        "status": "discovery-required",
                        "transitions": None,
                    },
                }
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


def test_production_core_manifests_bind_only_the_committed_first_cycle() -> None:
    repo = Path(__file__).resolve().parents[2]
    config = repo / "catvba_refactor" / "config"
    components_document = json.loads(
        (config / "components.json").read_text(encoding="utf-8")
    )
    tools_document = json.loads(
        (config / "tools.json").read_text(encoding="utf-8")
    )

    assert components_document["source_roots"] == [
        {
            "root_id": "upstream-src",
            "origin": "upstream",
            "path": "Src",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
        {
            "root_id": "new-src",
            "origin": "new",
            "path": "catvba_refactor/vba/new",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
        {
            "root_id": "override-src",
            "origin": "override",
            "path": "catvba_refactor/vba/overrides",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
    ]

    records = components_document["components"]
    assert [record["source_id"] for record in records] == [
        *[item[0] for item in _CORE_NEW_COMPONENTS],
        "core.menu-form",
    ]
    for record, (source_id, component_type, vb_name, filename) in zip(
        records[:-1], _CORE_NEW_COMPONENTS, strict=True
    ):
        path = f"catvba_refactor/vba/new/{filename}"
        assert record == {
            "source_id": source_id,
            "origin": "new",
            "component_type": component_type,
            "vb_name": vb_name,
            "package_id": "core",
            "disposition": "candidate",
            "encoding_decision": "cp936",
            "members": [
                {
                    "path": path,
                    "blob_oid": _git(repo, "rev-parse", f"HEAD:{path}"),
                    "raw_sha256": hashlib.sha256(
                        _git_bytes(repo, "show", f"HEAD:{path}")
                    ).hexdigest(),
                    "role": "source",
                }
            ],
        }

    form = records[-1]
    local_form_paths = (
        ("catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frm", "frm"),
        ("catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frx", "frx"),
    )
    base_form_paths = (
        ("Src/Cat_Macro_Menu_View.frm", "frm"),
        ("Src/Cat_Macro_Menu_View.frx", "frx"),
    )

    def committed_bindings(
        revision: str, paths: tuple[tuple[str, str], ...]
    ) -> list[dict[str, str]]:
        return [
            {
                "path": path,
                "blob_oid": _git(repo, "rev-parse", f"{revision}:{path}"),
                "raw_sha256": hashlib.sha256(
                    _git_bytes(repo, "show", f"{revision}:{path}")
                ).hexdigest(),
                "role": role,
            }
            for path, role in paths
        ]

    assert form == {
        "source_id": "core.menu-form",
        "origin": "override",
        "component_type": "user_form",
        "vb_name": "Cat_Macro_Menu_View",
        "package_id": "core",
        "disposition": "candidate",
        "encoding_decision": "cp936",
        "members": committed_bindings("HEAD", local_form_paths),
        "base_members": committed_bindings(
            "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad", base_form_paths
        ),
    }
    assert all(
        record["package_id"] == "core"
        and record["disposition"] == "candidate"
        and not record["source_id"].startswith(("fleet.", "optional."))
        for record in records
    )

    tools = tools_document["tools"]
    assert [tool["tool_id"] for tool in tools] == [item[0] for item in _CORE_TOOLS]
    for tool, (
        tool_id,
        caption,
        module_name,
        entrypoint,
        document_types,
    ) in zip(tools, _CORE_TOOLS, strict=True):
        assert tool == {
            "tool_id": tool_id,
            "caption": caption,
            "tooltip": (
                "Report Core runtime readiness without changing CATIA state."
                if tool_id == "core.healthcheck"
                else "Summarize the active document without changing CATIA state."
            ),
            "group_id": "core.general",
            "group_caption": "Core",
            "package_id": "core",
            "module_name": module_name,
            "entrypoint": entrypoint,
            "document_types": document_types,
            "required_capabilities": [],
            "risk_level": "read-only",
        }


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

    target_plan = json.loads(
        (first_kit / "target-test-plan/target-test-plan.json").read_text(
            encoding="ascii"
        )
    )
    cases = target_plan["cases"]
    catalog_identity = json.loads(
        (first_kit / "catalog.json").read_text(encoding="ascii")
    )
    catalog_sha256 = hashlib.sha256(
        (first_kit / "catalog.json").read_bytes()
    ).hexdigest()
    assert len(cases) == 30
    assert [case["case_id"] for case in cases[:8]] == [
        "context.core.healthcheck.none",
        "context.core.healthcheck.CATPart",
        "context.core.healthcheck.CATProduct",
        "context.core.healthcheck.CATDrawing",
        "context.core.document-summary.none",
        "context.core.document-summary.CATPart",
        "context.core.document-summary.CATProduct",
        "context.core.document-summary.CATDrawing",
    ]
    assert all(case["status"] == "not-run" for case in cases)
    assert all(
        case["build_identity"]
        == {
            "catalog_sha256": catalog_sha256,
            "kit_id": first["kit_id"],
            "manifest_digest": catalog_identity["snapshot"]["manifest_digest"],
            "work_commit": catalog_identity["snapshot"]["work_commit"],
            "work_tree": catalog_identity["snapshot"]["work_tree"],
        }
        for case in cases
    )

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
