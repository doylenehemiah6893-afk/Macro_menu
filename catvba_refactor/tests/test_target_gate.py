from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

from catvba_refactor.macro_build.audit import (
    AuditReport,
    PCodeSignal,
    ReferenceVerification,
)
from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.errors import EvidenceError
from catvba_refactor.macro_build.model import Diagnostic
from catvba_refactor.macro_build.target_evidence import gate as gate_module
from catvba_refactor.macro_build.target_evidence.container import (
    canonical_evidence_zip_bytes,
    canonical_payload_manifest,
)
from catvba_refactor.macro_build.target_evidence.gate import (
    RULE_VERSION,
    GateRuleResult,
    evaluate_gate_rules,
    evaluate_target_gate,
    gate_receipt_document,
)
from catvba_refactor.macro_build.target_evidence.kit_binding import (
    kit_verifier_report_digest,
)
from catvba_refactor.macro_build.target_evidence.model import (
    ComputedOutcome,
    EvidencePhase,
    GateId,
    TargetEvidenceReport,
)
from catvba_refactor.macro_build.target_evidence.validator import (
    TargetEvidenceInspection,
    validate_target_evidence,
)
from catvba_refactor.tests import test_target_evidence_validator as evidence


def _document_files(
    documents: dict[str, dict[str, Any]], members: dict[str, bytes]
) -> dict[str, bytes]:
    files = {path: canonical_json_bytes(value) for path, value in documents.items()}
    files.update(members)
    return dict(sorted(files.items()))


def _inspection(files: dict[str, bytes], mode: str) -> TargetEvidenceInspection:
    _, payload_digest, payload_members = canonical_payload_manifest(files)
    document_paths = {*evidence.ROOT_DOCUMENTS, "handoff.json"}
    documents = {
        path: json.loads(data)
        for path, data in files.items()
        if path in document_paths
    }
    return TargetEvidenceInspection(
        report=TargetEvidenceReport(
            phase=EvidencePhase.CAPTURE,
            session_id=evidence._binding(mode)["session_id"],
            evidence_payload_digest=payload_digest,
            payload_members=payload_members,
            diagnostics=(),
        ),
        files=tuple(sorted(files.items())),
        documents=tuple(sorted(documents.items())),
        kit=evidence._kit(formal=mode != "discovery"),
    )


def _add_operator_record(
    documents: dict[str, dict[str, Any]],
    members: dict[str, bytes],
    record_id: str,
    category: str,
) -> None:
    if any(
        item["record_id"] == record_id
        for item in documents["operator-records/index.json"]["records"]
    ):
        return
    record, payload = evidence._operator_record(record_id, category)
    documents["operator-records/index.json"]["records"].append(record)
    members[record["relative_path"]] = payload


def _eligible_g2_files() -> dict[str, bytes]:
    documents, members = evidence._documents("g2")
    entitlement_statuses = {
        "configuration_product": "observed",
        "reference_visibility": "available",
        "api_workbench": "available",
        "session_checkout": "available",
        "tool_result": "observed",
    }
    for field, status_value in entitlement_statuses.items():
        record_id = f"record-entitlement-{field.replace('_', '-')}"
        documents["entitlements.json"][field] = {
            "status": status_value,
            "operator_record_id": record_id,
        }
        _add_operator_record(documents, members, record_id, "entitlement")
    documents["entitlements.json"]["licenses"] = evidence._license_records(
        selected="AB3"
    )

    reference_record_id = "record-reference-point-01"
    documents["references.json"]["points"][0].update(
        status="observed",
        observations=[evidence._observation(ordinal=1)],
        operator_record_id=reference_record_id,
    )
    _add_operator_record(documents, members, reference_record_id, "reference")
    documents["operator-records/index.json"]["records"].sort(
        key=lambda item: item["record_id"]
    )
    return _document_files(documents, members)


