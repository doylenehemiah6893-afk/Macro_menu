from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from ...target_collector.canonical import CollectorError
from ...target_collector.raw_validation import (
    REQUIRED_DOCUMENTS as RAW_REQUIRED_DOCUMENTS,
    validate_raw_capture_files,
)

from ..canonical import (
    CanonicalJsonError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    sha256_bytes,
)
from ..handoff import validate_handoff
from ..errors import BuildKitError, EvidenceError
from ..model import BuildKitInspection, Diagnostic
from ..portable_paths import validate_portable_ascii_paths
from ..reference_contract import resolved_reference_id
from .container import (
    EvidenceContainerSnapshot,
    MAX_EVIDENCE_DIRECTORIES,
    MAX_EVIDENCE_ENTRIES,
    MAX_EVIDENCE_FILE_BYTES,
    MAX_EVIDENCE_TOTAL_BYTES,
    NESTED_G2_PATH,
    _read_zip_bytes,
    canonical_payload_manifest,
    read_evidence_container,
    read_raw_evidence_container,
)
from .kit_binding import KitEvidenceBinding, load_kit_evidence_binding
from .model import EvidencePhase, TargetEvidenceReport
from .schemas import load_target_evidence_schemas, validate_target_document


_ROOT_DOCUMENTS = (
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
_JSON_DOCUMENTS = frozenset((*_ROOT_DOCUMENTS, "handoff.json"))
_SEAL_DOCUMENTS = (
    "gate-receipt.json",
    "approval.json",
    "SHA256SUMS",
    "SESSION_COMPLETE",
)
_REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
_COMPILE_POINTS = (
    "blank-project",
    "post-import",
    "post-save",
    "post-restart",
)
_MODE_GATE = {"discovery": "DISCOVERY", "g2": "G2", "g3-c": "G3-C"}
_FORMAL_PROFILES = frozenset({"P-AB3", "P-HD2", "P-MD2"})
_UNRESOLVED_ID = re.compile(r"^unresolved\.([0-9a-f]{16,64})$")


@dataclass(frozen=True)
class TargetEvidenceInspection:
    report: TargetEvidenceReport
    files: tuple[tuple[str, bytes], ...]
    documents: tuple[tuple[str, Any], ...]
    kit: BuildKitInspection


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message)


def _utc(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _capture_record_ids(
    documents: Mapping[str, Any],
    files: Mapping[str, bytes] | None = None,
) -> frozenset[str]:
    """Collect record provenance from immutable capture documents only."""
    record_ids: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if (
                    type(key) is str
                    and (key == "record_id" or key.endswith("_record_id"))
                    and type(child) is str
                ):
                    record_ids.add(child)
                visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)

    for path in _JSON_DOCUMENTS:
        if path in documents:
            visit(documents[path])
    nested_data = files.get(NESTED_G2_PATH) if files is not None else None
    if type(nested_data) is bytes:
        nested = _read_zip_bytes(
            nested_data,
            phase=EvidencePhase.SEALED,
            nesting_depth=1,
            container_sha256=sha256_bytes(nested_data),
        )
        if not nested.diagnostics:
            for path, data in nested.files:
                if path not in {*_JSON_DOCUMENTS, "approval.json"}:
                    continue
                try:
                    visit(parse_canonical_json_bytes(data))
                except CanonicalJsonError:
                    continue
    return frozenset(record_ids)


def _sort_text(value: object) -> str:
    return value if type(value) is str else ""


def environment_fingerprint(document: Mapping[str, Any], contract_body_digest: str) -> str:
    """Hash the stable, anonymous CATIA target environment projection.

    ``document`` is the validator's composite ``{"session": ..., "environment": ...}``.
    Keeping the projection here prevents timestamps, operators, notes and checkout
    state from accidentally entering the G2/G3-C environment identity.
    """
    session = _mapping(document.get("session"))
    environment = _mapping(document.get("environment"))
    if session is None or environment is None:
        raise ValueError("environment fingerprint requires session and environment")
    binding = _mapping(environment.get("binding"))
    install = _mapping(_mapping(environment.get("catia_environment")) or {})
    install_root = _mapping(install.get("install_root")) if install is not None else None
    dsls = _mapping(environment.get("dsls"))
    if binding is None or install_root is None or dsls is None:
        raise ValueError("environment fingerprint projection is incomplete")
    projection = {
        "anonymous_host_id": session.get("anonymous_host_id"),
        "vm_lineage_id": session.get("vm_lineage_id"),
        "snapshot_id": session.get("snapshot_id"),
        "windows": environment.get("windows"),
        "catia": environment.get("catia"),
        "vba": environment.get("vba"),
        "install_root": {
            "root_kind": install_root.get("root_kind"),
            "normalized_path_sha256": install_root.get("normalized_path_sha256"),
        },
        "dsls_connection_mode": dsls.get("connection_mode"),
        "profile_id": binding.get("profile_id"),
        "reference_contract_body_digest": contract_body_digest,
    }
    return sha256_bytes(canonical_json_bytes(projection))


def _empty_inspection(
    phase: EvidencePhase,
    kit: BuildKitInspection,
    diagnostics: list[Diagnostic] | tuple[Diagnostic, ...],
    *,
    files: tuple[tuple[str, bytes], ...] = (),
    documents: tuple[tuple[str, Any], ...] = (),
) -> TargetEvidenceInspection:
    report = TargetEvidenceReport(
        phase=phase,
        session_id=None,
        evidence_payload_digest=None,
        payload_members=(),
        diagnostics=tuple(sorted(set(diagnostics))),
    )
    return TargetEvidenceInspection(report, files, documents, kit)


def _snapshot_boundary_diagnostics(
    snapshot: EvidenceContainerSnapshot,
) -> tuple[Diagnostic, ...]:
    invalid = type(snapshot.files) is not tuple or type(snapshot.directories) is not tuple
    paths: list[str] = []
    total = 0
    if not invalid:
        for item in snapshot.files:
            if (
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not bytes
            ):
                invalid = True
                continue
            path, data = item
            paths.append(path)
            total += len(data)
            if len(data) > MAX_EVIDENCE_FILE_BYTES:
                invalid = True
            if path.lower().endswith(".zip") and path != NESTED_G2_PATH:
                invalid = True
    directories = list(snapshot.directories) if type(snapshot.directories) is tuple else []
    directory_paths = [path for path in directories if type(path) is str]
    if len(directory_paths) != len(directories):
        invalid = True
    if (
        len(paths) > MAX_EVIDENCE_ENTRIES
        or len(directories) > MAX_EVIDENCE_DIRECTORIES
        or total > MAX_EVIDENCE_TOTAL_BYTES
        or len(paths) != len(set(paths))
        or len(directory_paths) != len(set(directory_paths))
        or paths
        != sorted(paths, key=lambda value: value.encode("utf-8", errors="surrogatepass"))
        or directory_paths
        != sorted(
            directory_paths,
            key=lambda value: value.encode("utf-8", errors="surrogatepass"),
        )
    ):
        invalid = True
    if not invalid:
        return ()
    return (
        _diagnostic(
            "TARGET_EVIDENCE_FILE_POLICY",
            "snapshot",
            "direct evidence snapshot violates secure container invariants",
        ),
    )


