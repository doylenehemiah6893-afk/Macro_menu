from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build import cli
from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.handoff import (
    issue_target_handoff as _issue_target_handoff,
)
from catvba_refactor.macro_build.reference_contract import (
    reference_contract_body_digest,
)
from catvba_refactor.macro_build.target_evidence.session import (
    init_target_session as _init_target_session,
)
from catvba_refactor.macro_build.target_evidence.validator import (
    environment_fingerprint,
)
from catvba_refactor.tests import test_target_evidence_validator as evidence_fixtures


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

_SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
_REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
_STABLE_REFERENCE_ID = "ref.000204ef00000000c000000000000046.4.2"
_DISCOVERY_REVIEW_ID = "record-synthetic-discovery-decision-review"
_REFERENCE_REVIEW_ID = "record-synthetic-reference-contract-review"
_G2_REVIEW_ID = "record-synthetic-g2-decision-review"
_G3_REVIEW_ID = "record-synthetic-g3-decision-review"


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


def _invoke_success(
    capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> dict[str, Any]:
    return_code, document, stdout, stderr = _invoke_json(
        capsys, [*arguments, "--format", "json"]
    )
    assert return_code == 0, document
    assert stdout and not stderr
    return document


def _build_pair(
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    first_root: Path,
    second_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipts = tuple(
        _invoke_success(
            capsys,
            [
                "build-kit",
                "--repo-root",
                os.fspath(repo),
                "--output-root",
                os.fspath(output_root),
            ],
        )
        for output_root in (first_root, second_root)
    )
    assert receipts[0]["kit_id"] == receipts[1]["kit_id"]
    assert receipts[0]["zip_sha256"] == receipts[1]["zip_sha256"]
    assert Path(receipts[0]["zip_path"]).read_bytes() == Path(
        receipts[1]["zip_path"]
    ).read_bytes()
    return receipts


def _write_revocations(
    path: Path,
    *,
    captured_at: str,
    active: list[str] | None = None,
    withdrawn: list[str] | None = None,
) -> Path:
    path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": 1,
                "captured_at": captured_at,
                "source": "synthetic-e2e-active-handoff-ledger",
                "active_handoff_ids": active or [],
                "withdrawn_handoff_ids": withdrawn or [],
            }
        )
    )
    return path


def _write_active_ledger(
    path: Path,
    *,
    captured_at: str,
    active: list[str],
    withdrawn: list[str],
) -> Path:
    path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": 1,
                "captured_at": captured_at,
                "source": "repository-active-handoff-ledger",
                "active_handoff_ids": active,
                "withdrawn_handoff_ids": withdrawn,
            }
        )
    )
    return path


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _operator_record(
    record_id: str, category: str, captured_at: str
) -> tuple[dict[str, Any], bytes]:
    payload = f"synthetic redacted E2E witness for {record_id}\n".encode("ascii")
    relative_path = f"operator-records/{record_id}.txt"
    return (
        {
            "record_id": record_id,
            "category": category,
            "relative_path": relative_path,
            "sha256": sha256_bytes(payload),
            "captured_at": captured_at,
            "collector_role": "isolated-builder",
            "redaction_status": "two-person-text",
        },
        payload,
    )


def _synthetic_observation(ordinal: int) -> dict[str, Any]:
    return {
        "observation_record_id": f"record-synthetic-reference-vba-{ordinal:02d}",
        "stable_reference_id": _STABLE_REFERENCE_ID,
        "name": "VBA",
        "description": "Visual Basic For Applications",
        "guid": "{000204EF-0000-0000-C000-000000000046}",
        "major": 4,
        "minor": 2,
        "source_classification": "host-default",
        "missing": False,
        "path_kind": "catia-install",
        "path_basename": "VBE7.DLL",
        "relative_path": "win_b64/code/bin/VBE7.DLL",
        "redacted_path": "<CATIA_INSTALL>/VBE7.DLL",
        "path_sha256": "f" * 64,
        "architecture": "x64",
        "release_provenance": "B28",
        "operator_record_id": f"record-synthetic-reference-point-{ordinal:02d}",
    }


