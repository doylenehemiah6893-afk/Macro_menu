from __future__ import annotations

import copy
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from ..canonical import (
    CanonicalJsonError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    sha256_bytes,
)
from ..errors import EvidenceError, InfrastructureError
from ..handoff import validate_handoff
from ..model import BuildKitInspection
from . import container as _container
from .container import (
    EvidenceContainerSnapshot,
    canonical_evidence_zip_bytes,
    canonical_payload_manifest,
    read_evidence_container,
)
from .kit_binding import KitEvidenceBinding, load_kit_evidence_binding
from .model import EvidencePhase, SessionMode, TargetSessionReceipt
from .validator import environment_fingerprint, validate_target_evidence


_SESSION_ID = re.compile(r"^session-[a-z0-9][a-z0-9-]{2,94}$")
_FORMAL_PROFILES = frozenset({"P-AB3", "P-HD2", "P-MD2", "P-ALL", "P-PROD"})
_REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
_COMPILE_POINTS = ("blank-project", "post-import", "post-save", "post-restart")
_MAX_HANDOFF_BYTES = 4 * 1024 * 1024


def _error(code: str, *details: object) -> EvidenceError:
    suffix = ":" + ":".join(str(item) for item in details) if details else ""
    return EvidenceError(code + suffix)


def _current_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _read_regular_file(path_value: os.PathLike[str] | str) -> bytes:
    try:
        data, _absolute_path = _container._read_regular_path(
            path_value, max_bytes=_MAX_HANDOFF_BYTES
        )
    except (_container._ContainerFault, OSError, TypeError, ValueError) as error:
        raise _error("TARGET_SESSION_HANDOFF_INVALID") from error
    return data


def _parse_handoff(
    path: os.PathLike[str] | str,
    inspection: BuildKitInspection,
    *,
    effective_at: str,
) -> tuple[bytes, dict[str, Any]]:
    data = _read_regular_file(path)
    try:
        document = parse_canonical_json_bytes(data)
    except CanonicalJsonError as error:
        raise _error("TARGET_SESSION_HANDOFF_INVALID") from error
    if type(document) is not dict:
        raise _error("TARGET_SESSION_HANDOFF_INVALID")
    try:
        report = validate_handoff(inspection, document, effective_at=effective_at)
    except (TypeError, ValueError) as error:
        raise _error("TARGET_SESSION_HANDOFF_INVALID") from error
    if not report.ok:
        codes = ",".join(item.code for item in report.diagnostics)
        raise _error("TARGET_SESSION_HANDOFF_INVALID", codes)
    return data, document


def _profile_baseline(profile_id: str) -> list[str]:
    fixed = {
        "P-AB3": ["AB3"],
        "P-HD2": ["HD2"],
        "P-MD2": ["MD2"],
        "P-ALL": ["AB3", "HD2", "MD2"],
    }
    if profile_id in fixed:
        return fixed[profile_id]
    if profile_id in {"DISCOVERY", "P-PROD"}:
        return []
    raise _error("TARGET_SESSION_PROFILE_INVALID")


def _binding(
    kit_binding: KitEvidenceBinding,
    *,
    session_id: str,
    mode: SessionMode,
    profile_id: str,
    handoff_id: str,
) -> dict[str, Any]:
    result = dict(kit_binding.expected_binding)
    result.update(
        {
            "session_id": session_id,
            "session_mode": mode.value,
            "profile_id": profile_id,
            "handoff_id": handoff_id,
        }
    )
    return result


def _not_run_environment(
    binding: Mapping[str, Any],
    contract_digest: str,
) -> dict[str, Any]:
    return {
        "binding": dict(binding),
        "windows": None,
        "catia": None,
        "catia_environment": None,
        "vba": None,
        "dsls": None,
        "security": {
            "office_state": "unknown",
            "network_state": "unknown",
            "powershell_state": "unknown",
            "wsh_state": "unknown",
        },
        "accounts_isolated": None,
        "pollution_scan": {
            "b30": "not-run",
            "x86": "not-run",
            "vba6": "not-run",
            "syswow64": "not-run",
            "temp_com": "not-run",
            "user_com": "not-run",
        },
        "reference_contract_body_digest": contract_digest,
        "environment_fingerprint": None,
        "operator_record_id": None,
    }


def _not_run_compile(point: str) -> dict[str, Any]:
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