def _parse_documents(
    files: Mapping[str, bytes],
    phase: EvidencePhase,
    schema_dir: os.PathLike[str] | str,
    diagnostics: list[Diagnostic],
) -> dict[str, Any]:
    schemas = load_target_evidence_schemas(schema_dir)
    expected = set(_JSON_DOCUMENTS)
    if phase is EvidencePhase.SEALED:
        expected.update({"gate-receipt.json", "approval.json", "SESSION_COMPLETE"})
    documents: dict[str, Any] = {}
    for path in sorted(expected):
        data = files.get(path)
        if data is None:
            continue
        try:
            value = parse_canonical_json_bytes(data)
        except CanonicalJsonError:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_JSON_INVALID",
                    path,
                    "evidence JSON is not strict canonical JSON",
                )
            )
            continue
        documents[path] = value
        diagnostics.extend(validate_target_document(path, value, schemas).diagnostics)
    return documents


def _required_and_seal_policy(
    files: Mapping[str, bytes], phase: EvidencePhase, diagnostics: list[Diagnostic]
) -> None:
    for path in (*_ROOT_DOCUMENTS, "handoff.json"):
        if path not in files:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_REQUIRED_FILE",
                    path,
                    "required target evidence document is missing",
                )
            )
    if phase is EvidencePhase.CAPTURE:
        for path in _SEAL_DOCUMENTS:
            if path in files:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_EVIDENCE_SEAL_FORBIDDEN",
                        path,
                        "capture evidence cannot contain decision or seal members",
                    )
                )
    else:
        for path in _SEAL_DOCUMENTS:
            if path not in files:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_EVIDENCE_SEAL_REQUIRED",
                        path,
                        "sealed evidence requires the complete decision envelope",
                    )
                )


def _file_policy(
    snapshot: EvidenceContainerSnapshot,
    files: Mapping[str, bytes],
    documents: Mapping[str, Any],
    phase: EvidencePhase,
    diagnostics: list[Diagnostic],
) -> None:
    paths = tuple(files)
    if validate_portable_ascii_paths(paths).diagnostics:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY",
                "files",
                "evidence contains a non-portable member path",
            )
        )

    derived_directories = {
        "/".join(path.split("/")[:index])
        for path in paths
        for index in range(1, len(path.split("/")))
    }
    if set(snapshot.directories) != derived_directories:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY",
                "directories",
                "evidence has an undeclared or missing directory",
            )
        )

    session = _mapping(documents.get("session.json"))
    binding = _mapping(session.get("binding")) if session is not None else None
    mode = binding.get("session_mode") if binding is not None else None
    artifact_document = _mapping(documents.get("artifact-manifest.json"))
    artifact_status = (
        artifact_document.get("artifact_status") if artifact_document is not None else None
    )
    returned_members = tuple(
        path for path in files if path.startswith("returned-catvba/")
    )
    returned = "returned-catvba/core.catvba" in files
    prerequisite = NESTED_G2_PATH in files

    if mode == "discovery" and (
        returned_members
        or artifact_status != "not-produced"
        or (
            artifact_document is not None
            and artifact_document.get("artifact") is not None
        )
    ):
        diagnostics.append(
            _diagnostic(
                "DISCOVERY_ARTIFACT_FORBIDDEN",
                "artifact-manifest.json",
                "Discovery forbids returned CATVBA artifacts and members",
            )
        )
    if mode == "g2" and returned_members:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY",
                "returned-catvba/core.catvba",
                "G2 evidence forbids a returned CATVBA artifact",
            )
        )
    if mode in ("discovery", "g2") and prerequisite:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY",
                NESTED_G2_PATH,
                "this mode forbids a G2 prerequisite archive",
            )
        )
    if mode == "g3-c" and not prerequisite:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY",
                NESTED_G2_PATH,
                "G3-C evidence requires exactly one G2 prerequisite archive",
            )
        )
    if artifact_status == "returned" and not returned:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_ARTIFACT_MISMATCH",
                "artifact-manifest.json",
                "returned artifact manifest has no artifact member",
            )
        )
    if artifact_status != "returned" and returned:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_ARTIFACT_MISMATCH",
                "returned-catvba/core.catvba",
                "artifact member is not declared returned",
            )
        )

    fixed = set(_ROOT_DOCUMENTS) | {"handoff.json"}
    if phase is EvidencePhase.SEALED:
        fixed.update(_SEAL_DOCUMENTS)
    allowed = set(fixed)
    allowed.update(path for path in files if path.startswith("operator-records/"))
    if returned:
        allowed.add("returned-catvba/core.catvba")
    if prerequisite:
        allowed.add(NESTED_G2_PATH)
    for path in sorted(set(files) - allowed):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY",
                path,
                "evidence contains an undeclared member",
            )
        )


def _binding_diagnostics(
    documents: Mapping[str, Any],
    kit_binding: KitEvidenceBinding,
    diagnostics: list[Diagnostic],
) -> tuple[Mapping[str, Any] | None, str | None]:
    session = _mapping(documents.get("session.json"))
    session_binding = _mapping(session.get("binding")) if session is not None else None
    if session_binding is None:
        return None, None
    mode = session_binding.get("session_mode")
    for path in _ROOT_DOCUMENTS:
        document = _mapping(documents.get(path))
        binding = _mapping(document.get("binding")) if document is not None else None
        if binding != session_binding:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_BINDING_MISMATCH",
                    f"{path}#/binding",
                    "session evidence bindings are not exactly equal",
                )
            )
    for field, expected in kit_binding.expected_binding:
        if session_binding.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_BINDING_MISMATCH",
                    f"session.json#/binding/{field}",
                    "session binding does not match the authenticated Kit",
                )
            )

    profile = session_binding.get("profile_id")
    handoff = _mapping(documents.get("handoff.json"))
    handoff_id = handoff.get("handoff_id") if handoff is not None else None
    expected_purpose = "discovery" if mode == "discovery" else "formal"
    expected_contract = "discovery-required" if mode == "discovery" else "approved"
    mode_valid = (
        (mode == "discovery" and profile == "DISCOVERY")
        or (
            mode in ("g2", "g3-c")
            and type(profile) is str
            and profile in _FORMAL_PROFILES
        )
    )
    if (
        not mode_valid
        or handoff is None
        or handoff.get("purpose") != expected_purpose
        or handoff_id != session_binding.get("handoff_id")
        or kit_binding.reference_contract_status != expected_contract
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_MODE_BINDING",
                "session.json#/binding/session_mode",
                "mode, profile, handoff purpose or contract status do not agree",
            )
        )
    return session_binding, mode if type(mode) is str else None