def _mutated_inspection(
    files: dict[str, bytes],
    mode: str,
    mutate: Callable[[dict[str, dict[str, Any]], dict[str, bytes]], None],
) -> TargetEvidenceInspection:
    members = {
        path: data
        for path, data in files.items()
        if path not in {*evidence.ROOT_DOCUMENTS, "handoff.json"}
    }
    documents = {
        path: json.loads(data)
        for path, data in files.items()
        if path in {*evidence.ROOT_DOCUMENTS, "handoff.json"}
    }
    mutate(documents, members)
    return _inspection(_document_files(documents, members), mode)


def _clean_audit(files: dict[str, bytes]) -> AuditReport:
    artifact = files["returned-catvba/core.catvba"]
    return AuditReport(
        file_sha256=sha256_bytes(artifact),
        streams=(),
        modules=(),
        references=(),
        pcode=PCodeSignal(
            status="not-run",
            returncode=None,
            stdout_sha256=None,
            stderr_sha256=None,
        ),
        diagnostics=(),
        package_id="core",
        reference_verification=ReferenceVerification(
            status="verified",
            contract_body_digest=json.loads(files["references.json"])[
                "reference_contract_body_digest"
            ],
            observation_sha256=evidence.MANIFEST_DIGEST,
            matched_stable_ids=(evidence.STABLE_ID,),
        ),
    )


def _audit_document(report: AuditReport) -> dict[str, Any]:
    """Independent complete projection required by the receipt digest contract."""
    return {
        "file_sha256": report.file_sha256,
        "streams": list(report.streams),
        "modules": list(report.modules),
        "references": list(report.references),
        "pcode": {
            "status": report.pcode.status,
            "returncode": report.pcode.returncode,
            "stdout_sha256": report.pcode.stdout_sha256,
            "stderr_sha256": report.pcode.stderr_sha256,
            "diagnostic_only": report.pcode.diagnostic_only,
        },
        "diagnostics": [
            {
                "code": item.code,
                "path": item.path,
                "message": item.message,
                "details": item.details,
            }
            for item in report.diagnostics
        ],
        "package_id": report.package_id,
        "reference_verification": {
            "status": report.reference_verification.status,
            "contract_body_digest": report.reference_verification.contract_body_digest,
            "observation_sha256": report.reference_verification.observation_sha256,
            "matched_stable_ids": list(
                report.reference_verification.matched_stable_ids
            ),
        },
    }


def _seal_with_receipt(
    capture: dict[str, bytes],
    receipt_bytes: bytes,
    *,
    approval_status: str = "approved",
) -> dict[str, bytes]:
    receipt = json.loads(receipt_bytes)
    files = dict(capture)
    approval_body = {
        "schema_version": 1,
        "session_id": receipt["session_id"],
        "session_mode": receipt["session_mode"],
        "gate_id": receipt["gate_id"],
        "evidence_payload_digest": receipt["evidence_payload_digest"],
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_scope": (
            "observation" if receipt["gate_id"] == "DISCOVERY" else "gate"
        ),
        "approval_status": approval_status,
        "reviewer_role": "independent-reviewer",
        "review_record_id": "record-independent-evidence-review",
        "approved_at": evidence.APPROVED,
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
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(bundle_files.items())
    ).encode("ascii")
    completion = {
        "schema_version": 1,
        "session_id": receipt["session_id"],
        "sealed_at": evidence.APPROVED,
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": receipt["evidence_payload_digest"],
        "sha256sums_sha256": sha256_bytes(sums),
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_sha256": sha256_bytes(files["approval.json"]),
    }
    files["SHA256SUMS"] = sums
    files["SESSION_COMPLETE"] = canonical_json_bytes(completion)
    return dict(sorted(files.items()))


def _reidentified_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    body = dict(receipt)
    body.pop("receipt_id", None)
    body["receipt_id"] = (
        "gate-receipt-" + sha256_bytes(canonical_json_bytes(body))[:20]
    )
    return canonical_json_bytes(body)