def _complete_synthetic_capture(
    capture: Path,
    *,
    mode: str,
    ended_at: str,
) -> None:
    documents = {
        name: json.loads((capture / name).read_bytes())
        for name in evidence_fixtures.ROOT_DOCUMENTS
    }
    session = documents["session.json"]
    session.update(
        capture_status="complete",
        anonymous_host_id="host-synthetic-e2e",
        vm_lineage_id="vm-lineage-synthetic-e2e",
        snapshot_id="snapshot-synthetic-clean-b28",
        ended_at=ended_at,
    )
    started_at = session["started_at"]
    index = documents["operator-records/index.json"]
    members: dict[str, bytes] = {}

    def add_record(record_id: str, category: str) -> None:
        record, payload = _operator_record(record_id, category, started_at)
        index["records"].append(record)
        members[record["relative_path"]] = payload

    if mode != "g3-c":
        template_documents, _template_members = evidence_fixtures._documents(mode)
        environment = copy.deepcopy(template_documents["environment.json"])
        environment["binding"] = session["binding"]
        environment["reference_contract_body_digest"] = documents[
            "environment.json"
        ]["reference_contract_body_digest"]
        environment["operator_record_id"] = "record-synthetic-environment"
        environment["environment_fingerprint"] = environment_fingerprint(
            {"session": session, "environment": environment},
            environment["reference_contract_body_digest"],
        )
        documents["environment.json"] = environment
        add_record("record-synthetic-environment", "environment")

    if mode == "discovery":
        for ordinal, point in enumerate(
            documents["references.json"]["points"], start=1
        ):
            record_id = f"record-synthetic-reference-point-{ordinal:02d}"
            point.update(
                status="observed",
                observations=[_synthetic_observation(ordinal)],
                operator_record_id=record_id,
            )
            add_record(record_id, "reference")
    elif mode == "g2":
        statuses = {
            "configuration_product": "observed",
            "reference_visibility": "available",
            "api_workbench": "available",
            "session_checkout": "available",
            "tool_result": "observed",
        }
        for field, status in statuses.items():
            record_id = f"record-synthetic-entitlement-{field.replace('_', '-')}"
            documents["entitlements.json"][field] = {
                "status": status,
                "operator_record_id": record_id,
            }
            add_record(record_id, "entitlement")
        documents["entitlements.json"]["licenses"] = {
            "AB3": {
                "availability": "observed-available",
                "checkout": "observed-checked-out",
            },
            "HD2": {
                "availability": "observed-unavailable",
                "checkout": "not-checked-out",
            },
            "MD2": {
                "availability": "observed-unavailable",
                "checkout": "not-checked-out",
            },
            "SPA": {
                "availability": "observed-available",
                "checkout": "observed-checked-out",
            },
            "FTA": {
                "availability": "observed-available",
                "checkout": "observed-checked-out",
            },
        }
        reference_record = "record-synthetic-reference-point-01"
        documents["references.json"]["points"][0].update(
            status="observed",
            observations=[_synthetic_observation(1)],
            operator_record_id=reference_record,
        )
        add_record(reference_record, "reference")

    index["records"].sort(key=lambda item: item["record_id"])
    for name, document in documents.items():
        (capture / name).write_bytes(canonical_json_bytes(document))
    for relative_path, data in members.items():
        destination = capture / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _approved_reference_contract(
    discovery_bundle: dict[str, Any],
    gate_receipt: Path,
    observation_approval: Path,
) -> dict[str, Any]:
    definitions = [
        {
            "stable_reference_id": _STABLE_REFERENCE_ID,
            "guid": "{000204EF-0000-0000-C000-000000000046}",
            "major": 4,
            "minor": 2,
            "allowed_names": ["VBA"],
            "allowed_descriptions": ["Visual Basic For Applications"],
            "source_classification": "host-default",
            "architecture": "x64",
            "release_provenance": "B28",
            "path_policy": {
                "root_kind": "catia-install",
                "allowed_basenames": ["VBE7.DLL"],
                "allowed_relative_paths": ["win_b64/code/bin/VBE7.DLL"],
                "canonical_path_sha256": "f" * 64,
            },
        }
    ]
    contract: dict[str, Any] = {
        "contract_id": "references.core.b28",
        "contract_version": 1,
        "status": "approved",
        "reference_definitions": definitions,
        "observation_points": {
            point: [_STABLE_REFERENCE_ID] for point in _REFERENCE_POINTS
        },
        "transitions": [
            {"from": source, "to": target, "added": [], "removed": []}
            for source, target in zip(
                _REFERENCE_POINTS[:-1], _REFERENCE_POINTS[1:], strict=True
            )
        ],
        "path_policy": {
            "allowed_root_kinds": ["catia-install"],
            "allow_user_paths": False,
        },
    }
    digest = reference_contract_body_digest(contract)
    assert digest is not None
    contract["contract_body_digest"] = digest
    contract["approval"] = {
        "reference_approval_record_id": _REFERENCE_REVIEW_ID,
        "reviewer_role": "independent-reference-reviewer",
        "approved_at": "2026-07-14T13:45:00Z",
        "discovery_session_id": discovery_bundle["session_id"],
        "discovery_bundle_sha256": discovery_bundle["zip_sha256"],
        "discovery_gate_receipt_sha256": sha256_bytes(gate_receipt.read_bytes()),
        "observation_approval_sha256": sha256_bytes(
            observation_approval.read_bytes()
        ),
        "approved_contract_body_digest": digest,
    }
    return contract


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
            "upstream_ref": "refs/heads/dev",
            "fork_repository": "fixture/fork",
            "fork_dev_ref": "refs/heads/dev",
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
    assert return_code == 3
    assert stdout and not stderr
    assert checked["ok"] is False
    assert checked["formal_eligible"] is False
    assert checked["mode"] == "worktree"
    assert [item["code"] for item in checked["diagnostics"]] == [
        "MEMBER_BINDING_MISMATCH"
    ]
    assert not {"kit_id", "kit_dir", "zip_path"} & checked.keys()


