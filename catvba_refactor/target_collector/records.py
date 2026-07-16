"""Normalize raw B28 discovery observations without making trust decisions.

This module is deliberately Python-standard-library-only so that the collector
can run under native Windows CPython 3.12.  Its files remain raw/untrusted and
must be ingested by the trusted A-environment before any Gate result exists.
"""

from __future__ import annotations

import csv
import contextvars
import ctypes
import functools
import hashlib
import io
import json
import os
import re
import secrets
import stat
import tempfile
import unicodedata
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, TextIO

from .canonical import CollectorError, canonical_json_bytes, parse_canonical_json_bytes
from .workspace import (
    CollectorResult,
    _chain_snapshot,
    _failure,
    _result,
    _safe_absolute_path,
    _stable_read,
    status,
)


POINT_ORDER = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
LICENSE_IDS = ("AB3", "HD2", "MD2", "SPA", "FTA")
QUALIFICATION_EXPRESSION = "(AB3 OR HD2 OR MD2) AND SPA AND FTA"

REFERENCE_FIELDS = (
    "guid", "major", "minor", "display_name", "missing", "architecture",
    "source_class", "root_kind", "basename", "relative_path", "path_sha256",
)
ENTITLEMENT_FIELDS = ("license_id", "availability", "checkout")
GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._ -]{1,100}$")
RECORD_ID_RE = re.compile(r"^record-[a-z0-9][a-z0-9-]{2,94}$")
ALLOWED_ROOT_KINDS = frozenset({"CATIA_INSTALL", "WINDOWS_INSTALL", "SYSTEM"})
ALLOWED_SOURCE_CLASSES = frozenset(
    {"system", "builtin", "host-default", "package-added", "import-introduced", "unknown"}
)
ALLOWED_AVAILABILITY = frozenset({"unknown", "observed-available", "observed-unavailable"})
ALLOWED_CHECKOUT = frozenset({"unknown", "observed-checked-out", "not-checked-out"})
ALLOWED_CATEGORIES = frozenset(
    {"session", "environment", "entitlement", "reference", "review", "state", "other"}
)
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_CSV_ROWS = 4096
MAX_OPERATOR_CSV_CELLS = 128
MAX_OPERATOR_CSV_CELL_CHARS = 4096
MAX_ENVIRONMENT_EDITION = 100
MAX_ENVIRONMENT_BUILD = 32
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100_000
MAX_JSON_INTEGER_DIGITS = 128
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
TEXT_SUFFIXES = frozenset({".txt", ".csv", ".json", ".md"})
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"\\\\[^\\\s]+[\\/]"),
    re.compile(r"\bfile\s*://", re.IGNORECASE),
    re.compile(r"%userprofile%|\$\{?home\}?", re.IGNORECASE),
    re.compile(r"(?:^|[\\/])users[\\/]", re.IGNORECASE),
    re.compile(r"(?:^|/)home/", re.IGNORECASE),
    re.compile(r"\buser[\s_-]*profile\b", re.IGNORECASE),
    re.compile(r"\btemp(?:orary)?\b", re.IGNORECASE),
    re.compile(r"\bcustomer\b", re.IGNORECASE),
    re.compile(r"\buser[\s_-]+name\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:account|user)[\s_-]+id\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:operator|customer|user)[\s_-]+login\s*[:=]", re.IGNORECASE),
    re.compile(r"\boperator[\s_-]+(?:name|id|account)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:dsls[\s_-]+)?(?:endpoint|host(?:name)?|server)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
    re.compile(r"\bhttps?://", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|secret|token|credential|api[\s_-]*key|private[\s_-]*key)\b", re.IGNORECASE),
    re.compile(r"(?<![:A-Za-z0-9._-])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"),
)
_ACTIVE_BACKEND: contextvars.ContextVar["_CaptureWriteBackend | None"] = contextvars.ContextVar(
    "collector_record_backend", default=None
)


def stable_reference_id(guid: str, major: int, minor: int) -> str:
    """Return an opaque identity from the COM reference tuple."""

    if type(guid) is not str or GUID_RE.fullmatch(guid) is None:
        raise ValueError("invalid reference GUID")
    if type(major) is not int or type(minor) is not int or major < 0 or minor < 0:
        raise ValueError("invalid reference version")
    body = f"{guid.upper()}|{major}|{minor}".encode("ascii")
    return "reference-" + hashlib.sha256(body).hexdigest()[:24]


