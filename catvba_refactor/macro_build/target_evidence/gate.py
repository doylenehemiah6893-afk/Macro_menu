from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..audit import AuditReport, audit_catvba
from ..canonical import canonical_json_bytes, parse_canonical_json_bytes, sha256_bytes
from ..errors import EvidenceError
from ..handoff import _publish
from ..model import BuildKitInspection, Diagnostic
from .container import EvidenceContainerSnapshot, _read_zip_bytes, read_evidence_container
from .kit_binding import kit_verifier_report_digest
from .model import ComputedOutcome, EvidencePhase, GateEvaluation, GateId


RULE_VERSION = "b28-g2-g3-c-v1"
AUDIT_RULE_VERSION = 1

_MODE_GATE = {"discovery": "DISCOVERY", "g2": "G2", "g3-c": "G3-C"}
_DIAGNOSTIC_ONLY_PCODE_CODES = frozenset(
    {
        "PCODE_NONZERO",
        "PCODE_OUTPUT_TRUNCATED",
        "PCODE_TIMEOUT",
        "PCODE_UNAVAILABLE",
    }
)
_REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)


@dataclass(frozen=True)
class GateRuleResult:
    computed_outcome: ComputedOutcome
    reason: str
    diagnostics: tuple[Diagnostic, ...]


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _diagnostic_document(diagnostic: Diagnostic) -> dict[str, str]:
    return {
        "code": diagnostic.code,
        "path": diagnostic.path,
        "message": diagnostic.message,
    }


def _audit_document(report: AuditReport) -> dict[str, Any]:
    return {
        "file_sha256": report.file_sha256,
        "package_id": report.package_id,
        "streams": list(report.streams),
        "modules": list(report.modules),
        "references": list(report.references),
        "reference_verification": {
            "status": report.reference_verification.status,
            "contract_body_digest": report.reference_verification.contract_body_digest,
            "observation_sha256": report.reference_verification.observation_sha256,
            "matched_stable_ids": list(
                report.reference_verification.matched_stable_ids
            ),
        },
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
    }


def audit_report_digest(report: AuditReport | None) -> str | None:
    return (
        sha256_bytes(canonical_json_bytes(_audit_document(report)))
        if report is not None
        else None
    )


def _rule_result(
    failures: list[Diagnostic], blockers: list[Diagnostic]
) -> GateRuleResult:
    if failures:
        return GateRuleResult(
            ComputedOutcome.FAIL,
            "explicit-failure",
            tuple(sorted(set(failures))),
        )
    if blockers:
        return GateRuleResult(
            ComputedOutcome.BLOCKED,
            "evidence-incomplete",
            tuple(sorted(set(blockers))),
        )
    return GateRuleResult(ComputedOutcome.ELIGIBLE, "all-rules-satisfied", ())


def _status_rule(
    value: object,
    *,
    path: str,
    failures: list[Diagnostic],
    blockers: list[Diagnostic],
    successes: tuple[str, ...] = ("observed", "available", "passed"),
) -> None:
    if value in successes:
        return
    if value == "failed":
        failures.append(
            _diagnostic("GATE_OBSERVED_FAILURE", path, "evidence records a failure")
        )
        return
    if value == "unavailable":
        blockers.append(
            _diagnostic(
                "GATE_CAPABILITY_UNAVAILABLE",
                path,
                "required capability is unavailable",
            )
        )
        return
    blockers.append(
        _diagnostic(
            "GATE_EVIDENCE_INCOMPLETE",
            path,
            "required evidence is blocked, unknown or not run",
        )
    )


