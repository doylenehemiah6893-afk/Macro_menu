from __future__ import annotations

import datetime as _datetime
import os
from pathlib import Path
from typing import Any, Mapping

from ..canonical import (
    CanonicalJsonError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    sha256_bytes,
)
from ..errors import BuildKitError, EvidenceError, InfrastructureError
from ..model import BuildKitInspection
from . import container as _container
from .container import (
    EvidenceContainerSnapshot,
    canonical_evidence_zip_bytes,
    canonical_payload_manifest,
    publish_evidence_artifacts,
    read_evidence_container,
)
from .gate import recompute_gate_receipt
from .model import EvidencePhase, TargetEvidenceBundleReceipt
from .schemas import load_target_evidence_schemas, validate_target_document
from .session import _reject_prerequisite_output_overlap
from .validator import (
    _capture_record_ids,
    _inspect_snapshot,
    validate_target_evidence,
)


_MAX_DECISION_BYTES = 4 * 1024 * 1024
_MODE_GATE = {"discovery": "DISCOVERY", "g2": "G2", "g3-c": "G3-C"}


def _error(code: str, *details: object) -> EvidenceError:
    suffix = ":" + ":".join(str(item) for item in details) if details else ""
    return EvidenceError(code + suffix)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _utc(value: object) -> _datetime.datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = _datetime.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(_datetime.UTC)


def _read_decision_document(
    path: os.PathLike[str] | str,
    *,
    document_name: str,
    schema_dir: os.PathLike[str] | str,
) -> tuple[bytes, dict[str, Any]]:
    try:
        data, _absolute = _container._read_regular_path(
            path, max_bytes=_MAX_DECISION_BYTES
        )
    except (_container._ContainerFault, OSError, TypeError, ValueError) as error:
        raise _error("TARGET_EVIDENCE_DECISION_INVALID", document_name) from error
    try:
        document = parse_canonical_json_bytes(data)
    except CanonicalJsonError as error:
        raise _error("TARGET_EVIDENCE_DECISION_INVALID", document_name) from error
    if type(document) is not dict:
        raise _error("TARGET_EVIDENCE_DECISION_INVALID", document_name)
    schemas = load_target_evidence_schemas(schema_dir)
    report = validate_target_document(document_name, document, schemas)
    if not report.ok:
        codes = ",".join(item.code for item in report.diagnostics)
        raise _error("TARGET_EVIDENCE_DECISION_INVALID", document_name, codes)
    return data, document


def _capture_inspection(
    capture: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    *,
    schema_dir: os.PathLike[str] | str,
):
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
    if not inspection.report.ok or inspection.report.evidence_payload_digest is None:
        codes = ",".join(item.code for item in inspection.report.diagnostics)
        raise _error("TARGET_EVIDENCE_INVALID", codes)
    documents = dict(inspection.documents)
    session = _mapping(documents.get("session.json")) or {}
    if session.get("capture_status") != "complete":
        raise _error("TARGET_EVIDENCE_CAPTURE_INCOMPLETE")
    return snapshot, inspection, documents


def _validate_decisions(
    inspection: Any,
    documents: Mapping[str, Any],
    receipt_bytes: bytes,
    receipt: Mapping[str, Any],
    approval_bytes: bytes,
    approval: Mapping[str, Any],
) -> None:
    try:
        expected_receipt, _audit = recompute_gate_receipt(inspection)
        expected_receipt_bytes = canonical_json_bytes(expected_receipt)
    except BuildKitError:
        raise
    except OSError as error:
        raise InfrastructureError("TARGET_EVIDENCE_RECOMPUTE_IO") from error
    except (TypeError, ValueError) as error:
        raise _error("TARGET_GATE_RECEIPT_INVALID") from error
    if receipt_bytes != expected_receipt_bytes:
        raise _error("TARGET_GATE_RECEIPT_MISMATCH")

    session = _mapping(documents.get("session.json")) or {}
    binding = _mapping(session.get("binding")) or {}
    mode = binding.get("session_mode")
    expected_scope = "observation" if mode == "discovery" else "gate"
    expected = {
        "session_id": binding.get("session_id"),
        "session_mode": mode,
        "gate_id": _MODE_GATE.get(mode),
        "evidence_payload_digest": inspection.report.evidence_payload_digest,
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_scope": expected_scope,
    }
    body = dict(approval)
    body.pop("approval_id", None)
    expected_id = "approval-" + sha256_bytes(canonical_json_bytes(body))[:20]
    ended_at = _utc(session.get("ended_at"))
    approved_at = _utc(approval.get("approved_at"))
    invalid = (
        any(approval.get(field) != value for field, value in expected.items())
        or approval.get("approval_id") != expected_id
        or approval.get("approval_status") not in {"approved", "rejected"}
        or approval.get("review_record_id")
        in _capture_record_ids(documents, dict(inspection.files))
        or approval.get("reviewer_role")
        in {session.get("builder_role"), session.get("standard_user_role")}
        or ended_at is None
        or approved_at is None
        or approved_at < ended_at
    )
    if invalid:
        raise _error("TARGET_APPROVAL_INVALID")
    if approval.get("gate_receipt_sha256") != sha256_bytes(receipt_bytes):
        raise _error("TARGET_APPROVAL_INVALID")
    if canonical_json_bytes(dict(approval)) != approval_bytes:
        raise _error("TARGET_APPROVAL_INVALID")


