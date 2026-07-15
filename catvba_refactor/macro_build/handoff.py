from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import (
    CanonicalJsonError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    sha256_bytes,
)
from .errors import EvidenceError, InfrastructureError, VerificationError
from .kit import inspect_build_kit
from .model import BuildKitInspection, Diagnostic, ValidationReport, VerificationReport


@dataclass(frozen=True)
class HandoffRequest:
    purpose: str
    created_at: str
    expires_at: str
    revocation_snapshot: bytes
    prepared_record_id: str
    review_record_id: str
    supersedes_handoff: bytes | None = None


@dataclass(frozen=True)
class HandoffReceipt:
    handoff_id: str
    handoff_path: str
    handoff_sha256: str
    kit_id: str
    kit_zip_sha256: str


_KIT_ID = re.compile(r"^kit-[0-9a-f]{20}$")
_HANDOFF_ID = re.compile(r"^handoff-[a-z0-9][a-z0-9-]{2,94}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_WORK_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,126}$")
_RECORD_ID = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")

_VERIFIER_FIELDS = (
    "primary_directory_verifier_report_digest",
    "comparison_directory_verifier_report_digest",
    "primary_zip_verifier_report_digest",
    "comparison_zip_verifier_report_digest",
)
_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "handoff_id",
        "purpose",
        "created_at",
        "expires_at",
        "revocation_status",
        "revocation_snapshot_sha256",
        "kit_id",
        "catalog_sha256",
        "manifest_sha256",
        "manifest_digest",
        "zip_sha256",
        "zip_sidecar_sha256",
        "work_commit",
        "work_tree",
        "work_branch",
        "upstream_cutoff",
        "fork_dev_cutoff",
        "package_id",
        "target",
        "compile_status",
        "release_eligible",
        "generation_command",
        *_VERIFIER_FIELDS,
        "prepared_record_id",
        "review_record_id",
        "reference_contract",
    }
)
_REVOCATION_FIELDS = frozenset(
    {
        "schema_version",
        "captured_at",
        "source",
        "active_handoff_ids",
        "withdrawn_handoff_ids",
    }
)
_REFERENCE_CONTRACT_FIELDS = frozenset(
    {
        "status",
        "contract_id",
        "contract_version",
        "contract_body_digest",
        "reference_definitions",
        "observations",
        "transitions",
        "path_policy",
        "approval",
    }
)


def _evidence_error(code: str, detail: str | None = None) -> EvidenceError:
    return EvidenceError(code if detail is None else f"{code}: {detail}")


def _infrastructure_error(
    code: str, detail: str | None = None, *, cause: BaseException | None = None
) -> InfrastructureError:
    error = InfrastructureError(code if detail is None else f"{code}: {detail}")
    if cause is not None:
        error.__cause__ = cause
    return error


def _utc(value: object) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message)


def _diagnostic_document(diagnostic: Diagnostic) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "path": diagnostic.path,
        "message": diagnostic.message,
        "details": diagnostic.details,
    }


def _verifier_digest(report: VerificationReport) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "ok": report.ok and not report.diagnostics,
                "diagnostics": [
                    _diagnostic_document(item)
                    for item in sorted(report.diagnostics)
                ],
            }
        )
    )


def _triplet(root_value: str | os.PathLike[str]) -> tuple[Path, Path, Path]:
    root = Path(root_value)
    try:
        entries = tuple(root.iterdir())
    except OSError as error:
        raise _evidence_error("HANDOFF_KIT_TRIPLET_COUNT", os.fspath(root)) from error

    directories: dict[str, Path] = {}
    zips: dict[str, Path] = {}
    sidecars: dict[str, Path] = {}
    for entry in entries:
        name = entry.name
        try:
            status = entry.lstat()
        except OSError as error:
            raise _evidence_error(
                "HANDOFF_KIT_TRIPLET_COUNT", os.fspath(entry)
            ) from error
        if _KIT_ID.fullmatch(name) and (
            stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode)
        ):
            directories[name] = entry
            continue
        if name.endswith(".zip"):
            kit_id = name[:-4]
            if _KIT_ID.fullmatch(kit_id) and (
                stat.S_ISREG(status.st_mode) or stat.S_ISLNK(status.st_mode)
            ):
                zips[kit_id] = entry
            continue
        if name.endswith(".zip.sha256"):
            kit_id = name[: -len(".zip.sha256")]
            if _KIT_ID.fullmatch(kit_id) and (
                stat.S_ISREG(status.st_mode) or stat.S_ISLNK(status.st_mode)
            ):
                sidecars[kit_id] = entry

    ids = set(directories) & set(zips) & set(sidecars)
    exact = (
        len(ids) == 1
        and set(directories) == ids
        and set(zips) == ids
        and set(sidecars) == ids
    )
    if not exact:
        raise _evidence_error("HANDOFF_KIT_TRIPLET_COUNT", os.fspath(root))
    kit_id = next(iter(ids))
    return directories[kit_id], zips[kit_id], sidecars[kit_id]