def _time_diagnostics(
    documents: Mapping[str, Any], phase: EvidencePhase, diagnostics: list[Diagnostic]
) -> None:
    session = _mapping(documents.get("session.json"))
    handoff = _mapping(documents.get("handoff.json"))
    if session is None or handoff is None:
        return
    started = _utc(session.get("started_at"))
    ended = _utc(session.get("ended_at"))
    created = _utc(handoff.get("created_at"))
    expires = _utc(handoff.get("expires_at"))
    capture_status = session.get("capture_status")
    capture_state_invalid = (
        capture_status not in {"in-progress", "complete"}
        or (capture_status == "in-progress" and ended is not None)
        or (capture_status == "complete" and ended is None)
        or (phase is EvidencePhase.SEALED and capture_status != "complete")
    )
    if capture_state_invalid:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_CAPTURE_INCOMPLETE",
                "session.json#/capture_status",
                "capture lifecycle state is incomplete or inconsistent",
            )
        )
        return
    invalid = (
        started is None
        or created is None
        or expires is None
        or not created <= started < expires
        or (
            capture_status == "complete"
            and (
                ended is None
                or not started <= ended < expires
            )
        )
    )
    if invalid:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_TIME_ORDER",
                "session.json",
                "session and handoff timestamps are not monotonic",
            )
        )
        return
    for path in ("compile-result.json", "test-results.json"):
        document = _mapping(documents.get(path))
        records = document.get("records") if document is not None else None
        if type(records) is not list:
            continue
        previous_compile_end: datetime | None = None
        for index, record in enumerate(records):
            if type(record) is not dict:
                continue
            record_started = _utc(record.get("started_at"))
            record_ended = _utc(record.get("ended_at"))
            after_session = (
                record_ended is not None
                and (
                    (ended is not None and record_ended > ended)
                    or (ended is None and expires is not None and record_ended >= expires)
                )
            )
            if (record_started is None) != (record_ended is None) or (
                record_started is not None
                and record_ended is not None
                and (
                    not started <= record_started <= record_ended
                    or after_session
                )
            ):
                diagnostics.append(
                    _diagnostic(
                        "TARGET_EVIDENCE_TIME_ORDER",
                        f"{path}#/records/{index}",
                        "record timestamps fall outside the session",
                    )
                )
            if (
                path == "compile-result.json"
                and record_started is not None
                and record_ended is not None
            ):
                if (
                    previous_compile_end is not None
                    and record_started < previous_compile_end
                ):
                    diagnostics.append(
                        _diagnostic(
                            "TARGET_EVIDENCE_TIME_ORDER",
                            f"{path}#/records/{index}/started_at",
                            "Compile checkpoints are not chronologically monotonic",
                        )
                    )
                previous_compile_end = record_ended

    if phase is EvidencePhase.SEALED:
        approval = _mapping(documents.get("approval.json"))
        completion = _mapping(documents.get("SESSION_COMPLETE"))
        approved = _utc(approval.get("approved_at")) if approval is not None else None
        sealed = _utc(completion.get("sealed_at")) if completion is not None else None
        if approved is None or sealed != approved or ended is None or approved < ended:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_TIME_ORDER",
                    "SESSION_COMPLETE#/sealed_at",
                    "approval and seal timestamps are not monotonic",
                )
            )


def _reference_diagnostics(
    document: Mapping[str, Any], mode: str, contract_digest: str, diagnostics: list[Diagnostic]
) -> None:
    points = document.get("points")
    if (
        document.get("reference_contract_body_digest") != contract_digest
        or type(points) is not list
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_REFERENCE_CONTRACT_MISMATCH",
                "references.json",
                "Reference evidence does not bind the Kit contract",
            )
        )
        return
    if [item.get("point") for item in points if type(item) is dict] != list(
        _REFERENCE_POINTS
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_CHECKPOINT_ORDER",
                "references.json#/points",
                "Reference checkpoints are missing, unknown or reordered",
            )
        )

    seen_observation_ids: set[str] = set()
    for point_index, point in enumerate(points):
        if type(point) is not dict:
            continue
        observations = point.get("observations")
        if type(observations) is not list:
            continue
        if mode == "g2" and point_index > 0 and point.get("status") != "not-run":
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_MODE_BINDING",
                    f"references.json#/points/{point_index}/status",
                    "G2 permits Reference activity only at blank-project",
                )
            )
        ordered = sorted(
            observations,
            key=lambda item: (
                _sort_text(item.get("stable_reference_id")),
                _sort_text(item.get("path_sha256")),
                _sort_text(item.get("observation_record_id")),
            )
            if type(item) is dict
            else ("", "", ""),
        )
        if observations != ordered:
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_REFERENCE_ORDER",
                    f"references.json#/points/{point_index}/observations",
                    "Reference observations are not deterministically ordered",
                )
            )
        for ordinal, observation in enumerate(observations, start=1):
            if type(observation) is not dict:
                continue
            observation_id = observation.get("observation_record_id")
            if type(observation_id) is str:
                if observation_id in seen_observation_ids:
                    diagnostics.append(
                        _diagnostic(
                            "TARGET_EVIDENCE_REFERENCE_ID_MISMATCH",
                            f"references.json#/points/{point_index}/observations/{ordinal - 1}/observation_record_id",
                            "Reference observation IDs must be unique",
                        )
                    )
                seen_observation_ids.add(observation_id)
            guid = observation.get("guid")
            major = observation.get("major")
            minor = observation.get("minor")
            stable_id = observation.get("stable_reference_id")
            resolved = type(guid) is str and type(major) is int and type(minor) is int
            if resolved:
                try:
                    expected_id = resolved_reference_id(guid, major, minor)
                except ValueError:
                    expected_id = None
                if stable_id != expected_id:
                    diagnostics.append(
                        _diagnostic(
                            "TARGET_EVIDENCE_REFERENCE_ID_MISMATCH",
                            f"references.json#/points/{point_index}/observations/{ordinal - 1}/stable_reference_id",
                            "stable Reference ID does not match GUID and version",
                        )
                    )
                continue

            all_unresolved = guid is None and major is None and minor is None and stable_id is None
            unresolved_match = (
                _UNRESOLVED_ID.fullmatch(observation_id)
                if type(observation_id) is str
                else None
            )
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
            expected_prefix = sha256_bytes(canonical_json_bytes(raw_identity))[:20]
            hashed_identity = (
                unresolved_match is not None
                and unresolved_match.group(1) == expected_prefix[: len(unresolved_match.group(1))]
            )
            formal_observed = mode != "discovery" and point.get("status") == "observed"
            if not all_unresolved or not hashed_identity or formal_observed:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_EVIDENCE_REFERENCE_ID_MISMATCH",
                        f"references.json#/points/{point_index}/observations/{ordinal - 1}",
                        "unresolved Reference identity is invalid for this session state",
                    )
                )


def _compile_diagnostics(
    document: Mapping[str, Any], mode: str, diagnostics: list[Diagnostic]
) -> None:
    records = document.get("records")
    if type(records) is not list:
        return
    if [item.get("point") for item in records if type(item) is dict] != list(
        _COMPILE_POINTS
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_CHECKPOINT_ORDER",
                "compile-result.json#/records",
                "Compile checkpoints are missing, unknown or reordered",
            )
        )
    record_ids = [
        item.get("record_id") for item in records if type(item) is dict
    ]
    witness_ids = {
        witness_id
        for item in records
        if type(item) is dict
        for witness_id in (
            item.get("catia_operator_record_id"),
            item.get("vbe_operator_record_id"),
        )
        if type(witness_id) is str
    }
    if (
        len(record_ids) != len(_COMPILE_POINTS)
        or any(type(record_id) is not str for record_id in record_ids)
        or len(set(record_ids)) != len(record_ids)
        or bool(set(record_ids) & witness_ids)
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_RECORD_LINK",
                "compile-result.json#/records",
                "Compile checkpoint record IDs must be explicit and unique",
            )
        )
    if mode == "g2" and any(
        type(record) is dict and record.get("status") != "not-run" for record in records
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_MODE_BINDING",
                "compile-result.json#/records",
                "G2 does not run Compile checkpoints",
            )
        )


