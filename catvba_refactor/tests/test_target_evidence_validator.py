from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.model import BuildKitInspection, VerificationReport
from catvba_refactor.macro_build.target_evidence.container import (
    EvidenceContainerSnapshot,
    canonical_evidence_zip_bytes,
    canonical_payload_manifest,
)
from catvba_refactor.macro_build.target_evidence.model import (
    EvidencePhase,
    TargetEvidenceReport,
)
from catvba_refactor.macro_build.target_evidence.validator import (
    TargetEvidenceInspection,
    environment_fingerprint,
    validate_target_evidence,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas" / "target_evidence"
REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
COMPILE_POINTS = ("blank-project", "post-import", "post-save", "post-restart")
ROOT_DOCUMENTS = (
    "session.json",
    "environment.json",
    "entitlements.json",
    "references.json",
    "compile-result.json",
    "test-results.json",
    "state-diff.json",
    "artifact-manifest.json",
    "operator-records/index.json",
)
MANIFEST_DIGEST = "c" * 64
KIT_ZIP_SHA = "d" * 64
WORK_COMMIT = "1" * 40
WORK_TREE = "2" * 40
UPSTREAM_COMMIT = "3" * 40
FORK_COMMIT = "4" * 40
REVOKE_SHA = "e" * 64
RECORD_SHA = "f" * 64
CATALOG_BYTES = canonical_json_bytes(
    {
        "snapshot": {
            "upstream_commit": UPSTREAM_COMMIT,
            "fork_dev_commit": FORK_COMMIT,
            "work_commit": WORK_COMMIT,
            "work_tree": WORK_TREE,
            "work_branch": "codex/offline-build-kit",
            "manifest_digest": MANIFEST_DIGEST,
        },
        "packages": [{"package_id": "core"}],
    }
)
CATALOG_SHA = sha256_bytes(CATALOG_BYTES)
KIT_ID = "kit-" + CATALOG_SHA[:20]
MANIFEST_BYTES = canonical_json_bytes(
    {
        "kit_id": KIT_ID,
        "manifest_digest": MANIFEST_DIGEST,
        "target_build_required": True,
        "catvba_artifacts": [],
        "compile_status": "not-run",
        "release_eligible": False,
    }
)
MANIFEST_SHA = sha256_bytes(MANIFEST_BYTES)
CLEAN_VERIFIER_SHA = sha256_bytes(
    canonical_json_bytes({"ok": True, "diagnostics": []})
)
ZIP_SIDECAR_SHA = sha256_bytes(
    f"{KIT_ZIP_SHA}  {KIT_ID}.zip\n".encode("ascii")
)
CREATED = "2026-07-14T10:00:00Z"
STARTED = "2026-07-14T12:00:00Z"
ENDED = "2026-07-14T13:00:00Z"
APPROVED = "2026-07-14T13:30:00Z"


def _stable_id(guid: str, major: int, minor: int) -> str:
    return f"ref.{guid.strip('{}').replace('-', '').lower()}.{major}.{minor}"


GUID = "{000204EF-0000-0000-C000-000000000046}"
STABLE_ID = _stable_id(GUID, 4, 2)


def _case_specs() -> list[dict[str, Any]]:
    """A concise, independent expression of the immutable 30-case contract."""
    specs: list[dict[str, Any]] = []
    for tool_id, documents in (
        (
            "core.healthcheck",
            (("none", 0), ("CATPart", 0), ("CATProduct", 0), ("CATDrawing", 0)),
        ),
        (
            "core.document-summary",
            (("none", 20), ("CATPart", 0), ("CATProduct", 0), ("CATDrawing", 0)),
        ),
    ):
        for document_type, result_code in documents:
            specs.append(
                {
                    "case_id": f"context.{tool_id}.{document_type}",
                    "category": "context",
                    "document_type": document_type,
                    "expected": {"result_code": result_code},
                    "tool_id": tool_id,
                }
            )
    runnable = (("core.healthcheck", "none", 0), ("core.document-summary", "CATPart", 0))
    for profile_id in ("P-AB3", "P-HD2", "P-MD2"):
        for tool_id, document_type, result_code in runnable:
            specs.append(
                {
                    "case_id": f"profile.{profile_id}.{tool_id}",
                    "category": "profile",
                    "document_type": document_type,
                    "expected": {"result_code": result_code},
                    "profile_id": profile_id,
                    "tool_id": tool_id,
                }
            )
    for scenario in ("restart", "repeat", "cross-document", "state-diff"):
        for tool_id, document_type, result_code in runnable:
            specs.append(
                {
                    "case_id": f"lifecycle.{scenario}.{tool_id}",
                    "category": "lifecycle",
                    "document_type": document_type,
                    "expected": {"result_code": result_code, "state": "clean"},
                    "scenario": scenario,
                    "tool_id": tool_id,
                }
            )
    for package_id in ("fleet-spa", "fleet-fta"):
        for failure_mode in ("missing", "broken", "reference-failed", "checkout-failed"):
            specs.append(
                {
                    "case_id": f"isolation.{package_id}.{failure_mode}",
                    "category": "isolation",
                    "expected": {"core_state": "READY", "result_code": 0},
                    "extension_package_id": package_id,
                    "failure_mode": failure_mode,
                    "tool_id": "core.healthcheck",
                }
            )
    assert len(specs) == 30
    return specs


def _reference_contract(*, approved: bool) -> tuple[dict[str, Any], str]:
    path_policy = {"allowed_root_kinds": ["catia-install"], "allow_user_paths": False}
    definitions: list[dict[str, Any]] = []
    points: dict[str, list[str]] | None = None
    transitions: list[dict[str, Any]] | None = None
    approval: dict[str, Any] | None = None
    if approved:
        definitions = [
            {
                "stable_reference_id": STABLE_ID,
                "guid": GUID,
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
                    "canonical_path_sha256": RECORD_SHA,
                },
            }
        ]
        points = {point: [STABLE_ID] for point in REFERENCE_POINTS}
        transitions = [
            {"from": source, "to": target, "added": [], "removed": []}
            for source, target in zip(
                REFERENCE_POINTS[:-1], REFERENCE_POINTS[1:], strict=True
            )
        ]
    body = {
        "reference_definitions": definitions,
        "observation_points": points,
        "transitions": transitions,
        "path_policy": path_policy,
    }
    digest = sha256_bytes(canonical_json_bytes(body))
    if approved:
        approval = {
            "reference_approval_record_id": "record-reference-approval",
            "reviewer_role": "independent-reviewer",
            "approved_at": CREATED,
            "discovery_session_id": "session-20260713-discovery",
            "discovery_bundle_sha256": RECORD_SHA,
            "discovery_gate_receipt_sha256": REVOKE_SHA,
            "observation_approval_sha256": MANIFEST_SHA,
            "approved_contract_body_digest": digest,
        }
    return (
        {
            "status": "approved" if approved else "discovery-required",
            "contract_id": "reference-contract-core",
            "contract_version": 1,
            "contract_body_digest": digest,
            "reference_definitions": definitions,
            "observations": points,
            "transitions": transitions,
            "path_policy": path_policy,
            "approval": approval,
        },
        digest,
    )


def _target_plan() -> dict[str, Any]:
    identity = {
        "catalog_sha256": CATALOG_SHA,
        "kit_id": KIT_ID,
        "manifest_digest": MANIFEST_DIGEST,
        "work_commit": WORK_COMMIT,
        "work_tree": WORK_TREE,
    }
    cases = [
        {**spec, "build_identity": identity, "package_id": "core", "status": "not-run"}
        for spec in _case_specs()
    ]
    return {
        "schema_version": 1,
        "target": "CATIA R2018/VBA7 64",
        "license_requirements": {
            "baseline_any_of": ["AB3", "HD2", "MD2"],
            "additional_required": ["SPA", "FTA"],
            "verification_status": "not-run",
        },
        "cases": cases,
        "target_build_required": True,
        "catvba_artifacts": [],
        "compile_status": "not-run",
        "release_eligible": False,
    }


