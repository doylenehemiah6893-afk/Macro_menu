from __future__ import annotations

import hashlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import olefile

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
from oletools.olevba import VBA_Parser, decompress_stream

from .canonical import canonical_json_bytes
from .encoding import decode_vba
from .errors import SourceError, VerificationError
from .kit import _verify_file_map
from .model import BuildKitInspection, Diagnostic
from .reference_contract import (
    approved_reference_set,
    reference_companion,
    reference_contract_body_digest,
    resolved_reference_id,
)
from .target_evidence.schemas import (
    load_target_evidence_schemas,
    validate_target_document,
)


_MAX_PCODE_CAPTURE = 1024 * 1024
_MAX_REFERENCE_STREAM = 16 * 1024 * 1024
_MAX_CATVBA_FILE = 256 * 1024 * 1024
_MAX_EXPECTED_FILE = 16 * 1024 * 1024
_MAX_EXPECTED_ENTRIES = 4096
_MAX_EXPECTED_TOTAL = 256 * 1024 * 1024
_MAX_EXPECTED_DEPTH = 32
_FRX_WRAPPER_SIZE = 24
_FRX_WRAPPER_MAGIC = b"LB\x08\x00"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_KIT_ID = re.compile(r"^kit-[0-9a-f]{20}$")
_STABLE_ID = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")
_LIBID = re.compile(
    rb"\*\\[A-Za-z]\{"
    rb"(?P<guid>[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    rb"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\}#"
    rb"(?P<version>[0-9A-Fa-f.]+)#(?P<lcid>[0-9A-Fa-f]+)#"
    rb"(?P<location>[^#\x00\r\n]{0,2048})#"
    rb"(?P<description>[\x20-\x7e]{0,512})"
)
_GUID_TEXT = (
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_EXTRACTED_CLASS_BASE = re.compile(
    rf'^Attribute VB_Base = "0\{{{_GUID_TEXT}\}}"$', re.IGNORECASE
)
_EXTRACTED_FORM_BASE = re.compile(
    rf'^Attribute VB_Base = "0\{{{_GUID_TEXT}\}}\{{{_GUID_TEXT}\}}"$',
    re.IGNORECASE,
)
_KIT_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "kit_id",
        "identity_sha256",
        "manifest_digest",
        "target_build_required",
        "catvba_artifacts",
        "compile_status",
        "release_eligible",
    }
)
_EXPECTED_MAPPING_FIELDS = frozenset(
    {"file_sha256", "modules", "frx", "references", "hashes"}
)


@dataclass(frozen=True)
class PCodeSignal:
    status: str
    returncode: int | None
    stdout_sha256: str | None
    stderr_sha256: str | None
    diagnostic_only: bool = True


@dataclass(frozen=True)
class ReferenceVerification:
    status: str
    contract_body_digest: str | None
    observation_sha256: str | None
    matched_stable_ids: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    file_sha256: str
    streams: tuple[dict[str, str | int], ...]
    modules: tuple[dict[str, str], ...]
    references: tuple[dict[str, str], ...]
    pcode: PCodeSignal
    diagnostics: tuple[Diagnostic, ...]
    package_id: str | None = None
    reference_verification: ReferenceVerification = field(
        default_factory=lambda: ReferenceVerification(
            "unavailable", None, None, ()
        )
    )


@dataclass(frozen=True)
class _InputSnapshot:
    sha256: str
    device: int
    inode: int
    size: int
    mode: int
    modified_ns: int
    changed_ns: int
    data: bytes = field(repr=False, compare=False)


@dataclass(frozen=True)
class _Expected:
    package_id: str | None = None
    file_sha256: str | None = None
    modules: tuple[str, ...] | None = None
    frx: tuple[str, ...] | None = None
    references: tuple[str, ...] | None = None
    hashes: tuple[tuple[str, str], ...] = ()
    source_semantic_hashes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    frx_semantic_hashes: tuple[tuple[str, str], ...] = ()
    reference_contract: _ExpectedReferenceContract | None = None


@dataclass(frozen=True)
class _ExpectedReferenceDefinition:
    stable_id: str
    guid: str
    major: int
    minor: int
    allowed_names: tuple[str, ...]
    allowed_descriptions: tuple[str, ...]
    source_classification: str
    architecture: str
    release_provenance: str
    root_kind: str
    allowed_basenames: tuple[str, ...]
    allowed_relative_paths: tuple[str, ...]
    canonical_path_sha256: str | None


@dataclass(frozen=True)
class _ExpectedReferenceContract:
    body_digest: str
    definitions: tuple[_ExpectedReferenceDefinition, ...]
    allowed_root_kinds: tuple[str, ...]


class _ExpectedPackageSelectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _FormStorage:
    name: str
    path: str
    sha256: str
    designer_sha256: str


@dataclass(frozen=True)
class _FormSite:
    control_id: int
    class_index: int
    object_size: int


@dataclass(frozen=True)
class _ProcessCapture:
    returncode: int | None
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class _ExpectedFileSnapshot:
    identity: tuple[int, int, int, int, int, int]
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class _ExpectedDirectorySnapshot:
    identity: tuple[int, int, int, int, int, int]
    names: tuple[str, ...]


def _diag(
    code: str,
    path: str,
    message: str,
    **details: str | int | bool | list[str],
) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message, details=details)


def _stable_diagnostics(values: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    unique: dict[tuple[str, str, str], Diagnostic] = {}
    for diagnostic in values:
        unique.setdefault(
            (diagnostic.code, diagnostic.path, diagnostic.message), diagnostic
        )
    return tuple(sorted(unique.values()))


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _open_regular_nofollow(path: Path, error_code: str) -> tuple[int, os.stat_result]:
    """Open a regular file through descriptor-relative, no-follow ancestors."""
    if not all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ) or not os.supports_dir_fd or os.open not in os.supports_dir_fd:
        raise VerificationError(f"{error_code}: NOFOLLOW_UNAVAILABLE")
    absolute = _absolute(path)
    parts = absolute.parts
    if len(parts) < 2:
        raise VerificationError(error_code)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    try:
        directory = os.open(parts[0], directory_flags)
    except OSError as error:
        raise VerificationError(f"{error_code}: {type(error).__name__}") from error
    try:
        for component in parts[1:-1]:
            try:
                next_directory = os.open(
                    component, directory_flags, dir_fd=directory
                )
            except OSError as error:
                symlink_code = (
                    "AUDIT_INPUT_SYMLINK"
                    if error_code == "AUDIT_INPUT_INVALID"
                    else error_code
                )
                raise VerificationError(
                    f"{symlink_code}: {type(error).__name__}"
                ) from error
            os.close(directory)
            directory = next_directory
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=directory)
        except OSError as error:
            symlink_code = (
                "AUDIT_INPUT_SYMLINK"
                if error_code == "AUDIT_INPUT_INVALID"
                else error_code
            )
            raise VerificationError(
                f"{symlink_code}: {type(error).__name__}"
            ) from error
    finally:
        os.close(directory)
    try:
        opened = os.fstat(descriptor)
    except OSError as error:
        os.close(descriptor)
        raise VerificationError(f"{error_code}: {type(error).__name__}") from error
    if (
        not stat.S_ISREG(opened.st_mode)
    ):
        os.close(descriptor)
        raise VerificationError(error_code)
    return descriptor, opened


def _read_descriptor(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > maximum:
        raise VerificationError("AUDIT_INPUT_TOO_LARGE")
    return data


def _read_input_snapshot(path: Path) -> _InputSnapshot:
    descriptor, opened = _open_regular_nofollow(path, "AUDIT_INPUT_INVALID")
    try:
        if opened.st_size > _MAX_CATVBA_FILE:
            raise VerificationError("AUDIT_INPUT_TOO_LARGE")
        data = _read_descriptor(descriptor, _MAX_CATVBA_FILE)
        after = os.fstat(descriptor)
    except OSError as error:
        raise VerificationError(f"AUDIT_INPUT_INVALID: {type(error).__name__}") from error
    finally:
        os.close(descriptor)
    if (
        after.st_dev != opened.st_dev
        or after.st_ino != opened.st_ino
        or after.st_size != opened.st_size
        or after.st_mode != opened.st_mode
        or after.st_mtime_ns != opened.st_mtime_ns
        or after.st_ctime_ns != opened.st_ctime_ns
    ):
        raise VerificationError("AUDIT_INPUT_CHANGED")
    return _InputSnapshot(
        sha256=hashlib.sha256(data).hexdigest(),
        device=opened.st_dev,
        inode=opened.st_ino,
        size=opened.st_size,
        mode=stat.S_IMODE(opened.st_mode),
        modified_ns=opened.st_mtime_ns,
        changed_ns=opened.st_ctime_ns,
        data=data,
    )


def _write_readonly_copy(path: Path, data: bytes) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o444)


def _stream_record(ole: olefile.OleFileIO, entry: list[str]) -> dict[str, str | int]:
    digest = hashlib.sha256()
    size = 0
    stream = ole.openstream(entry)
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return {
        "path": unicodedata.normalize("NFC", "/".join(entry)),
        "size": size,
        "sha256": digest.hexdigest(),
    }


class _DirReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        if size < 0 or size > _MAX_REFERENCE_STREAM:
            raise ValueError("VBA dir record size exceeds the parser bound")
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("VBA dir record is truncated")
        value = self.data[self.offset : end]
        self.offset = end
        return value

    def u16(self) -> int:
        return int.from_bytes(self.read(2), "little")

    def u32(self) -> int:
        return int.from_bytes(self.read(4), "little")

    def sized(self) -> bytes:
        return self.read(self.u32())

    def fixed_sized(self, expected_size: int) -> bytes:
        size = self.u32()
        if size != expected_size:
            raise ValueError("VBA dir fixed record size is invalid")
        return self.read(size)

    def expect_u16(self, expected: int) -> None:
        if self.u16() != expected:
            raise ValueError("VBA dir record identifier is invalid")

    def expect_u32(self, expected: int) -> None:
        if self.u32() != expected:
            raise ValueError("VBA dir reserved value is invalid")


def _skip_project_information(reader: _DirReader) -> str:
    reader.expect_u16(0x0001)
    reader.fixed_sized(4)
    record_id = reader.u16()
    if record_id == 0x004A:
        reader.fixed_sized(4)
        record_id = reader.u16()
    if record_id != 0x0002:
        raise ValueError("VBA PROJECTLCID record is missing")
    reader.fixed_sized(4)
    reader.expect_u16(0x0014)
    reader.fixed_sized(4)
    reader.expect_u16(0x0003)
    codepage_bytes = reader.fixed_sized(2)
    codepage = int.from_bytes(codepage_bytes, "little")
    reader.expect_u16(0x0004)
    reader.sized()
    reader.expect_u16(0x0005)
    reader.sized()
    reader.expect_u16(0x0040)
    reader.sized()
    reader.expect_u16(0x0006)
    reader.sized()
    reader.expect_u16(0x003D)
    reader.sized()
    reader.expect_u16(0x0007)
    reader.fixed_sized(4)
    reader.expect_u16(0x0008)
    reader.fixed_sized(4)
    reader.expect_u16(0x0009)
    reader.expect_u32(4)
    reader.read(6)
    reader.expect_u16(0x000C)
    reader.sized()
    reader.expect_u16(0x003C)
    reader.sized()
    return f"cp{codepage}"


def _decode_reference_name(raw: bytes, codec: str) -> str:
    try:
        return raw.decode(codec, errors="strict")
    except (LookupError, UnicodeDecodeError) as error:
        raise ValueError("VBA reference name encoding is unsupported") from error


def _parse_reference_name(
    reader: _DirReader, codec: str
) -> tuple[str, int | None]:
    raw_name = reader.sized()
    name = _decode_reference_name(raw_name, codec)
    reserved_or_next = reader.u16()
    if reserved_or_next != 0x003E:
        return name, reserved_or_next
    unicode_name = reader.sized()
    if unicode_name:
        name = unicode_name.decode("utf-16le", errors="strict")
    return name, None


def _parse_reference_control(reader: _DirReader) -> bytes:
    reader.u32()
    reader.sized()
    reader.expect_u32(0)
    reader.expect_u16(0)
    reserved3 = reader.u16()
    if reserved3 == 0x0016:
        reader.sized()
        reserved3 = reader.u16()
        if reserved3 == 0x003E:
            reader.sized()
            reserved3 = reader.u16()
    if reserved3 != 0x0030:
        raise ValueError("VBA REFERENCECONTROL record is invalid")
    reader.u32()
    extended = reader.sized()
    reader.expect_u32(0)
    reader.expect_u16(0)
    reader.read(16 + 4)
    return extended


def _libid_record(
    name: str, libid: bytes
) -> dict[str, str]:
    match = _LIBID.fullmatch(libid)
    if match is None:
        raise ValueError("VBA reference LIBID is malformed")
    return {
        "name": name,
        "guid": "{" + match.group("guid").decode("ascii").upper() + "}",
        "version": match.group("version").decode("ascii"),
        "description": match.group("description").decode("ascii").strip(),
        "libid_sha256": hashlib.sha256(libid).hexdigest(),
    }