def _discovery_compile_diagnostics(
    document: object, diagnostics: list[Diagnostic]
) -> None:
    records = document.get("records") if isinstance(document, Mapping) else None
    forbidden = (
        not isinstance(document, Mapping)
        or frozenset(document) != {"binding", "records"}
        or type(records) is not list
        or len(records) != len(_COMPILE_POINTS)
    )
    if type(records) is list:
        forbidden = forbidden or any(
            type(record) is not dict
            or record
            != {
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
            for point, record in zip(_COMPILE_POINTS, records, strict=False)
        )
    if forbidden:
        diagnostics.append(
            _diagnostic(
                "DISCOVERY_COMPILE_FORBIDDEN",
                "compile-result.json#/records",
                "Discovery must never attempt Compile",
            )
        )


def _test_plan_diagnostics(
    document: Mapping[str, Any],
    mode: str,
    profile: object,
    kit_binding: KitEvidenceBinding,
    diagnostics: list[Diagnostic],
) -> None:
    records = document.get("records")
    cases = kit_binding.target_plan.get("cases")
    mismatch = (
        document.get("target_plan_sha256") != kit_binding.target_plan_sha256
        or type(records) is not list
        or type(cases) is not list
        or len(records) != len(cases)
    )
    if not mismatch and type(records) is list and type(cases) is list:
        for index, (record, case) in enumerate(zip(records, cases, strict=True)):
            if type(record) is not dict or type(case) is not dict:
                mismatch = True
                break
            expected = case.get("expected")
            if type(expected) is not dict or any(
                (
                    record.get("case_id") != case.get("case_id"),
                    record.get("case_definition_sha256")
                    != sha256_bytes(canonical_json_bytes(case)),
                    record.get("profile_id") != profile,
                    record.get("package_id") != case.get("package_id"),
                    record.get("tool_id") != case.get("tool_id"),
                    record.get("expected_result_code") != expected.get("result_code"),
                    record.get("expected_state")
                    != expected.get("state", expected.get("core_state")),
                )
            ):
                mismatch = True
                break
            allowed_run = mode == "g3-c" and index == 0
            if not allowed_run and (
                record.get("status") != "not-run"
                or record.get("execution_point") != "not-run"
            ):
                mismatch = True
                break
    if mismatch:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_TEST_PLAN_MISMATCH",
                "test-results.json#/records",
                "target results do not exactly bind the ordered Kit target plan",
            )
        )


def _entitlement_diagnostics(
    document: Mapping[str, Any],
    profile: object,
    diagnostics: list[Diagnostic],
) -> None:
    baseline = document.get("baseline_any_of")
    expected = {
        "P-AB3": ["AB3"],
        "P-HD2": ["HD2"],
        "P-MD2": ["MD2"],
    }.get(profile) if type(profile) is str else None
    valid = (
        type(baseline) is list
        and all(type(item) is str for item in baseline)
        and set(baseline) <= {"AB3", "HD2", "MD2"}
        and document.get("additional_required") == ["SPA", "FTA"]
    )
    if expected is not None:
        valid = valid and baseline == expected
    elif profile == "DISCOVERY":
        valid = valid and baseline == []
    else:
        valid = False
    if not valid:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_MODE_BINDING",
                "entitlements.json#/baseline_any_of",
                "license evidence does not match the selected target profile",
            )
        )


def _execution_link_diagnostics(
    documents: Mapping[str, Any], mode: str, diagnostics: list[Diagnostic]
) -> None:
    compile_document = _mapping(documents.get("compile-result.json"))
    test_document = _mapping(documents.get("test-results.json"))
    state_document = _mapping(documents.get("state-diff.json"))
    artifact_document = _mapping(documents.get("artifact-manifest.json"))
    compile_records = (
        compile_document.get("records") if compile_document is not None else None
    )
    test_records = test_document.get("records") if test_document is not None else None
    state_records = state_document.get("records") if state_document is not None else None
    if (
        type(compile_records) is not list
        or type(test_records) is not list
        or type(state_records) is not list
    ):
        return

    compile_by_point = {
        record.get("point"): record
        for record in compile_records
        if type(record) is dict and type(record.get("point")) is str
    }
    compile_ids = {
        point: record.get("record_id") for point, record in compile_by_point.items()
    }
    state_by_id = {
        record.get("record_id"): record
        for record in state_records
        if type(record) is dict and type(record.get("record_id")) is str
    }
    link_invalid = False
    if mode in ("discovery", "g2") and (
        state_document is not None
        and (
            state_document.get("overall_status") != "not-run" or bool(state_records)
        )
    ):
        link_invalid = True

    for record in test_records:
        if type(record) is not dict:
            continue
        state_id = record.get("state_diff_record_id")
        if state_id is not None:
            state_record = state_by_id.get(state_id) if type(state_id) is str else None
            if (
                state_record is None
                or state_record.get("case_id") != record.get("case_id")
                or state_record.get("execution_point") != record.get("execution_point")
                or state_record.get("operator_record_id")
                != record.get("operator_record_id")
            ):
                link_invalid = True
        if record.get("status") != "not-run":
            post_restart = compile_by_point.get("post-restart")
            compile_id = compile_ids.get("post-restart")
            test_started = _utc(record.get("started_at"))
            compile_ended = (
                _utc(post_restart.get("ended_at"))
                if isinstance(post_restart, Mapping)
                else None
            )
            if (
                record.get("compile_record_id") != compile_id
                or compile_id is None
                or compile_ended is None
                or test_started is None
                or not test_started > compile_ended
            ):
                if (
                    compile_ended is not None
                    and test_started is not None
                    and not test_started > compile_ended
                ):
                    diagnostics.append(
                        _diagnostic(
                            "TARGET_EVIDENCE_TIME_ORDER",
                            "test-results.json#/records/0/started_at",
                            "executed smoke test must start after post-restart Compile",
                        )
                    )
                else:
                    link_invalid = True

    referenced_state_ids = {
        state_id
        for record in test_records
        if type(record) is dict
        for state_id in (record.get("state_diff_record_id"),)
        if type(state_id) is str
    }
    if set(state_by_id) != referenced_state_ids:
        link_invalid = True

    if artifact_document is not None and artifact_document.get("artifact_status") == "returned":
        artifact = _mapping(artifact_document.get("artifact"))
        if artifact is None or (
            artifact.get("post_import_compile_record_id")
            != compile_ids.get("post-import")
            or artifact.get("post_restart_compile_record_id")
            != compile_ids.get("post-restart")
            or compile_ids.get("post-import") is None
            or compile_ids.get("post-restart") is None
        ):
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_ARTIFACT_MISMATCH",
                    "artifact-manifest.json#/artifact",
                    "artifact does not bind the executed Compile records",
                )
            )
    if link_invalid:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_RECORD_LINK",
                "test-results.json",
                "Compile, test and state-diff records are not bidirectionally linked",
            )
        )


