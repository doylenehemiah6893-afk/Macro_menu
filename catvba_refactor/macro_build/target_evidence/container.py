from __future__ import annotations

import ctypes
import errno
import os
import secrets
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Mapping

from ..canonical import canonical_json_bytes, sha256_bytes
from ..errors import EvidenceError, InfrastructureError
from ..model import Diagnostic
from ..portable_paths import validate_portable_ascii_paths
from .model import EvidencePhase, PayloadMember


CONTAINER_POLICY_VERSION = 1
MAX_EVIDENCE_ENTRIES = 512
MAX_EVIDENCE_DIRECTORIES = 512
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 256 * 1024 * 1024
MAX_EVIDENCE_CONTAINER_BYTES = 256 * 1024 * 1024
MAX_EVIDENCE_COMPRESSION_RATIO = 100.0
MAX_EVIDENCE_NESTING_DEPTH = 1
NESTED_G2_PATH = "prerequisites/g2-evidence.zip"

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_FILE_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
)
_RENAME_NOREPLACE = 1
_OS_LINK = os.link
_OS_MKDIR = os.mkdir
_OS_OPEN = os.open
_OS_RMDIR = os.rmdir
_OS_SCANDIR = os.scandir
_OS_STAT = os.stat
_OS_UNLINK = os.unlink


@dataclass(frozen=True)
class EvidenceContainerSnapshot:
    files: tuple[tuple[str, bytes], ...]
    directories: tuple[str, ...]
    container_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class _FileRecord:
    path: str
    parent_fd: int
    name: str
    fd: int
    signature: tuple[int, ...]
    size: int


@dataclass(frozen=True)
class _DirectoryRecord:
    path: str
    fd: int
    parent_fd: int | None
    name: str | None
    signature: tuple[int, ...]


class _ContainerFault(Exception):
    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.message = message


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message)


def _snapshot_failure(
    diagnostics: list[Diagnostic] | tuple[Diagnostic, ...],
    *,
    container_sha256: str | None = None,
) -> EvidenceContainerSnapshot:
    return EvidenceContainerSnapshot(
        files=(),
        directories=(),
        container_sha256=container_sha256,
        diagnostics=tuple(sorted(diagnostics)),
    )


def _stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_descriptor_capabilities() -> None:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if not all(hasattr(os, name) for name in required):
        raise InfrastructureError("EVIDENCE_NOFOLLOW_UNAVAILABLE")
    if not (
        _OS_OPEN in os.supports_dir_fd
        and _OS_STAT in os.supports_dir_fd
        and _OS_STAT in os.supports_follow_symlinks
        and _OS_SCANDIR in os.supports_fd
    ):
        raise InfrastructureError("EVIDENCE_NOFOLLOW_UNAVAILABLE")


def _require_publication_capabilities() -> None:
    _require_descriptor_capabilities()
    if not all(
        operation in os.supports_dir_fd
        for operation in (_OS_MKDIR, _OS_UNLINK, _OS_RMDIR, _OS_LINK)
    ) or _OS_LINK not in os.supports_follow_symlinks:
        raise InfrastructureError("EVIDENCE_ATOMIC_NOREPLACE_UNAVAILABLE")


def _absolute_path(path: os.PathLike[str] | str) -> str:
    try:
        raw = os.fspath(path)
        if type(raw) is not str or not raw or "\x00" in raw:
            raise ValueError("invalid path text")
        return os.path.abspath(raw)
    except (TypeError, ValueError) as error:
        raise _ContainerFault(
            "EVIDENCE_PATH_INVALID", "", "container path is invalid"
        ) from error


def _open_directory_path(
    path: os.PathLike[str] | str, *, create: bool = False
) -> tuple[int, str, tuple[int, ...]]:
    _require_descriptor_capabilities()
    absolute = _absolute_path(path)
    parts = Path(absolute).parts
    if not parts or parts[0] != os.path.sep:
        raise _ContainerFault(
            "EVIDENCE_PATH_INVALID", absolute, "container path must be absolute"
        )
    try:
        current_fd = os.open(os.path.sep, _DIRECTORY_FLAGS)
    except OSError as error:
        raise _ContainerFault(
            "EVIDENCE_PATH_UNREADABLE", os.path.sep, "cannot open filesystem root"
        ) from error
    try:
        for component in parts[1:]:
            try:
                next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise _ContainerFault(
                        "EVIDENCE_PATH_MISSING",
                        absolute,
                        "container path does not exist",
                    )
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current_fd)
                    os.fsync(current_fd)
                    next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
                except FileExistsError:
                    try:
                        next_fd = os.open(
                            component, _DIRECTORY_FLAGS, dir_fd=current_fd
                        )
                    except OSError as error:
                        raise _ContainerFault(
                            "EVIDENCE_SYMLINK_FORBIDDEN",
                            absolute,
                            "output root contains a symlink or non-directory",
                        ) from error
                except OSError as error:
                    raise _ContainerFault(
                        "EVIDENCE_OUTPUT_ROOT_CREATE_FAILED",
                        absolute,
                        "cannot create output root",
                    ) from error
            except OSError as error:
                code = (
                    "EVIDENCE_SYMLINK_FORBIDDEN"
                    if error.errno in {errno.ELOOP, errno.ENOTDIR}
                    else "EVIDENCE_PATH_UNREADABLE"
                )
                raise _ContainerFault(
                    code,
                    absolute,
                    "container path contains a symlink or unreadable directory",
                ) from error
            os.close(current_fd)
            current_fd = next_fd
        signature = _stat_signature(os.fstat(current_fd))
        return current_fd, absolute, signature
    except BaseException:
        os.close(current_fd)
        raise


