from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from collections import Counter
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_json_bytes, sha256_bytes
from .errors import InfrastructureError, SourceError
from .manifests import ManifestSet
from .model import (
    BuildKitReceipt,
    Component,
    Diagnostic,
    GeneratedSourceSet,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    ResolvedSourceSet,
    SnapshotMode,
    SourceMember,
    ValidationReport,
    VerificationReport,
)
from .policy import validate_catalog
from .portable_paths import portable_key, validate_portable_paths


_IMMUTABLE_STATUS = {
    "target_build_required": True,
    "catvba_artifacts": [],
    "compile_status": "not-run",
    "release_eligible": False,
}
_REQUIRED_FILES = {
    "catalog.json",
    "kit-manifest.json",
    "receipts/hashes.json",
    "receipts/source-resolution.json",
    "target-test-plan/target-test-plan.json",
    "evidence-templates/target-verification.json",
    "SHA256SUMS",
    "KIT_COMPLETE",
}
_JSON_FILES = {
    "catalog.json",
    "kit-manifest.json",
    "receipts/hashes.json",
    "receipts/source-resolution.json",
    "target-test-plan/target-test-plan.json",
    "evidence-templates/target-verification.json",
}
_HASH_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")
_SIDECAR_LINE = re.compile(r"^([0-9a-f]{64})  ([^/\\]+\.zip)\n$")
_MEMBER_ROLE_ORDER = {"frm": 0, "frx": 1, "source": 2}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_safe(item) for item in value), key=repr)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _diagnostic_record(diagnostic: Diagnostic) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "path": diagnostic.path,
    }
    if diagnostic.details:
        record["details"] = _json_safe(diagnostic.details)
    return record


def _diagnostic_key(diagnostic: Diagnostic) -> bytes:
    return canonical_json_bytes(_diagnostic_record(diagnostic))


def _stable_diagnostics(
    groups: Iterable[Iterable[Diagnostic]],
) -> tuple[Diagnostic, ...]:
    unique: dict[bytes, Diagnostic] = {}
    for group in groups:
        for diagnostic in group:
            unique.setdefault(_diagnostic_key(diagnostic), diagnostic)
    return tuple(unique[key] for key in sorted(unique))


def _member_sort_key(member: SourceMember) -> tuple[Any, ...]:
    return (
        _MEMBER_ROLE_ORDER.get(member.role, 99),
        unicodedata.normalize("NFC", member.path),
        member.raw_sha256,
        member.blob_oid or "",
    )


def _component_sort_key(component: Component) -> tuple[Any, ...]:
    return (
        component.package_id or "",
        component.source_id,
        component.vb_name,
        component.component_type,
        component.origin.value,
        tuple(_member_sort_key(member) for member in component.members),
    )


def _record_sort_key(record: dict[str, Any], id_field: str) -> tuple[str, bytes]:
    value = record.get(id_field)
    return (
        value if isinstance(value, str) else "",
        canonical_json_bytes(_json_safe(record)),
    )


def assemble_catalog(
    snapshot: InputSnapshot,
    resolved: ResolvedSourceSet,
    generated: GeneratedSourceSet,
    manifests: ManifestSet,
) -> ResolvedCatalog:
    """Combine candidate and generated sources and run static policy.

    Quarantine is deliberately not part of the catalog identity or its byte
    graph.  The returned report is deterministic and carries every upstream
    validation result before adding combined-catalog policy findings.
    """
    diagnostics: list[Diagnostic] = list(
        _stable_diagnostics(
            (
                manifests.report.diagnostics,
                resolved.report.diagnostics,
                generated.report.diagnostics,
            )
        )
    )
    if snapshot.manifest_digest != manifests.digest:
        diagnostics.append(
            Diagnostic(
                code="MANIFEST_DIGEST_MISMATCH",
                path="config",
                message="snapshot manifest digest does not match loaded manifests",
                details={
                    "actual": snapshot.manifest_digest,
                    "expected": manifests.digest,
                },
            )
        )

    candidates = tuple(
        sorted(
            (
                component
                for component in (*resolved.components, *generated.components)
                if component.disposition == "candidate"
                and component.origin is not Origin.QUARANTINE
            ),
            key=_component_sort_key,
        )
    )
    package_values = manifests.packages.get("packages", [])
    tool_values = manifests.tools.get("tools", [])
    packages = tuple(
        sorted(
            (record for record in package_values if isinstance(record, dict)),
            key=lambda record: _record_sort_key(record, "package_id"),
        )
        if isinstance(package_values, list)
        else ()
    )
    tools = tuple(
        sorted(
            (record for record in tool_values if isinstance(record, dict)),
            key=lambda record: _record_sort_key(record, "tool_id"),
        )
        if isinstance(tool_values, list)
        else ()
    )
    catalog = ResolvedCatalog(
        snapshot=snapshot,
        components=candidates,
        packages=packages,
        tools=tools,
        report=ValidationReport(
            _stable_diagnostics((diagnostics,))
        ),
    )
    return ResolvedCatalog(
        snapshot=catalog.snapshot,
        components=catalog.components,
        packages=catalog.packages,
        tools=catalog.tools,
        report=validate_catalog(catalog),
    )


def _snapshot_record(snapshot: InputSnapshot) -> dict[str, Any]:
    return {
        "mode": snapshot.mode.value,
        "upstream_repository": snapshot.upstream_repository,
        "upstream_ref": snapshot.upstream_ref,
        "upstream_commit": snapshot.upstream_commit,
        "fork_repository": snapshot.fork_repository,
        "fork_dev_commit": snapshot.fork_dev_commit,
        "work_repository": snapshot.work_repository,
        "work_branch": snapshot.work_branch,
        "work_commit": snapshot.work_commit,
        "work_tree": snapshot.work_tree,
        "manifest_digest": snapshot.manifest_digest,
        "tool_version": snapshot.tool_version,
        "formal_eligible": snapshot.formal_eligible,
    }


def _member_record(member: SourceMember) -> dict[str, Any]:
    return {
        "path": unicodedata.normalize("NFC", member.path.replace("\\", "/")),
        "blob_oid": member.blob_oid,
        "raw_sha256": member.raw_sha256,
        "role": member.role,
    }