def _operator_and_record_diagnostics(
    files: Mapping[str, bytes], documents: Mapping[str, Any], diagnostics: list[Diagnostic]
) -> None:
    index = _mapping(documents.get("operator-records/index.json"))
    records = index.get("records") if index is not None else None
    if type(records) is not list:
        return
    by_id: dict[str, Mapping[str, Any]] = {}
    declared_paths: set[str] = set()
    invalid = False
    session = _mapping(documents.get("session.json"))
    session_started = _utc(session.get("started_at")) if session is not None else None
    session_ended = _utc(session.get("ended_at")) if session is not None else None
    handoff = _mapping(documents.get("handoff.json"))
    handoff_expires = _utc(handoff.get("expires_at")) if handoff is not None else None
    for record in records:
        if not isinstance(record, Mapping):
            continue
        record_id = record.get("record_id")
        path = record.get("relative_path")
        if (
            type(record_id) is not str
            or type(path) is not str
            or record_id in by_id
            or path in declared_paths
            or files.get(path) is None
            or sha256_bytes(files[path]) != record.get("sha256")
        ):
            invalid = True
            continue
        by_id[record_id] = record
        declared_paths.add(path)
        captured = _utc(record.get("captured_at"))
        captured_after_session = (
            captured is not None
            and (
                (session_ended is not None and captured > session_ended)
                or (
                    session_ended is None
                    and handoff_expires is not None
                    and captured >= handoff_expires
                )
            )
        )
        if (
            captured is None
            or session_started is None
            or (session_ended is None and handoff_expires is None)
            or captured < session_started
            or captured_after_session
        ):
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_TIME_ORDER",
                    f"operator-records/index.json#/records/{len(by_id) - 1}/captured_at",
                    "operator record timestamp falls outside the session",
                )
            )
    actual_paths = {
        path for path in files if path.startswith("operator-records/") and path != "operator-records/index.json"
    }
    if actual_paths != declared_paths:
        invalid = True

    referenced: list[tuple[str, object]] = []
    if session is not None:
        referenced.append(("session.json#/notes_record_id", session.get("notes_record_id")))
    environment = _mapping(documents.get("environment.json"))
    if environment is not None:
        referenced.append(("environment.json#/operator_record_id", environment.get("operator_record_id")))
    entitlements = _mapping(documents.get("entitlements.json"))
    if entitlements is not None:
        for field in (
            "configuration_product",
            "reference_visibility",
            "api_workbench",
            "session_checkout",
            "tool_result",
        ):
            value = _mapping(entitlements.get(field))
            if value is not None:
                referenced.append((f"entitlements.json#/{field}/operator_record_id", value.get("operator_record_id")))
    references = _mapping(documents.get("references.json"))
    points = references.get("points") if references is not None else None
    if type(points) is list:
        for point_index, point in enumerate(points):
            if type(point) is not dict:
                continue
            referenced.append((f"references.json#/points/{point_index}/operator_record_id", point.get("operator_record_id")))
            observations = point.get("observations")
            if type(observations) is list:
                for observation_index, observation in enumerate(observations):
                    if type(observation) is dict:
                        referenced.append((f"references.json#/points/{point_index}/observations/{observation_index}/operator_record_id", observation.get("operator_record_id")))
    compile_document = _mapping(documents.get("compile-result.json"))
    compile_records = compile_document.get("records") if compile_document is not None else None
    if type(compile_records) is list:
        for index_value, record in enumerate(compile_records):
            if type(record) is dict:
                referenced.extend(
                    (
                        (f"compile-result.json#/records/{index_value}/catia_operator_record_id", record.get("catia_operator_record_id")),
                        (f"compile-result.json#/records/{index_value}/vbe_operator_record_id", record.get("vbe_operator_record_id")),
                    )
                )
    tests = _mapping(documents.get("test-results.json"))
    test_records = tests.get("records") if tests is not None else None
    if type(test_records) is list:
        for index_value, record in enumerate(test_records):
            if type(record) is dict:
                referenced.append((f"test-results.json#/records/{index_value}/operator_record_id", record.get("operator_record_id")))
    state = _mapping(documents.get("state-diff.json"))
    state_records = state.get("records") if state is not None else None
    if type(state_records) is list:
        for index_value, record in enumerate(state_records):
            if type(record) is dict:
                referenced.append((f"state-diff.json#/records/{index_value}/operator_record_id", record.get("operator_record_id")))
    for path, record_id in referenced:
        if record_id is not None and (
            type(record_id) is not str or record_id not in by_id
        ):
            invalid = True
            diagnostics.append(
                _diagnostic(
                    "TARGET_EVIDENCE_RECORD_LINK",
                    path,
                    "operator record reference is not resolved by the index",
                )
            )
    if invalid and not any(item.code == "TARGET_EVIDENCE_RECORD_LINK" for item in diagnostics):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_RECORD_LINK",
                "operator-records/index.json",
                "operator index does not exactly bind member bytes",
            )
        )


def _artifact_diagnostics(
    files: Mapping[str, bytes], document: Mapping[str, Any], diagnostics: list[Diagnostic]
) -> None:
    if document.get("artifact_status") != "returned":
        return
    artifact = _mapping(document.get("artifact"))
    data = files.get("returned-catvba/core.catvba")
    if (
        artifact is None
        or data is None
        or artifact.get("relative_path") != "returned-catvba/core.catvba"
        or artifact.get("sha256") != sha256_bytes(data)
        or artifact.get("size") != len(data)
        or artifact.get("readonly") is not True
    ):
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_ARTIFACT_MISMATCH",
                "artifact-manifest.json#/artifact",
                "returned artifact bytes do not match the manifest",
            )
        )