def _rewalk_matches(path: str, signature: tuple[int, ...]) -> bool:
    try:
        fd, _, current = _open_directory_path(path)
    except (_ContainerFault, InfrastructureError):
        return False
    try:
        return current == signature
    finally:
        os.close(fd)


def _rewalk_identity_matches(path: str, signature: tuple[int, ...]) -> bool:
    try:
        fd, _, current = _open_directory_path(path)
    except (_ContainerFault, InfrastructureError):
        return False
    try:
        return current[:3] == signature[:3]
    finally:
        os.close(fd)


def _portable_diagnostics(paths: tuple[str, ...]) -> list[Diagnostic]:
    return list(validate_portable_ascii_paths(paths).diagnostics)


def _directory_name_diagnostics(
    directory_paths: tuple[str, ...], file_paths: tuple[str, ...]
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for path in directory_paths:
        diagnostics.extend(validate_portable_ascii_paths((path,)).diagnostics)

    folded: dict[str, list[str]] = {}
    for path in directory_paths:
        key = "/".join(part.casefold() for part in path.split("/"))
        folded.setdefault(key, []).append(path)
    for paths in folded.values():
        if len(paths) > 1:
            ordered = tuple(sorted(paths))
            diagnostics.append(
                Diagnostic(
                    code="PATH_COLLISION",
                    path=ordered[0],
                    message="directory paths collide after normalization",
                    details={"paths": ordered},
                )
            )

    file_keys = {
        "/".join(part.casefold() for part in path.split("/")): path
        for path in file_paths
    }
    for path in directory_paths:
        key = "/".join(part.casefold() for part in path.split("/"))
        if key in file_keys:
            diagnostics.append(
                Diagnostic(
                    code="PATH_FILE_DIR_COLLISION",
                    path=file_keys[key],
                    message="a path is both a file and a directory",
                    details={"directory_path": path, "file_path": file_keys[key]},
                )
            )
    return diagnostics


def _derived_directories(paths: tuple[str, ...]) -> tuple[str, ...]:
    directories: set[str] = set()
    for path in paths:
        parts = path.split("/")
        for length in range(1, len(parts)):
            directories.add("/".join(parts[:length]))
    return tuple(sorted(directories))


def _scan_directory(
    root_fd: int,
) -> tuple[list[_FileRecord], list[_DirectoryRecord], list[Diagnostic]]:
    root_stat = os.fstat(root_fd)
    directories = [
        _DirectoryRecord(
            path="",
            fd=root_fd,
            parent_fd=None,
            name=None,
            signature=_stat_signature(root_stat),
        )
    ]
    files: list[_FileRecord] = []
    diagnostics: list[Diagnostic] = []
    entry_count = 0
    file_count = 0
    directory_count = 0
    limit_reached = False

    def visit(record: _DirectoryRecord) -> None:
        nonlocal entry_count, file_count, directory_count, limit_reached
        if limit_reached:
            return
        try:
            names: list[str] = []
            with os.scandir(record.fd) as entries:
                for entry in entries:
                    if entry_count >= (
                        MAX_EVIDENCE_ENTRIES + MAX_EVIDENCE_DIRECTORIES
                    ):
                        diagnostics.append(
                            _diagnostic(
                                "EVIDENCE_ENTRY_LIMIT",
                                record.path,
                                "evidence entry count exceeds policy",
                            )
                        )
                        limit_reached = True
                        return
                    names.append(entry.name)
                    entry_count += 1
            names.sort()
        except OSError:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_DIRECTORY_UNREADABLE",
                    record.path,
                    "evidence directory cannot be enumerated",
                )
            )
            return
        for name in names:
            if limit_reached:
                return
            relative = f"{record.path}/{name}" if record.path else name
            try:
                observed = os.stat(name, dir_fd=record.fd, follow_symlinks=False)
            except OSError:
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_MEMBER_RACE",
                        relative,
                        "evidence member changed during enumeration",
                    )
                )
                continue
            mode = observed.st_mode
            if stat.S_ISLNK(mode):
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_SYMLINK_FORBIDDEN",
                        relative,
                        "symbolic links are forbidden in evidence",
                    )
                )
                continue
            if stat.S_ISDIR(mode):
                if directory_count >= MAX_EVIDENCE_DIRECTORIES:
                    diagnostics.append(
                        _diagnostic(
                            "EVIDENCE_DIRECTORY_LIMIT",
                            relative,
                            "evidence directory count exceeds policy",
                        )
                    )
                    limit_reached = True
                    return
                directory_count += 1
                child_fd: int | None = None
                try:
                    child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=record.fd)
                    child_stat = os.fstat(child_fd)
                except OSError:
                    if child_fd is not None:
                        os.close(child_fd)
                    diagnostics.append(
                        _diagnostic(
                            "EVIDENCE_MEMBER_RACE",
                            relative,
                            "evidence directory changed while opening",
                        )
                    )
                    continue
                if _stat_signature(child_stat) != _stat_signature(observed):
                    os.close(child_fd)
                    diagnostics.append(
                        _diagnostic(
                            "EVIDENCE_MEMBER_RACE",
                            relative,
                            "evidence directory identity changed while opening",
                        )
                    )
                    continue
                child = _DirectoryRecord(
                    path=relative,
                    fd=child_fd,
                    parent_fd=record.fd,
                    name=name,
                    signature=_stat_signature(observed),
                )
                directories.append(child)
                visit(child)
                continue
            if not stat.S_ISREG(mode):
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_NONREGULAR_FILE",
                        relative,
                        "evidence members must be regular files",
                    )
                )
                continue
            if file_count >= MAX_EVIDENCE_ENTRIES:
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_ENTRY_LIMIT",
                        relative,
                        "evidence file count exceeds policy",
                    )
                )
                limit_reached = True
                return
            file_count += 1
            if observed.st_nlink != 1:
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_HARDLINK_FORBIDDEN",
                        relative,
                        "evidence files must have exactly one link",
                    )
                )
                continue
            file_fd: int | None = None
            try:
                file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=record.fd)
                opened = os.fstat(file_fd)
            except OSError:
                if file_fd is not None:
                    os.close(file_fd)
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_MEMBER_RACE",
                        relative,
                        "evidence member changed while pinning",
                    )
                )
                continue
            if _stat_signature(opened) != _stat_signature(observed):
                os.close(file_fd)
                diagnostics.append(
                    _diagnostic(
                        "EVIDENCE_MEMBER_RACE",
                        relative,
                        "evidence member identity changed while pinning",
                    )
                )
                continue
            files.append(
                _FileRecord(
                    path=relative,
                    parent_fd=record.fd,
                    name=name,
                    fd=file_fd,
                    signature=_stat_signature(observed),
                    size=observed.st_size,
                )
            )

    visit(directories[0])
    return files, directories, diagnostics


