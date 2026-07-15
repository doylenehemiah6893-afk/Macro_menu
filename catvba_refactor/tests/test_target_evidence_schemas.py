import copy
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from catvba_refactor.macro_build.errors import ConfigError
from catvba_refactor.macro_build.model import Diagnostic
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
from catvba_refactor.macro_build.target_evidence.schemas import (
    load_target_evidence_schemas,
    validate_target_document,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas" / "target_evidence"
SHA = "a" * 64
SHA_B = "b" * 64
GIT = "c" * 40
UTC = "2026-07-14T12:00:00Z"
UTC_LATER = "2026-07-14T12:01:00Z"


def _binding(mode: str = "discovery", profile: str = "DISCOVERY") -> dict:
    return {
        "schema_version": 1,
        "session_id": "session-20260714-001",
        "session_mode": mode,
        "package_id": "core",
        "profile_id": profile,
        "kit_id": "kit-0123456789abcdef0123",
        "catalog_sha256": SHA,
        "manifest_sha256": SHA_B,
        "manifest_digest": SHA,
        "work_commit": GIT,
        "work_tree": SHA_B,
        "handoff_id": "handoff-20260714-001",
        "target": "CATIA R2018/VBA7 64",
    }


def _not_run_test(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "case_definition_sha256": SHA,
        "profile_id": "DISCOVERY",
        "package_id": "core",
        "tool_id": "core.healthcheck",
        "execution_point": "not-run",
        "compile_record_id": None,
        "status": "not-run",
        "expected_result_code": 0,
        "expected_state": None,
        "observed_result_code": None,
        "observed_state": None,
        "started_at": None,
        "ended_at": None,
        "operator_record_id": None,
        "state_diff_record_id": None,
        "failure_classification": None,
    }


def _reference_point(point: str) -> dict:
    return {
        "point": point,
        "status": "not-run",
        "observations": [],
        "operator_record_id": None,
    }


def _compile_record(point: str) -> dict:
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


def _reference_contract(status: str = "discovery-required") -> dict:
    contract = {
        "status": status,
        "contract_id": "reference-contract-core",
        "contract_version": 1,
        "contract_body_digest": SHA,
        "reference_definitions": [],
        "observations": None,
        "transitions": None,
        "path_policy": {
            "allowed_root_kinds": ["catia-install"],
            "allow_user_paths": False,
        },
        "approval": None,
    }
    if status == "approved":
        contract["observations"] = {
            point: []
            for point in (
                "blank-project",
                "post-form-import",
                "post-all-import",
                "post-save",
                "post-restart",
            )
        }
        contract["transitions"] = [
            {
                "from": source,
                "to": target,
                "added": [],
                "removed": [],
            }
            for source, target in zip(
                (
                    "blank-project",
                    "post-form-import",
                    "post-all-import",
                    "post-save",
                ),
                (
                    "post-form-import",
                    "post-all-import",
                    "post-save",
                    "post-restart",
                ),
                strict=True,
            )
        ]
        contract["approval"] = {
            "reference_approval_record_id": "record-reference-approval",
            "reviewer_role": "independent-reviewer",
            "approved_at": UTC,
            "discovery_session_id": "session-20260714-000",
            "discovery_bundle_sha256": SHA,
            "discovery_gate_receipt_sha256": SHA_B,
            "observation_approval_sha256": SHA,
            "approved_contract_body_digest": SHA,
        }
    return contract


def _documents() -> dict[str, dict]:
    binding = _binding()
    test_cases = [
        _not_run_test("context.core.healthcheck.none")
    ] + [_not_run_test(f"reserved.case.{index:02d}") for index in range(1, 30)]
    return {
        "common.schema.json": binding,
        "session.json": {
            "binding": binding,
            "capture_status": "complete",
            "anonymous_host_id": "host-ab12cd34",
            "vm_lineage_id": "vm-lineage-ab12cd34",
            "snapshot_id": "snapshot-clean-b28",
            "builder_role": "isolated-builder",
            "standard_user_role": "isolated-standard-user",
            "started_at": UTC,
            "ended_at": UTC_LATER,
            "production_macro_library_touched": False,
            "supersedes_session_id": None,
            "notes_record_id": None,
        },
        "environment.json": {
            "binding": binding,
            "windows": {
                "edition": "Enterprise",
                "build": "17763",
                "patch": "KB5039217",
            },
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
                    "normalized_path_sha256": SHA,
                },
            },
            "vba": {
                "ds_vba_version": "7.1",
                "vbe_version": "7.1",
                "vba7": True,
                "win64": True,
            },
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
            "reference_contract_body_digest": SHA,
            "environment_fingerprint": SHA_B,
            "operator_record_id": "record-environment-001",
        },
        "entitlements.json": {
            "binding": binding,
            "configuration_product": {
                "status": "observed",
                "operator_record_id": "record-entitlement-product",
            },
            "reference_visibility": {
                "status": "observed",
                "operator_record_id": "record-entitlement-reference",
            },
            "api_workbench": {
                "status": "observed",
                "operator_record_id": "record-entitlement-api",
            },
            "session_checkout": {
                "status": "observed",
                "operator_record_id": "record-entitlement-checkout",
            },
            "tool_result": {
                "status": "observed",
                "operator_record_id": "record-entitlement-tool",
            },
            "baseline_any_of": ["AB3"],
            "additional_required": ["SPA", "FTA"],
            "set_license_used": False,
            "scripted_reference_selection_used": False,
            "licensing_repository_modified": False,
        },
        "references.json": {
            "binding": binding,
            "reference_contract_body_digest": SHA,
            "points": [
                _reference_point(point)
                for point in (
                    "blank-project",
                    "post-form-import",
                    "post-all-import",
                    "post-save",
                    "post-restart",
                )
            ],
        },
        "compile-result.json": {
            "binding": binding,
            "records": [
                _compile_record(point)
                for point in (
                    "blank-project",
                    "post-import",
                    "post-save",
                    "post-restart",
                )
            ],
        },
        "test-results.json": {
            "binding": binding,
            "target_plan_sha256": SHA,
            "records": test_cases,
        },
        "state-diff.json": {
            "binding": binding,
            "overall_status": "not-run",
            "records": [],
        },
        "artifact-manifest.json": {
            "binding": binding,
            "artifact_status": "not-produced",
            "artifact": None,
            "release_eligible": False,
        },
        "operator-records/index.json": {
            "binding": binding,
            "records": [
                {
                    "record_id": "record-environment-001",
                    "category": "environment",
                    "relative_path": "operator-records/environment-001.txt",
                    "sha256": SHA,
                    "captured_at": UTC,
                    "collector_role": "isolated-builder",
                    "redaction_status": "two-person-text",
                }
            ],
        },
        "handoff.json": {
            "schema_version": 1,
            "handoff_id": "handoff-20260714-001",
            "purpose": "discovery",
            "created_at": UTC,
            "expires_at": "2026-07-21T12:00:00Z",
            "revocation_status": "active",
            "revocation_snapshot_sha256": SHA,
            "kit_id": "kit-0123456789abcdef0123",
            "catalog_sha256": SHA,
            "manifest_sha256": SHA_B,
            "manifest_digest": SHA,
            "zip_sha256": SHA_B,
            "zip_sidecar_sha256": SHA,
            "work_commit": GIT,
            "work_tree": SHA_B,
            "work_branch": "codex/dev-review-report",
            "upstream_cutoff": GIT,
            "fork_dev_cutoff": GIT,
            "package_id": "core",
            "target": "CATIA R2018/VBA7 64",
            "compile_status": "not-run",
            "release_eligible": False,
            "generation_command": "macro-menu-build create-target-handoff",
            "primary_directory_verifier_report_digest": SHA,
            "comparison_directory_verifier_report_digest": SHA_B,
            "primary_zip_verifier_report_digest": SHA,
            "comparison_zip_verifier_report_digest": SHA_B,
            "prepared_record_id": "record-handoff-prepared",
            "review_record_id": "record-handoff-reviewed",
            "reference_contract": _reference_contract(),
        },
        "payload-manifest.json": {
            "schema_version": 1,
            "members": [
                {"path": "session.json", "sha256": SHA, "size": 1024},
                {"path": "environment.json", "sha256": SHA_B, "size": 2048},
            ],
        },
        "gate-receipt.json": {
            "schema_version": 1,
            "receipt_id": "gate-receipt-20260714-001",
            "session_id": "session-20260714-001",
            "session_mode": "discovery",
            "gate_id": "DISCOVERY",
            "kit_id": "kit-0123456789abcdef0123",
            "kit_zip_sha256": SHA,
            "kit_verifier_report_digest": SHA_B,
            "evidence_payload_digest": SHA,
            "rule_version": "b28-g2-g3-c-v1",
            "computed_outcome": "blocked",
            "reason": "discovery-only",
            "audit_rule_version": 1,
            "audit_status": "not-run",
            "audit_report_digest": None,
            "diagnostics": [],
            "release_eligible": False,
        },
        "approval.json": {
            "schema_version": 1,
            "approval_id": "approval-20260714-001",
            "session_id": "session-20260714-001",
            "session_mode": "discovery",
            "gate_id": "DISCOVERY",
            "evidence_payload_digest": SHA,
            "gate_receipt_sha256": SHA_B,
            "approval_scope": "observation",
            "approval_status": "approved",
            "reviewer_role": "independent-reviewer",
            "review_record_id": "record-independent-review",
            "approved_at": UTC_LATER,
        },
        "SESSION_COMPLETE": {
            "schema_version": 1,
            "session_id": "session-20260714-001",
            "sealed_at": UTC_LATER,
            "bundle_content_digest": SHA,
            "evidence_payload_digest": SHA_B,
            "sha256sums_sha256": SHA,
            "gate_receipt_sha256": SHA_B,
            "approval_sha256": SHA,
        },
    }