def _parse_logical_references(decompressed: bytes) -> tuple[dict[str, str], ...]:
    reader = _DirReader(decompressed)
    codec = _skip_project_information(reader)
    records: list[dict[str, str]] = []
    pending_name = ""
    pending_original: bytes | None = None
    record_id = reader.u16()
    while record_id != 0x000F:
        if record_id == 0x0016:
            pending_name, next_id = _parse_reference_name(reader, codec)
            record_id = reader.u16() if next_id is None else next_id
        if record_id == 0x0033:
            pending_original = reader.sized()
            record_id = reader.u16()
            if record_id != 0x002F:
                raise ValueError("REFERENCEORIGINAL is not followed by CONTROL")
        if record_id == 0x002F:
            extended = _parse_reference_control(reader)
            records.append(
                _libid_record(pending_name, pending_original or extended)
            )
        elif record_id == 0x000D:
            reader.u32()
            libid = reader.sized()
            reader.expect_u32(0)
            reader.expect_u16(0)
            records.append(_libid_record(pending_name, libid))
        elif record_id == 0x000E:
            reader.u32()
            absolute = reader.sized()
            reader.sized()
            major = reader.u32()
            minor = reader.u16()
            record = _libid_record(pending_name, absolute)
            if record["version"] != f"{major}.{minor}":
                raise ValueError("VBA project reference version disagrees with LIBID")
            records.append(record)
        else:
            raise ValueError("VBA reference record type is unsupported")
        pending_name = ""
        pending_original = None
        record_id = reader.u16()
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item["name"],
                item["guid"],
                item["version"],
                item["description"],
            ),
        )
    )


def _reference_records(
    compressed: bytes, diagnostics: list[Diagnostic]
) -> tuple[dict[str, str], ...]:
    if len(compressed) > _MAX_REFERENCE_STREAM:
        diagnostics.append(
            _diag(
                "REFERENCE_PARSE_FAILED",
                "vba/dir",
                "VBA reference metadata exceeds the bounded parser limit",
            )
        )
        return ()
    try:
        decompressed = bytes(decompress_stream(bytearray(compressed)))
        if len(decompressed) > _MAX_REFERENCE_STREAM:
            raise ValueError("decompressed VBA dir metadata exceeds the parser bound")
        records = _parse_logical_references(decompressed)
        if not records:
            raise ValueError("VBA dir contains no logical reference records")
        return records
    except Exception as error:
        diagnostics.append(
            _diag(
                "REFERENCE_PARSE_FAILED",
                "vba/dir",
                "VBA reference records could not be parsed structurally",
                error_type=type(error).__name__,
            )
        )
        return ()


def _semantic_stream_hash(
    records: list[tuple[str, int, str]],
) -> str:
    digest = hashlib.sha256()
    for path, size, stream_sha256 in sorted(records):
        encoded = path.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(stream_sha256))
    return digest.hexdigest()


_FORM_PARENT_CLASSES = frozenset({7, 14, 57})
_FORM_OBJECT_CLASSES = frozenset({12, 17, 21, 23, 24, 25, 27, 47})
_FORM_CLASSES = _FORM_PARENT_CLASSES | _FORM_OBJECT_CLASSES
_STD_FONT_GUID = bytes.fromhex("0352e30b918fce119de300aa004bb851")
_TEXT_PROPS_GUID = bytes.fromhex("2009c2af4edace11b94300aa006887b4")
_PICTURE_GUID = bytes.fromhex("0452e30b918fce119de300aa004bb851")


class _FormByteReader:
    """Bounded MS-OFORMS reader retaining bytes except documented padding."""

    def __init__(self, data: bytes, path: str) -> None:
        self.data = data
        self.normalized = bytearray(data)
        self.path = path
        self.pos = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError(f"{self.path}: truncated form structure")
        start = self.pos
        self.pos += size
        return self.data[start : self.pos]

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), "little")

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def u64(self) -> int:
        return int.from_bytes(self.take(8), "little")

    def expect(self, value: bytes, label: str) -> None:
        if self.take(len(value)) != value:
            raise ValueError(f"{self.path}: invalid {label}")

    def align(self, start: int, boundary: int) -> None:
        padding = (-(self.pos - start)) % boundary
        if not padding:
            return
        end = self.pos + padding
        if end > len(self.data):
            raise ValueError(f"{self.path}: truncated form padding")
        self.normalized[self.pos : end] = b"\x00" * padding
        self.pos = end

    def count_bytes(self) -> int:
        count = self.u32() & 0x7FFF_FFFF
        if count > len(self.data) - self.pos:
            raise ValueError(f"{self.path}: form string exceeds stream bounds")
        return count

    def form_string(self, count: int) -> None:
        start = self.pos
        self.take(count)
        self.align(start, 4)

    def require_end(self) -> None:
        if self.pos != len(self.data):
            raise ValueError(f"{self.path}: unconsumed form stream bytes")


def _has(mask: int, bit: int) -> bool:
    return bool(mask & (1 << bit))


def _require_mask(mask: int, allowed: int, path: str) -> None:
    if mask & ~allowed:
        raise ValueError(
            f"{path}: unsupported or reserved property mask bits "
            f"0x{mask & ~allowed:x}"
        )


def _take_if(reader: _FormByteReader, mask: int, bit: int, size: int) -> None:
    if _has(mask, bit):
        reader.take(size)


def _aligned_take_if(
    reader: _FormByteReader,
    mask: int,
    bit: int,
    start: int,
    alignment: int,
    size: int,
) -> bytes | None:
    if not _has(mask, bit):
        return None
    reader.align(start, alignment)
    return reader.take(size)


def _expect_marker(value: bytes | None, marker: bytes, path: str) -> None:
    if value != marker:
        raise ValueError(f"{path}: invalid persisted property marker")


def _parse_text_props(reader: _FormByteReader) -> None:
    reader.expect(b"\x00\x02", "TextProps version")
    block_size = reader.u16()
    if block_size < 4:
        raise ValueError(f"{reader.path}: invalid TextProps block size")
    block_start = reader.pos
    mask = reader.u32()
    _require_mask(mask, 0xF7, reader.path)
    data_start = reader.pos
    font_name = reader.count_bytes() if _has(mask, 0) else 0
    _take_if(reader, mask, 1, 4)
    _take_if(reader, mask, 2, 4)
    _take_if(reader, mask, 4, 1)
    _take_if(reader, mask, 5, 1)
    _take_if(reader, mask, 6, 1)
    _aligned_take_if(reader, mask, 7, data_start, 2, 2)
    reader.align(data_start, 4)
    if _has(mask, 0):
        reader.form_string(font_name)
    if reader.pos - block_start != block_size:
        raise ValueError(f"{reader.path}: invalid TextProps block boundary")


def _parse_guid_and_picture(reader: _FormByteReader) -> None:
    reader.expect(_PICTURE_GUID, "picture GUID")
    if reader.u32() != 0x0000746C:
        raise ValueError(f"{reader.path}: invalid picture preamble")
    reader.take(reader.u32())


def _parse_guid_and_font(reader: _FormByteReader) -> None:
    guid = reader.take(16)
    if guid == _STD_FONT_GUID:
        if reader.u8() != 1:
            raise ValueError(f"{reader.path}: invalid StdFont version")
        reader.take(2 + 1 + 2 + 4)
        face_length = reader.u8()
        if face_length >= 32:
            raise ValueError(f"{reader.path}: invalid StdFont face length")
        reader.take(face_length)
    elif guid == _TEXT_PROPS_GUID:
        _parse_text_props(reader)
    else:
        raise ValueError(f"{reader.path}: unsupported form font GUID")


def _parse_form_site(reader: _FormByteReader) -> _FormSite:
    if reader.u16() != 0:
        raise ValueError(f"{reader.path}: invalid form site version")
    block_size = reader.u16()
    if block_size < 4:
        raise ValueError(f"{reader.path}: invalid form site size")
    block_start = reader.pos
    mask = reader.u32()
    _require_mask(mask, 0x7BFF, reader.path)
    data_start = reader.pos
    name_count = reader.count_bytes() if _has(mask, 0) else 0
    tag_count = reader.count_bytes() if _has(mask, 1) else 0
    control_id = reader.u32() if _has(mask, 2) else 0
    _take_if(reader, mask, 3, 4)
    _take_if(reader, mask, 4, 4)
    object_size = reader.u32() if _has(mask, 5) else 0
    _take_if(reader, mask, 6, 2)
    class_index = reader.u16() if _has(mask, 7) else 0x7FFF
    _take_if(reader, mask, 9, 2)
    string_counts: dict[int, int] = {}
    for bit in (11, 12, 13, 14):
        if _has(mask, bit):
            reader.align(data_start, 4)
            string_counts[bit] = reader.count_bytes()
    reader.align(data_start, 4)
    if _has(mask, 0):
        reader.form_string(name_count)
    if _has(mask, 1):
        reader.form_string(tag_count)
    _take_if(reader, mask, 8, 8)
    for bit in (11, 12, 13, 14):
        if _has(mask, bit):
            reader.form_string(string_counts[bit])
    if reader.pos - block_start != block_size:
        raise ValueError(f"{reader.path}: invalid form site boundary")
    if class_index not in _FORM_CLASSES:
        raise ValueError(f"{reader.path}: unsupported control class {class_index}")
    return _FormSite(
        control_id=control_id,
        class_index=class_index,
        object_size=object_size,
    )


def _parse_design_extender(reader: _FormByteReader) -> None:
    reader.expect(b"\x00\x02", "DesignExtender version")
    block_size = reader.u16()
    if block_size < 4:
        raise ValueError(f"{reader.path}: invalid DesignExtender block size")
    block_start = reader.pos
    mask = reader.u32()
    _require_mask(mask, 0x1F, reader.path)
    data_start = reader.pos
    for bit in (0, 1, 2):
        _take_if(reader, mask, bit, 4)
    for bit in (3, 4):
        _take_if(reader, mask, bit, 1)
    reader.align(data_start, 4)
    if reader.pos - block_start != block_size:
        raise ValueError(f"{reader.path}: invalid DesignExtender block boundary")


def _parse_form_stream(data: bytes, path: str) -> tuple[bytes, tuple[_FormSite, ...]]:
    reader = _FormByteReader(data, path)
    reader.expect(b"\x00\x04", "FormControl version")
    block_size = reader.u16()
    if block_size < 4:
        raise ValueError(f"{path}: invalid FormControl block size")
    block_start = reader.pos
    mask = reader.u32()
    allowed = sum(1 << bit for bit in (*range(1, 4), *range(6, 14), *range(15, 28)))
    _require_mask(mask, allowed, path)
    data_start = reader.pos
    _take_if(reader, mask, 1, 4)
    _take_if(reader, mask, 2, 4)
    _take_if(reader, mask, 3, 4)
    boolean_properties = reader.u32() if _has(mask, 6) else 0
    _take_if(reader, mask, 7, 1)
    _take_if(reader, mask, 8, 1)
    _take_if(reader, mask, 9, 1)
    _aligned_take_if(reader, mask, 13, data_start, 4, 4)
    mouse_icon = _aligned_take_if(reader, mask, 15, data_start, 2, 2)
    if mouse_icon is not None:
        _expect_marker(mouse_icon, b"\xff\xff", path)
    _take_if(reader, mask, 16, 1)
    _take_if(reader, mask, 17, 1)
    _aligned_take_if(reader, mask, 18, data_start, 4, 4)
    caption_count = 0
    if _has(mask, 19):
        reader.align(data_start, 4)
        caption_count = reader.count_bytes()
    font = _aligned_take_if(reader, mask, 20, data_start, 2, 2)
    if font is not None:
        _expect_marker(font, b"\xff\xff", path)
    picture = _aligned_take_if(reader, mask, 21, data_start, 2, 2)
    if picture is not None:
        _expect_marker(picture, b"\xff\xff", path)
    _aligned_take_if(reader, mask, 22, data_start, 4, 4)
    _take_if(reader, mask, 23, 1)
    _take_if(reader, mask, 25, 1)
    _aligned_take_if(reader, mask, 26, data_start, 4, 4)
    _aligned_take_if(reader, mask, 27, data_start, 4, 4)
    reader.align(data_start, 4)
    _take_if(reader, mask, 10, 8)
    _take_if(reader, mask, 11, 8)
    _take_if(reader, mask, 12, 8)
    if _has(mask, 19):
        reader.form_string(caption_count)
    if reader.pos - block_start != block_size:
        raise ValueError(f"{path}: invalid FormControl block boundary")
    if _has(mask, 15):
        _parse_guid_and_picture(reader)
    if _has(mask, 20):
        _parse_guid_and_font(reader)
    if _has(mask, 21):
        _parse_guid_and_picture(reader)

    if not (boolean_properties & (1 << 15)):
        class_count = reader.u16()
        if class_count:
            raise ValueError(f"{path}: non-cached form classes are unsupported")
    count_sites = reader.u32()
    count_bytes = reader.u32()
    if count_sites > 4096 or count_bytes > len(data) - reader.pos:
        raise ValueError(f"{path}: form site table exceeds parser bounds")
    sites_start = reader.pos
    represented = 0
    while represented < count_sites:
        reader.u8()
        type_or_count = reader.u8()
        if type_or_count & 0x80:
            represented += type_or_count & 0x7F
            if not (type_or_count & 0x7F) or reader.u8() != 1:
                raise ValueError(f"{path}: invalid form site type run")
        else:
            represented += 1
            if type_or_count != 1:
                raise ValueError(f"{path}: invalid form site type")
        if represented > count_sites:
            raise ValueError(f"{path}: form site run exceeds declared count")
    reader.align(sites_start, 4)
    sites = tuple(_parse_form_site(reader) for _ in range(count_sites))
    if reader.pos - sites_start != count_bytes:
        raise ValueError(f"{path}: invalid form site table boundary")
    site_ids = [site.control_id for site in sites]
    if any(not control_id for control_id in site_ids) or len(site_ids) != len(
        set(site_ids)
    ):
        raise ValueError(f"{path}: form site IDs are missing or duplicated")
    if boolean_properties & (1 << 14):
        _parse_design_extender(reader)
    reader.require_end()
    return bytes(reader.normalized), sites