def _limit_diagnostics(records: tuple[_FileRecord, ...]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if len(records) > MAX_EVIDENCE_ENTRIES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_ENTRY_LIMIT", "", "evidence entry count exceeds policy"
            )
        )
    total = 0
    for record in records:
        if record.size > MAX_EVIDENCE_FILE_BYTES:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_FILE_SIZE_LIMIT",
                    record.path,
                    "evidence member exceeds the individual size limit",
                )
            )
        total += record.size
    if total > MAX_EVIDENCE_TOTAL_BYTES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_TOTAL_SIZE_LIMIT", "", "evidence total size exceeds policy"
            )
        )
    return diagnostics


def _read_file_record(record: _FileRecord) -> bytes:
    try:
        before = os.stat(record.name, dir_fd=record.parent_fd, follow_symlinks=False)
    except OSError as error:
        raise _ContainerFault(
            "EVIDENCE_MEMBER_RACE",
            record.path,
            "evidence member changed before reading",
        ) from error
    opened = os.fstat(record.fd)
    if (
        _stat_signature(before) != record.signature
        or _stat_signature(opened) != record.signature
        or not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
    ):
        raise _ContainerFault(
            "EVIDENCE_MEMBER_RACE",
            record.path,
            "evidence member identity changed after pinning",
        )
    os.lseek(record.fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = record.size
    while remaining:
        chunk = os.read(record.fd, min(1024 * 1024, remaining))
        if not chunk:
            raise _ContainerFault(
                "EVIDENCE_MEMBER_RACE",
                record.path,
                "evidence member became shorter while reading",
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(record.fd, 1):
        raise _ContainerFault(
            "EVIDENCE_MEMBER_RACE",
            record.path,
            "evidence member became longer while reading",
        )
    final_fd = os.fstat(record.fd)
    try:
        final_path = os.stat(
            record.name, dir_fd=record.parent_fd, follow_symlinks=False
        )
    except OSError as error:
        raise _ContainerFault(
            "EVIDENCE_MEMBER_RACE",
            record.path,
            "evidence member disappeared after reading",
        ) from error
    if (
        _stat_signature(final_fd) != record.signature
        or _stat_signature(final_path) != record.signature
    ):
        raise _ContainerFault(
            "EVIDENCE_MEMBER_RACE",
            record.path,
            "evidence member identity changed while reading",
        )
    return b"".join(chunks)


def _validate_directory_records(records: tuple[_DirectoryRecord, ...]) -> None:
    for record in records:
        if _stat_signature(os.fstat(record.fd)) != record.signature:
            raise _ContainerFault(
                "EVIDENCE_DIRECTORY_RACE",
                record.path,
                "evidence directory identity changed during snapshot",
            )
        if record.parent_fd is not None and record.name is not None:
            try:
                current = os.stat(
                    record.name, dir_fd=record.parent_fd, follow_symlinks=False
                )
            except OSError as error:
                raise _ContainerFault(
                    "EVIDENCE_DIRECTORY_RACE",
                    record.path,
                    "evidence directory disappeared during snapshot",
                ) from error
            if _stat_signature(current) != record.signature:
                raise _ContainerFault(
                    "EVIDENCE_DIRECTORY_RACE",
                    record.path,
                    "evidence directory path changed during snapshot",
                )


def _nested_diagnostics(
    files: tuple[tuple[str, bytes], ...], *, phase: EvidencePhase, nesting_depth: int
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for path, data in files:
        if not path.lower().endswith(".zip"):
            continue
        if path != NESTED_G2_PATH:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_NESTED_ZIP_PATH",
                    path,
                    "nested ZIP is allowed only at the G2 prerequisite path",
                )
            )
            continue
        if nesting_depth >= MAX_EVIDENCE_NESTING_DEPTH:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_NESTING_DEPTH",
                    path,
                    "nested evidence depth exceeds policy",
                )
            )
            continue
        nested = _read_zip_bytes(
            data,
            phase=phase,
            nesting_depth=nesting_depth + 1,
            container_sha256=sha256_bytes(data),
        )
        for item in nested.diagnostics:
            diagnostics.append(
                Diagnostic(
                    code=item.code,
                    path=f"{path}!/{item.path}" if item.path else path,
                    message=item.message,
                    details=item.details,
                )
            )
    return diagnostics


