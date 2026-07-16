"""Fail-closed workspace state machine for native Windows raw capture."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import re
import secrets
import shutil
import stat
import sys
import unicodedata
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable

from . import PACKAGE_ID, PROFILE_ID, SESSION_MODE, TRUST_LEVEL
from .canonical import (
    CollectorError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)
from .constants import MAX_RAW_SOURCE_MEMBERS


MAX_CONTROL_BYTES = 4 * 1024 * 1024
MAX_SKELETON_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_MEMBER_BYTES = 128 * 1024 * 1024
MAX_MEMBER_COUNT = MAX_RAW_SOURCE_MEMBERS
MAX_BUNDLE_MEMBER_BYTES = 512 * 1024 * 1024
# Builder caps pre-checksum output at 512 MiB; retain a small control-file margin.
MAX_BUNDLE_TOTAL_BYTES = 513 * 1024 * 1024
MAX_BUNDLE_MEMBER_COUNT = 8192
LEDGER_MAX_AGE = timedelta(hours=24)
LEDGER_FIELDS = frozenset(
    {"schema_version", "captured_at", "source", "active_handoff_ids", "withdrawn_handoff_ids"}
)
CURRENT_FIELDS = frozenset({"schema_version", "bundle_id", "bundle_sha256", "handoff_id"})
MEMBER_FIELDS = frozenset({"path", "sha256", "size"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HANDOFF_RE = re.compile(r"^handoff-[a-z0-9][a-z0-9-]{2,94}$")
BUNDLE_RE = re.compile(r"^bundle-[0-9a-f]{24}$")
KIT_RE = re.compile(r"^kit-[0-9a-f]{16,64}$")
SOURCE_RE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
OID_RE = re.compile(r"^[0-9a-f]{40}$")
RECORD_RE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
SESSION_RE = re.compile(r"^session-[a-z0-9][a-z0-9-]{2,94}$")
WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
WINDOWS_INVALID_CHARS = frozenset('<>:"\\|?*')
BUNDLE_FORBIDDEN_SUFFIXES = (".catvba", ".bas", ".cls", ".frm", ".frx")
SESSION_FIELDS = frozenset(
    {
        "schema_version",
        "session_id",
        "created_at",
        "capture_status",
        "trust_level",
        "mode",
        "package_id",
        "profile_id",
        "bundle_id",
        "kit_id",
        "handoff_id",
        "compile_status",
        "target_case_status",
        "artifact_status",
        "release_eligible",
    }
)
PROVENANCE_FIELDS = frozenset(
    {
        "schema_version", "repository", "branch", "evidence_commit", "evidence_tree",
        "approved_cutoff", "kit_id", "catalog_sha256", "manifest_sha256",
        "manifest_digest", "kit_zip_sha256", "kit_sidecar_sha256", "handoff_id",
        "handoff_sha256", "handoff_created_at", "handoff_expires_at",
        "issuance_revocation_snapshot_sha256", "active_ledger_schema_version",
        "active_ledger_source", "bundle_content_sha256", "collector_source_commit", "collector_source_sha256",
        "collector_pyz_sha256", "python_requirement", "session_skeleton_sha256",
        "session_skeleton_members", "tutorials_sha256", "templates_sha256",
        "schemas_sha256", "compile_status", "target_case_status", "artifact_status",
        "release_eligible", "generation_record_id", "test_record_id", "review_record_id",
    }
)
HANDOFF_FIELDS = frozenset(
    {
        "schema_version", "handoff_id", "purpose", "created_at", "expires_at",
        "revocation_status", "revocation_snapshot_sha256", "kit_id", "catalog_sha256",
        "manifest_sha256", "manifest_digest", "zip_sha256", "zip_sidecar_sha256",
        "work_commit", "work_tree", "work_branch", "upstream_cutoff", "fork_dev_cutoff",
        "package_id", "target", "compile_status", "release_eligible", "generation_command",
        "primary_directory_verifier_report_digest", "comparison_directory_verifier_report_digest",
        "primary_zip_verifier_report_digest", "comparison_zip_verifier_report_digest",
        "prepared_record_id", "review_record_id", "reference_contract",
    }
)
REFERENCE_FIELDS = frozenset(
    {"status", "contract_id", "contract_version", "contract_body_digest",
     "reference_definitions", "observations", "transitions", "path_policy", "approval"}
)
PATH_POLICY_FIELDS = frozenset({"allowed_root_kinds", "allow_user_paths"})
APPROVED_CUTOFF = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
REPOSITORY = "doylenehemiah6893-afk/Macro_menu"
BRANCH = "codex/dev-review-report"


@dataclass(frozen=True, order=True)
class CollectorDiagnostic:
    code: str
    path: str = ""
    message: str = ""


@dataclass(frozen=True)
class CollectorResult:
    ok: bool
    exit_code: int
    diagnostics: tuple[CollectorDiagnostic, ...]
    facts: Mapping[str, object]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.diagnostics)


def _result(*, facts: Mapping[str, object] | None = None) -> CollectorResult:
    return CollectorResult(True, 0, (), MappingProxyType(dict(facts or {})))


def _failure(error: CollectorError, *, exit_code: int = 3) -> CollectorResult:
    return CollectorResult(
        False,
        exit_code,
        (CollectorDiagnostic(error.code, error.detail or "", error.code),),
        MappingProxyType({}),
    )


def _now(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CollectorError("COLLECTOR_TIME_INVALID")
        return value.astimezone(UTC)
    if type(value) is not str or UTC_RE.fullmatch(value) is None:
        raise CollectorError("COLLECTOR_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CollectorError("COLLECTOR_TIME_INVALID") from error
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _operation_now(clock: Callable[[], datetime] | None) -> datetime:
    value = datetime.now(UTC) if clock is None else clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CollectorError("COLLECTOR_CLOCK_INVALID")
    return value.astimezone(UTC)


def _require_runtime() -> None:
    if platform.python_implementation() != "CPython":
        raise CollectorError("COLLECTOR_CPYTHON_REQUIRED")
    if sys.version_info[:2] != (3, 12):
        raise CollectorError("COLLECTOR_PYTHON_312_REQUIRED")
    if platform.system() != "Windows":
        raise CollectorError("COLLECTOR_NATIVE_WINDOWS_REQUIRED")


def _require_dict(value: object, code: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CollectorError(code)
    return value


def _require_exact_keys(value: Mapping[str, object], keys: frozenset[str], code: str) -> None:
    if frozenset(value) != keys:
        raise CollectorError(code)


def _portable_key(path: str) -> str:
    return "/".join(unicodedata.normalize("NFKC", part).casefold() for part in path.split("/"))


def _validate_member_path(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or any(
            ord(character) < 0x20
            or ord(character) > 0x7E
            or character in WINDOWS_INVALID_CHARS
            for character in value
        )
    ):
        raise CollectorError("COLLECTOR_MEMBER_PATH_INVALID")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or value.startswith("//")
        or "/".join(posix.parts) != value
        or any(part in {"", ".", ".."} for part in posix.parts)
        or any(part.endswith((" ", ".")) or ":" in part for part in posix.parts)
        or any(part.split(".", 1)[0].upper() in WINDOWS_RESERVED for part in posix.parts)
    ):
        raise CollectorError("COLLECTOR_MEMBER_PATH_INVALID", value)
    return value


def _validate_member_records(value: object) -> tuple[dict[str, Any], ...]:
    if type(value) is not list or not value or len(value) > MAX_MEMBER_COUNT:
        raise CollectorError("COLLECTOR_SKELETON_MEMBERS_INVALID")
    result: list[dict[str, Any]] = []
    control_key = _portable_key("session.json")
    portable: set[str] = {control_key}
    portable_parts: list[tuple[str, ...]] = [tuple(control_key.split("/"))]
    total_size = 0
    for raw in value:
        member = _require_dict(raw, "COLLECTOR_SKELETON_MEMBERS_INVALID")
        _require_exact_keys(member, MEMBER_FIELDS, "COLLECTOR_SKELETON_MEMBERS_INVALID")
        path = _validate_member_path(member.get("path"))
        digest = member.get("sha256")
        size = member.get("size")
        if type(digest) is not str or SHA256_RE.fullmatch(digest) is None:
            raise CollectorError("COLLECTOR_SKELETON_MEMBERS_INVALID", path)
        if type(size) is not int or size < 0:
            raise CollectorError("COLLECTOR_SKELETON_MEMBERS_INVALID", path)
        if size > MAX_MEMBER_BYTES:
            raise CollectorError("COLLECTOR_FILE_TOO_LARGE", path)
        total_size += size
        if total_size > MAX_TOTAL_MEMBER_BYTES:
            raise CollectorError("COLLECTOR_TOTAL_SIZE_TOO_LARGE")
        key = _portable_key(path)
        parts = tuple(key.split("/"))
        if (
            key in portable
            or any(
                parts[: len(other)] == other or other[: len(parts)] == parts
                for other in portable_parts
            )
        ):
            raise CollectorError("COLLECTOR_MEMBER_PATH_COLLISION", path)
        portable.add(key)
        portable_parts.append(parts)
        result.append(member)
    return tuple(result)


def _path_has_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _safe_absolute_path(path: Path, *, leaf_may_be_missing: bool = False) -> Path:
    """Validate every lexical ancestor without resolving links or junctions."""

    absolute = _lexical_absolute(path)
    chain = list(reversed((absolute, *absolute.parents)))
    for candidate in chain:
        is_leaf = candidate == absolute
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if is_leaf and leaf_may_be_missing:
                continue
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(candidate))
        except OSError as error:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(candidate)) from error
        if stat.S_ISLNK(info.st_mode) or _path_has_reparse(info):
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(candidate))
        if not is_leaf and not stat.S_ISDIR(info.st_mode):
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(candidate))
    return absolute


def _chain_snapshot(path: Path) -> tuple[Path, tuple[tuple[str, int, int, int, int], ...]]:
    absolute = _safe_absolute_path(path)
    result: list[tuple[str, int, int, int, int]] = []
    for candidate in reversed((absolute, *absolute.parents)):
        try:
            info = candidate.lstat()
        except OSError as error:
            raise CollectorError("COLLECTOR_PATH_UNSAFE", str(candidate)) from error
        result.append(
            (
                os.fspath(candidate), info.st_dev, info.st_ino, info.st_mode,
                getattr(info, "st_file_attributes", 0),
            )
        )
    return absolute, tuple(result)


def _stable_read(path: Path, *, max_bytes: int) -> tuple[bytes, str]:
    absolute, before = _chain_snapshot(path)
    try:
        leaf_before = absolute.lstat()
        if not stat.S_ISREG(leaf_before.st_mode) or leaf_before.st_nlink != 1:
            raise CollectorError("COLLECTOR_FILE_UNSAFE", str(absolute))
        with absolute.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or _path_has_reparse(opened)
                or (opened.st_dev, opened.st_ino) != (leaf_before.st_dev, leaf_before.st_ino)
            ):
                raise CollectorError("COLLECTOR_FILE_UNSAFE", str(absolute))
            data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise CollectorError("COLLECTOR_FILE_TOO_LARGE", str(absolute))
            opened_after = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                opened_after.st_dev, opened_after.st_ino, opened_after.st_size, opened_after.st_mtime_ns
            ):
                raise CollectorError("COLLECTOR_FILE_CHANGED", str(absolute))
    except CollectorError:
        raise
    except OSError as error:
        raise CollectorError("COLLECTOR_FILE_READ_ERROR", str(absolute)) from error
    _absolute_after, after = _chain_snapshot(absolute)
    if before != after:
        raise CollectorError("COLLECTOR_FILE_CHANGED", str(absolute))
    return data, hashlib.sha256(data).hexdigest()


def _read_control(path: Path, *, max_bytes: int = MAX_CONTROL_BYTES) -> tuple[dict[str, Any], str]:
    data, digest = _stable_read(path, max_bytes=max_bytes)
    document = _require_dict(parse_canonical_json_bytes(data), "COLLECTOR_JSON_INVALID")
    return document, digest


def _node_signature(path: Path) -> tuple[int, int, int, int, int, int, int]:
    info = path.lstat()
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, getattr(info, "st_file_attributes", 0),
    )


def _bundle_tree(bundle: Path) -> tuple[tuple[str, bytes], ...]:
    """Read every regular immutable bundle member with portable-name checks."""

    try:
        root = _safe_absolute_path(bundle)
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode):
            raise CollectorError("COLLECTOR_BUNDLE_TREE_INVALID")
        directories = {root: _node_signature(root)}
        portable: set[str] = set()
        records: list[tuple[str, bytes]] = []
        total = 0
        for path in sorted(
            root.rglob("*"),
            key=lambda item: item.relative_to(root).as_posix().encode("ascii"),
        ):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or _path_has_reparse(info):
                raise CollectorError("COLLECTOR_BUNDLE_TREE_INVALID", str(path))
            if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                raise CollectorError("COLLECTOR_BUNDLE_TREE_INVALID", str(path))
            relative = _validate_member_path(path.relative_to(root).as_posix())
            key = _portable_key(relative)
            if key in portable:
                raise CollectorError("COLLECTOR_BUNDLE_PATH_COLLISION", relative)
            portable.add(key)
            if stat.S_ISDIR(info.st_mode):
                directories[path] = _node_signature(path)
                continue
            if relative.casefold().endswith(BUNDLE_FORBIDDEN_SUFFIXES):
                raise CollectorError("COLLECTOR_BUNDLE_FORBIDDEN_PAYLOAD", relative)
            data, _digest = _stable_read(path, max_bytes=MAX_BUNDLE_MEMBER_BYTES)
            total += len(data)
            if len(records) >= MAX_BUNDLE_MEMBER_COUNT:
                raise CollectorError("COLLECTOR_BUNDLE_MEMBER_LIMIT")
            if total > MAX_BUNDLE_TOTAL_BYTES:
                raise CollectorError("COLLECTOR_BUNDLE_SIZE_LIMIT")
            records.append((relative, data))
        if any(_node_signature(path) != signature for path, signature in directories.items()):
            raise CollectorError("COLLECTOR_BUNDLE_TREE_CHANGED")
    except CollectorError:
        raise
    except (OSError, UnicodeError) as error:
        raise CollectorError("COLLECTOR_BUNDLE_TREE_INVALID") from error
    return tuple(records)


def _bundle_member_digest(records: tuple[tuple[str, bytes], ...]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            [{"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)} for path, data in records]
        )
    ).hexdigest()


def _bundle_sums(records: tuple[tuple[str, bytes], ...]) -> bytes:
    return b"".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n".encode("ascii")
        for path, data in records
        if path != "SHA256SUMS"
    )


def _paths_overlap(first: Path, second: Path) -> bool:
    first_text = os.fspath(first)
    second_text = os.fspath(second)
    if platform.system() == "Windows":
        first_text = first_text.casefold()
        second_text = second_text.casefold()
    try:
        common = os.path.commonpath((first_text, second_text))
    except ValueError:
        return False
    return common == first_text or common == second_text


def _validate_ledger(document: object, *, handoff_id: str, now: datetime, source: str) -> None:
    ledger = _require_dict(document, "COLLECTOR_LEDGER_INVALID")
    _require_exact_keys(ledger, LEDGER_FIELDS, "COLLECTOR_LEDGER_INVALID")
    if ledger.get("schema_version") != 1 or type(ledger.get("schema_version")) is not int:
        raise CollectorError("COLLECTOR_LEDGER_INVALID")
    if ledger.get("source") != source or SOURCE_RE.fullmatch(source) is None:
        raise CollectorError("COLLECTOR_LEDGER_SOURCE_MISMATCH")
    active = ledger.get("active_handoff_ids")
    withdrawn = ledger.get("withdrawn_handoff_ids")
    if type(active) is not list or type(withdrawn) is not list:
        raise CollectorError("COLLECTOR_LEDGER_INVALID")
    if not all(type(item) is str and HANDOFF_RE.fullmatch(item) for item in active + withdrawn):
        raise CollectorError("COLLECTOR_LEDGER_INVALID")
    if len(active) != len(set(active)) or len(withdrawn) != len(set(withdrawn)) or set(active) & set(withdrawn):
        raise CollectorError("COLLECTOR_LEDGER_INVALID")
    captured_at = _now(ledger.get("captured_at"))
    if captured_at > now:
        raise CollectorError("COLLECTOR_LEDGER_CAPTURED_IN_FUTURE")
    if now - captured_at > LEDGER_MAX_AGE:
        raise CollectorError("COLLECTOR_LEDGER_STALE")
    if handoff_id in withdrawn:
        raise CollectorError("COLLECTOR_HANDOFF_WITHDRAWN")
    if handoff_id not in active:
        raise CollectorError("COLLECTOR_HANDOFF_NOT_ACTIVE")


def _sha(value: object) -> bool:
    return type(value) is str and SHA256_RE.fullmatch(value) is not None


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _validate_provenance(provenance: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    _require_exact_keys(provenance, PROVENANCE_FIELDS, "COLLECTOR_PROVENANCE_INVALID")
    constants = {
        "schema_version": 1, "repository": REPOSITORY, "branch": BRANCH,
        "approved_cutoff": APPROVED_CUTOFF, "active_ledger_schema_version": 1,
        "python_requirement": "CPython 3.12", "compile_status": "not-run",
        "target_case_status": "not-run", "artifact_status": "not-produced",
        "release_eligible": False,
    }
    if any(provenance.get(key) != expected for key, expected in constants.items()):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    if type(provenance.get("schema_version")) is not int or provenance.get("release_eligible") is not False:
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    if not all(_matches(OID_RE, provenance.get(key)) for key in ("evidence_commit", "evidence_tree", "collector_source_commit")):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    if provenance.get("collector_source_commit") != provenance.get("evidence_commit"):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    digest_fields = (
        "catalog_sha256", "manifest_sha256", "manifest_digest", "kit_zip_sha256",
        "kit_sidecar_sha256", "handoff_sha256", "issuance_revocation_snapshot_sha256",
        "bundle_content_sha256", "collector_source_sha256", "collector_pyz_sha256", "session_skeleton_sha256",
        "tutorials_sha256", "templates_sha256", "schemas_sha256",
    )
    if not all(_sha(provenance.get(key)) for key in digest_fields):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    if not _matches(KIT_RE, provenance.get("kit_id")) or not _matches(HANDOFF_RE, provenance.get("handoff_id")):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    if not _matches(SOURCE_RE, provenance.get("active_ledger_source")):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    if not all(_matches(RECORD_RE, provenance.get(key)) for key in ("generation_record_id", "test_record_id", "review_record_id")):
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    _now(provenance.get("handoff_created_at"))
    _now(provenance.get("handoff_expires_at"))
    return _validate_member_records(provenance.get("session_skeleton_members"))


def _validate_reference_contract(value: object) -> None:
    contract = _require_dict(value, "COLLECTOR_HANDOFF_INVALID")
    _require_exact_keys(contract, REFERENCE_FIELDS, "COLLECTOR_HANDOFF_INVALID")
    if (
        contract.get("status") != "discovery-required"
        or contract.get("contract_id") != "reference-contract-core"
        or type(contract.get("contract_version")) is not int
        or contract.get("contract_version") != 1
        or not _sha(contract.get("contract_body_digest"))
        or contract.get("reference_definitions") != []
        or contract.get("observations") is not None
        or contract.get("transitions") is not None
        or contract.get("approval") is not None
    ):
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    policy = _require_dict(contract.get("path_policy"), "COLLECTOR_HANDOFF_INVALID")
    _require_exact_keys(policy, PATH_POLICY_FIELDS, "COLLECTOR_HANDOFF_INVALID")
    roots = policy.get("allowed_root_kinds")
    allowed = {"catia-install", "windows-install", "system"}
    if (
        type(roots) is not list or not roots or not all(type(item) is str and item in allowed for item in roots)
        or len(roots) != len(set(roots)) or policy.get("allow_user_paths") is not False
    ):
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")


def _validate_handoff(document: object, provenance: Mapping[str, Any], now: datetime) -> str:
    handoff = _require_dict(document, "COLLECTOR_HANDOFF_INVALID")
    _require_exact_keys(handoff, HANDOFF_FIELDS, "COLLECTOR_HANDOFF_INVALID")
    constants = {
        "schema_version": 1, "purpose": "discovery", "revocation_status": "active",
        "package_id": "core", "target": "CATIA R2018/VBA7 64",
        "compile_status": "not-run", "release_eligible": False,
    }
    if any(handoff.get(key) != expected for key, expected in constants.items()):
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    if type(handoff.get("schema_version")) is not int or handoff.get("release_eligible") is not False:
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    handoff_id = handoff.get("handoff_id")
    if type(handoff_id) is not str or HANDOFF_RE.fullmatch(handoff_id) is None:
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    if handoff_id != provenance.get("handoff_id"):
        raise CollectorError("COLLECTOR_HANDOFF_ID_MISMATCH")
    created = _now(handoff.get("created_at"))
    expires = _now(handoff.get("expires_at"))
    if handoff.get("created_at") != provenance.get("handoff_created_at") or handoff.get(
        "expires_at"
    ) != provenance.get("handoff_expires_at"):
        raise CollectorError("COLLECTOR_HANDOFF_TIME_MISMATCH")
    if created > now:
        raise CollectorError("COLLECTOR_HANDOFF_NOT_YET_VALID")
    if expires <= now:
        raise CollectorError("COLLECTOR_HANDOFF_EXPIRED")
    digest_fields = (
        "revocation_snapshot_sha256", "catalog_sha256", "manifest_sha256", "manifest_digest",
        "zip_sha256", "zip_sidecar_sha256", "primary_directory_verifier_report_digest",
        "comparison_directory_verifier_report_digest", "primary_zip_verifier_report_digest",
        "comparison_zip_verifier_report_digest",
    )
    if not all(_sha(handoff.get(key)) for key in digest_fields):
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    if not all(_matches(OID_RE, handoff.get(key)) for key in ("work_commit", "work_tree", "upstream_cutoff", "fork_dev_cutoff")):
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    if not all(_matches(RECORD_RE, handoff.get(key)) for key in ("prepared_record_id", "review_record_id")):
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    if type(handoff.get("generation_command")) is not str or not 1 <= len(handoff["generation_command"]) <= 500:
        raise CollectorError("COLLECTOR_HANDOFF_INVALID")
    bindings = {
        "kit_id": "kit_id", "catalog_sha256": "catalog_sha256",
        "manifest_sha256": "manifest_sha256", "manifest_digest": "manifest_digest",
        "zip_sha256": "kit_zip_sha256", "zip_sidecar_sha256": "kit_sidecar_sha256",
        "revocation_snapshot_sha256": "issuance_revocation_snapshot_sha256",
        "work_commit": "evidence_commit", "work_tree": "evidence_tree", "work_branch": "branch",
    }
    if any(handoff.get(left) != provenance.get(right) for left, right in bindings.items()):
        raise CollectorError("COLLECTOR_HANDOFF_BINDING_MISMATCH")
    if handoff.get("upstream_cutoff") != APPROVED_CUTOFF or handoff.get("fork_dev_cutoff") != APPROVED_CUTOFF:
        raise CollectorError("COLLECTOR_HANDOFF_BINDING_MISMATCH")
    _validate_reference_contract(handoff.get("reference_contract"))
    return handoff_id


def _load_preflight(
    *, bundle: Path, current: Path, ledger: Path, _clock: Callable[[], datetime] | None
) -> dict[str, object]:
    _require_runtime()
    now = _operation_now(_clock)
    bundle = _safe_absolute_path(Path(bundle))
    current = _safe_absolute_path(Path(current))
    ledger = _safe_absolute_path(Path(ledger))
    if _paths_overlap(bundle, current) or _paths_overlap(bundle, ledger):
        raise CollectorError("COLLECTOR_EXTERNAL_STATE_REQUIRED")
    tree = _bundle_tree(bundle)
    file_map = dict(tree)
    if "provenance.json" not in file_map or "SHA256SUMS" not in file_map:
        raise CollectorError("COLLECTOR_BUNDLE_REQUIRED_FILE_MISSING")
    provenance_bytes = file_map["provenance.json"]
    provenance = _require_dict(
        parse_canonical_json_bytes(provenance_bytes), "COLLECTOR_JSON_INVALID"
    )
    provenance_digest = hashlib.sha256(provenance_bytes).hexdigest()
    members = _validate_provenance(provenance)
    if file_map["SHA256SUMS"] != _bundle_sums(tree):
        raise CollectorError("COLLECTOR_BUNDLE_SHA256SUMS_INVALID")
    content = tuple(
        (path, data)
        for path, data in tree
        if path not in {"provenance.json", "SHA256SUMS"}
    )
    if _bundle_member_digest(content) != provenance["bundle_content_sha256"]:
        raise CollectorError("COLLECTOR_BUNDLE_CONTENT_MISMATCH")
    current_document, _current_digest = _read_control(current)
    _require_exact_keys(current_document, CURRENT_FIELDS, "COLLECTOR_CURRENT_INVALID")
    bundle_id = "bundle-" + provenance_digest[:24]
    if (
        current_document.get("schema_version") != 1
        or type(current_document.get("schema_version")) is not int
        or current_document.get("bundle_id") != bundle_id
        or BUNDLE_RE.fullmatch(bundle_id) is None
        or current_document.get("bundle_sha256") != provenance_digest
    ):
        raise CollectorError("COLLECTOR_CURRENT_BUNDLE_MISMATCH")
    kit_id = provenance.get("kit_id")
    try:
        skeleton_bytes = file_map["session-skeleton.zip"]
        handoff_bytes = file_map["handoff.json"]
        kit_zip = file_map[f"{kit_id}.zip"]
        kit_sidecar = file_map[f"{kit_id}.zip.sha256"]
        pyz = file_map["target-discovery.pyz"]
        pyz_sidecar = file_map["target-discovery.pyz.sha256"]
    except KeyError as error:
        raise CollectorError("COLLECTOR_BUNDLE_REQUIRED_FILE_MISSING", str(error)) from error
    if len(skeleton_bytes) > MAX_SKELETON_BYTES:
        raise CollectorError("COLLECTOR_FILE_TOO_LARGE", "session-skeleton.zip")
    skeleton_digest = hashlib.sha256(skeleton_bytes).hexdigest()
    if skeleton_digest != provenance.get("session_skeleton_sha256"):
        raise CollectorError("COLLECTOR_SKELETON_HASH_MISMATCH")
    if (
        hashlib.sha256(kit_zip).hexdigest() != provenance.get("kit_zip_sha256")
        or kit_sidecar != f"{provenance['kit_zip_sha256']}  {kit_id}.zip\n".encode("ascii")
        or hashlib.sha256(pyz).hexdigest() != provenance.get("collector_pyz_sha256")
        or pyz_sidecar != f"{provenance['collector_pyz_sha256']}  target-discovery.pyz\n".encode("ascii")
    ):
        raise CollectorError("COLLECTOR_BUNDLE_MEMBER_BINDING_MISMATCH")
    handoff = _require_dict(parse_canonical_json_bytes(handoff_bytes), "COLLECTOR_JSON_INVALID")
    handoff_digest = hashlib.sha256(handoff_bytes).hexdigest()
    if handoff_digest != provenance.get("handoff_sha256"):
        raise CollectorError("COLLECTOR_HANDOFF_HASH_MISMATCH")
    handoff_id = _validate_handoff(handoff, provenance, now)
    if current_document.get("handoff_id") != handoff_id:
        raise CollectorError("COLLECTOR_CURRENT_HANDOFF_MISMATCH")
    source = provenance.get("active_ledger_source")
    if provenance.get("active_ledger_schema_version") != 1 or type(source) is not str:
        raise CollectorError("COLLECTOR_PROVENANCE_INVALID")
    ledger_document, _ledger_digest = _read_control(ledger)
    _validate_ledger(ledger_document, handoff_id=handoff_id, now=now, source=source)
    return {
        "bundle": bundle,
        "bundle_id": bundle_id,
        "handoff_id": handoff_id,
        "kit_id": kit_id,
        "members": members,
        "observed_at": _utc_text(now),
        "skeleton_bytes": skeleton_bytes,
    }


def preflight(
    *,
    bundle: Path,
    current: Path,
    ledger: Path,
    _clock: Callable[[], datetime] | None = None,
) -> CollectorResult:
    """Authenticate an immutable bundle plus fresh external mutable state."""

    try:
        facts = _load_preflight(
            bundle=Path(bundle), current=Path(current), ledger=Path(ledger), _clock=_clock
        )
    except CollectorError as error:
        exit_code = 4 if error.code in {
            "COLLECTOR_CPYTHON_REQUIRED",
            "COLLECTOR_PYTHON_312_REQUIRED",
            "COLLECTOR_NATIVE_WINDOWS_REQUIRED",
        } else 3
        return _failure(error, exit_code=exit_code)
    public = {key: value for key, value in facts.items() if key not in {"bundle", "members", "skeleton_bytes"}}
    return _result(facts=public)


def _zip_member_is_regular(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == 0 or stat.S_ISREG(mode)


def _write_exclusive(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(path)) from error
    except OSError as error:
        raise CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(path)) from error


def _plan_skeleton(skeleton_bytes: bytes, members: tuple[dict[str, Any], ...]) -> tuple[tuple[str, bytes], ...]:
    expected = {item["path"]: item for item in members}
    planned: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(skeleton_bytes), "r") as archive:
            infos: dict[str, zipfile.ZipInfo] = {}
            all_infos = archive.infolist()
            if len(all_infos) > MAX_MEMBER_COUNT:
                raise CollectorError("COLLECTOR_MEMBER_COUNT_EXCEEDED")
            for info in all_infos:
                if info.filename in infos:
                    raise CollectorError("COLLECTOR_MEMBER_DUPLICATE", info.filename)
                infos[info.filename] = info
            actual_paths = set(infos)
            expected_paths = set(expected)
            if actual_paths - expected_paths:
                raise CollectorError("COLLECTOR_MEMBER_EXTRA", sorted(actual_paths - expected_paths)[0])
            if expected_paths - actual_paths:
                raise CollectorError(
                    "COLLECTOR_MEMBER_MISSING", sorted(expected_paths - actual_paths)[0]
                )
            for path, member in expected.items():
                info = infos.get(path)
                if info is None:
                    raise CollectorError("COLLECTOR_MEMBER_MISSING", path)
                if not _zip_member_is_regular(info):
                    raise CollectorError("COLLECTOR_MEMBER_UNSAFE", path)
                if (
                    info.compress_type != zipfile.ZIP_STORED
                    or info.flag_bits & ~0x800
                    or info.extra
                    or info.compress_size != info.file_size
                ):
                    raise CollectorError("COLLECTOR_MEMBER_UNSUPPORTED", path)
                if info.file_size != member["size"] or info.file_size > MAX_MEMBER_BYTES:
                    raise CollectorError("COLLECTOR_MEMBER_SIZE_MISMATCH", path)
                with archive.open(info, "r") as stream:
                    data = stream.read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES:
                    raise CollectorError("COLLECTOR_FILE_TOO_LARGE", path)
                if hashlib.sha256(data).hexdigest() != member["sha256"]:
                    raise CollectorError("COLLECTOR_MEMBER_HASH_MISMATCH", path)
                planned.append((path, data))
    except CollectorError:
        raise
    except (OSError, EOFError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as error:
        raise CollectorError("COLLECTOR_SKELETON_INVALID") from error
    return tuple(planned)


def _new_staging(capture: Path) -> Path:
    for _attempt in range(16):
        candidate = capture.with_name(f".{capture.name}.staging-{secrets.token_hex(8)}")
        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        except OSError as error:
            raise CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(candidate)) from error
        return candidate
    raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(capture))


def init_capture(
    *,
    bundle: Path,
    current: Path,
    ledger: Path,
    capture: Path,
    _clock: Callable[[], datetime] | None = None,
) -> CollectorResult:
    """Create one new raw/untrusted capture without changing the bundle tree."""

    try:
        bundle_absolute = _safe_absolute_path(Path(bundle))
        capture_lexical = _lexical_absolute(Path(capture))
        if _paths_overlap(bundle_absolute, capture_lexical):
            raise CollectorError("COLLECTOR_PATH_OVERLAP")
        capture = _safe_absolute_path(Path(capture), leaf_may_be_missing=True)
    except CollectorError as error:
        return _failure(error)
    if capture.exists() or capture.is_symlink():
        return _failure(CollectorError("COLLECTOR_OUTPUT_EXISTS", str(capture)))
    try:
        facts = _load_preflight(
            bundle=Path(bundle), current=Path(current), ledger=Path(ledger), _clock=_clock
        )
        plan = _plan_skeleton(facts["skeleton_bytes"], facts["members"])
        observed = str(facts["observed_at"])
        session_id = "session-" + re.sub(r"[^0-9]", "", observed)[:14] + "-raw"
        session = {
            "schema_version": 1,
            "session_id": session_id,
            "created_at": observed,
            "capture_status": "in-progress",
            "trust_level": TRUST_LEVEL,
            "mode": SESSION_MODE,
            "package_id": PACKAGE_ID,
            "profile_id": PROFILE_ID,
            "bundle_id": facts["bundle_id"],
            "kit_id": facts["kit_id"],
            "handoff_id": facts["handoff_id"],
            "compile_status": "not-run",
            "target_case_status": "not-run",
            "artifact_status": "not-produced",
            "release_eligible": False,
        }
        staging = _new_staging(capture)
        try:
            for member_path, data in plan:
                _write_exclusive(staging.joinpath(*PurePosixPath(member_path).parts), data)
            _write_exclusive(staging / "session.json", canonical_json_bytes(session))
            _safe_absolute_path(capture.parent)
            if capture.exists() or capture.is_symlink():
                raise CollectorError("COLLECTOR_OUTPUT_EXISTS", str(capture))
            staging.replace(capture)
            staging = None
        finally:
            if staging is not None and staging.exists():
                try:
                    shutil.rmtree(staging)
                except OSError as error:
                    raise CollectorError("COLLECTOR_STAGING_CLEANUP_FAILED", str(staging)) from error
    except FileExistsError:
        return _failure(CollectorError("COLLECTOR_OUTPUT_EXISTS", str(capture)))
    except OSError as error:
        return _failure(CollectorError("COLLECTOR_OUTPUT_WRITE_ERROR", str(capture)))
    except CollectorError as error:
        return _failure(error)
    return _result(
        facts={
            "session_dir": str(capture),
            "session_id": session_id,
            "capture_status": "in-progress",
            "trust_level": TRUST_LEVEL,
        }
    )


def status(capture: Path) -> CollectorResult:
    """Read the canonical session state without deriving any Gate result."""

    try:
        capture = _safe_absolute_path(Path(capture))
        session_path = _safe_absolute_path(capture / "session.json")
        session, _session_digest = _read_control(session_path)
        if (
            frozenset(session) != SESSION_FIELDS
            or type(session.get("schema_version")) is not int
            or session.get("schema_version") != 1
            or type(session.get("session_id")) is not str
            or SESSION_RE.fullmatch(session["session_id"]) is None
            or type(session.get("created_at")) is not str
            or session.get("capture_status") != "in-progress"
            or session.get("trust_level") != TRUST_LEVEL
            or session.get("mode") != SESSION_MODE
            or session.get("package_id") != PACKAGE_ID
            or session.get("profile_id") != PROFILE_ID
            or type(session.get("bundle_id")) is not str
            or BUNDLE_RE.fullmatch(session["bundle_id"]) is None
            or type(session.get("kit_id")) is not str
            or KIT_RE.fullmatch(session["kit_id"]) is None
            or type(session.get("handoff_id")) is not str
            or HANDOFF_RE.fullmatch(session["handoff_id"]) is None
            or session.get("compile_status") != "not-run"
            or session.get("target_case_status") != "not-run"
            or session.get("artifact_status") != "not-produced"
            or session.get("release_eligible") is not False
        ):
            raise CollectorError("COLLECTOR_SESSION_INVALID")
        _now(session["created_at"])
        from .records import (
            POINT_ORDER,
            validate_entitlements_document,
            validate_environment_document,
            validate_operator_index_files,
            validate_references_document,
        )

        def optional_document(name: str) -> dict[str, Any] | None:
            path = capture / name
            if not path.exists():
                return None
            document, _digest = _read_control(path)
            return document

        environment = optional_document("environment.json")
        entitlements = optional_document("entitlements.json")
        references = optional_document("references.json")
        if environment is not None:
            validate_environment_document(environment)
        if entitlements is not None:
            validate_entitlements_document(entitlements)
        reference_points: tuple[str, ...] = ()
        if references is not None:
            validated = validate_references_document(references)
            observations = validated.get("observations")
            if type(observations) is not list:
                raise CollectorError("COLLECTOR_REFERENCES_INVALID")
            reference_points = tuple(
                str(item.get("point_id"))
                for item in observations
                if type(item) is dict
            )
            if reference_points != POINT_ORDER[:len(reference_points)]:
                raise CollectorError("COLLECTOR_REFERENCES_INVALID")
        operator_root = capture / "operator-records"
        index_path = operator_root / "index.json"
        operator_record_count = 0
        operator_records_valid = False
        if index_path.exists():
            operator_root = _safe_absolute_path(operator_root)
            files: dict[str, bytes] = {}
            try:
                candidates = sorted(
                    operator_root.rglob("*"),
                    key=lambda item: item.relative_to(capture).as_posix().encode("ascii"),
                )
            except (OSError, UnicodeError) as error:
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID") from error
            for candidate in candidates:
                info = candidate.lstat()
                if stat.S_ISLNK(info.st_mode) or _path_has_reparse(info):
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID", str(candidate))
                if stat.S_ISDIR(info.st_mode):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID", str(candidate))
                relative = candidate.relative_to(capture).as_posix()
                files[relative], _digest = _stable_read(candidate, max_bytes=MAX_MEMBER_BYTES)
            validate_operator_index_files(files)
            document = parse_canonical_json_bytes(files["operator-records/index.json"])
            if type(document) is not dict or type(document.get("records")) is not list:
                raise CollectorError("COLLECTOR_OPERATOR_INDEX_INVALID")
            operator_record_count = len(document["records"])
            operator_records_valid = True
        required = {
            "environment": environment is not None,
            "entitlements": entitlements is not None,
            "reference_points": reference_points,
            "operator_records_valid": operator_records_valid,
        }
        if environment is None:
            next_action = "record-environment"
        elif entitlements is None:
            next_action = "record-entitlements"
        elif len(reference_points) < len(POINT_ORDER):
            next_action = f"import-reference-csv:{POINT_ORDER[len(reference_points)]}"
        elif not operator_records_valid:
            next_action = "add-operator-record"
        else:
            next_action = "finalize-raw"
    except CollectorError as error:
        return _failure(error)
    return _result(
        facts={
            "session_id": session.get("session_id"),
            "capture_status": session.get("capture_status"),
            "trust_level": TRUST_LEVEL,
            "environment_recorded": required["environment"],
            "entitlements_recorded": required["entitlements"],
            "reference_points_recorded": list(required["reference_points"]),
            "reference_points_required": list(POINT_ORDER),
            "operator_records_valid": required["operator_records_valid"],
            "operator_record_count": operator_record_count,
            "ready_to_finalize_raw": next_action == "finalize-raw",
            "next_action": next_action,
            "gate_evaluated": False,
        }
    )