def _parse_control_header(
    reader: _FormByteReader, label: str, mask_bytes: int
) -> tuple[int, int, int]:
    reader.expect(b"\x00\x02", f"{label} version")
    block_size = reader.u16()
    if block_size < mask_bytes:
        raise ValueError(f"{reader.path}: invalid {label} block size")
    block_start = reader.pos
    mask = reader.u64() if mask_bytes == 8 else reader.u32()
    return block_size, block_start, mask


def _finish_control_block(
    reader: _FormByteReader, block_size: int, block_start: int, label: str
) -> None:
    if reader.pos - block_start != block_size:
        raise ValueError(f"{reader.path}: invalid {label} block boundary")


def _parse_image_control(reader: _FormByteReader) -> None:
    block_size, block_start, mask = _parse_control_header(reader, "Image", 4)
    _require_mask(mask, 0x7FFC, reader.path)
    data_start = reader.pos
    _take_if(reader, mask, 3, 4)
    _take_if(reader, mask, 4, 4)
    for bit in (5, 6, 7, 8):
        _take_if(reader, mask, bit, 1)
    picture = _aligned_take_if(reader, mask, 10, data_start, 2, 2)
    if picture is not None:
        _expect_marker(picture, b"\xff\xff", reader.path)
    _take_if(reader, mask, 11, 1)
    _aligned_take_if(reader, mask, 13, data_start, 4, 4)
    mouse = _aligned_take_if(reader, mask, 14, data_start, 2, 2)
    if mouse is not None:
        _expect_marker(mouse, b"\xff\xff", reader.path)
    reader.align(data_start, 4)
    _take_if(reader, mask, 9, 8)
    _finish_control_block(reader, block_size, block_start, "Image")
    if _has(mask, 10):
        _parse_guid_and_picture(reader)
    if _has(mask, 14):
        _parse_guid_and_picture(reader)


def _parse_command_button(reader: _FormByteReader) -> None:
    block_size, block_start, mask = _parse_control_header(
        reader, "CommandButton", 4
    )
    _require_mask(mask, 0x7FF, reader.path)
    data_start = reader.pos
    for bit in (0, 1, 2):
        _take_if(reader, mask, bit, 4)
    caption_count = reader.count_bytes() if _has(mask, 3) else 0
    _take_if(reader, mask, 4, 4)
    _take_if(reader, mask, 6, 1)
    picture = _aligned_take_if(reader, mask, 7, data_start, 2, 2)
    if picture is not None:
        _expect_marker(picture, b"\xff\xff", reader.path)
    _aligned_take_if(reader, mask, 8, data_start, 2, 2)
    mouse = _aligned_take_if(reader, mask, 10, data_start, 2, 2)
    if mouse is not None:
        _expect_marker(mouse, b"\xff\xff", reader.path)
    reader.align(data_start, 4)
    if _has(mask, 3):
        reader.form_string(caption_count)
    _take_if(reader, mask, 5, 8)
    _finish_control_block(reader, block_size, block_start, "CommandButton")
    if _has(mask, 7):
        _parse_guid_and_picture(reader)
    if _has(mask, 10):
        _parse_guid_and_picture(reader)
    _parse_text_props(reader)


def _parse_label_control(reader: _FormByteReader) -> None:
    block_size, block_start, mask = _parse_control_header(reader, "Label", 4)
    _require_mask(mask, 0x1FFF, reader.path)
    data_start = reader.pos
    for bit in (0, 1, 2):
        _take_if(reader, mask, bit, 4)
    caption_count = reader.count_bytes() if _has(mask, 3) else 0
    _take_if(reader, mask, 4, 4)
    _take_if(reader, mask, 6, 1)
    _aligned_take_if(reader, mask, 7, data_start, 4, 4)
    _aligned_take_if(reader, mask, 8, data_start, 2, 2)
    _aligned_take_if(reader, mask, 9, data_start, 2, 2)
    picture = _aligned_take_if(reader, mask, 10, data_start, 2, 2)
    if picture is not None:
        _expect_marker(picture, b"\xff\xff", reader.path)
    _aligned_take_if(reader, mask, 11, data_start, 2, 2)
    mouse = _aligned_take_if(reader, mask, 12, data_start, 2, 2)
    if mouse is not None:
        _expect_marker(mouse, b"\xff\xff", reader.path)
    reader.align(data_start, 4)
    if _has(mask, 3):
        reader.form_string(caption_count)
    _take_if(reader, mask, 5, 8)
    _finish_control_block(reader, block_size, block_start, "Label")
    if _has(mask, 10):
        _parse_guid_and_picture(reader)
    if _has(mask, 12):
        _parse_guid_and_picture(reader)
    _parse_text_props(reader)


def _parse_scroll_bar(reader: _FormByteReader) -> None:
    block_size, block_start, mask = _parse_control_header(reader, "ScrollBar", 4)
    _require_mask(mask, 0x1_F0FF, reader.path)
    data_start = reader.pos
    for bit in (0, 1, 2):
        _take_if(reader, mask, bit, 4)
    _take_if(reader, mask, 4, 1)
    for bit in (5, 6, 7, 9, 10, 11, 12, 13):
        _aligned_take_if(reader, mask, bit, data_start, 4, 4)
    _aligned_take_if(reader, mask, 14, data_start, 2, 2)
    _aligned_take_if(reader, mask, 15, data_start, 4, 4)
    mouse = _aligned_take_if(reader, mask, 16, data_start, 2, 2)
    if mouse is not None:
        _expect_marker(mouse, b"\xff\xff", reader.path)
    reader.align(data_start, 4)
    _take_if(reader, mask, 3, 8)
    _finish_control_block(reader, block_size, block_start, "ScrollBar")
    if _has(mask, 16):
        _parse_guid_and_picture(reader)


def _parse_morph_control(reader: _FormByteReader, class_index: int) -> None:
    block_size, block_start, mask = _parse_control_header(reader, "MorphData", 8)
    allowed = sum(1 << bit for bit in (*range(0, 19), *range(20, 30), 31, 32))
    _require_mask(mask, allowed, reader.path)
    if not _has(mask, 31):
        raise ValueError(f"{reader.path}: MorphData reserved marker is missing")
    data_start = reader.pos
    for bit in (0, 1, 2, 3):
        _take_if(reader, mask, bit, 4)
    for bit in (4, 5, 6, 7):
        _take_if(reader, mask, bit, 1)
    _aligned_take_if(reader, mask, 9, data_start, 2, 2)
    _aligned_take_if(reader, mask, 10, data_start, 4, 4)
    for bit in (11, 12, 13, 14, 15):
        _aligned_take_if(reader, mask, bit, data_start, 2, 2)
    column_count = (
        int.from_bytes(reader.data[reader.pos - 2 : reader.pos], "little")
        if _has(mask, 15)
        else 0
    )
    for bit in (16, 17, 18, 20, 21):
        _take_if(reader, mask, bit, 1)
    value_count = 0
    caption_count = 0
    group_count = 0
    if _has(mask, 22):
        reader.align(data_start, 4)
        value_count = reader.count_bytes()
    if _has(mask, 23):
        reader.align(data_start, 4)
        caption_count = reader.count_bytes()
    for bit in (24, 25, 26):
        _aligned_take_if(reader, mask, bit, data_start, 4, 4)
    mouse = _aligned_take_if(reader, mask, 27, data_start, 2, 2)
    if mouse is not None:
        _expect_marker(mouse, b"\xff\xff", reader.path)
    picture = _aligned_take_if(reader, mask, 28, data_start, 2, 2)
    if picture is not None:
        _expect_marker(picture, b"\xff\xff", reader.path)
    _aligned_take_if(reader, mask, 29, data_start, 2, 2)
    if _has(mask, 32):
        reader.align(data_start, 4)
        group_count = reader.count_bytes()
    reader.align(data_start, 4)
    _take_if(reader, mask, 8, 8)
    if _has(mask, 22):
        reader.form_string(value_count)
    if _has(mask, 23):
        reader.form_string(caption_count)
    if _has(mask, 32):
        reader.form_string(group_count)
    _finish_control_block(reader, block_size, block_start, "MorphData")
    if _has(mask, 27):
        _parse_guid_and_picture(reader)
    if _has(mask, 28):
        _parse_guid_and_picture(reader)
    _parse_text_props(reader)
    if column_count and class_index not in {24, 25}:
        raise ValueError(f"{reader.path}: column info on unsupported control class")
    for _ in range(column_count):
        reader.expect(b"\x00\x02", "column info version")
        info_size = reader.u16()
        info_start = reader.pos
        info_mask = reader.u32()
        _require_mask(info_mask, 1, reader.path)
        _take_if(reader, info_mask, 0, 4)
        if reader.pos - info_start != info_size:
            raise ValueError(f"{reader.path}: invalid column info boundary")


def _parse_object_stream(
    data: bytes, sites: tuple[_FormSite, ...], path: str
) -> bytes:
    reader = _FormByteReader(data, path)
    parsers = {
        12: _parse_image_control,
        17: _parse_command_button,
        21: _parse_label_control,
        47: _parse_scroll_bar,
    }
    for site in sites:
        if site.class_index in _FORM_PARENT_CLASSES:
            continue
        start = reader.pos
        if site.class_index in {23, 24, 25, 27}:
            _parse_morph_control(reader, site.class_index)
        else:
            parser = parsers.get(site.class_index)
            if parser is None:
                raise ValueError(
                    f"{path}: unsupported control class {site.class_index}"
                )
            parser(reader)
        if site.object_size and reader.pos - start != site.object_size:
            raise ValueError(f"{path}: invalid persisted control size")
    reader.require_end()
    return bytes(reader.normalized)


def _embedded_storage_name(control_id: int) -> str:
    return f"i0{control_id}" if control_id < 10 else f"i{control_id}"