def _read_directory(
    path: os.PathLike[str] | str, *, phase: EvidencePhase, nesting_depth: int
) -> EvidenceContainerSnapshot:
    try:
        root_fd, absolute, root_signature = _open_directory_path(path)
    except _ContainerFault as fault:
        return _snapshot_failure(
            [_diagnostic(fault.code, fault.path, fault.message)]
        )
    records: list[_DirectoryRecord] = []
    pinned_files: tuple[_FileRecord, ...] = ()
    try:
        files, records, diagnostics = _scan_directory(root_fd)
        file_records = tuple(
            sorted(
                files,
                key=lambda item: item.path.encode(
                    "utf-8", errors="surrogatepass"
                ),
            )
        )
        pinned_files = file_records
        directory_records = tuple(records)
        file_paths = tuple(record.path for record in file_records)
        directory_paths = tuple(
            sorted(record.path for record in directory_records if record.path)
        )
        diagnostics.extend(_portable_diagnostics(file_paths))
        diagnostics.extend(_directory_name_diagnostics(directory_paths, file_paths))
        diagnostics.extend(_limit_diagnostics(file_records))
        expected_directories = _derived_directories(file_paths)
        for extra in sorted(set(directory_paths) - set(expected_directories)):
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_EXTRA_DIRECTORY",
                    extra,
                    "empty or undeclared directories are forbidden",
                )
            )
        if diagnostics:
            return _snapshot_failure(diagnostics)

        captured: list[tuple[str, bytes]] = []
        for record in file_records:
            try:
                captured.append((record.path, _read_file_record(record)))
            except _ContainerFault as fault:
                diagnostics.append(_diagnostic(fault.code, fault.path, fault.message))
                break
        if not diagnostics:
            try:
                _validate_directory_records(directory_records)
            except _ContainerFault as fault:
                diagnostics.append(_diagnostic(fault.code, fault.path, fault.message))
        if not _rewalk_matches(absolute, root_signature):
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ROOT_RACE",
                    "",
                    "evidence root path changed during snapshot",
                )
            )
        stable_files = tuple(captured)
        diagnostics.extend(
            _nested_diagnostics(
                stable_files, phase=phase, nesting_depth=nesting_depth
            )
        )
        if diagnostics:
            return _snapshot_failure(diagnostics)
        return EvidenceContainerSnapshot(
            files=stable_files,
            directories=expected_directories,
            container_sha256=None,
            diagnostics=(),
        )
    except OSError as error:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_DIRECTORY_UNREADABLE",
                    "",
                    f"evidence directory snapshot failed: {error.__class__.__name__}",
                )
            ]
        )
    finally:
        for record in pinned_files:
            os.close(record.fd)
        for record in reversed(records[1:]):
            os.close(record.fd)
        os.close(root_fd)


def _zip_metadata_diagnostics(
    archive: zipfile.ZipFile, infos: tuple[zipfile.ZipInfo, ...]
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if archive.comment:
        diagnostics.append(
            _diagnostic("EVIDENCE_ZIP_COMMENT", "", "ZIP archive comment is forbidden")
        )
    if len(infos) > MAX_EVIDENCE_ENTRIES:
        diagnostics.append(
            _diagnostic("EVIDENCE_ENTRY_LIMIT", "", "ZIP entry count exceeds policy")
        )

    names = tuple(info.filename for info in infos)
    seen: set[str] = set()
    for name in names:
        if name in seen:
            diagnostics.append(
                _diagnostic("EVIDENCE_ZIP_DUPLICATE", name, "duplicate ZIP name")
            )
        seen.add(name)
    diagnostics.extend(_portable_diagnostics(names))
    if len(_derived_directories(names)) > MAX_EVIDENCE_DIRECTORIES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_DIRECTORY_LIMIT",
                "",
                "derived ZIP directory count exceeds policy",
            )
        )

    total = 0
    for info in infos:
        path = info.filename
        mode = info.external_attr >> 16
        if info.flag_bits & 0x1:
            diagnostics.append(
                _diagnostic("EVIDENCE_ZIP_ENCRYPTED", path, "encrypted ZIP entry")
            )
        if info.flag_bits & 0x8:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_DATA_DESCRIPTOR",
                    path,
                    "ZIP data descriptors are forbidden",
                )
            )
        if info.compress_type != zipfile.ZIP_STORED:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_COMPRESSION",
                    path,
                    "ZIP entries must use ZIP_STORED",
                )
            )
        if info.is_dir() or not stat.S_ISREG(mode):
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_DIRECTORY_ENTRY",
                    path,
                    "ZIP directory and non-regular entries are forbidden",
                )
            )
        elif stat.S_IMODE(mode) != 0o644:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_MODE", path, "ZIP entry mode must be POSIX 0644"
                )
            )
        if info.create_system != 3:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_PLATFORM",
                    path,
                    "ZIP entry platform must be POSIX",
                )
            )
        if info.date_time != (1980, 1, 1, 0, 0, 0):
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_TIMESTAMP",
                    path,
                    "ZIP entry timestamp must be 1980-01-01 UTC",
                )
            )
        if info.extra:
            diagnostics.append(
                _diagnostic("EVIDENCE_ZIP_EXTRA", path, "ZIP extra data is forbidden")
            )
        if info.comment:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_ZIP_ENTRY_COMMENT",
                    path,
                    "ZIP entry comments are forbidden",
                )
            )
        if info.file_size > MAX_EVIDENCE_FILE_BYTES:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_FILE_SIZE_LIMIT",
                    path,
                    "ZIP entry exceeds the individual size limit",
                )
            )
        total += info.file_size
        ratio = (
            float("inf")
            if info.compress_size == 0 and info.file_size
            else info.file_size / max(1, info.compress_size)
        )
        if ratio > MAX_EVIDENCE_COMPRESSION_RATIO:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_COMPRESSION_RATIO",
                    path,
                    "ZIP entry compression ratio exceeds policy",
                )
            )
    if total > MAX_EVIDENCE_TOTAL_BYTES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_TOTAL_SIZE_LIMIT", "", "ZIP total size exceeds policy"
            )
        )
    return diagnostics