def _not_run_results(
    kit_binding: KitEvidenceBinding, *, profile_id: str
) -> list[dict[str, Any]]:
    cases = kit_binding.target_plan.get("cases")
    if type(cases) is not list or len(cases) != 30:
        raise _error("TARGET_SESSION_TARGET_PLAN_INVALID")
    records: list[dict[str, Any]] = []
    for case in cases:
        if type(case) is not dict or type(case.get("expected")) is not dict:
            raise _error("TARGET_SESSION_TARGET_PLAN_INVALID")
        expected = case["expected"]
        records.append(
            {
                "case_id": case.get("case_id"),
                "case_definition_sha256": sha256_bytes(
                    canonical_json_bytes(case)
                ),
                "profile_id": profile_id,
                "package_id": case.get("package_id"),
                "tool_id": case.get("tool_id"),
                "execution_point": "not-run",
                "compile_record_id": None,
                "status": "not-run",
                "expected_result_code": expected.get("result_code"),
                "expected_state": expected.get("state", expected.get("core_state")),
                "observed_result_code": None,
                "observed_state": None,
                "started_at": None,
                "ended_at": None,
                "operator_record_id": None,
                "state_diff_record_id": None,
                "failure_classification": None,
            }
        )
    return records


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


def _g3_prerequisite(
    prerequisite: os.PathLike[str] | str,
    inspection: BuildKitInspection,
    handoff_bytes: bytes,
    *,
    profile_id: str,
    started_at: str,
    schema_dir: os.PathLike[str] | str,
) -> tuple[
    bytes,
    dict[str, Any],
    dict[str, Any],
    tuple[str, ...] | None,
    tuple[tuple[int, int], ...] | None,
]:
    snapshot = read_evidence_container(
        prerequisite,
        phase=EvidencePhase.SEALED,
    )
    report = validate_target_evidence(
        snapshot,
        inspection,
        phase=EvidencePhase.SEALED,
        schema_dir=schema_dir,
    )
    if not report.ok:
        codes = ",".join(item.code for item in report.diagnostics)
        raise _error("TARGET_SESSION_PREREQUISITE_INVALID", codes)
    files = dict(snapshot.files)
    try:
        nested_session = parse_canonical_json_bytes(files["session.json"])
        nested_environment = parse_canonical_json_bytes(files["environment.json"])
        receipt = parse_canonical_json_bytes(files["gate-receipt.json"])
        approval = parse_canonical_json_bytes(files["approval.json"])
        completion = parse_canonical_json_bytes(files["SESSION_COMPLETE"])
    except (KeyError, CanonicalJsonError) as error:
        raise _error("TARGET_SESSION_PREREQUISITE_INVALID") from error
    if not all(
        type(value) is dict
        for value in (
            nested_session,
            nested_environment,
            receipt,
            approval,
            completion,
        )
    ):
        raise _error("TARGET_SESSION_PREREQUISITE_INVALID")
    nested_binding = nested_session.get("binding")
    outer_started = _utc(started_at)
    nested_sealed = _utc(completion.get("sealed_at"))
    if (
        type(nested_binding) is not dict
        or nested_binding.get("session_mode") != "g2"
        or nested_binding.get("package_id") != "core"
        or nested_binding.get("profile_id") != profile_id
        or files.get("handoff.json") != handoff_bytes
        or receipt.get("gate_id") != "G2"
        or receipt.get("computed_outcome") != "eligible"
        or approval.get("approval_scope") != "gate"
        or approval.get("approval_status") != "approved"
        or outer_started is None
        or nested_sealed is None
        or outer_started < nested_sealed
    ):
        raise _error("TARGET_SESSION_PREREQUISITE_INVALID")
    return (
        canonical_evidence_zip_bytes(files),
        nested_session,
        nested_environment,
        snapshot.directories if snapshot.container_sha256 is None else None,
        snapshot.directory_identities if snapshot.container_sha256 is None else None,
    )


def _same_or_descendant(candidate: str, parent: str) -> bool:
    try:
        return os.path.commonpath((candidate, parent)) == parent
    except ValueError:
        return False