def _snapshot(files: Mapping[str, bytes]) -> EvidenceContainerSnapshot:
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


def _assert_sealed_valid(
    evidence: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    *,
    schema_dir: os.PathLike[str] | str,
) -> None:
    report = validate_target_evidence(
        evidence,
        kit,
        phase=EvidencePhase.SEALED,
        schema_dir=schema_dir,
    )
    if not report.ok:
        codes = ",".join(item.code for item in report.diagnostics)
        raise _error("TARGET_EVIDENCE_SEALED_INVALID", codes)


def pack_target_evidence(
    capture: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    gate_receipt: os.PathLike[str] | str,
    approval: os.PathLike[str] | str,
    output_root: os.PathLike[str] | str,
    *,
    schema_dir: os.PathLike[str] | str,
) -> TargetEvidenceBundleReceipt:
    """Seal one authenticated capture into deterministic directory/ZIP siblings."""
    snapshot, inspection, documents = _capture_inspection(
        capture, kit, schema_dir=schema_dir
    )
    receipt_bytes, receipt_document = _read_decision_document(
        gate_receipt,
        document_name="gate-receipt.json",
        schema_dir=schema_dir,
    )
    approval_bytes, approval_document = _read_decision_document(
        approval,
        document_name="approval.json",
        schema_dir=schema_dir,
    )
    _validate_decisions(
        inspection,
        documents,
        receipt_bytes,
        receipt_document,
        approval_bytes,
        approval_document,
    )

    capture_files = dict(snapshot.files)
    payload_digest = inspection.report.evidence_payload_digest
    bundle_files = {
        **capture_files,
        "gate-receipt.json": receipt_bytes,
        "approval.json": approval_bytes,
    }
    _manifest, bundle_digest, _members = canonical_payload_manifest(bundle_files)
    sums = "".join(
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(
            bundle_files.items(), key=lambda item: item[0].encode("ascii")
        )
    ).encode("ascii")
    session = _mapping(documents.get("session.json")) or {}
    binding = _mapping(session.get("binding")) or {}
    completion = {
        "schema_version": 1,
        "session_id": binding.get("session_id"),
        "sealed_at": approval_document.get("approved_at"),
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": payload_digest,
        "sha256sums_sha256": sha256_bytes(sums),
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_sha256": sha256_bytes(approval_bytes),
    }
    sealed_files = dict(
        sorted(
            {
                **bundle_files,
                "SHA256SUMS": sums,
                "SESSION_COMPLETE": canonical_json_bytes(completion),
            }.items()
        )
    )

    _assert_sealed_valid(_snapshot(sealed_files), kit, schema_dir=schema_dir)
    zip_bytes = canonical_evidence_zip_bytes(sealed_files)
    zip_snapshot = _container._read_zip_bytes(
        zip_bytes,
        phase=EvidencePhase.SEALED,
        nesting_depth=0,
        container_sha256=sha256_bytes(zip_bytes),
    )
    _assert_sealed_valid(zip_snapshot, kit, schema_dir=schema_dir)

    bundle_name = f"target-session-{binding.get('session_id')}"
    if (
        not isinstance(capture, EvidenceContainerSnapshot)
        and snapshot.container_sha256 is None
    ):
        _reject_prerequisite_output_overlap(
            capture,
            snapshot.directories,
            output_root,
            bundle_name,
            prerequisite_identities=snapshot.directory_identities,
            invalid_code="TARGET_EVIDENCE_CAPTURE_INVALID",
            overlap_code="TARGET_EVIDENCE_CAPTURE_OUTPUT_OVERLAP",
        )

    def validate_published(directory: Path, archive: Path) -> None:
        _assert_sealed_valid(directory, kit, schema_dir=schema_dir)
        _assert_sealed_valid(archive, kit, schema_dir=schema_dir)

    bundle_dir, zip_path, zip_digest = publish_evidence_artifacts(
        sealed_files,
        bundle_name=bundle_name,
        output_root=output_root,
        _post_publish=validate_published,
    )
    return TargetEvidenceBundleReceipt(
        session_id=str(binding.get("session_id")),
        bundle_dir=os.fspath(bundle_dir),
        zip_path=os.fspath(zip_path),
        zip_sha256=zip_digest,
        evidence_payload_digest=payload_digest,
        bundle_content_digest=bundle_digest,
    )


__all__ = ["pack_target_evidence"]