def _read_zip_bytes(
    data: bytes,
    *,
    phase: EvidencePhase,
    nesting_depth: int,
    container_sha256: str,
) -> EvidenceContainerSnapshot:
    if len(data) > MAX_EVIDENCE_CONTAINER_BYTES:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_CONTAINER_SIZE_LIMIT",
                    "",
                    "ZIP container exceeds policy",
                )
            ],
            container_sha256=container_sha256,
        )
    try:
        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            infos = tuple(archive.infolist())
            diagnostics = _zip_metadata_diagnostics(archive, infos)
            if diagnostics:
                return _snapshot_failure(
                    diagnostics, container_sha256=container_sha256
                )
            captured: list[tuple[str, bytes]] = []
            for info in sorted(infos, key=lambda item: item.filename.encode("utf-8")):
                try:
                    with archive.open(info, "r") as member:
                        payload = member.read(MAX_EVIDENCE_FILE_BYTES + 1)
                except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                    return _snapshot_failure(
                        [
                            _diagnostic(
                                "EVIDENCE_ZIP_MEMBER_INVALID",
                                info.filename,
                                f"ZIP member read failed: {error.__class__.__name__}",
                            )
                        ],
                        container_sha256=container_sha256,
                    )
                if len(payload) != info.file_size:
                    return _snapshot_failure(
                        [
                            _diagnostic(
                                "EVIDENCE_ZIP_MEMBER_SIZE",
                                info.filename,
                                "ZIP member size differs from central directory",
                            )
                        ],
                        container_sha256=container_sha256,
                    )
                captured.append((info.filename, payload))
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_ZIP_INVALID",
                    "",
                    f"invalid ZIP container: {error.__class__.__name__}",
                )
            ],
            container_sha256=container_sha256,
        )

    stable_files = tuple(captured)
    try:
        canonical_bytes = canonical_evidence_zip_bytes(dict(stable_files))
    except EvidenceError:
        canonical_bytes = b""
    if data != canonical_bytes:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_ZIP_NONCANONICAL",
                    "",
                    "ZIP bytes are not the canonical evidence representation",
                )
            ],
            container_sha256=container_sha256,
        )
    nested = _nested_diagnostics(
        stable_files, phase=phase, nesting_depth=nesting_depth
    )
    if nested:
        return _snapshot_failure(nested, container_sha256=container_sha256)
    return EvidenceContainerSnapshot(
        files=stable_files,
        directories=_derived_directories(tuple(path for path, _ in stable_files)),
        container_sha256=container_sha256,
        diagnostics=(),
    )


def _read_regular_path(path: os.PathLike[str] | str) -> tuple[bytes, str]:
    absolute = _absolute_path(path)
    parent = os.path.dirname(absolute)
    name = os.path.basename(absolute)
    if not name:
        raise _ContainerFault(
            "EVIDENCE_CONTAINER_TYPE", absolute, "container path is not a file"
        )
    parent_fd, _, parent_signature = _open_directory_path(parent)
    try:
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as error:
            raise _ContainerFault(
                "EVIDENCE_PATH_MISSING", absolute, "container path does not exist"
            ) from error
        if stat.S_ISLNK(before.st_mode):
            raise _ContainerFault(
                "EVIDENCE_SYMLINK_FORBIDDEN",
                absolute,
                "symbolic-link containers are forbidden",
            )
        if not stat.S_ISREG(before.st_mode):
            raise _ContainerFault(
                "EVIDENCE_CONTAINER_TYPE",
                absolute,
                "container must be a directory or regular ZIP file",
            )
        if before.st_nlink != 1:
            raise _ContainerFault(
                "EVIDENCE_HARDLINK_FORBIDDEN",
                absolute,
                "container file must have exactly one link",
            )
        if before.st_size > MAX_EVIDENCE_CONTAINER_BYTES:
            raise _ContainerFault(
                "EVIDENCE_CONTAINER_SIZE_LIMIT",
                absolute,
                "ZIP container exceeds policy",
            )
        try:
            fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
        except OSError as error:
            raise _ContainerFault(
                "EVIDENCE_CONTAINER_RACE",
                absolute,
                "container changed while opening",
            ) from error
        try:
            opened = os.fstat(fd)
            signature = _stat_signature(before)
            if _stat_signature(opened) != signature:
                raise _ContainerFault(
                    "EVIDENCE_CONTAINER_RACE",
                    absolute,
                    "container identity changed while opening",
                )
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    raise _ContainerFault(
                        "EVIDENCE_CONTAINER_RACE",
                        absolute,
                        "container became shorter while reading",
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(fd, 1):
                raise _ContainerFault(
                    "EVIDENCE_CONTAINER_RACE",
                    absolute,
                    "container became longer while reading",
                )
            final_fd = os.fstat(fd)
        finally:
            os.close(fd)
        final_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _stat_signature(final_fd) != signature
            or _stat_signature(final_path) != signature
            or not _rewalk_matches(parent, parent_signature)
        ):
            raise _ContainerFault(
                "EVIDENCE_CONTAINER_RACE",
                absolute,
                "container or parent identity changed while reading",
            )
        return b"".join(chunks), absolute
    finally:
        os.close(parent_fd)