def _existing_directory_identities(
    absolute_path: str,
) -> tuple[tuple[int, int], ...]:
    parts = Path(absolute_path).parts
    identities: list[tuple[int, int]] = []
    for length in range(1, len(parts) + 1):
        prefix = os.fspath(Path(*parts[:length]))
        try:
            descriptor, _absolute, signature = _container._open_directory_path(
                prefix
            )
        except _container._ContainerFault as fault:
            if fault.code == "EVIDENCE_PATH_MISSING":
                break
            raise InfrastructureError(fault.code) from fault
        else:
            os.close(descriptor)
            identities.append((signature[0], signature[1]))
    return tuple(identities)


def _reject_prerequisite_output_overlap(
    prerequisite: os.PathLike[str] | str,
    prerequisite_directories: tuple[str, ...],
    output_root: os.PathLike[str] | str,
    directory_name: str,
    *,
    prerequisite_identities: tuple[tuple[int, int], ...] | None = None,
    invalid_code: str = "TARGET_SESSION_PREREQUISITE_INVALID",
    overlap_code: str = "TARGET_SESSION_PREREQUISITE_OUTPUT_OVERLAP",
) -> None:
    try:
        absolute_prerequisite = _container._absolute_path(prerequisite)
        absolute_output = _container._absolute_path(output_root)
    except _container._ContainerFault as fault:
        raise _error(invalid_code, fault.code) from fault
    final_output = os.path.join(absolute_output, directory_name)
    if _same_or_descendant(
        absolute_output, absolute_prerequisite
    ) or _same_or_descendant(absolute_prerequisite, final_output):
        raise _error(overlap_code)

    source_identities = set(prerequisite_identities or ())
    if not source_identities:
        source_paths = (
            absolute_prerequisite,
            *(
                os.path.join(absolute_prerequisite, *relative.split("/"))
                for relative in prerequisite_directories
            ),
        )
        for source_path in source_paths:
            try:
                descriptor, _absolute, signature = _container._open_directory_path(
                    source_path
                )
            except _container._ContainerFault as fault:
                raise _error(invalid_code, fault.code) from fault
            try:
                source_identities.add((signature[0], signature[1]))
            finally:
                os.close(descriptor)

    for candidate in (absolute_output, final_output):
        if source_identities.intersection(
            _existing_directory_identities(candidate)
        ):
            raise _error(overlap_code)


def _publish_directory(
    files: Mapping[str, bytes],
    *,
    directory_name: str,
    output_root: os.PathLike[str] | str,
) -> Path:
    _container._require_publication_capabilities()
    _container._validate_bundle_name(directory_name)
    items = _container._validated_file_items(files)
    try:
        root_fd, absolute_root, root_signature = _container._open_directory_path(
            output_root, create=True
        )
    except _container._ContainerFault as fault:
        raise InfrastructureError(fault.code) from fault

    _manifest, staging_digest, _members = canonical_payload_manifest(dict(items))
    temporary_name = f".{directory_name}.{staging_digest[:24]}.dir"
    staged = False
    try:
        if _container._entry_kind(root_fd, directory_name) is not None:
            raise _error("TARGET_SESSION_OUTPUT_CONFLICT")
        _container._stage_directory(root_fd, temporary_name, items)
        staged = True
        if not _container._rewalk_identity_matches(absolute_root, root_signature):
            raise InfrastructureError("TARGET_SESSION_OUTPUT_ROOT_RACE")
        _container._rename_directory_noreplace(
            root_fd, temporary_name, directory_name
        )
        staged = False
        os.fsync(root_fd)
        if not _container._rewalk_identity_matches(absolute_root, root_signature):
            raise InfrastructureError("TARGET_SESSION_OUTPUT_ROOT_RACE")
        return Path(absolute_root) / directory_name
    except FileExistsError as error:
        raise _error("TARGET_SESSION_OUTPUT_CONFLICT") from error
    except OSError as error:
        raise InfrastructureError("TARGET_SESSION_PUBLICATION_FAILED") from error
    finally:
        cleanup_error: OSError | None = None
        try:
            if staged:
                _container._remove_tree_at(root_fd, temporary_name)
                os.fsync(root_fd)
        except OSError as error:
            cleanup_error = error
        finally:
            os.close(root_fd)
        if cleanup_error is not None:
            raise InfrastructureError("TARGET_SESSION_TEMP_CLEANUP_FAILED") from cleanup_error