def _require_authenticated(inspection: BuildKitInspection, label: str) -> None:
    if not inspection.report.ok or inspection.report.diagnostics:
        codes = ",".join(item.code for item in inspection.report.diagnostics)
        raise VerificationError(
            f"HANDOFF_KIT_VERIFICATION_FAILED: {label}"
            + (f": {codes}" if codes else "")
        )


def _identity(inspection: BuildKitInspection) -> tuple[object, ...]:
    return (
        inspection.kit_id,
        inspection.catalog_sha256,
        inspection.manifest_sha256,
        inspection.manifest_digest,
        inspection.upstream_commit,
        inspection.fork_dev_commit,
        inspection.work_commit,
        inspection.work_tree,
        inspection.work_branch,
        inspection.canonical_zip_sha256,
    )


def _captured_json(inspection: BuildKitInspection, path: str) -> dict[str, Any]:
    files = dict(inspection.files)
    try:
        value = parse_canonical_json_bytes(files[path])
    except (KeyError, CanonicalJsonError) as error:
        raise _evidence_error("HANDOFF_AUTHENTICATED_DOCUMENT_INVALID", path) from error
    if type(value) is not dict:
        raise _evidence_error("HANDOFF_AUTHENTICATED_DOCUMENT_INVALID", path)
    return value


def _core_reference_contract(inspection: BuildKitInspection) -> dict[str, Any]:
    catalog = _captured_json(inspection, "catalog.json")
    packages = catalog.get("packages")
    if type(packages) is not list:
        raise _evidence_error("HANDOFF_CORE_PACKAGE_INVALID")
    core = [
        item
        for item in packages
        if isinstance(item, dict) and item.get("package_id") == "core"
    ]
    if len(core) != 1:
        raise _evidence_error("HANDOFF_CORE_PACKAGE_INVALID")
    companion = _captured_json(inspection, "references/core.json")
    if companion.get("package_id") != "core":
        raise _evidence_error("HANDOFF_CORE_PACKAGE_INVALID")
    contract = companion.get("reference_contract")
    if type(contract) is not dict:
        raise _evidence_error("HANDOFF_CORE_PACKAGE_INVALID")
    status = contract.get("status")
    if status not in {"discovery-required", "approved"}:
        raise _evidence_error("HANDOFF_CORE_PACKAGE_INVALID")

    contract_body_digest = companion.get("contract_body_digest")
    if not isinstance(contract_body_digest, str):
        contract_body_digest = sha256_bytes(canonical_json_bytes(contract))
    reference_definitions = contract.get("reference_definitions")
    path_policy = contract.get("path_policy")
    return {
        "status": status,
        "contract_id": "reference-contract-core",
        "contract_version": contract.get("contract_version"),
        "contract_body_digest": contract_body_digest,
        "reference_definitions": (
            reference_definitions if isinstance(reference_definitions, list) else []
        ),
        "observations": contract.get("observation_points"),
        "transitions": contract.get("transitions"),
        "path_policy": (
            path_policy
            if isinstance(path_policy, dict)
            else {
                "allowed_root_kinds": [
                    "catia-install",
                    "windows-install",
                    "system",
                ],
                "allow_user_paths": False,
            }
        ),
        "approval": contract.get("approval"),
    }