def test_synthetic_discovery_g2_and_g3_evidence_workflow_is_deterministic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise only synthetic offline evidence; never promote target status."""
    handoff_times = iter(("2026-07-14T10:30:00Z", "2026-07-14T14:00:00Z"))
    session_times = {
        "session-synthetic-discovery": "2026-07-14T12:00:00Z",
        "session-synthetic-g2": "2026-07-14T15:00:00Z",
        "session-synthetic-g3-c": "2026-07-14T17:00:00Z",
    }

    def issue_with_test_clock(*args: Any, **kwargs: Any) -> Any:
        fixed_time = next(handoff_times)
        return _issue_target_handoff(
            *args,
            **kwargs,
            _clock=lambda: fixed_time,
        )

    def init_with_test_time(*args: Any, **kwargs: Any) -> Any:
        session_id = kwargs["session_id"]
        return _init_target_session(
            *args,
            **kwargs,
            created_at=session_times[session_id],
        )

    monkeypatch.setattr(cli, "issue_target_handoff", issue_with_test_clock)
    monkeypatch.setattr(cli, "init_target_session", init_with_test_time)
    repo, _module_path, _module = _create_fixture_repository(tmp_path)
    discovery_builds = _build_pair(
        capsys,
        repo,
        tmp_path / "discovery build one",
        tmp_path / "discovery build two",
    )
    discovery_kit = Path(discovery_builds[0]["zip_path"])
    discovery_revocations = _write_revocations(
        tmp_path / "discovery revocations.json",
        captured_at="2026-07-14T10:00:00Z",
    )
    discovery_handoff = _invoke_success(
        capsys,
        [
            "create-target-handoff",
            os.fspath(tmp_path / "discovery build one"),
            "--compare-build-root",
            os.fspath(tmp_path / "discovery build two"),
            "--purpose",
            "discovery",
            "--revocation-snapshot",
            os.fspath(discovery_revocations),
            "--prepared-record-id",
            "record-synthetic-discovery-handoff-prepared",
            "--review-record-id",
            "record-synthetic-discovery-handoff-reviewed",
            "--expires-at",
            "2026-07-21T10:30:00Z",
            "--output-root",
            os.fspath(tmp_path / "discovery handoff"),
        ],
    )
    discovery_handoff_path = Path(discovery_handoff["handoff_path"])
    assert json.loads(discovery_handoff_path.read_bytes())["created_at"] == (
        "2026-07-14T10:30:00Z"
    )
    discovery_ledger = _write_active_ledger(
        tmp_path / "discovery active ledger.json",
        captured_at="2026-07-14T10:31:00Z",
        active=[discovery_handoff["handoff_id"]],
        withdrawn=[],
    )

    discovery_runs: list[dict[str, Any]] = []
    for ordinal in (1, 2):
        root = tmp_path / f"discovery workflow {ordinal}"
        initialized = _invoke_success(
            capsys,
            [
                "init-target-session",
                os.fspath(discovery_kit),
                "--mode",
                "discovery",
                "--package",
                "core",
                "--profile",
                "DISCOVERY",
                "--handoff",
                os.fspath(discovery_handoff_path),
                "--revocation-ledger",
                os.fspath(discovery_ledger),
                "--session-id",
                "session-synthetic-discovery",
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
                "--output-root",
                os.fspath(root / "capture output"),
            ],
        )
        capture = Path(initialized["session_dir"])
        _complete_synthetic_capture(
            capture, mode="discovery", ended_at="2026-07-14T13:00:00Z"
        )
        validated = _invoke_success(
            capsys,
            [
                "validate-target-evidence",
                os.fspath(capture),
                "--kit",
                os.fspath(discovery_kit),
                "--phase",
                "capture",
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
            ],
        )
        assert validated["session_id"] == "session-synthetic-discovery"

        gate_code, gate, stdout, stderr = _invoke_json(
            capsys,
            [
                "evaluate-target-gate",
                os.fspath(capture),
                "--gate",
                "DISCOVERY",
                "--kit",
                os.fspath(discovery_kit),
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
                "--output-root",
                os.fspath(root / "gate"),
                "--format",
                "json",
            ],
        )
        assert gate_code == 7
        assert stdout and not stderr
        assert gate["computed_outcome"] == "blocked"
        assert gate["reason"] == "discovery-only"
        gate_receipt = Path(gate["receipt_path"])

        approval = _invoke_success(
            capsys,
            [
                "record-target-approval",
                os.fspath(capture),
                "--kit",
                os.fspath(discovery_kit),
                "--gate-receipt",
                os.fspath(gate_receipt),
                "--scope",
                "observation",
                "--status",
                "approved",
                "--reviewer-role",
                "independent-evidence-reviewer",
                "--review-record-id",
                _DISCOVERY_REVIEW_ID,
                "--approved-at",
                "2026-07-14T13:30:00Z",
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
                "--output-root",
                os.fspath(root / "approval"),
            ],
        )
        approval_path = Path(approval["approval_path"])
        bundle = _invoke_success(
            capsys,
            [
                "pack-target-evidence",
                os.fspath(capture),
                "--kit",
                os.fspath(discovery_kit),
                "--gate-receipt",
                os.fspath(gate_receipt),
                "--approval",
                os.fspath(approval_path),
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
                "--output-root",
                os.fspath(root / "sealed"),
            ],
        )
        for sealed_input in (bundle["bundle_dir"], bundle["zip_path"]):
            sealed = _invoke_success(
                capsys,
                [
                    "validate-target-evidence",
                    sealed_input,
                    "--kit",
                    os.fspath(discovery_kit),
                    "--phase",
                    "sealed",
                    "--schema-dir",
                    os.fspath(_SCHEMA_ROOT),
                ],
            )
            assert sealed["session_id"] == "session-synthetic-discovery"
        discovery_runs.append(
            {
                "capture": capture,
                "gate": gate_receipt,
                "approval": approval_path,
                "bundle": bundle,
            }
        )

    first_discovery, second_discovery = discovery_runs
    assert _tree_bytes(first_discovery["capture"]) == _tree_bytes(
        second_discovery["capture"]
    )
    assert first_discovery["gate"].read_bytes() == second_discovery[
        "gate"
    ].read_bytes()
    assert first_discovery["approval"].read_bytes() == second_discovery[
        "approval"
    ].read_bytes()
    assert _tree_bytes(Path(first_discovery["bundle"]["bundle_dir"])) == _tree_bytes(
        Path(second_discovery["bundle"]["bundle_dir"])
    )
    assert Path(first_discovery["bundle"]["zip_path"]).read_bytes() == Path(
        second_discovery["bundle"]["zip_path"]
    ).read_bytes()

    packages_path = repo / "catvba_refactor" / "config" / "packages.json"
    packages = json.loads(packages_path.read_text(encoding="utf-8"))
    packages["packages"][0]["reference_contract"] = _approved_reference_contract(
        first_discovery["bundle"],
        first_discovery["gate"],
        first_discovery["approval"],
    )
    _write_json(packages_path, packages)
    old_cutoff = _git(repo, "rev-parse", "dev")
    _git(repo, "add", "catvba_refactor/config/packages.json")
    _git(repo, "commit", "-m", "fixture: approve synthetic reference contract")
    assert _git(repo, "rev-parse", "dev") == old_cutoff
    assert _git(repo, "rev-parse", "HEAD") != old_cutoff

    formal_builds = _build_pair(
        capsys,
        repo,
        tmp_path / "formal build one",
        tmp_path / "formal build two",
    )
    formal_kit = Path(formal_builds[0]["zip_path"])
    formal_revocations = _write_revocations(
        tmp_path / "formal revocations.json",
        captured_at="2026-07-14T13:50:00Z",
        withdrawn=[discovery_handoff["handoff_id"]],
    )
    formal_handoff = _invoke_success(
        capsys,
        [
            "create-target-handoff",
            os.fspath(tmp_path / "formal build one"),
            "--compare-build-root",
            os.fspath(tmp_path / "formal build two"),
            "--purpose",
            "formal",
            "--supersedes-handoff",
            os.fspath(discovery_handoff_path),
            "--revocation-snapshot",
            os.fspath(formal_revocations),
            "--prepared-record-id",
            "record-synthetic-formal-handoff-prepared",
            "--review-record-id",
            "record-synthetic-formal-handoff-reviewed",
            "--expires-at",
            "2026-07-21T14:00:00Z",
            "--output-root",
            os.fspath(tmp_path / "formal handoff"),
        ],
    )
    formal_handoff_path = Path(formal_handoff["handoff_path"])
    assert json.loads(formal_handoff_path.read_bytes())["created_at"] == (
        "2026-07-14T14:00:00Z"
    )
    formal_ledger = _write_active_ledger(
        tmp_path / "formal active ledger.json",
        captured_at="2026-07-14T14:01:00Z",
        active=[formal_handoff["handoff_id"]],
        withdrawn=[discovery_handoff["handoff_id"]],
    )

    g2_initialized = _invoke_success(
        capsys,
        [
            "init-target-session",
            os.fspath(formal_kit),
            "--mode",
            "g2",
            "--package",
            "core",
            "--profile",
            "P-AB3",
            "--handoff",
            os.fspath(formal_handoff_path),
            "--revocation-ledger",
            os.fspath(formal_ledger),
            "--session-id",
            "session-synthetic-g2",
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g2 capture"),
        ],
    )
    g2_capture = Path(g2_initialized["session_dir"])
    _complete_synthetic_capture(
        g2_capture, mode="g2", ended_at="2026-07-14T16:00:00Z"
    )
    g2_gate = _invoke_success(
        capsys,
        [
            "evaluate-target-gate",
            os.fspath(g2_capture),
            "--gate",
            "G2",
            "--kit",
            os.fspath(formal_kit),
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g2 gate"),
        ],
    )
    assert g2_gate["computed_outcome"] == "eligible"
    g2_approval = _invoke_success(
        capsys,
        [
            "record-target-approval",
            os.fspath(g2_capture),
            "--kit",
            os.fspath(formal_kit),
            "--gate-receipt",
            g2_gate["receipt_path"],
            "--scope",
            "gate",
            "--status",
            "approved",
            "--reviewer-role",
            "independent-evidence-reviewer",
            "--review-record-id",
            _G2_REVIEW_ID,
            "--approved-at",
            "2026-07-14T16:30:00Z",
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g2 approval"),
        ],
    )
    g2_bundle = _invoke_success(
        capsys,
        [
            "pack-target-evidence",
            os.fspath(g2_capture),
            "--kit",
            os.fspath(formal_kit),
            "--gate-receipt",
            g2_gate["receipt_path"],
            "--approval",
            g2_approval["approval_path"],
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g2 sealed"),
        ],
    )

    g3_initialized = _invoke_success(
        capsys,
        [
            "init-target-session",
            os.fspath(formal_kit),
            "--mode",
            "g3-c",
            "--package",
            "core",
            "--profile",
            "P-AB3",
            "--handoff",
            os.fspath(formal_handoff_path),
            "--revocation-ledger",
            os.fspath(formal_ledger),
            "--prerequisite-evidence",
            g2_bundle["zip_path"],
            "--session-id",
            "session-synthetic-g3-c",
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g3 capture"),
        ],
    )
    g3_capture = Path(g3_initialized["session_dir"])
    _complete_synthetic_capture(
        g3_capture, mode="g3-c", ended_at="2026-07-14T18:00:00Z"
    )
    g3_gate_code, g3_gate, stdout, stderr = _invoke_json(
        capsys,
        [
            "evaluate-target-gate",
            os.fspath(g3_capture),
            "--gate",
            "G3-C",
            "--kit",
            os.fspath(formal_kit),
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g3 gate"),
            "--format",
            "json",
        ],
    )
    assert g3_gate_code == 7
    assert stdout and not stderr
    assert g3_gate["computed_outcome"] == "blocked"
    g3_approval = _invoke_success(
        capsys,
        [
            "record-target-approval",
            os.fspath(g3_capture),
            "--kit",
            os.fspath(formal_kit),
            "--gate-receipt",
            g3_gate["receipt_path"],
            "--scope",
            "gate",
            "--status",
            "approved",
            "--reviewer-role",
            "independent-evidence-reviewer",
            "--review-record-id",
            _G3_REVIEW_ID,
            "--approved-at",
            "2026-07-14T18:30:00Z",
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g3 approval"),
        ],
    )
    assert _G2_REVIEW_ID != _G3_REVIEW_ID
    nested_approval = json.loads(Path(g2_approval["approval_path"]).read_bytes())
    outer_approval = json.loads(Path(g3_approval["approval_path"]).read_bytes())
    assert nested_approval["review_record_id"] == _G2_REVIEW_ID
    assert outer_approval["review_record_id"] == _G3_REVIEW_ID
    g3_bundle = _invoke_success(
        capsys,
        [
            "pack-target-evidence",
            os.fspath(g3_capture),
            "--kit",
            os.fspath(formal_kit),
            "--gate-receipt",
            g3_gate["receipt_path"],
            "--approval",
            g3_approval["approval_path"],
            "--schema-dir",
            os.fspath(_SCHEMA_ROOT),
            "--output-root",
            os.fspath(tmp_path / "g3 sealed"),
        ],
    )
    for sealed_input in (g2_bundle["bundle_dir"], g2_bundle["zip_path"]):
        assert _invoke_success(
            capsys,
            [
                "validate-target-evidence",
                sealed_input,
                "--kit",
                os.fspath(formal_kit),
                "--phase",
                "sealed",
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
            ],
        )["ok"] is True
    for sealed_input in (g3_bundle["bundle_dir"], g3_bundle["zip_path"]):
        assert _invoke_success(
            capsys,
            [
                "validate-target-evidence",
                sealed_input,
                "--kit",
                os.fspath(formal_kit),
                "--phase",
                "sealed",
                "--schema-dir",
                os.fspath(_SCHEMA_ROOT),
            ],
        )["ok"] is True