def _form_designer_sha256(
    data: bytes,
    *,
    expected_frx_name: str | None = None,
    declared_encoding: str | None = None,
) -> str:
    try:
        text = decode_vba(data, declared_encoding).text
    except SourceError as error:
        raise ValueError("Form designer text encoding is invalid") from error
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    attributes = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (
            match := re.match(
                r'^\s*Attribute\s+VB_Name\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*$',
                line,
                re.IGNORECASE,
            )
        )
    ]
    attribute_index = attributes[0][0] if attributes else None
    blob_records: list[tuple[str, str]] = []
    for line in lines[:attribute_index]:
        if not re.match(r"^\s*OleObjectBlob\b", line, re.IGNORECASE):
            continue
        match = re.match(
            r'^\s*OleObjectBlob\s*=\s*"([^"/\\]+\.frx)"\s*:\s*([0-9A-Fa-f]+)\s*$',
            line,
            re.IGNORECASE,
        )
        if match is None:
            raise ValueError("Form designer OleObjectBlob is malformed")
        blob_records.append((unicodedata.normalize("NFC", match.group(1)), match.group(2)))
    if expected_frx_name is None:
        if attributes or blob_records:
            raise ValueError("internal Form designer contains export-only records")
    else:
        expected_name = unicodedata.normalize("NFC", expected_frx_name)
        expected_stem = PurePosixPath(expected_name).stem
        if (
            len(attributes) != 1
            or attributes[0][1] != expected_stem
            or blob_records != [(expected_name, "0000")]
        ):
            raise ValueError("Form designer identity does not match its FRM/FRX bundle")
    if attribute_index is not None:
        lines = lines[:attribute_index]
    normalized = [
        line.rstrip()
        for line in lines
        if not re.match(
            r"^\s*(?:OleObjectBlob|TypeInfoVer)\s*=", line, re.IGNORECASE
        )
    ]
    while normalized and not normalized[0]:
        normalized.pop(0)
    while normalized and not normalized[-1]:
        normalized.pop()
    if (
        not normalized
        or normalized[0].strip() != "VERSION 5.00"
        or normalized[-1].strip() != "End"
        or sum(
            bool(re.match(r"^\s*Begin\s+", line, re.IGNORECASE))
            for line in normalized
        )
        != 1
    ):
        raise ValueError("Form designer header is incomplete")
    begin_match = next(
        re.match(
            r"^\s*Begin\s+\{[0-9A-Fa-f-]+\}\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
            line,
        )
        for line in normalized
        if re.match(r"^\s*Begin\s+", line, re.IGNORECASE)
    )
    if (
        begin_match is None
        or (
            expected_frx_name is not None
            and begin_match.group(1) != PurePosixPath(expected_frx_name).stem
        )
    ):
        raise ValueError("Form designer Begin identity is invalid")
    canonical = ("\n".join(normalized) + "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _combined_form_sha256(payload_sha256: str, designer_sha256: str) -> str:
    digest = hashlib.sha256(b"catvba-form-semantic-v1\x00")
    digest.update(bytes.fromhex(payload_sha256))
    digest.update(bytes.fromhex(designer_sha256))
    return digest.hexdigest()


def _validate_compobj(data: bytes, path: str, *, nested: bool) -> None:
    if len(data) > 4096 or len(data) < 32:
        raise ValueError(f"{path}: invalid CompObj stream size")
    if data[:12] != bytes.fromhex("0100feff030a0000ffffffff"):
        raise ValueError(f"{path}: invalid CompObj header")
    clsid = data[12:28]
    form_clsid = bytes.fromhex("f0692ac6dc16ce119e9800aa00574a4f")
    frame_clsid = bytes.fromhex("2020186e60f4ce119bcd00aa00608e01")
    if clsid not in {b"\x00" * 16, form_clsid, frame_clsid}:
        raise ValueError(f"{path}: unexpected CompObj class")
    reader = _FormByteReader(data, path)
    reader.pos = 28

    def counted_ascii(label: str) -> bytes:
        value = reader.take(reader.u32())
        if value and (not value.endswith(b"\x00") or not value[:-1].isascii()):
            raise ValueError(f"{path}: invalid CompObj {label}")
        return value

    user_type = counted_ascii("user type")
    clipboard = counted_ascii("clipboard format")
    progid = counted_ascii("ProgID")
    if clipboard != b"Embedded Object\x00":
        raise ValueError(f"{path}: invalid CompObj clipboard format")
    if nested:
        if (
            clsid != frame_clsid
            or user_type != b"Microsoft Forms 2.0 Frame\x00"
            or progid != b"Forms.Frame.1\x00"
        ):
            raise ValueError(f"{path}: invalid logical Frame CompObj identity")
    elif (
        user_type != b"Microsoft Forms 2.0 Form\x00"
        or (clsid, progid)
        not in {
            (b"\x00" * 16, b""),
            (form_clsid, b"Forms.Form.1\x00"),
        }
    ):
        raise ValueError(f"{path}: invalid logical Form CompObj identity")
    if reader.take(16) != bytes.fromhex("f439b271000000000000000000000000"):
        raise ValueError(f"{path}: invalid CompObj trailer")
    reader.require_end()


def _form_semantic_sha256(ole: Any, prefix: tuple[str, ...]) -> str:
    entries = [
        tuple(entry)
        for entry in ole.listdir(streams=True, storages=False)
        if tuple(entry[: len(prefix)]) == prefix and len(entry) > len(prefix)
    ]
    relative = {entry[len(prefix) :] for entry in entries}
    visited: set[tuple[str, ...]] = set()
    ignored: set[tuple[str, ...]] = set()
    records: list[tuple[str, int, str]] = []
    visited_storages: set[tuple[str, ...]] = set()

    def stream(parts: tuple[str, ...]) -> bytes:
        full = list(prefix + parts)
        try:
            return ole.openstream(full).read()
        except Exception as error:
            raise ValueError(f"missing form stream {'/'.join(parts)}") from error

    def walk(storage: tuple[str, ...]) -> None:
        if storage in visited_storages:
            raise ValueError("form storage is referenced more than once")
        visited_storages.add(storage)
        f_path = storage + ("f",)
        o_path = storage + ("o",)
        if f_path not in relative or o_path not in relative:
            raise ValueError("form storage is missing required f/o streams")
        f_data = stream(f_path)
        normalized_f, sites = _parse_form_stream(f_data, "/".join(f_path))
        o_data = stream(o_path)
        normalized_o = _parse_object_stream(o_data, sites, "/".join(o_path))
        for path_parts, raw, normalized in (
            (f_path, f_data, normalized_f),
            (o_path, o_data, normalized_o),
        ):
            visited.add(path_parts)
            records.append(
                (
                    unicodedata.normalize("NFC", "/".join(path_parts)),
                    len(raw),
                    hashlib.sha256(normalized).hexdigest(),
                )
            )
        compobj = storage + ("\x01CompObj",)
        if compobj in relative:
            _validate_compobj(
                stream(compobj), "/".join(compobj), nested=bool(storage)
            )
            ignored.add(compobj)
        for site in sites:
            if site.class_index in _FORM_PARENT_CLASSES:
                child = storage + (_embedded_storage_name(site.control_id),)
                walk(child)

    walk(())
    vbframe = ("\x03VBFrame",)
    if vbframe in relative:
        ignored.add(vbframe)
    unexpected = relative - visited - ignored
    if unexpected:
        raise ValueError(
            "form storage contains unexpected stream tree entries: "
            + ", ".join("/".join(path) for path in sorted(unexpected))
        )
    return _semantic_stream_hash(records)


def _form_storage_records(
    ole: Any, entries: list[list[str]]
) -> tuple[_FormStorage, ...]:
    candidates: set[tuple[str, ...]] = set()
    immediate: dict[tuple[str, ...], set[str]] = {}
    for entry in entries:
        prefix = tuple(entry[:-1])
        immediate.setdefault(prefix, set()).add(entry[-1].casefold())
    for prefix, names in immediate.items():
        if {"f", "o", "\x03vbframe"} <= names:
            candidates.add(prefix)

    result: list[_FormStorage] = []
    for prefix in sorted(candidates):
        designer_path = list(prefix + ("\x03VBFrame",))
        result.append(
            _FormStorage(
                name=unicodedata.normalize("NFC", prefix[-1]),
                path=unicodedata.normalize("NFC", "/".join(prefix)),
                sha256=_form_semantic_sha256(ole, prefix),
                designer_sha256=_form_designer_sha256(
                    ole.openstream(designer_path).read()
                ),
            )
        )
    return tuple(result)


def _frx_semantic_sha256(data: bytes) -> str:
    if len(data) < _FRX_WRAPPER_SIZE + len(olefile.MAGIC):
        raise ValueError("FRX wrapper is truncated")
    if data[:4] != _FRX_WRAPPER_MAGIC:
        raise ValueError("FRX wrapper signature is invalid")
    declared_size = int.from_bytes(data[4:8], "little")
    payload = data[_FRX_WRAPPER_SIZE:]
    if declared_size != len(payload):
        raise ValueError("FRX wrapper payload length does not match the file")
    if declared_size < 512 or declared_size % 512:
        raise ValueError("FRX wrapper payload is not sector aligned")
    if not payload.startswith(olefile.MAGIC):
        raise ValueError("FRX wrapper does not contain OLE at its declared boundary")
    ole = olefile.OleFileIO(io.BytesIO(payload), write_mode=False)
    try:
        return _form_semantic_sha256(ole, ())
    finally:
        ole.close()


def _audit_ole(
    readonly_copy: Path, diagnostics: list[Diagnostic]
) -> tuple[
    tuple[dict[str, str | int], ...],
    tuple[dict[str, str], ...],
    tuple[_FormStorage, ...],
]:
    try:
        if not olefile.isOleFile(readonly_copy):
            diagnostics.append(
                _diag(
                    "CFB_INVALID",
                    "catvba",
                    "input is not a complete readable OLE compound file",
                )
            )
            return (), (), ()
        ole = olefile.OleFileIO(readonly_copy, write_mode=False)
        try:
            entries = sorted(
                ole.listdir(streams=True, storages=False),
                key=lambda parts: tuple(
                    unicodedata.normalize("NFC", value) for value in parts
                ),
            )
            records = tuple(_stream_record(ole, entry) for entry in entries)
            form_storages = _form_storage_records(ole, entries)
            dir_entries = [
                entry
                for entry in entries
                if len(entry) >= 2
                and entry[-1].casefold() == "dir"
                and entry[-2].casefold() == "vba"
            ]
            if len(dir_entries) != 1:
                diagnostics.append(
                    _diag(
                        "REFERENCE_METADATA_MISSING",
                        "vba/dir",
                        "the compound file does not contain exactly one VBA dir stream",
                    )
                )
                references: tuple[dict[str, str], ...] = ()
            else:
                references = _reference_records(
                    ole.openstream(dir_entries[0]).read(), diagnostics
                )
            return records, references, form_storages
        finally:
            ole.close()
    except Exception as error:
        diagnostics.append(
            _diag(
                "CFB_INVALID",
                "catvba",
                "input is not a complete readable OLE compound file",
                error_type=type(error).__name__,
            )
        )
        return (), (), ()


def _source_text_variants(
    source: str | bytes, declared_encoding: str | None = None
) -> tuple[str, ...]:
    if isinstance(source, str):
        return (source,)
    try:
        return (decode_vba(source, declared_encoding).text,)
    except SourceError:
        return ()


def _canonical_source_text(
    value: str, *, source_kind: str | None = None, extracted: bool = False
) -> str:
    normalized = value.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    vb_name_indexes = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*Attribute\s+VB_Name\s*=", line, re.IGNORECASE)
    ]
    if source_kind is not None and len(vb_name_indexes) != 1:
        raise ValueError("VBA source must contain exactly one module identity")
    if vb_name_indexes:
        if len(vb_name_indexes) != 1:
            raise ValueError("VBA source contains duplicate module identities")
        vb_name_index = vb_name_indexes[0]
        prefix = lines[:vb_name_index]
        kind = source_kind.casefold() if source_kind is not None else None
        if kind == ".bas" and prefix:
            raise ValueError("standard module export header contains hidden source")
        if kind == ".cls":
            expected_header = [
                "VERSION 1.0 CLASS",
                "BEGIN",
                "  MultiUse = -1  'True",
                "END",
            ]
            if (extracted and prefix) or (not extracted and prefix != expected_header):
                raise ValueError("class module export header is invalid")
        if kind == ".frm":
            valid_form_header = (
                len(prefix) >= 3
                and prefix[0] == "VERSION 5.00"
                and re.match(r"^Begin\s+", prefix[1]) is not None
                and prefix[-1] == "End"
            )
            if (extracted and prefix) or (not extracted and not valid_form_header):
                raise ValueError("Form export header is invalid")
        if kind not in {None, ".bas", ".cls", ".frm"}:
            raise ValueError("VBA source kind is unsupported")
        if kind is None and prefix:
            raise ValueError("VBA export header requires a source kind")
        lines = lines[vb_name_index:]
    canonical_lines: list[str] = []
    for line in lines:
        extraction_attribute = re.match(
            r"^\s*Attribute\s+(VB_Base|VB_TemplateDerived|VB_Customizable)\b",
            line,
            re.IGNORECASE,
        )
        if extraction_attribute is None:
            canonical_lines.append(line.rstrip())
            continue
        if not extracted:
            raise ValueError("staged VBA source contains extraction-only metadata")
        valid_extraction_attribute = (
            kind == ".cls"
            and _EXTRACTED_CLASS_BASE.fullmatch(line) is not None
        ) or (
            kind == ".frm"
            and _EXTRACTED_FORM_BASE.fullmatch(line) is not None
        ) or (
            kind in {".cls", ".frm"}
            and line.casefold()
            in {
                "attribute vb_templatederived = false",
                "attribute vb_customizable = false",
            }
        )
        if not valid_extraction_attribute:
            raise ValueError("extracted VBA source contains invalid extraction-only metadata")
    lines = canonical_lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def _semantic_source_hashes(
    source: str | bytes,
    declared_encoding: str | None = None,
    *,
    source_kind: str | None = None,
    extracted: bool = False,
) -> frozenset[str]:
    return frozenset(
        hashlib.sha256(
            _canonical_source_text(
                text, source_kind=source_kind, extracted=extracted
            ).encode("utf-8")
        ).hexdigest()
        for text in _source_text_variants(source, declared_encoding)
    )