def _parse_revocation_snapshot(data: bytes, *, created_at: datetime) -> dict[str, Any]:
    try:
        value = parse_canonical_json_bytes(data)
    except CanonicalJsonError as error:
        raise _evidence_error("REVOCATION_SNAPSHOT_INVALID") from error
    if type(value) is not dict or frozenset(value) != _REVOCATION_FIELDS:
        raise _evidence_error("REVOCATION_SNAPSHOT_INVALID")
    captured_at = _utc(value.get("captured_at"))
    source = value.get("source")
    active = value.get("active_handoff_ids")
    withdrawn = value.get("withdrawn_handoff_ids")
    arrays_valid = (
        type(active) is list
        and type(withdrawn) is list
        and all(type(item) is str and _HANDOFF_ID.fullmatch(item) for item in active)
        and all(type(item) is str and _HANDOFF_ID.fullmatch(item) for item in withdrawn)
        and len(active) == len(set(active))
        and len(withdrawn) == len(set(withdrawn))
        and not (set(active) & set(withdrawn))
    )
    if (
        value.get("schema_version") != 1
        or type(value.get("schema_version")) is not int
        or captured_at is None
        or captured_at > created_at
        or type(source) is not str
        or _SOURCE.fullmatch(source) is None
        or not arrays_valid
        or active
    ):
        raise _evidence_error("REVOCATION_SNAPSHOT_INVALID")
    return value


def _reference_contract_shape_valid(contract: object) -> bool:
    if type(contract) is not dict or frozenset(contract) != _REFERENCE_CONTRACT_FIELDS:
        return False
    status = contract.get("status")
    path_policy = contract.get("path_policy")
    roots = path_policy.get("allowed_root_kinds") if isinstance(path_policy, dict) else None
    common = (
        status in {"discovery-required", "approved"}
        and contract.get("contract_id") == "reference-contract-core"
        and contract.get("contract_version") == 1
        and type(contract.get("contract_version")) is int
        and type(contract.get("contract_body_digest")) is str
        and _SHA256.fullmatch(contract["contract_body_digest"]) is not None
        and type(contract.get("reference_definitions")) is list
        and isinstance(path_policy, dict)
        and frozenset(path_policy) == {"allowed_root_kinds", "allow_user_paths"}
        and type(roots) is list
        and bool(roots)
        and len(roots) == len(set(roots))
        and set(roots) <= {"catia-install", "windows-install", "system"}
        and path_policy.get("allow_user_paths") is False
    )
    if not common:
        return False
    if status == "discovery-required":
        return (
            contract["reference_definitions"] == []
            and contract.get("observations") is None
            and contract.get("transitions") is None
            and contract.get("approval") is None
        )
    return (
        isinstance(contract.get("observations"), dict)
        and type(contract.get("transitions")) is list
        and isinstance(contract.get("approval"), dict)
    )