class _CaptureWriteBackend:
    """Identity-pinned write backend shared by all record mutations."""

    def __init__(
        self,
        capture: Path,
        chain: tuple[tuple[str, int, int, int, int], ...],
        lock_fd: int,
        lock_identity: tuple[int, int],
        nonce: str,
    ) -> None:
        self.capture = capture
        self.chain = chain
        self.lock_fd = lock_fd
        self.lock_identity = lock_identity
        self.nonce = nonce
        self.counter = 0
        self.undo: list[tuple[str, str, bytes | None]] = []
        self.capture_fd: int | None = None
        if os.name == "posix" and os.open in getattr(os, "supports_dir_fd", set()):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            self.capture_fd = os.open(capture, flags)
            capture_info = os.fstat(self.capture_fd)
            if (capture_info.st_dev, capture_info.st_ino) != (chain[-1][1], chain[-1][2]):
                os.close(self.capture_fd)
                self.capture_fd = None
                raise CollectorError("COLLECTOR_PATH_UNSAFE", str(capture))

    def close(self) -> None:
        if self.capture_fd is not None:
            os.close(self.capture_fd)
            self.capture_fd = None

    def verify(self) -> None:
        lock_info = os.fstat(self.lock_fd)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_nlink != 1
            or (lock_info.st_dev, lock_info.st_ino) != self.lock_identity
        ):
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(self.capture))
        if self.capture_fd is not None:
            capture_info = os.fstat(self.capture_fd)
            if (capture_info.st_dev, capture_info.st_ino) != (
                self.chain[-1][1], self.chain[-1][2]
            ):
                raise CollectorError("COLLECTOR_PATH_UNSAFE", str(self.capture))
        _capture, current = _chain_snapshot(self.capture)
        if current != self.chain:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(self.capture))

    def _relative(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.capture).as_posix()
        except ValueError as error:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path)) from error
        if not relative or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts):
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path))
        return relative

    def _open_parent_fd(self, relative: str) -> tuple[int, str]:
        if self.capture_fd is None:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", relative)
        descriptor = os.dup(self.capture_fd)
        try:
            parts = PurePosixPath(relative).parts
            for part in parts[:-1]:
                child = os.open(
                    part,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            return descriptor, parts[-1]
        except Exception:
            os.close(descriptor)
            raise

    def write_exclusive(self, path: Path, data: bytes) -> None:
        relative = self._relative(path)
        self.verify()
        _safe_absolute_path(path.parent)
        _parent, parent_chain = _chain_snapshot(path.parent)
        self.counter += 1
        staging_name = f".record-staging-{self.nonce}-{self.counter}"
        created_destination = False
        parent_fd: int | None = None
        try:
            if self.capture_fd is not None:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
                staging_fd = os.open(staging_name, flags, 0o600, dir_fd=self.capture_fd)
                try:
                    os.write(staging_fd, data)
                    os.fsync(staging_fd)
                    staged = os.fstat(staging_fd)
                    if not stat.S_ISREG(staged.st_mode) or staged.st_nlink != 1:
                        raise CollectorError("COLLECTOR_PATH_UNSAFE", relative)
                finally:
                    os.close(staging_fd)
                self.verify()
                _parent_after, parent_before_publish = _chain_snapshot(path.parent)
                if parent_before_publish != parent_chain:
                    raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path.parent))
                parent_fd, leaf = self._open_parent_fd(relative)
                try:
                    os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(path))
                os.link(
                    staging_name,
                    leaf,
                    src_dir_fd=self.capture_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                os.unlink(staging_name, dir_fd=self.capture_fd)
            else:
                staging = self.capture / staging_name
                with staging.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    staged = os.fstat(stream.fileno())
                    if not stat.S_ISREG(staged.st_mode) or staged.st_nlink != 1:
                        raise CollectorError("COLLECTOR_PATH_UNSAFE", str(staging))
                self.verify()
                _parent_after, parent_before_publish = _chain_snapshot(path.parent)
                if parent_before_publish != parent_chain:
                    raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path.parent))
                if path.exists() or path.is_symlink():
                    raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(path))
                os.rename(staging, path)
            created_destination = True
            self.verify()
            _parent_after, parent_after_publish = _chain_snapshot(path.parent)
            if parent_after_publish != parent_chain:
                raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path.parent))
            self.undo.append(("unlink", relative, None))
        except FileExistsError as error:
            raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(path)) from error
        except Exception:
            try:
                if created_destination:
                    if parent_fd is not None:
                        os.unlink(PurePosixPath(relative).name, dir_fd=parent_fd)
                    elif path.exists():
                        path.unlink()
                if self.capture_fd is not None:
                    try:
                        os.unlink(staging_name, dir_fd=self.capture_fd)
                    except FileNotFoundError:
                        pass
                else:
                    (self.capture / staging_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        finally:
            if parent_fd is not None:
                os.close(parent_fd)

    def replace(self, path: Path, data: bytes, expected_sha256: str) -> None:
        old = _read_bounded_file(path)
        if hashlib.sha256(old).hexdigest() != expected_sha256:
            raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
        relative = self._relative(path)
        _parent, parent_chain = _chain_snapshot(path.parent)
        self.counter += 1
        staging_name = f".record-staging-{self.nonce}-{self.counter}"
        self.verify()
        try:
            if self.capture_fd is not None:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(staging_name, flags, 0o600, dir_fd=self.capture_fd)
                try:
                    os.write(descriptor, data)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                parent_fd, leaf = self._open_parent_fd(relative)
                try:
                    current_fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                    try:
                        current = b""
                        while True:
                            chunk = os.read(current_fd, 65536)
                            if not chunk:
                                break
                            current += chunk
                            if len(current) > MAX_INPUT_BYTES:
                                raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
                    finally:
                        os.close(current_fd)
                    if hashlib.sha256(current).hexdigest() != expected_sha256:
                        raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
                    self.verify()
                    _parent_after, parent_before_publish = _chain_snapshot(path.parent)
                    if parent_before_publish != parent_chain:
                        raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path.parent))
                    os.replace(staging_name, leaf, src_dir_fd=self.capture_fd, dst_dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
            else:
                staging = self.capture / staging_name
                with staging.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.verify()
                if hashlib.sha256(_read_bounded_file(path)).hexdigest() != expected_sha256:
                    raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
                _parent_after, parent_before_publish = _chain_snapshot(path.parent)
                if parent_before_publish != parent_chain:
                    raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path.parent))
                staging.replace(path)
            self.undo.append(("restore", relative, old))
            self.verify()
            _parent_after, parent_after_publish = _chain_snapshot(path.parent)
            if parent_after_publish != parent_chain:
                raise CollectorError("COLLECTOR_PATH_UNSAFE", str(path.parent))
        finally:
            if self.capture_fd is not None:
                try:
                    os.unlink(staging_name, dir_fd=self.capture_fd)
                except FileNotFoundError:
                    pass
            else:
                (self.capture / staging_name).unlink(missing_ok=True)

    def commit(self) -> None:
        self.verify()
        self.undo.clear()

    def rollback(self) -> None:
        for operation, relative, old in reversed(self.undo):
            try:
                if self.capture_fd is not None:
                    parent_fd, leaf = self._open_parent_fd(relative)
                    try:
                        if operation == "unlink":
                            os.unlink(leaf, dir_fd=parent_fd)
                        elif old is not None:
                            temp = f".rollback-{self.nonce}-{secrets.token_hex(4)}"
                            descriptor = os.open(
                                temp,
                                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                                0o600,
                                dir_fd=self.capture_fd,
                            )
                            os.write(descriptor, old)
                            os.fsync(descriptor)
                            os.close(descriptor)
                            os.replace(temp, leaf, src_dir_fd=self.capture_fd, dst_dir_fd=parent_fd)
                    finally:
                        os.close(parent_fd)
                else:
                    target = self.capture.joinpath(*PurePosixPath(relative).parts)
                    if operation == "unlink":
                        target.unlink(missing_ok=True)
                    elif old is not None:
                        target.write_bytes(old)
            except OSError:
                pass
        self.undo.clear()