def _state_snapshot() -> dict:
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
        "scalar_state_sha256": SHA,
    }


def _formal_documents(mode: str) -> dict[str, dict]:
    profile = "P-AB3"
    documents = copy.deepcopy(_documents())
    binding = _binding(mode, profile)
    documents["common.schema.json"] = binding
    for filename in (
        "session.json",
        "environment.json",
        "entitlements.json",
        "references.json",
        "compile-result.json",
        "test-results.json",
        "state-diff.json",
        "artifact-manifest.json",
        "operator-records/index.json",
    ):
        documents[filename]["binding"] = copy.deepcopy(binding)
    for record in documents["test-results.json"]["records"]:
        record["profile_id"] = profile

    documents["handoff.json"]["purpose"] = "formal"
    documents["handoff.json"][
        "supersedes_handoff_id"
    ] = "handoff-20260714-discovery"
    documents["handoff.json"]["reference_contract"] = _reference_contract("approved")
    gate_id = "G2" if mode == "g2" else "G3-C"
    documents["gate-receipt.json"].update(
        {
            "session_mode": mode,
            "gate_id": gate_id,
            "computed_outcome": "blocked",
            "reason": "not-run",
        }
    )
    documents["approval.json"].update(
        {
            "session_mode": mode,
            "gate_id": gate_id,
            "approval_scope": "gate",
        }
    )

    if mode == "g3-c":
        for point in documents["references.json"]["points"]:
            point["status"] = "observed"
            point["operator_record_id"] = f"record-reference-{point['point']}"
        for record in documents["compile-result.json"]["records"][1:]:
            record.update(
                {
                    "status": "passed",
                    "started_at": UTC,
                    "ended_at": UTC_LATER,
                    "catia_operator_record_id": f"record-catia-{record['point']}",
                    "vbe_operator_record_id": f"record-vbe-{record['point']}",
                }
            )
        smoke = documents["test-results.json"]["records"][0]
        smoke.update(
            {
                "execution_point": "post-restart",
                "compile_record_id": "compile-post-restart",
                "status": "passed",
                "observed_result_code": 0,
                "observed_state": "clean",
                "started_at": "2026-07-14T12:02:00Z",
                "ended_at": "2026-07-14T12:03:00Z",
                "operator_record_id": "record-test-smoke",
                "state_diff_record_id": "state-diff-smoke",
            }
        )
        documents["state-diff.json"].update(
            {
                "overall_status": "observed",
                "records": [
                    {
                        "record_id": "state-diff-smoke",
                        "case_id": "context.core.healthcheck.none",
                        "execution_point": "post-restart",
                        "status": "observed",
                        "operator_record_id": "record-test-smoke",
                        "before": _state_snapshot(),
                        "after": _state_snapshot(),
                    }
                ],
            }
        )
        documents["artifact-manifest.json"].update(
            {
                "artifact_status": "returned",
                "artifact": {
                    "relative_path": "returned-catvba/core.catvba",
                    "filename": "core.catvba",
                    "package_id": "core",
                    "sha256": SHA,
                    "size": 1024,
                    "post_import_compile_record_id": "compile-post-import",
                    "post_restart_compile_record_id": "compile-post-restart",
                    "modules_sha256": SHA,
                    "form_frx_sha256": SHA_B,
                    "reference_observation_sha256": SHA,
                    "signature_stream_status": "absent",
                    "kit_source_receipt_sha256": SHA_B,
                    "readonly": True,
                },
            }
        )
        documents["gate-receipt.json"].update(
            {
                "computed_outcome": "eligible",
                "reason": "rules-satisfied",
                "audit_status": "verified",
                "audit_report_digest": SHA,
            }
        )
    return documents