def _basic_document_diagnostics(
    document: object, *, effective_at: object
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    def add(code: str, path: str, message: str) -> None:
        diagnostics.append(_diagnostic(code, path, message))

    if type(document) is not dict:
        add("HANDOFF_DOCUMENT_INVALID", "handoff.json", "handoff must be an object")
        return diagnostics
    purpose = document.get("purpose")
    expected_fields = _BASE_FIELDS | (
        {"supersedes_handoff_id"} if purpose == "formal" else set()
    )
    if frozenset(document) != frozenset(expected_fields):
        add(
            "HANDOFF_DOCUMENT_INVALID",
            "handoff.json",
            "handoff has missing or unknown fields",
        )
    if purpose not in {"discovery", "formal"}:
        add("HANDOFF_PURPOSE_INVALID", "handoff.json#/purpose", "purpose is invalid")
    if document.get("schema_version") != 1 or type(document.get("schema_version")) is not int:
        add("HANDOFF_DOCUMENT_INVALID", "handoff.json#/schema_version", "schema version is invalid")

    body = dict(document)
    handoff_id = body.pop("handoff_id", None)
    try:
        expected_id = "handoff-" + sha256_bytes(canonical_json_bytes(body))[:20]
    except (RecursionError, TypeError, ValueError):
        expected_id = None
    if handoff_id != expected_id:
        add("HANDOFF_ID_MISMATCH", "handoff.json#/handoff_id", "handoff ID does not bind its body")

    created = _utc(document.get("created_at"))
    expires = _utc(document.get("expires_at"))
    effective = _utc(effective_at)
    if created is None or expires is None or effective is None or not created < expires:
        add("HANDOFF_TIME_INVALID", "handoff.json", "handoff timestamps are invalid")
    elif effective < created:
        add("HANDOFF_NOT_YET_ACTIVE", "handoff.json#/created_at", "handoff is not yet active")
    elif effective >= expires:
        add("HANDOFF_EXPIRED", "handoff.json#/expires_at", "handoff has expired")
    if document.get("revocation_status") != "active":
        add("HANDOFF_REVOKED", "handoff.json#/revocation_status", "handoff is revoked")
    if document.get("package_id") != "core":
        add("HANDOFF_PACKAGE_INVALID", "handoff.json#/package_id", "handoff package must be core")
    kit_id = document.get("kit_id")
    if type(kit_id) is not str or _KIT_ID.fullmatch(kit_id) is None:
        add("HANDOFF_DOCUMENT_INVALID", "handoff.json#/kit_id", "Kit ID is invalid")
    for field in (
        "work_commit",
        "work_tree",
        "upstream_cutoff",
        "fork_dev_cutoff",
    ):
        value = document.get(field)
        if type(value) is not str or _GIT_OID.fullmatch(value) is None:
            add(
                "HANDOFF_DOCUMENT_INVALID",
                f"handoff.json#/{field}",
                "Git object ID is invalid",
            )
    branch = document.get("work_branch")
    if type(branch) is not str or _WORK_BRANCH.fullmatch(branch) is None:
        add(
            "HANDOFF_DOCUMENT_INVALID",
            "handoff.json#/work_branch",
            "work branch is invalid",
        )
    if document.get("target") != "CATIA R2018/VBA7 64":
        add("HANDOFF_TARGET_INVALID", "handoff.json#/target", "handoff target is invalid")
    if document.get("compile_status") != "not-run" or document.get("release_eligible") is not False:
        add(
            "HANDOFF_STATUS_INVALID",
            "handoff.json",
            "handoff status must remain not-run and ineligible",
        )
    if document.get("generation_command") != "macro-menu-build create-target-handoff":
        add(
            "HANDOFF_DOCUMENT_INVALID",
            "handoff.json#/generation_command",
            "generation command is invalid",
        )
    for field in (
        "revocation_snapshot_sha256",
        "catalog_sha256",
        "manifest_sha256",
        "manifest_digest",
        "zip_sha256",
        "zip_sidecar_sha256",
        *_VERIFIER_FIELDS,
    ):
        value = document.get(field)
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            add("HANDOFF_DOCUMENT_INVALID", f"handoff.json#/{field}", "SHA-256 digest is invalid")
    for field in ("prepared_record_id", "review_record_id"):
        value = document.get(field)
        if type(value) is not str or _RECORD_ID.fullmatch(value) is None:
            add("HANDOFF_DOCUMENT_INVALID", f"handoff.json#/{field}", "record ID is invalid")
    contract = document.get("reference_contract")
    status = contract.get("status") if isinstance(contract, dict) else None
    if not _reference_contract_shape_valid(contract):
        add(
            "HANDOFF_DOCUMENT_INVALID",
            "handoff.json#/reference_contract",
            "Reference contract shape is invalid",
        )
    if (purpose, status) not in {
        ("discovery", "discovery-required"),
        ("formal", "approved"),
    }:
        add(
            "HANDOFF_CONTRACT_PURPOSE_MISMATCH",
            "handoff.json#/reference_contract/status",
            "handoff purpose does not match the Reference contract",
        )
    supersedes = document.get("supersedes_handoff_id")
    if purpose == "formal" and (
        type(supersedes) is not str or _HANDOFF_ID.fullmatch(supersedes) is None
    ):
        add(
            "HANDOFF_SUPERSEDES_INVALID",
            "handoff.json#/supersedes_handoff_id",
            "formal handoff requires a valid supersedes ID",
        )
    return diagnostics


def validate_handoff(
    inspection: BuildKitInspection,
    document: object,
    *,
    effective_at: str,
) -> ValidationReport:
    """Validate one detached handoff against an authenticated Kit snapshot."""
    diagnostics = _basic_document_diagnostics(document, effective_at=effective_at)
    if not inspection.report.ok or inspection.report.diagnostics:
        diagnostics.append(
            _diagnostic(
                "HANDOFF_KIT_VERIFICATION_FAILED",
                "kit",
                "Kit inspection is not authenticated",
            )
        )
        return ValidationReport(tuple(sorted(set(diagnostics)))).sorted()
    if type(document) is not dict:
        return ValidationReport(tuple(sorted(set(diagnostics)))).sorted()

    expected = {
        "kit_id": inspection.kit_id,
        "catalog_sha256": inspection.catalog_sha256,
        "manifest_sha256": inspection.manifest_sha256,
        "manifest_digest": inspection.manifest_digest,
        "zip_sha256": inspection.canonical_zip_sha256,
        "work_commit": inspection.work_commit,
        "work_tree": inspection.work_tree,
        "work_branch": inspection.work_branch,
        "upstream_cutoff": inspection.upstream_commit,
        "fork_dev_cutoff": inspection.fork_dev_commit,
    }
    for field, value in expected.items():
        if document.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "HANDOFF_KIT_IDENTITY_MISMATCH",
                    f"handoff.json#/{field}",
                    "handoff does not bind the authenticated Kit",
                )
            )
    if inspection.kit_id is not None and inspection.canonical_zip_sha256 is not None:
        sidecar = (
            f"{inspection.canonical_zip_sha256}  {inspection.kit_id}.zip\n".encode(
                "ascii"
            )
        )
        if document.get("zip_sidecar_sha256") != sha256_bytes(sidecar):
            diagnostics.append(
                _diagnostic(
                    "HANDOFF_KIT_IDENTITY_MISMATCH",
                    "handoff.json#/zip_sidecar_sha256",
                    "handoff does not bind the canonical ZIP sidecar",
                )
            )
    try:
        contract = _core_reference_contract(inspection)
    except EvidenceError:
        diagnostics.append(
            _diagnostic(
                "HANDOFF_CORE_PACKAGE_INVALID",
                "kit",
                "authenticated Kit has no valid Core Reference contract",
            )
        )
    else:
        if document.get("reference_contract") != contract:
            diagnostics.append(
                _diagnostic(
                    "HANDOFF_REFERENCE_CONTRACT_MISMATCH",
                    "handoff.json#/reference_contract",
                    "handoff does not bind the authenticated Core Reference contract",
                )
            )
    return ValidationReport(tuple(sorted(set(diagnostics)))).sorted()