def _seal_diagnostics(
    files: Mapping[str, bytes],
    documents: Mapping[str, Any],
    binding: Mapping[str, Any],
    kit: BuildKitInspection,
    kit_binding: KitEvidenceBinding,
    payload_digest: str,
    diagnostics: list[Diagnostic],
) -> None:
    receipt = _mapping(documents.get("gate-receipt.json"))
    approval = _mapping(documents.get("approval.json"))
    completion = _mapping(documents.get("SESSION_COMPLETE"))
    if receipt is None or approval is None or completion is None:
        return
    mode = binding.get("session_mode")
    gate = _MODE_GATE.get(mode) if type(mode) is str else None
    receipt_bytes = files.get("gate-receipt.json")
    approval_bytes = files.get("approval.json")
    sums = files.get("SHA256SUMS")
    if receipt_bytes is None or approval_bytes is None or sums is None:
        return

    receipt_identity = {
        "session_id": binding.get("session_id"),
        "session_mode": mode,
        "gate_id": gate,
        "kit_id": kit.kit_id,
        "kit_zip_sha256": kit.canonical_zip_sha256,
        "kit_verifier_report_digest": kit_binding.verifier_report_digest,
        "evidence_payload_digest": payload_digest,
    }
    approval_identity = {
        "session_id": binding.get("session_id"),
        "session_mode": mode,
        "gate_id": gate,
        "evidence_payload_digest": payload_digest,
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
    }
    expected_scope = "observation" if mode == "discovery" else "gate"
    identity_invalid = any(receipt.get(field) != value for field, value in receipt_identity.items())
    identity_invalid = identity_invalid or any(
        approval.get(field) != value for field, value in approval_identity.items()
    )
    identity_invalid = identity_invalid or approval.get("approval_scope") != expected_scope

    approval_body = dict(approval)
    approval_body.pop("approval_id", None)
    expected_approval_id = (
        "approval-" + sha256_bytes(canonical_json_bytes(approval_body))[:20]
    )
    session = _mapping(documents.get("session.json")) or {}
    identity_invalid = identity_invalid or (
        approval.get("approval_id") != expected_approval_id
        or approval.get("approval_status") not in {"approved", "rejected"}
        or approval.get("review_record_id")
        in _capture_record_ids(documents, files)
        or approval.get("reviewer_role")
        in {session.get("builder_role"), session.get("standard_user_role")}
    )

    bundle_files = {
        path: data
        for path, data in files.items()
        if path not in {"SHA256SUMS", "SESSION_COMPLETE"}
    }
    _, bundle_digest, _ = canonical_payload_manifest(bundle_files)
    expected_sums = "".join(
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(bundle_files.items(), key=lambda item: item[0].encode("ascii"))
    ).encode("ascii")
    closure = {
        "session_id": binding.get("session_id"),
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": payload_digest,
        "sha256sums_sha256": sha256_bytes(sums),
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_sha256": sha256_bytes(approval_bytes),
        "sealed_at": approval.get("approved_at"),
    }
    closure_invalid = sums != expected_sums or any(
        completion.get(field) != value for field, value in closure.items()
    )
    if identity_invalid or closure_invalid:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_HASH_CLOSURE",
                "SESSION_COMPLETE",
                "sealed decision identity or SHA-256 closure is invalid",
            )
        )


def _nested_g2_diagnostics(
    data: bytes,
    outer_documents: Mapping[str, Any],
    kit: BuildKitInspection,
    schema_dir: os.PathLike[str] | str,
    nesting_depth: int,
    diagnostics: list[Diagnostic],
) -> None:
    if nesting_depth >= 1:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_NESTING_DEPTH",
                NESTED_G2_PATH,
                "G2 prerequisite exceeds the one-level evidence nesting limit",
            )
        )
        return
    nested_snapshot = _read_zip_bytes(
        data,
        phase=EvidencePhase.SEALED,
        nesting_depth=nesting_depth + 1,
        container_sha256=sha256_bytes(data),
    )
    if nested_snapshot.diagnostics:
        for item in nested_snapshot.diagnostics:
            code = (
                "TARGET_EVIDENCE_NESTING_DEPTH"
                if item.code == "EVIDENCE_NESTING_DEPTH"
                else item.code
            )
            diagnostics.append(
                _diagnostic(code, f"{NESTED_G2_PATH}!/{item.path}", item.message)
            )
        return
    nested = _inspect_snapshot(
        nested_snapshot,
        kit,
        phase=EvidencePhase.SEALED,
        schema_dir=schema_dir,
        nesting_depth=nesting_depth + 1,
    )
    if not nested.report.ok:
        diagnostics.extend(
            _diagnostic(
                item.code,
                f"{NESTED_G2_PATH}!/{item.path}",
                item.message,
            )
            for item in nested.report.diagnostics
        )
        return
    nested_documents = dict(nested.documents)
    outer_session = _mapping(outer_documents.get("session.json"))
    outer_environment = _mapping(outer_documents.get("environment.json"))
    outer_references = _mapping(outer_documents.get("references.json"))
    nested_session = _mapping(nested_documents.get("session.json"))
    nested_environment = _mapping(nested_documents.get("environment.json"))
    nested_references = _mapping(nested_documents.get("references.json"))
    outer_handoff = _mapping(outer_documents.get("handoff.json"))
    nested_files = dict(nested_snapshot.files)
    outer_binding = _mapping(outer_session.get("binding")) if outer_session is not None else None
    nested_binding = _mapping(nested_session.get("binding")) if nested_session is not None else None
    inherited = (
        nested_binding is not None
        and nested_binding.get("session_mode") == "g2"
        and outer_handoff is not None
        and nested_files.get("handoff.json") == canonical_json_bytes(outer_handoff)
        and outer_binding is not None
        and nested_binding.get("profile_id") == outer_binding.get("profile_id")
        and nested_binding.get("handoff_id") == outer_binding.get("handoff_id")
        and nested_session is not None
        and outer_session is not None
        and nested_session.get("anonymous_host_id") == outer_session.get("anonymous_host_id")
        and nested_session.get("vm_lineage_id") == outer_session.get("vm_lineage_id")
        and nested_environment is not None
        and outer_environment is not None
        and nested_environment.get("environment_fingerprint")
        == outer_environment.get("environment_fingerprint")
        and nested_environment.get("catia") == outer_environment.get("catia")
        and nested_references is not None
        and outer_references is not None
        and nested_references.get("reference_contract_body_digest")
        == outer_references.get("reference_contract_body_digest")
    )
    if not inherited:
        diagnostics.append(
            _diagnostic(
                "TARGET_EVIDENCE_PREREQUISITE_MISMATCH",
                NESTED_G2_PATH,
                "G3-C prerequisite does not inherit the stable G2 environment "
                "fingerprint and identity",
            )
        )