def _g3_files_with_prerequisite(prerequisite: dict[str, bytes]) -> dict[str, bytes]:
    files = evidence._executed_g3_files()
    files["prerequisites/g2-evidence.zip"] = canonical_evidence_zip_bytes(prerequisite)
    return dict(sorted(files.items()))


def _diagnostic_keys(result: GateRuleResult) -> tuple[tuple[str, str, str], ...]:
    return tuple((item.code, item.path, item.message) for item in result.diagnostics)


def test_gate_rule_version_is_fixed() -> None:
    assert RULE_VERSION == "b28-g2-g3-c-v1"


@pytest.mark.parametrize("explicit_status", ["observed", "failed", "blocked", "not-run"])
def test_discovery_is_always_blocked_discovery_only(explicit_status: str) -> None:
    files = evidence._capture_files("discovery")
    inspection = _mutated_inspection(
        files,
        "discovery",
        lambda documents, _members: documents["references.json"]["points"][0].__setitem__(
            "status", explicit_status
        ),
    )

    result = evaluate_gate_rules(
        inspection, gate_id=GateId.DISCOVERY, audit_report=None
    )

    assert result.computed_outcome is ComputedOutcome.BLOCKED
    assert result.reason == "discovery-only"


def test_discovery_with_every_license_checked_out_is_still_never_eligible() -> None:
    def all_checked_out(
        documents: dict[str, dict[str, Any]], _members: dict[str, bytes]
    ) -> None:
        documents["entitlements.json"]["licenses"] = {
            license_id: {
                "availability": "observed-available",
                "checkout": "observed-checked-out",
            }
            for license_id in ("AB3", "HD2", "MD2", "SPA", "FTA")
        }

    result = evaluate_gate_rules(
        _mutated_inspection(
            evidence._capture_files("discovery"), "discovery", all_checked_out
        ),
        gate_id=GateId.DISCOVERY,
        audit_report=None,
    )

    assert result.computed_outcome is ComputedOutcome.BLOCKED
    assert result.reason == "discovery-only"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d, _m: d["entitlements.json"].__setitem__(
            "baseline_any_of", ["AB3", "HD2"]
        ),
        lambda d, _m: d["entitlements.json"].__setitem__(
            "baseline_any_of", ["HD2"]
        ),
        lambda d, _m: d["entitlements.json"]["licenses"].pop("AB3"),
        lambda d, _m: d["entitlements.json"]["licenses"]["AB3"].update(
            availability="unknown", checkout="unknown"
        ),
        lambda d, _m: d["entitlements.json"]["licenses"]["HD2"].update(
            availability="observed-available", checkout="observed-checked-out"
        ),
        lambda d, _m: d["entitlements.json"]["licenses"]["SPA"].update(
            availability="observed-unavailable", checkout="not-checked-out"
        ),
        lambda d, _m: d["entitlements.json"]["licenses"]["FTA"].update(
            checkout="not-checked-out"
        ),
    ],
    ids=[
        "multiple-baselines", "profile-mismatch", "missing-baseline",
        "unknown-baseline", "second-baseline-checked-out", "spa-unavailable",
        "fta-not-checked-out",
    ],
)
def test_formal_gate_requires_exact_checked_out_profile_and_spa_fta(
    mutate: Callable[[dict[str, dict[str, Any]], dict[str, bytes]], None]
) -> None:
    result = evaluate_gate_rules(
        _mutated_inspection(_eligible_g2_files(), "g2", mutate),
        gate_id=GateId.G2,
        audit_report=None,
    )

    assert result.computed_outcome is not ComputedOutcome.ELIGIBLE
    assert result.diagnostics


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d, _m: d["session.json"].__setitem__(
            "production_macro_library_touched", True
        ),
        lambda d, _m: d["entitlements.json"]["tool_result"].__setitem__("status", "failed"),
        lambda d, _m: d["entitlements.json"].__setitem__("set_license_used", True),
        lambda d, _m: d["entitlements.json"].__setitem__(
            "scripted_reference_selection_used", True
        ),
        lambda d, _m: d["entitlements.json"].__setitem__(
            "licensing_repository_modified", True
        ),
        lambda d, _m: d["environment.json"]["pollution_scan"].__setitem__("b30", "present"),
        lambda d, _m: d["environment.json"]["security"].__setitem__("office_state", "installed"),
        lambda d, _m: d["references.json"]["points"][0].__setitem__("status", "failed"),
    ],
    ids=[
        "production-touched",
        "entitlement-failed",
        "set-license-used",
        "scripted-reference-selection",
        "licensing-repository-modified",
        "pollution-present",
        "office-installed",
        "reference-failed",
    ],
)
def test_g2_explicit_failure_is_fail(
    mutate: Callable[[dict[str, dict[str, Any]], dict[str, bytes]], None]
) -> None:
    result = evaluate_gate_rules(
        _mutated_inspection(_eligible_g2_files(), "g2", mutate),
        gate_id=GateId.G2,
        audit_report=None,
    )

    assert result.computed_outcome is ComputedOutcome.FAIL
    assert result.reason != "all-rules-satisfied"
    assert result.diagnostics


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d, _m: d["entitlements.json"]["tool_result"].__setitem__("status", "not-run"),
        lambda d, _m: d["environment.json"]["pollution_scan"].__setitem__("b30", "unknown"),
        lambda d, _m: d["environment.json"]["security"].__setitem__("office_state", "unknown"),
        lambda d, _m: d["environment.json"]["dsls"].__setitem__("connection_mode", "unknown"),
        lambda d, _m: d["environment.json"].__setitem__("catia", None),
        lambda d, _m: d["environment.json"].__setitem__("vba", None),
        lambda d, _m: d["environment.json"].__setitem__("accounts_isolated", None),
        lambda d, _m: d["environment.json"].__setitem__("operator_record_id", None),
        lambda d, _m: (
            d["environment.json"].__setitem__("operator_record_id", None),
            d["environment.json"]["catia"].__setitem__("ga", False),
        ),
        lambda d, _m: d["session.json"].update(
            capture_status="in-progress", ended_at=None
        ),
        lambda d, _m: d["references.json"]["points"][0].__setitem__("status", "blocked"),
    ],
    ids=[
        "entitlement-not-run",
        "pollution-unknown",
        "office-unknown",
        "dsls-unknown",
        "catia-not-observed",
        "vba-not-observed",
        "accounts-not-observed",
        "environment-witness-not-recorded",
        "unwitnessed-template-value",
        "capture-in-progress",
        "reference-blocked",
    ],
)
def test_g2_missing_or_unknown_fact_is_blocked(
    mutate: Callable[[dict[str, dict[str, Any]], dict[str, bytes]], None]
) -> None:
    result = evaluate_gate_rules(
        _mutated_inspection(_eligible_g2_files(), "g2", mutate),
        gate_id=GateId.G2,
        audit_report=None,
    )

    assert result.computed_outcome is ComputedOutcome.BLOCKED
    assert result.reason != "all-rules-satisfied"
    assert result.diagnostics