def init_target_session(
    kit: BuildKitInspection,
    handoff: os.PathLike[str] | str,
    output_root: os.PathLike[str] | str,
    *,
    mode: SessionMode | str,
    package_id: str,
    profile_id: str,
    schema_dir: os.PathLike[str] | str,
    prerequisite_evidence: os.PathLike[str] | str | None = None,
    session_id: str | None = None,
    created_at: str | None = None,
) -> TargetSessionReceipt:
    """Create one validated canonical capture skeleton outside the Kit."""
    try:
        stable_mode = SessionMode(mode)
    except (TypeError, ValueError) as error:
        raise _error("TARGET_SESSION_MODE_INVALID") from error
    if package_id != "core" or type(profile_id) is not str:
        raise _error("TARGET_SESSION_SCOPE_INVALID")
    if (
        stable_mode is SessionMode.DISCOVERY
        and profile_id != "DISCOVERY"
    ) or (
        stable_mode is not SessionMode.DISCOVERY
        and profile_id not in _FORMAL_PROFILES
    ):
        raise _error("TARGET_SESSION_PROFILE_INVALID")
    if (stable_mode is SessionMode.G3_C) != (prerequisite_evidence is not None):
        raise _error("TARGET_SESSION_PREREQUISITE_INVALID")

    stable_session_id = (
        session_id if session_id is not None else f"session-{secrets.token_hex(16)}"
    )
    stable_created_at = created_at if created_at is not None else _current_utc()
    if (
        type(stable_session_id) is not str
        or _SESSION_ID.fullmatch(stable_session_id) is None
        or type(stable_created_at) is not str
    ):
        raise _error("TARGET_SESSION_IDENTITY_INVALID")

    kit_binding, kit_diagnostics = load_kit_evidence_binding(kit)
    if kit_binding is None:
        codes = ",".join(item.code for item in kit_diagnostics)
        raise _error("TARGET_SESSION_KIT_INVALID", codes)
    handoff_bytes, handoff_document = _parse_handoff(
        handoff,
        kit,
        effective_at=stable_created_at,
    )
    expected_purpose = (
        "discovery" if stable_mode is SessionMode.DISCOVERY else "formal"
    )
    expected_contract = (
        "discovery-required"
        if stable_mode is SessionMode.DISCOVERY
        else "approved"
    )
    contract = handoff_document.get("reference_contract")
    if (
        handoff_document.get("purpose") != expected_purpose
        or not isinstance(contract, Mapping)
        or contract.get("status") != expected_contract
        or kit_binding.reference_contract_status != expected_contract
    ):
        raise _error("TARGET_SESSION_HANDOFF_MODE_MISMATCH")

    binding = _binding(
        kit_binding,
        session_id=stable_session_id,
        mode=stable_mode,
        profile_id=profile_id,
        handoff_id=str(handoff_document["handoff_id"]),
    )
    inherited_session: dict[str, Any] | None = None
    inherited_environment: dict[str, Any] | None = None
    prerequisite_bytes: bytes | None = None
    prerequisite_directories: tuple[str, ...] | None = None
    prerequisite_identities: tuple[tuple[int, int], ...] | None = None
    if prerequisite_evidence is not None:
        (
            prerequisite_bytes,
            inherited_session,
            inherited_environment,
            prerequisite_directories,
            prerequisite_identities,
        ) = _g3_prerequisite(
            prerequisite_evidence,
            kit,
            handoff_bytes,
            profile_id=profile_id,
            started_at=stable_created_at,
            schema_dir=schema_dir,
        )

    session_document: dict[str, Any] = {
        "binding": binding,
        "capture_status": "in-progress",
        "anonymous_host_id": (
            inherited_session["anonymous_host_id"]
            if inherited_session is not None
            else None
        ),
        "vm_lineage_id": (
            inherited_session["vm_lineage_id"]
            if inherited_session is not None
            else None
        ),
        "snapshot_id": (
            inherited_session["snapshot_id"]
            if inherited_session is not None
            else None
        ),
        "builder_role": "isolated-builder",
        "standard_user_role": "isolated-standard-user",
        "started_at": stable_created_at,
        "ended_at": None,
        "production_macro_library_touched": False,
        "supersedes_session_id": None,
        "notes_record_id": None,
    }

    if inherited_environment is None:
        environment_document = _not_run_environment(
            binding,
            kit_binding.reference_contract_body_digest,
        )
    else:
        environment_document = copy.deepcopy(inherited_environment)
        environment_document["binding"] = binding
        environment_document["security"] = {
            "office_state": "unknown",
            "network_state": "unknown",
            "powershell_state": "unknown",
            "wsh_state": "unknown",
        }
        environment_document["accounts_isolated"] = None
        environment_document["pollution_scan"] = {
            "b30": "not-run",
            "x86": "not-run",
            "vba6": "not-run",
            "syswow64": "not-run",
            "temp_com": "not-run",
            "user_com": "not-run",
        }
        environment_document["operator_record_id"] = None
        recomputed = environment_fingerprint(
            {"session": session_document, "environment": environment_document},
            kit_binding.reference_contract_body_digest,
        )
        if recomputed != inherited_environment.get("environment_fingerprint"):
            raise _error("TARGET_SESSION_PREREQUISITE_ENVIRONMENT_MISMATCH")
        environment_document["environment_fingerprint"] = recomputed

    status_record = {"status": "not-run", "operator_record_id": None}
    entitlements_document = {
        "binding": binding,
        "configuration_product": dict(status_record),
        "reference_visibility": dict(status_record),
        "api_workbench": dict(status_record),
        "session_checkout": dict(status_record),
        "tool_result": dict(status_record),
        "baseline_any_of": _profile_baseline(profile_id),
        "additional_required": ["SPA", "FTA"],
        "set_license_used": False,
        "scripted_reference_selection_used": False,
        "licensing_repository_modified": False,
    }
    references_document = {
        "binding": binding,
        "reference_contract_body_digest": kit_binding.reference_contract_body_digest,
        "points": [
            {
                "point": point,
                "status": "not-run",
                "observations": [],
                "operator_record_id": None,
            }
            for point in _REFERENCE_POINTS
        ],
    }
    compile_document = {
        "binding": binding,
        "records": [_not_run_compile(point) for point in _COMPILE_POINTS],
    }
    test_document = {
        "binding": binding,
        "target_plan_sha256": kit_binding.target_plan_sha256,
        "records": _not_run_results(kit_binding, profile_id=profile_id),
    }
    state_document = {"binding": binding, "overall_status": "not-run", "records": []}
    artifact_document = {
        "binding": binding,
        "artifact_status": "not-produced",
        "artifact": None,
        "release_eligible": False,
    }

    operator_index = {"binding": binding, "records": []}

    documents = {
        "session.json": session_document,
        "environment.json": environment_document,
        "entitlements.json": entitlements_document,
        "references.json": references_document,
        "compile-result.json": compile_document,
        "test-results.json": test_document,
        "state-diff.json": state_document,
        "artifact-manifest.json": artifact_document,
        "operator-records/index.json": operator_index,
    }
    files = {
        path: canonical_json_bytes(document)
        for path, document in documents.items()
    }
    files["handoff.json"] = handoff_bytes
    if prerequisite_bytes is not None:
        files[_container.NESTED_G2_PATH] = prerequisite_bytes
    files = dict(sorted(files.items()))

    validation = validate_target_evidence(
        _snapshot(files),
        kit,
        phase=EvidencePhase.CAPTURE,
        schema_dir=schema_dir,
    )
    if not validation.ok or validation.evidence_payload_digest is None:
        codes = ",".join(item.code for item in validation.diagnostics)
        raise _error("TARGET_SESSION_SELF_VALIDATION_FAILED", codes)
    _manifest, payload_digest, _members = canonical_payload_manifest(files)
    if payload_digest != validation.evidence_payload_digest:
        raise _error("TARGET_SESSION_SELF_VALIDATION_FAILED")

    directory_name = f"target-session-{stable_session_id}"
    if prerequisite_evidence is not None and prerequisite_directories is not None:
        _reject_prerequisite_output_overlap(
            prerequisite_evidence,
            prerequisite_directories,
            output_root,
            directory_name,
            prerequisite_identities=prerequisite_identities,
        )
    session_directory = _publish_directory(
        files,
        directory_name=directory_name,
        output_root=output_root,
    )
    return TargetSessionReceipt(
        session_id=stable_session_id,
        session_dir=os.fspath(session_directory),
        mode=stable_mode,
        kit_id=kit.kit_id or "",
        evidence_payload_digest=payload_digest,
    )


__all__ = ["init_target_session"]