def _inspect_snapshot(
    snapshot: EvidenceContainerSnapshot,
    kit: BuildKitInspection,
    *,
    phase: EvidencePhase,
    schema_dir: os.PathLike[str] | str,
    nesting_depth: int,
) -> TargetEvidenceInspection:
    boundary_diagnostics = _snapshot_boundary_diagnostics(snapshot)
    if snapshot.diagnostics or boundary_diagnostics:
        return _empty_inspection(
            phase, kit, [*snapshot.diagnostics, *boundary_diagnostics]
        )
    files = dict(snapshot.files)
    diagnostics: list[Diagnostic] = []
    _required_and_seal_policy(files, phase, diagnostics)
    documents = _parse_documents(files, phase, schema_dir, diagnostics)
    _file_policy(snapshot, files, documents, phase, diagnostics)

    kit_binding, kit_diagnostics = load_kit_evidence_binding(kit)
    diagnostics.extend(kit_diagnostics)
    if kit_binding is None:
        return _empty_inspection(
            phase,
            kit,
            diagnostics,
            files=snapshot.files,
            documents=tuple(sorted(documents.items())),
        )

    binding, mode = _binding_diagnostics(documents, kit_binding, diagnostics)
    session = _mapping(documents.get("session.json"))
    session_binding = (
        _mapping(session.get("binding")) if session is not None else None
    )
    if (
        session_binding is not None
        and session_binding.get("session_mode") == "discovery"
    ):
        _discovery_compile_diagnostics(
            documents.get("compile-result.json"), diagnostics
        )
    if binding is not None and mode is not None:
        handoff = documents.get("handoff.json")
        if session is not None and type(session.get("started_at")) is str:
            try:
                handoff_report = validate_handoff(
                    kit, handoff, effective_at=session["started_at"]
                )
            except (TypeError, ValueError):
                diagnostics.append(
                    _diagnostic(
                        "TARGET_EVIDENCE_SCHEMA_INVALID",
                        "handoff.json",
                        "invalid handoff value cannot cross the schema boundary",
                    )
                )
            else:
                diagnostics.extend(handoff_report.diagnostics)
        _time_diagnostics(documents, phase, diagnostics)
        environment = _mapping(documents.get("environment.json"))
        if environment is not None:
            digest = environment.get("reference_contract_body_digest")
            fingerprint_value = environment.get("environment_fingerprint")
            fingerprint_valid = fingerprint_value is None
            if fingerprint_value is not None:
                try:
                    fingerprint = environment_fingerprint(
                        {"session": session, "environment": environment}, digest
                    )
                except (TypeError, ValueError):
                    fingerprint = None
                fingerprint_valid = (
                    fingerprint_value == fingerprint
                    and session is not None
                    and all(
                        type(session.get(field)) is str
                        for field in (
                            "anonymous_host_id",
                            "vm_lineage_id",
                            "snapshot_id",
                        )
                    )
                )
            if digest != kit_binding.reference_contract_body_digest or not fingerprint_valid:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_EVIDENCE_FINGERPRINT_MISMATCH",
                        "environment.json#/environment_fingerprint",
                        "environment fingerprint does not bind the governed projection",
                    )
                )
        references = _mapping(documents.get("references.json"))
        if references is not None:
            _reference_diagnostics(
                references,
                mode,
                kit_binding.reference_contract_body_digest,
                diagnostics,
            )
        compile_document = _mapping(documents.get("compile-result.json"))
        if compile_document is not None:
            _compile_diagnostics(compile_document, mode, diagnostics)
        tests = _mapping(documents.get("test-results.json"))
        if tests is not None:
            _test_plan_diagnostics(
                tests, mode, binding.get("profile_id"), kit_binding, diagnostics
            )
        entitlements = _mapping(documents.get("entitlements.json"))
        if entitlements is not None:
            _entitlement_diagnostics(
                entitlements,
                binding.get("profile_id"),
                diagnostics,
            )
        artifact = _mapping(documents.get("artifact-manifest.json"))
        if artifact is not None:
            _artifact_diagnostics(files, artifact, diagnostics)
        _execution_link_diagnostics(documents, mode, diagnostics)
        _operator_and_record_diagnostics(files, documents, diagnostics)

    payload_files = {
        path: data for path, data in files.items() if path not in _SEAL_DOCUMENTS
    }
    try:
        _, payload_digest, payload_members = canonical_payload_manifest(payload_files)
    except EvidenceError:
        payload_digest = None
        payload_members = ()
    if (
        phase is EvidencePhase.SEALED
        and binding is not None
        and payload_digest is not None
    ):
        _seal_diagnostics(
            files,
            documents,
            binding,
            kit,
            kit_binding,
            payload_digest,
            diagnostics,
        )
    if mode == "g3-c" and NESTED_G2_PATH in files:
        _nested_g2_diagnostics(
            files[NESTED_G2_PATH],
            documents,
            kit,
            schema_dir,
            nesting_depth,
            diagnostics,
        )

    stable_diagnostics = tuple(sorted(set(diagnostics)))
    report = TargetEvidenceReport(
        phase=phase,
        session_id=(binding.get("session_id") if binding is not None else None),
        evidence_payload_digest=(payload_digest if not stable_diagnostics else None),
        payload_members=(payload_members if not stable_diagnostics else ()),
        diagnostics=stable_diagnostics,
    )
    inspection = TargetEvidenceInspection(
        report=report,
        files=snapshot.files,
        documents=tuple(sorted(documents.items())),
        kit=kit,
    )
    if phase is EvidencePhase.SEALED and inspection.report.ok:
        # Import lazily so Gate evaluation can reuse the structural validator
        # without creating a module import cycle.
        from .gate import sealed_gate_diagnostics

        try:
            gate_diagnostics = sealed_gate_diagnostics(inspection)
        except (BuildKitError, OSError, TypeError, ValueError):
            gate_diagnostics = (
                _diagnostic(
                    "TARGET_EVIDENCE_GATE_MISMATCH",
                    "gate-receipt.json",
                    "embedded Gate receipt cannot be recomputed",
                ),
            )
        if gate_diagnostics:
            stable_diagnostics = tuple(
                sorted(set((*inspection.report.diagnostics, *gate_diagnostics)))
            )
            inspection = TargetEvidenceInspection(
                report=TargetEvidenceReport(
                    phase=phase,
                    session_id=(
                        binding.get("session_id") if binding is not None else None
                    ),
                    evidence_payload_digest=None,
                    payload_members=(),
                    diagnostics=stable_diagnostics,
                ),
                files=inspection.files,
                documents=inspection.documents,
                kit=inspection.kit,
            )
    return inspection


def validate_target_evidence(
    evidence: EvidenceContainerSnapshot | os.PathLike[str] | str,
    kit: BuildKitInspection,
    *,
    phase: EvidencePhase,
    schema_dir: os.PathLike[str] | str,
    nesting_depth: int = 0,
) -> TargetEvidenceReport:
    """Validate one immutable evidence snapshot without reopening Kit inputs."""
    try:
        stable_phase = EvidencePhase(phase)
    except (TypeError, ValueError):
        return TargetEvidenceReport(
            phase=EvidencePhase.CAPTURE,
            session_id=None,
            evidence_payload_digest=None,
            payload_members=(),
            diagnostics=(
                _diagnostic(
                    "TARGET_EVIDENCE_PHASE_INVALID", "phase", "invalid evidence phase"
                ),
            ),
        )
    if stable_phase is EvidencePhase.RAW:
        return TargetEvidenceReport(
            phase=stable_phase,
            session_id=None,
            evidence_payload_digest=None,
            payload_members=(),
            diagnostics=(_diagnostic(
                "TARGET_EVIDENCE_PHASE_INVALID", "phase",
                "formal evidence validation cannot consume raw transports",
            ),),
        )
    if (
        type(nesting_depth) is not int
        or nesting_depth < 0
        or nesting_depth > 1
    ):
        return TargetEvidenceReport(
            phase=stable_phase,
            session_id=None,
            evidence_payload_digest=None,
            payload_members=(),
            diagnostics=(
                _diagnostic(
                    "TARGET_EVIDENCE_NESTING_DEPTH",
                    "nesting_depth",
                    "invalid evidence nesting depth",
                ),
            ),
        )
    snapshot = (
        evidence
        if isinstance(evidence, EvidenceContainerSnapshot)
        else read_evidence_container(
            evidence, phase=stable_phase, nesting_depth=nesting_depth
        )
    )
    return _inspect_snapshot(
        snapshot,
        kit,
        phase=stable_phase,
        schema_dir=schema_dir,
        nesting_depth=nesting_depth,
    ).report


_RAW_MANIFEST_FIELDS = frozenset({
    "schema_version", "session_id", "created_at", "trust_level", "mode",
    "package_id", "profile_id", "bundle_id", "kit_id", "handoff_id",
    "compile_status", "target_case_status", "artifact_status",
    "release_eligible", "members",
})
_RAW_REQUIRED = RAW_REQUIRED_DOCUMENTS | {"raw-capture-manifest.json", "SHA256SUMS"}


