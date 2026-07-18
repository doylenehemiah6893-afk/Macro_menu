"""Deterministically finalize a native-Windows raw discovery capture.

This module intentionally uses only the Python standard library.  Its ZIP is
an untrusted transport envelope, never an approval or evidence seal.
"""

from __future__ import annotations

import hashlib
import ctypes
import errno
import os
import re
import secrets
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from .canonical import CollectorError, canonical_json_bytes, parse_canonical_json_bytes
from .workspace import (
    MAX_MEMBER_BYTES,
    MAX_TOTAL_MEMBER_BYTES,
    CollectorDiagnostic,
    _chain_snapshot,
    _safe_absolute_path,
    _stable_read,
    status,
)
from .raw_validation import REQUIRED_DOCUMENTS, validate_raw_capture_files
from .constants import MAX_RAW_DEPTH, MAX_RAW_DIRECTORIES, MAX_RAW_SOURCE_MEMBERS


RAW_ZIP_NAME = "raw-discovery-capture.zip"
RAW_MANIFEST_NAME = "raw-capture-manifest.json"
CHECKSUM_NAME = "SHA256SUMS"
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_REQUIRED = REQUIRED_DOCUMENTS
_FORBIDDEN = frozenset({
    "session_complete", "approval.json", "gate-receipt.json",
    RAW_MANIFEST_NAME.casefold(), CHECKSUM_NAME.casefold(), RAW_ZIP_NAME.casefold(),
})
_ASCII_PATH = re.compile(r"^[ -~]+$")


@dataclass(frozen=True)
class RawFinalizeResult:
    ok: bool
    exit_code: int
    diagnostics: tuple[CollectorDiagnostic, ...]
    facts: Mapping[str, object]
    output_root: Path | None = None
    zip_path: Path | None = None
    manifest_path: Path | None = None
    zip_sha256: str | None = None

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.diagnostics)


def _failure(error: CollectorError) -> RawFinalizeResult:
    return RawFinalizeResult(
        False, 3,
        (CollectorDiagnostic(error.code, error.detail or "", error.code),),
        MappingProxyType({}),
    )