def _source_hash_candidates(
    source: str | bytes, declared_encoding: str | None = None
) -> frozenset[str]:
    if isinstance(source, bytes):
        direct = {hashlib.sha256(source).hexdigest()}
    else:
        direct = set()
    variants: set[str] = set()
    for value in _source_text_variants(source, declared_encoding):
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        variants.update((normalized, normalized.replace("\n", "\r\n")))
    digests: set[str] = set(direct)
    for text in variants:
        for encoding in ("utf-8", "cp936"):
            try:
                data = text.encode(encoding, errors="strict")
            except UnicodeEncodeError:
                continue
            digests.add(hashlib.sha256(data).hexdigest())
            if encoding == "utf-8":
                digests.add(hashlib.sha256(b"\xef\xbb\xbf" + data).hexdigest())
    return frozenset(digests)


def _audit_vba(
    readonly_copy: Path,
    form_storages: tuple[_FormStorage, ...],
    diagnostics: list[Diagnostic],
) -> tuple[
    tuple[dict[str, str], ...],
    dict[str, frozenset[str]],
    dict[str, frozenset[str]],
    dict[str, str],
]:
    parser: VBA_Parser | None = None
    try:
        parser = VBA_Parser(
            os.fspath(readonly_copy), relaxed=True, disable_pcode=True
        )
        extracted = list(parser.extract_macros())
        if not extracted:
            raise ValueError("no VBA modules")
        records: list[dict[str, str]] = []
        raw_candidates: dict[str, frozenset[str]] = {}
        semantic_candidates: dict[str, frozenset[str]] = {}
        forms: dict[str, str] = {}
        matched_storage_paths: set[str] = set()
        storages_by_name: dict[str, list[_FormStorage]] = {}
        for storage in form_storages:
            storages_by_name.setdefault(storage.name.casefold(), []).append(storage)
        for _container, stream_path, vba_filename, source in extracted:
            name = PurePosixPath(str(vba_filename).replace("\\", "/")).name
            normalized_stream = unicodedata.normalize(
                "NFC", str(stream_path).replace("\\", "/")
            )
            raw_hashes = _source_hash_candidates(source)
            semantic_hashes = _semantic_source_hashes(
                source,
                source_kind=PurePosixPath(name).suffix,
                extracted=True,
            )
            record = {
                "name": unicodedata.normalize("NFC", name),
                "stream_path": normalized_stream,
                "source_sha256": min(semantic_hashes),
            }
            raw_candidates[name] = frozenset(
                (*raw_candidates.get(name, ()), *raw_hashes)
            )
            semantic_candidates[name] = frozenset(
                (*semantic_candidates.get(name, ()), *semantic_hashes)
            )
            if name.casefold().endswith(".frm"):
                stem = PurePosixPath(name).stem
                matches = storages_by_name.get(stem.casefold(), [])
                if len(matches) == 1:
                    frx_name = PurePosixPath(name).with_suffix(".frx").name
                    matched_storage_paths.add(matches[0].path)
                    forms[frx_name] = _combined_form_sha256(
                        matches[0].sha256, matches[0].designer_sha256
                    )
                    record["form_storage_sha256"] = matches[0].sha256
                    record["form_designer_sha256"] = matches[0].designer_sha256
                else:
                    diagnostics.append(
                        _diag(
                            "FORM_STORAGE_MISMATCH",
                            name,
                            "VBA Form source does not bind exactly one internal Form storage",
                            matches=len(matches),
                        )
                    )
            records.append(record)
        for storage in form_storages:
            if storage.path not in matched_storage_paths:
                diagnostics.append(
                    _diag(
                        "FORM_STORAGE_ORPHAN",
                        storage.path,
                        "internal Form storage does not bind exactly one VBA Form source module",
                        storage_name=storage.name,
                    )
                )
        return (
            tuple(
                sorted(
                    records,
                    key=lambda item: (
                        item["name"], item["stream_path"], item["source_sha256"]
                    ),
                )
            ),
            raw_candidates,
            semantic_candidates,
            dict(sorted(forms.items())),
        )
    except Exception as error:
        diagnostics.append(
            _diag(
                "VBA_PARSE_FAILED",
                "catvba",
                "VBA source modules could not be enumerated",
                error_type=type(error).__name__,
            )
        )
        return (), {}, {}, {}
    finally:
        if parser is not None:
            try:
                parser.close()
            except Exception:
                pass


def _drain_bounded_fd(
    descriptor: int,
    buffer: bytearray,
    state: dict[str, bool],
    stop: threading.Event,
) -> None:
    try:
        while not stop.is_set():
            try:
                chunk = os.read(descriptor, 64 * 1024)
            except BlockingIOError:
                stop.wait(0.01)
                continue
            if not chunk:
                return
            remaining = _MAX_PCODE_CAPTURE - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                state["truncated"] = True
    except OSError:
        state["truncated"] = True


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _run_bounded_process(
    args: list[str], *, env: dict[str, str], timeout: float
) -> _ProcessCapture:
    """Run a subprocess while continuously draining and discarding overflow."""
    popen_options: dict[str, Any] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":
        popen_options["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    process = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        shell=False,
        env=env,
        **popen_options,
    )
    if process.stdout is None or process.stderr is None:
        _kill_process_group(process)
        process.wait()
        raise OSError("subprocess pipes were not created")
    pipes = (process.stdout, process.stderr)
    try:
        for pipe in pipes:
            os.set_blocking(pipe.fileno(), False)
    except OSError:
        _kill_process_group(process)
        process.wait()
        for pipe in pipes:
            pipe.close()
        raise
    stdout = bytearray()
    stderr = bytearray()
    stdout_state = {"truncated": False}
    stderr_state = {"truncated": False}
    stop = threading.Event()
    readers = (
        threading.Thread(
            target=_drain_bounded_fd,
            args=(process.stdout.fileno(), stdout, stdout_state, stop),
            daemon=True,
        ),
        threading.Thread(
            target=_drain_bounded_fd,
            args=(process.stderr.fileno(), stderr, stderr_state, stop),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(process)
        try:
            returncode = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            returncode = None
    grace_deadline = time.monotonic() + (0.25 if timed_out else 1.0)
    for reader in readers:
        reader.join(timeout=max(0.0, grace_deadline - time.monotonic()))
    stop.set()
    for pipe, reader, state in zip(pipes, readers, (stdout_state, stderr_state), strict=True):
        reader.join(timeout=0.25)
        if reader.is_alive():
            state["truncated"] = True
            try:
                os.close(pipe.fileno())
            except OSError:
                pass
            reader.join(timeout=0.25)
        if reader.is_alive():
            raise OSError("subprocess output reader did not stop")
        try:
            pipe.close()
        except OSError:
            pass
    return _ProcessCapture(
        returncode=returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        stdout_truncated=stdout_state["truncated"],
        stderr_truncated=stderr_state["truncated"],
        timed_out=timed_out,
    )


def _run_pcode(
    readonly_copy: Path, diagnostics: list[Diagnostic]
) -> PCodeSignal:
    args = [
        sys.executable,
        "-m",
        "pcodedmp.pcodedmp",
        "-d",
        os.fspath(readonly_copy),
    ]
    try:
        capture = _run_bounded_process(
            args,
            timeout=60,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        )
        stdout_sha256 = hashlib.sha256(capture.stdout).hexdigest()
        stderr_sha256 = hashlib.sha256(capture.stderr).hexdigest()
        if capture.stdout_truncated or capture.stderr_truncated:
            diagnostics.append(
                _diag(
                    "PCODE_OUTPUT_TRUNCATED",
                    "pcodedmp",
                    "diagnostic p-code output exceeded the one MiB reporting bound",
                )
            )
        returncode = capture.returncode
        if capture.timed_out:
            diagnostics.append(
                _diag(
                    "PCODE_TIMEOUT",
                    "pcodedmp",
                    "diagnostic p-code subprocess exceeded its 60 second timeout",
                )
            )
            return PCodeSignal(
                "timeout", None, stdout_sha256, stderr_sha256
            )
        if returncode != 0:
            diagnostics.append(
                _diag(
                    "PCODE_NONZERO",
                    "pcodedmp",
                    "diagnostic p-code subprocess returned a nonzero status",
                    returncode=returncode,
                )
            )
            status = "nonzero"
        else:
            status = "ok"
        return PCodeSignal(status, returncode, stdout_sha256, stderr_sha256)
    except OSError as error:
        diagnostics.append(
            _diag(
                "PCODE_UNAVAILABLE",
                "pcodedmp",
                "diagnostic p-code subprocess could not be started",
                error_type=type(error).__name__,
            )
        )
        return PCodeSignal("unavailable", None, None, None)


def _duplicate_key_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load_json_object(data: bytes) -> dict[str, Any]:
    value = json.loads(
        data.decode("utf-8", errors="strict"),
        object_pairs_hook=_duplicate_key_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant: {value}")
        ),
    )
    if type(value) is not dict:
        raise ValueError("JSON document is not an object")
    return value


def _open_directory_nofollow(path: Path, error_code: str) -> int:
    if not all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ) or not os.supports_dir_fd or os.open not in os.supports_dir_fd:
        raise VerificationError(f"{error_code}: NOFOLLOW_UNAVAILABLE")
    parts = _absolute(path).parts
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(parts[0], flags)
        for component in parts[1:]:
            next_descriptor = os.open(
                component, flags, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as error:
        try:
            os.close(descriptor)
        except (OSError, UnboundLocalError):
            pass
        raise VerificationError(f"{error_code}: {type(error).__name__}") from error


def _expected_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


class _ExpectedKitReader:
    """Read one stable Kit tree through a single no-follow root descriptor."""

    def __init__(self, root: Path) -> None:
        self._root = _absolute(root)
        self._root_fd = _open_directory_nofollow(
            self._root, "EXPECTED_MANIFEST_INVALID"
        )
        self._root_identity = _expected_identity(os.fstat(self._root_fd))
        self._files: dict[PurePosixPath, _ExpectedFileSnapshot] = {}
        self._directories: dict[
            PurePosixPath, _ExpectedDirectorySnapshot
        ] = {}
        self._root_directory: _ExpectedDirectorySnapshot | None = None

    def __enter__(self) -> _ExpectedKitReader:
        return self

    def __exit__(self, *args: object) -> None:
        os.close(self._root_fd)

    @staticmethod
    def _validate_relative(path: PurePosixPath) -> None:
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in path.as_posix()
        ):
            raise ValueError("expected companion path is invalid")

    def _open_directory(self, path: PurePosixPath | None) -> int:
        descriptor = os.dup(self._root_fd)
        if path is None:
            return descriptor
        self._validate_relative(path)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            for component in path.parts:
                child = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _snapshot_file(self, path: PurePosixPath) -> _ExpectedFileSnapshot:
        self._validate_relative(path)
        parent_path = (
            PurePosixPath(*path.parts[:-1]) if len(path.parts) > 1 else None
        )
        parent = self._open_directory(parent_path)
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("expected companion is not a regular file")
            if before.st_size > _MAX_EXPECTED_FILE:
                raise ValueError("expected companion exceeds the bounded input limit")
            chunks: list[bytes] = []
            remaining = _MAX_EXPECTED_FILE + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (
            len(data) > _MAX_EXPECTED_FILE
            or len(data) != before.st_size
            or _expected_identity(before) != _expected_identity(after)
        ):
            raise ValueError("expected companion changed while being read")
        return _ExpectedFileSnapshot(_expected_identity(after), data)

    def read_file(self, path: PurePosixPath) -> bytes:
        snapshot = self._snapshot_file(path)
        previous = self._files.setdefault(path, snapshot)
        if previous != snapshot:
            raise ValueError("expected companion changed between reads")
        return previous.data

    def _snapshot_directory(
        self, path: PurePosixPath | None
    ) -> _ExpectedDirectorySnapshot:
        descriptor = self._open_directory(path)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError("expected companion directory is invalid")
            bounded_names: list[str] = []
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    bounded_names.append(entry.name)
                    if len(bounded_names) > _MAX_EXPECTED_ENTRIES:
                        raise ValueError(
                            "expected Kit tree exceeds bounded audit limits"
                        )
            names = tuple(sorted(bounded_names))
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if _expected_identity(before) != _expected_identity(after):
            raise ValueError("expected companion directory changed while listed")
        return _ExpectedDirectorySnapshot(_expected_identity(after), names)

    def _remember_directory(
        self, path: PurePosixPath | None
    ) -> _ExpectedDirectorySnapshot:
        snapshot = self._snapshot_directory(path)
        if path is None:
            if self._root_directory is None:
                self._root_directory = snapshot
            elif self._root_directory != snapshot:
                raise ValueError("expected Kit root directory changed between listings")
            return self._root_directory
        previous = self._directories.setdefault(path, snapshot)
        if previous != snapshot:
            raise ValueError("expected companion directory changed between listings")
        return previous

    def read_directory(
        self, path: PurePosixPath
    ) -> tuple[tuple[str, bytes], ...]:
        previous = self._remember_directory(path)
        result: list[tuple[str, bytes]] = []
        for name in previous.names:
            if not name or "/" in name or "\\" in name or name in {".", ".."}:
                raise ValueError("expected companion entry name is invalid")
            result.append((name, self.read_file(path / name)))
        return tuple(result)

    def snapshot_tree(self) -> tuple[dict[str, bytes], set[str]]:
        """Capture the complete regular-file Kit tree through the held root fd."""
        files: dict[str, bytes] = {}
        directories: set[str] = set()
        total_bytes = 0
        entry_count = 0

        def visit(path: PurePosixPath | None, depth: int) -> None:
            nonlocal entry_count, total_bytes
            if depth > _MAX_EXPECTED_DEPTH:
                raise ValueError("expected Kit tree exceeds bounded audit limits")
            listing = self._remember_directory(path)
            entry_count += len(listing.names)
            if entry_count > _MAX_EXPECTED_ENTRIES:
                raise ValueError("expected Kit tree exceeds bounded audit limits")
            descriptor = self._open_directory(path)
            try:
                for name in listing.names:
                    if not name or "/" in name or name in {".", ".."}:
                        raise ValueError("expected Kit entry name is invalid")
                    relative = PurePosixPath(name) if path is None else path / name
                    status = os.stat(
                        name, dir_fd=descriptor, follow_symlinks=False
                    )
                    if stat.S_ISLNK(status.st_mode):
                        raise ValueError("expected Kit contains a symlink entry")
                    if stat.S_ISDIR(status.st_mode):
                        child = self._remember_directory(relative)
                        if child.identity != _expected_identity(status):
                            raise ValueError("expected Kit directory changed while opening")
                        directories.add(relative.as_posix())
                        visit(relative, depth + 1)
                        continue
                    if not stat.S_ISREG(status.st_mode):
                        raise ValueError("expected Kit contains a non-regular entry")
                    data = self.read_file(relative)
                    if self._files[relative].identity != _expected_identity(status):
                        raise ValueError("expected Kit file changed while opening")
                    files[relative.as_posix()] = data
                    total_bytes += len(data)
                    if total_bytes > _MAX_EXPECTED_TOTAL:
                        raise ValueError("expected Kit tree exceeds bounded audit limits")
            finally:
                os.close(descriptor)

        visit(None, 0)
        return files, directories

    def validate(self) -> None:
        if _expected_identity(os.fstat(self._root_fd)) != self._root_identity:
            raise ValueError("expected Kit root changed during audit")
        if (
            self._root_directory is not None
            and self._snapshot_directory(None) != self._root_directory
        ):
            raise ValueError("expected Kit root directory changed during audit")
        for path, expected in sorted(
            self._files.items(), key=lambda item: item[0].as_posix()
        ):
            if self._snapshot_file(path) != expected:
                raise ValueError("expected companion changed during audit")
        for path, expected in sorted(
            self._directories.items(), key=lambda item: item[0].as_posix()
        ):
            if self._snapshot_directory(path) != expected:
                raise ValueError("expected companion directory changed during audit")
        if _expected_identity(os.fstat(self._root_fd)) != self._root_identity:
            raise ValueError("expected Kit root changed during audit")