def _common_rules(
    documents: Mapping[str, Any],
    failures: list[Diagnostic],
    blockers: list[Diagnostic],
) -> None:
    session = _mapping(documents.get("session.json"))
    environment = _mapping(documents.get("environment.json"))
    entitlements = _mapping(documents.get("entitlements.json"))
    handoff = _mapping(documents.get("handoff.json"))
    if session is None or environment is None or entitlements is None or handoff is None:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "documents",
                "required Gate documents are unavailable",
            )
        )
        return

    if session.get("production_macro_library_touched") is True:
        failures.append(
            _diagnostic(
                "GATE_PRODUCTION_TOUCHED",
                "session.json#/production_macro_library_touched",
                "session touched the Production macro library",
            )
        )
    if session.get("capture_status") != "complete":
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "session.json#/capture_status",
                "capture has not been marked complete",
            )
        )
    if any(
        session.get(field) is None
        for field in ("anonymous_host_id", "vm_lineage_id", "snapshot_id")
    ):
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "session.json",
                "target host, VM lineage or snapshot identity is unobserved",
            )
        )
    if handoff.get("purpose") != "formal":
        blockers.append(
            _diagnostic(
                "GATE_FORMAL_HANDOFF_REQUIRED",
                "handoff.json#/purpose",
                "formal Gate requires a formal handoff",
            )
        )
    contract = _mapping(handoff.get("reference_contract"))
    if contract is None or contract.get("status") != "approved":
        blockers.append(
            _diagnostic(
                "GATE_REFERENCE_CONTRACT_REQUIRED",
                "handoff.json#/reference_contract/status",
                "formal Gate requires an approved Reference contract",
            )
        )

    catia = _mapping(environment.get("catia"))
    vba = _mapping(environment.get("vba"))
    environment_witnessed = environment.get("operator_record_id") is not None
    if not environment_witnessed:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/operator_record_id",
                "current-session environment witness is unavailable",
            )
        )
    if catia is None or catia.get("ga") is None:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/catia/ga",
                "target CATIA environment has not been observed",
            )
        )
    elif catia.get("ga") is not True and environment_witnessed:
        failures.append(
            _diagnostic(
                "GATE_TARGET_MISMATCH",
                "environment.json#/catia/ga",
                "target is not the governed B28 GA environment",
            )
        )
    if vba is None or vba.get("vba7") is None or vba.get("win64") is None:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/vba",
                "target VBA environment has not been observed",
            )
        )
    elif environment_witnessed and (
        vba.get("vba7") is not True or vba.get("win64") is not True
    ):
        failures.append(
            _diagnostic(
                "GATE_TARGET_MISMATCH",
                "environment.json#/vba",
                "target is not VBA7 Win64",
            )
        )
    if environment.get("accounts_isolated") is None:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/accounts_isolated",
                "account isolation has not been observed",
            )
        )
    elif environment.get("accounts_isolated") is not True and environment_witnessed:
        failures.append(
            _diagnostic(
                "GATE_ENVIRONMENT_NOT_ISOLATED",
                "environment.json#/accounts_isolated",
                "builder and standard-user accounts are not isolated",
            )
        )

    pollution = _mapping(environment.get("pollution_scan"))
    if pollution is None:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/pollution_scan",
                "pollution scan is unavailable",
            )
        )
    else:
        for field, value in pollution.items():
            if value == "present" and environment_witnessed:
                failures.append(
                    _diagnostic(
                        "GATE_ENVIRONMENT_POLLUTION",
                        f"environment.json#/pollution_scan/{field}",
                        "forbidden target pollution was observed",
                    )
                )
            elif value != "absent":
                blockers.append(
                    _diagnostic(
                        "GATE_EVIDENCE_INCOMPLETE",
                        f"environment.json#/pollution_scan/{field}",
                        "pollution status is unknown or not run",
                    )
                )

    security = _mapping(environment.get("security"))
    if security is None:
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/security",
                "security isolation evidence is unavailable",
            )
        )
    else:
        office_state = security.get("office_state")
        if office_state == "installed" and environment_witnessed:
            failures.append(
                _diagnostic(
                    "GATE_ENVIRONMENT_NOT_ISOLATED",
                    "environment.json#/security/office_state",
                    "Office is installed in the isolated Core environment",
                )
            )
        elif office_state != "not-installed":
            blockers.append(
                _diagnostic(
                    "GATE_EVIDENCE_INCOMPLETE",
                    "environment.json#/security/office_state",
                    "Office installation state is unknown",
                )
            )
        forbidden = {
            "network_state": "connected",
            "powershell_state": "enabled",
            "wsh_state": "enabled",
        }
        for field, bad_value in forbidden.items():
            value = security.get(field)
            if value == bad_value and environment_witnessed:
                failures.append(
                    _diagnostic(
                        "GATE_ENVIRONMENT_NOT_ISOLATED",
                        f"environment.json#/security/{field}",
                        "target security isolation was explicitly violated",
                    )
                )
            elif value == "unknown":
                blockers.append(
                    _diagnostic(
                        "GATE_EVIDENCE_INCOMPLETE",
                        f"environment.json#/security/{field}",
                        "target security state is unknown",
                    )
                )

    dsls = _mapping(environment.get("dsls"))
    if dsls is None or dsls.get("connection_mode") == "unknown":
        blockers.append(
            _diagnostic(
                "GATE_EVIDENCE_INCOMPLETE",
                "environment.json#/dsls/connection_mode",
                "DSLS connection mode is unknown",
            )
        )

    for field in (
        "configuration_product",
        "reference_visibility",
        "api_workbench",
        "session_checkout",
        "tool_result",
    ):
        record = _mapping(entitlements.get(field))
        _status_rule(
            record.get("status") if record is not None else None,
            path=f"entitlements.json#/{field}/status",
            failures=failures,
            blockers=blockers,
        )
    for field in (
        "set_license_used",
        "scripted_reference_selection_used",
        "licensing_repository_modified",
    ):
        if entitlements.get(field) is True:
            failures.append(
                _diagnostic(
                    "GATE_FORBIDDEN_LICENSE_ACTION",
                    f"entitlements.json#/{field}",
                    "session used a forbidden license or Reference mutation",
                )
            )
    baseline = entitlements.get("baseline_any_of")
    profile = _mapping(session.get("binding"))
    profile_id = profile.get("profile_id") if profile is not None else None
    selected = {
        "P-AB3": "AB3",
        "P-HD2": "HD2",
        "P-MD2": "MD2",
    }.get(profile_id)
    licenses = _mapping(entitlements.get("licenses"))
    exact_keys = {"AB3", "HD2", "MD2", "SPA", "FTA"}
    if (
        selected is None
        or type(baseline) is not list
        or baseline != [selected]
        or licenses is None
        or set(licenses) != exact_keys
    ):
        blockers.append(
            _diagnostic(
                "GATE_ENTITLEMENT_BASELINE_UNOBSERVED",
                "entitlements.json#/licenses",
                "exact formal license selection has not been observed",
            )
        )
    else:
        for license_id in (selected, "SPA", "FTA"):
            record = _mapping(licenses.get(license_id))
            if (
                record is None
                or record.get("availability") != "observed-available"
                or record.get("checkout") != "observed-checked-out"
            ):
                blockers.append(
                    _diagnostic(
                        "GATE_ENTITLEMENT_NOT_CHECKED_OUT",
                        f"entitlements.json#/licenses/{license_id}",
                        "required license is not observed available and checked out",
                    )
                )
        for license_id in ({"AB3", "HD2", "MD2"} - {selected}):
            record = _mapping(licenses.get(license_id))
            if record is not None and record.get("checkout") == "observed-checked-out":
                blockers.append(
                    _diagnostic(
                        "GATE_ENTITLEMENT_MULTIPLE_BASELINES",
                        f"entitlements.json#/licenses/{license_id}/checkout",
                        "more than one baseline license is checked out",
                    )
                )