def _kit(*, formal: bool) -> BuildKitInspection:
    contract, digest = _reference_contract(approved=formal)
    companion_contract = copy.deepcopy(contract)
    companion_contract["observation_points"] = companion_contract.pop("observations")
    files = {
        "catalog.json": CATALOG_BYTES,
        "kit-manifest.json": MANIFEST_BYTES,
        "references/core.json": canonical_json_bytes(
            {
                "schema_version": 2,
                "package_id": "core",
                "reference_allowlist": [],
                "reference_contract": companion_contract,
                "contract_body_digest": digest,
                "compile_status": "not-run",
            }
        ),
        "target-test-plan/target-test-plan.json": canonical_json_bytes(_target_plan()),
    }
    return BuildKitInspection(
        files=tuple(sorted(files.items())),
        kit_id=KIT_ID,
        catalog_sha256=CATALOG_SHA,
        manifest_sha256=MANIFEST_SHA,
        manifest_digest=MANIFEST_DIGEST,
        upstream_commit=UPSTREAM_COMMIT,
        fork_dev_commit=FORK_COMMIT,
        work_commit=WORK_COMMIT,
        work_tree=WORK_TREE,
        work_branch="codex/offline-build-kit",
        canonical_zip_sha256=KIT_ZIP_SHA,
        report=VerificationReport(ok=True, diagnostics=()),
    )


def _handoff_body(mode: str) -> dict[str, Any]:
    formal = mode != "discovery"
    contract, _ = _reference_contract(approved=formal)
    return {
        "schema_version": 1,
        "purpose": "formal" if formal else "discovery",
        "created_at": CREATED,
        "expires_at": "2026-07-21T10:00:00Z",
        "revocation_status": "active",
        "revocation_snapshot_sha256": REVOKE_SHA,
        "kit_id": KIT_ID,
        "catalog_sha256": CATALOG_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "manifest_digest": MANIFEST_DIGEST,
        "zip_sha256": KIT_ZIP_SHA,
        "zip_sidecar_sha256": ZIP_SIDECAR_SHA,
        "work_commit": WORK_COMMIT,
        "work_tree": WORK_TREE,
        "work_branch": "codex/offline-build-kit",
        "upstream_cutoff": UPSTREAM_COMMIT,
        "fork_dev_cutoff": FORK_COMMIT,
        "package_id": "core",
        "target": "CATIA R2018/VBA7 64",
        "compile_status": "not-run",
        "release_eligible": False,
        "generation_command": "macro-menu-build create-target-handoff",
        "primary_directory_verifier_report_digest": CLEAN_VERIFIER_SHA,
        "comparison_directory_verifier_report_digest": CLEAN_VERIFIER_SHA,
        "primary_zip_verifier_report_digest": CLEAN_VERIFIER_SHA,
        "comparison_zip_verifier_report_digest": CLEAN_VERIFIER_SHA,
        "prepared_record_id": "record-handoff-prepared",
        "review_record_id": "record-handoff-reviewed",
        "reference_contract": contract,
        **({"supersedes_handoff_id": "handoff-20260713-discovery"} if formal else {}),
    }


def _handoff_id(mode: str) -> str:
    return "handoff-" + sha256_bytes(canonical_json_bytes(_handoff_body(mode)))[:20]


def _binding(mode: str) -> dict[str, Any]:
    profile = "DISCOVERY" if mode == "discovery" else "P-AB3"
    return {
        "schema_version": 1,
        "session_id": f"session-20260714-{mode}",
        "session_mode": mode,
        "package_id": "core",
        "profile_id": profile,
        "kit_id": KIT_ID,
        "catalog_sha256": CATALOG_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "manifest_digest": MANIFEST_DIGEST,
        "work_commit": WORK_COMMIT,
        "work_tree": WORK_TREE,
        "handoff_id": _handoff_id(mode),
        "target": "CATIA R2018/VBA7 64",
    }


def _environment_projection(document: dict[str, Any], digest: str) -> dict[str, Any]:
    session = document["session"]
    environment = document["environment"]
    binding = environment["binding"]
    return {
        "anonymous_host_id": session["anonymous_host_id"],
        "vm_lineage_id": session["vm_lineage_id"],
        "snapshot_id": session["snapshot_id"],
        "windows": environment["windows"],
        "catia": environment["catia"],
        "vba": environment["vba"],
        "install_root": {
            "root_kind": environment["catia_environment"]["install_root"]["root_kind"],
            "normalized_path_sha256": environment["catia_environment"]["install_root"]["normalized_path_sha256"],
        },
        "dsls_connection_mode": environment["dsls"]["connection_mode"],
        "profile_id": binding["profile_id"],
        "reference_contract_body_digest": digest,
    }


def _expected_fingerprint(document: dict[str, Any], digest: str) -> str:
    return sha256_bytes(canonical_json_bytes(_environment_projection(document, digest)))


def _observation(
    *,
    stable_id: str | None = STABLE_ID,
    ordinal: int = 1,
    path_sha256: str = RECORD_SHA,
) -> dict[str, Any]:
    unresolved = stable_id is None
    observation = {
        "observation_record_id": "pending.identity",
        "stable_reference_id": stable_id,
        "name": "Unknown" if unresolved else "VBA",
        "description": None if unresolved else "Visual Basic For Applications",
        "guid": None if unresolved else GUID,
        "major": None if unresolved else 4,
        "minor": None if unresolved else 2,
        "source_classification": "unknown" if unresolved else "host-default",
        "missing": False,
        "path_kind": "unknown" if unresolved else "catia-install",
        "path_basename": None if unresolved else "VBE7.DLL",
        "relative_path": None if unresolved else "win_b64/code/bin/VBE7.DLL",
        "redacted_path": "<UNKNOWN>" if unresolved else "<CATIA_INSTALL>/VBE7.DLL",
        "path_sha256": None if unresolved else path_sha256,
        "architecture": "unknown" if unresolved else "x64",
        "release_provenance": "unknown" if unresolved else "B28",
        "operator_record_id": f"record-reference-point-{ordinal:02d}",
    }
    if unresolved:
        raw_identity = {
            key: value
            for key, value in observation.items()
            if key
            not in {
                "observation_record_id",
                "stable_reference_id",
                "operator_record_id",
            }
        }
        observation["observation_record_id"] = (
            "unresolved."
            + sha256_bytes(canonical_json_bytes(raw_identity))[:20]
        )
    else:
        observation["observation_record_id"] = f"record-reference-vba-{ordinal:02d}"
    return observation


def _compile(point: str) -> dict[str, Any]:
    return {
        "record_id": f"record-compile-{point}",
        "point": point,
        "status": "not-run",
        "started_at": None,
        "ended_at": None,
        "catia_operator_record_id": None,
        "vbe_operator_record_id": None,
        "error_stage": None,
        "error_module": None,
        "redacted_error_summary": None,
    }


def _result(case: dict[str, Any], profile: str) -> dict[str, Any]:
    expected = case["expected"]
    return {
        "case_id": case["case_id"],
        "case_definition_sha256": sha256_bytes(canonical_json_bytes(case)),
        "profile_id": profile,
        "package_id": case["package_id"],
        "tool_id": case["tool_id"],
        "execution_point": "not-run",
        "compile_record_id": None,
        "status": "not-run",
        "expected_result_code": expected["result_code"],
        "expected_state": expected.get("state", expected.get("core_state")),
        "observed_result_code": None,
        "observed_state": None,
        "started_at": None,
        "ended_at": None,
        "operator_record_id": None,
        "state_diff_record_id": None,
        "failure_classification": None,
    }


