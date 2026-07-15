from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import CannotDetermineSpecification, Unresolvable
from referencing.jsonschema import UnknownDialect

from ..errors import ConfigError
from ..model import Diagnostic, ValidationReport


_SCHEMA_FILES = (
    "common.schema.json",
    "session.schema.json",
    "environment.schema.json",
    "entitlements.schema.json",
    "references.schema.json",
    "compile-result.schema.json",
    "test-results.schema.json",
    "state-diff.schema.json",
    "artifact-manifest.schema.json",
    "operator-index.schema.json",
    "handoff.schema.json",
    "payload-manifest.schema.json",
    "gate-receipt.schema.json",
    "approval.schema.json",
    "session-complete.schema.json",
)

_SCHEMA_ID_BASE = "https://schemas.catvba.invalid/target-evidence/"

_DOCUMENT_SCHEMAS = {
    "session.json": "session.schema.json",
    "environment.json": "environment.schema.json",
    "entitlements.json": "entitlements.schema.json",
    "references.json": "references.schema.json",
    "compile-result.json": "compile-result.schema.json",
    "test-results.json": "test-results.schema.json",
    "state-diff.json": "state-diff.schema.json",
    "artifact-manifest.json": "artifact-manifest.schema.json",
    "operator-records/index.json": "operator-index.schema.json",
    "handoff.json": "handoff.schema.json",
    "payload-manifest.json": "payload-manifest.schema.json",
    "gate-receipt.json": "gate-receipt.schema.json",
    "approval.json": "approval.schema.json",
    "SESSION_COMPLETE": "session-complete.schema.json",
}


@dataclass(frozen=True)
class TargetEvidenceSchemaSet:
    validators: Mapping[str, Draft202012Validator]


def _schema_references(value: object) -> tuple[str, ...]:
    references: list[str] = []

    def visit(node: object, *, root: bool = False) -> None:
        if isinstance(node, dict):
            if not root and "$id" in node:
                raise ValueError("nested $id is not permitted")
            for key, child in node.items():
                if key in {"$ref", "$dynamicRef"} and isinstance(child, str):
                    references.append(child)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value, root=True)
    return tuple(references)


def load_target_evidence_schemas(schema_dir: str | Path) -> TargetEvidenceSchemaSet:
    root = Path(schema_dir)
    documents: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    seen_ids: set[str] = set()
    for filename in _SCHEMA_FILES:
        path = root / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"INVALID_TARGET_EVIDENCE_SCHEMA: {filename}"
            ) from exc
        if not isinstance(value, dict):
            raise ConfigError(f"INVALID_TARGET_EVIDENCE_SCHEMA: {filename}")
        expected_id = f"{_SCHEMA_ID_BASE}{filename}"
        schema_id = value.get("$id")
        if schema_id != expected_id or schema_id in seen_ids:
            raise ConfigError(f"INVALID_TARGET_EVIDENCE_SCHEMA: {filename}")
        try:
            Draft202012Validator.check_schema(value)
            _schema_references(value)
            resource = Resource.from_contents(value)
        except (
            CannotDetermineSpecification,
            SchemaError,
            UnknownDialect,
            ValueError,
        ) as exc:
            raise ConfigError(
                f"INVALID_TARGET_EVIDENCE_SCHEMA: {filename}"
            ) from exc
        seen_ids.add(schema_id)
        documents[filename] = value
        resources.append((schema_id, resource))

    registry = Registry().with_resources(resources).crawl()
    for filename in _SCHEMA_FILES:
        schema_id = f"{_SCHEMA_ID_BASE}{filename}"
        resolver = registry.resolver(schema_id)
        try:
            for reference in _schema_references(documents[filename]):
                resolver.lookup(reference)
        except (Unresolvable, ValueError) as exc:
            raise ConfigError(
                f"INVALID_TARGET_EVIDENCE_SCHEMA: {filename}"
            ) from exc
    validators = {
        filename: Draft202012Validator(
            documents[filename],
            registry=registry,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        for filename in _SCHEMA_FILES
    }
    return TargetEvidenceSchemaSet(MappingProxyType(validators))


def _pointer(parts: tuple[object, ...]) -> str:
    if not parts:
        return ""
    escaped = (
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )
    return "/" + "/".join(escaped)


def validate_target_document(
    filename: str,
    document: object,
    schemas: TargetEvidenceSchemaSet,
) -> ValidationReport:
    schema_filename = _DOCUMENT_SCHEMAS.get(filename, filename)
    validator = schemas.validators.get(schema_filename)
    if validator is None:
        return ValidationReport(
            (
                Diagnostic(
                    code="UNKNOWN_TARGET_EVIDENCE_DOCUMENT",
                    path=filename,
                    message="no target evidence schema is registered for this filename",
                ),
            )
        )

    try:
        errors = sorted(
            validator.iter_errors(document),
            key=lambda item: (
                tuple(str(part) for part in item.absolute_path),
                item.validator or "",
                item.message,
            ),
        )
    except Unresolvable:
        return ValidationReport(
            (
                Diagnostic(
                    code="TARGET_EVIDENCE_SCHEMA_UNRESOLVABLE",
                    path=f"{filename}#",
                    message="target evidence schema reference could not be resolved",
                ),
            )
        )
    diagnostics = tuple(
        Diagnostic(
            code="TARGET_EVIDENCE_SCHEMA_INVALID",
            path=f"{filename}#{_pointer(tuple(error.absolute_path))}",
            message=error.message,
        )
        for error in errors
    )
    return ValidationReport(diagnostics).sorted()