def _validate_request(request: HandoffRequest) -> tuple[datetime, dict[str, Any]]:
    created = _utc(request.created_at)
    expires = _utc(request.expires_at)
    if (
        request.purpose not in {"discovery", "formal"}
        or created is None
        or expires is None
        or not created < expires
        or type(request.prepared_record_id) is not str
        or type(request.review_record_id) is not str
        or _RECORD_ID.fullmatch(request.prepared_record_id) is None
        or _RECORD_ID.fullmatch(request.review_record_id) is None
    ):
        raise _evidence_error("HANDOFF_REQUEST_INVALID")
    snapshot = _parse_revocation_snapshot(
        request.revocation_snapshot, created_at=created
    )
    if request.purpose == "discovery" and request.supersedes_handoff is not None:
        raise _evidence_error("HANDOFF_SUPERSEDES_FORBIDDEN")
    if request.purpose == "formal" and request.supersedes_handoff is None:
        raise _evidence_error("HANDOFF_SUPERSEDES_REQUIRED")
    return created, snapshot


def _parse_superseded(
    data: bytes,
    *,
    snapshot: dict[str, Any],
    created_at: str,
    current: BuildKitInspection,
) -> dict[str, Any]:
    try:
        value = parse_canonical_json_bytes(data)
    except CanonicalJsonError as error:
        raise _evidence_error("HANDOFF_SUPERSEDED_INVALID") from error
    diagnostics = _basic_document_diagnostics(value, effective_at=created_at)
    if type(value) is not dict or diagnostics:
        raise _evidence_error("HANDOFF_SUPERSEDED_INVALID")
    if (
        value.get("purpose") != "discovery"
        or value.get("revocation_status") != "active"
        or value.get("package_id") != "core"
        or value.get("target") != "CATIA R2018/VBA7 64"
        or value.get("handoff_id") not in snapshot["withdrawn_handoff_ids"]
    ):
        raise _evidence_error("HANDOFF_SUPERSEDED_INVALID")
    if value.get("kit_id") == current.kit_id:
        raise _evidence_error("HANDOFF_SUPERSEDED_INVALID")
    for field, expected in (
        ("work_branch", current.work_branch),
        ("upstream_cutoff", current.upstream_commit),
        ("fork_dev_cutoff", current.fork_dev_commit),
    ):
        if value.get(field) != expected:
            raise _evidence_error("HANDOFF_SUPERSEDED_IDENTITY_MISMATCH", field)
    return value