@pytest.fixture(scope="module")
def schemas():
    return load_target_evidence_schemas(SCHEMA_DIR)


@pytest.mark.parametrize("filename", sorted(_documents()))
def test_every_schema_accepts_a_canonical_document(schemas, filename: str) -> None:
    assert validate_target_document(filename, _documents()[filename], schemas).ok


def test_public_model_enums_and_reports_are_frozen_and_dictionary_free() -> None:
    assert tuple(EvidencePhase) == (EvidencePhase.CAPTURE, EvidencePhase.SEALED)
    assert [item.value for item in SessionMode] == ["discovery", "g2", "g3-c"]
    assert [item.value for item in GateId] == ["DISCOVERY", "G2", "G3-C"]
    assert [item.value for item in ComputedOutcome] == ["eligible", "fail", "blocked"]

    diagnostic = Diagnostic("CODE", "file.json#/field", "message")
    reports = (
        PayloadMember("session.json", SHA, 1),
        TargetEvidenceReport(EvidencePhase.CAPTURE, None, None, (), (diagnostic,)),
        TargetSessionReceipt(
            "session-20260714-001", "capture", SessionMode.G2, "kit-id", SHA
        ),
        GateEvaluation(
            GateId.G2,
            ComputedOutcome.BLOCKED,
            "not-run",
            SHA,
            "gate-receipt.json",
            SHA_B,
            (diagnostic,),
        ),
        TargetEvidenceBundleReceipt(
            "session-20260714-001", "sealed", "sealed.zip", SHA, SHA_B, SHA
        ),
    )
    assert not TargetEvidenceReport(EvidencePhase.CAPTURE, None, None, (), ()).diagnostics
    for report in reports:
        assert all(not isinstance(getattr(report, item.name), dict) for item in fields(report))
        with pytest.raises(FrozenInstanceError):
            report.__setattr__(fields(report)[0].name, None)