def read_evidence_container(
    path: os.PathLike[str] | str,
    *,
    phase: EvidencePhase,
    nesting_depth: int = 0,
) -> EvidenceContainerSnapshot:
    try:
        stable_phase = EvidencePhase(phase)
    except (TypeError, ValueError):
        return _snapshot_failure(
            [_diagnostic("EVIDENCE_PHASE_INVALID", "", "invalid evidence phase")]
        )
    if (
        type(nesting_depth) is not int
        or nesting_depth < 0
        or nesting_depth > MAX_EVIDENCE_NESTING_DEPTH
    ):
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_NESTING_DEPTH", "", "invalid evidence nesting depth"
                )
            ]
        )
    try:
        absolute = _absolute_path(path)
        observed = os.lstat(absolute)
    except _ContainerFault as fault:
        return _snapshot_failure(
            [_diagnostic(fault.code, fault.path, fault.message)]
        )
    except FileNotFoundError:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_PATH_MISSING", str(path), "container path does not exist"
                )
            ]
        )
    except OSError:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_PATH_UNREADABLE",
                    str(path),
                    "container path is unreadable",
                )
            ]
        )
    if stat.S_ISLNK(observed.st_mode):
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_SYMLINK_FORBIDDEN",
                    absolute,
                    "symbolic-link containers are forbidden",
                )
            ]
        )
    if stat.S_ISDIR(observed.st_mode):
        try:
            return _read_directory(
                absolute, phase=stable_phase, nesting_depth=nesting_depth
            )
        except InfrastructureError:
            raise
    try:
        data, _ = _read_regular_path(absolute)
    except _ContainerFault as fault:
        return _snapshot_failure(
            [_diagnostic(fault.code, fault.path, fault.message)]
        )
    except OSError as error:
        return _snapshot_failure(
            [
                _diagnostic(
                    "EVIDENCE_CONTAINER_RACE",
                    "",
                    f"container read changed: {error.__class__.__name__}",
                )
            ]
        )
    return _read_zip_bytes(
        data,
        phase=stable_phase,
        nesting_depth=nesting_depth,
        container_sha256=sha256_bytes(data),
    )


def _validated_file_items(
    files: Mapping[str, bytes],
) -> tuple[tuple[str, bytes], ...]:
    if not isinstance(files, Mapping):
        raise EvidenceError("EVIDENCE_FILE_MAP_INVALID")
    items: list[tuple[str, bytes]] = []
    for path, data in files.items():
        if type(path) is not str or type(data) is not bytes:
            raise EvidenceError("EVIDENCE_FILE_MAP_INVALID")
        items.append((path, data))
    items.sort(key=lambda item: item[0].encode("utf-8", errors="surrogatepass"))
    paths = tuple(path for path, _ in items)
    diagnostics = _portable_diagnostics(paths)
    if len(items) > MAX_EVIDENCE_ENTRIES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_ENTRY_LIMIT",
                "",
                "evidence entry count exceeds policy",
            )
        )
    if len(_derived_directories(paths)) > MAX_EVIDENCE_DIRECTORIES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_DIRECTORY_LIMIT",
                "",
                "derived evidence directory count exceeds policy",
            )
        )
    total = 0
    for path, data in items:
        if len(data) > MAX_EVIDENCE_FILE_BYTES:
            diagnostics.append(
                _diagnostic(
                    "EVIDENCE_FILE_SIZE_LIMIT",
                    path,
                    "evidence member exceeds the individual size limit",
                )
            )
        total += len(data)
    if total > MAX_EVIDENCE_TOTAL_BYTES:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_TOTAL_SIZE_LIMIT", "", "evidence total size exceeds policy"
            )
        )
    if diagnostics:
        codes = ",".join(item.code for item in sorted(diagnostics))
        raise EvidenceError(f"EVIDENCE_FILE_MAP_INVALID:{codes}")
    return tuple(items)


def canonical_payload_manifest(
    files: Mapping[str, bytes],
) -> tuple[bytes, str, tuple[PayloadMember, ...]]:
    items = _validated_file_items(files)
    members = tuple(
        PayloadMember(path=path, sha256=sha256_bytes(data), size=len(data))
        for path, data in items
    )
    manifest = canonical_json_bytes(
        {
            "schema_version": 1,
            "members": [
                {"path": member.path, "sha256": member.sha256, "size": member.size}
                for member in members
            ],
        }
    )
    return manifest, sha256_bytes(manifest), members