def _reject_symlink_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            status = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise _infrastructure_error(
                "HANDOFF_OUTPUT_INSPECTION_FAILED", os.fspath(current), cause=error
            )
        if stat.S_ISLNK(status.st_mode):
            raise _infrastructure_error("HANDOFF_OUTPUT_SYMLINK_FORBIDDEN")


def _read_regular_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise _infrastructure_error(
            "HANDOFF_ID_CONTENT_MISMATCH", path.name, cause=error
        )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise _infrastructure_error("HANDOFF_ID_CONTENT_MISMATCH", path.name)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _publish(root_value: str | os.PathLike[str], handoff_id: str, data: bytes) -> Path:
    root = Path(os.path.abspath(os.fspath(root_value)))
    _reject_symlink_ancestors(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _infrastructure_error("HANDOFF_OUTPUT_CREATE_FAILED", cause=error)
    _reject_symlink_ancestors(root)
    try:
        status = root.lstat()
    except OSError as error:
        raise _infrastructure_error("HANDOFF_OUTPUT_CREATE_FAILED", cause=error)
    if not stat.S_ISDIR(status.st_mode):
        raise _infrastructure_error("HANDOFF_OUTPUT_NOT_DIRECTORY")

    destination = root / f"{handoff_id}.json"
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{handoff_id}.tmp-", dir=root
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o644)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            existing = _read_regular_nofollow(destination)
            if existing != data:
                raise _infrastructure_error(
                    "HANDOFF_ID_CONTENT_MISMATCH", handoff_id
                )
        except OSError as error:
            raise _infrastructure_error(
                "HANDOFF_PUBLISH_FAILED", handoff_id, cause=error
            )
        else:
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return destination
    except InfrastructureError:
        raise
    except OSError as error:
        raise _infrastructure_error("HANDOFF_PUBLISH_FAILED", handoff_id, cause=error)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _path_is_within(path: Path, directory: Path) -> bool:
    path_text = os.path.abspath(os.fspath(path))
    directory_text = os.path.abspath(os.fspath(directory))
    try:
        return os.path.commonpath((path_text, directory_text)) == directory_text
    except ValueError:
        return False


