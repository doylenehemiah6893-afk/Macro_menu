"""Shared strict semantics for raw Discovery capture members.

The target finalizer and trusted A-environment ingestion call this same
standard-library-only validator so the raw boundary cannot drift.
"""

from __future__ import annotations

from collections.abc import Mapping

from .canonical import CollectorError, parse_canonical_json_bytes
from .records import (
    POINT_ORDER,
    validate_entitlements_document,
    validate_environment_document,
    validate_operator_index_files,
    validate_references_document,
)
from .workspace import SESSION_FIELDS


REQUIRED_DOCUMENTS = frozenset({
    "session.json", "environment.json", "entitlements.json", "references.json",
    "compile-result.json", "test-results.json", "artifact-manifest.json",
    "operator-records/index.json",
})
CONTROL_MEMBERS = frozenset({"raw-capture-manifest.json", "SHA256SUMS"})
COMPILE_POINTS = ("blank-project", "post-import", "post-save", "post-restart")
TARGET_CASE_IDS = (
    *(f"context.{tool}.{document}" for tool in ("core.healthcheck", "core.document-summary")
      for document in ("none", "CATPart", "CATProduct", "CATDrawing")),
    *(f"profile.{profile}.{tool}" for profile in ("P-AB3", "P-HD2", "P-MD2")
      for tool in ("core.healthcheck", "core.document-summary")),
    *(f"lifecycle.{scenario}.{tool}" for scenario in ("restart", "repeat", "cross-document", "state-diff")
      for tool in ("core.healthcheck", "core.document-summary")),
    *(f"isolation.{package}.{failure}" for package in ("fleet-spa", "fleet-fta")
      for failure in ("missing", "broken", "reference-failed", "checkout-failed")),
)
ENVELOPE = {
    "schema_version": 1,
    "trust_level": "raw-untrusted",
    "mode": "discovery",
    "compile_status": "not-run",
    "target_case_status": "not-run",
    "artifact_status": "not-produced",
    "release_eligible": False,
}
DISCOVERY_SKELETON_MEMBERS = frozenset({
    "compile-result.json", "test-results.json", "artifact-manifest.json",
})


def _document(files: Mapping[str, bytes], path: str) -> dict[str, object]:
    data = files.get(path)
    if type(data) is not bytes:
        raise CollectorError("COLLECTOR_CAPTURE_INCOMPLETE", path)
    try:
        value = parse_canonical_json_bytes(data)
    except CollectorError as error:
        raise CollectorError("COLLECTOR_CAPTURE_INVALID", path) from error
    if type(value) is not dict:
        raise CollectorError("COLLECTOR_CAPTURE_INVALID", path)
    return value


def _exact(document: Mapping[str, object], extras: frozenset[str], path: str) -> None:
    if frozenset(document) != frozenset(ENVELOPE) | extras:
        raise CollectorError("COLLECTOR_CAPTURE_INVALID", path)
    for key, expected in ENVELOPE.items():
        if document.get(key) != expected:
            code = {
                "compile_status": "DISCOVERY_COMPILE_FORBIDDEN",
                "release_eligible": "DISCOVERY_RELEASE_FORBIDDEN",
                "artifact_status": "DISCOVERY_ARTIFACT_FORBIDDEN",
                "target_case_status": "DISCOVERY_TEST_FORBIDDEN",
            }.get(key, "COLLECTOR_CAPTURE_INVALID")
            raise CollectorError(code, path)


def _session(document: Mapping[str, object]) -> None:
    if frozenset(document) != SESSION_FIELDS:
        raise CollectorError("COLLECTOR_SESSION_INVALID", "session.json")
    fixed = {**ENVELOPE, "package_id": "core", "profile_id": "DISCOVERY", "capture_status": "in-progress"}
    for key, expected in fixed.items():
        if document.get(key) != expected:
            code = "DISCOVERY_COMPILE_FORBIDDEN" if key == "compile_status" else "COLLECTOR_SESSION_INVALID"
            raise CollectorError(code, "session.json")


def _environment(document: Mapping[str, object]) -> None:
    validate_environment_document(document)