def canonical_evidence_zip_bytes(files: Mapping[str, bytes]) -> bytes:
    items = _validated_file_items(files)
    output = BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as archive:
        archive.comment = b""
        for path, data in items:
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            info.extra = b""
            info.comment = b""
            archive.writestr(info, data)
    result = output.getvalue()
    if len(result) > MAX_EVIDENCE_CONTAINER_BYTES:
        raise EvidenceError("EVIDENCE_CONTAINER_SIZE_LIMIT")
    return result


def _validate_bundle_name(bundle_name: str) -> None:
    if type(bundle_name) is not str or not bundle_name or "/" in bundle_name:
        raise EvidenceError("EVIDENCE_BUNDLE_NAME_INVALID")
    report = validate_portable_ascii_paths((bundle_name, f"{bundle_name}.zip"))
    if not report.ok or bundle_name in {".", ".."}:
        raise EvidenceError("EVIDENCE_BUNDLE_NAME_INVALID")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "short write")
        view = view[written:]


def _open_or_create_child_directory(parent_fd: int, name: str) -> int:
    created = False
    try:
        os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    if created:
        os.fsync(parent_fd)
    return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)


def _stage_directory(
    root_fd: int, name: str, items: tuple[tuple[str, bytes], ...]
) -> None:
    created = False
    try:
        os.mkdir(name, mode=0o700, dir_fd=root_fd)
        created = True
        stage_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=root_fd)
        try:
            for path, data in items:
                parts = path.split("/")
                current_fd = os.dup(stage_fd)
                try:
                    for component in parts[:-1]:
                        child_fd = _open_or_create_child_directory(
                            current_fd, component
                        )
                        os.close(current_fd)
                        current_fd = child_fd
                    fd = os.open(
                        parts[-1], _FILE_CREATE_FLAGS, 0o600, dir_fd=current_fd
                    )
                    try:
                        _write_all(fd, data)
                        os.fchmod(fd, 0o644)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.fsync(current_fd)
                finally:
                    os.close(current_fd)
            os.fchmod(stage_fd, 0o755)
            os.fsync(stage_fd)
        finally:
            os.close(stage_fd)
        os.fsync(root_fd)
    except BaseException as primary:
        if created:
            try:
                _remove_tree_at(root_fd, name)
                os.fsync(root_fd)
            except OSError as cleanup_error:
                failure = InfrastructureError("EVIDENCE_TEMP_CLEANUP_FAILED")
                failure.add_note(f"cleanup error: {cleanup_error!r}")
                raise failure from primary
        raise


def _stage_file(root_fd: int, name: str, data: bytes) -> None:
    created = False
    try:
        fd = os.open(name, _FILE_CREATE_FLAGS, 0o600, dir_fd=root_fd)
        created = True
        try:
            _write_all(fd, data)
            os.fchmod(fd, 0o644)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(root_fd)
    except BaseException as primary:
        if created:
            try:
                os.unlink(name, dir_fd=root_fd)
                os.fsync(root_fd)
            except OSError as cleanup_error:
                failure = InfrastructureError("EVIDENCE_TEMP_CLEANUP_FAILED")
                failure.add_note(f"cleanup error: {cleanup_error!r}")
                raise failure from primary
        raise