@pytest.mark.parametrize("filename", sorted(_documents()))
def test_every_schema_rejects_extra_and_missing_root_fields(schemas, filename: str) -> None:
    document = copy.deepcopy(_documents()[filename])
    document["unexpected"] = True
    assert not validate_target_document(filename, document, schemas).ok

    document = copy.deepcopy(_documents()[filename])
    document.pop(next(iter(document)))
    assert not validate_target_document(filename, document, schemas).ok


def test_session_binding_rejects_wrong_mode_profile_and_non_utc_time(schemas) -> None:
    wrong_profile = copy.deepcopy(_documents()["session.json"])
    wrong_profile["binding"]["profile_id"] = "P-AB3"
    assert not validate_target_document("session.json", wrong_profile, schemas).ok

    local_time = copy.deepcopy(_documents()["session.json"])
    local_time["started_at"] = "2026-07-14T05:00:00-07:00"
    assert not validate_target_document("session.json", local_time, schemas).ok


@pytest.mark.parametrize(
    ("filename", "path", "bad_value"),
    [
        ("environment.json", ("environment_fingerprint",), "A" * 64),
        ("session.json", ("binding", "session_id"), "../../session"),
        ("handoff.json", ("kit_id",), "kit with spaces"),
    ],
)
def test_digest_and_id_grammars_fail_closed(schemas, filename, path, bad_value) -> None:
    document = copy.deepcopy(_documents()[filename])
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value
    assert not validate_target_document(filename, document, schemas).ok


@pytest.mark.parametrize("filename", ["artifact-manifest.json", "handoff.json", "gate-receipt.json"])
def test_release_eligibility_cannot_be_predeclared(schemas, filename: str) -> None:
    document = copy.deepcopy(_documents()[filename])
    document["release_eligible"] = True
    assert not validate_target_document(filename, document, schemas).ok