def _component_record(component: Component) -> dict[str, Any]:
    return {
        "source_id": component.source_id,
        "origin": component.origin.value,
        "component_type": component.component_type,
        "vb_name": component.vb_name,
        "package_id": component.package_id,
        "disposition": component.disposition,
        "members": [
            _member_record(member)
            for member in sorted(component.members, key=_member_sort_key)
        ],
    }


def _identity_payload(catalog: ResolvedCatalog) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": _snapshot_record(catalog.snapshot),
        "components": [
            _component_record(component)
            for component in sorted(catalog.components, key=_component_sort_key)
        ],
        "packages": [
            _json_safe(record)
            for record in sorted(
                catalog.packages,
                key=lambda record: _record_sort_key(record, "package_id"),
            )
        ],
        "tools": [
            _json_safe(record)
            for record in sorted(
                catalog.tools,
                key=lambda record: _record_sort_key(record, "tool_id"),
            )
        ],
        "policy_evidence": {
            "compile_status": "not-run",
            "diagnostics": [
                _diagnostic_record(diagnostic)
                for diagnostic in sorted(
                    catalog.report.diagnostics, key=_diagnostic_key
                )
            ],
        },
    }


def _is_catvba_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(
        segment.casefold().endswith(".catvba")
        for segment in normalized.split("/")
    )


def _source_error(code: str, detail: str = "") -> SourceError:
    return SourceError(f"{code}: {detail}" if detail else code)


def _infrastructure_error(
    code: str, detail: str = "", *, cause: BaseException | None = None
) -> InfrastructureError:
    error = InfrastructureError(f"{code}: {detail}" if detail else code)
    if cause is not None:
        error.__cause__ = cause
    return error


def _package_ids(catalog: ResolvedCatalog) -> tuple[str, ...]:
    return tuple(sorted(
        record["package_id"]
        for record in catalog.packages
        if isinstance(record.get("package_id"), str)
    ))


def _output_member_path(component: Component, member: SourceMember) -> str:
    assert component.package_id is not None
    source_name = PurePosixPath(member.path.replace("\\", "/")).name
    return f"packages/{component.package_id}/source/{source_name}"


def _preflight(catalog: ResolvedCatalog) -> tuple[dict[str, Any], bytes, str]:
    if catalog.snapshot.mode is not SnapshotMode.CANDIDATE:
        raise _source_error("SNAPSHOT_NOT_CANDIDATE")
    if not catalog.snapshot.formal_eligible:
        raise _source_error("SNAPSHOT_NOT_FORMAL")
    if catalog.report.diagnostics:
        raise _source_error(
            "CATALOG_DIAGNOSTICS",
            ",".join(item.code for item in catalog.report.diagnostics),
        )
    if not catalog.components:
        raise _source_error("NO_BUILDABLE_COMPONENTS")

    package_ids = _package_ids(catalog)
    if len(package_ids) != len(set(package_ids)):
        raise _source_error("DUPLICATE_PACKAGE_ID")

    member_paths: list[str] = []
    output_paths: list[str] = []
    for component in catalog.components:
        if (
            component.disposition != "candidate"
            or component.origin is Origin.QUARANTINE
        ):
            raise _source_error("NON_CANDIDATE_COMPONENT", component.source_id)
        if component.package_id not in package_ids:
            raise _source_error("PACKAGE_BINDING_INVALID", component.source_id)
        if not component.members:
            raise _source_error("EMPTY_COMPONENT", component.source_id)
        for member in component.members:
            if sha256_bytes(member.data) != member.raw_sha256:
                raise _source_error("SOURCE_HASH_MISMATCH", member.path)
            if _is_catvba_path(member.path):
                raise _source_error("CATVBA_FORBIDDEN", member.path)
            member_paths.append(member.path)
            output_paths.append(_output_member_path(component, member))

    path_report = validate_portable_paths((*package_ids, *member_paths))
    if path_report.diagnostics:
        finding = path_report.diagnostics[0]
        raise _source_error(finding.code, finding.path)
    output_report = validate_portable_paths(output_paths)
    if output_report.diagnostics:
        finding = output_report.diagnostics[0]
        raise _source_error(finding.code, finding.path)
    if any(_is_catvba_path(path) for path in output_paths):
        raise _source_error("CATVBA_FORBIDDEN")

    identity = _identity_payload(catalog)
    catalog_bytes = canonical_json_bytes(identity)
    kit_id = "kit-" + sha256_bytes(catalog_bytes)[:20]
    return identity, catalog_bytes, kit_id


def _package_record(
    catalog: ResolvedCatalog, package_id: str
) -> dict[str, Any]:
    return next(
        record for record in catalog.packages if record.get("package_id") == package_id
    )