def _remove_tree_at(parent_fd: int, name: str) -> None:
    try:
        observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(observed.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return
    fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        for child in os.listdir(fd):
            child_stat = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(child_stat.st_mode):
                _remove_tree_at(fd, child)
            else:
                os.unlink(child, dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent_fd)


def _rename_directory_noreplace(root_fd: int, source: str, destination: str) -> None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as error:
        raise InfrastructureError("EVIDENCE_ATOMIC_NOREPLACE_UNAVAILABLE") from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        root_fd,
        os.fsencode(source),
        root_fd,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise InfrastructureError("EVIDENCE_ATOMIC_NOREPLACE_UNAVAILABLE")
    raise OSError(error_number, os.strerror(error_number), destination)


def _entry_kind(root_fd: int, name: str) -> str | None:
    try:
        observed = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(observed.st_mode):
        return "directory"
    if stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1:
        return "file"
    return "unsafe"


def _existing_outputs_match(
    output_root: str,
    bundle_name: str,
    items: tuple[tuple[str, bytes], ...],
    zip_bytes: bytes,
) -> bool:
    directory = read_evidence_container(
        os.path.join(output_root, bundle_name), phase=EvidencePhase.CAPTURE
    )
    archive = read_evidence_container(
        os.path.join(output_root, f"{bundle_name}.zip"), phase=EvidencePhase.CAPTURE
    )
    return (
        not directory.diagnostics
        and not archive.diagnostics
        and directory.files == items
        and archive.files == items
        and archive.container_sha256 == sha256_bytes(zip_bytes)
    )


def publish_evidence_artifacts(
    files: Mapping[str, bytes],
    *,
    bundle_name: str,
    output_root: os.PathLike[str] | str,
) -> tuple[Path, Path, str]:
    _require_publication_capabilities()
    _validate_bundle_name(bundle_name)
    items = _validated_file_items(files)
    nested_diagnostics = _nested_diagnostics(
        items, phase=EvidencePhase.SEALED, nesting_depth=0
    )
    if nested_diagnostics:
        codes = ",".join(
            item.code for item in sorted(nested_diagnostics)
        )
        raise EvidenceError(f"EVIDENCE_FILE_MAP_INVALID:{codes}")
    zip_bytes = canonical_evidence_zip_bytes(dict(items))
    zip_digest = sha256_bytes(zip_bytes)
    try:
        root_fd, absolute_root, root_signature = _open_directory_path(
            output_root, create=True
        )
    except _ContainerFault as fault:
        raise InfrastructureError(fault.code) from fault

    directory_name = bundle_name
    zip_name = f"{bundle_name}.zip"
    temp_token = secrets.token_hex(12)
    temp_directory = f".{bundle_name}.{temp_token}.dir"
    temp_zip = f".{bundle_name}.{temp_token}.zip"
    staged_directory = False
    staged_zip = False
    published_directory = False
    published_zip = False
    primary: BaseException | None = None
    try:
        directory_kind = _entry_kind(root_fd, directory_name)
        zip_kind = _entry_kind(root_fd, zip_name)
        if directory_kind is not None or zip_kind is not None:
            if (
                directory_kind == "directory"
                and zip_kind == "file"
                and _existing_outputs_match(
                    absolute_root, bundle_name, items, zip_bytes
                )
                and _rewalk_identity_matches(absolute_root, root_signature)
            ):
                return (
                    Path(absolute_root) / directory_name,
                    Path(absolute_root) / zip_name,
                    zip_digest,
                )
            raise EvidenceError("EVIDENCE_OUTPUT_CONFLICT")

        _stage_directory(root_fd, temp_directory, items)
        staged_directory = True
        _stage_file(root_fd, temp_zip, zip_bytes)
        staged_zip = True
        if not _rewalk_identity_matches(absolute_root, root_signature):
            raise InfrastructureError("EVIDENCE_OUTPUT_ROOT_RACE")

        os.link(
            temp_zip,
            zip_name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
        published_zip = True
        _rename_directory_noreplace(root_fd, temp_directory, directory_name)
        staged_directory = False
        published_directory = True
        try:
            os.unlink(temp_zip, dir_fd=root_fd)
        except OSError as error:
            raise InfrastructureError("EVIDENCE_TEMP_CLEANUP_FAILED") from error
        staged_zip = False
        os.fsync(root_fd)

        if not _rewalk_identity_matches(absolute_root, root_signature):
            raise InfrastructureError("EVIDENCE_OUTPUT_ROOT_RACE")
        if not _existing_outputs_match(absolute_root, bundle_name, items, zip_bytes):
            raise InfrastructureError("EVIDENCE_OUTPUT_REVALIDATION_FAILED")
        if not _rewalk_identity_matches(absolute_root, root_signature):
            raise InfrastructureError("EVIDENCE_OUTPUT_ROOT_RACE")
        return (
            Path(absolute_root) / directory_name,
            Path(absolute_root) / zip_name,
            zip_digest,
        )
    except BaseException as error:
        if isinstance(error, (EvidenceError, InfrastructureError)):
            failure: BaseException = error
        elif isinstance(error, FileExistsError):
            failure = EvidenceError("EVIDENCE_OUTPUT_CONFLICT")
        elif isinstance(error, OSError):
            failure = InfrastructureError("EVIDENCE_PUBLICATION_FAILED")
        else:
            failure = error
        primary = failure
        if published_zip and not published_directory:
            try:
                temporary_stat = os.stat(
                    temp_zip, dir_fd=root_fd, follow_symlinks=False
                )
                destination_stat = os.stat(
                    zip_name, dir_fd=root_fd, follow_symlinks=False
                )
                if (temporary_stat.st_dev, temporary_stat.st_ino) != (
                    destination_stat.st_dev,
                    destination_stat.st_ino,
                ):
                    raise OSError(errno.ESTALE, "published ZIP identity changed")
                os.unlink(zip_name, dir_fd=root_fd)
                published_zip = False
            except OSError as rollback_error:
                failure = InfrastructureError("EVIDENCE_TEMP_CLEANUP_FAILED")
                primary = failure
                raise failure from rollback_error
        if failure is error:
            raise
        raise failure from error
    finally:
        cleanup_error: OSError | None = None
        try:
            if staged_zip:
                os.unlink(temp_zip, dir_fd=root_fd)
            if staged_directory:
                _remove_tree_at(root_fd, temp_directory)
            os.fsync(root_fd)
        except OSError as error:
            cleanup_error = error
        finally:
            os.close(root_fd)
        if cleanup_error is not None:
            failure = InfrastructureError("EVIDENCE_TEMP_CLEANUP_FAILED")
            if primary is not None:
                raise failure from primary
            raise failure from cleanup_error


__all__ = [
    "CONTAINER_POLICY_VERSION",
    "EvidenceContainerSnapshot",
    "MAX_EVIDENCE_COMPRESSION_RATIO",
    "MAX_EVIDENCE_CONTAINER_BYTES",
    "MAX_EVIDENCE_DIRECTORIES",
    "MAX_EVIDENCE_ENTRIES",
    "MAX_EVIDENCE_FILE_BYTES",
    "MAX_EVIDENCE_NESTING_DEPTH",
    "MAX_EVIDENCE_TOTAL_BYTES",
    "canonical_evidence_zip_bytes",
    "canonical_payload_manifest",
    "publish_evidence_artifacts",
    "read_evidence_container",
]