def _reference_rules(
    documents: Mapping[str, Any],
    *,
    required_points: int,
    failures: list[Diagnostic],
    blockers: list[Diagnostic],
) -> None:
    references = _mapping(documents.get("references.json"))
    handoff = _mapping(documents.get("handoff.json"))
    contract = _mapping(handoff.get("reference_contract")) if handoff is not None else None
    expected = _mapping(contract.get("observations")) if contract is not None else None
    points = references.get("points") if references is not None else None
    if type(points) is not list or expected is None:
        blockers.append(
            _diagnostic(
                "GATE_REFERENCE_INCOMPLETE",
                "references.json#/points",
                "Reference evidence or approved point contract is unavailable",
            )
        )
        return
    for index, point_name in enumerate(_REFERENCE_POINTS[:required_points]):
        point = _mapping(points[index]) if index < len(points) else None
        if point is None:
            blockers.append(
                _diagnostic(
                    "GATE_REFERENCE_INCOMPLETE",
                    f"references.json#/points/{index}",
                    "required Reference point is missing",
                )
            )
            continue
        status = point.get("status")
        if status == "failed":
            failures.append(
                _diagnostic(
                    "GATE_REFERENCE_FAILURE",
                    f"references.json#/points/{index}/status",
                    "Reference observation explicitly failed",
                )
            )
            continue
        if status != "observed":
            blockers.append(
                _diagnostic(
                    "GATE_REFERENCE_INCOMPLETE",
                    f"references.json#/points/{index}/status",
                    "Reference observation is blocked or not run",
                )
            )
            continue
        observations = point.get("observations")
        if type(observations) is not list:
            blockers.append(
                _diagnostic(
                    "GATE_REFERENCE_INCOMPLETE",
                    f"references.json#/points/{index}/observations",
                    "Reference observations are unavailable",
                )
            )
            continue
        stable_ids = [
            observation.get("stable_reference_id")
            for observation in observations
            if type(observation) is dict
        ]
        if len(stable_ids) != len(set(stable_ids)):
            failures.append(
                _diagnostic(
                    "GATE_REFERENCE_DUPLICATE",
                    f"references.json#/points/{index}/observations",
                    "duplicate stable Reference IDs were observed",
                )
            )
        for observation_index, observation in enumerate(observations):
            if type(observation) is not dict:
                continue
            path = f"references.json#/points/{index}/observations/{observation_index}"
            if (
                observation.get("missing") is True
                or observation.get("architecture") == "x86"
                or observation.get("release_provenance") == "B30"
                or observation.get("path_kind") in ("user-profile", "temp")
            ):
                failures.append(
                    _diagnostic(
                        "GATE_REFERENCE_POLLUTION",
                        path,
                        "forbidden or missing Reference was observed",
                    )
                )
            if (
                observation.get("stable_reference_id") is None
                or observation.get("architecture") == "unknown"
                or observation.get("release_provenance") == "unknown"
                or observation.get("path_kind") == "unknown"
            ):
                blockers.append(
                    _diagnostic(
                        "GATE_REFERENCE_INCOMPLETE",
                        path,
                        "Reference identity or provenance remains unknown",
                    )
                )
        expected_ids = expected.get(point_name)
        if type(expected_ids) is not list:
            blockers.append(
                _diagnostic(
                    "GATE_REFERENCE_INCOMPLETE",
                    f"handoff.json#/reference_contract/observations/{point_name}",
                    "approved Reference point is unavailable",
                )
            )
        elif stable_ids != expected_ids:
            failures.append(
                _diagnostic(
                    "GATE_REFERENCE_CONTRACT_MISMATCH",
                    f"references.json#/points/{index}/observations",
                    "observed Reference set differs from the approved contract",
                )
            )


