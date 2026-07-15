from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..canonical import (
    CanonicalJsonError,
    parse_canonical_json_bytes,
    sha256_bytes,
)
from ..model import BuildKitInspection, Diagnostic


@dataclass(frozen=True)
class KitEvidenceBinding:
    """Evidence-relevant values captured from one authenticated Kit snapshot."""

    expected_binding: tuple[tuple[str, object], ...]
    reference_contract_status: str
    reference_contract_body_digest: str
    target_plan: dict[str, Any]
    target_plan_sha256: str
    verifier_report_digest: str


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message)


def _diagnostic_document(diagnostic: Diagnostic) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "path": diagnostic.path,
        "message": diagnostic.message,
        "details": diagnostic.details,
    }


def kit_verifier_report_digest(inspection: BuildKitInspection) -> str:
    from ..canonical import canonical_json_bytes

    return sha256_bytes(
        canonical_json_bytes(
            {
                "ok": inspection.report.ok and not inspection.report.diagnostics,
                "diagnostics": [
                    _diagnostic_document(item)
                    for item in sorted(inspection.report.diagnostics)
                ],
            }
        )
    )


def load_kit_evidence_binding(
    inspection: BuildKitInspection,
) -> tuple[KitEvidenceBinding | None, tuple[Diagnostic, ...]]:
    """Parse evidence contracts only from the authenticated captured Kit bytes."""
    if not inspection.report.ok or inspection.report.diagnostics:
        return None, (
            _diagnostic(
                "TARGET_EVIDENCE_KIT_INVALID",
                "kit",
                "Kit inspection is not authenticated",
            ),
        )

    files = dict(inspection.files)
    parsed: dict[str, dict[str, Any]] = {}
    required = (
        "catalog.json",
        "kit-manifest.json",
        "references/core.json",
        "target-test-plan/target-test-plan.json",
    )
    diagnostics: list[Diagnostic] = []
    for path in required:
        try:
            value = parse_canonical_json_bytes(files[path])
        except (KeyError, CanonicalJsonError):
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_KIT_DOCUMENT_INVALID",
                    path,
                    "authenticated Kit evidence document is unavailable or invalid",
                )
            )
            continue
        if type(value) is not dict:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_KIT_DOCUMENT_INVALID",
                    path,
                    "authenticated Kit evidence document must be an object",
                )
            )
            continue
        parsed[path] = value

    if diagnostics:
        return None, tuple(sorted(diagnostics))

    companion = parsed["references/core.json"]
    contract = companion.get("reference_contract")
    contract_digest = companion.get("contract_body_digest")
    status = contract.get("status") if type(contract) is dict else None
    plan = parsed["target-test-plan/target-test-plan.json"]
    cases = plan.get("cases")
    if (
        companion.get("package_id") != "core"
        or type(contract) is not dict
        or status not in {"discovery-required", "approved"}
        or type(contract_digest) is not str
        or type(cases) is not list
        or len(cases) != 30
    ):
        return None, (
            _diagnostic(
                "TARGET_EVIDENCE_KIT_CONTRACT_INVALID",
                "kit",
                "authenticated Kit has no valid Core evidence contract",
            ),
        )

    expected_values = {
        "schema_version": 1,
        "package_id": "core",
        "kit_id": inspection.kit_id,
        "catalog_sha256": inspection.catalog_sha256,
        "manifest_sha256": inspection.manifest_sha256,
        "manifest_digest": inspection.manifest_digest,
        "work_commit": inspection.work_commit,
        "work_tree": inspection.work_tree,
        "target": "CATIA R2018/VBA7 64",
    }
    if any(value is None for value in expected_values.values()):
        return None, (
            _diagnostic(
                "TARGET_EVIDENCE_KIT_IDENTITY_INVALID",
                "kit",
                "authenticated Kit identity is incomplete",
            ),
        )

    return (
        KitEvidenceBinding(
            expected_binding=tuple(sorted(expected_values.items())),
            reference_contract_status=status,
            reference_contract_body_digest=contract_digest,
            target_plan=plan,
            target_plan_sha256=sha256_bytes(
                files["target-test-plan/target-test-plan.json"]
            ),
            verifier_report_digest=kit_verifier_report_digest(inspection),
        ),
        (),
    )
