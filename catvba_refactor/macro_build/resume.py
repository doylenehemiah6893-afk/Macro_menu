from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from .errors import ConfigError, EvidenceError
from .model import ValidationReport
from .portable_paths import portable_key, validate_portable_ascii_paths


_LEDGER_FIELDS = frozenset(
    {
        "schema_version",
        "captured_at",
        "source",
        "active_handoff_ids",
        "withdrawn_handoff_ids",
    }
)
_HANDOFF_ID = re.compile(r"^handoff-[a-z0-9][a-z0-9-]{2,94}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
_RAW_CAPTURE_MANIFEST_CONTROL_KEY = portable_key("raw-capture-manifest.json")
_RAW_CAPTURE_SHA256SUMS_PATH = "SHA256SUMS"


def _is_strict_integer(checker: object, instance: object) -> bool:
    del checker
    return type(instance) is int


StrictDraft202012Validator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", _is_strict_integer
    ),
)


def _ledger_error(code: str) -> EvidenceError:
    return EvidenceError(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"duplicate JSON key: {key}")
        document[key] = value
    return document


def _read_json(path: Path, *, read_code: str, json_code: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConfigError(read_code) from error
    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as error:
        raise ConfigError(json_code) from error


def _require_internal_schema_references(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ConfigError("RESUME_STATE_SCHEMA_INVALID")
            _require_internal_schema_references(child)
    elif isinstance(value, list):
        for child in value:
            _require_internal_schema_references(child)


def load_resume_state(path: Path, schema_dir: Path) -> dict[str, Any]:
    """Read and strictly validate a resume state without changing the repository."""

    state = _read_json(
        Path(path),
        read_code="RESUME_STATE_READ_ERROR",
        json_code="RESUME_STATE_JSON_INVALID",
    )
    schema = _read_json(
        Path(schema_dir) / "resume-state.schema.json",
        read_code="RESUME_STATE_SCHEMA_READ_ERROR",
        json_code="RESUME_STATE_SCHEMA_INVALID",
    )
    if not isinstance(schema, dict):
        raise ConfigError("RESUME_STATE_SCHEMA_INVALID")
    try:
        Draft202012Validator.check_schema(schema)
        _require_internal_schema_references(schema)
        validator = StrictDraft202012Validator(
            schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = tuple(validator.iter_errors(state))
    except (SchemaError, Unresolvable) as error:
        raise ConfigError("RESUME_STATE_SCHEMA_INVALID") from error
    if errors or not isinstance(state, dict):
        raise ConfigError("RESUME_STATE_INVALID")
    return state


def _utc_timestamp(value: object) -> datetime | None:
    if type(value) is not str or _UTC_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def _handoff_ids(value: object) -> list[str] | None:
    if type(value) is not list:
        return None
    if not all(type(item) is str and _HANDOFF_ID.fullmatch(item) for item in value):
        return None
    if len(value) != len(set(value)):
        return None
    return value


def validate_active_ledger(
    document: Mapping[str, Any], *, effective_at: datetime
) -> ValidationReport:
    """Validate a current handoff ledger and its cross-field time semantics.

    JSON Schema owns the serialized shape contract.  This function repeats the
    security-relevant shape checks before enforcing facts that JSON Schema
    cannot express: disjoint active/withdrawn sets and a non-future capture.
    """

    if (
        not isinstance(document, Mapping)
        or frozenset(document) != _LEDGER_FIELDS
        or document.get("schema_version") != 1
        or type(document.get("schema_version")) is not int
        or type(document.get("source")) is not str
        or _SOURCE.fullmatch(document["source"]) is None
    ):
        raise _ledger_error("HANDOFF_LEDGER_INVALID")

    active = _handoff_ids(document.get("active_handoff_ids"))
    withdrawn = _handoff_ids(document.get("withdrawn_handoff_ids"))
    captured_at = _utc_timestamp(document.get("captured_at"))
    if active is None or withdrawn is None or captured_at is None:
        raise _ledger_error("HANDOFF_LEDGER_INVALID")
    if (
        not isinstance(effective_at, datetime)
        or effective_at.tzinfo is None
        or effective_at.utcoffset() is None
    ):
        raise _ledger_error("HANDOFF_LEDGER_EFFECTIVE_TIME_INVALID")
    if set(active) & set(withdrawn):
        raise _ledger_error("HANDOFF_LEDGER_ID_OVERLAP")
    if captured_at > effective_at.astimezone(UTC):
        raise _ledger_error("HANDOFF_LEDGER_CAPTURED_IN_FUTURE")
    return ValidationReport()


def validate_raw_capture_manifest(
    document: Mapping[str, Any],
) -> ValidationReport:
    """After schema validation, enforce cross-member portable path semantics."""

    if not isinstance(document, Mapping) or type(document.get("members")) is not list:
        raise EvidenceError("RAW_CAPTURE_MANIFEST_INVALID")
    paths: list[str] = []
    for member in document["members"]:
        if not isinstance(member, Mapping) or type(member.get("path")) is not str:
            raise EvidenceError("RAW_CAPTURE_MANIFEST_INVALID")
        paths.append(member["path"])

    if paths.count(_RAW_CAPTURE_SHA256SUMS_PATH) != 1:
        raise EvidenceError("RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID")
    if not validate_portable_ascii_paths(paths).ok:
        raise EvidenceError("RAW_CAPTURE_PATH_NAMESPACE_INVALID")
    if any(
        portable_key(path) == _RAW_CAPTURE_MANIFEST_CONTROL_KEY for path in paths
    ):
        raise EvidenceError("RAW_CAPTURE_CONTROL_PATH_RESERVED")
    return ValidationReport()