def test_explicit_failure_precedes_downstream_not_run() -> None:
    def mutate(documents: dict[str, dict[str, Any]], _members: dict[str, bytes]) -> None:
        documents["entitlements.json"]["tool_result"]["status"] = "failed"
        documents["references.json"]["points"][0].update(
            status="not-run", observations=[], operator_record_id=None
        )

    result = evaluate_gate_rules(
        _mutated_inspection(_eligible_g2_files(), "g2", mutate),
        gate_id=GateId.G2,
        audit_report=None,
    )

    assert result.computed_outcome is ComputedOutcome.FAIL


def test_complete_g2_rules_are_eligible_with_stable_diagnostics() -> None:
    inspection = _inspection(_eligible_g2_files(), "g2")

    first = evaluate_gate_rules(inspection, gate_id=GateId.G2, audit_report=None)
    second = evaluate_gate_rules(inspection, gate_id=GateId.G2, audit_report=None)

    assert first == second
    assert first.computed_outcome is ComputedOutcome.ELIGIBLE
    assert first.reason == "all-rules-satisfied"
    assert _diagnostic_keys(first) == tuple(sorted(_diagnostic_keys(first)))


@pytest.mark.parametrize(
    ("mutate", "audit_kind", "expected"),
    [
        (lambda d, _m: d["compile-result.json"]["records"][2].__setitem__("status", "failed"), "clean", ComputedOutcome.FAIL),
        (lambda d, _m: d["compile-result.json"]["records"][2].__setitem__("status", "blocked"), "clean", ComputedOutcome.BLOCKED),
        (lambda d, _m: d["test-results.json"]["records"][0].__setitem__("status", "failed"), "clean", ComputedOutcome.FAIL),
        (lambda d, _m: d["test-results.json"]["records"][0].__setitem__("status", "blocked"), "clean", ComputedOutcome.BLOCKED),
        (lambda d, _m: d["references.json"]["points"][4].__setitem__("status", "failed"), "clean", ComputedOutcome.FAIL),
        (lambda d, _m: d["entitlements.json"]["tool_result"].__setitem__("status", "failed"), "clean", ComputedOutcome.FAIL),
        (lambda d, _m: d["entitlements.json"]["tool_result"].__setitem__("status", "not-run"), "clean", ComputedOutcome.BLOCKED),
        (lambda d, _m: d["state-diff.json"].__setitem__("overall_status", "failed"), "clean", ComputedOutcome.FAIL),
        (lambda d, _m: d["state-diff.json"]["records"][0].__setitem__("status", "failed"), "clean", ComputedOutcome.FAIL),
        (lambda d, _m: d["state-diff.json"]["records"][0].__setitem__("status", "blocked"), "clean", ComputedOutcome.BLOCKED),
        (lambda _d, _m: None, "missing", ComputedOutcome.BLOCKED),
        (lambda _d, _m: None, "failed", ComputedOutcome.FAIL),
        (lambda _d, _m: None, "wrong-package", ComputedOutcome.FAIL),
        (lambda _d, _m: None, "wrong-observation", ComputedOutcome.FAIL),
    ],
    ids=[
        "compile-failed",
        "compile-blocked",
        "smoke-failed",
        "smoke-blocked",
        "reference-failed",
        "entitlement-failed",
        "entitlement-not-run",
        "state-overall-failed",
        "state-record-failed",
        "state-record-blocked",
        "audit-missing",
        "audit-failed",
        "audit-wrong-package",
        "audit-wrong-observation",
    ],
)
def test_g3_rule_matrix_has_fail_over_blocked_precedence(
    mutate: Callable[[dict[str, dict[str, Any]], dict[str, bytes]], None],
    audit_kind: str,
    expected: ComputedOutcome,
) -> None:
    files = evidence._executed_g3_files()
    inspection = _mutated_inspection(files, "g3-c", mutate)
    audit = _clean_audit(files)
    if audit_kind == "missing":
        audit = None
    elif audit_kind == "failed":
        audit = replace(
            audit,
            diagnostics=(
                Diagnostic("AUDIT_SOURCE_MISMATCH", "core.catvba", "source differs"),
            ),
        )
    elif audit_kind == "wrong-package":
        audit = replace(audit, package_id="fleet-spa")
    elif audit_kind == "wrong-observation":
        audit = replace(
            audit,
            reference_verification=replace(
                audit.reference_verification,
                observation_sha256="0" * 64,
            ),
        )

    result = evaluate_gate_rules(
        inspection, gate_id=GateId.G3_C, audit_report=audit
    )

    assert result.computed_outcome is expected
    assert result.diagnostics