class _ExpectedInspectionReader:
    """Expose one already-captured BuildKitInspection without reopening it."""

    def __init__(self, inspection: BuildKitInspection) -> None:
        if type(inspection.files) is not tuple:
            raise ValueError("expected Kit inspection files are invalid")
        files: dict[str, bytes] = {}
        directories: set[str] = set()
        total = 0
        for item in inspection.files:
            if (
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not bytes
                or item[0] in files
            ):
                raise ValueError("expected Kit inspection files are invalid")
            path = PurePosixPath(item[0])
            if (
                path.is_absolute()
                or not path.parts
                or path.as_posix() != item[0]
                or "\\" in item[0]
                or any(part in {"", ".", ".."} for part in path.parts)
                or len(path.parts) > _MAX_EXPECTED_DEPTH
            ):
                raise ValueError("expected Kit inspection path is invalid")
            files[item[0]] = item[1]
            total += len(item[1])
            if (
                len(files) > _MAX_EXPECTED_ENTRIES
                or total > _MAX_EXPECTED_TOTAL
            ):
                raise ValueError("expected Kit inspection exceeds audit limits")
            for depth in range(1, len(path.parts)):
                directories.add(PurePosixPath(*path.parts[:depth]).as_posix())
        self._files = files
        self._directories = directories
        self._root = Path(inspection.kit_id or "invalid-inspection")

    def read_file(self, path: PurePosixPath) -> bytes:
        try:
            return self._files[path.as_posix()]
        except KeyError as error:
            raise ValueError("expected Kit inspection file is missing") from error

    def read_directory(
        self, path: PurePosixPath
    ) -> tuple[tuple[str, bytes], ...]:
        prefix = path.as_posix() + "/"
        children: list[tuple[str, bytes]] = []
        for name, data in self._files.items():
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix) :]
            if "/" in relative:
                continue
            children.append((relative, data))
        if path.as_posix() not in self._directories:
            raise ValueError("expected Kit inspection directory is missing")
        return tuple(sorted(children))

    def snapshot_tree(self) -> tuple[dict[str, bytes], set[str]]:
        return dict(self._files), set(self._directories)

    def validate(self) -> None:
        return