def _operator_record(record_id: str, category: str, captured_at: str = STARTED) -> tuple[dict[str, Any], bytes]:
    payload = f"synthetic redacted witness for {record_id}\n".encode("ascii")
    path = f"operator-records/{record_id}.txt"
    return (
        {
            "record_id": record_id,
            "category": category,
            "relative_path": path,
            "sha256": sha256_bytes(payload),
            "captured_at": captured_at,
            "collector_role": "isolated-builder",
            "redaction_status": "two-person-text",
        },
        payload,
    )


def _documents(mode: str) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    binding = _binding(mode)
    formal = mode != "discovery"
    contract, contract_digest = _reference_contract(approved=formal)
    session = {
        "binding": binding,
        "capture_status": "complete",
        "anonymous_host_id": "host-ab12cd34",
        "vm_lineage_id": "vm-lineage-ab12cd34",
        "snapshot_id": "snapshot-clean-b28",
        "builder_role": "isolated-builder",
        "standard_user_role": "isolated-standard-user",
        "started_at": STARTED,
        "ended_at": ENDED,
        "production_macro_library_touched": False,
        "supersedes_session_id": None,
        "notes_record_id": None,
    }
    environment = {
        "binding": binding,
        "windows": {"edition": "Enterprise", "build": "17763", "patch": "KB5039217"},
        "catia": {
            "release": "V5-6R2018",
            "revision": "R28",
            "build": "B28",
            "ga": True,
            "service_pack": "SP6",
            "hotfix": "HF12",
        },
        "catia_environment": {
            "anonymous_id": "catia-env-ab12cd34",
            "install_root": {
                "root_kind": "catia-install",
                "basename": "B28",
                "relative_path": None,
                "redacted_display": "<CATIA_INSTALL>/B28",
                "normalized_path_sha256": RECORD_SHA,
            },
        },
        "vba": {"ds_vba_version": "7.1", "vbe_version": "7.1", "vba7": True, "win64": True},
        "dsls": {
            "client_anonymous_id": "dsls-client-ab12cd34",
            "server_anonymous_id": "dsls-server-ab12cd34",
            "connection_mode": "network",
        },
        "security": {
            "office_state": "not-installed",
            "network_state": "isolated",
            "powershell_state": "disabled",
            "wsh_state": "disabled",
        },
        "accounts_isolated": True,
        "pollution_scan": {
            "b30": "absent",
            "x86": "absent",
            "vba6": "absent",
            "syswow64": "absent",
            "temp_com": "absent",
            "user_com": "absent",
        },
        "reference_contract_body_digest": contract_digest,
        "environment_fingerprint": "0" * 64,
        "operator_record_id": "record-environment",
    }
    composite = {"session": session, "environment": environment}
    environment["environment_fingerprint"] = _expected_fingerprint(composite, contract_digest)
    plan = _target_plan()
    documents = {
        "session.json": session,
        "environment.json": environment,
        "entitlements.json": {
            "binding": binding,
            **{
                field: {"status": "not-run", "operator_record_id": None}
                for field in (
                    "configuration_product",
                    "reference_visibility",
                    "api_workbench",
                    "session_checkout",
                    "tool_result",
                )
            },
            "baseline_any_of": [] if mode == "discovery" else ["AB3"],
            "additional_required": ["SPA", "FTA"],
            "set_license_used": False,
            "scripted_reference_selection_used": False,
            "licensing_repository_modified": False,
        },
        "references.json": {
            "binding": binding,
            "reference_contract_body_digest": contract_digest,
            "points": [
                {"point": point, "status": "not-run", "observations": [], "operator_record_id": None}
                for point in REFERENCE_POINTS
            ],
        },
        "compile-result.json": {"binding": binding, "records": [_compile(point) for point in COMPILE_POINTS]},
        "test-results.json": {
            "binding": binding,
            "target_plan_sha256": sha256_bytes(canonical_json_bytes(plan)),
            "records": [_result(case, binding["profile_id"]) for case in plan["cases"]],
        },
        "state-diff.json": {"binding": binding, "overall_status": "not-run", "records": []},
        "artifact-manifest.json": {
            "binding": binding,
            "artifact_status": "not-produced",
            "artifact": None,
            "release_eligible": False,
        },
        "operator-records/index.json": {"binding": binding, "records": []},
        "handoff.json": {"handoff_id": binding["handoff_id"], **_handoff_body(mode)},
    }
    members: dict[str, bytes] = {}
    for record_id, category in (
        ("record-environment", "environment"),
        ("record-handoff-prepared", "handoff"),
        ("record-handoff-reviewed", "review"),
    ):
        record, payload = _operator_record(record_id, category)
        documents["operator-records/index.json"]["records"].append(record)
        members[record["relative_path"]] = payload
    return documents, members


def _capture_files(mode: str, *, g2_prerequisite: bytes | None = None) -> dict[str, bytes]:
    documents, members = _documents(mode)
    files = {name: canonical_json_bytes(document) for name, document in documents.items()}
    files.update(members)
    if mode == "g3-c":
        files["prerequisites/g2-evidence.zip"] = g2_prerequisite or _sealed_zip("g2")
    return dict(sorted(files.items()))


def _capture_with_reference_point(
    mode: str,
    *,
    status: str,
    observations: list[dict[str, Any]],
) -> dict[str, bytes]:
    documents, members = _documents(mode)
    point = documents["references.json"]["points"][0]
    point.update(
        status=status,
        observations=observations,
        operator_record_id="record-reference-point-01",
    )
    record_ids = {"record-reference-point-01"}
    record_ids.update(item["operator_record_id"] for item in observations)
    for record_id in sorted(record_ids):
        record, payload = _operator_record(record_id, "reference")
        documents["operator-records/index.json"]["records"].append(record)
        members[record["relative_path"]] = payload
    files = {name: canonical_json_bytes(value) for name, value in documents.items()}
    files.update(members)
    if mode == "g3-c":
        files["prerequisites/g2-evidence.zip"] = _sealed_zip("g2")
    return dict(sorted(files.items()))


def _state_snapshot() -> dict[str, Any]:
    return {
        "active_document_generic_type": "none",
        "saved": None,
        "read_only": None,
        "dirty": None,
        "selection_count": 0,
        "alerts": "enabled",
        "refresh": "enabled",
        "interactivity": "enabled",
        "opened_document_count": 0,
        "closed_document_count": 0,
        "recovered_after_error": True,
        "recovered_after_cancel": True,
        "recovered_after_restart": True,
        "scalar_state_sha256": RECORD_SHA,
    }