def _nested_decisions(files: Mapping[str, bytes]) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    data = files.get("prerequisites/g2-evidence.zip")
    if data is None:
        return None, None
    snapshot = _read_zip_bytes(
        data,
        phase=EvidencePhase.SEALED,
        nesting_depth=1,
        container_sha256=sha256_bytes(data),
    )
    if snapshot.diagnostics:
        return None, None
    nested_files = dict(snapshot.files)
    try:
        receipt = parse_canonical_json_bytes(nested_files["gate-receipt.json"])
        approval = parse_canonical_json_bytes(nested_files["approval.json"])
    except (KeyError, ValueError):
        return None, None
    return _mapping(receipt), _mapping(approval)


def _g3_rules(
    inspection: Any,
    documents: Mapping[str, Any],
    audit_report: AuditReport | None,
    failures: list[Diagnostic],
    blockers: list[Diagnostic],
) -> None:
    nested_receipt, nested_approval = _nested_decisions(dict(inspection.files))
    if (
        nested_receipt is None
        or nested_receipt.get("gate_id") != "G2"
        or nested_receipt.get("computed_outcome") != "eligible"
        or nested_approval is None
        or nested_approval.get("approval_scope") != "gate"
        or nested_approval.get("approval_status") != "approved"
    ):
        blockers.append(
            _diagnostic(
                "GATE_G2_PREREQUISITE",
                "prerequisites/g2-evidence.zip",
                "G3-C requires eligible and approved sealed G2 evidence",
            )
        )

    compile_document = _mapping(documents.get("compile-result.json"))
    records = compile_document.get("records") if compile_document is not None else None
    if type(records) is not list:
        blockers.append(
            _diagnostic(
                "GATE_COMPILE_INCOMPLETE",
                "compile-result.json#/records",
                "Compile evidence is unavailable",
            )
        )
    else:
        for index in (1, 2, 3):
            record = _mapping(records[index]) if index < len(records) else None
            _status_rule(
                record.get("status") if record is not None else None,
                path=f"compile-result.json#/records/{index}/status",
                failures=failures,
                blockers=blockers,
                successes=("passed",),
            )

    tests = _mapping(documents.get("test-results.json"))
    test_records = tests.get("records") if tests is not None else None
    smoke = _mapping(test_records[0]) if type(test_records) is list and test_records else None
    _status_rule(
        smoke.get("status") if smoke is not None else None,
        path="test-results.json#/records/0/status",
        failures=failures,
        blockers=blockers,
        successes=("passed",),
    )
    if smoke is not None and smoke.get("status") == "passed" and (
        smoke.get("expected_result_code") != 0
        or smoke.get("observed_result_code") != 0
    ):
        failures.append(
            _diagnostic(
                "GATE_SMOKE_MISMATCH",
                "test-results.json#/records/0/observed_result_code",
                "post-restart HealthCheck did not return code zero",
            )
        )

    state = _mapping(documents.get("state-diff.json"))
    state_records = state.get("records") if state is not None else None
    _status_rule(
        state.get("overall_status") if state is not None else None,
        path="state-diff.json#/overall_status",
        failures=failures,
        blockers=blockers,
        successes=("observed",),
    )
    if type(state_records) is not list or not state_records:
        blockers.append(
            _diagnostic(
                "GATE_STATE_INCOMPLETE",
                "state-diff.json#/records",
                "post-restart state evidence is incomplete",
            )
        )
    else:
        for index, record_value in enumerate(state_records):
            record = _mapping(record_value)
            _status_rule(
                record.get("status") if record is not None else None,
                path=f"state-diff.json#/records/{index}/status",
                failures=failures,
                blockers=blockers,
                successes=("observed",),
            )

    artifact_document = _mapping(documents.get("artifact-manifest.json"))
    artifact = (
        _mapping(artifact_document.get("artifact"))
        if artifact_document is not None
        else None
    )
    if artifact_document is None or artifact_document.get("artifact_status") != "returned":
        blockers.append(
            _diagnostic(
                "GATE_ARTIFACT_REQUIRED",
                "artifact-manifest.json#/artifact_status",
                "G3-C requires a returned Core CATVBA",
            )
        )
    elif audit_report is None:
        blockers.append(
            _diagnostic(
                "GATE_AUDIT_REQUIRED",
                "returned-catvba/core.catvba",
                "returned CATVBA audit is unavailable",
            )
        )
    elif artifact is None or audit_report.file_sha256 != artifact.get("sha256"):
        failures.append(
            _diagnostic(
                "GATE_AUDIT_MISMATCH",
                "artifact-manifest.json#/artifact/sha256",
                "audit input does not match the returned artifact",
            )
        )
    else:
        references = _mapping(documents.get("references.json"))
        verification = audit_report.reference_verification
        if (
            audit_report.package_id != "core"
            or references is None
            or verification.contract_body_digest
            != references.get("reference_contract_body_digest")
            or verification.observation_sha256
            != artifact.get("reference_observation_sha256")
        ):
            failures.append(
                _diagnostic(
                    "GATE_AUDIT_MISMATCH",
                    "audit#/reference_verification",
                    "audit identity does not bind the Core Reference evidence",
                )
            )
        if _blocking_audit_diagnostics(audit_report):
            failures.append(
                _diagnostic(
                    "GATE_AUDIT_FAILURE",
                    "returned-catvba/core.catvba",
                    "returned CATVBA audit has blocking diagnostics",
                )
            )
        reference_status = audit_report.reference_verification.status
        if reference_status == "failed":
            failures.append(
                _diagnostic(
                    "GATE_AUDIT_FAILURE",
                    "audit#/reference_verification/status",
                    "returned CATVBA Reference audit failed",
                )
            )
        elif reference_status != "verified":
            blockers.append(
                _diagnostic(
                    "GATE_AUDIT_INCOMPLETE",
                    "audit#/reference_verification/status",
                    "returned CATVBA Reference audit is incomplete",
                )
            )