def test_discovery_cannot_receive_gate_approval_or_formal_gate_receipt(schemas) -> None:
    approval = copy.deepcopy(_documents()["approval.json"])
    approval["approval_scope"] = "gate"
    assert not validate_target_document("approval.json", approval, schemas).ok

    receipt = copy.deepcopy(_documents()["gate-receipt.json"])
    receipt["gate_id"] = "G2"
    assert not validate_target_document("gate-receipt.json", receipt, schemas).ok


def test_artifact_status_and_file_metadata_must_match(schemas) -> None:
    document = copy.deepcopy(_documents()["artifact-manifest.json"])
    document["artifact_status"] = "returned"
    assert not validate_target_document("artifact-manifest.json", document, schemas).ok

    document["artifact"] = {
        "relative_path": "returned-catvba/not-core.catvba",
        "filename": "not-core.catvba",
        "package_id": "core",
        "sha256": SHA,
        "size": 12,
        "post_import_compile_record_id": "compile-post-import",
        "post_restart_compile_record_id": "compile-post-restart",
        "modules_sha256": SHA,
        "form_frx_sha256": SHA_B,
        "reference_observation_sha256": SHA,
        "signature_stream_status": "absent",
        "kit_source_receipt_sha256": SHA_B,
        "readonly": True,
    }
    assert not validate_target_document("artifact-manifest.json", document, schemas).ok


def test_reference_evidence_requires_all_five_ordered_points(schemas) -> None:
    document = copy.deepcopy(_documents()["references.json"])
    document["points"].pop()
    assert not validate_target_document("references.json", document, schemas).ok

    document = copy.deepcopy(_documents()["references.json"])
    document["points"][0], document["points"][1] = (
        document["points"][1],
        document["points"][0],
    )
    assert not validate_target_document("references.json", document, schemas).ok


@pytest.mark.parametrize("case_count", [29, 31])
def test_results_require_exactly_thirty_cases(schemas, case_count: int) -> None:
    document = copy.deepcopy(_documents()["test-results.json"])
    document["records"] = document["records"][:case_count]
    if case_count == 31:
        document["records"].append(_not_run_test("reserved.case.30"))
    assert len(document["records"]) == case_count
    assert not validate_target_document("test-results.json", document, schemas).ok


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_result_code", 0),
        ("observed_state", "clean"),
        ("compile_record_id", "compile-post-restart"),
        ("operator_record_id", "record-test-smoke"),
        ("state_diff_record_id", "state-diff-smoke"),
        ("started_at", UTC),
    ],
)
def test_not_run_test_records_cannot_retain_observations(schemas, field, value) -> None:
    document = copy.deepcopy(_documents()["test-results.json"])
    document["records"][0][field] = value
    assert not validate_target_document("test-results.json", document, schemas).ok


def test_not_run_compile_records_cannot_retain_error_observations(schemas) -> None:
    document = copy.deepcopy(_documents()["compile-result.json"])
    document["records"][0]["redacted_error_summary"] = "stale error"
    assert not validate_target_document("compile-result.json", document, schemas).ok


def test_compile_checkpoint_requires_an_explicit_event_record_id(schemas) -> None:
    document = copy.deepcopy(_documents()["compile-result.json"])
    del document["records"][0]["record_id"]

    assert not validate_target_document("compile-result.json", document, schemas).ok


def test_g2_compile_records_are_all_not_run(schemas) -> None:
    document = copy.deepcopy(_documents()["compile-result.json"])
    document["binding"] = _binding("g2", "P-AB3")
    document["records"][0].update(
        {
            "status": "passed",
            "started_at": UTC,
            "ended_at": UTC_LATER,
            "catia_operator_record_id": "record-compile-catia",
            "vbe_operator_record_id": "record-compile-vbe",
        }
    )
    assert not validate_target_document("compile-result.json", document, schemas).ok


def test_formal_handoff_requires_complete_reference_approval_provenance(schemas) -> None:
    document = copy.deepcopy(_documents()["handoff.json"])
    document["purpose"] = "formal"
    document["supersedes_handoff_id"] = "handoff-20260714-discovery"
    document["reference_contract"] = _reference_contract("approved")
    assert validate_target_document("handoff.json", document, schemas).ok

    del document["reference_contract"]["approval"]["discovery_bundle_sha256"]
    assert not validate_target_document("handoff.json", document, schemas).ok