@contextmanager
def _capture_transaction(capture: Path):
    """Hold one cross-process lock while preserving the capture directory identity."""

    capture, before = _chain_snapshot(Path(capture))
    lock_path = capture / ".collector-records.lock"
    descriptor: int | None = None
    lock_identity: tuple[int, int] | None = None
    backend: _CaptureWriteBackend | None = None
    token = None
    try:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError as error:
            raise CollectorError("COLLECTOR_CAPTURE_BUSY", str(lock_path)) from error
        except OSError as error:
            raise CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(lock_path)) from error
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(lock_path))
        lock_identity = (info.st_dev, info.st_ino)
        nonce = secrets.token_hex(16)
        lock_document = (
            f"schema_version=1\npid={os.getpid()}\nnonce={nonce}\n"
            f"capture_dev={before[-1][1]}\ncapture_ino={before[-1][2]}\n"
        ).encode("ascii")
        os.write(descriptor, lock_document)
        os.fsync(descriptor)
        _capture_after, after_lock = _chain_snapshot(capture)
        if before != after_lock:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(capture))
        backend = _CaptureWriteBackend(capture, before, descriptor, lock_identity, nonce)
        backend.verify()
        token = _ACTIVE_BACKEND.set(backend)
        yield capture
        backend.commit()
    except Exception:
        if backend is not None:
            backend.rollback()
        raise
    finally:
        if token is not None:
            _ACTIVE_BACKEND.reset(token)
        if backend is not None:
            backend.close()
        if descriptor is not None:
            try:
                current = lock_path.lstat()
                if (
                    lock_identity is None
                    or not stat.S_ISREG(current.st_mode)
                    or current.st_nlink != 1
                    or (current.st_dev, current.st_ino) != lock_identity
                ):
                    raise CollectorError("COLLECTOR_PATH_UNSAFE", str(lock_path))
                os.close(descriptor)
                descriptor = None
                lock_path.unlink()
            finally:
                if descriptor is not None:
                    os.close(descriptor)


def _locked_mutation(function):
    @functools.wraps(function)
    def wrapper(capture: Path, *args, **kwargs) -> CollectorResult:
        try:
            with _capture_transaction(Path(capture)) as checked:
                result = function(checked, *args, **kwargs)
                backend = _ACTIVE_BACKEND.get()
                if backend is not None and not result.ok:
                    backend.rollback()
                return result
        except CollectorError as error:
            return _failure(error)

    return wrapper


def _process_is_alive(pid: int) -> bool:
    """Conservatively probe a process without ever signalling it on Windows."""

    if type(pid) is not int or pid <= 0:
        return True
    if os.name == "nt":
        synchronize = 0x00100000
        query_limited_information = 0x00001000
        wait_object_0 = 0x00000000
        wait_timeout = 0x00000102
        error_invalid_parameter = 87
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            wait_for_single_object = kernel32.WaitForSingleObject
            close_handle = kernel32.CloseHandle
            try:
                open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
                open_process.restype = ctypes.c_void_p
                wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                wait_for_single_object.restype = ctypes.c_ulong
                close_handle.argtypes = [ctypes.c_void_p]
                close_handle.restype = ctypes.c_int
            except (AttributeError, TypeError):
                pass
            handle = open_process(
                synchronize | query_limited_information,
                False,
                pid,
            )
        except Exception:
            return True
        if not handle:
            try:
                error = ctypes.get_last_error()
            except Exception:
                return True
            return error != error_invalid_parameter
        try:
            try:
                result = wait_for_single_object(handle, 0)
            except Exception:
                return True
            if result == wait_object_0:
                return False
            if result == wait_timeout:
                return True
            return True
        finally:
            try:
                close_handle(handle)
            except Exception:
                pass
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True
    return True


def recover_stale_record_lock(capture: Path) -> bool:
    """Explicitly recover a dead-owner lock; never called implicitly or by the CLI."""

    capture, before = _chain_snapshot(Path(capture))
    lock_path = capture / ".collector-records.lock"
    data, _digest = _stable_read(lock_path, max_bytes=4096)
    try:
        lines = data.decode("ascii").splitlines()
        pairs = [line.split("=", 1) for line in lines]
        fields = dict(pairs)
        if (
            len(pairs) != 5
            or any(len(pair) != 2 for pair in pairs)
            or set(fields) != {"schema_version", "pid", "nonce", "capture_dev", "capture_ino"}
            or fields["schema_version"] != "1"
            or not re.fullmatch(r"[0-9a-f]{32}", fields["nonce"])
        ):
            raise ValueError("lock format")
        pid = int(fields["pid"])
        if pid <= 0:
            raise ValueError("pid")
        expected_identity = (int(fields["capture_dev"]), int(fields["capture_ino"]))
    except (UnicodeError, ValueError) as error:
        raise CollectorError("COLLECTOR_STALE_LOCK_INVALID", str(lock_path)) from error
    if expected_identity != (before[-1][1], before[-1][2]):
        raise CollectorError("COLLECTOR_STALE_LOCK_IDENTITY_MISMATCH", str(lock_path))
    if any(path.name.startswith((".record-staging-", ".rollback-")) for path in capture.iterdir()):
        raise CollectorError("COLLECTOR_STALE_LOCK_STAGING_PRESENT", str(capture))
    if _process_is_alive(pid):
        raise CollectorError("COLLECTOR_CAPTURE_BUSY", str(lock_path))
    lock_before = lock_path.lstat()
    _capture_after, after = _chain_snapshot(capture)
    if before != after:
        raise CollectorError("COLLECTOR_PATH_UNSAFE", str(capture))
    lock_after = lock_path.lstat()
    if (
        not stat.S_ISREG(lock_after.st_mode)
        or lock_after.st_nlink != 1
        or (lock_before.st_dev, lock_before.st_ino) != (lock_after.st_dev, lock_after.st_ino)
    ):
        raise CollectorError("COLLECTOR_PATH_UNSAFE", str(lock_path))
    lock_path.unlink()
    return True


def _checked_capture(capture: Path) -> Path:
    capture = Path(capture)
    result = status(capture)
    if not result.ok:
        diagnostic = result.diagnostics[0]
        raise CollectorError(diagnostic.code, diagnostic.path or None)
    return capture


def _write_exclusive(path: Path, document: object) -> None:
    backend = _ACTIVE_BACKEND.get()
    if backend is not None:
        backend.write_exclusive(path, canonical_json_bytes(document))
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _safe_absolute_path(path.parent)
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(document))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(path)) from error
    except OSError as error:
        raise CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(path)) from error