def test_complete_g3_outer_rules_and_nonblocking_audit_are_eligible(
    tmp_path: Path,
) -> None:
    files = _g3_files_with_prerequisite(_eligible_sealed_g2(tmp_path))
    result = evaluate_gate_rules(
        _inspection(files, "g3-c"),
        gate_id=GateId.G3_C,
        audit_report=_clean_audit(files),
    )

    assert result.computed_outcome is ComputedOutcome.ELIGIBLE
    assert result.reason == "all-rules-satisfied"


def test_diagnostic_only_pcode_does_not_fail_g3_audit(tmp_path: Path) -> None:
    files = _g3_files_with_prerequisite(_eligible_sealed_g2(tmp_path))
    clean = _clean_audit(files)
    diagnostic_only = replace(
        clean,
        pcode=replace(clean.pcode, status="nonzero", returncode=7),
        diagnostics=(
            Diagnostic(
                "PCODE_NONZERO",
                "pcodedmp",
                "diagnostic p-code subprocess returned a nonzero status",
                {"returncode": 7},
            ),
        ),
    )

    result = evaluate_gate_rules(
        _inspection(files, "g3-c"),
        gate_id=GateId.G3_C,
        audit_report=diagnostic_only,
    )
    receipt = gate_receipt_document(
        _inspection(files, "g3-c"),
        gate_id=GateId.G3_C,
        rule_result=result,
        audit_report=diagnostic_only,
    )

    assert result.computed_outcome is ComputedOutcome.ELIGIBLE
    assert receipt["audit_status"] == "verified"
    assert receipt["audit_report_digest"] == sha256_bytes(
        canonical_json_bytes(_audit_document(diagnostic_only))
    )