def _executed_g3_files() -> dict[str, bytes]:
    documents, members = _documents("g3-c")
    operator_ids: dict[str, str] = {}

    entitlement_statuses = {
        "configuration_product": "observed",
        "reference_visibility": "available",
        "api_workbench": "available",
        "session_checkout": "available",
        "tool_result": "observed",
    }
    for field, status_value in entitlement_statuses.items():
        operator_id = f"record-entitlement-{field.replace('_', '-')}"
        documents["entitlements.json"][field] = {
            "status": status_value,
            "operator_record_id": operator_id,
        }
        operator_ids[operator_id] = "entitlement"

    for ordinal, point in enumerate(documents["references.json"]["points"], start=1):
        operator_id = f"record-reference-point-{ordinal:02d}"
        point.update(
            status="observed",
            observations=[_observation(ordinal=ordinal)],
            operator_record_id=operator_id,
        )
        operator_ids[operator_id] = "reference"

    compile_times = {
        "post-import": ("2026-07-14T12:10:00Z", "2026-07-14T12:11:00Z"),
        "post-save": ("2026-07-14T12:20:00Z", "2026-07-14T12:21:00Z"),
        "post-restart": ("2026-07-14T12:30:00Z", "2026-07-14T12:31:00Z"),
    }
    for record in documents["compile-result.json"]["records"]:
        point = record["point"]
        if point == "blank-project":
            continue
        catia_id = f"record-compile-{point}-catia"
        vbe_id = f"record-compile-{point}-vbe"
        started_at, ended_at = compile_times[point]
        record.update(
            status="passed",
            started_at=started_at,
            ended_at=ended_at,
            catia_operator_record_id=catia_id,
            vbe_operator_record_id=vbe_id,
        )
        operator_ids[catia_id] = "compile"
        operator_ids[vbe_id] = "compile"

    smoke = documents["test-results.json"]["records"][0]
    smoke.update(
        execution_point="post-restart",
        compile_record_id="record-compile-post-restart",
        status="passed",
        observed_result_code=0,
        started_at="2026-07-14T12:32:00Z",
        ended_at="2026-07-14T12:33:00Z",
        operator_record_id="record-test-smoke",
        state_diff_record_id="record-state-diff-smoke",
    )
    operator_ids["record-test-smoke"] = "test"
    documents["state-diff.json"] = {
        "binding": _binding("g3-c"),
        "overall_status": "observed",
        "records": [
            {
                "record_id": "record-state-diff-smoke",
                "case_id": "context.core.healthcheck.none",
                "execution_point": "post-restart",
                "status": "observed",
                "operator_record_id": "record-test-smoke",
                "before": _state_snapshot(),
                "after": _state_snapshot(),
            }
        ],
    }

    artifact = b"synthetic read-only core CATVBA\x00"
    documents["artifact-manifest.json"] = {
        "binding": _binding("g3-c"),
        "artifact_status": "returned",
        "artifact": {
            "relative_path": "returned-catvba/core.catvba",
            "filename": "core.catvba",
            "package_id": "core",
            "sha256": sha256_bytes(artifact),
            "size": len(artifact),
            "post_import_compile_record_id": "record-compile-post-import",
            "post_restart_compile_record_id": "record-compile-post-restart",
            "modules_sha256": CATALOG_SHA,
            "form_frx_sha256": MANIFEST_SHA,
            "reference_observation_sha256": MANIFEST_DIGEST,
            "signature_stream_status": "absent",
            "kit_source_receipt_sha256": RECORD_SHA,
            "readonly": True,
        },
        "release_eligible": False,
    }

    for record_id, category in sorted(operator_ids.items()):
        record, payload = _operator_record(record_id, category)
        documents["operator-records/index.json"]["records"].append(record)
        members[record["relative_path"]] = payload
    files = {name: canonical_json_bytes(value) for name, value in documents.items()}
    files.update(members)
    files["returned-catvba/core.catvba"] = artifact
    files["prerequisites/g2-evidence.zip"] = _sealed_zip("g2")
    return dict(sorted(files.items()))


def _sealed_files(mode: str) -> dict[str, bytes]:
    from catvba_refactor.macro_build.target_evidence.gate import (
        evaluate_gate_rules,
        gate_receipt_document,
    )

    files = _capture_files(mode)
    _, payload_digest, payload_members = canonical_payload_manifest(files)
    gate_id = {"discovery": "DISCOVERY", "g2": "G2", "g3-c": "G3-C"}[mode]
    document_paths = {*ROOT_DOCUMENTS, "handoff.json"}
    inspection = TargetEvidenceInspection(
        report=TargetEvidenceReport(
            phase=EvidencePhase.CAPTURE,
            session_id=_binding(mode)["session_id"],
            evidence_payload_digest=payload_digest,
            payload_members=payload_members,
            diagnostics=(),
        ),
        files=tuple(sorted(files.items())),
        documents=tuple(
            sorted(
                (path, json.loads(data))
                for path, data in files.items()
                if path in document_paths
            )
        ),
        kit=_kit(formal=mode != "discovery"),
    )
    rule_result = evaluate_gate_rules(
        inspection,
        gate_id=gate_id,
        audit_report=None,
    )
    receipt = gate_receipt_document(
        inspection,
        gate_id=gate_id,
        rule_result=rule_result,
        audit_report=None,
    )
    receipt_bytes = canonical_json_bytes(receipt)
    approval_body = {
        "schema_version": 1,
        "session_id": _binding(mode)["session_id"],
        "session_mode": mode,
        "gate_id": gate_id,
        "evidence_payload_digest": payload_digest,
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_scope": "observation" if mode == "discovery" else "gate",
        "approval_status": "approved",
        "reviewer_role": "independent-reviewer",
        "review_record_id": f"record-independent-{mode}-review",
        "approved_at": APPROVED,
    }
    approval = {
        "approval_id": (
            "approval-"
            + sha256_bytes(canonical_json_bytes(approval_body))[:20]
        ),
        **approval_body,
    }
    files["gate-receipt.json"] = receipt_bytes
    files["approval.json"] = canonical_json_bytes(approval)
    bundle_files = dict(sorted(files.items()))
    _, bundle_digest, _ = canonical_payload_manifest(bundle_files)
    sums = "".join(
        f"{sha256_bytes(data)}  {path}\n" for path, data in sorted(bundle_files.items())
    ).encode("ascii")
    completion = {
        "schema_version": 1,
        "session_id": _binding(mode)["session_id"],
        "sealed_at": APPROVED,
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": payload_digest,
        "sha256sums_sha256": sha256_bytes(sums),
        "gate_receipt_sha256": sha256_bytes(files["gate-receipt.json"]),
        "approval_sha256": sha256_bytes(files["approval.json"]),
    }
    files["SHA256SUMS"] = sums
    files["SESSION_COMPLETE"] = canonical_json_bytes(completion)
    return dict(sorted(files.items()))


def _sealed_zip(mode: str) -> bytes:
    return canonical_evidence_zip_bytes(_sealed_files(mode))


def _snapshot(files: dict[str, bytes]) -> EvidenceContainerSnapshot:
    paths = tuple(sorted(files))
    directories = {
        "/".join(path.split("/")[:index])
        for path in paths
        for index in range(1, len(path.split("/")))
    }
    return EvidenceContainerSnapshot(
        files=tuple((path, files[path]) for path in paths),
        directories=tuple(sorted(directories)),
        container_sha256=None,
        diagnostics=(),
    )


def _validate(files: dict[str, bytes], mode: str, phase: EvidencePhase = EvidencePhase.CAPTURE, *, depth: int = 0):
    return validate_target_evidence(
        _snapshot(files),
        _kit(formal=mode != "discovery"),
        phase=phase,
        schema_dir=SCHEMA_DIR,
        nesting_depth=depth,
    )


def _validate_with_kit(
    files: dict[str, bytes],
    mode: str,
    kit: BuildKitInspection,
    phase: EvidencePhase = EvidencePhase.CAPTURE,
):
    return validate_target_evidence(
        _snapshot(files),
        kit,
        phase=phase,
        schema_dir=SCHEMA_DIR,
    )