def _replace_document(path: Path, document: object, *, expected_sha256: str) -> None:
    backend = _ACTIVE_BACKEND.get()
    if backend is not None:
        backend.replace(path, canonical_json_bytes(document), expected_sha256)
        return
    temporary = path.with_name(path.name + ".new")
    try:
        _safe_absolute_path(path.parent)
        current, current_sha256 = _stable_read(path, max_bytes=MAX_INPUT_BYTES)
        if hashlib.sha256(current).hexdigest() != current_sha256 or current_sha256 != expected_sha256:
            raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
        with temporary.open("xb") as stream:
            stream.write(canonical_json_bytes(document))
            stream.flush()
            os.fsync(stream.fileno())
        _current, before_commit_sha256 = _stable_read(path, max_bytes=MAX_INPUT_BYTES)
        if before_commit_sha256 != expected_sha256:
            raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
        temporary.replace(path)
    except FileExistsError as error:
        raise CollectorError("COLLECTOR_UPDATE_BUSY", str(path)) from error
    except OSError as error:
        raise CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(path)) from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_bounded_file(path: Path) -> bytes:
    try:
        data, _digest = _stable_read(Path(path), max_bytes=MAX_INPUT_BYTES)
        return data
    except CollectorError as error:
        if error.code == "COLLECTOR_FILE_TOO_LARGE":
            raise CollectorError("COLLECTOR_OPERATOR_RECORD_TOO_LARGE", str(path)) from error
        if error.code in {"COLLECTOR_PATH_UNSAFE", "COLLECTOR_FILE_UNSAFE"}:
            raise CollectorError("COLLECTOR_FILE_UNSAFE", str(path)) from error
        raise
    except OSError as error:
        raise CollectorError("COLLECTOR_FILE_READ_ERROR", str(path)) from error