def evaluate_gate_rules(
    inspection: Any,
    *,
    gate_id: GateId | str,
    audit_report: AuditReport | None,
) -> GateRuleResult:
    if not inspection.report.ok or inspection.report.diagnostics:
        return GateRuleResult(
            ComputedOutcome.BLOCKED,
            "invalid-evidence",
            tuple(sorted(inspection.report.diagnostics)),
        )
    documents = dict(inspection.documents)
    session = _mapping(documents.get("session.json"))
    binding = _mapping(session.get("binding")) if session is not None else None
    mode = binding.get("session_mode") if binding is not None else None
    stable_gate = gate_id.value if isinstance(gate_id, GateId) else gate_id
    if mode == "discovery":
        return GateRuleResult(ComputedOutcome.BLOCKED, "discovery-only", ())
    if type(mode) is not str or _MODE_GATE.get(mode) != stable_gate:
        return GateRuleResult(
            ComputedOutcome.BLOCKED,
            "gate-mode-mismatch",
            (
                _diagnostic(
                    "GATE_MODE_MISMATCH",
                    "session.json#/binding/session_mode",
                    "requested Gate does not match the session mode",
                ),
            ),
        )

    failures: list[Diagnostic] = []
    blockers: list[Diagnostic] = []
    _common_rules(documents, failures, blockers)
    _reference_rules(
        documents,
        required_points=1 if mode == "g2" else 5,
        failures=failures,
        blockers=blockers,
    )
    if mode == "g3-c":
        _g3_rules(inspection, documents, audit_report, failures, blockers)
    return _rule_result(failures, blockers)