@pytest.mark.parametrize(
    ("filename", "mutation"),
    [
        (
            "payload-manifest.json",
            lambda doc: doc["members"].append(
                {"path": "payload-manifest.json", "sha256": SHA, "size": 1}
            ),
        ),
        (
            "payload-manifest.json",
            lambda doc: doc["members"].append(
                {"path": "SESSION_COMPLETE", "sha256": SHA, "size": 1}
            ),
        ),
        (
            "SESSION_COMPLETE",
            lambda doc: doc.update({"session_complete_sha256": SHA}),
        ),
    ],
)
def test_digest_documents_reject_self_reference(schemas, filename, mutation) -> None:
    document = copy.deepcopy(_documents()[filename])
    mutation(document)
    assert not validate_target_document(filename, document, schemas).ok


@pytest.mark.parametrize(
    ("filename", "mutation"),
    [
        ("session.json", lambda doc: doc.update({"username": "alice"})),
        ("session.json", lambda doc: doc.update({"customer_name": "Acme"})),
        ("session.json", lambda doc: doc.update({"machine_full_name": "WS-ACME-01"})),
        (
            "environment.json",
            lambda doc: doc["catia_environment"]["install_root"].update(
                {"redacted_display": "C:\\Users\\alice\\Acme\\B28"}
            ),
        ),
        ("state-diff.json", lambda doc: doc.update({"part_number": "PN-SECRET"})),
        ("state-diff.json", lambda doc: doc.update({"object_name": "CustomerPart"})),
        ("state-diff.json", lambda doc: doc.update({"model_name": "SecretModel"})),
        ("state-diff.json", lambda doc: doc.update({"parameter_name": "SecretParam"})),
        (
            "operator-records/index.json",
            lambda doc: doc["records"][0].update({"redaction_status": "unredacted"}),
        ),
    ],
)
def test_privacy_and_redaction_fields_are_fail_closed(schemas, filename, mutation) -> None:
    document = copy.deepcopy(_documents()[filename])
    mutation(document)
    assert not validate_target_document(filename, document, schemas).ok


def test_validation_diagnostics_use_stable_json_pointers(schemas) -> None:
    document = copy.deepcopy(_documents()["session.json"])
    document["binding"]["session_mode"] = "G2"
    report = validate_target_document("session.json", document, schemas)
    assert [diagnostic.path for diagnostic in report.diagnostics] == [
        "session.json#/binding/session_mode"
    ]
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "TARGET_EVIDENCE_SCHEMA_INVALID"
    ]


def test_loader_checks_every_draft_2020_12_schema(tmp_path: Path) -> None:
    copied = tmp_path / "schemas"
    copied.mkdir()
    for source in SCHEMA_DIR.glob("*.schema.json"):
        (copied / source.name).write_bytes(source.read_bytes())
    bad = json.loads((copied / "common.schema.json").read_text(encoding="utf-8"))
    bad["type"] = "not-a-json-schema-type"
    (copied / "common.schema.json").write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"INVALID_TARGET_EVIDENCE_SCHEMA.*common"):
        load_target_evidence_schemas(copied)


def _copy_schema_family(tmp_path: Path) -> Path:
    copied = tmp_path / "schemas"
    copied.mkdir()
    for source in SCHEMA_DIR.glob("*.schema.json"):
        (copied / source.name).write_bytes(source.read_bytes())
    return copied


def _replace_schema(copied: Path, filename: str, document: dict) -> None:
    (copied / filename).write_text(json.dumps(document), encoding="utf-8")


def test_review_contract_payload_manifest_has_exact_non_self_referential_shape(
    schemas,
) -> None:
    document = _documents()["payload-manifest.json"]
    assert set(document) == {"schema_version", "members"}
    assert validate_target_document("payload-manifest.json", document, schemas).ok

    for forbidden in ("session_id", "evidence_payload_digest"):
        mutated = copy.deepcopy(document)
        mutated[forbidden] = SHA
        assert not validate_target_document(
            "payload-manifest.json", mutated, schemas
        ).ok