def _load_json_source(source: object) -> dict[str, Any]:
    if type(source) is dict:
        # Round-trip ensures only JSON values and makes a detached copy.
        data = canonical_json_bytes(source)
    elif isinstance(source, (str, os.PathLike)):
        data = _read_bounded_file(Path(source))
    elif hasattr(source, "read"):
        value = source.read()  # type: ignore[union-attr]
        data = value.encode("utf-8") if type(value) is str else value
    else:
        raise CollectorError("COLLECTOR_INPUT_INVALID")
    if type(data) is not bytes or len(data) > MAX_INPUT_BYTES:
        raise CollectorError("COLLECTOR_INPUT_INVALID")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def bounded_integer(text: str) -> int:
        if len(text.lstrip("-")) > MAX_JSON_INTEGER_DIGITS:
            raise ValueError("integer too large")
        return int(text)

    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_int=bounded_integer,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
        pending: list[tuple[object, int]] = [(document, 1)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
                raise ValueError("structure limit")
            if type(item) is dict:
                pending.extend((value, depth + 1) for value in item.values())
            elif type(item) is list:
                pending.extend((value, depth + 1) for value in item)
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise CollectorError("COLLECTOR_INPUT_INVALID") from error
    if type(document) is not dict:
        raise CollectorError("COLLECTOR_INPUT_INVALID")
    return document


def _raw_envelope() -> dict[str, object]:
    return {
        "schema_version": 1,
        "trust_level": "raw-untrusted",
        "mode": "discovery",
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
    }


def _reject_sensitive_text(value: object, *, allow_multiline: bool = False) -> None:
    """Reject path or identity fragments before any free text is persisted."""

    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            pending.extend(item.values())
        elif type(item) in {list, tuple}:
            pending.extend(item)
        elif type(item) is str:
            if (
                (item.lstrip(" ").startswith(("=", "+", "-", "@")))
                or any(
                    unicodedata.category(character) == "Cc"
                    and (not allow_multiline or character not in "\t\r\n")
                    for character in item
                )
                or any(pattern.search(item) for pattern in SENSITIVE_TEXT_PATTERNS)
            ):
                raise CollectorError("COLLECTOR_SENSITIVE_PATH_FORBIDDEN")


def _validate_text_record(data: object) -> str:
    """Apply the same bounded UTF-8, control, and privacy contract on every read."""

    if type(data) is not bytes:
        raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
    if len(data) > MAX_INPUT_BYTES:
        raise CollectorError("COLLECTOR_OPERATOR_RECORD_TOO_LARGE")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID") from error
    if "\x00" in text or any(
        unicodedata.category(character) == "Cc" and character not in "\t\r\n"
        for character in text
    ):
        raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
    _reject_sensitive_text(text, allow_multiline=True)
    return text


def _validate_csv_record(data: object) -> None:
    text = _validate_text_record(data)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows: list[list[str]] = []
        width: int | None = None
        for row in reader:
            if len(rows) >= MAX_CSV_ROWS or not row or len(row) > MAX_OPERATOR_CSV_CELLS:
                raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
            if width is None:
                width = len(row)
                if any(not cell for cell in row) or len(row) != len(set(row)):
                    raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
            elif len(row) != width:
                raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
            for cell in row:
                if len(cell) > MAX_OPERATOR_CSV_CELL_CHARS:
                    raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
                _reject_sensitive_text(cell)
            rows.append(row)
        if len(rows) < 2:
            raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
    except (csv.Error, UnicodeError, CollectorError) as error:
        raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID") from error


def _validate_raw_envelope(document: Mapping[str, object], extras: frozenset[str], code: str) -> None:
    expected = frozenset(_raw_envelope()) | extras
    if frozenset(document) != expected:
        raise CollectorError(code)
    envelope = {key: document.get(key) for key in _raw_envelope()}
    if envelope != _raw_envelope():
        raise CollectorError(code)


def _exact_mapping(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise CollectorError("COLLECTOR_INPUT_INVALID")
    return value


@_locked_mutation
def record_environment(capture: Path, source: object) -> CollectorResult:
    """Record only the approved B28/R28/VBA7/Win64 environment facts."""

    try:
        capture = _checked_capture(capture)
        document = _load_json_source(source)
        _exact_mapping(document, frozenset({"schema_version", "windows", "catia", "vba", "pollution_scan"}))
        if document.get("schema_version") != 1 or type(document.get("schema_version")) is not int:
            raise CollectorError("COLLECTOR_INPUT_INVALID")
        windows = _exact_mapping(document["windows"], frozenset({"edition", "build", "architecture"}))
        catia = _exact_mapping(document["catia"], frozenset({"release", "revision", "build"}))
        vba = _exact_mapping(document["vba"], frozenset({"generation", "win64"}))
        pollution = _exact_mapping(
            document["pollution_scan"], frozenset({"B30", "x86", "VBA6", "Temp", "user-profile"})
        )
        _reject_sensitive_text((windows, catia, vba, tuple(pollution.values())))
        if (
            type(windows.get("edition")) is not str
            or not 1 <= len(windows["edition"]) <= MAX_ENVIRONMENT_EDITION
            or type(windows.get("build")) is not str
            or not 1 <= len(windows["build"]) <= MAX_ENVIRONMENT_BUILD
        ):
            raise CollectorError("COLLECTOR_INPUT_INVALID")
        if (
            catia != {"release": "V5-6R2018", "revision": "R28", "build": "B28"}
            or windows.get("architecture") != "Win64"
            or vba != {"generation": "VBA7", "win64": True}
            or any(pollution.get(item) != "absent" for item in ("B30", "x86", "VBA6", "Temp", "user-profile"))
        ):
            raise CollectorError("COLLECTOR_ENVIRONMENT_FORBIDDEN")
        output = _raw_envelope()
        output.update({"windows": windows, "catia": catia, "vba": vba, "pollution_scan": pollution})
        validate_environment_document(output)
        _write_exclusive(capture / "environment.json", output)
    except CollectorError as error:
        return _failure(error)
    return _result(facts={"relative_path": "environment.json", "trust_level": "raw-untrusted"})


def _open_csv_source(source: object) -> tuple[TextIO, bool]:
    if isinstance(source, (str, os.PathLike)):
        data = _read_bounded_file(Path(source))
        try:
            return io.StringIO(data.decode("utf-8-sig", errors="strict"), newline=""), True
        except UnicodeError as error:
            raise CollectorError("COLLECTOR_CSV_INVALID") from error
    if hasattr(source, "read"):
        return source, False  # type: ignore[return-value]
    raise CollectorError("COLLECTOR_CSV_INVALID")


def _read_csv(source: object, fields: tuple[str, ...]) -> list[dict[str, str]]:
    stream, owned = _open_csv_source(source)
    try:
        reader = csv.DictReader(stream, strict=True)
        if tuple(reader.fieldnames or ()) != fields:
            raise CollectorError("COLLECTOR_CSV_HEADER_INVALID")
        rows: list[dict[str, str]] = []
        for row in reader:
            if len(rows) >= MAX_CSV_ROWS or None in row or any(type(value) is not str for value in row.values()):
                raise CollectorError("COLLECTOR_CSV_INVALID")
            _reject_sensitive_text(tuple(row.values()))
            rows.append(dict(row))
        if not rows:
            raise CollectorError("COLLECTOR_CSV_INVALID")
        return rows
    except (csv.Error, UnicodeError) as error:
        raise CollectorError("COLLECTOR_CSV_INVALID") from error
    finally:
        if owned:
            stream.close()


@_locked_mutation
def record_entitlements(capture: Path, source: object) -> CollectorResult:
    """Record the exact five qualification license observations."""

    try:
        capture = _checked_capture(capture)
        rows = _read_csv(source, ENTITLEMENT_FIELDS)
        if tuple(row["license_id"] for row in rows) != LICENSE_IDS:
            raise CollectorError("COLLECTOR_LICENSE_SET_INVALID")
        licenses: dict[str, object] = {}
        for row in rows:
            if row["availability"] not in ALLOWED_AVAILABILITY or row["checkout"] not in ALLOWED_CHECKOUT:
                raise CollectorError("COLLECTOR_LICENSE_OBSERVATION_INVALID")
            if (
                row["checkout"] == "observed-checked-out"
                and row["availability"] != "observed-available"
            ) or (
                row["availability"] == "observed-unavailable"
                and row["checkout"] != "not-checked-out"
            ):
                raise CollectorError("COLLECTOR_LICENSE_OBSERVATION_INVALID")
            licenses[row["license_id"]] = {
                "availability": row["availability"], "checkout": row["checkout"]
            }
        output = _raw_envelope()
        output.update({"qualification_expression": QUALIFICATION_EXPRESSION, "licenses": licenses})
        validate_entitlements_document(output)
        _write_exclusive(capture / "entitlements.json", output)
    except CollectorError as error:
        return _failure(error)
    return _result(facts={"relative_path": "entitlements.json", "trust_level": "raw-untrusted"})


def _portable_relative(value: str) -> str:
    lowered = value.casefold()
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if (
        not value
        or not value.isascii()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.is_absolute()
        or value.startswith(("//", "\\\\"))
        or "\\" in value
        or "/".join(posix.parts) != value
        or any(part in {"", ".", ".."} for part in posix.parts)
        or any(token in lowered for token in ("users/", "user-profile", "customer", "%userprofile%", "<user"))
        or any(":" in part for part in posix.parts)
    ):
        raise CollectorError("COLLECTOR_SENSITIVE_PATH_FORBIDDEN")
    return value


def _reference_row(row: Mapping[str, str]) -> dict[str, object]:
    guid = row["guid"].upper()
    if GUID_RE.fullmatch(guid) is None:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID")
    try:
        major, minor = int(row["major"]), int(row["minor"])
    except ValueError as error:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID") from error
    if major < 0 or minor < 0 or str(major) != row["major"] or str(minor) != row["minor"]:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID")
    if row["missing"] not in {"true", "false"}:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID")
    if row["architecture"] not in {"x64", "unknown"}:
        raise CollectorError("COLLECTOR_REFERENCE_FORBIDDEN")
    if row["source_class"] not in ALLOWED_SOURCE_CLASSES or row["root_kind"] not in ALLOWED_ROOT_KINDS:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID")
    if SAFE_NAME_RE.fullmatch(row["basename"]) is None or not row["display_name"] or len(row["display_name"]) > 160:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID")
    relative = _portable_relative(row["relative_path"])
    if PurePosixPath(relative).name != row["basename"] or SHA256_RE.fullmatch(row["path_sha256"]) is None:
        raise CollectorError("COLLECTOR_REFERENCE_INVALID")
    return {
        "stable_reference_id": stable_reference_id(guid, major, minor),
        "guid": guid,
        "major": major,
        "minor": minor,
        "display_name": row["display_name"],
        "missing": row["missing"] == "true",
        "architecture": row["architecture"],
        "source_class": row["source_class"],
        "root_kind": row["root_kind"],
        "basename": row["basename"],
        "relative_path": relative,
        "path_sha256": row["path_sha256"],
    }


def _validate_reference_item(item: object) -> None:
    keys = frozenset({
        "architecture", "basename", "display_name", "guid", "major", "minor", "missing",
        "path_sha256", "relative_path", "root_kind", "source_class", "stable_reference_id",
    })
    if type(item) is not dict or frozenset(item) != keys:
        raise CollectorError("COLLECTOR_REFERENCES_INVALID")
    guid, major, minor = item.get("guid"), item.get("major"), item.get("minor")
    if (
        type(guid) is not str
        or GUID_RE.fullmatch(guid) is None
        or guid != guid.upper()
        or type(major) is not int
        or type(minor) is not int
        or major < 0
        or minor < 0
        or item.get("stable_reference_id") != stable_reference_id(guid, major, minor)
        or type(item.get("missing")) is not bool
        or item.get("architecture") not in {"x64", "unknown"}
        or item.get("source_class") not in ALLOWED_SOURCE_CLASSES
        or item.get("root_kind") not in ALLOWED_ROOT_KINDS
        or type(item.get("display_name")) is not str
        or not item["display_name"]
        or len(item["display_name"]) > 160
        or type(item.get("basename")) is not str
        or SAFE_NAME_RE.fullmatch(item["basename"]) is None
        or type(item.get("relative_path")) is not str
        or PurePosixPath(_portable_relative(item["relative_path"])).name != item["basename"]
        or type(item.get("path_sha256")) is not str
        or SHA256_RE.fullmatch(item["path_sha256"]) is None
    ):
        raise CollectorError("COLLECTOR_REFERENCES_INVALID")
    _reject_sensitive_text(tuple(item.values()))


def _validate_references_document(document: object) -> dict[str, object]:
    try:
        if type(document) is not dict:
            raise CollectorError("COLLECTOR_REFERENCES_INVALID")
        _validate_raw_envelope(
            document, frozenset({"point_order", "observations"}), "COLLECTOR_REFERENCES_INVALID"
        )
        if document.get("point_order") != list(POINT_ORDER):
            raise CollectorError("COLLECTOR_REFERENCES_INVALID")
        observations = document.get("observations")
        if type(observations) is not list or len(observations) > len(POINT_ORDER):
            raise CollectorError("COLLECTOR_REFERENCES_INVALID")
        for index, observation in enumerate(observations):
            if (
                type(observation) is not dict
                or frozenset(observation) != frozenset({"point_id", "status", "references"})
                or observation.get("point_id") != POINT_ORDER[index]
                or observation.get("status") != "observed"
                or type(observation.get("references")) is not list
                or not observation["references"]
            ):
                raise CollectorError("COLLECTOR_REFERENCES_INVALID")
            references = observation["references"]
            for item in references:
                _validate_reference_item(item)
            identifiers = [item["stable_reference_id"] for item in references]
            if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
                raise CollectorError("COLLECTOR_REFERENCES_INVALID")
        return document
    except (CollectorError, TypeError, ValueError, KeyError) as error:
        if isinstance(error, CollectorError) and error.code == "COLLECTOR_REFERENCES_INVALID":
            raise
        raise CollectorError("COLLECTOR_REFERENCES_INVALID") from error


@_locked_mutation
def import_reference_csv(capture: Path, *, point: str, source: object) -> CollectorResult:
    """Append the next immutable Reference observation point."""

    try:
        capture = _checked_capture(capture)
        if point not in POINT_ORDER:
            raise CollectorError("COLLECTOR_POINT_INVALID")
        path = capture / "references.json"
        expected_sha256: str | None = None
        if path.exists():
            try:
                current_bytes = _read_bounded_file(path)
                expected_sha256 = hashlib.sha256(current_bytes).hexdigest()
                document = validate_references_document(
                    parse_canonical_json_bytes(current_bytes)
                )
            except CollectorError as error:
                raise CollectorError("COLLECTOR_REFERENCES_INVALID") from error
        else:
            document = _raw_envelope()
            document.update({"point_order": list(POINT_ORDER), "observations": []})
        observations = document["observations"]
        if not isinstance(observations, list) or len(observations) > len(POINT_ORDER):
            raise CollectorError("COLLECTOR_REFERENCES_INVALID")
        closed = [item.get("point_id") for item in observations if type(item) is dict]
        if point in closed:
            raise CollectorError("COLLECTOR_POINT_CLOSED")
        if len(observations) >= len(POINT_ORDER) or point != POINT_ORDER[len(observations)]:
            raise CollectorError("COLLECTOR_POINT_ORDER_INVALID")
        references = [_reference_row(row) for row in _read_csv(source, REFERENCE_FIELDS)]
        identifiers = [item["stable_reference_id"] for item in references]
        if len(identifiers) != len(set(identifiers)):
            raise CollectorError("COLLECTOR_REFERENCE_DUPLICATE")
        references.sort(key=lambda item: str(item["stable_reference_id"]))
        observations.append({"point_id": point, "status": "observed", "references": references})
        if path.exists():
            if expected_sha256 is None:
                raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(path))
            _replace_document(path, document, expected_sha256=expected_sha256)
        else:
            _write_exclusive(path, document)
    except CollectorError as error:
        return _failure(error)
    return _result(facts={"relative_path": "references.json", "point_id": point, "trust_level": "raw-untrusted"})


def _operator_index(path: Path) -> tuple[dict[str, object], str | None]:
    if not path.exists():
        document = _raw_envelope()
        document["records"] = []
        return document, None
    try:
        index_bytes = _read_bounded_file(path)
        index_sha256 = hashlib.sha256(index_bytes).hexdigest()
        document = parse_canonical_json_bytes(index_bytes)
        if type(document) is not dict:
            raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
        _validate_raw_envelope(document, frozenset({"records"}), "COLLECTOR_OPERATOR_INDEX_INVALID")
        records = document.get("records")
        if type(records) is not list:
            raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
        identifiers: list[str] = []
        image_bindings: list[tuple[dict[str, object], dict[str, object]]] = []
        record_keys = frozenset({
            "record_id", "category", "relative_path", "sha256", "size", "media_type",
            "redaction_review_record_ids", "redaction_review_record_sha256",
            "redaction_review_sidecar_sha256",
        })
        for record in records:
            if type(record) is not dict or frozenset(record) != record_keys:
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            record_id = record.get("record_id")
            relative = record.get("relative_path")
            if (
                type(record_id) is not str
                or RECORD_ID_RE.fullmatch(record_id) is None
                or record.get("category") not in ALLOWED_CATEGORIES
                or type(relative) is not str
                or not relative.startswith(f"operator-records/{record_id}/")
                or type(record.get("sha256")) is not str
                or SHA256_RE.fullmatch(record["sha256"]) is None
                or type(record.get("size")) is not int
                or record["size"] < 0
                or record.get("media_type") not in {"text", "image"}
                or type(record.get("redaction_review_record_ids")) is not list
                or type(record.get("redaction_review_record_sha256")) is not list
            ):
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            if _portable_relative(relative) != relative or PurePosixPath(relative).name == "index.json":
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            expected_id = "record-" + hashlib.sha256(
                (str(record["category"]) + "\0" + str(record["sha256"])).encode("ascii")
            ).hexdigest()[:24]
            if record_id != expected_id:
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            member = path.parents[1].joinpath(*PurePosixPath(relative).parts)
            data = _read_bounded_file(member)
            if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            if record["media_type"] == "image":
                if member.suffix.casefold() not in IMAGE_SUFFIXES:
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
                if member.suffix.casefold() == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
                if member.suffix.casefold() in {".jpg", ".jpeg"} and not (
                    data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
                ):
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
                review, sidecar_sha256 = _review_document(member, data)
                if review["review_record_ids"] != record["redaction_review_record_ids"]:
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
                if record.get("redaction_review_sidecar_sha256") != sidecar_sha256:
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
                image_bindings.append((record, review))
            elif (
                record["redaction_review_record_ids"]
                or record["redaction_review_record_sha256"]
                or record.get("redaction_review_sidecar_sha256") is not None
            ):
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            else:
                if member.suffix.casefold() not in TEXT_SUFFIXES:
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
                if member.suffix.casefold() == ".csv":
                    _validate_csv_record(data)
                else:
                    _validate_text_record(data)
            identifiers.append(record_id)
        if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
            raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
        by_id = {record["record_id"]: record for record in records}
        for image_record, review in image_bindings:
            review_sha256 = _validate_review_bindings(review, by_id)
            if image_record["redaction_review_record_sha256"] != review_sha256:
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
        return document, index_sha256
    except CollectorError as error:
        if error.code == "COLLECTOR_OPERATOR_INDEX_INVALID":
            raise
        raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID") from error


def _review_document(source: Path, image_data: bytes) -> tuple[dict[str, object], str]:
    review_path = source.with_name(source.stem + ".redaction-review.json")
    if not review_path.exists():
        raise CollectorError("COLLECTOR_REDACTION_REVIEW_REQUIRED")
    try:
        review_bytes = _read_bounded_file(review_path)
        document = parse_canonical_json_bytes(review_bytes)
    except CollectorError as error:
        if error.code in {"COLLECTOR_FILE_READ_ERROR", "COLLECTOR_JSON_INVALID", "COLLECTOR_NONCANONICAL_JSON"}:
            raise CollectorError("COLLECTOR_REDACTION_REVIEW_INVALID") from error
        raise
    expected = frozenset({"schema_version", "image_sha256", "review_record_ids", "decision"})
    if type(document) is not dict or frozenset(document) != expected:
        raise CollectorError("COLLECTOR_REDACTION_REVIEW_INVALID")
    reviewers = document.get("review_record_ids")
    if (
        document.get("schema_version") != 1
        or document.get("decision") != "approved-redacted"
        or document.get("image_sha256") != hashlib.sha256(image_data).hexdigest()
        or type(reviewers) is not list
        or len(reviewers) != 2
        or reviewers[0] == reviewers[1]
        or not all(type(item) is str and RECORD_ID_RE.fullmatch(item) for item in reviewers)
    ):
        raise CollectorError("COLLECTOR_REDACTION_REVIEW_INVALID")
    return document, hashlib.sha256(review_bytes).hexdigest()


def _validate_review_bindings(
    review: Mapping[str, object], records_by_id: Mapping[str, Mapping[str, object]]
) -> list[str]:
    reviewers = review.get("review_record_ids")
    if type(reviewers) is not list:
        raise CollectorError("COLLECTOR_REDACTION_REVIEW_INVALID")
    digests: list[str] = []
    for record_id in reviewers:
        record = records_by_id.get(record_id)
        if (
            type(record) is not dict
            or record.get("category") != "review"
            or record.get("media_type") != "text"
            or type(record.get("sha256")) is not str
            or SHA256_RE.fullmatch(record["sha256"]) is None
        ):
            raise CollectorError("COLLECTOR_REDACTION_REVIEW_INVALID")
        digests.append(record["sha256"])
    return digests


def validate_environment_document(document: Mapping[str, object]) -> None:
    """Pure strict validation for a recorded B28 environment document."""
    _validate_raw_envelope(document, frozenset({"windows", "catia", "vba", "pollution_scan"}), "COLLECTOR_CAPTURE_INVALID")
    windows = _exact_mapping(document.get("windows"), frozenset({"edition", "build", "architecture"}))
    catia = _exact_mapping(document.get("catia"), frozenset({"release", "revision", "build"}))
    vba = _exact_mapping(document.get("vba"), frozenset({"generation", "win64"}))
    pollution = _exact_mapping(document.get("pollution_scan"), frozenset({"B30", "x86", "VBA6", "Temp", "user-profile"}))
    if (
        type(windows.get("edition")) is not str or not windows["edition"]
        or type(windows.get("build")) is not str or not windows["build"]
        or windows.get("architecture") != "Win64"
        or catia != {"release": "V5-6R2018", "revision": "R28", "build": "B28"}
        or vba != {"generation": "VBA7", "win64": True}
        or any(value != "absent" for value in pollution.values())
    ):
        raise CollectorError("COLLECTOR_ENVIRONMENT_FORBIDDEN")


def validate_entitlements_document(document: Mapping[str, object]) -> None:
    """Pure strict validation for the five recorded license observations."""
    _validate_raw_envelope(document, frozenset({"qualification_expression", "licenses"}), "COLLECTOR_CAPTURE_INVALID")
    licenses = document.get("licenses")
    if (
        document.get("qualification_expression") != QUALIFICATION_EXPRESSION
        or type(licenses) is not dict or set(licenses) != set(LICENSE_IDS)
        or len(licenses) != len(LICENSE_IDS)
    ):
        raise CollectorError("COLLECTOR_LICENSE_SET_INVALID")
    for value in licenses.values():
        if (
            type(value) is not dict or frozenset(value) != {"availability", "checkout"}
            or value.get("availability") not in ALLOWED_AVAILABILITY
            or value.get("checkout") not in ALLOWED_CHECKOUT
            or (value.get("checkout") == "observed-checked-out" and value.get("availability") != "observed-available")
            or (value.get("availability") == "observed-unavailable" and value.get("checkout") != "not-checked-out")
        ):
            raise CollectorError("COLLECTOR_LICENSE_OBSERVATION_INVALID")


def validate_references_document(document: object) -> dict[str, object]:
    """Public pure validator shared by finalization and ingestion."""
    return _validate_references_document(document)


def validate_operator_index_files(files: Mapping[str, bytes]) -> None:
    """Validate the index against exactly its supplied bounded member bytes."""
    with tempfile.TemporaryDirectory(prefix="macro-menu-operator-index-") as temporary:
        root = Path(temporary)
        for path, data in files.items():
            if not path.startswith("operator-records/"):
                continue
            target = root.joinpath(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)

        document, _digest = _operator_index(root / "operator-records" / "index.json")
    records = document.get("records")
    if type(records) is not list:
        raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
    declared = {"operator-records/index.json"}
    for record in records:
        if type(record) is not dict or type(record.get("relative_path")) is not str:
            raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
        relative = record["relative_path"]
        declared.add(relative)
        if record.get("media_type") == "image":
            member = PurePosixPath(relative)
            declared.add(str(member.with_name(member.stem + ".redaction-review.json")))
    if {path for path in files if path.startswith("operator-records/")} != declared:
        raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")


@_locked_mutation
def add_operator_record(capture: Path, *, source: Path, category: str) -> CollectorResult:
    """Copy one bounded operator record into the private raw capture."""

    try:
        capture = _checked_capture(capture)
        source = Path(source)
        if category not in ALLOWED_CATEGORIES:
            raise CollectorError("COLLECTOR_OPERATOR_CATEGORY_INVALID")
        suffix = source.suffix.casefold()
        if suffix not in IMAGE_SUFFIXES | TEXT_SUFFIXES or SAFE_NAME_RE.fullmatch(source.name) is None:
            raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
        _reject_sensitive_text(source.name)
        data = _read_bounded_file(source)
        if suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
        if suffix in {".jpg", ".jpeg"} and not (data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")):
            raise CollectorError("COLLECTOR_OPERATOR_RECORD_TYPE_INVALID")
        if suffix in TEXT_SUFFIXES:
            if suffix == ".csv":
                _validate_csv_record(data)
            else:
                _validate_text_record(data)
        digest = hashlib.sha256(data).hexdigest()
        record_id = "record-" + hashlib.sha256((category + "\0" + digest).encode("ascii")).hexdigest()[:24]
        relative = f"operator-records/{record_id}/{source.name}"
        destination = capture.joinpath(*PurePosixPath(relative).parts)
        index_path = capture / "operator-records" / "index.json"
        index, expected_index_sha256 = _operator_index(index_path)
        records = index["records"]
        if not isinstance(records, list):
            raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
        if destination.exists() or any(type(item) is dict and item.get("record_id") == record_id for item in records):
            raise CollectorError("COLLECTOR_OPERATOR_RECORD_EXISTS")
        review: dict[str, object] | None = None
        review_sidecar_sha256: str | None = None
        review_record_sha256: list[str] = []
        if suffix in IMAGE_SUFFIXES:
            review, review_sidecar_sha256 = _review_document(source, data)
            review_record_sha256 = _validate_review_bindings(
                review,
                {item["record_id"]: item for item in records if type(item) is dict},
            )
        records_root = capture / "operator-records"
        if records_root.exists():
            _safe_absolute_path(records_root)
        else:
            try:
                records_root.mkdir(exist_ok=False)
            except FileExistsError as error:
                raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(records_root)) from error
            _safe_absolute_path(records_root)
        destination.parent.mkdir(exist_ok=False)
        _safe_absolute_path(destination.parent)
        try:
            backend = _ACTIVE_BACKEND.get()
            if backend is None:
                raise CollectorError("COLLECTOR_PATH_UNSAFE", str(capture))
            backend.write_exclusive(destination, data)
            if review is not None:
                review_name = source.stem + ".redaction-review.json"
                backend.write_exclusive(destination.parent / review_name, canonical_json_bytes(review))
            records.append({
                "record_id": record_id,
                "category": category,
                "relative_path": relative,
                "sha256": digest,
                "size": len(data),
                "media_type": "image" if suffix in IMAGE_SUFFIXES else "text",
                "redaction_review_record_ids": review["review_record_ids"] if review else [],
                "redaction_review_record_sha256": review_record_sha256,
                "redaction_review_sidecar_sha256": review_sidecar_sha256,
            })
            records.sort(key=lambda item: str(item["record_id"]) if type(item) is dict else "")
            if index_path.exists():
                if expected_index_sha256 is None:
                    raise CollectorError("COLLECTOR_UPDATE_CONFLICT", str(index_path))
                _replace_document(index_path, index, expected_sha256=expected_index_sha256)
            else:
                _write_exclusive(index_path, index)
        except Exception:
            try:
                if destination.parent.exists():
                    for child in destination.parent.iterdir():
                        child.unlink()
                    destination.parent.rmdir()
            except OSError:
                pass
            raise
    except CollectorError as error:
        return _failure(error)
    except OSError as error:
        return _failure(CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(source)))
    return _result(facts={"record_id": record_id, "relative_path": relative, "trust_level": "raw-untrusted"})