def test_invalid_capture_writes_no_receipt(tmp_path: Path) -> None:
    files = _eligible_g2_files()
    del files["session.json"]
    output = tmp_path / "receipt-output"

    with pytest.raises(EvidenceError):
        evaluate_target_gate(
            evidence._snapshot(files),
            evidence._kit(formal=True),
            output,
            gate_id=GateId.G2,
            schema_dir=evidence.SCHEMA_DIR,
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("mode", "gate_id"),
    [
        ("discovery", GateId.G2),
        ("discovery", GateId.G3_C),
        ("g2", GateId.DISCOVERY),
        ("g2", GateId.G3_C),
    ],
)
def test_requested_gate_must_exactly_match_session_mode(
    tmp_path: Path, mode: str, gate_id: GateId
) -> None:
    output = tmp_path / "receipt-output"
    files = (
        evidence._capture_files("discovery")
        if mode == "discovery"
        else _eligible_g2_files()
    )

    with pytest.raises(EvidenceError):
        evaluate_target_gate(
            evidence._snapshot(files),
            evidence._kit(formal=mode != "discovery"),
            output,
            gate_id=gate_id,
            schema_dir=evidence.SCHEMA_DIR,
        )

    assert not output.exists()


def test_receipt_is_byte_deterministic_and_binds_all_authenticated_inputs(
    tmp_path: Path,
) -> None:
    files = _eligible_g2_files()
    kit = evidence._kit(formal=True)
    evaluations = [
        evaluate_target_gate(
            evidence._snapshot(files),
            kit,
            tmp_path / f"output-{index}",
            gate_id=GateId.G2,
            schema_dir=evidence.SCHEMA_DIR,
        )
        for index in range(2)
    ]
    receipt_bytes = [Path(item.receipt_path).read_bytes() for item in evaluations]
    receipt = json.loads(receipt_bytes[0])
    _, payload_digest, _ = canonical_payload_manifest(files)

    assert receipt_bytes[0] == receipt_bytes[1]
    assert evaluations[0].receipt_sha256 == sha256_bytes(receipt_bytes[0])
    assert receipt["session_id"] == evidence._binding("g2")["session_id"]
    assert receipt["session_mode"] == "g2"
    assert receipt["gate_id"] == "G2"
    assert receipt["kit_id"] == kit.kit_id
    assert receipt["kit_zip_sha256"] == kit.canonical_zip_sha256
    assert receipt["kit_verifier_report_digest"] == kit_verifier_report_digest(kit)
    assert receipt["evidence_payload_digest"] == payload_digest
    assert receipt["rule_version"] == RULE_VERSION
    assert receipt["computed_outcome"] == "eligible"
    assert receipt["reason"] == "all-rules-satisfied"
    assert receipt["audit_rule_version"] == 1
    assert receipt["audit_status"] == "not-run"
    assert receipt["audit_report_digest"] is None
    assert receipt["release_eligible"] is False