def _strict_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str or not item for item in value):
        raise ValueError(f"{field_name} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(value)


def _mapping_expected(value: Mapping[str, Any]) -> _Expected:
    document = dict(value)
    if any(type(key) is not str for key in document):
        raise ValueError("expected mapping keys must be strings")
    if set(document) - _EXPECTED_MAPPING_FIELDS:
        raise ValueError("expected mapping contains unknown fields")
    file_sha256 = document.get("file_sha256")
    if file_sha256 is not None and (
        type(file_sha256) is not str or _DIGEST.fullmatch(file_sha256) is None
    ):
        raise ValueError("file_sha256 is invalid")
    modules = (
        _strict_strings(document["modules"], "modules")
        if "modules" in document
        else None
    )
    frx = _strict_strings(document["frx"], "frx") if "frx" in document else None
    references = (
        _strict_strings(document["references"], "references")
        if "references" in document
        else None
    )
    raw_hashes = document.get("hashes", {})
    if type(raw_hashes) is not dict or any(
        type(name) is not str
        or not name
        or type(digest) is not str
        or _DIGEST.fullmatch(digest) is None
        for name, digest in raw_hashes.items()
    ):
        raise ValueError("hashes must map non-empty names to SHA-256 digests")
    return _Expected(
        file_sha256=file_sha256,
        modules=modules,
        frx=frx,
        references=references,
        hashes=tuple(sorted(raw_hashes.items())),
    )


def _structured_reference_contract(
    contract: Mapping[str, Any],
) -> _ExpectedReferenceContract:
    body_digest = reference_contract_body_digest(contract)
    if (
        type(body_digest) is not str
        or contract.get("contract_body_digest") != body_digest
    ):
        raise ValueError("approved Reference contract digest is invalid")
    approved = approved_reference_set(contract, "post-restart")
    raw_definitions = contract.get("reference_definitions")
    raw_global_policy = contract.get("path_policy")
    if type(raw_definitions) is not list or not isinstance(
        raw_global_policy, Mapping
    ):
        raise ValueError("approved Reference contract is invalid")
    definitions: dict[str, _ExpectedReferenceDefinition] = {}
    for value in raw_definitions:
        if not isinstance(value, Mapping):
            raise ValueError("approved Reference definition is invalid")
        stable_id = value.get("stable_reference_id")
        path_policy = value.get("path_policy")
        if type(stable_id) is not str or not isinstance(path_policy, Mapping):
            raise ValueError("approved Reference definition is invalid")
        if stable_id in definitions:
            raise ValueError("approved Reference definition is duplicated")
        guid = value.get("guid")
        major = value.get("major")
        minor = value.get("minor")
        if (
            type(guid) is not str
            or type(major) is not int
            or type(minor) is not int
            or resolved_reference_id(guid, major, minor) != stable_id
        ):
            raise ValueError("approved Reference identity is invalid")
        canonical_path_sha256 = path_policy.get("canonical_path_sha256")
        if canonical_path_sha256 is not None and (
            type(canonical_path_sha256) is not str
            or _DIGEST.fullmatch(canonical_path_sha256) is None
        ):
            raise ValueError("approved Reference path digest is invalid")
        definitions[stable_id] = _ExpectedReferenceDefinition(
            stable_id=stable_id,
            guid=guid,
            major=major,
            minor=minor,
            allowed_names=_strict_strings(
                value.get("allowed_names"), "allowed_names"
            ),
            allowed_descriptions=_strict_strings(
                value.get("allowed_descriptions"), "allowed_descriptions"
            ),
            source_classification=str(value.get("source_classification")),
            architecture=str(value.get("architecture")),
            release_provenance=str(value.get("release_provenance")),
            root_kind=str(path_policy.get("root_kind")),
            allowed_basenames=_strict_strings(
                path_policy.get("allowed_basenames"), "allowed_basenames"
            ),
            allowed_relative_paths=_strict_strings(
                path_policy.get("allowed_relative_paths"),
                "allowed_relative_paths",
            ),
            canonical_path_sha256=canonical_path_sha256,
        )
    if not approved <= definitions.keys():
        raise ValueError("approved Reference point names an unknown definition")
    allowed_root_kinds = _strict_strings(
        raw_global_policy.get("allowed_root_kinds"), "allowed_root_kinds"
    )
    if raw_global_policy.get("allow_user_paths") is not False:
        raise ValueError("approved Reference global path policy is invalid")
    return _ExpectedReferenceContract(
        body_digest=body_digest,
        definitions=tuple(definitions[value] for value in sorted(approved)),
        allowed_root_kinds=allowed_root_kinds,
    )


def _kit_expected_snapshot(
    reader: _ExpectedKitReader | _ExpectedInspectionReader,
    package_id: str | None,
) -> _Expected:
    files, directories = reader.snapshot_tree()
    kit_findings = _verify_file_map(
        files, directories, container_name=reader._root.name
    )
    if kit_findings:
        codes = ",".join(sorted({item.code for item in kit_findings}))
        raise ValueError(f"expected Kit verification failed: {codes}")

    catalog = _load_json_object(reader.read_file(PurePosixPath("catalog.json")))
    package_records = catalog.get("packages")
    component_records = catalog.get("components")
    if type(package_records) is not list or type(component_records) is not list:
        raise ValueError("catalog package graph is invalid")
    package_ids = tuple(record["package_id"] for record in package_records)
    packages_by_id = {record["package_id"]: record for record in package_records}
    nonempty_packages = tuple(
        value
        for value in package_ids
        if any(record["package_id"] == value for record in component_records)
    )
    if package_id is None:
        if len(nonempty_packages) != 1:
            raise _ExpectedPackageSelectionError(
                "EXPECTED_PACKAGE_REQUIRED",
                "a multi-package Kit requires an explicit package selection",
            )
        selected_package = nonempty_packages[0]
    else:
        if type(package_id) is not str or _STABLE_ID.fullmatch(package_id) is None:
            raise _ExpectedPackageSelectionError(
                "EXPECTED_PACKAGE_UNKNOWN", "expected package ID is invalid"
            )
        if package_id not in package_ids:
            raise _ExpectedPackageSelectionError(
                "EXPECTED_PACKAGE_UNKNOWN", "expected package is not in the Kit"
            )
        if package_id not in nonempty_packages:
            raise _ExpectedPackageSelectionError(
                "EXPECTED_PACKAGE_EMPTY", "expected package has no buildable source"
            )
        selected_package = package_id

    manifest = _load_json_object(reader.read_file(PurePosixPath("kit-manifest.json")))
    if set(manifest) != _KIT_MANIFEST_FIELDS:
        raise ValueError("kit manifest fields are not exact")
    if (
        manifest["schema_version"] != 1
        or type(manifest["schema_version"]) is not int
        or type(manifest["kit_id"]) is not str
        or _KIT_ID.fullmatch(manifest["kit_id"]) is None
        or type(manifest["identity_sha256"]) is not str
        or _DIGEST.fullmatch(manifest["identity_sha256"]) is None
        or type(manifest["manifest_digest"]) is not str
        or _DIGEST.fullmatch(manifest["manifest_digest"]) is None
        or manifest["target_build_required"] is not True
        or manifest["catvba_artifacts"] != []
        or manifest["compile_status"] != "not-run"
        or manifest["release_eligible"] is not False
    ):
        raise ValueError("kit manifest invariants are invalid")

    receipt = _load_json_object(
        reader.read_file(PurePosixPath("receipts/hashes.json"))
    )
    if set(receipt) != {"schema_version", "algorithm", "members"}:
        raise ValueError("hash receipt fields are not exact")
    if (
        receipt["schema_version"] != 1
        or receipt["algorithm"] != "sha256"
        or type(receipt["members"]) is not list
    ):
        raise ValueError("hash receipt header is invalid")
    hashes: dict[str, str] = {}
    expected_by_package: dict[str, list[str]] = {
        value: [] for value in package_ids
    }
    form_bundle_roles: dict[tuple[str, str, str], set[str]] = {}
    frx_by_package: dict[str, list[str]] = {
        value: [] for value in package_ids
    }
    source_semantic_hashes: dict[str, tuple[str, ...]] = {}
    frx_payload_hashes: dict[tuple[str, str, str], tuple[str, str]] = {}
    frm_designer_hashes: dict[tuple[str, str, str], str] = {}
    component_decisions: dict[tuple[str, str], str | None] = {}
    for member in receipt["members"]:
        if type(member) is not dict or set(member) != {
            "source_id",
            "source_path",
            "staged_path",
            "raw_sha256",
            "role",
            "encoding_decision",
        }:
            raise ValueError("hash receipt member fields are not exact")
        staged_path = member["staged_path"]
        digest = member["raw_sha256"]
        role = member["role"]
        source_id = member["source_id"]
        source_path = member["source_path"]
        encoding_decision = member["encoding_decision"]
        staged = PurePosixPath(staged_path) if type(staged_path) is str else None
        source = PurePosixPath(source_path) if type(source_path) is str else None
        if (
            type(source_id) is not str
            or _STABLE_ID.fullmatch(source_id) is None
            or type(source_path) is not str
            or not source_path
            or source is None
            or source.is_absolute()
            or ".." in source.parts
            or "\\" in source_path
            or source.as_posix() != source_path
            or type(staged_path) is not str
            or not staged_path
            or staged is None
            or staged.is_absolute()
            or ".." in staged.parts
            or "\\" in staged_path
            or staged.as_posix() != staged_path
            or type(digest) is not str
            or _DIGEST.fullmatch(digest) is None
            or role not in {"source", "frm", "frx"}
            or (
                encoding_decision is not None
                and (
                    type(encoding_decision) is not str
                    or encoding_decision not in {"utf-8", "cp936"}
                )
            )
        ):
            raise ValueError("hash receipt member is invalid")
        assert staged is not None and source is not None
        if (
            len(staged.parts) != 4
            or staged.parts[0] != "packages"
            or staged.parts[2] != "source"
            or _STABLE_ID.fullmatch(staged.parts[1]) is None
            or staged.name != source.name
        ):
            raise ValueError("hash receipt path binding is invalid")
        suffix = staged.suffix.casefold()
        if (role, suffix) not in {
            ("source", ".bas"),
            ("source", ".cls"),
            ("frm", ".frm"),
            ("frx", ".frx"),
        }:
            raise ValueError("hash receipt role and extension disagree")
        if staged_path in hashes:
            raise ValueError("hash receipt staged paths are not unique")
        staged_bytes = reader.read_file(staged)
        if hashlib.sha256(staged_bytes).hexdigest() != digest:
            raise ValueError("staged source does not match its hash receipt")
        hashes[staged_path] = digest
        basename = staged.name
        package_id = staged.parts[1]
        if package_id not in expected_by_package:
            raise ValueError("hash receipt names an unknown package")
        component_key = (package_id, source_id)
        if (
            component_key in component_decisions
            and component_decisions[component_key] != encoding_decision
        ):
            raise ValueError("component encoding decisions are inconsistent")
        component_decisions[component_key] = encoding_decision
        bundle_key = (package_id, source_id, staged.stem)
        if role in {"frm", "frx"}:
            form_bundle_roles.setdefault(bundle_key, set()).add(role)
        if role == "frx":
            frx_by_package[package_id].append(basename)
            frx_payload_hashes[bundle_key] = (
                basename,
                _frx_semantic_sha256(staged_bytes),
            )
        else:
            expected_by_package[package_id].append(basename)
            semantic = _semantic_source_hashes(
                staged_bytes,
                declared_encoding=encoding_decision,
                source_kind=suffix,
            )
            if not semantic:
                raise ValueError("staged VBA source encoding is not supported")
            source_semantic_hashes[staged_path] = tuple(sorted(semantic))
            if role == "frm":
                frm_designer_hashes[bundle_key] = _form_designer_sha256(
                    staged_bytes,
                    expected_frx_name=f"{staged.stem}.frx",
                    declared_encoding=encoding_decision,
                )

    if any(roles != {"frm", "frx"} for roles in form_bundle_roles.values()):
        raise ValueError("hash receipt contains an incomplete Form bundle")
    frx_semantic_hashes: dict[tuple[str, str], str] = {}
    for bundle_key in sorted(form_bundle_roles):
        name, payload_digest = frx_payload_hashes[bundle_key]
        semantic_key = (bundle_key[0], name)
        if semantic_key in frx_semantic_hashes:
            raise ValueError("Form FRX basenames must be package-local unique")
        frx_semantic_hashes[semantic_key] = _combined_form_sha256(
            payload_digest, frm_designer_hashes[bundle_key]
        )

    import_entries = reader.read_directory(PurePosixPath("import-order"))
    modules_by_package: dict[str, tuple[str, ...]] = {}
    import_packages: set[str] = set()
    for filename, raw in import_entries:
        entry = PurePosixPath(filename)
        if entry.suffix != ".txt" or _STABLE_ID.fullmatch(entry.stem) is None:
            raise ValueError("import-order contains an unexpected entry")
        if entry.stem in import_packages:
            raise ValueError("import-order package IDs are not unique")
        import_packages.add(entry.stem)
        text = raw.decode("utf-8", errors="strict")
        if text and not text.endswith("\n"):
            raise ValueError("import-order is not newline terminated")
        names = text.splitlines()
        if any(not name or "/" in name or "\\" in name for name in names):
            raise ValueError("import-order contains an invalid member name")
        if sorted(names) != sorted(expected_by_package.get(entry.stem, [])):
            raise ValueError("import-order and package hash receipt disagree")
        if len(names) != len(set(names)):
            raise ValueError("import-order member names are not package-local unique")
        modules_by_package[entry.stem] = tuple(names)
    if import_packages != set(expected_by_package):
        raise ValueError("import-order package set is incomplete")
    if any(len(names) != len(set(names)) for names in frx_by_package.values()):
        raise ValueError("Form FRX basenames must be package-local unique")

    reference_entries = reader.read_directory(PurePosixPath("references"))
    references_by_package: dict[str, tuple[str, ...]] = {}
    reference_contracts_by_package: dict[
        str, _ExpectedReferenceContract
    ] = {}
    reference_packages: set[str] = set()
    for filename, raw in reference_entries:
        entry = PurePosixPath(filename)
        if entry.suffix != ".json" or _STABLE_ID.fullmatch(entry.stem) is None:
            raise ValueError("references contains an unexpected entry")
        if entry.stem in reference_packages:
            raise ValueError("reference package IDs are not unique")
        reference_packages.add(entry.stem)
        record = _load_json_object(raw)
        package = packages_by_id.get(entry.stem)
        if package is None or record != reference_companion(package):
            raise ValueError("reference companion does not match its catalog package")
        contract = record.get("reference_contract")
        if (
            record.get("schema_version") != 2
            or not isinstance(contract, dict)
            or contract.get("status") not in {"discovery-required", "approved"}
            or record.get("compile_status") != "not-run"
        ):
            raise ValueError("reference companion header is invalid")
        allowlist = _strict_strings(
            record["reference_allowlist"], "reference_allowlist"
        )
        if contract.get("status") == "approved":
            reference_contracts_by_package[entry.stem] = (
                _structured_reference_contract(contract)
            )
            references_by_package[entry.stem] = ()
        else:
            references_by_package[entry.stem] = allowlist
    if reference_packages != set(expected_by_package):
        raise ValueError("reference package set is incomplete")
    selected_hashes = {
        path: digest
        for path, digest in hashes.items()
        if PurePosixPath(path).parts[1] == selected_package
    }
    selected_source_hashes = {
        path: digest
        for path, digest in source_semantic_hashes.items()
        if PurePosixPath(path).parts[1] == selected_package
    }
    selected_frx_hashes = {
        name: digest
        for (value, name), digest in frx_semantic_hashes.items()
        if value == selected_package
    }
    return _Expected(
        package_id=selected_package,
        modules=modules_by_package[selected_package],
        frx=tuple(sorted(frx_by_package[selected_package])),
        references=(
            None
            if selected_package in reference_contracts_by_package
            else tuple(sorted(references_by_package[selected_package]))
        ),
        hashes=tuple(sorted(selected_hashes.items())),
        source_semantic_hashes=tuple(sorted(selected_source_hashes.items())),
        frx_semantic_hashes=tuple(sorted(selected_frx_hashes.items())),
        reference_contract=reference_contracts_by_package.get(selected_package),
    )


def _kit_expected(
    manifest_path: Path, *, package_id: str | None
) -> _Expected:
    if manifest_path.name != "kit-manifest.json":
        raise ValueError("expected path must name kit-manifest.json")
    with _ExpectedKitReader(manifest_path.parent) as reader:
        expected = _kit_expected_snapshot(reader, package_id)
        reader.validate()
        return expected


def _inspection_expected(
    inspection: BuildKitInspection, *, package_id: str | None
) -> _Expected:
    if (
        type(inspection) is not BuildKitInspection
        or inspection.report.ok is not True
        or inspection.report.diagnostics
    ):
        raise ValueError("expected Kit inspection is not verified")
    reader = _ExpectedInspectionReader(inspection)
    expected = _kit_expected_snapshot(reader, package_id)
    catalog_bytes = reader.read_file(PurePosixPath("catalog.json"))
    manifest_bytes = reader.read_file(PurePosixPath("kit-manifest.json"))
    catalog = _load_json_object(catalog_bytes)
    manifest = _load_json_object(manifest_bytes)
    snapshot = catalog.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("expected Kit snapshot is invalid")
    bindings = {
        "kit_id": manifest.get("kit_id"),
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_digest": manifest.get("manifest_digest"),
        "upstream_commit": snapshot.get("upstream_commit"),
        "fork_dev_commit": snapshot.get("fork_dev_commit"),
        "work_commit": snapshot.get("work_commit"),
        "work_tree": snapshot.get("work_tree"),
        "work_branch": snapshot.get("work_branch"),
    }
    if any(getattr(inspection, field) != value for field, value in bindings.items()):
        raise ValueError("expected Kit inspection metadata does not match its files")
    if (
        type(inspection.canonical_zip_sha256) is not str
        or _DIGEST.fullmatch(inspection.canonical_zip_sha256) is None
    ):
        raise ValueError("expected Kit inspection ZIP identity is invalid")
    reader.validate()
    return expected


def _load_expected(
    expected_manifest: Mapping[str, Any] | str | os.PathLike[str] | None,
    expected_kit: BuildKitInspection | None,
    diagnostics: list[Diagnostic],
    package_id: str | None,
) -> _Expected | None:
    if expected_manifest is None and expected_kit is None:
        if package_id is not None:
            diagnostics.append(
                _diag(
                    "EXPECTED_PACKAGE_UNEXPECTED",
                    "expected/package",
                    "package selection requires an expected Kit manifest",
                )
            )
        return None
    try:
        if expected_kit is not None:
            return _inspection_expected(expected_kit, package_id=package_id)
        if isinstance(expected_manifest, Mapping):
            if package_id is not None:
                raise _ExpectedPackageSelectionError(
                    "EXPECTED_PACKAGE_UNEXPECTED",
                    "package selection is not valid for an inline expected mapping",
                )
            return _mapping_expected(expected_manifest)
        if isinstance(expected_manifest, (str, os.PathLike)):
            return _kit_expected(
                Path(expected_manifest), package_id=package_id
            )
        raise ValueError("expected manifest must be a mapping or path")
    except _ExpectedPackageSelectionError as error:
        diagnostics.append(
            _diag(
                error.code,
                "expected/package",
                str(error),
            )
        )
        return None
    except Exception as error:
        diagnostics.append(
            _diag(
                "EXPECTED_MANIFEST_INVALID",
                "expected",
                "expected Kit metadata is invalid or unsafe",
                error_type=type(error).__name__,
            )
        )
        return None


_REFERENCE_VERSION = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)$"
)
_REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)


def _alias_matches(value: object, allowed: tuple[str, ...]) -> bool:
    return type(value) is str and unicodedata.normalize(
        "NFC", value
    ).casefold() in {
        unicodedata.normalize("NFC", candidate).casefold()
        for candidate in allowed
    }