@pytest.mark.parametrize(
    "field",
    [
        "revocation_snapshot_sha256",
        "primary_directory_verifier_report_digest",
        "comparison_directory_verifier_report_digest",
        "primary_zip_verifier_report_digest",
        "comparison_zip_verifier_report_digest",
    ],
)
def test_review_contract_handoff_requires_all_authenticated_verifier_digests(
    schemas, field: str
) -> None:
    canonical = _documents()["handoff.json"]
    assert validate_target_document("handoff.json", canonical, schemas).ok

    missing = copy.deepcopy(canonical)
    del missing[field]
    assert not validate_target_document("handoff.json", missing, schemas).ok

    uppercase = copy.deepcopy(canonical)
    uppercase[field] = "A" * 64
    assert not validate_target_document("handoff.json", uppercase, schemas).ok


def test_formal_handoff_requires_valid_supersedes_id_and_discovery_forbids_it(
    schemas,
) -> None:
    discovery = _documents()["handoff.json"]
    assert validate_target_document("handoff.json", discovery, schemas).ok

    formal = copy.deepcopy(discovery)
    formal["purpose"] = "formal"
    formal["reference_contract"] = _reference_contract("approved")
    formal["supersedes_handoff_id"] = "handoff-20260714-discovery"
    assert validate_target_document("handoff.json", formal, schemas).ok

    missing = copy.deepcopy(formal)
    del missing["supersedes_handoff_id"]
    assert not validate_target_document("handoff.json", missing, schemas).ok

    discovery_with_supersedes = copy.deepcopy(discovery)
    discovery_with_supersedes["supersedes_handoff_id"] = formal[
        "supersedes_handoff_id"
    ]
    assert not validate_target_document(
        "handoff.json", discovery_with_supersedes, schemas
    ).ok

    malformed = copy.deepcopy(formal)
    malformed["supersedes_handoff_id"] = "not-a-handoff"
    assert not validate_target_document("handoff.json", malformed, schemas).ok


def test_review_contract_gate_receipt_uses_exact_public_rule_version(schemas) -> None:
    canonical = _documents()["gate-receipt.json"]
    assert canonical["rule_version"] == "b28-g2-g3-c-v1"
    assert validate_target_document("gate-receipt.json", canonical, schemas).ok

    for invalid in (1, "v1", "b28-g2-g3-c-v2"):
        mutated = copy.deepcopy(canonical)
        mutated["rule_version"] = invalid
        assert not validate_target_document("gate-receipt.json", mutated, schemas).ok


@pytest.mark.parametrize(
    "path",
    [
        "bad:name.txt",
        "x/<bad>.txt",
        "x/quoted\".txt",
        "x/pipe|.txt",
        "x/question?.txt",
        "x/star*.txt",
        "CON",
        "aux.txt",
        "x/COM1.log",
        "x/lpt9",
        ".",
        "x/./y.txt",
        "x/../y.txt",
        "x//y.txt",
        "x/name.",
        "x/name ",
        "x\\name.txt",
        "/absolute.txt",
        "客户.txt",
    ],
)
def test_review_contract_common_portable_path_rejects_windows_unsafe_names(
    schemas, path: str
) -> None:
    common = schemas.validators["common.schema.json"]
    path_validator = common.evolve(schema=common.schema["$defs"]["portable_path"])
    assert path_validator.is_valid("operator-records/safe-record.txt")
    assert not path_validator.is_valid(path)


@pytest.mark.parametrize(
    "path",
    [
        "operator-records/../secret.txt",
        "operator-records/CON.txt",
        "operator-records/record.txt.",
        "operator-records/nested//record.txt",
    ],
)
def test_review_contract_operator_paths_reuse_portable_grammar(
    schemas, path: str
) -> None:
    document = copy.deepcopy(_documents()["operator-records/index.json"])
    assert validate_target_document("operator-records/index.json", document, schemas).ok
    document["records"][0]["relative_path"] = path
    assert not validate_target_document(
        "operator-records/index.json", document, schemas
    ).ok


@pytest.mark.parametrize("root_kind", ["user-profile", "customer-root", "temp"])
def test_review_contract_private_environment_roots_cannot_carry_path_data(
    schemas, root_kind: str
) -> None:
    validator = schemas.validators["environment.schema.json"]
    path_validator = validator.evolve(
        schema=validator.schema["$defs"]["path_evidence"]
    )
    private = {
        "root_kind": root_kind,
        "basename": None,
        "relative_path": None,
        "redacted_display": f"<{root_kind.upper().replace('-', '_')}>",
        "normalized_path_sha256": SHA,
    }
    assert path_validator.is_valid(private)

    private["basename"] = "alice"
    private["relative_path"] = "Users/alice/Acme/B28"
    assert not path_validator.is_valid(private)

    private["basename"] = None
    private["relative_path"] = None
    private["redacted_display"] += "/alice/Acme"
    assert not path_validator.is_valid(private)