def _audit_for_inspection(inspection: Any) -> AuditReport | None:
    documents = dict(inspection.documents)
    artifact_document = _mapping(documents.get("artifact-manifest.json"))
    if artifact_document is None or artifact_document.get("artifact_status") != "returned":
        return None
    files = dict(inspection.files)
    returned = files.get("returned-catvba/core.catvba")
    references = _mapping(documents.get("references.json"))
    if returned is None or references is None:
        return None
    with tempfile.TemporaryDirectory(prefix="catvba-gate-") as temporary:
        path = Path(temporary) / "core.catvba"
        path.write_bytes(returned)
        path.chmod(0o444)
        return audit_catvba(
            path,
            expected_kit=inspection.kit,
            package_id="core",
            reference_observation=references,
        )


def _blocking_audit_diagnostics(report: AuditReport) -> tuple[Diagnostic, ...]:
    if report.pcode.diagnostic_only:
        return tuple(
            item
            for item in report.diagnostics
            if item.code not in _DIAGNOSTIC_ONLY_PCODE_CODES
        )
    return report.diagnostics


def _audit_status(report: AuditReport | None) -> str:
    if report is None:
        return "not-run"
    if (
        _blocking_audit_diagnostics(report)
        or report.reference_verification.status == "failed"
    ):
        return "failed"
    if report.reference_verification.status == "verified":
        return "verified"
    if report.reference_verification.status == "unavailable":
        return "unavailable"
    return "partial"


def gate_receipt_document(
    inspection: Any,
    *,
    gate_id: GateId | str,
    rule_result: GateRuleResult,
    audit_report: AuditReport | None,
) -> dict[str, Any]:
    documents = dict(inspection.documents)
    session = _mapping(documents.get("session.json")) or {}
    binding = _mapping(session.get("binding")) or {}
    if session.get("capture_status") != "complete":
        raise EvidenceError("TARGET_EVIDENCE_CAPTURE_INCOMPLETE")
    stable_gate = gate_id.value if isinstance(gate_id, GateId) else gate_id
    body = {
        "schema_version": 1,
        "session_id": binding.get("session_id"),
        "session_mode": binding.get("session_mode"),
        "gate_id": stable_gate,
        "kit_id": inspection.kit.kit_id,
        "kit_zip_sha256": inspection.kit.canonical_zip_sha256,
        "kit_verifier_report_digest": kit_verifier_report_digest(inspection.kit),
        "evidence_payload_digest": inspection.report.evidence_payload_digest,
        "rule_version": RULE_VERSION,
        "computed_outcome": rule_result.computed_outcome.value,
        "reason": rule_result.reason,
        "audit_rule_version": AUDIT_RULE_VERSION,
        "audit_status": _audit_status(audit_report),
        "audit_report_digest": audit_report_digest(audit_report),
        "diagnostics": [
            _diagnostic_document(item) for item in rule_result.diagnostics
        ],
        "release_eligible": False,
    }
    receipt_id = "gate-receipt-" + sha256_bytes(canonical_json_bytes(body))[:20]
    return {"receipt_id": receipt_id, **body}