def _documents_from_files(files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    return {
        path: json.loads(data)
        for path, data in files.items()
        if path.endswith(".json") and path not in {"gate-receipt.json", "approval.json"}
    }


def _replace_json(files: dict[str, bytes], path: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, bytes]:
    changed = dict(files)
    document = json.loads(changed[path])
    mutate(document)
    changed[path] = canonical_json_bytes(document)
    return changed


def _codes(report: object) -> set[str]:
    return {item.code for item in report.diagnostics}  # type: ignore[attr-defined]


def _assert_invalid(report: object, code: str) -> None:
    assert not report.ok  # type: ignore[attr-defined]
    assert code in _codes(report)


@pytest.mark.parametrize("mode", ["discovery", "g2", "g3-c"])
def test_canonical_capture_for_each_mode_is_structurally_valid(mode: str) -> None:
    files = _capture_files(mode)
    report = _validate(files, mode)
    _, expected_digest, expected_members = canonical_payload_manifest(files)

    assert report.ok
    assert report.session_id == _binding(mode)["session_id"]
    assert report.evidence_payload_digest == expected_digest
    assert report.payload_members == expected_members


def test_capture_accepts_truthful_in_progress_unobserved_skeleton() -> None:
    files = _capture_files("discovery")
    documents = _documents_from_files(files)
    documents["session.json"].update(
        capture_status="in-progress",
        anonymous_host_id=None,
        vm_lineage_id=None,
        snapshot_id=None,
        ended_at=None,
    )
    documents["environment.json"].update(
        windows=None,
        catia=None,
        catia_environment=None,
        vba=None,
        dsls=None,
        accounts_isolated=None,
        security={
            "office_state": "unknown",
            "network_state": "unknown",
            "powershell_state": "unknown",
            "wsh_state": "unknown",
        },
        pollution_scan={
            name: "not-run"
            for name in ("b30", "x86", "vba6", "syswow64", "temp_com", "user_com")
        },
        environment_fingerprint=None,
        operator_record_id=None,
    )
    documents["entitlements.json"]["baseline_any_of"] = []
    documents["operator-records/index.json"]["records"] = []
    skeleton = {
        path: canonical_json_bytes(document)
        for path, document in documents.items()
    }

    report = _validate(skeleton, "discovery")

    assert report.ok, report.diagnostics


def test_handoff_record_ids_are_detached_provenance_not_current_operator_links() -> None:
    files = _capture_files("g2")
    index = json.loads(files["operator-records/index.json"])
    detached_ids = {"record-handoff-prepared", "record-handoff-reviewed"}
    removed_paths = {
        record["relative_path"]
        for record in index["records"]
        if record["record_id"] in detached_ids
    }
    index["records"] = [
        record
        for record in index["records"]
        if record["record_id"] not in detached_ids
    ]
    files["operator-records/index.json"] = canonical_json_bytes(index)
    for path in removed_paths:
        del files[path]

    report = _validate(files, "g2")

    assert report.ok, report.diagnostics


def test_directory_and_zip_inputs_have_identical_validation_semantics(
    tmp_path: Path,
) -> None:
    files = _capture_files("discovery")
    directory = tmp_path / "capture"
    for path, data in files.items():
        member = directory / path
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(data)
    zip_path = tmp_path / "capture.zip"
    zip_path.write_bytes(canonical_evidence_zip_bytes(files))

    directory_report = validate_target_evidence(
        directory,
        _kit(formal=False),
        phase=EvidencePhase.CAPTURE,
        schema_dir=SCHEMA_DIR,
    )
    zip_report = validate_target_evidence(
        zip_path,
        _kit(formal=False),
        phase=EvidencePhase.CAPTURE,
        schema_dir=SCHEMA_DIR,
    )

    assert directory_report == zip_report
    assert directory_report.ok


def test_direct_snapshot_rejects_duplicate_member_paths_before_mapping() -> None:
    snapshot = _snapshot(_capture_files("discovery"))
    duplicated = EvidenceContainerSnapshot(
        files=(("session.json", b"forged shadow\n"), *snapshot.files),
        directories=snapshot.directories,
        container_sha256=None,
        diagnostics=(),
    )

    report = validate_target_evidence(
        duplicated,
        _kit(formal=False),
        phase=EvidencePhase.CAPTURE,
        schema_dir=SCHEMA_DIR,
    )

    _assert_invalid(report, "TARGET_EVIDENCE_FILE_POLICY")


@pytest.mark.parametrize("missing", [*ROOT_DOCUMENTS, "handoff.json"])
def test_capture_requires_every_evidence_document(missing: str) -> None:
    files = _capture_files("discovery")
    del files[missing]

    _assert_invalid(_validate(files, "discovery"), "TARGET_EVIDENCE_REQUIRED_FILE")


@pytest.mark.parametrize("filename", ROOT_DOCUMENTS[1:])
def test_all_evidence_documents_share_the_exact_session_binding(filename: str) -> None:
    files = _replace_json(
        _capture_files("g2"), filename, lambda document: document["binding"].__setitem__("kit_id", "kit-ffffffffffffffffffff")
    )

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_BINDING_MISMATCH")


@pytest.mark.parametrize(
    "field",
    [
        "kit_id",
        "catalog_sha256",
        "manifest_sha256",
        "manifest_digest",
        "zip_sha256",
        "work_commit",
        "work_tree",
        "work_branch",
        "upstream_cutoff",
        "fork_dev_cutoff",
    ],
)
def test_handoff_exactly_binds_every_authenticated_kit_identity_field(field: str) -> None:
    replacements = {
        "kit_id": "kit-ffffffffffffffffffff",
        "work_commit": "9" * 40,
        "work_tree": "9" * 40,
        "work_branch": "different/formal-branch",
        "upstream_cutoff": "9" * 40,
        "fork_dev_cutoff": "9" * 40,
    }

    files = _replace_json(
        _capture_files("g2"),
        "handoff.json",
        lambda document: document.__setitem__(
            field, replacements.get(field, REVOKE_SHA)
        ),
    )
    _assert_invalid(
        _validate(files, "g2"), "HANDOFF_KIT_IDENTITY_MISMATCH"
    )


def test_validator_rejects_an_unauthenticated_build_kit_inspection() -> None:
    kit = replace(
        _kit(formal=True),
        report=VerificationReport(ok=False, diagnostics=()),
    )

    _assert_invalid(
        _validate_with_kit(_capture_files("g2"), "g2", kit),
        "TARGET_EVIDENCE_KIT_INVALID",
    )


def test_target_plan_is_read_from_authenticated_inspection_bytes() -> None:
    kit = _kit(formal=True)
    kit_files = dict(kit.files)
    plan = json.loads(kit_files["target-test-plan/target-test-plan.json"])
    plan["cases"][0]["expected"]["result_code"] = 999
    kit_files["target-test-plan/target-test-plan.json"] = canonical_json_bytes(plan)

    _assert_invalid(
        _validate_with_kit(
            _capture_files("g2"),
            "g2",
            replace(kit, files=tuple(sorted(kit_files.items()))),
        ),
        "TARGET_EVIDENCE_TEST_PLAN_MISMATCH",
    )


@pytest.mark.parametrize(
    ("filename", "field", "value"),
    [
        ("references.json", "points", list(reversed(REFERENCE_POINTS))),
        ("compile-result.json", "records", list(reversed(COMPILE_POINTS))),
    ],
)
def test_reference_and_compile_checkpoints_are_exact_and_ordered(filename: str, field: str, value: list[str]) -> None:
    def reorder(document: dict[str, Any]) -> None:
        by_point = {item["point"]: item for item in document[field]}
        document[field] = [by_point[point] for point in value]

    _assert_invalid(
        _validate(_replace_json(_capture_files("discovery"), filename, reorder), "discovery"),
        "TARGET_EVIDENCE_CHECKPOINT_ORDER",
    )


@pytest.mark.parametrize("tamper", ["missing", "extra", "reordered", "unknown", "case-hash", "expected"])
def test_target_results_exactly_bind_all_30_ordered_kit_cases(tamper: str) -> None:
    def mutate(document: dict[str, Any]) -> None:
        records = document["records"]
        if tamper == "missing":
            records.pop()
        elif tamper == "extra":
            records.append(copy.deepcopy(records[-1]))
        elif tamper == "reordered":
            records[0], records[1] = records[1], records[0]
        elif tamper == "unknown":
            records[0]["case_id"] = "context.core.unknown.none"
        elif tamper == "case-hash":
            records[0]["case_definition_sha256"] = RECORD_SHA
        else:
            records[0]["expected_result_code"] = 999

    _assert_invalid(
        _validate(_replace_json(_capture_files("g2"), "test-results.json", mutate), "g2"),
        "TARGET_EVIDENCE_TEST_PLAN_MISMATCH",
    )


@pytest.mark.parametrize(
    ("mode", "filename", "mutate"),
    [
        ("discovery", "session.json", lambda d: d["binding"].__setitem__("profile_id", "P-AB3")),
        ("g2", "session.json", lambda d: d["binding"].__setitem__("profile_id", "DISCOVERY")),
        ("g2", "handoff.json", lambda d: d.__setitem__("purpose", "discovery")),
        ("discovery", "handoff.json", lambda d: d.__setitem__("purpose", "formal")),
        ("g3-c", "handoff.json", lambda d: d.__setitem__("handoff_id", "handoff-cross-kit-formal")),
    ],
)
def test_mode_profile_and_handoff_purpose_are_exact(mode: str, filename: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    _assert_invalid(
        _validate(_replace_json(_capture_files(mode), filename, mutate), mode),
        "TARGET_EVIDENCE_MODE_BINDING",
    )


def test_environment_fingerprint_has_an_independent_known_projection() -> None:
    documents = _documents_from_files(_capture_files("g2"))
    environment = documents["environment.json"]
    document = {
        "session": documents["session.json"],
        "environment": environment,
    }
    digest = environment["reference_contract_body_digest"]

    assert environment_fingerprint(document, digest) == _expected_fingerprint(document, digest)


def test_non_null_environment_fingerprint_requires_all_session_identity_inputs() -> None:
    files = _capture_files("g2")
    session = json.loads(files["session.json"])
    environment = json.loads(files["environment.json"])
    for field in ("anonymous_host_id", "vm_lineage_id", "snapshot_id"):
        session[field] = None
    environment["environment_fingerprint"] = environment_fingerprint(
        {"session": session, "environment": environment},
        environment["reference_contract_body_digest"],
    )
    files["session.json"] = canonical_json_bytes(session)
    files["environment.json"] = canonical_json_bytes(environment)

    _assert_invalid(
        _validate(files, "g2"),
        "TARGET_EVIDENCE_FINGERPRINT_MISMATCH",
    )


@pytest.mark.parametrize("field", ["windows", "catia", "vba", "catia_environment", "dsls"])
def test_environment_fingerprint_detects_every_governed_environment_family(field: str) -> None:
    def mutate(document: dict[str, Any]) -> None:
        if field == "windows":
            document[field]["patch"] = "KB0000000"
        elif field == "catia":
            document[field]["hotfix"] = "HF99"
        elif field == "vba":
            document[field]["vbe_version"] = "7.2"
        elif field == "catia_environment":
            document[field]["install_root"]["normalized_path_sha256"] = REVOKE_SHA
        else:
            document[field]["connection_mode"] = "local"

    _assert_invalid(
        _validate(_replace_json(_capture_files("g2"), "environment.json", mutate), "g2"),
        "TARGET_EVIDENCE_FINGERPRINT_MISMATCH",
    )


def test_environment_fingerprint_excludes_operator_and_transient_checkout_facts() -> None:
    documents, _ = _documents("g2")
    environment = documents["environment.json"]
    digest = environment["reference_contract_body_digest"]
    document = {"session": documents["session.json"], "environment": environment}
    baseline = environment_fingerprint(document, digest)
    changed = copy.deepcopy(document)
    changed["environment"]["operator_record_id"] = "record-another-environment"
    changed["session"]["started_at"] = "2026-07-14T12:15:00Z"
    changed["session"]["ended_at"] = "2026-07-14T12:45:00Z"
    changed["session"]["notes_record_id"] = "record-session-notes"
    documents["entitlements.json"]["session_checkout"] = {"status": "failed", "operator_record_id": "record-checkout"}

    assert environment_fingerprint(changed, digest) == baseline


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("session", "anonymous_host_id", "host-different-99"),
        ("session", "vm_lineage_id", "vm-lineage-different-99"),
        ("session", "snapshot_id", "snapshot-different-b28"),
        ("environment", "profile_id", "P-HD2"),
    ],
)
def test_environment_fingerprint_includes_session_lineage_and_profile(
    section: str, field: str, value: str
) -> None:
    documents, _ = _documents("g2")
    environment = documents["environment.json"]
    digest = environment["reference_contract_body_digest"]
    document = {"session": documents["session.json"], "environment": environment}
    changed = copy.deepcopy(document)
    if section == "environment":
        changed["environment"]["binding"][field] = value
    else:
        changed[section][field] = value

    assert environment_fingerprint(changed, digest) != environment_fingerprint(
        document, digest
    )


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        ("session.json", lambda d: d.__setitem__("ended_at", "2026-07-14T11:59:59Z")),
        ("handoff.json", lambda d: d.__setitem__("created_at", "2026-07-14T12:30:00Z")),
        ("handoff.json", lambda d: d.__setitem__("expires_at", "2026-07-14T12:30:00Z")),
    ],
)
def test_session_and_handoff_times_must_be_monotonic(filename: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    _assert_invalid(
        _validate(_replace_json(_capture_files("discovery"), filename, mutate), "discovery"),
        "TARGET_EVIDENCE_TIME_ORDER",
    )


def test_operator_index_must_resolve_each_record_to_exact_member_bytes() -> None:
    files = _capture_files("g2")
    del files["operator-records/record-environment.txt"]

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_RECORD_LINK")


def test_operator_index_rejects_unindexed_or_hash_mismatched_members() -> None:
    files = _capture_files("g2")
    files["operator-records/unindexed.txt"] = b"not declared\n"

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_RECORD_LINK")


def test_operator_index_rejects_a_forged_member_hash() -> None:
    files = _replace_json(
        _capture_files("g2"),
        "operator-records/index.json",
        lambda document: document["records"][0].__setitem__("sha256", RECORD_SHA),
    )

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_RECORD_LINK")


def test_operator_capture_time_must_fall_within_the_session_window() -> None:
    files = _replace_json(
        _capture_files("g2"),
        "operator-records/index.json",
        lambda document: document["records"][0].__setitem__(
            "captured_at", "2026-07-14T11:59:59Z"
        ),
    )

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_TIME_ORDER")


@pytest.mark.parametrize(
    ("mode", "path", "present"),
    [
        ("g2", "returned-catvba/core.catvba", False),
        ("discovery", "prerequisites/g2-evidence.zip", False),
        ("g2", "prerequisites/g2-evidence.zip", False),
        ("g3-c", "prerequisites/g2-evidence.zip", True),
    ],
)
def test_mode_conditional_artifact_and_prerequisite_files(mode: str, path: str, present: bool) -> None:
    files = _capture_files(mode)
    if present:
        del files[path]
    else:
        files[path] = b"unexpected"

    _assert_invalid(_validate(files, mode), "TARGET_EVIDENCE_FILE_POLICY")


def test_returned_artifact_requires_exact_manifest_hash_size_and_readonly_path() -> None:
    artifact = b"synthetic CATVBA bytes"
    files = _capture_files("discovery")
    files["returned-catvba/core.catvba"] = artifact

    _assert_invalid(_validate(files, "discovery"), "TARGET_EVIDENCE_ARTIFACT_MISMATCH")


def test_executed_g3_capture_closes_compile_test_state_and_returned_artifact_links() -> None:
    assert _validate(_executed_g3_files(), "g3-c").ok


def test_compile_checkpoints_must_remain_monotonic_across_records() -> None:
    def move_post_import_after_restart(document: dict[str, Any]) -> None:
        document["records"][1].update(
            started_at="2026-07-14T12:40:00Z",
            ended_at="2026-07-14T12:41:00Z",
        )

    _assert_invalid(
        _validate(
            _replace_json(
                _executed_g3_files(),
                "compile-result.json",
                move_post_import_after_restart,
            ),
            "g3-c",
        ),
        "TARGET_EVIDENCE_TIME_ORDER",
    )


def test_compile_checkpoint_record_ids_are_explicit_and_unique() -> None:
    def duplicate_compile_identity(document: dict[str, Any]) -> None:
        document["records"][2]["record_id"] = document["records"][1]["record_id"]

    _assert_invalid(
        _validate(
            _replace_json(
                _executed_g3_files(),
                "compile-result.json",
                duplicate_compile_identity,
            ),
            "g3-c",
        ),
        "TARGET_EVIDENCE_RECORD_LINK",
    )


def test_compile_event_ids_cannot_alias_operator_witness_ids() -> None:
    files = _executed_g3_files()

    def alias_event_to_witness(document: dict[str, Any]) -> None:
        document["records"][1]["record_id"] = "record-compile-post-import-vbe"

    files = _replace_json(files, "compile-result.json", alias_event_to_witness)
    files = _replace_json(
        files,
        "artifact-manifest.json",
        lambda document: document["artifact"].__setitem__(
            "post_import_compile_record_id", "record-compile-post-import-vbe"
        ),
    )

    _assert_invalid(
        _validate(files, "g3-c"),
        "TARGET_EVIDENCE_RECORD_LINK",
    )


@pytest.mark.parametrize(
    ("filename", "mutate", "code"),
    [
        (
            "compile-result.json",
            lambda document: document["records"][1].__setitem__(
                "ended_at", "2026-07-14T12:09:59Z"
            ),
            "TARGET_EVIDENCE_TIME_ORDER",
        ),
        (
            "test-results.json",
            lambda document: document["records"][0].__setitem__(
                "started_at", "2026-07-14T12:31:00Z"
            ),
            "TARGET_EVIDENCE_TIME_ORDER",
        ),
        (
            "test-results.json",
            lambda document: document["records"][0].__setitem__(
                "compile_record_id", "record-compile-post-save"
            ),
            "TARGET_EVIDENCE_RECORD_LINK",
        ),
        (
            "test-results.json",
            lambda document: document["records"][0].__setitem__(
                "state_diff_record_id", "record-state-diff-other"
            ),
            "TARGET_EVIDENCE_RECORD_LINK",
        ),
        (
            "state-diff.json",
            lambda document: document["records"][0].__setitem__(
                "operator_record_id", "record-compile-post-save-vbe"
            ),
            "TARGET_EVIDENCE_RECORD_LINK",
        ),
    ],
)
def test_executed_record_times_and_bidirectional_links_are_exact(
    filename: str,
    mutate: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    _assert_invalid(
        _validate(_replace_json(_executed_g3_files(), filename, mutate), "g3-c"),
        code,
    )


@pytest.mark.parametrize("field", ["sha256", "size", "post_import_compile_record_id", "post_restart_compile_record_id"])
def test_returned_artifact_manifest_binds_exact_bytes_and_compile_records(field: str) -> None:
    def mutate(document: dict[str, Any]) -> None:
        artifact = document["artifact"]
        if field == "size":
            artifact[field] += 1
        elif field == "sha256":
            artifact[field] = REVOKE_SHA
        else:
            artifact[field] = "record-compile-blank-project"

    _assert_invalid(
        _validate(
            _replace_json(_executed_g3_files(), "artifact-manifest.json", mutate),
            "g3-c",
        ),
        "TARGET_EVIDENCE_ARTIFACT_MISMATCH",
    )


def test_resolved_reference_stable_id_is_recomputed_from_guid_and_version() -> None:
    def mutate(document: dict[str, Any]) -> None:
        point = document["points"][0]
        point.update(status="observed", observations=[_observation(stable_id="ref." + "0" * 32 + ".4.2")], operator_record_id="record-reference-point-01")

    _assert_invalid(
        _validate(_replace_json(_capture_files("discovery"), "references.json", mutate), "discovery"),
        "TARGET_EVIDENCE_REFERENCE_ID_MISMATCH",
    )


def test_schema_invalid_reference_sort_fields_return_diagnostics_not_type_errors() -> None:
    observations = [_observation(ordinal=1), _observation(ordinal=2)]
    observations[0]["stable_reference_id"] = 7

    report = _validate(
        _capture_with_reference_point(
            "discovery", status="failed", observations=observations
        ),
        "discovery",
    )

    _assert_invalid(report, "TARGET_EVIDENCE_SCHEMA_INVALID")


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        (
            "session.json",
            lambda document: document["binding"].__setitem__("session_mode", []),
        ),
        (
            "entitlements.json",
            lambda document: document.__setitem__("baseline_any_of", [["AB3"]]),
        ),
        (
            "environment.json",
            lambda document: document.__setitem__("operator_record_id", []),
        ),
        (
            "handoff.json",
            lambda document: document.__setitem__("purpose", []),
        ),
        (
            "test-results.json",
            lambda document: document["records"][0].__setitem__(
                "state_diff_record_id", []
            ),
        ),
    ],
)
def test_other_schema_invalid_types_return_diagnostics_not_type_errors(
    filename: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    report = _validate(
        _replace_json(_capture_files("g2"), filename, mutate),
        "g2",
    )

    _assert_invalid(report, "TARGET_EVIDENCE_SCHEMA_INVALID")


def test_discovery_preserves_hashed_unresolved_observation_identity() -> None:
    unresolved = _observation(stable_id=None)
    raw_identity = {
        key: value
        for key, value in unresolved.items()
        if key not in {"observation_record_id", "stable_reference_id", "operator_record_id"}
    }

    assert unresolved["observation_record_id"] == (
        "unresolved." + sha256_bytes(canonical_json_bytes(raw_identity))[:20]
    )
    assert _validate(
        _capture_with_reference_point(
            "discovery", status="observed", observations=[unresolved]
        ),
        "discovery",
    ).ok


def test_discovery_rejects_an_unresolved_identity_without_the_exact_raw_identity_hash() -> None:
    unresolved = _observation(stable_id=None)
    unresolved["observation_record_id"] = "unresolved.deadbeef"

    _assert_invalid(
        _validate(
            _capture_with_reference_point(
                "discovery", status="observed", observations=[unresolved]
            ),
            "discovery",
        ),
        "TARGET_EVIDENCE_REFERENCE_ID_MISMATCH",
    )


@pytest.mark.parametrize("point_status", ["blocked", "failed"])
def test_formal_unresolved_identity_is_valid_only_as_explicit_non_observed_business_state(point_status: str) -> None:
    files = _capture_with_reference_point(
        "g2", status=point_status, observations=[_observation(stable_id=None)]
    )
    assert _validate(files, "g2").ok


def test_formal_observed_unresolved_identity_is_structural_tamper() -> None:
    def mutate(document: dict[str, Any]) -> None:
        point = document["points"][0]
        point.update(status="observed", observations=[_observation(stable_id=None)], operator_record_id="record-reference-point-01")

    _assert_invalid(
        _validate(_replace_json(_capture_files("g2"), "references.json", mutate), "g2"),
        "TARGET_EVIDENCE_REFERENCE_ID_MISMATCH",
    )


def test_duplicate_formal_reference_observations_remain_distinct_structurally_valid_records() -> None:
    observations = [
        _observation(ordinal=2, path_sha256=REVOKE_SHA),
        _observation(ordinal=1),
    ]

    assert len(observations) == 2
    assert observations[0]["stable_reference_id"] == observations[1]["stable_reference_id"]
    assert observations[0]["observation_record_id"] != observations[1]["observation_record_id"]
    assert _validate(
        _capture_with_reference_point("g2", status="failed", observations=observations),
        "g2",
    ).ok


def test_reference_observations_use_exact_stable_path_record_sort_order() -> None:
    observations = [
        _observation(ordinal=1),
        _observation(ordinal=2, path_sha256=REVOKE_SHA),
    ]

    _assert_invalid(
        _validate(
            _capture_with_reference_point(
                "discovery", status="failed", observations=observations
            ),
            "discovery",
        ),
        "TARGET_EVIDENCE_REFERENCE_ORDER",
    )


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        ("references.json", lambda d: d["points"][0].update(status="blocked")),
        ("references.json", lambda d: d["points"][0].update(status="failed")),
        ("compile-result.json", lambda d: d["records"][0].update(status="failed", error_stage="compile", redacted_error_summary="synthetic failure")),
        ("compile-result.json", lambda d: d["records"][0].update(status="blocked")),
    ],
)
def test_business_failed_blocked_and_not_run_outcomes_remain_structurally_valid(filename: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    assert _validate(_replace_json(_capture_files("discovery"), filename, mutate), "discovery").ok


@pytest.mark.parametrize(
    ("status", "observed_code", "classification"),
    [("failed", 5, "runtime"), ("blocked", None, "blocked")],
)
def test_executed_smoke_business_failure_is_structurally_valid(
    status: str, observed_code: int | None, classification: str
) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["records"][0].update(
            status=status,
            observed_result_code=observed_code,
            failure_classification=classification,
        )

    assert _validate(
        _replace_json(_executed_g3_files(), "test-results.json", mutate),
        "g3-c",
    ).ok


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        ("compile-result.json", lambda d: d["records"][0].update(started_at=STARTED)),
        ("test-results.json", lambda d: d["records"][0].update(observed_result_code=0)),
        ("references.json", lambda d: d["points"][0].update(observations=[_observation()])),
    ],
)
def test_not_run_records_reject_stale_observation_fields(filename: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    _assert_invalid(
        _validate(_replace_json(_capture_files("discovery"), filename, mutate), "discovery"),
        "TARGET_EVIDENCE_SCHEMA_INVALID",
    )


def test_unsafe_operator_member_path_is_evidence_error() -> None:
    files = _capture_files("g2")
    files["operator-records/../escape.txt"] = b"unsafe"

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_FILE_POLICY")


@pytest.mark.parametrize("forbidden", ["gate-receipt.json", "approval.json", "SHA256SUMS", "SESSION_COMPLETE"])
def test_capture_forbids_receipt_approval_and_seal_members(forbidden: str) -> None:
    files = _capture_files("g2")
    files[forbidden] = b"{}\n" if forbidden != "SHA256SUMS" else b""

    _assert_invalid(_validate(files, "g2"), "TARGET_EVIDENCE_SEAL_FORBIDDEN")


@pytest.mark.parametrize("mode", ["discovery", "g2", "g3-c"])
def test_canonical_sealed_envelope_for_each_mode_is_structurally_valid(mode: str) -> None:
    sealed = _sealed_files(mode)
    capture = _capture_files(mode)
    report = _validate(sealed, mode, EvidencePhase.SEALED)
    _, expected_digest, expected_members = canonical_payload_manifest(capture)

    assert report.ok
    assert report.evidence_payload_digest == expected_digest
    assert report.payload_members == expected_members


@pytest.mark.parametrize(
    ("mode", "field", "value"),
    [
        ("g2", "approval_status", "pending"),
        ("g2", "review_record_id", "record-compile-blank-project"),
        ("g3-c", "review_record_id", "record-independent-g2-review"),
    ],
    ids=["pending-review", "reused-capture-record", "reused-nested-g2-review"],
)
def test_sealed_approval_requires_a_final_independent_review(
    mode: str, field: str, value: str
) -> None:
    sealed = _sealed_files(mode)
    approval = json.loads(sealed["approval.json"])
    approval[field] = value
    approval_body = dict(approval)
    approval_body.pop("approval_id")
    approval["approval_id"] = (
        "approval-"
        + sha256_bytes(canonical_json_bytes(approval_body))[:20]
    )
    receipt_bytes = sealed["gate-receipt.json"]
    approval_bytes = canonical_json_bytes(approval)
    capture = {
        path: data
        for path, data in sealed.items()
        if path
        not in {
            "gate-receipt.json",
            "approval.json",
            "SHA256SUMS",
            "SESSION_COMPLETE",
        }
    }
    bundle_files = {
        **capture,
        "gate-receipt.json": receipt_bytes,
        "approval.json": approval_bytes,
    }
    _, bundle_digest, _ = canonical_payload_manifest(bundle_files)
    sums = "".join(
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(
            bundle_files.items(), key=lambda item: item[0].encode("ascii")
        )
    ).encode("ascii")
    _, payload_digest, _ = canonical_payload_manifest(capture)
    completion = {
        "schema_version": 1,
        "session_id": _binding(mode)["session_id"],
        "sealed_at": approval["approved_at"],
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": payload_digest,
        "sha256sums_sha256": sha256_bytes(sums),
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_sha256": sha256_bytes(approval_bytes),
    }
    candidate = {
        **bundle_files,
        "SHA256SUMS": sums,
        "SESSION_COMPLETE": canonical_json_bytes(completion),
    }

    report = _validate(candidate, mode, EvidencePhase.SEALED)

    assert not report.ok
    assert any(
        item.code == "TARGET_EVIDENCE_HASH_CLOSURE"
        for item in report.diagnostics
    )


def test_sealed_phase_rejects_an_in_progress_capture() -> None:
    files = _replace_json(
        _sealed_files("g2"),
        "session.json",
        lambda document: document.update(
            capture_status="in-progress", ended_at=None
        ),
    )

    _assert_invalid(
        _validate(files, "g2", EvidencePhase.SEALED),
        "TARGET_EVIDENCE_CAPTURE_INCOMPLETE",
    )


@pytest.mark.parametrize("required", ["gate-receipt.json", "approval.json", "SHA256SUMS", "SESSION_COMPLETE"])
def test_sealed_phase_requires_complete_detached_decision_and_envelope(required: str) -> None:
    files = _sealed_files("g2")
    del files[required]

    _assert_invalid(_validate(files, "g2", EvidencePhase.SEALED), "TARGET_EVIDENCE_SEAL_REQUIRED")


@pytest.mark.parametrize("tamper", ["receipt", "approval", "sums-member", "sums-order", "completion"])
def test_sealed_phase_checks_exact_identity_and_sha256_closure(tamper: str) -> None:
    files = _sealed_files("g2")
    if tamper == "receipt":
        files = _replace_json(files, "gate-receipt.json", lambda d: d.__setitem__("kit_id", "kit-ffffffffffffffffffff"))
    elif tamper == "approval":
        files = _replace_json(files, "approval.json", lambda d: d.__setitem__("gate_receipt_sha256", RECORD_SHA))
    elif tamper == "sums-member":
        lines = files["SHA256SUMS"].splitlines(keepends=True)
        files["SHA256SUMS"] = b"".join(lines[1:])
    elif tamper == "sums-order":
        files["SHA256SUMS"] = b"".join(reversed(files["SHA256SUMS"].splitlines(keepends=True)))
    else:
        files = _replace_json(files, "SESSION_COMPLETE", lambda d: d.__setitem__("bundle_content_digest", RECORD_SHA))

    _assert_invalid(_validate(files, "g2", EvidencePhase.SEALED), "TARGET_EVIDENCE_HASH_CLOSURE")


def test_g3_capture_accepts_one_fully_sealed_g2_zip_at_depth_one() -> None:
    assert _validate(_capture_files("g3-c"), "g3-c").ok


def test_g3_snapshot_started_at_depth_one_cannot_add_a_prerequisite_zip() -> None:
    _assert_invalid(
        _validate(_capture_files("g3-c"), "g3-c", depth=1),
        "TARGET_EVIDENCE_NESTING_DEPTH",
    )


@pytest.mark.parametrize("depth", [-1, 2, True])
def test_direct_snapshot_rejects_invalid_nesting_depth_arguments(
    depth: object,
) -> None:
    report = validate_target_evidence(
        _snapshot(_capture_files("discovery")),
        _kit(formal=False),
        phase=EvidencePhase.CAPTURE,
        schema_dir=SCHEMA_DIR,
        nesting_depth=depth,  # type: ignore[arg-type]
    )

    _assert_invalid(report, "TARGET_EVIDENCE_NESTING_DEPTH")


def test_nested_g2_zip_cannot_contain_another_evidence_zip() -> None:
    nested_g2 = _sealed_files("g2")
    nested_g2["prerequisites/g2-evidence.zip"] = _sealed_zip("g2")
    files = _capture_files("g3-c", g2_prerequisite=canonical_evidence_zip_bytes(nested_g2))

    _assert_invalid(_validate(files, "g3-c"), "TARGET_EVIDENCE_NESTING_DEPTH")
