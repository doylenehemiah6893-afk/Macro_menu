"""Deterministic, fail-closed B28 discovery operator bundle builder."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
import ctypes
import errno
import ast
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from jsonschema import Draft202012Validator

from .canonical import CanonicalJsonError, canonical_json_bytes, parse_canonical_json_bytes
from .errors import EvidenceError, InfrastructureError, VerificationError
from .git_objects import GitRepository
from .handoff import validate_handoff
from .kit import _directory_file_map, inspect_build_kit
from .model import BuildKitInspection
from .portable_paths import validate_portable_ascii_paths
from .resume import APPROVED_CUTOFF, validate_active_ledger
from .target_evidence.container import (
    MAX_EVIDENCE_FILE_BYTES,
    MAX_EVIDENCE_TOTAL_BYTES,
    _read_directory,
    _read_regular_path,
)
from .target_evidence.model import EvidencePhase
from catvba_refactor.target_collector.canonical import CollectorError
from catvba_refactor.target_collector.raw_validation import (
    validate_discovery_skeleton_files,
)


REPOSITORY = "doylenehemiah6893-afk/Macro_menu"
BRANCH = "codex/dev-review-report"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_TUTORIAL_NAMES = (
    "README_TARGET_B28.md",
    "QUICKSTART_B28.md",
    "SECURITY_AND_REDACTION.md",
    "TROUBLESHOOTING.md",
)
_RECORD = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_FORBIDDEN_SUFFIXES = frozenset((".catvba", ".bas", ".cls", ".frm", ".frx"))
_MAX_PYZ_BYTES = 64 * 1024 * 1024
_MAX_OUTPUT_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class _StableFile:
    data: bytes
    identity: tuple[int, int]


@dataclass(frozen=True)
class _StableTree:
    files: tuple[tuple[str, bytes], ...]
    directories: tuple[str, ...]
    directory_identities: tuple[tuple[int, int], ...]
    file_identities: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class OperatorBundleRequest:
    primary_build_root: Path
    comparison_build_root: Path
    handoff: Path
    active_ledger: Path
    issuance_revocation_snapshot: Path
    session_skeleton: Path
    output_root: Path
    repo_root: Path
    tutorials: Path
    run_script: Path
    generation_record_id: str
    test_record_id: str
    review_record_id: str


@dataclass(frozen=True)
class OperatorBundleReceipt:
    bundle_id: str
    bundle_dir: Path
    bundle_sha256: str
    provenance_sha256: str
    pyz_sha256: str
    kit_id: str
    handoff_id: str
    active_ledger_sha256: str
    active_ledger_captured_at: str
    active_ledger_source: str


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reparse(status: os.stat_result) -> bool:
    return bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _stable_file(path: Path, code: str) -> _StableFile:
    try:
        status = path.lstat()
        if (
            not stat.S_ISREG(status.st_mode)
            or stat.S_ISLNK(status.st_mode)
            or _reparse(status)
            or status.st_nlink != 1
            or status.st_size > MAX_EVIDENCE_FILE_BYTES
        ):
            raise OSError("not a regular file")
        data, _absolute = _read_regular_path(path)
        after = path.lstat()
        signature = (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns)
        if (
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != signature
            or len(data) != status.st_size
        ):
            raise OSError("file changed")
        return _StableFile(data, (status.st_dev, status.st_ino))
    except Exception as error:
        raise VerificationError(f"{code}: {path}") from error


def _capture_tree(root: Path, code: str) -> _StableTree:
    snapshot = _read_directory(root, phase=EvidencePhase.RAW, nesting_depth=0)
    if snapshot.diagnostics:
        raise VerificationError(f"{code}: {snapshot.diagnostics[0].code}")
    identities: list[tuple[int, int]] = []
    total = 0
    for relative, data in snapshot.files:
        path = root.joinpath(*relative.split("/"))
        status = path.lstat()
        if status.st_nlink != 1 or _reparse(status):
            raise VerificationError(f"{code}: unsafe identity")
        identities.append((status.st_dev, status.st_ino))
        total += len(data)
    if total > MAX_EVIDENCE_TOTAL_BYTES:
        raise VerificationError(f"{code}: total size")
    return _StableTree(
        snapshot.files, snapshot.directories,
        snapshot.directory_identities, tuple(identities),
    )


def _tree_identity_map(
    root: Path, code: str,
) -> tuple[dict[str, tuple[int, ...]], set[tuple[int, int]], set[tuple[int, int]]]:
    signatures: dict[str, tuple[int, ...]] = {}
    directory_ids: set[tuple[int, int]] = set()
    file_ids: set[tuple[int, int]] = set()
    total = 0
    for path in (root, *root.rglob("*")):
        relative = "." if path == root else path.relative_to(root).as_posix()
        status = path.lstat()
        if stat.S_ISLNK(status.st_mode) or _reparse(status):
            raise VerificationError(f"{code}: unsafe entry")
        if stat.S_ISDIR(status.st_mode):
            directory_ids.add((status.st_dev, status.st_ino))
        elif stat.S_ISREG(status.st_mode) and status.st_nlink == 1:
            file_ids.add((status.st_dev, status.st_ino))
            total += status.st_size
            if status.st_size > MAX_EVIDENCE_FILE_BYTES:
                raise VerificationError(f"{code}: file size")
        else:
            raise VerificationError(f"{code}: nonregular entry")
        signatures[relative] = (
            status.st_dev, status.st_ino, status.st_mode, status.st_nlink,
            status.st_size, status.st_mtime_ns, status.st_ctime_ns,
        )
        if len(signatures) > 1024:
            raise VerificationError(f"{code}: member limit")
        if relative != "." and len(Path(relative).parts) > 16:
            raise VerificationError(f"{code}: depth limit")
    if total > MAX_EVIDENCE_TOTAL_BYTES:
        raise VerificationError(f"{code}: total size")
    return signatures, directory_ids, file_ids


def _capture_kit_tree(root: Path, code: str) -> _StableTree:
    before, directory_ids, file_ids = _tree_identity_map(root, code)
    files, diagnostics, directories = _directory_file_map(root)
    after, after_directories, after_files = _tree_identity_map(root, code)
    if diagnostics or before != after or directory_ids != after_directories or file_ids != after_files:
        detail = diagnostics[0].code if diagnostics else "KIT_INPUT_CHANGED"
        raise VerificationError(f"{code}: {detail}")
    records = tuple(sorted(files.items(), key=lambda item: item[0].encode("ascii")))
    return _StableTree(
        records, tuple(sorted(directories)),
        tuple(sorted(directory_ids)), tuple(sorted(file_ids)),
    )


def _read(path: Path, code: str) -> bytes:
    return _stable_file(path, code).data


def _canonical_bytes(data: bytes, code: str) -> dict[str, Any]:
    try:
        value = parse_canonical_json_bytes(data)
    except CanonicalJsonError as error:
        raise VerificationError(code) from error
    if type(value) is not dict:
        raise VerificationError(code)
    return value


def _utc(value: object, code: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise VerificationError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise VerificationError(code) from error
    return parsed.astimezone(UTC)


def _trusted_now() -> datetime:
    return datetime.now(UTC)


def _chain_identity(path: Path) -> tuple[int, int]:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current /= part
            observed = current.lstat()
            if stat.S_ISLNK(observed.st_mode) or _reparse(observed):
                raise VerificationError("OPERATOR_BUNDLE_PATH_CHAIN_UNSAFE")
    except OSError as error:
        raise VerificationError("OPERATOR_BUNDLE_PATH_CHAIN_UNSAFE") from error
    return observed.st_dev, observed.st_ino


def _independent_roots(
    first: Path, second: Path,
) -> tuple[Path, Path]:
    try:
        first_identity = _chain_identity(first)
        second_identity = _chain_identity(second)
        first_resolved = first.resolve(strict=True)
        second_resolved = second.resolve(strict=True)
        if first_identity == second_identity or first_resolved.samefile(second_resolved):
            raise VerificationError("OPERATOR_BUNDLE_BUILD_ROOTS_NOT_INDEPENDENT")
        common = Path(os.path.commonpath((first_resolved, second_resolved)))
    except VerificationError:
        raise
    except (OSError, ValueError) as error:
        raise VerificationError("OPERATOR_BUNDLE_BUILD_ROOTS_NOT_INDEPENDENT") from error
    if common in {first_resolved, second_resolved}:
        raise VerificationError("OPERATOR_BUNDLE_BUILD_ROOTS_NOT_INDEPENDENT")
    return first_resolved, second_resolved


def _files(root: Path, *, code: str) -> tuple[tuple[str, bytes], ...]:
    records = _capture_tree(root, code).files
    if not records or not validate_portable_ascii_paths(path for path, _ in records).ok:
        raise VerificationError(code)
    return records


def _member_records(files: Iterable[tuple[str, bytes]]) -> list[dict[str, Any]]:
    return [
        {"path": path, "sha256": _sha(data), "size": len(data)}
        for path, data in files
    ]


def _tree_digest(files: Iterable[tuple[str, bytes]]) -> str:
    return _sha(canonical_json_bytes(_member_records(files)))


def _zip_bytes(files: Iterable[tuple[str, bytes]], *, shebang: bytes = b"") -> bytes:
    stream = io.BytesIO()
    stream.write(shebang)
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for path, data in files:
            info = zipfile.ZipInfo(path, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            info.flag_bits = 0x800
            archive.writestr(info, data)
    return stream.getvalue()


def _triplet(root: Path) -> tuple[Path, Path, Path]:
    try:
        entries = tuple(root.iterdir())
    except OSError as error:
        raise VerificationError("OPERATOR_BUNDLE_KIT_TRIPLET_INVALID") from error
    try:
        statuses = {path: path.lstat() for path in entries}
    except OSError as error:
        raise VerificationError("OPERATOR_BUNDLE_KIT_TRIPLET_INVALID") from error
    directories = [
        path
        for path in entries
        if stat.S_ISDIR(statuses[path].st_mode)
        and not stat.S_ISLNK(statuses[path].st_mode)
        and path.name.startswith("kit-")
    ]
    archives = [
        path
        for path in entries
        if stat.S_ISREG(statuses[path].st_mode)
        and not stat.S_ISLNK(statuses[path].st_mode)
        and path.name.startswith("kit-")
        and path.name.endswith(".zip")
    ]
    if len(directories) != 1 or len(archives) != 1:
        raise VerificationError("OPERATOR_BUNDLE_KIT_TRIPLET_INVALID")
    kit_id = directories[0].name
    if archives[0].name != f"{kit_id}.zip":
        raise VerificationError("OPERATOR_BUNDLE_KIT_TRIPLET_INVALID")
    sidecar = root / f"{kit_id}.zip.sha256"
    extras = [path for path in entries if path not in {*directories, *archives, sidecar}]
    try:
        sidecar_status = sidecar.lstat()
    except OSError as error:
        raise VerificationError("OPERATOR_BUNDLE_KIT_TRIPLET_INVALID") from error
    if (
        not stat.S_ISREG(sidecar_status.st_mode)
        or stat.S_ISLNK(sidecar_status.st_mode)
        or any(
            path.name != ".locks"
            or not stat.S_ISDIR(statuses[path].st_mode)
            or stat.S_ISLNK(statuses[path].st_mode)
            for path in extras
        )
    ):
        raise VerificationError("OPERATOR_BUNDLE_KIT_TRIPLET_INVALID")
    return directories[0], archives[0], sidecar


def _verifier_document(
    *, label: str, artifact_kind: str, inspection: BuildKitInspection,
    sidecar_sha256: str,
) -> dict[str, Any]:
    report = inspection.report
    return {
        "label": label,
        "artifact_kind": artifact_kind,
        "ok": report.ok and not report.diagnostics,
        "identity": {
            "kit_id": inspection.kit_id,
            "catalog_sha256": inspection.catalog_sha256,
            "manifest_sha256": inspection.manifest_sha256,
            "manifest_digest": inspection.manifest_digest,
            "work_tree": inspection.work_tree,
            "zip_sha256": inspection.canonical_zip_sha256,
            "sidecar_sha256": sidecar_sha256,
        },
        "diagnostics": [
            {"code": item.code, "path": item.path, "message": item.message, "details": item.details}
            for item in sorted(report.diagnostics)
        ],
    }


def _inspection_identity(value: BuildKitInspection) -> tuple[object, ...]:
    return (
        value.files, value.kit_id, value.catalog_sha256, value.manifest_sha256,
        value.manifest_digest, value.upstream_commit, value.fork_dev_commit,
        value.work_commit, value.work_tree, value.work_branch,
        value.canonical_zip_sha256,
    )


def _authenticate_builds(
    request: OperatorBundleRequest,
) -> tuple[
    BuildKitInspection, bytes, bytes, dict[str, dict[str, Any]], dict[str, Any]
]:
    primary_root, comparison_root = _independent_roots(
        request.primary_build_root, request.comparison_build_root
    )
    primary_dir, primary_zip, primary_sidecar = _triplet(primary_root)
    comparison_dir, comparison_zip, comparison_sidecar = _triplet(comparison_root)
    primary_tree = _capture_kit_tree(primary_dir, "OPERATOR_BUNDLE_PRIMARY_BUILD_INVALID")
    comparison_tree = _capture_kit_tree(comparison_dir, "OPERATOR_BUNDLE_BUILD_MISMATCH")
    primary_zip_file = _stable_file(primary_zip, "OPERATOR_BUNDLE_KIT_READ_FAILED")
    comparison_zip_file = _stable_file(comparison_zip, "OPERATOR_BUNDLE_KIT_READ_FAILED")
    primary_sidecar_file = _stable_file(primary_sidecar, "OPERATOR_BUNDLE_SIDECAR_INVALID")
    comparison_sidecar_file = _stable_file(comparison_sidecar, "OPERATOR_BUNDLE_SIDECAR_INVALID")
    primary_identities = set(primary_tree.directory_identities) | set(primary_tree.file_identities) | {
        primary_zip_file.identity, primary_sidecar_file.identity,
    }
    comparison_identities = set(comparison_tree.directory_identities) | set(comparison_tree.file_identities) | {
        comparison_zip_file.identity, comparison_sidecar_file.identity,
    }
    if primary_identities & comparison_identities:
        raise VerificationError("OPERATOR_BUNDLE_BUILD_ROOTS_NOT_INDEPENDENT")
    if primary_tree.files != comparison_tree.files:
        raise VerificationError("OPERATOR_BUNDLE_BUILD_MISMATCH")
    if primary_zip_file.data != comparison_zip_file.data:
        raise VerificationError("OPERATOR_BUNDLE_BUILD_MISMATCH")
    expected_sidecar = (
        f"{_sha(primary_zip_file.data)}  {primary_zip.name}\n".encode("ascii")
    )
    if (
        primary_sidecar_file.data != expected_sidecar
        or comparison_sidecar_file.data != expected_sidecar
    ):
        raise VerificationError("OPERATOR_BUNDLE_BUILD_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="macro-menu-frozen-builds-") as temporary_text:
        temporary = Path(temporary_text)
        temporary.chmod(0o700)
        frozen_paths: list[Path] = []
        for label, tree, archive in (
            ("primary", primary_tree, primary_zip_file.data),
            ("comparison", comparison_tree, comparison_zip_file.data),
        ):
            frozen_root = temporary / label
            frozen_root.mkdir(mode=0o700)
            frozen_dir = frozen_root / primary_dir.name
            frozen_dir.mkdir(mode=0o700)
            for relative in tree.directories:
                frozen_dir.joinpath(*relative.split("/")).mkdir(
                    parents=True, exist_ok=True, mode=0o700
                )
            _copy_records(frozen_dir, "", tree.files)
            frozen_zip = frozen_root / primary_zip.name
            _write_file(frozen_root, primary_zip.name, archive)
            _write_file(frozen_root, primary_sidecar.name, expected_sidecar)
            frozen_paths.extend((frozen_dir, frozen_zip))
        inspections = tuple(inspect_build_kit(path) for path in frozen_paths)
    if not inspections[0].report.ok or inspections[0].report.diagnostics:
        codes = ",".join(item.code for item in inspections[0].report.diagnostics)
        raise VerificationError(f"OPERATOR_BUNDLE_PRIMARY_BUILD_INVALID: {codes}")
    if any(not item.report.ok or item.report.diagnostics for item in inspections[1:]):
        codes = ";".join(
            ",".join(diagnostic.code for diagnostic in item.report.diagnostics)
            for item in inspections[1:]
        )
        raise VerificationError(f"OPERATOR_BUNDLE_BUILD_MISMATCH: {codes}")
    if any(_inspection_identity(item) != _inspection_identity(inspections[0]) for item in inspections[1:]):
        raise VerificationError("OPERATOR_BUNDLE_BUILD_MISMATCH")
    labels = ("primary_directory", "primary_zip", "comparison_directory", "comparison_zip")
    kinds = ("directory", "zip", "directory", "zip")
    sidecar_sha = _sha(expected_sidecar)
    verifier_records = {
        label: _verifier_document(
            label=label,
            artifact_kind=kind,
            inspection=item,
            sidecar_sha256=sidecar_sha,
        )
        for label, kind, item in zip(labels, kinds, inspections, strict=True)
    }
    def authenticated_content_sha256(
        tree: _StableTree, archive: bytes, sidecar: bytes,
    ) -> str:
        return _sha(canonical_json_bytes({
            "directories": list(tree.directories),
            "files": _member_records(tree.files),
            "kit_zip_sha256": _sha(archive),
            "kit_sidecar_sha256": _sha(sidecar),
        }))

    build_identity = {
        "primary_build_record_id": request.generation_record_id + "-primary",
        "comparison_build_record_id": request.generation_record_id + "-comparison",
        "primary_authenticated_content_sha256": authenticated_content_sha256(
            primary_tree, primary_zip_file.data, primary_sidecar_file.data,
        ),
        "comparison_authenticated_content_sha256": authenticated_content_sha256(
            comparison_tree, comparison_zip_file.data, comparison_sidecar_file.data,
        ),
        "primary_kit_identity": verifier_records["primary_directory"]["identity"],
        "comparison_kit_identity": verifier_records["comparison_directory"]["identity"],
        "verifier_records": verifier_records,
    }
    return (
        inspections[0], primary_zip_file.data, expected_sidecar,
        verifier_records, build_identity,
    )


def _verify_git_binding(repo: Path, inspection: BuildKitInspection) -> tuple[str, str]:
    repository = GitRepository(repo)
    try:
        if repository.replace_refs():
            raise VerificationError("OPERATOR_BUNDLE_GIT_REPLACE_REFS_FORBIDDEN")
        commit = repository.resolve_commit("HEAD")
        tree = repository.tree_oid(commit)
        branch = repository._run("symbolic-ref", "--short", "HEAD", text=True).strip()
        git_dir = repository._run("rev-parse", "--absolute-git-dir", text=True).strip()
    except InfrastructureError as error:
        raise VerificationError("OPERATOR_BUNDLE_GIT_PROVENANCE_INVALID") from error
    if (Path(git_dir) / "objects" / "info" / "alternates").exists():
        raise VerificationError("OPERATOR_BUNDLE_GIT_ALTERNATES_FORBIDDEN")
    if (
        branch != BRANCH or commit != inspection.work_commit or tree != inspection.work_tree
        or inspection.work_branch != BRANCH
        or inspection.upstream_commit != APPROVED_CUTOFF
        or inspection.fork_dev_commit != APPROVED_CUTOFF
    ):
        raise VerificationError("OPERATOR_BUNDLE_GIT_PROVENANCE_INVALID")
    return commit, tree


def _validate_governance(
    request: OperatorBundleRequest, inspection: BuildKitInspection, *, now: datetime,
) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes, bytes]:
    handoff_file = _stable_file(request.handoff, "OPERATOR_BUNDLE_HANDOFF_INVALID")
    ledger_file = _stable_file(request.active_ledger, "OPERATOR_BUNDLE_LEDGER_INVALID")
    snapshot_file = _stable_file(
        request.issuance_revocation_snapshot,
        "OPERATOR_BUNDLE_ISSUANCE_SNAPSHOT_INVALID",
    )
    if ledger_file.identity == snapshot_file.identity:
        raise VerificationError("OPERATOR_BUNDLE_REVOCATION_INPUTS_NOT_DISTINCT")
    handoff_bytes = handoff_file.data
    ledger_bytes = ledger_file.data
    snapshot_bytes = snapshot_file.data
    handoff = _canonical_bytes(handoff_bytes, "OPERATOR_BUNDLE_HANDOFF_INVALID")
    ledger = _canonical_bytes(ledger_bytes, "OPERATOR_BUNDLE_LEDGER_INVALID")
    snapshot = _canonical_bytes(
        snapshot_bytes, "OPERATOR_BUNDLE_ISSUANCE_SNAPSHOT_INVALID"
    )
    created = _utc(handoff.get("created_at"), "OPERATOR_BUNDLE_HANDOFF_INVALID")
    expires = _utc(handoff.get("expires_at"), "OPERATOR_BUNDLE_HANDOFF_INVALID")
    ledger_time = _utc(ledger.get("captured_at"), "OPERATOR_BUNDLE_LEDGER_INVALID")
    snapshot_time = _utc(snapshot.get("captured_at"), "OPERATOR_BUNDLE_ISSUANCE_SNAPSHOT_INVALID")
    if created > now:
        raise VerificationError("OPERATOR_BUNDLE_HANDOFF_NOT_YET_VALID")
    if now >= expires:
        raise VerificationError("OPERATOR_BUNDLE_HANDOFF_EXPIRED")
    if ledger_time > now:
        raise VerificationError("OPERATOR_BUNDLE_LEDGER_CAPTURED_IN_FUTURE")
    try:
        validate_active_ledger(ledger, effective_at=now)
        validate_active_ledger(snapshot, effective_at=created)
    except EvidenceError as error:
        raise VerificationError(f"OPERATOR_BUNDLE_LEDGER_INVALID: {error}") from error
    handoff_id = handoff.get("handoff_id")
    if handoff.get("purpose") != "discovery" or handoff.get("compile_status") != "not-run" or handoff.get("release_eligible") is not False:
        raise VerificationError("OPERATOR_BUNDLE_HANDOFF_INVALID")
    if _sha(snapshot_bytes) != handoff.get("revocation_snapshot_sha256"):
        raise VerificationError("OPERATOR_BUNDLE_ISSUANCE_SNAPSHOT_MISMATCH")
    if snapshot.get("source") != ledger.get("source"):
        raise VerificationError("OPERATOR_BUNDLE_LEDGER_SOURCE_MISMATCH")
    if snapshot_time > created or created - snapshot_time > timedelta(hours=24):
        raise VerificationError("OPERATOR_BUNDLE_ISSUANCE_SNAPSHOT_STALE")
    if ledger_time < created or ledger_time > now or now - ledger_time > timedelta(hours=24):
        raise VerificationError("OPERATOR_BUNDLE_LEDGER_STALE")
    active = ledger.get("active_handoff_ids")
    withdrawn = ledger.get("withdrawn_handoff_ids")
    if handoff_id in (withdrawn if isinstance(withdrawn, list) else ()):
        raise VerificationError("OPERATOR_BUNDLE_HANDOFF_WITHDRAWN")
    if handoff_id not in (active if isinstance(active, list) else ()):
        raise VerificationError("OPERATOR_BUNDLE_HANDOFF_INACTIVE")
    if handoff_id in (
        *(snapshot.get("active_handoff_ids") or ()),
        *(snapshot.get("withdrawn_handoff_ids") or ()),
    ):
        raise VerificationError("OPERATOR_BUNDLE_ISSUANCE_SNAPSHOT_STATE_INVALID")
    if snapshot_bytes == ledger_bytes:
        raise VerificationError("OPERATOR_BUNDLE_REVOCATION_INPUTS_NOT_DISTINCT")
    report = validate_handoff(inspection, handoff, effective_at=ledger["captured_at"])
    if not report.ok or report.diagnostics:
        raise VerificationError("OPERATOR_BUNDLE_HANDOFF_BINDING_INVALID")
    return handoff, handoff_bytes, ledger, ledger_bytes, snapshot_bytes


def _pinned_worktree_files(
    repo: Path, commit: str, root: Path, code: str,
) -> tuple[tuple[str, bytes], ...]:
    captured = _capture_tree(root, code).files
    try:
        prefix = root.relative_to(repo).as_posix()
    except ValueError as error:
        raise VerificationError(code) from error
    repository = GitRepository(repo)
    try:
        tracked = repository.list_tree(commit, prefix)
        status = repository._run(
            "status", "--porcelain=v1", "-z", "--untracked-files=no", "--", prefix
        )
    except InfrastructureError as error:
        raise VerificationError(code) from error
    expected = tuple(
        (path.removeprefix(prefix + "/"), repository.read_blob(commit, path))
        for path, _oid in tracked
    )
    if status or captured != expected:
        raise VerificationError(code)
    return expected


def _pinned_worktree_file(
    repo: Path, commit: str, path: Path, code: str,
) -> bytes:
    captured = _stable_file(path, code).data
    try:
        relative = path.relative_to(repo).as_posix()
    except ValueError as error:
        raise VerificationError(code) from error
    repository = GitRepository(repo)
    try:
        status = repository._run(
            "status", "--porcelain=v1", "-z", "--untracked-files=no", "--", relative
        )
        pinned = repository.read_blob(commit, relative)
    except InfrastructureError as error:
        raise VerificationError(code) from error
    if status or captured != pinned:
        raise VerificationError(code)
    return captured


def _pinned_collector_files(repo: Path, commit: str) -> tuple[tuple[str, bytes], ...]:
    repository = GitRepository(repo)
    prefix = "catvba_refactor/target_collector"
    try:
        status = repository._run(
            "status", "--porcelain=v1", "-z", "--untracked-files=no", "--", prefix
        )
        output = repository._run(
            "ls-tree", "-r", "-z", "--name-only", commit, "--", prefix
        )
    except InfrastructureError as error:
        raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_INVALID") from error
    if status:
        raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_TRACKED_DIRTY")
    records: list[tuple[str, bytes]] = []
    for raw_path in output.split(b"\0"):
        if not raw_path:
            continue
        try:
            path = raw_path.decode("ascii")
        except UnicodeDecodeError as error:
            raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_INVALID") from error
        expected_prefix = prefix + "/"
        if not path.startswith(expected_prefix):
            raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_INVALID")
        relative = path.removeprefix(expected_prefix)
        try:
            data = repository.read_blob(commit, path)
        except InfrastructureError as error:
            raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_INVALID") from error
        records.append((relative, data))
    records.sort(key=lambda item: item[0].encode("ascii"))
    if not records or not validate_portable_ascii_paths(path for path, _ in records).ok:
        raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_INVALID")
    if any(not path.endswith(".py") for path, _data in records):
        raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_NONPY_FORBIDDEN")
    try:
        final_head = repository.resolve_commit("HEAD")
        final_status = repository._run(
            "status", "--porcelain=v1", "-z", "--untracked-files=no", "--", prefix
        )
    except InfrastructureError as error:
        raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_INVALID") from error
    if final_head != commit:
        raise VerificationError("OPERATOR_BUNDLE_GIT_PROVENANCE_INVALID")
    if final_status:
        raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_TRACKED_DIRTY")
    return tuple(records)


def _collector_imports(files: tuple[tuple[str, bytes], ...]) -> tuple[str, ...]:
    imports: set[str] = set()
    for path, data in files:
        try:
            tree = ast.parse(data.decode("utf-8"), filename=path)
        except (UnicodeError, SyntaxError) as error:
            raise VerificationError("OPERATOR_BUNDLE_COLLECTOR_SYNTAX_INVALID") from error
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                names = (node.module or "",)
            else:
                continue
            for name in names:
                top = name.partition(".")[0]
                if top == "catvba_refactor":
                    imports.add(top)
                    continue
                if top not in sys.stdlib_module_names:
                    raise VerificationError(
                        f"OPERATOR_BUNDLE_COLLECTOR_THIRD_PARTY_IMPORT: {top}"
                    )
                imports.add(top)
    return tuple(sorted(imports))


def build_target_collector_pyz(
    repo_root: Path, commit: str,
) -> tuple[bytes, tuple[tuple[str, bytes], ...]]:
    """Build the pinned stdlib-only target collector pyz and return its sources."""

    collector = _pinned_collector_files(Path(repo_root), commit)
    _collector_imports(collector)
    pyz_files = (
        (
            "__main__.py",
            b"from catvba_refactor.target_collector.cli import main\n"
            b"raise SystemExit(main())\n",
        ),
        ("catvba_refactor/__init__.py", b""),
        *((f"catvba_refactor/target_collector/{path}", data) for path, data in collector),
    )
    pyz_bytes = _zip_bytes(pyz_files, shebang=b"#!/usr/bin/env python3\n")
    if len(pyz_bytes) > _MAX_PYZ_BYTES:
        raise VerificationError("OPERATOR_BUNDLE_PYZ_SIZE_LIMIT")
    return pyz_bytes, collector


def _write_file(root: Path, relative: str, data: bytes) -> None:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise InfrastructureError(f"OPERATOR_BUNDLE_STAGE_WRITE_FAILED: {relative}") from error


def _copy_records(root: Path, prefix: str, records: Iterable[tuple[str, bytes]]) -> None:
    for path, data in records:
        _write_file(root, f"{prefix}/{path}" if prefix else path, data)


def _checksum_bytes(root: Path) -> bytes:
    files = tuple(
        sorted(
            (
                (path.relative_to(root).as_posix(), path.read_bytes())
                for path in root.rglob("*")
                if path.is_file() and path.name != "SHA256SUMS"
            ),
            key=lambda item: item[0].encode("ascii"),
        )
    )
    return b"".join(f"{_sha(data)}  {path}\n".encode("ascii") for path, data in files)


def _fsync_tree(root: Path) -> None:
    if os.name == "nt":
        return
    directories = [path for path in root.rglob("*") if path.is_dir()]
    directories.sort(key=lambda path: len(path.parts), reverse=True)
    for path in (*directories, root):
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_publish(staging: Path, destination: Path) -> None:
    """Publish one complete directory with an OS-enforced no-replace rename."""

    if os.name == "nt":  # pragma: no cover - exercised by the native Windows CI job
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        move.restype = ctypes.c_int
        if move(str(staging), str(destination), 0x8):  # MOVEFILE_WRITE_THROUGH
            return
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise InfrastructureError("OPERATOR_BUNDLE_OUTPUT_EXISTS")
        raise InfrastructureError("OPERATOR_BUNDLE_ATOMIC_PUBLISH_FAILED")
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as error:
        raise InfrastructureError("OPERATOR_BUNDLE_ATOMIC_NOREPLACE_UNAVAILABLE") from error
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(staging), -100, os.fsencode(destination), 1)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise InfrastructureError("OPERATOR_BUNDLE_OUTPUT_EXISTS")
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise InfrastructureError("OPERATOR_BUNDLE_ATOMIC_NOREPLACE_UNAVAILABLE")
    raise InfrastructureError("OPERATOR_BUNDLE_ATOMIC_PUBLISH_FAILED")


def _validate_record_ids(request: OperatorBundleRequest) -> None:
    if not all(_RECORD.fullmatch(value) for value in (
        request.generation_record_id, request.test_record_id, request.review_record_id,
    )):
        raise VerificationError("OPERATOR_BUNDLE_RECORD_ID_INVALID")


def build_operator_bundle(
    request: OperatorBundleRequest,
    *,
    _clock: Callable[[], datetime] = _trusted_now,
) -> OperatorBundleReceipt:
    """Build one immutable bundle, publishing only after every check succeeds."""

    try:
        request = OperatorBundleRequest(**{
            field: (Path(getattr(request, field)) if field not in {
                "generation_record_id", "test_record_id", "review_record_id"
            } else getattr(request, field))
            for field in request.__dataclass_fields__
        })
    except (AttributeError, TypeError, ValueError) as error:
        raise VerificationError("OPERATOR_BUNDLE_REQUEST_INVALID") from error
    if request.output_root.exists():
        raise InfrastructureError("OPERATOR_BUNDLE_OUTPUT_EXISTS")
    now = _clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise VerificationError("OPERATOR_BUNDLE_TRUSTED_TIME_INVALID")
    now = now.astimezone(UTC)
    _validate_record_ids(request)
    (
        inspection, kit_zip_bytes, kit_sidecar_bytes, verifier_records,
        build_identity,
    ) = _authenticate_builds(request)
    commit, tree = _verify_git_binding(request.repo_root, inspection)
    handoff, handoff_bytes, ledger, ledger_bytes, snapshot_bytes = _validate_governance(
        request, inspection, now=now
    )

    schemas_root = request.repo_root / "catvba_refactor" / "schemas"
    templates_root = request.repo_root / "catvba_refactor" / "templates" / "target_operator"
    pyz_bytes, collector = build_target_collector_pyz(request.repo_root, commit)
    collector_imports = _collector_imports(collector)
    schemas = _pinned_worktree_files(
        request.repo_root, commit, schemas_root, "OPERATOR_BUNDLE_SCHEMAS_INVALID"
    )
    templates = _pinned_worktree_files(
        request.repo_root, commit, templates_root, "OPERATOR_BUNDLE_TEMPLATES_INVALID"
    )
    tutorials_all = _pinned_worktree_files(
        request.repo_root, commit, request.tutorials,
        "OPERATOR_BUNDLE_TUTORIALS_INVALID",
    )
    tutorial_map = dict(tutorials_all)
    if set(tutorial_map) != set(_TUTORIAL_NAMES):
        raise VerificationError("OPERATOR_BUNDLE_TUTORIAL_SET_INVALID")
    run_script = _pinned_worktree_file(
        request.repo_root, commit, request.run_script,
        "OPERATOR_BUNDLE_RUN_SCRIPT_INVALID",
    )
    skeleton = _files(request.session_skeleton, code="OPERATOR_BUNDLE_SKELETON_INVALID")
    try:
        validate_discovery_skeleton_files(dict(skeleton))
    except CollectorError as error:
        raise VerificationError(f"OPERATOR_BUNDLE_SKELETON_INVALID: {error.code}") from error
    if any(path.casefold().endswith(tuple(_FORBIDDEN_SUFFIXES)) for path, _ in (
        *collector, *schemas, *templates, *tutorials_all, *skeleton,
    )):
        raise VerificationError("OPERATOR_BUNDLE_FORBIDDEN_PAYLOAD")

    pyz_sha = _sha(pyz_bytes)
    skeleton_zip = _zip_bytes(skeleton)

    parent = request.output_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".operator-bundle-", dir=parent))
    try:
        stage = temporary / "stage"
        stage.mkdir()
        _copy_records(stage, "source/target_collector", collector)
        _copy_records(stage, "schemas", schemas)
        _copy_records(stage, "templates", templates)
        for name in _TUTORIAL_NAMES:
            _write_file(stage, name, tutorial_map[name])
        _write_file(stage, "run-discovery.cmd", run_script)
        _write_file(stage, "target-discovery.pyz", pyz_bytes)
        _write_file(stage, "target-discovery.pyz.sha256", f"{pyz_sha}  target-discovery.pyz\n".encode("ascii"))
        _write_file(stage, f"{inspection.kit_id}.zip", kit_zip_bytes)
        _write_file(stage, f"{inspection.kit_id}.zip.sha256", kit_sidecar_bytes)
        _write_file(stage, "handoff.json", handoff_bytes)
        _write_file(stage, "revocation-snapshot.json", snapshot_bytes)
        _write_file(stage, "session-skeleton.zip", skeleton_zip)
        reproducibility = {
            "schema_version": 1,
            "builds_byte_identical": True,
            "kit_zip_sha256": _sha(kit_zip_bytes),
            "verifier_report_digests": {
                label: _sha(canonical_json_bytes(record))
                for label, record in verifier_records.items()
            },
            "active_ledger": {
                "sha256": _sha(ledger_bytes),
                "captured_at": ledger["captured_at"],
                "source": ledger["source"],
            },
            "generation_record_id": request.generation_record_id,
            **build_identity,
        }
        verifier_summary = {
            "schema_version": 1,
            "all_four_verifiers_ok": True,
            "verifiers": verifier_records,
            "verifier_report_digests": {
                label: _sha(canonical_json_bytes(record))
                for label, record in verifier_records.items()
            },
            "review_record_id": request.review_record_id,
        }
        test_receipt = {
            "schema_version": 1,
            "record_id": request.test_record_id,
            "scope": "target-collector-offline-tests",
            "target_execution": "not-run",
            "release_eligible": False,
        }
        _write_file(stage, "receipts/build-reproducibility.json", canonical_json_bytes(reproducibility))
        _write_file(stage, "receipts/verifier-summary.json", canonical_json_bytes(verifier_summary))
        _write_file(stage, "receipts/target-collector-tests.json", canonical_json_bytes(test_receipt))
        _write_file(stage, "SBOM.json", canonical_json_bytes({
            "schema_version": 1,
            "runtime": "CPython 3.12 standard library only",
            "components": [{
                "name": "macro-menu-target-collector",
                "source_commit": commit,
                "files": _member_records(collector),
                "stdlib_imports": list(collector_imports),
            }],
        }))
        _write_file(stage, "THIRD_PARTY_NOTICES.md", b"# Third-party notices\n\nThe target collector uses only the CPython 3.12 standard library.\n")

        provenance = {
            "schema_version": 1,
            "repository": REPOSITORY,
            "branch": BRANCH,
            "evidence_commit": commit,
            "evidence_tree": tree,
            "approved_cutoff": APPROVED_CUTOFF,
            "kit_id": inspection.kit_id,
            "catalog_sha256": inspection.catalog_sha256,
            "manifest_sha256": inspection.manifest_sha256,
            "manifest_digest": inspection.manifest_digest,
            "kit_zip_sha256": _sha(kit_zip_bytes),
            "kit_sidecar_sha256": _sha(kit_sidecar_bytes),
            "handoff_id": handoff["handoff_id"],
            "handoff_sha256": _sha(handoff_bytes),
            "handoff_created_at": handoff["created_at"],
            "handoff_expires_at": handoff["expires_at"],
            "issuance_revocation_snapshot_sha256": _sha(snapshot_bytes),
            "active_ledger_schema_version": ledger["schema_version"],
            "active_ledger_source": ledger["source"],
            "collector_source_commit": commit,
            "collector_source_sha256": _tree_digest(collector),
            "collector_pyz_sha256": pyz_sha,
            "python_requirement": "CPython 3.12",
            "session_skeleton_sha256": _sha(skeleton_zip),
            "session_skeleton_members": _member_records(skeleton),
            "tutorials_sha256": _tree_digest(tutorials_all),
            "templates_sha256": _tree_digest(templates),
            "schemas_sha256": _tree_digest(schemas),
            "compile_status": "not-run",
            "target_case_status": "not-run",
            "artifact_status": "not-produced",
            "release_eligible": False,
            "generation_record_id": request.generation_record_id,
            "test_record_id": request.test_record_id,
            "review_record_id": request.review_record_id,
        }
        try:
            schema = json.loads(
                dict(schemas)["operator-bundle-provenance.schema.json"].decode("utf-8")
            )
        except (KeyError, UnicodeError, json.JSONDecodeError) as error:
            raise VerificationError("OPERATOR_BUNDLE_PROVENANCE_SCHEMA_INVALID") from error
        errors = tuple(Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(provenance))
        if errors:
            raise VerificationError(f"OPERATOR_BUNDLE_PROVENANCE_INVALID: {errors[0].message}")
        provenance_bytes = canonical_json_bytes(provenance)
        provenance_sha = _sha(provenance_bytes)
        bundle_id = "bundle-" + provenance_sha[:24]
        _write_file(stage, "provenance.json", provenance_bytes)
        staged_size = sum(
            path.stat().st_size for path in stage.rglob("*") if path.is_file()
        )
        if staged_size > _MAX_OUTPUT_BYTES:
            raise VerificationError("OPERATOR_BUNDLE_OUTPUT_SIZE_LIMIT")
        _write_file(stage, "SHA256SUMS", _checksum_bytes(stage))

        bundle = temporary / bundle_id
        stage.rename(bundle)
        _fsync_tree(temporary)
        _atomic_publish(temporary, request.output_root)
        final = request.output_root / bundle_id
        return OperatorBundleReceipt(
            bundle_id=bundle_id,
            bundle_dir=final,
            bundle_sha256=provenance_sha,
            provenance_sha256=provenance_sha,
            pyz_sha256=pyz_sha,
            kit_id=str(inspection.kit_id),
            handoff_id=str(handoff["handoff_id"]),
            active_ledger_sha256=_sha(ledger_bytes),
            active_ledger_captured_at=str(ledger["captured_at"]),
            active_ledger_source=str(ledger["source"]),
        )
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise
