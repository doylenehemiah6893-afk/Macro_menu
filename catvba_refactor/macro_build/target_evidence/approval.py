from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from ..canonical import (
    CanonicalJsonError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    sha256_bytes,
)
from ..errors import BuildKitError, EvidenceError, InfrastructureError
from ..handoff import _publish
from ..model import BuildKitInspection
from . import container as _container
from .container import EvidenceContainerSnapshot, read_evidence_container
from .gate import recompute_gate_receipt
from .model import EvidencePhase
from .schemas import (
    load_target_evidence_schemas,
    validate_target_document,
)
from .session import _reject_prerequisite_output_overlap
from .validator import _capture_record_ids, _inspect_snapshot


_MAX_GATE_RECEIPT_BYTES = 4 * 1024 * 1024
_APPROVAL_STATUSES = frozenset({"approved", "rejected"})
_MODE_SCOPE = {
    "discovery": "observation",
    "g2": "gate",
    "g3-c": "gate",
}


def _error(code: str, *details: object) -> EvidenceError:
    suffix = ":" + ":".join(str(item) for item in details) if details else ""
    return EvidenceError(code + suffix)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _utc(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _read_gate_receipt(path: os.PathLike[str] | str) -> bytes:
    try:
        data, _absolute_path = _container._read_regular_path(
            path, max_bytes=_MAX_GATE_RECEIPT_BYTES
        )
    except (
        _container._ContainerFault,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_INVALID") from error
    return data


def _reject_capture_output_overlap(
    capture: EvidenceContainerSnapshot | os.PathLike[str] | str,
    snapshot: EvidenceContainerSnapshot,
    output_root: os.PathLike[str] | str,
) -> None:
    if isinstance(capture, EvidenceContainerSnapshot):
        return
    if snapshot.container_sha256 is not None:
        return
    _reject_prerequisite_output_overlap(
        capture,
        snapshot.directories,
        output_root,
        "approval.json",
        prerequisite_identities=snapshot.directory_identities,
        invalid_code="TARGET_APPROVAL_OUTPUT_INVALID",
        overlap_code="TARGET_APPROVAL_CAPTURE_OUTPUT_OVERLAP",
    )


def _validated_capture(
    capture: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    *,
    schema_dir: os.PathLike[str] | str,
) -> tuple[EvidenceContainerSnapshot, Any]:
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
        raise _error("TARGET_APPROVAL_CAPTURE_INVALID", codes)
    return snapshot, inspection


def _validate_receipt_schema(
    data: bytes,
    *,
    schema_dir: os.PathLike[str] | str,
) -> Mapping[str, Any]:
    try:
        value = parse_canonical_json_bytes(data)
    except CanonicalJsonError as error:
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_INVALID") from error
    schemas = load_target_evidence_schemas(schema_dir)
    report = validate_target_document("gate-receipt.json", value, schemas)
    if not report.ok:
        codes = ",".join(item.code for item in report.diagnostics)
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_INVALID", codes)
    document = _mapping(value)
    if document is None:
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_INVALID")
    return document


def _validate_approval_schema(
    document: Mapping[str, Any],
    *,
    schema_dir: os.PathLike[str] | str,
) -> None:
    schemas = load_target_evidence_schemas(schema_dir)
    report = validate_target_document("approval.json", document, schemas)
    if not report.ok:
        codes = ",".join(item.code for item in report.diagnostics)
        raise _error("TARGET_APPROVAL_DOCUMENT_INVALID", codes)


def record_target_approval(
    capture: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    gate_receipt: os.PathLike[str] | str,
    output_root: os.PathLike[str] | str,
    *,
    scope: str,
    status: str,
    reviewer_role: str,
    review_record_id: str,
    approved_at: str,
    schema_dir: os.PathLike[str] | str,
) -> Path:
    """Normalize one explicit independent review into a detached approval."""
    snapshot, inspection = _validated_capture(
        capture, kit, schema_dir=schema_dir
    )
    _reject_capture_output_overlap(capture, snapshot, output_root)

    receipt_bytes = _read_gate_receipt(gate_receipt)
    _validate_receipt_schema(receipt_bytes, schema_dir=schema_dir)
    try:
        expected_receipt, _audit_report = recompute_gate_receipt(inspection)
        expected_receipt_bytes = canonical_json_bytes(expected_receipt)
    except BuildKitError:
        raise
    except OSError as error:
        raise InfrastructureError("TARGET_APPROVAL_RECOMPUTE_IO") from error
    except (TypeError, ValueError) as error:
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_INVALID") from error
    if receipt_bytes != expected_receipt_bytes:
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_MISMATCH")

    documents = dict(inspection.documents)
    session = _mapping(documents.get("session.json"))
    binding = _mapping(session.get("binding")) if session is not None else None
    if session is None or binding is None:
        raise _error("TARGET_APPROVAL_CAPTURE_INVALID")
    mode = binding.get("session_mode")
    expected_scope = _MODE_SCOPE.get(mode) if type(mode) is str else None
    if type(scope) is not str or scope != expected_scope:
        raise _error("TARGET_APPROVAL_SCOPE_INVALID")
    if type(status) is not str or status not in _APPROVAL_STATUSES:
        raise _error("TARGET_APPROVAL_STATUS_INVALID")
    if type(reviewer_role) is not str:
        raise _error("TARGET_APPROVAL_REVIEWER_INVALID")
    if type(review_record_id) is not str:
        raise _error("TARGET_APPROVAL_REVIEW_RECORD_INVALID")
    if reviewer_role in {
        session.get("builder_role"),
        session.get("standard_user_role"),
    }:
        raise _error("TARGET_APPROVAL_SELF_REVIEW")
    if review_record_id in _capture_record_ids(
        documents, dict(inspection.files)
    ):
        raise _error("TARGET_APPROVAL_REVIEW_RECORD_REUSED")

    decision_time = _utc(approved_at)
    capture_ended = _utc(session.get("ended_at"))
    if (
        decision_time is None
        or capture_ended is None
        or decision_time < capture_ended
    ):
        raise _error("TARGET_APPROVAL_TIME_INVALID")

    receipt = _mapping(expected_receipt)
    if receipt is None:
        raise _error("TARGET_APPROVAL_GATE_RECEIPT_INVALID")
    body = {
        "schema_version": 1,
        "session_id": binding.get("session_id"),
        "session_mode": mode,
        "gate_id": receipt.get("gate_id"),
        "evidence_payload_digest": inspection.report.evidence_payload_digest,
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_scope": scope,
        "approval_status": status,
        "reviewer_role": reviewer_role,
        "review_record_id": review_record_id,
        "approved_at": approved_at,
    }
    approval_id = "approval-" + sha256_bytes(canonical_json_bytes(body))[:20]
    document = {"approval_id": approval_id, **body}
    _validate_approval_schema(document, schema_dir=schema_dir)
    data = canonical_json_bytes(document)
    return _publish(output_root, approval_id, data)