def _raw_report(
    diagnostics: list[Diagnostic],
    *,
    session_id: str | None = None,
    digest: str | None = None,
    members: tuple[Any, ...] = (),
) -> TargetEvidenceReport:
    stable = tuple(sorted(set(diagnostics)))
    return TargetEvidenceReport(
        phase=EvidencePhase.RAW,
        session_id=session_id if not stable else None,
        evidence_payload_digest=digest if not stable else None,
        payload_members=members if not stable else (),
        diagnostics=stable,
    )


def _validate_raw_snapshot(snapshot: EvidenceContainerSnapshot) -> TargetEvidenceReport:
    """Ingest raw/untrusted Discovery transport without computing a Gate.

    Collector documents intentionally remain distinct from formal evidence
    schemas.  This function validates their transport and immutable Discovery
    boundaries; a subsequent explicit mapping step is required before calling
    :func:`validate_target_evidence` with ``EvidencePhase.CAPTURE``.
    """

    boundary = _snapshot_boundary_diagnostics(snapshot)
    if snapshot.diagnostics or boundary:
        return _raw_report([*snapshot.diagnostics, *boundary])
    files = dict(snapshot.files)
    diagnostics: list[Diagnostic] = []
    for path in sorted(_RAW_REQUIRED - files.keys()):
        diagnostics.append(_diagnostic(
            "TARGET_EVIDENCE_REQUIRED_FILE", path, "required raw member is missing",
        ))
    for path in sorted(files):
        folded = path.casefold()
        if (
            folded in {"session_complete", "approval.json", "gate-receipt.json"}
            or folded.startswith("returned-catvba/")
        ):
            diagnostics.append(_diagnostic(
                "TARGET_EVIDENCE_SEAL_FORBIDDEN", path,
                "raw capture cannot contain a seal, decision or returned CATVBA",
            ))
        if path not in _RAW_REQUIRED and not path.startswith("operator-records/"):
            diagnostics.append(_diagnostic(
                "TARGET_EVIDENCE_FILE_POLICY", path,
                "raw capture contains an undeclared member",
            ))

    documents: dict[str, Any] = {}
    governance_json = RAW_REQUIRED_DOCUMENTS | {"raw-capture-manifest.json"}
    for path, data in sorted(files.items()):
        if path in governance_json:
            try:
                documents[path] = parse_canonical_json_bytes(data)
            except CanonicalJsonError:
                diagnostics.append(_diagnostic(
                    "TARGET_EVIDENCE_JSON_INVALID", path,
                    "raw JSON is not strict canonical JSON",
                ))
    try:
        shared_documents = validate_raw_capture_files(files, controls=True)
    except CollectorError as error:
        diagnostics.append(_diagnostic(
            error.code, error.detail or "files",
            "raw capture violates the shared target/A-environment semantic contract",
        ))
    else:
        documents.update(shared_documents)

    manifest = _mapping(documents.get("raw-capture-manifest.json"))
    if manifest is None or frozenset(manifest) != _RAW_MANIFEST_FIELDS:
        diagnostics.append(_diagnostic(
            "RAW_CAPTURE_MANIFEST_INVALID", "raw-capture-manifest.json",
            "raw manifest is missing or has an unknown field",
        ))
    else:
        schema_path = Path(__file__).parents[2] / "schemas" / "raw-capture-manifest.schema.json"
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema_errors = sorted(
                Draft202012Validator(
                    schema, format_checker=Draft202012Validator.FORMAT_CHECKER
                ).iter_errors(manifest),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            schema_errors = [None]
        for error in schema_errors:
            pointer = "" if error is None else "/" + "/".join(
                str(part) for part in error.absolute_path
            )
            diagnostics.append(_diagnostic(
                "RAW_CAPTURE_MANIFEST_INVALID",
                f"raw-capture-manifest.json#{pointer}",
                "raw manifest violates its governed schema",
            ))
        fixed = {
            "schema_version": 1, "trust_level": "raw-untrusted",
            "mode": "discovery", "package_id": "core", "profile_id": "DISCOVERY",
            "compile_status": "not-run", "target_case_status": "not-run",
            "artifact_status": "not-produced", "release_eligible": False,
        }
        for key, expected in fixed.items():
            if manifest.get(key) != expected:
                code = "DISCOVERY_COMPILE_FORBIDDEN" if key == "compile_status" else "RAW_CAPTURE_MANIFEST_INVALID"
                diagnostics.append(_diagnostic(
                    code, f"raw-capture-manifest.json#/{key}",
                    "raw boundary invariant mismatch",
                ))
        expected_members = [
            {"path": path, "sha256": sha256_bytes(data), "size": len(data)}
            for path, data in sorted(snapshot.files)
            if path != "raw-capture-manifest.json"
        ]
        if manifest.get("members") != expected_members:
            diagnostics.append(_diagnostic(
                "RAW_CAPTURE_MANIFEST_MISMATCH", "raw-capture-manifest.json#/members",
                "raw manifest does not exactly cover every non-self member",
            ))

    expected_checksum = "".join(
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(snapshot.files)
        if path not in {"SHA256SUMS", "raw-capture-manifest.json"}
    ).encode("ascii")
    if files.get("SHA256SUMS") != expected_checksum:
        diagnostics.append(_diagnostic(
            "RAW_CAPTURE_CHECKSUM_MISMATCH", "SHA256SUMS",
            "raw checksum file does not cover the observation payload",
        ))

    session = _mapping(documents.get("session.json"))
    if session is None:
        diagnostics.append(_diagnostic(
            "TARGET_EVIDENCE_REQUIRED_FILE", "session.json", "raw session is missing",
        ))
    else:
        if manifest is not None:
            for key in ("session_id", "created_at", "bundle_id", "kit_id", "handoff_id"):
                if manifest.get(key) != session.get(key):
                    diagnostics.append(_diagnostic(
                        "RAW_CAPTURE_IDENTITY_MISMATCH", f"raw-capture-manifest.json#/{key}",
                        "raw manifest identity differs from the session",
                    ))
    if "compile-result.json" in documents:
        compile_document = _mapping(documents["compile-result.json"])
        _discovery_compile_diagnostics(
            {
                "binding": {},
                "records": compile_document.get("records") if compile_document is not None else None,
            },
            diagnostics,
        )
    if diagnostics:
        return _raw_report(diagnostics)

    payload = {
        path: data for path, data in files.items()
        if path not in {"SHA256SUMS", "raw-capture-manifest.json"}
    }
    try:
        _manifest_bytes, digest, members = canonical_payload_manifest(payload)
    except EvidenceError:
        return _raw_report([_diagnostic(
            "TARGET_EVIDENCE_FILE_POLICY", "files", "raw payload namespace is invalid",
        )])
    session_id = session.get("session_id") if session is not None else None
    return _raw_report(
        [],
        session_id=session_id if type(session_id) is str else None,
        digest=digest,
        members=members,
    )


def validate_raw_capture(
    evidence: os.PathLike[str] | str,
) -> TargetEvidenceReport:
    """Validate only one authenticated regular ``.zip`` raw transport path."""

    if isinstance(evidence, EvidenceContainerSnapshot) or not isinstance(evidence, (str, os.PathLike)):
        return _raw_report([_diagnostic(
            "RAW_CAPTURE_ZIP_REQUIRED", "evidence",
            "production raw ingestion accepts only a regular ZIP path",
        )])
    return _validate_raw_snapshot(read_raw_evidence_container(evidence))