def _layout(
    catalog: ResolvedCatalog,
    identity: dict[str, Any],
    catalog_bytes: bytes,
    kit_id: str,
) -> tuple[dict[str, bytes], tuple[str, ...], str]:
    files: dict[str, bytes] = {"catalog.json": catalog_bytes}
    package_ids = _package_ids(catalog)
    directories = {
        "receipts",
        "target-test-plan",
        "evidence-templates",
        "import-order",
        "references",
    }
    staged_members: list[dict[str, Any]] = []

    for package_id in package_ids:
        directories.add(f"packages/{package_id}/source")
        package_components = tuple(
            component
            for component in sorted(catalog.components, key=_component_sort_key)
            if component.package_id == package_id
        )
        import_names: list[str] = []
        for component in package_components:
            for member in sorted(component.members, key=_member_sort_key):
                staged_path = _output_member_path(component, member)
                files[staged_path] = member.data
                import_name = PurePosixPath(staged_path).name
                import_names.append(import_name)
                staged_members.append(
                    {
                        "source_id": component.source_id,
                        "source_path": _member_record(member)["path"],
                        "staged_path": staged_path,
                        "raw_sha256": member.raw_sha256,
                        "role": member.role,
                    }
                )
        files[f"import-order/{package_id}.txt"] = (
            "".join(f"{name}\n" for name in import_names).encode("utf-8")
        )
        package = _package_record(catalog, package_id)
        files[f"references/{package_id}.json"] = canonical_json_bytes(
            {
                "schema_version": 1,
                "package_id": package_id,
                "reference_allowlist": _json_safe(
                    package.get("reference_allowlist", [])
                ),
                "compile_status": "not-run",
            }
        )

    resolution = {
        "schema_version": 1,
        "kit_id": kit_id,
        "quarantine_included": False,
        "components": identity["components"],
    }
    files["receipts/source-resolution.json"] = canonical_json_bytes(resolution)
    files["receipts/hashes.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "members": sorted(
                staged_members,
                key=lambda record: (
                    record["staged_path"],
                    record["source_id"],
                    record["role"],
                ),
            ),
        }
    )
    files["target-test-plan/target-test-plan.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "target": "CATIA R2018/VBA7 64",
            "license_requirements": {
                "baseline_any_of": ["AB3", "HD2", "MD2"],
                "additional_required": ["SPA", "FTA"],
                "verification_status": "not-run",
            },
            **_IMMUTABLE_STATUS,
        }
    )
    files["evidence-templates/target-verification.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "kit_id": kit_id,
            "references": [],
            "runtime_checks": [],
            "license_evidence": [],
            **_IMMUTABLE_STATUS,
        }
    )
    manifest = {
        "schema_version": 1,
        "kit_id": kit_id,
        "identity_sha256": sha256_bytes(catalog_bytes),
        "manifest_digest": catalog.snapshot.manifest_digest,
        **_IMMUTABLE_STATUS,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    files["kit-manifest.json"] = manifest_bytes
    return files, tuple(sorted(directories)), sha256_bytes(manifest_bytes)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _assert_contained(root: Path, path: Path) -> None:
    root_text = os.fspath(_absolute(root))
    path_text = os.fspath(_absolute(path))
    try:
        common = os.path.commonpath((root_text, path_text))
    except ValueError as error:
        raise _infrastructure_error(
            "PATH_CONTAINMENT_FAILED", path_text, cause=error
        )
    if common != root_text:
        raise _infrastructure_error("PATH_CONTAINMENT_FAILED", path_text)


def _reject_existing_symlinks(path: Path) -> None:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            status = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise _infrastructure_error(
                "OUTPUT_PATH_INSPECTION_FAILED", os.fspath(current), cause=error
            )
        if stat.S_ISLNK(status.st_mode):
            raise _infrastructure_error("OUTPUT_SYMLINK_FORBIDDEN", os.fspath(current))


def _prepare_output_root(output_root: Path) -> Path:
    root = _absolute(output_root)
    _reject_existing_symlinks(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _infrastructure_error(
            "OUTPUT_ROOT_CREATE_FAILED", os.fspath(root), cause=error
        )
    _reject_existing_symlinks(root)
    if not root.is_dir():
        raise _infrastructure_error("OUTPUT_ROOT_NOT_DIRECTORY", os.fspath(root))
    locks = root / ".locks"
    _assert_contained(root, locks)
    try:
        locks.mkdir(mode=0o700, exist_ok=True)
    except OSError as error:
        raise _infrastructure_error("LOCK_DIRECTORY_FAILED", cause=error)
    if locks.is_symlink() or not locks.is_dir():
        raise _infrastructure_error("LOCK_DIRECTORY_UNSAFE")
    return root


def _acquire_lock(root: Path, kit_id: str) -> tuple[Path, int, os.stat_result]:
    path = root / ".locks" / f"{kit_id}.lock"
    _assert_contained(root, path)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise _infrastructure_error("KIT_LOCK_EXISTS", kit_id, cause=error)
    except OSError as error:
        raise _infrastructure_error("KIT_LOCK_FAILED", kit_id, cause=error)
    try:
        os.write(descriptor, f"{kit_id}\n".encode("ascii"))
        os.fsync(descriptor)
        status = os.fstat(descriptor)
    except OSError as error:
        os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise _infrastructure_error("KIT_LOCK_FAILED", kit_id, cause=error)
    return path, descriptor, status


def _release_own_lock(
    path: Path, descriptor: int, acquired_status: os.stat_result
) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass
    try:
        current = path.lstat()
    except OSError:
        return
    if (
        current.st_dev == acquired_status.st_dev
        and current.st_ino == acquired_status.st_ino
        and stat.S_ISREG(current.st_mode)
    ):
        try:
            path.unlink()
        except OSError:
            pass


def _write_file(path: Path, data: bytes) -> None:
    """Create one regular file without following a final-component symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir_layout(root: Path, directories: Sequence[str]) -> None:
    for relative in directories:
        target = root / relative
        _assert_contained(root, target)
        target.mkdir(parents=True, exist_ok=False)


def _write_layout(root: Path, files: Mapping[str, bytes]) -> None:
    for relative in sorted(files):
        target = root / relative
        _assert_contained(root, target)
        _write_file(target, files[relative])


def _regular_files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in tuple(directory_names):
            path = base / name
            if path.is_symlink():
                raise _infrastructure_error("SYMLINK_ENTRY", os.fspath(path))
        for name in file_names:
            path = base / name
            status = path.lstat()
            if not stat.S_ISREG(status.st_mode):
                raise _infrastructure_error("NON_REGULAR_ENTRY", os.fspath(path))
            relative = unicodedata.normalize(
                "NFC", path.relative_to(root).as_posix()
            )
            if relative != path.relative_to(root).as_posix():
                raise _infrastructure_error("PATH_NOT_NFC", relative)
            result[relative] = path.read_bytes()
    return dict(sorted(result.items()))


def _sha256sums(files: Mapping[str, bytes]) -> bytes:
    names = sorted(
        name for name in files if name not in {"SHA256SUMS", "KIT_COMPLETE"}
    )
    return "".join(
        f"{sha256_bytes(files[name])}  {name}\n" for name in names
    ).encode("ascii")


def _assert_sums(files: Mapping[str, bytes], sums: bytes) -> None:
    expected = _sha256sums(files)
    if sums != expected:
        raise _infrastructure_error("HASH_RECEIPT_SELF_CHECK_FAILED")


def _completion_marker(kit_id: str, sums: bytes) -> bytes:
    return canonical_json_bytes(
        {
            "complete": True,
            "kit_id": kit_id,
            "sha256sums_sha256": sha256_bytes(sums),
        }
    )


def _zip_bytes(files: Mapping[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(
        stream, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as archive:
        archive.comment = b""
        for name in sorted(files):
            normalized = unicodedata.normalize("NFC", name)
            if normalized != name:
                raise _infrastructure_error("PATH_NOT_NFC", name)
            info = zipfile.ZipInfo(normalized, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.extra = b""
            info.comment = b""
            archive.writestr(info, files[name])
    return stream.getvalue()


def _same_directory(expected_root: Path, actual_root: Path) -> bool:
    try:
        if actual_root.is_symlink() or not actual_root.is_dir():
            return False
        report = verify_build_kit(actual_root)
        return report.ok and _regular_files(expected_root) == _regular_files(actual_root)
    except (OSError, InfrastructureError):
        return False


def _safe_remove_tree(path: Path) -> None:
    try:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        pass


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def stage_build_kit(
    catalog: ResolvedCatalog, output_root: str | os.PathLike[str]
) -> BuildKitReceipt:
    """Stage, self-verify, archive, and atomically publish an offline kit."""
    identity, catalog_bytes, kit_id = _preflight(catalog)
    layout, directories, manifest_sha256 = _layout(
        catalog, identity, catalog_bytes, kit_id
    )

    root = _prepare_output_root(Path(output_root))
    lock_path, lock_descriptor, lock_status = _acquire_lock(root, kit_id)
    temp_dir: Path | None = None
    temp_zip: Path | None = None
    temp_sidecar: Path | None = None
    published: list[Path] = []
    final_dir = root / kit_id
    zip_path = root / f"{kit_id}.zip"
    sidecar_path = root / f"{kit_id}.zip.sha256"
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{kit_id}.tmp-", dir=root))
        _assert_contained(root, temp_dir)
        _mkdir_layout(temp_dir, directories)
        _write_layout(temp_dir, layout)

        staged = _regular_files(temp_dir)
        sums = _sha256sums(staged)
        _write_file(temp_dir / "SHA256SUMS", sums)
        staged = _regular_files(temp_dir)
        _assert_sums(staged, sums)
        _write_file(temp_dir / "KIT_COMPLETE", _completion_marker(kit_id, sums))
        staged = _regular_files(temp_dir)
        report = _verify_file_map(staged)
        if report:
            raise _infrastructure_error(
                "KIT_SELF_VERIFICATION_FAILED",
                ",".join(item.code for item in report),
            )

        archive_bytes = _zip_bytes(staged)
        archive_sha256 = sha256_bytes(archive_bytes)
        sidecar_bytes = (
            f"{archive_sha256}  {kit_id}.zip\n".encode("ascii")
        )
        token = uuid.uuid4().hex
        temp_zip = root / f".{kit_id}.tmp-{token}.zip"
        temp_sidecar = root / f".{kit_id}.tmp-{token}.zip.sha256"
        _write_file(temp_zip, archive_bytes)
        _write_file(temp_sidecar, sidecar_bytes)

        if final_dir.exists() or final_dir.is_symlink():
            if (
                not _same_directory(temp_dir, final_dir)
                or not zip_path.is_file()
                or zip_path.is_symlink()
                or zip_path.read_bytes() != archive_bytes
                or not sidecar_path.is_file()
                or sidecar_path.is_symlink()
                or sidecar_path.read_bytes() != sidecar_bytes
            ):
                raise _infrastructure_error("KIT_ID_CONTENT_MISMATCH", kit_id)
            _safe_remove_tree(temp_dir)
            temp_dir = None
            _safe_unlink(temp_zip)
            temp_zip = None
            _safe_unlink(temp_sidecar)
            temp_sidecar = None
        else:
            if zip_path.exists() or sidecar_path.exists():
                raise _infrastructure_error("KIT_OUTPUT_COLLISION", kit_id)
            os.replace(temp_zip, zip_path)
            temp_zip = None
            published.append(zip_path)
            os.replace(temp_sidecar, sidecar_path)
            temp_sidecar = None
            published.append(sidecar_path)
            os.replace(temp_dir, final_dir)
            temp_dir = None
            published.append(final_dir)

        return BuildKitReceipt(
            kit_id=kit_id,
            kit_dir=os.fspath(final_dir),
            zip_path=os.fspath(zip_path),
            zip_sha256=archive_sha256,
            manifest_sha256=manifest_sha256,
        )
    except (SourceError, InfrastructureError):
        for path in reversed(published):
            if path.is_dir() and not path.is_symlink():
                _safe_remove_tree(path)
            else:
                _safe_unlink(path)
        raise
    except Exception as error:
        for path in reversed(published):
            if path.is_dir() and not path.is_symlink():
                _safe_remove_tree(path)
            else:
                _safe_unlink(path)
        raise _infrastructure_error(
            "KIT_STAGE_FAILED", type(error).__name__, cause=error
        )
    finally:
        if temp_dir is not None:
            _safe_remove_tree(temp_dir)
        if temp_zip is not None:
            _safe_unlink(temp_zip)
        if temp_sidecar is not None:
            _safe_unlink(temp_sidecar)
        _release_own_lock(lock_path, lock_descriptor, lock_status)


def _verification_diagnostic(
    code: str, path: str, message: str, **details: Any
) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message, details=details)


def _path_diagnostics(name: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if "\\" in name:
        diagnostics.append(
            _verification_diagnostic(
                "PATH_BACKSLASH", name, "archive paths must use POSIX separators"
            )
        )
    if unicodedata.normalize("NFC", name) != name:
        diagnostics.append(
            _verification_diagnostic(
                "PATH_NOT_NFC", name, "entry path is not NFC normalized"
            )
        )
    try:
        portable_key(name)
    except SourceError as error:
        code = str(error).split(":", 1)[0]
        diagnostics.append(
            _verification_diagnostic(code, name, "entry path is not portable")
        )
    if _is_catvba_path(name):
        diagnostics.append(
            _verification_diagnostic(
                "CATVBA_FORBIDDEN", name, "Build Kit cannot contain CATVBA artifacts"
            )
        )
    return diagnostics


def _parse_canonical_json(
    files: Mapping[str, bytes], name: str, diagnostics: list[Diagnostic]
) -> Any | None:
    data = files.get(name)
    if data is None:
        return None
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as error:
        diagnostics.append(
            _verification_diagnostic(
                "JSON_MALFORMED", name, f"canonical JSON cannot be parsed: {type(error).__name__}"
            )
        )
        return None
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        diagnostics.append(
            _verification_diagnostic(
                "JSON_MALFORMED", name, f"canonical JSON is invalid: {type(error).__name__}"
            )
        )
        return None
    if canonical != data:
        diagnostics.append(
            _verification_diagnostic(
                "JSON_NOT_CANONICAL", name, "JSON bytes are not canonical"
            )
        )
    return value


def _verify_hash_manifest(
    files: Mapping[str, bytes], diagnostics: list[Diagnostic]
) -> None:
    data = files.get("SHA256SUMS")
    if data is None:
        return
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        diagnostics.append(
            _verification_diagnostic(
                "HASH_MANIFEST_MALFORMED", "SHA256SUMS", "hash manifest is not ASCII"
            )
        )
        return
    if "\r" in text or (text and not text.endswith("\n")):
        diagnostics.append(
            _verification_diagnostic(
                "HASH_MANIFEST_MALFORMED",
                "SHA256SUMS",
                "hash manifest requires stable LF lines",
            )
        )
    records: dict[str, str] = {}
    malformed = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _HASH_LINE.fullmatch(line)
        if match is None:
            malformed = True
            diagnostics.append(
                _verification_diagnostic(
                    "HASH_MANIFEST_MALFORMED",
                    "SHA256SUMS",
                    "hash line is malformed",
                    line=line_number,
                )
            )
            continue
        digest, name = match.groups()
        diagnostics.extend(_path_diagnostics(name))
        if name in records:
            diagnostics.append(
                _verification_diagnostic(
                    "DUPLICATE_HASH_ENTRY", name, "hash manifest path is duplicated"
                )
            )
            continue
        records[name] = digest

    expected_names = set(files) - {"SHA256SUMS", "KIT_COMPLETE"}
    for name in sorted(expected_names - set(records)):
        diagnostics.append(
            _verification_diagnostic(
                "EXTRA_FILE", name, "file is not declared by SHA256SUMS"
            )
        )
    for name in sorted(set(records) - expected_names):
        diagnostics.append(
            _verification_diagnostic(
                "MISSING_FILE", name, "SHA256SUMS declares a missing file"
            )
        )
    for name in sorted(expected_names & set(records)):
        actual = sha256_bytes(files[name])
        if records[name] != actual:
            diagnostics.append(
                _verification_diagnostic(
                    "HASH_MISMATCH",
                    name,
                    "file hash does not match SHA256SUMS",
                    actual=actual,
                    expected=records[name],
                )
            )
    if not malformed and list(records) != sorted(records):
        diagnostics.append(
            _verification_diagnostic(
                "HASH_ORDER_INVALID", "SHA256SUMS", "hash paths are not sorted"
            )
        )


def _verify_hash_receipt(
    files: Mapping[str, bytes], value: Any, diagnostics: list[Diagnostic]
) -> None:
    if not isinstance(value, dict) or value.get("algorithm") != "sha256":
        diagnostics.append(
            _verification_diagnostic(
                "HASH_RECEIPT_MALFORMED",
                "receipts/hashes.json",
                "member hash receipt is malformed",
            )
        )
        return
    members = value.get("members")
    if not isinstance(members, list):
        diagnostics.append(
            _verification_diagnostic(
                "HASH_RECEIPT_MALFORMED",
                "receipts/hashes.json",
                "member list is missing",
            )
        )
        return
    seen: set[str] = set()
    for index, record in enumerate(members):
        if not isinstance(record, dict):
            diagnostics.append(
                _verification_diagnostic(
                    "HASH_RECEIPT_MALFORMED",
                    f"receipts/hashes.json#/members/{index}",
                    "member receipt is not an object",
                )
            )
            continue
        path = record.get("staged_path")
        digest = record.get("raw_sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            diagnostics.append(
                _verification_diagnostic(
                    "HASH_RECEIPT_MALFORMED",
                    f"receipts/hashes.json#/members/{index}",
                    "member receipt requires staged_path and raw_sha256",
                )
            )
            continue
        if path in seen:
            diagnostics.append(
                _verification_diagnostic(
                    "DUPLICATE_HASH_ENTRY", path, "member receipt path is duplicated"
                )
            )
        seen.add(path)
        data = files.get(path)
        if data is None:
            diagnostics.append(
                _verification_diagnostic(
                    "MISSING_FILE", path, "member receipt declares a missing source"
                )
            )
        elif sha256_bytes(data) != digest:
            diagnostics.append(
                _verification_diagnostic(
                    "HASH_MISMATCH", path, "source differs from member hash receipt"
                )
            )


def _expected_catalog_graph(
    catalog: dict[str, Any], expected_id: str, diagnostics: list[Diagnostic]
) -> tuple[dict[str, bytes | None], set[str]] | None:
    packages = catalog.get("packages")
    components = catalog.get("components")
    snapshot = catalog.get("snapshot")
    if (
        catalog.get("schema_version") != 1
        or not isinstance(packages, list)
        or not isinstance(components, list)
        or not isinstance(snapshot, dict)
    ):
        diagnostics.append(
            _verification_diagnostic(
                "CATALOG_MALFORMED",
                "catalog.json",
                "catalog identity has an invalid top-level shape",
            )
        )
        return None

    package_records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(packages):
        if not isinstance(record, dict) or not isinstance(
            record.get("package_id"), str
        ):
            diagnostics.append(
                _verification_diagnostic(
                    "CATALOG_MALFORMED",
                    f"catalog.json#/packages/{index}",
                    "catalog package is malformed",
                )
            )
            continue
        package_id = record["package_id"]
        if package_id in package_records:
            diagnostics.append(
                _verification_diagnostic(
                    "CATALOG_MALFORMED",
                    f"catalog.json#/packages/{index}/package_id",
                    "catalog package ID is duplicated",
                )
            )
        package_records[package_id] = record
    if not package_records:
        diagnostics.append(
            _verification_diagnostic(
                "CATALOG_MALFORMED",
                "catalog.json#/packages",
                "catalog has no packages",
            )
        )
        return None

    expected: dict[str, bytes | None] = {
        "catalog.json": canonical_json_bytes(catalog),
        "SHA256SUMS": None,
        "KIT_COMPLETE": None,
    }
    expected_directories = {
        "receipts",
        "target-test-plan",
        "evidence-templates",
        "import-order",
        "references",
        "packages",
    }
    staged_members: list[dict[str, Any]] = []
    import_names: dict[str, list[str]] = {
        package_id: [] for package_id in package_records
    }
    source_hashes: dict[str, str] = {}
    for component_index, component in enumerate(components):
        if not isinstance(component, dict):
            diagnostics.append(
                _verification_diagnostic(
                    "CATALOG_MALFORMED",
                    f"catalog.json#/components/{component_index}",
                    "catalog component is not an object",
                )
            )
            continue
        source_id = component.get("source_id")
        package_id = component.get("package_id")
        members = component.get("members")
        if (
            component.get("disposition") != "candidate"
            or component.get("origin") == "quarantine"
            or not isinstance(source_id, str)
            or package_id not in package_records
            or not isinstance(members, list)
            or not members
        ):
            diagnostics.append(
                _verification_diagnostic(
                    "CATALOG_MALFORMED",
                    f"catalog.json#/components/{component_index}",
                    "catalog component identity is invalid",
                )
            )
            continue
        assert isinstance(package_id, str)
        for member_index, member in enumerate(members):
            if not isinstance(member, dict):
                diagnostics.append(
                    _verification_diagnostic(
                        "CATALOG_MALFORMED",
                        f"catalog.json#/components/{component_index}/members/{member_index}",
                        "catalog member is not an object",
                    )
                )
                continue
            source_path = member.get("path")
            raw_sha256 = member.get("raw_sha256")
            role = member.get("role")
            if (
                not isinstance(source_path, str)
                or not isinstance(raw_sha256, str)
                or _HASH_LINE.fullmatch(f"{raw_sha256}  x") is None
                or not isinstance(role, str)
            ):
                diagnostics.append(
                    _verification_diagnostic(
                        "CATALOG_MALFORMED",
                        f"catalog.json#/components/{component_index}/members/{member_index}",
                        "catalog member identity is malformed",
                    )
                )
                continue
            name = PurePosixPath(source_path.replace("\\", "/")).name
            staged_path = f"packages/{package_id}/source/{name}"
            if staged_path in source_hashes:
                diagnostics.append(
                    _verification_diagnostic(
                        "CATALOG_MALFORMED",
                        staged_path,
                        "catalog source output path is duplicated",
                    )
                )
                continue
            source_hashes[staged_path] = raw_sha256
            expected[staged_path] = None
            import_names[package_id].append(name)
            staged_members.append(
                {
                    "source_id": source_id,
                    "source_path": source_path,
                    "staged_path": staged_path,
                    "raw_sha256": raw_sha256,
                    "role": role,
                }
            )

    for package_id, package in sorted(package_records.items()):
        expected_directories.update(
            {
                f"packages/{package_id}",
                f"packages/{package_id}/source",
            }
        )
        expected[f"import-order/{package_id}.txt"] = "".join(
            f"{name}\n" for name in import_names[package_id]
        ).encode("utf-8")
        expected[f"references/{package_id}.json"] = canonical_json_bytes(
            {
                "schema_version": 1,
                "package_id": package_id,
                "reference_allowlist": _json_safe(
                    package.get("reference_allowlist", [])
                ),
                "compile_status": "not-run",
            }
        )

    expected["receipts/source-resolution.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "kit_id": expected_id,
            "quarantine_included": False,
            "components": components,
        }
    )
    expected["receipts/hashes.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "members": sorted(
                staged_members,
                key=lambda record: (
                    record["staged_path"],
                    record["source_id"],
                    record["role"],
                ),
            ),
        }
    )
    expected["target-test-plan/target-test-plan.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "target": "CATIA R2018/VBA7 64",
            "license_requirements": {
                "baseline_any_of": ["AB3", "HD2", "MD2"],
                "additional_required": ["SPA", "FTA"],
                "verification_status": "not-run",
            },
            **_IMMUTABLE_STATUS,
        }
    )
    expected["evidence-templates/target-verification.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "kit_id": expected_id,
            "references": [],
            "runtime_checks": [],
            "license_evidence": [],
            **_IMMUTABLE_STATUS,
        }
    )
    manifest_digest = snapshot.get("manifest_digest")
    expected["kit-manifest.json"] = canonical_json_bytes(
        {
            "schema_version": 1,
            "kit_id": expected_id,
            "identity_sha256": sha256_bytes(canonical_json_bytes(catalog)),
            "manifest_digest": manifest_digest,
            **_IMMUTABLE_STATUS,
        }
    )
    for name in expected:
        parts = PurePosixPath(name).parts[:-1]
        for length in range(1, len(parts) + 1):
            expected_directories.add("/".join(parts[:length]))

    for name, digest in source_hashes.items():
        # Store the expected digest in a sentinel form which cannot be confused
        # with actual source bytes; comparison happens below.
        expected[name] = None
    return expected, expected_directories


def _verify_expected_graph(
    files: Mapping[str, bytes],
    catalog: dict[str, Any],
    expected_id: str,
    diagnostics: list[Diagnostic],
    directories: set[str] | None,
) -> None:
    graph = _expected_catalog_graph(catalog, expected_id, diagnostics)
    if graph is None:
        return
    expected, expected_directories = graph
    expected_names = set(expected)
    for name in sorted(expected_names - set(files)):
        diagnostics.append(
            _verification_diagnostic(
                "MISSING_FILE", name, "catalog requires a missing kit file"
            )
        )
    for name in sorted(set(files) - expected_names):
        diagnostics.append(
            _verification_diagnostic(
                "EXTRA_FILE", name, "file is not part of the catalog-derived layout"
            )
        )
    for name in sorted(expected_names & set(files)):
        expected_bytes = expected[name]
        if expected_bytes is not None and files[name] != expected_bytes:
            diagnostics.append(
                _verification_diagnostic(
                    "CATALOG_CONTENT_MISMATCH",
                    name,
                    "file content differs from the catalog-derived layout",
                )
            )

    components = catalog.get("components", [])
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            package_id = component.get("package_id")
            members = component.get("members")
            if not isinstance(package_id, str) or not isinstance(members, list):
                continue
            for member in members:
                if not isinstance(member, dict):
                    continue
                source_path = member.get("path")
                digest = member.get("raw_sha256")
                if not isinstance(source_path, str) or not isinstance(digest, str):
                    continue
                name = PurePosixPath(source_path.replace("\\", "/")).name
                staged_path = f"packages/{package_id}/source/{name}"
                data = files.get(staged_path)
                if data is not None and sha256_bytes(data) != digest:
                    diagnostics.append(
                        _verification_diagnostic(
                            "HASH_MISMATCH",
                            staged_path,
                            "source bytes differ from the canonical catalog hash",
                        )
                    )
    if directories is not None:
        for name in sorted(expected_directories - directories):
            diagnostics.append(
                _verification_diagnostic(
                    "MISSING_DIRECTORY", name, "required kit directory is missing"
                )
            )
        for name in sorted(directories - expected_directories):
            diagnostics.append(
                _verification_diagnostic(
                    "EXTRA_DIRECTORY", name, "directory is not part of the kit layout"
                )
            )


def _verify_file_map(
    files: Mapping[str, bytes], directories: set[str] | None = None
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    names = tuple(files)
    for name in names:
        diagnostics.extend(_path_diagnostics(name))
    portable_counts: Counter[str] = Counter()
    for name in names:
        try:
            portable_counts[portable_key(name)] += 1
        except SourceError:
            continue
    for key, count in sorted(portable_counts.items()):
        if count > 1:
            diagnostics.append(
                _verification_diagnostic(
                    "DUPLICATE_ENTRY", key, "entries collide by portable path"
                )
            )

    for name in sorted(_REQUIRED_FILES - set(files)):
        diagnostics.append(
            _verification_diagnostic("MISSING_FILE", name, "required kit file is missing")
        )
    _verify_hash_manifest(files, diagnostics)

    parsed: dict[str, Any] = {}
    for name in sorted(_JSON_FILES & set(files)):
        parsed[name] = _parse_canonical_json(files, name, diagnostics)
    catalog = parsed.get("catalog.json")
    manifest = parsed.get("kit-manifest.json")
    hashes = parsed.get("receipts/hashes.json")
    target_plan = parsed.get("target-test-plan/target-test-plan.json")
    evidence = parsed.get("evidence-templates/target-verification.json")
    if hashes is not None:
        _verify_hash_receipt(files, hashes, diagnostics)

    expected_id: str | None = None
    if isinstance(catalog, dict):
        expected_id = "kit-" + sha256_bytes(canonical_json_bytes(catalog))[:20]
        policy = catalog.get("policy_evidence")
        if not isinstance(policy, dict) or policy.get("compile_status") != "not-run":
            diagnostics.append(
                _verification_diagnostic(
                    "IMMUTABLE_STATUS_INVALID",
                    "catalog.json#/policy_evidence/compile_status",
                    "static policy compile status must remain not-run",
                )
            )
        _verify_expected_graph(
            files, catalog, expected_id, diagnostics, directories
        )
        if isinstance(policy, dict) and policy.get("diagnostics") != []:
            diagnostics.append(
                _verification_diagnostic(
                    "IMMUTABLE_STATUS_INVALID",
                    "catalog.json#/policy_evidence/diagnostics",
                    "published kit cannot contain policy diagnostics",
                )
            )
    if isinstance(manifest, dict):
        if expected_id is not None and manifest.get("kit_id") != expected_id:
            diagnostics.append(
                _verification_diagnostic(
                    "WRONG_KIT_ID",
                    "kit-manifest.json#/kit_id",
                    "kit ID does not match canonical catalog identity",
                )
            )
        for field, expected in _IMMUTABLE_STATUS.items():
            if manifest.get(field) != expected:
                diagnostics.append(
                    _verification_diagnostic(
                        "IMMUTABLE_STATUS_INVALID",
                        f"kit-manifest.json#/{field}",
                        "immutable target status was changed",
                    )
                )
        if isinstance(catalog, dict) and manifest.get("identity_sha256") != sha256_bytes(
            canonical_json_bytes(catalog)
        ):
            diagnostics.append(
                _verification_diagnostic(
                    "IDENTITY_HASH_MISMATCH",
                    "kit-manifest.json#/identity_sha256",
                    "identity hash does not match catalog",
                )
            )
    for name, value in (
        ("target-test-plan/target-test-plan.json", target_plan),
        ("evidence-templates/target-verification.json", evidence),
    ):
        if isinstance(value, dict):
            for field, expected in _IMMUTABLE_STATUS.items():
                if value.get(field) != expected:
                    diagnostics.append(
                        _verification_diagnostic(
                            "IMMUTABLE_STATUS_INVALID",
                            f"{name}#/{field}",
                            "immutable target status was changed",
                        )
                    )

    marker = _parse_canonical_json(files, "KIT_COMPLETE", diagnostics)
    if marker is None and "KIT_COMPLETE" in files:
        diagnostics.append(
            _verification_diagnostic(
                "KIT_COMPLETE_INVALID", "KIT_COMPLETE", "completion marker is invalid"
            )
        )
    elif isinstance(marker, dict):
        valid_marker = (
            marker.get("complete") is True
            and expected_id is not None
            and marker.get("kit_id") == expected_id
            and isinstance(files.get("SHA256SUMS"), bytes)
            and marker.get("sha256sums_sha256")
            == sha256_bytes(files["SHA256SUMS"])
        )
        if not valid_marker:
            diagnostics.append(
                _verification_diagnostic(
                    "KIT_COMPLETE_INVALID", "KIT_COMPLETE", "completion marker does not bind this kit"
                )
            )
    elif marker is not None:
        diagnostics.append(
            _verification_diagnostic(
                "KIT_COMPLETE_INVALID", "KIT_COMPLETE", "completion marker is not an object"
            )
        )

    return _stable_diagnostics((diagnostics,))


def _directory_file_map(
    path: Path,
) -> tuple[dict[str, bytes], list[Diagnostic], set[str]]:
    files: dict[str, bytes] = {}
    diagnostics: list[Diagnostic] = []
    directories: set[str] = set()
    if path.is_symlink():
        return (
            files,
            [
                _verification_diagnostic(
                    "SYMLINK_ENTRY", os.fspath(path), "kit directory cannot be a symlink"
                )
            ],
            directories,
        )
    if not path.is_dir():
        return (
            files,
            [
                _verification_diagnostic(
                    "KIT_PATH_INVALID", os.fspath(path), "kit path is not a directory or ZIP"
                )
            ],
            directories,
        )
    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        base = Path(directory)
        for name in tuple(directory_names):
            child = base / name
            relative = child.relative_to(path).as_posix()
            diagnostics.extend(_path_diagnostics(relative))
            if child.is_symlink():
                diagnostics.append(
                    _verification_diagnostic(
                        "SYMLINK_ENTRY", relative, "kit contains a symlink directory"
                    )
                )
                directory_names.remove(name)
            else:
                directories.add(relative)
        for name in file_names:
            child = base / name
            relative = child.relative_to(path).as_posix()
            diagnostics.extend(_path_diagnostics(relative))
            try:
                status = child.lstat()
                if stat.S_ISLNK(status.st_mode):
                    diagnostics.append(
                        _verification_diagnostic(
                            "SYMLINK_ENTRY", relative, "kit contains a symlink file"
                        )
                    )
                    continue
                if not stat.S_ISREG(status.st_mode):
                    diagnostics.append(
                        _verification_diagnostic(
                            "NON_REGULAR_ENTRY", relative, "kit entry is not a regular file"
                        )
                    )
                    continue
                files[relative] = child.read_bytes()
            except OSError as error:
                diagnostics.append(
                    _verification_diagnostic(
                        "KIT_READ_ERROR", relative, f"cannot read kit entry: {type(error).__name__}"
                    )
                )
    return files, diagnostics, directories


def _zip_file_map(
    path: Path,
) -> tuple[dict[str, bytes], list[Diagnostic], None]:
    files: dict[str, bytes] = {}
    diagnostics: list[Diagnostic] = []
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.comment:
                diagnostics.append(
                    _verification_diagnostic(
                        "ZIP_METADATA_INVALID", "<archive>", "ZIP comment must be empty"
                    )
                )
            infos = archive.infolist()
            counts = Counter(info.filename for info in infos)
            for name, count in sorted(counts.items()):
                if count > 1:
                    diagnostics.append(
                        _verification_diagnostic(
                            "DUPLICATE_ENTRY", name, "ZIP entry name is duplicated"
                        )
                    )
            for info in infos:
                name = info.filename
                diagnostics.extend(_path_diagnostics(name))
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    diagnostics.append(
                        _verification_diagnostic(
                            "SYMLINK_ENTRY", name, "ZIP contains a symlink entry"
                        )
                    )
                    continue
                if info.is_dir() or not stat.S_ISREG(mode):
                    diagnostics.append(
                        _verification_diagnostic(
                            "NON_REGULAR_ENTRY", name, "ZIP entries must be regular files"
                        )
                    )
                    continue
                if (
                    info.date_time != (1980, 1, 1, 0, 0, 0)
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.create_system != 3
                    or stat.S_IMODE(mode) != 0o644
                    or info.extra != b""
                    or info.comment != b""
                ):
                    diagnostics.append(
                        _verification_diagnostic(
                            "ZIP_METADATA_INVALID", name, "ZIP entry metadata is not deterministic"
                        )
                    )
                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                    diagnostics.append(
                        _verification_diagnostic(
                            "ZIP_READ_ERROR", name, f"cannot read ZIP entry: {type(error).__name__}"
                        )
                    )
                    continue
                files.setdefault(name, data)
    except (OSError, zipfile.BadZipFile) as error:
        diagnostics.append(
            _verification_diagnostic(
                "ZIP_INVALID", os.fspath(path), f"cannot open ZIP: {type(error).__name__}"
            )
        )
        return files, diagnostics, None

    sidecar = path.with_name(path.name + ".sha256")
    try:
        sidecar_data = sidecar.read_bytes()
    except OSError:
        diagnostics.append(
            _verification_diagnostic(
                "ZIP_SIDECAR_MISSING", sidecar.name, "ZIP SHA-256 sidecar is missing"
            )
        )
    else:
        try:
            text = sidecar_data.decode("ascii")
        except UnicodeDecodeError:
            text = ""
        match = _SIDECAR_LINE.fullmatch(text)
        if match is None or match.group(2) != path.name:
            diagnostics.append(
                _verification_diagnostic(
                    "ZIP_SIDECAR_INVALID", sidecar.name, "ZIP SHA-256 sidecar is malformed"
                )
            )
        else:
            try:
                actual = sha256_bytes(path.read_bytes())
            except OSError as error:
                diagnostics.append(
                    _verification_diagnostic(
                        "ZIP_READ_ERROR", path.name, f"cannot hash ZIP: {type(error).__name__}"
                    )
                )
            else:
                if match.group(1) != actual:
                    diagnostics.append(
                        _verification_diagnostic(
                            "ZIP_SIDECAR_MISMATCH", sidecar.name, "ZIP SHA-256 sidecar does not match"
                        )
                    )
    return files, diagnostics, None


def verify_build_kit(path: str | os.PathLike[str]) -> VerificationReport:
    """Verify a staged directory or deterministic ZIP without extracting it."""
    candidate = Path(path)
    if candidate.suffix.casefold() == ".zip" and not candidate.is_dir():
        files, diagnostics, directories = _zip_file_map(candidate)
    else:
        files, diagnostics, directories = _directory_file_map(candidate)
    diagnostics.extend(_verify_file_map(files, directories))
    stable = _stable_diagnostics((diagnostics,))
    return VerificationReport(ok=not stable, diagnostics=stable)