def _portable(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(
        path
        and _ASCII_PATH.fullmatch(path)
        and "\\" not in path
        and not path.startswith("/")
        and "/".join(parts) == path
        and all(part not in {"", ".", ".."} and ":" not in part for part in parts)
    )


def _allowed(path: str) -> bool:
    folded = path.casefold()
    if folded in _FORBIDDEN or folded.startswith("returned-catvba/") or path.endswith(".zip"):
        return False
    return path in _REQUIRED or (
        path.startswith("operator-records/") and path != "operator-records/"
    )


def _read_capture(capture: Path) -> dict[str, bytes]:
    checked = status(capture)
    if not checked.ok:
        item = checked.diagnostics[0]
        if item.code == "COLLECTOR_SESSION_INVALID":
            try:
                raw = (capture / "session.json").read_bytes()
                session = parse_canonical_json_bytes(raw)
            except (OSError, CollectorError):
                session = None
            if isinstance(session, dict) and session.get("compile_status") != "not-run":
                raise CollectorError("DISCOVERY_COMPILE_FORBIDDEN", "session.json")
        raise CollectorError(item.code, item.path or None)
    capture, root_chain = _chain_snapshot(capture)
    files: dict[str, bytes] = {}
    total = 0
    directories: list[Path] = [capture]
    directory_signatures: dict[str, tuple[int, int, int, int]] = {}
    member_signatures: dict[str, tuple[int, int, int, int, int, int]] = {}
    while directories:
        directory = directories.pop()
        relative_directory = directory.relative_to(capture).as_posix()
        if relative_directory == ".":
            relative_directory = ""
        info_directory = directory.lstat()
        directory_signatures[relative_directory] = (
            info_directory.st_dev, info_directory.st_ino, info_directory.st_mode,
            info_directory.st_mtime_ns,
        )
        if len(directory_signatures) > MAX_RAW_DIRECTORIES:
            raise CollectorError("COLLECTOR_DIRECTORY_COUNT_EXCEEDED")
        if relative_directory and len(PurePosixPath(relative_directory).parts) > MAX_RAW_DEPTH:
            raise CollectorError("COLLECTOR_DIRECTORY_DEPTH_EXCEEDED", relative_directory)
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.encode("ascii"))
        except (OSError, UnicodeEncodeError) as error:
            raise CollectorError("COLLECTOR_MEMBER_PATH_INVALID", str(directory)) from error
        for child in children:
            try:
                info = child.lstat()
            except OSError as error:
                raise CollectorError("COLLECTOR_FILE_READ_ERROR", str(child)) from error
            relative = child.relative_to(capture).as_posix()
            reparse = bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            if stat.S_ISDIR(info.st_mode) and not reparse:
                directories.append(child)
                continue
            if (
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or reparse
                or not _portable(relative)
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE", relative)
            if not _allowed(relative):
                raise CollectorError("COLLECTOR_RAW_MEMBER_FORBIDDEN", relative)
            if len(files) >= MAX_RAW_SOURCE_MEMBERS or info.st_size > MAX_MEMBER_BYTES:
                raise CollectorError("COLLECTOR_FILE_TOO_LARGE", relative)
            try:
                data, _digest = _stable_read(child, max_bytes=MAX_MEMBER_BYTES)
                after = child.lstat()
            except CollectorError:
                raise
            except OSError as error:
                raise CollectorError("COLLECTOR_FILE_READ_ERROR", relative) from error
            if len(data) != info.st_size or (after.st_dev, after.st_ino, after.st_size) != (
                info.st_dev, info.st_ino, info.st_size
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE", relative)
            total += len(data)
            if total > MAX_TOTAL_MEMBER_BYTES:
                raise CollectorError("COLLECTOR_TOTAL_SIZE_TOO_LARGE")
            files[relative] = data
            member_signatures[relative] = (
                after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
                after.st_size, after.st_mtime_ns,
            )
    _capture_after, after_chain = _chain_snapshot(capture)
    if after_chain != root_chain:
        raise CollectorError("COLLECTOR_CAPTURE_CHANGED", str(capture))
    observed_paths: set[str] = set()
    for directory_path, signature in directory_signatures.items():
        directory = capture.joinpath(*PurePosixPath(directory_path).parts)
        current = directory.lstat()
        if (current.st_dev, current.st_ino, current.st_mode, current.st_mtime_ns) != signature:
            raise CollectorError("COLLECTOR_CAPTURE_CHANGED", directory_path)
        for child in directory.iterdir():
            relative = child.relative_to(capture).as_posix()
            if child.is_dir() and not child.is_symlink():
                observed_paths.add(relative + "/")
            else:
                observed_paths.add(relative)
    expected_paths = set(member_signatures) | {
        path + "/" for path in directory_signatures if path
    }
    if observed_paths != expected_paths:
        raise CollectorError("COLLECTOR_CAPTURE_CHANGED", str(capture))
    for relative, signature in member_signatures.items():
        current = capture.joinpath(*PurePosixPath(relative).parts).lstat()
        if (
            current.st_dev, current.st_ino, current.st_mode, current.st_nlink,
            current.st_size, current.st_mtime_ns,
        ) != signature:
            raise CollectorError("COLLECTOR_CAPTURE_CHANGED", relative)
    missing = sorted(_REQUIRED - files.keys())
    if missing:
        raise CollectorError("COLLECTOR_CAPTURE_INCOMPLETE", missing[0])
    return files


def _checksum_bytes(files: Mapping[str, bytes]) -> bytes:
    # The manifest covers this file.  Excluding both control files avoids a
    # manifest/checksum digest cycle while keeping every observation covered.
    lines = [
        f"{hashlib.sha256(data).hexdigest()}  {path}\n"
        for path, data in sorted(files.items(), key=lambda item: item[0].encode("ascii"))
        if path not in {CHECKSUM_NAME, RAW_MANIFEST_NAME}
    ]
    return "".join(lines).encode("ascii")


def _manifest(session: Mapping[str, object], files: Mapping[str, bytes]) -> bytes:
    members = [
        {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for path, data in sorted(files.items(), key=lambda item: item[0].encode("ascii"))
        if path != RAW_MANIFEST_NAME
    ]
    return canonical_json_bytes({
        "schema_version": 1,
        "session_id": session["session_id"],
        "created_at": session["created_at"],
        "trust_level": "raw-untrusted",
        "mode": "discovery",
        "package_id": "core",
        "profile_id": "DISCOVERY",
        "bundle_id": session["bundle_id"],
        "kit_id": session["kit_id"],
        "handoff_id": session["handoff_id"],
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
        "members": members,
    })


def _zip_bytes(files: Mapping[str, bytes]) -> bytes:
    import io

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, data in sorted(files.items(), key=lambda item: item[0].encode("ascii")):
            info = zipfile.ZipInfo(path, _FIXED_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            info.compress_type = zipfile.ZIP_STORED
            info.extra = b""
            info.comment = b""
            archive.writestr(info, data)
    return output.getvalue()


def _signature(path: Path) -> tuple[int, int, int, int, int, int]:
    info = path.lstat()
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        getattr(info, "st_file_attributes", 0),
    )


def _write_exclusive_file(path: Path, data: bytes) -> tuple[int, int, int, int, int, int]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0),
        0o400,
    )
    opened_initial = os.fstat(descriptor)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError(errno.EIO, "short staging write")
            view = view[written:]
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            current = path.lstat()
            if (
                (current.st_dev, current.st_ino) == (opened_initial.st_dev, opened_initial.st_ino)
                and stat.S_ISREG(current.st_mode) and current.st_nlink == 1
            ):
                path.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)
    observed = _signature(path)
    if observed[:5] != (
        opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink, opened.st_size
    ) or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        raise CollectorError("COLLECTOR_STAGING_CHANGED", str(path))
    return observed


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        # Win32 does not give FlushFileBuffers a supported directory-handle
        # durability contract.  Each staged file is already os.fsync'ed and
        # publication uses MoveFileExW(MOVEFILE_WRITE_THROUGH) below.  Task 9
        # keeps a native-Windows smoke test for this exact boundary.
        return
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_publish(staging: Path, output_root: Path) -> None:
    """Atomically publish a directory without any replacement fallback."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        move.restype = ctypes.c_int
        if move(str(staging), str(output_root), 0x8):  # MOVEFILE_WRITE_THROUGH only
            return
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(output_root))
        raise CollectorError("COLLECTOR_ATOMIC_PUBLISH_FAILED", str(output_root))
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise CollectorError("COLLECTOR_ATOMIC_PUBLISH_UNSUPPORTED")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100, os.fsencode(staging), -100, os.fsencode(output_root), 1
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(output_root))
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise CollectorError("COLLECTOR_ATOMIC_PUBLISH_UNSUPPORTED")
    raise CollectorError("COLLECTOR_ATOMIC_PUBLISH_FAILED", str(output_root))


def _cleanup_staging(
    staging: Path,
    directory_signature: tuple[int, int, int, int, int, int],
    members: Mapping[str, tuple[int, int, int, int, int, int]],
) -> None:
    try:
        current = _signature(staging)
        if (
            (current[0], current[1], current[2], current[5])
            != (
                directory_signature[0], directory_signature[1],
                directory_signature[2], directory_signature[5],
            )
            or not stat.S_ISDIR(current[2])
            or current[5] & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise CollectorError("COLLECTOR_STAGING_CLEANUP_REFUSED", str(staging))
        actual = {child.name: child for child in staging.iterdir()}
        if set(actual) != set(members):
            raise CollectorError("COLLECTOR_STAGING_CLEANUP_REFUSED", str(staging))
        for name, expected in members.items():
            if _signature(actual[name]) != expected:
                raise CollectorError("COLLECTOR_STAGING_CLEANUP_REFUSED", str(staging))
        for name in sorted(members):
            actual[name].unlink()
        staging.rmdir()
    except CollectorError:
        raise
    except OSError as error:
        raise CollectorError("COLLECTOR_STAGING_CLEANUP_REFUSED", str(staging)) from error


def finalize_raw(capture: Path, output_root: Path) -> RawFinalizeResult:
    """Validate fully, then publish one all-or-nothing raw transport directory."""

    staging: Path | None = None
    staging_signature: tuple[int, int, int, int, int, int] | None = None
    staging_members: dict[str, tuple[int, int, int, int, int, int]] = {}
    try:
        output_root = Path(output_root)
        files = _read_capture(Path(capture))
        documents = validate_raw_capture_files(files, controls=False)
        session = documents["session.json"]
        complete = dict(files)
        complete[CHECKSUM_NAME] = _checksum_bytes(complete)
        complete[RAW_MANIFEST_NAME] = _manifest(session, complete)
        archive_bytes = _zip_bytes(complete)
        zip_digest = hashlib.sha256(archive_bytes).hexdigest()

        output_root.parent.mkdir(parents=True, exist_ok=True)
        _safe_absolute_path(output_root.parent)
        for _attempt in range(16):
            candidate = output_root.with_name(
                f".{output_root.name}.staging-{secrets.token_hex(16)}"
            )
            try:
                candidate.mkdir(exist_ok=False, mode=0o700)
            except FileExistsError:
                continue
            staging = candidate
            staging_signature = _signature(staging)
            break
        if staging is None or staging_signature is None:
            raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(output_root))
        for name, data in (
            (RAW_MANIFEST_NAME, complete[RAW_MANIFEST_NAME]),
            (CHECKSUM_NAME, complete[CHECKSUM_NAME]),
            (RAW_ZIP_NAME, archive_bytes),
        ):
            staging_members[name] = _write_exclusive_file(staging / name, data)
        _fsync_directory(staging)
        _atomic_publish(staging, output_root)
        staging = None
        facts = MappingProxyType({
            "output_root": str(output_root), "zip_sha256": zip_digest,
            "trust_level": "raw-untrusted", "gate_evaluated": False,
        })
        return RawFinalizeResult(
            True, 0, (), facts, output_root,
            output_root / RAW_ZIP_NAME, output_root / RAW_MANIFEST_NAME, zip_digest,
        )
    except (CollectorError, OSError) as caught:
        error = caught if isinstance(caught, CollectorError) else CollectorError(
            "COLLECTOR_OUTPUT_WRITE_ERROR", str(output_root)
        )
        if staging is not None and staging_signature is not None:
            try:
                _cleanup_staging(staging, staging_signature, staging_members)
            except CollectorError as cleanup_error:
                error = cleanup_error
        return _failure(error)