def test_g3_receipt_is_deterministic_with_the_real_audit_boundary(
    tmp_path: Path,
) -> None:
    files = _g3_files_with_prerequisite(_eligible_sealed_g2(tmp_path))

    evaluations = [
        evaluate_target_gate(
            evidence._snapshot(files),
            evidence._kit(formal=True),
            tmp_path / f"g3-output-{index}",
            gate_id=GateId.G3_C,
            schema_dir=evidence.SCHEMA_DIR,
        )
        for index in range(2)
    ]

    assert Path(evaluations[0].receipt_path).read_bytes() == Path(
        evaluations[1].receipt_path
    ).read_bytes()


@pytest.mark.parametrize(
    ("status_value", "expected"),
    [("not-run", ComputedOutcome.BLOCKED), ("failed", ComputedOutcome.FAIL)],
)
def test_fail_and_blocked_still_publish_an_immutable_receipt(
    tmp_path: Path, status_value: str, expected: ComputedOutcome
) -> None:
    files = evidence._capture_files("g2")
    if status_value == "failed":
        files = evidence._replace_json(
            files,
            "entitlements.json",
            lambda document: document["tool_result"].__setitem__("status", "failed"),
        )
    evaluation = evaluate_target_gate(
        evidence._snapshot(files),
        evidence._kit(formal=True),
        tmp_path / "output",
        gate_id=GateId.G2,
        schema_dir=evidence.SCHEMA_DIR,
    )

    assert evaluation.computed_outcome is expected
    assert Path(evaluation.receipt_path).is_file()


@pytest.mark.parametrize(
    ("document_path", "mutate"),
    [
        (
            "session.json",
            lambda document: document.__setitem__(
                "production_macro_library_touched", True
            ),
        ),
        (
            "entitlements.json",
            lambda document: document.__setitem__("set_license_used", True),
        ),
    ],
    ids=["production-touched", "set-license-used"],
)
def test_business_policy_violations_publish_a_fail_receipt(
    tmp_path: Path,
    document_path: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    files = _eligible_g2_files()
    document = json.loads(files[document_path])
    mutate(document)
    files[document_path] = canonical_json_bytes(document)

    evaluation = evaluate_target_gate(
        evidence._snapshot(files),
        evidence._kit(formal=True),
        tmp_path / "policy-fail-receipt",
        gate_id=GateId.G2,
        schema_dir=evidence.SCHEMA_DIR,
    )

    assert evaluation.computed_outcome is ComputedOutcome.FAIL
    assert Path(evaluation.receipt_path).is_file()


def _eligible_sealed_g2(tmp_path: Path, *, approval_status: str = "approved") -> dict[str, bytes]:
    capture = _eligible_g2_files()
    evaluation = evaluate_target_gate(
        evidence._snapshot(capture),
        evidence._kit(formal=True),
        tmp_path / "g2-receipt",
        gate_id=GateId.G2,
        schema_dir=evidence.SCHEMA_DIR,
    )
    return _seal_with_receipt(
        capture,
        Path(evaluation.receipt_path).read_bytes(),
        approval_status=approval_status,
    )


def test_g3_accepts_only_an_eligible_approved_recomputed_g2_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prerequisite = _eligible_sealed_g2(tmp_path)
    files = _g3_files_with_prerequisite(prerequisite)
    expected_artifact = files["returned-catvba/core.catvba"]
    expected_audit = _clean_audit(files)
    seen_path: Path | None = None

    def fake_audit(
        path: os.PathLike[str] | str,
        *,
        expected_kit: object,
        package_id: str,
        reference_observation: object,
    ) -> AuditReport:
        nonlocal seen_path
        seen_path = Path(path)
        assert seen_path.read_bytes() == expected_artifact
        assert stat.S_IMODE(seen_path.stat().st_mode) & 0o222 == 0
        assert expected_kit is evidence._kit(formal=True) or expected_kit == evidence._kit(formal=True)
        assert package_id == "core"
        assert reference_observation == json.loads(files["references.json"])
        return expected_audit

    monkeypatch.setattr(gate_module, "audit_catvba", fake_audit)
    evaluation = evaluate_target_gate(
        evidence._snapshot(files),
        evidence._kit(formal=True),
        tmp_path / "g3-receipt",
        gate_id=GateId.G3_C,
        schema_dir=evidence.SCHEMA_DIR,
    )
    receipt = json.loads(Path(evaluation.receipt_path).read_bytes())

    assert evaluation.computed_outcome is ComputedOutcome.ELIGIBLE
    assert receipt["audit_status"] == "verified"
    assert receipt["audit_report_digest"] == sha256_bytes(
        canonical_json_bytes(_audit_document(expected_audit))
    )
    assert seen_path is not None and not seen_path.exists()


@pytest.mark.parametrize("approval_status", ["pending", "rejected"])
def test_g3_blocks_a_nonapproved_g2_prerequisite(
    tmp_path: Path,
    approval_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prerequisite = _eligible_sealed_g2(tmp_path, approval_status=approval_status)
    files = _g3_files_with_prerequisite(prerequisite)
    monkeypatch.setattr(
        gate_module,
        "audit_catvba",
        lambda *_args, **_kwargs: _clean_audit(files),
    )

    output = tmp_path / "g3-receipt"
    if approval_status == "pending":
        with pytest.raises(EvidenceError, match="TARGET_EVIDENCE_INVALID"):
            evaluate_target_gate(
                evidence._snapshot(files),
                evidence._kit(formal=True),
                output,
                gate_id=GateId.G3_C,
                schema_dir=evidence.SCHEMA_DIR,
            )
        assert not output.exists()
    else:
        evaluation = evaluate_target_gate(
            evidence._snapshot(files),
            evidence._kit(formal=True),
            output,
            gate_id=GateId.G3_C,
            schema_dir=evidence.SCHEMA_DIR,
        )
        assert evaluation.computed_outcome is ComputedOutcome.BLOCKED


def test_sealed_validator_recomputes_and_rejects_a_lying_gate_receipt() -> None:
    capture = evidence._capture_files("g2")
    receipt = json.loads(evidence._sealed_files("g2")["gate-receipt.json"])
    receipt["computed_outcome"] = "eligible"
    receipt["reason"] = "all-rules-satisfied"
    lying_sealed = _seal_with_receipt(capture, _reidentified_receipt_bytes(receipt))

    report = validate_target_evidence(
        evidence._snapshot(lying_sealed),
        evidence._kit(formal=True),
        phase=EvidencePhase.SEALED,
        schema_dir=evidence.SCHEMA_DIR,
    )

    assert not report.ok
    assert any(item.code == "TARGET_EVIDENCE_GATE_MISMATCH" for item in report.diagnostics)


def test_nested_g2_receipt_byte_tamper_is_invalid_input_and_writes_nothing(
    tmp_path: Path,
) -> None:
    prerequisite = _eligible_sealed_g2(tmp_path)
    receipt = json.loads(prerequisite["gate-receipt.json"])
    receipt["computed_outcome"] = "blocked"
    receipt["reason"] = "evidence-incomplete"
    prerequisite = _seal_with_receipt(
        _eligible_g2_files(), _reidentified_receipt_bytes(receipt)
    )
    output = tmp_path / "g3-output"

    with pytest.raises(EvidenceError):
        evaluate_target_gate(
            evidence._snapshot(_g3_files_with_prerequisite(prerequisite)),
            evidence._kit(formal=True),
            output,
            gate_id=GateId.G3_C,
            schema_dir=evidence.SCHEMA_DIR,
        )

    assert not output.exists()