@pytest.mark.parametrize(
    "root_kind", ["windows-install", "user-profile", "customer-root", "temp", "other"]
)
def test_review_contract_catia_install_root_is_only_public_catia_category(
    schemas, root_kind: str
) -> None:
    document = copy.deepcopy(_documents()["environment.json"])
    document["catia_environment"]["install_root"]["root_kind"] = root_kind
    assert not validate_target_document("environment.json", document, schemas).ok


@pytest.mark.parametrize("mode", ["g2", "g3-c"])
def test_review_contract_complete_formal_mode_schema_family_is_valid(
    schemas, mode: str
) -> None:
    documents = _formal_documents(mode)
    reports = {
        filename: validate_target_document(filename, document, schemas)
        for filename, document in documents.items()
    }
    assert {filename: report.diagnostics for filename, report in reports.items() if not report.ok} == {}
    if mode == "g3-c":
        smoke = documents["test-results.json"]["records"][0]
        assert smoke["status"] == "passed"
        assert smoke["execution_point"] == "post-restart"
        assert smoke["observed_result_code"] == 0


@pytest.mark.parametrize(
    "schema_id",
    [
        "https://schemas.catvba.invalid/target-evidence/shadow.schema.json",
        "https://schemas.catvba.invalid/target-evidence/common.schema.json",
    ],
)
def test_review_contract_loader_rejects_noncanonical_or_duplicate_schema_id(
    tmp_path: Path, schema_id: str
) -> None:
    copied = _copy_schema_family(tmp_path)
    filename = "session.schema.json"
    schema = json.loads((copied / filename).read_text(encoding="utf-8"))
    schema["$id"] = schema_id
    _replace_schema(copied, filename, schema)

    with pytest.raises(ConfigError, match=r"INVALID_TARGET_EVIDENCE_SCHEMA.*session"):
        load_target_evidence_schemas(copied)


def test_review_contract_loader_rejects_nested_shadow_id(tmp_path: Path) -> None:
    copied = _copy_schema_family(tmp_path)
    filename = "session.schema.json"
    schema = json.loads((copied / filename).read_text(encoding="utf-8"))
    schema["$defs"] = {
        "shadow": {
            "$id": "https://schemas.catvba.invalid/target-evidence/common.schema.json",
            "type": "null",
        }
    }
    _replace_schema(copied, filename, schema)

    with pytest.raises(ConfigError, match=r"INVALID_TARGET_EVIDENCE_SCHEMA.*session"):
        load_target_evidence_schemas(copied)


@pytest.mark.parametrize(
    "reference",
    [
        "https://schemas.catvba.invalid/target-evidence/missing.schema.json#/$defs/binding",
        "https://schemas.catvba.invalid/target-evidence/common.schema.json#/$defs/missing",
        "http://[malformed",
    ],
)
def test_review_contract_loader_eagerly_rejects_unresolvable_refs(
    tmp_path: Path, reference: str
) -> None:
    copied = _copy_schema_family(tmp_path)
    filename = "session.schema.json"
    schema = json.loads((copied / filename).read_text(encoding="utf-8"))
    schema["properties"]["binding"]["$ref"] = reference
    _replace_schema(copied, filename, schema)

    with pytest.raises(ConfigError, match=r"INVALID_TARGET_EVIDENCE_SCHEMA.*session"):
        load_target_evidence_schemas(copied)


@pytest.mark.parametrize(
    "dialect",
    [None, "https://schemas.catvba.invalid/unknown-dialect"],
    ids=["missing", "unknown"],
)
def test_review_contract_loader_contains_schema_dialect_errors(
    tmp_path: Path, dialect: str | None
) -> None:
    copied = _copy_schema_family(tmp_path)
    filename = "session.schema.json"
    schema = json.loads((copied / filename).read_text(encoding="utf-8"))
    if dialect is None:
        del schema["$schema"]
    else:
        schema["$schema"] = dialect
    _replace_schema(copied, filename, schema)

    with pytest.raises(ConfigError, match=r"INVALID_TARGET_EVIDENCE_SCHEMA.*session"):
        load_target_evidence_schemas(copied)