def _match_structured_references(
    contract: _ExpectedReferenceContract,
    references: tuple[dict[str, str], ...],
) -> tuple[bool, tuple[str, ...]]:
    expected = {item.stable_id: item for item in contract.definitions}
    matched: list[str] = []
    valid = len(references) == len(contract.definitions)
    for reference in references:
        version = reference.get("version")
        match = (
            _REFERENCE_VERSION.fullmatch(version)
            if type(version) is str
            else None
        )
        guid = reference.get("guid")
        if match is None or type(guid) is not str:
            valid = False
            continue
        major = int(match.group("major"))
        minor = int(match.group("minor"))
        try:
            stable_id = resolved_reference_id(guid, major, minor)
        except ValueError:
            valid = False
            continue
        definition = expected.get(stable_id)
        if (
            definition is None
            or definition.guid != guid
            or definition.major != major
            or definition.minor != minor
            or not _alias_matches(
                reference.get("name"), definition.allowed_names
            )
            or not _alias_matches(
                reference.get("description"),
                definition.allowed_descriptions,
            )
        ):
            valid = False
            continue
        matched.append(stable_id)
    if len(matched) != len(set(matched)) or set(matched) != set(expected):
        valid = False
    return valid, tuple(sorted(set(matched)))


def _reference_observation_document(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        encoded = canonical_json_bytes(dict(value))
        document = _load_json_object(encoded)
    except (RecursionError, TypeError, UnicodeError, ValueError):
        return None, None
    return document, hashlib.sha256(encoded).hexdigest()


def _observation_matches_reference_contract(
    document: dict[str, Any],
    contract: _ExpectedReferenceContract,
    inspection: BuildKitInspection,
    package_id: str,
) -> bool:
    try:
        schema_root = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "target_evidence"
        )
        schemas = load_target_evidence_schemas(schema_root)
        if not validate_target_document(
            "references.json", document, schemas
        ).ok:
            return False
    except Exception:
        return False
    binding = document.get("binding")
    points = document.get("points")
    if (
        not isinstance(binding, Mapping)
        or type(points) is not list
        or document.get("reference_contract_body_digest")
        != contract.body_digest
        or binding.get("session_mode") != "g3-c"
        or binding.get("package_id") != package_id
        or binding.get("target") != "CATIA R2018/VBA7 64"
        or tuple(point.get("point") for point in points if isinstance(point, Mapping))
        != _REFERENCE_POINTS
    ):
        return False
    for field in (
        "kit_id",
        "catalog_sha256",
        "manifest_sha256",
        "manifest_digest",
        "work_commit",
        "work_tree",
    ):
        if binding.get(field) != getattr(inspection, field):
            return False
    post_restart = points[-1]
    if (
        not isinstance(post_restart, Mapping)
        or post_restart.get("status") != "observed"
        or type(post_restart.get("observations")) is not list
    ):
        return False
    expected = {item.stable_id: item for item in contract.definitions}
    observations = post_restart["observations"]
    if len(observations) != len(expected):
        return False
    observed_ids: set[str] = set()
    for observation in observations:
        if not isinstance(observation, Mapping):
            return False
        stable_id = observation.get("stable_reference_id")
        definition = expected.get(stable_id) if type(stable_id) is str else None
        if definition is None or stable_id in observed_ids:
            return False
        observed_ids.add(stable_id)
        if (
            observation.get("guid") != definition.guid
            or observation.get("major") != definition.major
            or observation.get("minor") != definition.minor
            or not _alias_matches(
                observation.get("name"), definition.allowed_names
            )
            or not _alias_matches(
                observation.get("description"),
                definition.allowed_descriptions,
            )
            or observation.get("source_classification")
            != definition.source_classification
            or observation.get("missing") is not False
            or observation.get("architecture") != definition.architecture
            or observation.get("release_provenance")
            != definition.release_provenance
            or observation.get("path_kind") != definition.root_kind
            or observation.get("path_kind")
            not in contract.allowed_root_kinds
            or observation.get("path_basename")
            not in definition.allowed_basenames
            or (
                definition.allowed_relative_paths
                and observation.get("relative_path")
                not in definition.allowed_relative_paths
            )
            or (
                definition.canonical_path_sha256 is not None
                and observation.get("path_sha256")
                != definition.canonical_path_sha256
            )
        ):
            return False
    return observed_ids == set(expected)


def _compare_expected(
    expected: _Expected | None,
    file_sha256: str,
    modules: tuple[dict[str, str], ...],
    source_hashes: dict[str, frozenset[str]],
    source_semantic_hashes: dict[str, frozenset[str]],
    actual_forms: dict[str, str],
    references: tuple[dict[str, str], ...],
    diagnostics: list[Diagnostic],
    *,
    expected_kit: BuildKitInspection | None = None,
    reference_observation: Mapping[str, Any] | None = None,
) -> ReferenceVerification:
    if expected is None:
        return ReferenceVerification("unavailable", None, None, ())
    if expected.file_sha256 is not None and expected.file_sha256 != file_sha256:
        diagnostics.append(
            _diag(
                "EXPECTED_FILE_HASH_MISMATCH",
                "catvba",
                "returned CATVBA hash does not match the expected hash",
            )
        )
    actual_modules = tuple(sorted(item["name"] for item in modules))
    if expected.modules is not None and tuple(sorted(expected.modules)) != actual_modules:
        diagnostics.append(
            _diag(
                "EXPECTED_MODULE_MISMATCH",
                "modules",
                "returned VBA module names do not match the expected import set",
            )
        )
    if expected.frx is not None and tuple(sorted(expected.frx)) != tuple(
        sorted(actual_forms)
    ):
        diagnostics.append(
            _diag(
                "EXPECTED_FRX_MISMATCH",
                "forms",
                "returned VBA Form identities do not match the expected FRX sidecars",
            )
        )
    reference_verification = ReferenceVerification(
        "unavailable",
        (
            expected.reference_contract.body_digest
            if expected.reference_contract is not None
            else None
        ),
        None,
        (),
    )
    if expected.reference_contract is not None:
        container_matches, matched_ids = _match_structured_references(
            expected.reference_contract, references
        )
        if not container_matches:
            diagnostics.append(
                _diag(
                    "EXPECTED_REFERENCE_MISMATCH",
                    "references",
                    "returned VBA references do not match the approved post-restart set",
                )
            )
        observation_document: dict[str, Any] | None = None
        observation_sha256: str | None = None
        if reference_observation is not None:
            observation_document, observation_sha256 = (
                _reference_observation_document(reference_observation)
            )
        observation_matches = (
            observation_document is not None
            and expected_kit is not None
            and expected.package_id is not None
            and _observation_matches_reference_contract(
                observation_document,
                expected.reference_contract,
                expected_kit,
                expected.package_id,
            )
        )
        if reference_observation is not None and not observation_matches:
            diagnostics.append(
                _diag(
                    "REFERENCE_OBSERVATION_MISMATCH",
                    "references.json",
                    "external post-restart Reference evidence is invalid or cross-bound",
                )
            )
        status = (
            "verified"
            if container_matches and observation_matches
            else "partial"
            if container_matches
            else "unavailable"
        )
        reference_verification = ReferenceVerification(
            status,
            expected.reference_contract.body_digest,
            observation_sha256,
            matched_ids,
        )
    elif expected.references is not None:
        expected_tokens = tuple(value.casefold() for value in expected.references)
        actual_choices = tuple(
            frozenset(
                value.casefold()
                for value in (
                    reference.get("name"),
                    reference.get("guid"),
                    reference.get("description"),
                )
                if value
            )
            for reference in references
        )
        candidates = tuple(
            tuple(
                index
                for index, choices in enumerate(actual_choices)
                if token in choices
            )
            for token in expected_tokens
        )
        matched_actual: dict[int, int] = {}

        def assign(token_index: int, seen: set[int]) -> bool:
            for actual_index in candidates[token_index]:
                if actual_index in seen:
                    continue
                seen.add(actual_index)
                previous = matched_actual.get(actual_index)
                if previous is None or assign(previous, seen):
                    matched_actual[actual_index] = token_index
                    return True
            return False

        matched = len(expected_tokens) == len(actual_choices) and all(
            assign(token_index, set())
            for token_index in sorted(
                range(len(expected_tokens)), key=lambda index: len(candidates[index])
            )
        )
        if not matched or len(matched_actual) != len(actual_choices):
            diagnostics.append(
                _diag(
                    "EXPECTED_REFERENCE_MISMATCH",
                    "references",
                    "returned VBA references do not match the expected reference set",
                )
            )
    semantic_expected = dict(expected.source_semantic_hashes)
    for staged_path, expected_hashes in semantic_expected.items():
        name = PurePosixPath(staged_path).name
        if source_semantic_hashes.get(name, frozenset()).isdisjoint(
            expected_hashes
        ):
            diagnostics.append(
                _diag(
                    "EXPECTED_SOURCE_HASH_MISMATCH",
                    name,
                    "returned VBA source does not reproduce the canonical expected source",
                )
            )
    frx_expected = dict(expected.frx_semantic_hashes)
    for name, expected_digest in frx_expected.items():
        if actual_forms.get(name) != expected_digest:
            diagnostics.append(
                _diag(
                    "EXPECTED_FRX_HASH_MISMATCH",
                    name,
                    "returned internal Form storage does not reproduce the expected FRX payload",
                )
            )

    for staged_path, expected_digest in expected.hashes:
        suffix = PurePosixPath(staged_path).suffix.casefold()
        name = PurePosixPath(staged_path).name
        if suffix == ".frx":
            if name not in frx_expected:
                diagnostics.append(
                    _diag(
                        "EXPECTED_FRX_HASH_UNVERIFIABLE",
                        name,
                        "raw FRX hash lacks the staged bytes needed for semantic Form comparison",
                    )
                )
            continue
        if suffix not in {".bas", ".cls", ".frm"} or staged_path in semantic_expected:
            continue
        if (
            expected_digest not in source_hashes.get(name, frozenset())
            and expected_digest
            not in source_semantic_hashes.get(name, frozenset())
        ):
            diagnostics.append(
                _diag(
                    "EXPECTED_SOURCE_HASH_MISMATCH",
                    name,
                    "returned VBA source does not reproduce the expected source hash",
                )
            )
    return reference_verification


def _audit_copy(
    readonly_copy: Path,
    initial: _InputSnapshot,
    expected_manifest: Mapping[str, Any] | str | os.PathLike[str] | None,
    expected_kit: BuildKitInspection | None,
    reference_observation: Mapping[str, Any] | None,
    package_id: str | None,
) -> AuditReport:
    diagnostics: list[Diagnostic] = []
    streams, references, form_storages = _audit_ole(readonly_copy, diagnostics)
    if streams:
        (
            modules,
            source_hashes,
            source_semantic_hashes,
            actual_forms,
        ) = _audit_vba(readonly_copy, form_storages, diagnostics)
    else:
        diagnostics.append(
            _diag(
                "VBA_PARSE_FAILED",
                "catvba",
                "VBA source modules could not be enumerated from an invalid compound file",
            )
        )
        modules, source_hashes, source_semantic_hashes, actual_forms = (
            (),
            {},
            {},
            {},
        )
    pcode = _run_pcode(readonly_copy, diagnostics)
    expected = _load_expected(
        expected_manifest, expected_kit, diagnostics, package_id
    )
    reference_verification = _compare_expected(
        expected,
        initial.sha256,
        modules,
        source_hashes,
        source_semantic_hashes,
        actual_forms,
        references,
        diagnostics,
        expected_kit=expected_kit,
        reference_observation=reference_observation,
    )
    return AuditReport(
        file_sha256=initial.sha256,
        streams=streams,
        modules=modules,
        references=references,
        pcode=pcode,
        diagnostics=_stable_diagnostics(diagnostics),
        package_id=expected.package_id if expected is not None else None,
        reference_verification=reference_verification,
    )


def audit_catvba(
    path: str | os.PathLike[str],
    expected_manifest: Mapping[str, Any] | str | os.PathLike[str] | None = None,
    *,
    package_id: str | None = None,
    expected_kit: BuildKitInspection | None = None,
    reference_observation: Mapping[str, Any] | None = None,
) -> AuditReport:
    """Audit a CATVBA through an immutable local copy.

    The result is offline structural evidence only.  In particular, p-code is
    always diagnostic-only and is never treated as a CATIA compile or runtime
    signal.
    """
    if expected_manifest is not None and expected_kit is not None:
        raise ValueError("expected_manifest and expected_kit are mutually exclusive")
    original = Path(path)
    initial = _read_input_snapshot(original)
    result: AuditReport | None = None
    failure: Exception | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="catvba-audit-") as temporary:
            readonly_copy = Path(temporary) / "returned.catvba"
            _write_readonly_copy(readonly_copy, initial.data)
            result = _audit_copy(
                readonly_copy,
                initial,
                expected_manifest,
                expected_kit,
                reference_observation,
                package_id,
            )
    except Exception as error:
        failure = error

    try:
        final = _read_input_snapshot(original)
    except Exception as error:
        raise VerificationError("AUDIT_INPUT_CHANGED") from error
    if (
        final.sha256 != initial.sha256
        or final.device != initial.device
        or final.inode != initial.inode
        or final.size != initial.size
        or final.mode != initial.mode
        or final.modified_ns != initial.modified_ns
        or final.changed_ns != initial.changed_ns
    ):
        raise VerificationError("AUDIT_INPUT_CHANGED")
    if failure is not None:
        raise failure
    assert result is not None
    return result