def recompute_gate_receipt(inspection: Any) -> tuple[dict[str, Any], AuditReport | None]:
    documents = dict(inspection.documents)
    session = _mapping(documents.get("session.json")) or {}
    binding = _mapping(session.get("binding")) or {}
    mode = binding.get("session_mode")
    gate_id = _MODE_GATE.get(mode) if type(mode) is str else None
    if gate_id is None:
        raise EvidenceError("TARGET_GATE_MODE_INVALID")
    audit_report = _audit_for_inspection(inspection) if mode == "g3-c" else None
    result = evaluate_gate_rules(
        inspection, gate_id=gate_id, audit_report=audit_report
    )
    return (
        gate_receipt_document(
            inspection,
            gate_id=gate_id,
            rule_result=result,
            audit_report=audit_report,
        ),
        audit_report,
    )


def sealed_gate_diagnostics(inspection: Any) -> tuple[Diagnostic, ...]:
    expected, _audit_report = recompute_gate_receipt(inspection)
    files = dict(inspection.files)
    if files.get("gate-receipt.json") == canonical_json_bytes(expected):
        return ()
    return (
        _diagnostic(
            "TARGET_EVIDENCE_GATE_MISMATCH",
            "gate-receipt.json",
            "embedded Gate receipt does not match recomputed Gate semantics",
        ),
    )


def evaluate_target_gate(
    capture: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    output_root: os.PathLike[str] | str,
    *,
    gate_id: GateId | str,
    schema_dir: os.PathLike[str] | str,
) -> GateEvaluation:
    from .validator import _inspect_snapshot

    snapshot = (
        capture
        if isinstance(capture, EvidenceContainerSnapshot)
        else read_evidence_container(capture, phase=EvidencePhase.CAPTURE)
    )
    inspection = _inspect_snapshot(
        snapshot,
        kit,
        phase=EvidencePhase.CAPTURE,
        schema_dir=schema_dir,
        nesting_depth=0,
    )
    if not inspection.report.ok:
        codes = ",".join(item.code for item in inspection.report.diagnostics)
        raise EvidenceError(f"TARGET_EVIDENCE_INVALID:{codes}")
    documents = dict(inspection.documents)
    session = _mapping(documents.get("session.json")) or {}
    binding = _mapping(session.get("binding")) or {}
    if session.get("capture_status") != "complete":
        raise EvidenceError("TARGET_EVIDENCE_CAPTURE_INCOMPLETE")
    stable_gate = gate_id.value if isinstance(gate_id, GateId) else gate_id
    if _MODE_GATE.get(binding.get("session_mode")) != stable_gate:
        raise EvidenceError("TARGET_GATE_MODE_MISMATCH")
    audit_report = (
        _audit_for_inspection(inspection)
        if binding.get("session_mode") == "g3-c"
        else None
    )
    result = evaluate_gate_rules(
        inspection, gate_id=stable_gate, audit_report=audit_report
    )
    document = gate_receipt_document(
        inspection,
        gate_id=stable_gate,
        rule_result=result,
        audit_report=audit_report,
    )
    data = canonical_json_bytes(document)
    path = _publish(output_root, document["receipt_id"], data)
    return GateEvaluation(
        gate_id=GateId(stable_gate),
        computed_outcome=result.computed_outcome,
        reason=result.reason,
        evidence_payload_digest=inspection.report.evidence_payload_digest or "",
        receipt_path=os.fspath(path),
        receipt_sha256=sha256_bytes(data),
        diagnostics=result.diagnostics,
    )