def issue_target_handoff(
    primary_build_root: str | os.PathLike[str],
    comparison_build_root: str | os.PathLike[str],
    request: HandoffRequest,
    output_root: str | os.PathLike[str],
) -> HandoffReceipt:
    """Authenticate two independent Kit builds and issue one detached handoff."""
    _created, revocations = _validate_request(request)
    primary_dir, primary_zip, _primary_sidecar = _triplet(primary_build_root)
    comparison_dir, comparison_zip, _comparison_sidecar = _triplet(
        comparison_build_root
    )
    inspections = (
        inspect_build_kit(primary_dir),
        inspect_build_kit(primary_zip),
        inspect_build_kit(comparison_dir),
        inspect_build_kit(comparison_zip),
    )
    labels = (
        "primary directory",
        "primary ZIP",
        "comparison directory",
        "comparison ZIP",
    )
    for inspection, label in zip(inspections, labels, strict=True):
        _require_authenticated(inspection, label)
    first = inspections[0]
    if any(
        inspection.files != first.files or _identity(inspection) != _identity(first)
        for inspection in inspections[1:]
    ):
        raise _evidence_error("HANDOFF_KIT_MISMATCH")
    if first.kit_id is None or first.canonical_zip_sha256 is None:
        raise _evidence_error("HANDOFF_KIT_MISMATCH")
    output_path = Path(output_root)
    if _path_is_within(output_path, primary_dir) or _path_is_within(
        output_path, comparison_dir
    ):
        raise _evidence_error("HANDOFF_OUTPUT_INSIDE_KIT")

    contract = _core_reference_contract(first)
    expected_status = (
        "discovery-required" if request.purpose == "discovery" else "approved"
    )
    if contract["status"] != expected_status:
        raise _evidence_error("HANDOFF_CONTRACT_PURPOSE_MISMATCH")

    superseded: dict[str, Any] | None = None
    if request.supersedes_handoff is not None:
        superseded = _parse_superseded(
            request.supersedes_handoff,
            snapshot=revocations,
            created_at=request.created_at,
            current=first,
        )

    sidecar_bytes = (
        f"{first.canonical_zip_sha256}  {first.kit_id}.zip\n".encode("ascii")
    )
    body: dict[str, Any] = {
        "schema_version": 1,
        "purpose": request.purpose,
        "created_at": request.created_at,
        "expires_at": request.expires_at,
        "revocation_status": "active",
        "revocation_snapshot_sha256": sha256_bytes(request.revocation_snapshot),
        "kit_id": first.kit_id,
        "catalog_sha256": first.catalog_sha256,
        "manifest_sha256": first.manifest_sha256,
        "manifest_digest": first.manifest_digest,
        "zip_sha256": first.canonical_zip_sha256,
        "zip_sidecar_sha256": sha256_bytes(sidecar_bytes),
        "work_commit": first.work_commit,
        "work_tree": first.work_tree,
        "work_branch": first.work_branch,
        "upstream_cutoff": first.upstream_commit,
        "fork_dev_cutoff": first.fork_dev_commit,
        "package_id": "core",
        "target": "CATIA R2018/VBA7 64",
        "compile_status": "not-run",
        "release_eligible": False,
        "generation_command": "macro-menu-build create-target-handoff",
        "primary_directory_verifier_report_digest": _verifier_digest(
            inspections[0].report
        ),
        "primary_zip_verifier_report_digest": _verifier_digest(
            inspections[1].report
        ),
        "comparison_directory_verifier_report_digest": _verifier_digest(
            inspections[2].report
        ),
        "comparison_zip_verifier_report_digest": _verifier_digest(
            inspections[3].report
        ),
        "prepared_record_id": request.prepared_record_id,
        "review_record_id": request.review_record_id,
        "reference_contract": contract,
    }
    if superseded is not None:
        body["supersedes_handoff_id"] = superseded["handoff_id"]
    handoff_id = "handoff-" + sha256_bytes(canonical_json_bytes(body))[:20]
    if handoff_id in revocations["withdrawn_handoff_ids"]:
        raise _evidence_error("HANDOFF_WITHDRAWN_AT_ISSUANCE")
    if superseded is not None and handoff_id == superseded["handoff_id"]:
        raise _evidence_error("HANDOFF_SUCCESSOR_ID_COLLISION")
    document = {**body, "handoff_id": handoff_id}
    data = canonical_json_bytes(document)

    validation = validate_handoff(first, document, effective_at=request.created_at)
    if not validation.ok:
        codes = ",".join(item.code for item in validation.diagnostics)
        raise _evidence_error("HANDOFF_SELF_VALIDATION_FAILED", codes)
    path = _publish(output_root, handoff_id, data)
    return HandoffReceipt(
        handoff_id=handoff_id,
        handoff_path=os.fspath(path),
        handoff_sha256=sha256_bytes(data),
        kit_id=first.kit_id,
        kit_zip_sha256=first.canonical_zip_sha256,
    )