def _entitlements(document: Mapping[str, object]) -> None:
    validate_entitlements_document(document)


def _references(document: Mapping[str, object]) -> None:
    try:
        validated = validate_references_document(document)
    except CollectorError as error:
        raise CollectorError("COLLECTOR_REFERENCES_INVALID", "references.json") from error
    observations = validated.get("observations")
    if type(observations) is not list or len(observations) != len(POINT_ORDER):
        raise CollectorError("COLLECTOR_CAPTURE_INCOMPLETE", "references.json")


def _compile(document: Mapping[str, object]) -> None:
    _exact(document, frozenset({"records"}), "compile-result.json")
    expected = [{
        "record_id": f"record-compile-{point}", "point": point, "status": "not-run",
        "started_at": None, "ended_at": None, "catia_operator_record_id": None,
        "vbe_operator_record_id": None, "error_stage": None, "error_module": None,
        "redacted_error_summary": None,
    } for point in COMPILE_POINTS]
    if document.get("records") != expected:
        raise CollectorError("DISCOVERY_COMPILE_FORBIDDEN", "compile-result.json")


def _tests(document: Mapping[str, object]) -> None:
    _exact(document, frozenset({"records"}), "test-results.json")
    records = document.get("records")
    keys = frozenset({
        "case_id", "status", "execution_point", "observations", "started_at", "ended_at",
        "operator_record_id",
    })
    if (
        type(records) is not list or len(records) != 30
        or any(
            type(record) is not dict or frozenset(record) != keys
            or type(record.get("case_id")) is not str or not record["case_id"]
            or record.get("status") != "not-run" or record.get("execution_point") != "not-run"
            or record.get("observations") != [] or record.get("started_at") is not None
            or record.get("ended_at") is not None or record.get("operator_record_id") is not None
            for record in records
        )
        or tuple(record["case_id"] for record in records) != TARGET_CASE_IDS
    ):
        raise CollectorError("DISCOVERY_TEST_FORBIDDEN", "test-results.json")


def _artifact(document: Mapping[str, object]) -> None:
    _exact(document, frozenset({"artifact", "files"}), "artifact-manifest.json")
    if document.get("artifact") is not None or document.get("files") != []:
        raise CollectorError("DISCOVERY_ARTIFACT_FORBIDDEN", "artifact-manifest.json")


def _operator_members(files: Mapping[str, bytes]) -> None:
    try:
        validate_operator_index_files(files)
    except (CollectorError, OSError) as error:
        raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID", "operator-records/index.json") from error


def validate_raw_capture_files(files: Mapping[str, bytes], *, controls: bool) -> dict[str, object]:
    """Return parsed identity documents or raise one stable fail-closed code."""

    expected_controls = CONTROL_MEMBERS if controls else frozenset()
    missing = REQUIRED_DOCUMENTS - files.keys()
    if missing:
        raise CollectorError("COLLECTOR_CAPTURE_INCOMPLETE", sorted(missing)[0])
    allowed = REQUIRED_DOCUMENTS | expected_controls
    for path in files:
        if path in allowed or path.startswith("operator-records/"):
            continue
        raise CollectorError("COLLECTOR_RAW_MEMBER_FORBIDDEN", path)
    documents = {path: _document(files, path) for path in REQUIRED_DOCUMENTS}
    _session(documents["session.json"])
    _environment(documents["environment.json"])
    _entitlements(documents["entitlements.json"])
    _references(documents["references.json"])
    _compile(documents["compile-result.json"])
    _tests(documents["test-results.json"])
    _artifact(documents["artifact-manifest.json"])
    _operator_members(files)
    return documents


def validate_discovery_skeleton_files(files: Mapping[str, bytes]) -> None:
    """Validate the exact bundle-independent documents copied by init-capture."""

    if frozenset(files) != DISCOVERY_SKELETON_MEMBERS:
        raise CollectorError("COLLECTOR_SKELETON_MEMBER_SET_INVALID")
    documents = {path: _document(files, path) for path in DISCOVERY_SKELETON_MEMBERS}
    _compile(documents["compile-result.json"])
    _tests(documents["test-results.json"])
    _artifact(documents["artifact-manifest.json"])
