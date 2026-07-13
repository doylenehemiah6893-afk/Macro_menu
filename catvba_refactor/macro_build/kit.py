from __future__ import annotations

import io
import json
import ctypes
import errno
import hashlib
import math
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_json_bytes, sha256_bytes
from .encoding import decode_vba
from .errors import InfrastructureError, SourceError
from .generator import (
    GENERATED_PATH,
    GENERATED_SOURCE_ID,
    generate_sources,
)
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
_STABLE_ID = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")
_VBA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TOOL_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_VB_NAME_ATTRIBUTE = re.compile(
    r'^Attribute\s+VB_Name\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_OLE_OBJECT_BLOB = re.compile(
    r'^OleObjectBlob\s*=\s*"([^":]+\.frx)":([0-9A-Fa-f]+)\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_WINDOWS_INVALID = frozenset('<>:"|?*')
_PACKAGE_FIELDS = frozenset(
    {"package_id", "classification", "additional_deny_tokens", "reference_allowlist"}
)
_PACKAGE_CLASSIFICATIONS = frozenset(
    {
        "CORE_CANDIDATE",
        "FLEET_EXTENSION_SPA",
        "FLEET_EXTENSION_FTA",
        "BASELINE_EXTENSION_CANDIDATE",
        "CATIA_LICENSED_OPTIONAL_CANDIDATE",
        "EXTERNAL_INTEGRATION_OPTIONAL",
        "DEVTOOLS",
        "QUARANTINE",
    }
)
_TOOL_FIELDS = frozenset(
    {
        "tool_id",
        "caption",
        "group_id",
        "package_id",
        "module_name",
        "entrypoint",
        "document_types",
        "required_capabilities",
        "risk_level",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "mode",
        "upstream_commit",
        "fork_dev_commit",
        "work_commit",
        "work_tree",
        "manifest_digest",
        "tool_version",
        "formal_eligible",
    }
)
_COMPONENT_FIELDS = frozenset(
    {
        "source_id",
        "origin",
        "component_type",
        "vb_name",
        "package_id",
        "disposition",
        "encoding_decision",
        "members",
    }
)
_MEMBER_FIELDS = frozenset({"path", "blob_oid", "raw_sha256", "role"})
_POLICY_FIELDS = frozenset({"compile_status", "diagnostics"})


def _json_safe(value: Any) -> Any:
    """Return an exact JSON value or fail closed.

    Catalog identity must never depend on Python repr(), implicit key coercion,
    filesystem objects, or extension types.  Exact built-in JSON types are the
    only accepted boundary values.
    """
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
        raise _source_error("CATALOG_RECORD_INVALID", "non-finite number")
    if type(value) is list:
        return [_json_safe(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise _source_error("CATALOG_RECORD_INVALID", "non-string JSON key")
        return {key: _json_safe(nested) for key, nested in value.items()}
    raise _source_error(
        "CATALOG_RECORD_INVALID", f"unsupported JSON type {type(value).__name__}"
    )


def _diagnostic_json(value: Any) -> Any:
    """Normalize code-owned diagnostic detail without repr-based ordering."""
    if isinstance(value, tuple):
        return [_diagnostic_json(item) for item in value]
    if isinstance(value, set):
        values = [_diagnostic_json(item) for item in value]
        return sorted(values, key=canonical_json_bytes)
    try:
        return _json_safe(value)
    except SourceError:
        return {"unsupported_type": type(value).__name__}


def _diagnostic_record(diagnostic: Diagnostic) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "path": diagnostic.path,
    }
    if diagnostic.details:
        record["details"] = _diagnostic_json(diagnostic.details)
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
        component.encoding_decision or "",
        tuple(_member_sort_key(member) for member in component.members),
    )


def _member_document_sort_key(member: Mapping[str, Any]) -> tuple[Any, ...]:
    """Mirror ``_member_sort_key`` at the untrusted JSON boundary."""
    role = member.get("role")
    path = member.get("path")
    raw_sha256 = member.get("raw_sha256")
    blob_oid = member.get("blob_oid")
    return (
        _MEMBER_ROLE_ORDER.get(role if isinstance(role, str) else "", 99),
        unicodedata.normalize("NFC", path) if isinstance(path, str) else "",
        raw_sha256 if isinstance(raw_sha256, str) else "",
        blob_oid if isinstance(blob_oid, str) else "",
    )


def _component_document_sort_key(
    component: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Mirror ``_component_sort_key`` without trusting domain reconstruction."""

    def text_field(name: str) -> str:
        value = component.get(name)
        return value if isinstance(value, str) else ""

    raw_members = component.get("members")
    member_keys = (
        tuple(
            _member_document_sort_key(member)
            for member in raw_members
            if isinstance(member, dict)
        )
        if isinstance(raw_members, list)
        else ()
    )
    return (
        text_field("package_id"),
        text_field("source_id"),
        text_field("vb_name"),
        text_field("component_type"),
        text_field("origin"),
        text_field("encoding_decision"),
        member_keys,
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
        "upstream_commit": snapshot.upstream_commit,
        "fork_dev_commit": snapshot.fork_dev_commit,
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
        "encoding_decision": component.encoding_decision,
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


def _looks_pathlike(value: str) -> bool:
    return (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", value) is not None
    )


def _has_control(value: str) -> bool:
    return any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value)


def _strict_path_code(path: Any) -> str | None:
    if type(path) is not str or not path:
        return "PATH_EMPTY"
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        return "PATH_ABSOLUTE"
    if "\\" in path:
        return "PATH_BACKSLASH"
    if any(character in _WINDOWS_INVALID for character in path):
        return "PATH_INVALID_CHARACTER"
    if _has_control(path):
        return "PATH_INVALID_CHARACTER"
    try:
        path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return "PATH_INVALID_UTF8"
    return None


def _record_keys_error(
    value: Any, allowed: frozenset[str], required: frozenset[str]
) -> str | None:
    if type(value) is not dict:
        return "record is not an exact JSON object"
    keys = set(value)
    if any(type(key) is not str for key in value):
        return "record contains a non-string key"
    missing = sorted(required - keys)
    extra = sorted(keys - allowed)
    if missing:
        return f"missing fields: {','.join(missing)}"
    if extra:
        return f"unknown fields: {','.join(extra)}"
    return None


def _string_list_error(value: Any, *, nonempty: bool = False) -> str | None:
    if type(value) is not list or (nonempty and not value):
        return "field must be a JSON array with the required entries"
    if any(type(item) is not str or not item or _has_control(item) for item in value):
        return "array entries must be non-empty controlled strings"
    if any(_looks_pathlike(item) for item in value):
        return "non-path field contains an absolute/drive/UNC-looking value"
    if len(value) != len(set(value)):
        return "array entries must be unique"
    return None


def _catalog_document_errors(value: Any) -> list[tuple[str, str, str]]:
    """Validate the immutable catalog boundary shared by creator and verifier."""
    findings: list[tuple[str, str, str]] = []

    def add(code: str, path: str, message: str) -> None:
        findings.append((code, path, message))

    try:
        _json_safe(value)
    except SourceError as error:
        add("CATALOG_RECORD_INVALID", "catalog.json", str(error))
        return findings

    top_fields = frozenset(
        {"schema_version", "snapshot", "components", "packages", "tools", "policy_evidence"}
    )
    error = _record_keys_error(value, top_fields, top_fields)
    if error is not None:
        add("CATALOG_RECORD_INVALID", "catalog.json", error)
        return findings
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        add("CATALOG_RECORD_INVALID", "catalog.json#/schema_version", "schema_version must be integer 1")

    snapshot = value["snapshot"]
    error = _record_keys_error(snapshot, _SNAPSHOT_FIELDS, _SNAPSHOT_FIELDS)
    if error is not None:
        add("CATALOG_RECORD_INVALID", "catalog.json#/snapshot", error)
    else:
        if snapshot["mode"] != "candidate":
            add("CATALOG_RECORD_INVALID", "catalog.json#/snapshot/mode", "snapshot mode must be candidate")
        if snapshot["formal_eligible"] is not True:
            add("CATALOG_RECORD_INVALID", "catalog.json#/snapshot/formal_eligible", "snapshot must be formally eligible")
        for field in ("upstream_commit", "fork_dev_commit", "work_commit", "work_tree"):
            field_value = snapshot[field]
            if type(field_value) is not str or _OID.fullmatch(field_value) is None:
                add("CATALOG_RECORD_INVALID", f"catalog.json#/snapshot/{field}", "snapshot Git object ID is invalid")
        digest = snapshot["manifest_digest"]
        if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
            add("CATALOG_RECORD_INVALID", "catalog.json#/snapshot/manifest_digest", "manifest digest is invalid")
        version = snapshot["tool_version"]
        if type(version) is not str or _TOOL_VERSION.fullmatch(version) is None:
            add("CATALOG_RECORD_INVALID", "catalog.json#/snapshot/tool_version", "tool version is invalid")

    packages = value["packages"]
    package_ids: list[str] = []
    if type(packages) is not list or not packages:
        add("CATALOG_RECORD_INVALID", "catalog.json#/packages", "catalog requires packages")
        packages = []
    for index, package in enumerate(packages):
        path = f"catalog.json#/packages/{index}"
        error = _record_keys_error(
            package, _PACKAGE_FIELDS, frozenset({"package_id", "classification"})
        )
        if error is not None:
            add("CATALOG_RECORD_INVALID", path, error)
            continue
        package_id = package["package_id"]
        if type(package_id) is not str or _STABLE_ID.fullmatch(package_id) is None:
            add("CATALOG_RECORD_INVALID", f"{path}/package_id", "package_id is invalid")
        else:
            package_ids.append(package_id)
        classification = package["classification"]
        if type(classification) is not str or classification not in _PACKAGE_CLASSIFICATIONS:
            add("CATALOG_RECORD_INVALID", f"{path}/classification", "package classification is invalid")
        for field in ("additional_deny_tokens", "reference_allowlist"):
            if field in package:
                list_error = _string_list_error(package[field])
                if list_error is not None:
                    add("CATALOG_RECORD_INVALID", f"{path}/{field}", list_error)
    if package_ids != sorted(package_ids) or len(package_ids) != len(set(package_ids)):
        add("CATALOG_RECORD_INVALID", "catalog.json#/packages", "package IDs must be unique and sorted")
    package_id_set = set(package_ids)

    components = value["components"]
    source_ids: list[str] = []
    component_bindings: list[tuple[str, str, str]] = []
    output_paths: list[str] = []
    if type(components) is not list or not components:
        add("CATALOG_RECORD_INVALID", "catalog.json#/components", "catalog requires a non-empty component array")
        components = []
    for index, component in enumerate(components):
        path = f"catalog.json#/components/{index}"
        error = _record_keys_error(component, _COMPONENT_FIELDS, _COMPONENT_FIELDS)
        if error is not None:
            add("CATALOG_RECORD_INVALID", path, error)
            continue
        source_id = component["source_id"]
        package_id = component["package_id"]
        vb_name = component["vb_name"]
        component_type = component["component_type"]
        origin = component["origin"]
        encoding_decision = component["encoding_decision"]
        if type(source_id) is not str or _STABLE_ID.fullmatch(source_id) is None:
            add("CATALOG_RECORD_INVALID", f"{path}/source_id", "source_id is invalid")
        else:
            source_ids.append(source_id)
        if type(package_id) is not str or _STABLE_ID.fullmatch(package_id) is None:
            add("CATALOG_RECORD_INVALID", f"{path}/package_id", "package_id is invalid")
        elif package_id not in package_id_set:
            add("CATALOG_RECORD_INVALID", f"{path}/package_id", "component package is unknown")
        if type(vb_name) is not str or _VBA_NAME.fullmatch(vb_name) is None:
            add("CATALOG_RECORD_INVALID", f"{path}/vb_name", "VBA component name is invalid")
        if type(component_type) is not str or component_type not in {"standard_module", "class_module", "user_form"}:
            add("CATALOG_RECORD_INVALID", f"{path}/component_type", "component type is invalid")
        if type(origin) is not str or origin not in {"upstream", "new", "override", "shared", "generated"}:
            add("CATALOG_RECORD_INVALID", f"{path}/origin", "component origin is invalid")
        if encoding_decision is not None and (
            type(encoding_decision) is not str
            or encoding_decision not in {"utf-8", "cp936"}
        ):
            add(
                "CATALOG_RECORD_INVALID",
                f"{path}/encoding_decision",
                "component encoding decision is invalid",
            )
        if component["disposition"] != "candidate":
            add("CATALOG_RECORD_INVALID", f"{path}/disposition", "only candidate components may be published")
        members = component["members"]
        if type(members) is not list or not members:
            add("CATALOG_RECORD_INVALID", f"{path}/members", "component requires members")
            members = []
        roles: list[str] = []
        form_stems: list[str] = []
        for member_index, member in enumerate(members):
            member_path = f"{path}/members/{member_index}"
            error = _record_keys_error(member, _MEMBER_FIELDS, _MEMBER_FIELDS)
            if error is not None:
                add("CATALOG_RECORD_INVALID", member_path, error)
                continue
            source_path = member["path"]
            role = member["role"]
            raw_sha256 = member["raw_sha256"]
            blob_oid = member["blob_oid"]
            path_code = _strict_path_code(source_path)
            if path_code is not None:
                add(path_code, f"{member_path}/path", "source member path is not portable")
            elif (
                type(source_path) is str
                and unicodedata.normalize("NFC", source_path) != source_path
            ):
                add(
                    "PATH_NOT_NFC",
                    f"{member_path}/path",
                    "source member path must be NFC normalized",
                )
            elif type(source_path) is str and validate_portable_paths((source_path,)).diagnostics:
                finding = validate_portable_paths((source_path,)).diagnostics[0]
                add(finding.code, f"{member_path}/path", finding.message)
            if type(raw_sha256) is not str or _DIGEST.fullmatch(raw_sha256) is None:
                add("CATALOG_RECORD_INVALID", f"{member_path}/raw_sha256", "source digest is invalid")
            if blob_oid is None:
                if origin != "generated":
                    add("CATALOG_RECORD_INVALID", f"{member_path}/blob_oid", "only generated sources may omit a Git blob ID")
            elif type(blob_oid) is not str or _OID.fullmatch(blob_oid) is None:
                add("CATALOG_RECORD_INVALID", f"{member_path}/blob_oid", "Git blob ID is invalid")
            if type(role) is not str or role not in {"source", "frm", "frx"}:
                add("CATALOG_RECORD_INVALID", f"{member_path}/role", "member role is invalid")
            else:
                roles.append(role)
            if type(source_path) is str and type(package_id) is str:
                normalized_name = unicodedata.normalize(
                    "NFC", PurePosixPath(source_path).name
                )
                suffix = PurePosixPath(normalized_name).suffix.casefold()
                output_paths.append(f"packages/{package_id}/source/{normalized_name}")
                if role == "frm" and suffix == ".frm":
                    form_stems.append(PurePosixPath(normalized_name).stem)
                elif role == "frx" and suffix == ".frx":
                    form_stems.append(PurePosixPath(normalized_name).stem)
                elif role == "source":
                    expected_suffix = ".bas" if component_type == "standard_module" else ".cls"
                    if component_type == "user_form" or suffix != expected_suffix:
                        add("CATALOG_RECORD_INVALID", f"{member_path}/path", "member extension does not match component type")
                else:
                    add("FORM_BINDING_INVALID", member_path, "Form roles require matching .frm/.frx files")
        if component_type == "user_form":
            if roles != ["frm", "frx"] or len(form_stems) != 2 or len(set(form_stems)) != 1:
                add("FORM_BINDING_INVALID", f"{path}/members", "user form requires adjacent frm/frx members with the same NFC stem")
        elif roles != ["source"]:
            add("CATALOG_RECORD_INVALID", f"{path}/members", "module requires exactly one source member")
        if (
            isinstance(members, list)
            and all(isinstance(member, dict) for member in members)
            and members != sorted(members, key=_member_document_sort_key)
        ):
            add(
                "CATALOG_NONCANONICAL",
                f"{path}/members",
                "component members do not follow the canonical member order",
            )
        if type(package_id) is str and type(vb_name) is str and type(component_type) is str:
            component_bindings.append((package_id, vb_name, component_type))
    if len(source_ids) != len(set(source_ids)):
        add("CATALOG_RECORD_INVALID", "catalog.json#/components", "source IDs must be unique")
    if (
        isinstance(components, list)
        and all(isinstance(component, dict) for component in components)
        and components != sorted(components, key=_component_document_sort_key)
    ):
        add(
            "CATALOG_NONCANONICAL",
            "catalog.json#/components",
            "components do not follow the canonical component order",
        )

    path_report = validate_portable_paths(output_paths)
    for finding in path_report.diagnostics:
        add(finding.code, finding.path, finding.message)
    for output_path in output_paths:
        path_code = _strict_path_code(output_path)
        if path_code is not None:
            add(path_code, output_path, "staged source path is not portable")

    tools = value["tools"]
    tool_ids: list[str] = []
    if type(tools) is not list:
        add("CATALOG_RECORD_INVALID", "catalog.json#/tools", "tools must be an array")
        tools = []
    for index, tool in enumerate(tools):
        path = f"catalog.json#/tools/{index}"
        error = _record_keys_error(tool, _TOOL_FIELDS, _TOOL_FIELDS)
        if error is not None:
            add("CATALOG_RECORD_INVALID", path, error)
            continue
        for field in ("tool_id", "group_id", "package_id"):
            field_value = tool[field]
            if type(field_value) is not str or _STABLE_ID.fullmatch(field_value) is None:
                add("CATALOG_RECORD_INVALID", f"{path}/{field}", f"{field} is invalid")
        if type(tool["tool_id"]) is str:
            tool_ids.append(tool["tool_id"])
        for field in ("module_name", "entrypoint"):
            field_value = tool[field]
            if type(field_value) is not str or _VBA_NAME.fullmatch(field_value) is None:
                add("CATALOG_RECORD_INVALID", f"{path}/{field}", f"{field} is not a legal VBA name")
        for field in ("caption", "risk_level"):
            field_value = tool[field]
            if type(field_value) is not str or not field_value or _has_control(field_value) or _looks_pathlike(field_value):
                add("CATALOG_RECORD_INVALID", f"{path}/{field}", f"{field} is invalid or path-looking")
        for field, nonempty in (("document_types", True), ("required_capabilities", False)):
            list_error = _string_list_error(tool[field], nonempty=nonempty)
            if list_error is not None:
                add("CATALOG_RECORD_INVALID", f"{path}/{field}", list_error)
        package_id = tool["package_id"]
        binding = (package_id, tool["module_name"], "standard_module")
        if (
            type(package_id) is not str
            or package_id not in package_id_set
            or component_bindings.count(binding) != 1
        ):
            add("CATALOG_RECORD_INVALID", f"{path}/module_name", "tool must bind one standard module in its package")
    if tool_ids != sorted(tool_ids) or len(tool_ids) != len(set(tool_ids)):
        add("CATALOG_RECORD_INVALID", "catalog.json#/tools", "tool IDs must be unique and sorted")

    policy = value["policy_evidence"]
    error = _record_keys_error(policy, _POLICY_FIELDS, _POLICY_FIELDS)
    if error is not None:
        add("CATALOG_RECORD_INVALID", "catalog.json#/policy_evidence", error)
    elif policy != {"compile_status": "not-run", "diagnostics": []}:
        add("CATALOG_RECORD_INVALID", "catalog.json#/policy_evidence", "published static policy evidence must remain not-run and clean")
    return findings


def _package_ids(catalog: ResolvedCatalog) -> tuple[str, ...]:
    return tuple(sorted(
        record["package_id"]
        for record in catalog.packages
        if isinstance(record.get("package_id"), str)
    ))


def _output_member_path(component: Component, member: SourceMember) -> str:
    assert component.package_id is not None
    source_name = unicodedata.normalize(
        "NFC", PurePosixPath(member.path.replace("\\", "/")).name
    )
    return f"packages/{component.package_id}/source/{source_name}"


def _git_blob_oid(data: bytes, oid: str) -> str | None:
    """Recompute the Git blob identity carried by a committed source member."""
    header = f"blob {len(data)}\0".encode("ascii")
    if len(oid) == 40:
        return hashlib.sha1(header + data).hexdigest()
    if len(oid) == 64:
        return hashlib.sha256(header + data).hexdigest()
    return None


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

    # Authenticate exact source bytes and the hard CATVBA exclusion before
    # deriving any identity or reporting secondary structural findings.
    for component in catalog.components:
        for member in component.members:
            if type(member.path) is str and _is_catvba_path(member.path):
                raise _source_error("CATVBA_FORBIDDEN", member.path)
            if type(member.data) is not bytes:
                raise _source_error("CATALOG_RECORD_INVALID", "source data must be exact bytes")
            if sha256_bytes(member.data) != member.raw_sha256:
                raise _source_error("SOURCE_HASH_MISMATCH", member.path)

    try:
        identity = _identity_payload(catalog)
    except (TypeError, ValueError) as error:
        raise _source_error(
            "CATALOG_RECORD_INVALID", type(error).__name__
        ) from error
    validation_errors = _catalog_document_errors(identity)
    if validation_errors:
        code, path, message = next(
            (
                finding
                for finding in validation_errors
                if finding[0] == "FORM_BINDING_INVALID"
            ),
            validation_errors[0],
        )
        if code not in {"FORM_BINDING_INVALID"} and not code.startswith("PATH_"):
            code = "CATALOG_RECORD_INVALID"
        raise _source_error(code, f"{path}: {message}")

    staged_files = {
        _output_member_path(component, member): member.data
        for component in catalog.components
        for member in component.members
    }
    identity_diagnostics: list[Diagnostic] = []
    _verify_component_identities(staged_files, identity, identity_diagnostics)
    if identity_diagnostics:
        finding = _stable_diagnostics((identity_diagnostics,))[0]
        raise _source_error(finding.code, f"{finding.path}: {finding.message}")

    fresh_policy = validate_catalog(
        ResolvedCatalog(
            snapshot=catalog.snapshot,
            components=catalog.components,
            packages=catalog.packages,
            tools=catalog.tools,
            report=ValidationReport(),
        )
    )
    if fresh_policy.diagnostics:
        raise _source_error(
            "CATALOG_POLICY_INVALID",
            ",".join(item.code for item in fresh_policy.diagnostics),
        )

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
                # CATIA imports the .frm; the adjacent .frx is a binary sidecar
                # retained and hashed but is never itself an import operation.
                if member.role != "frx":
                    import_names.append(import_name)
                staged_members.append(
                    {
                        "source_id": component.source_id,
                        "source_path": _member_record(member)["path"],
                        "staged_path": staged_path,
                        "raw_sha256": member.raw_sha256,
                        "role": member.role,
                        "encoding_decision": component.encoding_decision,
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
    try:
        lock_status = locks.lstat()
    except OSError as error:
        raise _infrastructure_error("LOCK_DIRECTORY_FAILED", cause=error)
    if not stat.S_ISDIR(lock_status.st_mode) or stat.S_ISLNK(lock_status.st_mode):
        raise _infrastructure_error("LOCK_DIRECTORY_UNSAFE")
    # Lock-name ownership is trusted only inside this explicit protection
    # boundary: current effective UID and exact owner-only 0700 permissions.
    if lock_status.st_uid != os.geteuid():
        raise _infrastructure_error("LOCK_DIRECTORY_UNSAFE", "wrong owner")
    try:
        os.chmod(locks, 0o700, follow_symlinks=False)
        lock_status = locks.lstat()
    except OSError as error:
        raise _infrastructure_error("LOCK_DIRECTORY_FAILED", cause=error)
    if (
        not stat.S_ISDIR(lock_status.st_mode)
        or lock_status.st_uid != os.geteuid()
        or stat.S_IMODE(lock_status.st_mode) != 0o700
    ):
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
        status = os.fstat(descriptor)
    except OSError as error:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise _infrastructure_error("KIT_LOCK_FAILED", kit_id, cause=error)
    try:
        os.write(descriptor, f"{kit_id}\n".encode("ascii"))
        os.fsync(descriptor)
    except OSError as error:
        try:
            _release_own_lock(path, descriptor, status)
        except InfrastructureError as cleanup_error:
            raise cleanup_error from error
        raise _infrastructure_error("KIT_LOCK_FAILED", kit_id, cause=error)
    return path, descriptor, status


def _release_own_lock(
    path: Path, descriptor: int, acquired_status: os.stat_result
) -> None:
    try:
        current = path.lstat()
    except OSError as error:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise _infrastructure_error(
            "KIT_LOCK_OWNERSHIP_LOST", os.fspath(path), cause=error
        )
    owned = (
        current.st_dev == acquired_status.st_dev
        and current.st_ino == acquired_status.st_ino
        and stat.S_ISREG(current.st_mode)
    )
    if not owned:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise _infrastructure_error("KIT_LOCK_OWNERSHIP_LOST", os.fspath(path))
    try:
        path.unlink()
        os.close(descriptor)
    except OSError as error:
        raise _infrastructure_error("KIT_LOCK_RELEASE_FAILED", cause=error)


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


def _read_regular_nofollow(path: Path) -> bytes:
    """Read one authenticated regular-file inode without following a symlink."""
    try:
        before = path.lstat()
    except OSError as error:
        raise _infrastructure_error("FILE_READ_FAILED", os.fspath(path), cause=error)
    if stat.S_ISLNK(before.st_mode):
        raise _infrastructure_error("SYMLINK_ENTRY", os.fspath(path))
    if not stat.S_ISREG(before.st_mode):
        raise _infrastructure_error("NON_REGULAR_ENTRY", os.fspath(path))
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise _infrastructure_error("FILE_READ_FAILED", os.fspath(path), cause=error)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise _infrastructure_error("FILE_IDENTITY_CHANGED", os.fspath(path))
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if opened.st_dev != after.st_dev or opened.st_ino != after.st_ino:
            raise _infrastructure_error("FILE_IDENTITY_CHANGED", os.fspath(path))
        return b"".join(chunks)
    except OSError as error:
        raise _infrastructure_error("FILE_READ_FAILED", os.fspath(path), cause=error)
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
            result[relative] = _read_regular_nofollow(path)
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


def _remove_tree(path: Path) -> None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(status.st_mode):
        path.unlink()
    elif stat.S_ISDIR(status.st_mode):
        shutil.rmtree(path)
    else:
        raise OSError("temporary tree was replaced by a non-directory")


def _unlink_temp(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _publish_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without an overwrite-capable fallback.

    Linux renameat2(RENAME_NOREPLACE) is the only directory commit primitive
    used here.  Platforms without that guarantee fail closed rather than
    reintroducing a check-then-rename race.
    """
    function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if function is None:
        raise _infrastructure_error("ATOMIC_NOREPLACE_UNAVAILABLE")
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise _infrastructure_error("KIT_OUTPUT_COLLISION", destination.name)
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise _infrastructure_error("ATOMIC_NOREPLACE_UNAVAILABLE")
    error = OSError(error_number, os.strerror(error_number), os.fspath(destination))
    raise _infrastructure_error("KIT_PUBLISH_FAILED", destination.name, cause=error)


def _publish_file_noreplace(source: Path, destination: Path) -> None:
    """Publish a regular file by atomic hard-link creation (never overwrite)."""
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as error:
        raise _infrastructure_error(
            "KIT_OUTPUT_COLLISION", destination.name, cause=error
        )
    except OSError as error:
        raise _infrastructure_error(
            "KIT_PUBLISH_FAILED", destination.name, cause=error
        )


def _publish_or_match_file(
    temporary: Path, destination: Path, expected: bytes, kit_id: str
) -> None:
    if _lexists(destination):
        try:
            actual = _read_regular_nofollow(destination)
        except (OSError, InfrastructureError) as error:
            raise _infrastructure_error(
                "KIT_ID_CONTENT_MISMATCH", kit_id, cause=error
            )
        if actual != expected:
            raise _infrastructure_error("KIT_ID_CONTENT_MISMATCH", kit_id)
        _unlink_temp(temporary)
        return
    _publish_file_noreplace(temporary, destination)
    _unlink_temp(temporary)


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
    final_dir = root / kit_id
    zip_path = root / f"{kit_id}.zip"
    sidecar_path = root / f"{kit_id}.zip.sha256"
    receipt: BuildKitReceipt | None = None
    pending: BaseException | None = None
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

        if _lexists(final_dir):
            if not _same_directory(temp_dir, final_dir):
                raise _infrastructure_error("KIT_ID_CONTENT_MISMATCH", kit_id)
            _remove_tree(temp_dir)
            temp_dir = None
        else:
            # The fully self-verified primary directory is the commit point.
            # ZIP and sidecar are deterministic resumable derivatives.
            _publish_directory_noreplace(temp_dir, final_dir)
            temp_dir = None

        assert temp_zip is not None and temp_sidecar is not None
        _publish_or_match_file(temp_zip, zip_path, archive_bytes, kit_id)
        temp_zip = None
        _publish_or_match_file(temp_sidecar, sidecar_path, sidecar_bytes, kit_id)
        temp_sidecar = None

        receipt = BuildKitReceipt(
            kit_id=kit_id,
            kit_dir=os.fspath(final_dir),
            zip_path=os.fspath(zip_path),
            zip_sha256=archive_sha256,
            manifest_sha256=manifest_sha256,
        )
    except (SourceError, InfrastructureError) as error:
        pending = error
    except Exception as error:
        pending = _infrastructure_error(
            "KIT_STAGE_FAILED", type(error).__name__, cause=error
        )
    finally:
        cleanup_error: BaseException | None = None
        try:
            if temp_dir is not None:
                _remove_tree(temp_dir)
            if temp_zip is not None:
                _unlink_temp(temp_zip)
            if temp_sidecar is not None:
                _unlink_temp(temp_sidecar)
        except OSError as error:
            cleanup_error = _infrastructure_error(
                "KIT_CLEANUP_FAILED", type(error).__name__, cause=error
            )
        try:
            _release_own_lock(lock_path, lock_descriptor, lock_status)
        except InfrastructureError as error:
            cleanup_error = error
        if cleanup_error is not None:
            raise cleanup_error from pending
    if pending is not None:
        raise pending
    assert receipt is not None
    return receipt


def _verification_diagnostic(
    code: str, path: str, message: str, **details: Any
) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message, details=details)


def _path_diagnostics(name: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    strict_code = _strict_path_code(name)
    if strict_code is not None:
        diagnostics.append(
            _verification_diagnostic(
                strict_code, name, "entry path is not Windows-portable"
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
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        value = json.loads(
            data.decode("ascii"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
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
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "algorithm", "members"}
        or value.get("schema_version") != 1
        or type(value.get("schema_version")) is not int
        or value.get("algorithm") != "sha256"
    ):
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
        if type(record) is not dict or set(record) != {
            "source_id",
            "source_path",
            "staged_path",
            "raw_sha256",
            "role",
            "encoding_decision",
        }:
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
        decision = record.get("encoding_decision")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or (
                decision is not None
                and (
                    type(decision) is not str
                    or decision not in {"utf-8", "cp936"}
                )
            )
        ):
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
        encoding_decision = component.get("encoding_decision")
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
            name = unicodedata.normalize(
                "NFC", PurePosixPath(source_path.replace("\\", "/")).name
            )
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
            if role != "frx":
                import_names[package_id].append(name)
            staged_members.append(
                {
                    "source_id": source_id,
                    "source_path": source_path,
                    "staged_path": staged_path,
                    "raw_sha256": raw_sha256,
                    "role": role,
                    "encoding_decision": encoding_decision,
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
                name = unicodedata.normalize(
                    "NFC", PurePosixPath(source_path.replace("\\", "/")).name
                )
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


def _vba_text_variants(
    data: bytes, declared_encoding: str | None
) -> tuple[str, ...]:
    """Decode exactly the text identity bound into the catalog."""
    try:
        return (decode_vba(data, declared_encoding).text,)
    except SourceError:
        return ()


def _parsed_vba_identity(
    data: bytes, declared_encoding: str | None
) -> tuple[str | None, tuple[str, ...], str | None]:
    variants = _vba_text_variants(data, declared_encoding)
    if not variants:
        return None, (), "source has no strict UTF-8/CP936 interpretation"
    names: list[str] = []
    for text in variants:
        matches = _VB_NAME_ATTRIBUTE.findall(text)
        if len(matches) != 1:
            return (
                None,
                variants,
                "source must contain exactly one Attribute VB_Name in every strict interpretation",
            )
        names.append(matches[0])
    if len(set(names)) != 1:
        return None, variants, "Attribute VB_Name is encoding-ambiguous"
    return names[0], variants, None


def _component_identity_diagnostic(
    diagnostics: list[Diagnostic], path: str, message: str, *, reason: str
) -> None:
    diagnostics.append(
        _verification_diagnostic(
            "COMPONENT_IDENTITY_MISMATCH",
            path,
            message,
            identity_reason=reason,
        )
    )


def _verify_component_identities(
    files: Mapping[str, bytes],
    catalog: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    """Bind authenticated staged bytes to semantic and Git identities.

    ``validate_catalog`` intentionally scans policy, not exported-module
    identity.  Verification therefore parses the staged source independently,
    checks committed Git blob identities, validates Form metadata, and
    regenerates any deterministic generated component.
    """
    domain_components: list[Component] = []
    raw_generated: list[dict[str, Any]] = []

    for component_index, raw_component in enumerate(catalog["components"]):
        package_id = raw_component["package_id"]
        raw_members = raw_component["members"]
        members: list[SourceMember] = []
        staged_by_role: dict[str, tuple[str, bytes]] = {}
        missing = False
        for member_index, raw_member in enumerate(raw_members):
            name = unicodedata.normalize(
                "NFC", PurePosixPath(raw_member["path"]).name
            )
            staged_path = f"packages/{package_id}/source/{name}"
            data = files.get(staged_path)
            if data is None:
                missing = True
                continue
            role = raw_member["role"]
            staged_by_role[role] = (staged_path, data)
            member = SourceMember(
                path=raw_member["path"],
                blob_oid=raw_member["blob_oid"],
                raw_sha256=raw_member["raw_sha256"],
                role=role,
                data=data,
            )
            members.append(member)

            blob_oid = raw_member["blob_oid"]
            if raw_component["origin"] != Origin.GENERATED.value:
                actual_oid = (
                    _git_blob_oid(data, blob_oid)
                    if isinstance(blob_oid, str)
                    else None
                )
                if actual_oid != blob_oid:
                    _component_identity_diagnostic(
                        diagnostics,
                        staged_path,
                        "staged source bytes do not match their committed Git blob identity",
                        reason="GIT_BLOB_OID_MISMATCH",
                    )

            suffix = PurePosixPath(name).suffix.casefold()
            expected_role_type = {
                ".bas": ("source", "standard_module"),
                ".cls": ("source", "class_module"),
                ".frm": ("frm", "user_form"),
                ".frx": ("frx", "user_form"),
            }.get(suffix)
            if expected_role_type != (role, raw_component["component_type"]):
                _component_identity_diagnostic(
                    diagnostics,
                    staged_path,
                    "staged member extension and role do not reproduce the component type",
                    reason="COMPONENT_TYPE_ROLE_MISMATCH",
                )

        if missing:
            continue

        primary_role = (
            "frm" if raw_component["component_type"] == "user_form" else "source"
        )
        primary = staged_by_role.get(primary_role)
        texts: tuple[str, ...] = ()
        if primary is not None:
            staged_path, data = primary
            parsed_name, texts, parse_error = _parsed_vba_identity(
                data, raw_component["encoding_decision"]
            )
            if parse_error is not None:
                _component_identity_diagnostic(
                    diagnostics,
                    staged_path,
                    "staged VBA identity cannot be parsed unambiguously",
                    reason=parse_error,
                )
            elif parsed_name != raw_component["vb_name"]:
                _component_identity_diagnostic(
                    diagnostics,
                    staged_path,
                    "parsed Attribute VB_Name does not match catalog identity",
                    reason="VB_NAME_MISMATCH",
                )

        if raw_component["component_type"] == "user_form" and texts:
            frx = staged_by_role.get("frx")
            declared_names: list[str] = []
            form_error: str | None = None
            for text in texts:
                bindings = _OLE_OBJECT_BLOB.findall(text)
                if len(bindings) != 1:
                    form_error = (
                        "Form must contain exactly one OleObjectBlob binding "
                        "in every strict interpretation"
                    )
                    break
                declared_names.append(unicodedata.normalize("NFC", bindings[0][0]))
            if form_error is None and len(set(declared_names)) != 1:
                form_error = "OleObjectBlob filename is encoding-ambiguous"
            if form_error is None and frx is not None:
                actual_name = unicodedata.normalize(
                    "NFC", PurePosixPath(frx[0]).name
                )
                if not declared_names or declared_names[0] != actual_name:
                    form_error = "OleObjectBlob filename does not exactly bind the staged FRX"
            if form_error is not None:
                _component_identity_diagnostic(
                    diagnostics,
                    primary[0],
                    "staged Form metadata does not reproduce its FRM/FRX bundle identity",
                    reason=form_error,
                )

        component = Component(
            source_id=raw_component["source_id"],
            origin=Origin(raw_component["origin"]),
            component_type=raw_component["component_type"],
            vb_name=raw_component["vb_name"],
            members=tuple(members),
            package_id=package_id,
            disposition=raw_component["disposition"],
            encoding_decision=raw_component["encoding_decision"],
        )
        domain_components.append(component)
        if component.origin is Origin.GENERATED:
            raw_generated.append(raw_component)

        reserved_generated_path = any(
            raw_member["path"] == GENERATED_PATH for raw_member in raw_members
        )
        if (
            component.source_id == GENERATED_SOURCE_ID or reserved_generated_path
        ) and component.origin is not Origin.GENERATED:
            _component_identity_diagnostic(
                diagnostics,
                f"catalog.json#/components/{component_index}",
                "reserved generated source identity was downgraded to a non-generated origin",
                reason="GENERATED_ORIGIN_MISMATCH",
            )

    if not raw_generated:
        return

    snapshot = catalog["snapshot"]
    manifests = ManifestSet(
        project={"schema_version": 1},
        components={"schema_version": 1, "source_roots": [], "components": []},
        packages={"schema_version": 1, "packages": catalog["packages"]},
        tools={"schema_version": 1, "tools": catalog["tools"]},
        digest=snapshot["manifest_digest"],
        report=ValidationReport(),
    )
    regenerated = generate_sources(
        ResolvedSourceSet(
            components=tuple(
                component
                for component in domain_components
                if component.origin is not Origin.GENERATED
            ),
            quarantined=(),
            report=ValidationReport(),
        ),
        manifests,
    )
    expected_records = [
        _component_record(component) for component in regenerated.components
    ]
    if regenerated.report.diagnostics or raw_generated != expected_records:
        _component_identity_diagnostic(
            diagnostics,
            "catalog.json#/components",
            "embedded generated component does not reproduce deterministic generator output",
            reason="GENERATED_COMPONENT_MISMATCH",
        )
        return
    for component in regenerated.components:
        for member in component.members:
            staged_path = _output_member_path(component, member)
            if files.get(staged_path) != member.data:
                _component_identity_diagnostic(
                    diagnostics,
                    staged_path,
                    "embedded generated bytes do not reproduce deterministic generator output",
                    reason="GENERATED_BYTES_MISMATCH",
                )


def _verify_embedded_policy(
    files: Mapping[str, bytes],
    catalog: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    """Re-run static policy from authenticated embedded source bytes.

    The stored empty policy evidence is not itself trusted.  Reconstructing the
    exact domain graph closes self-consistent catalog/tool/source bypasses.
    """
    raw_snapshot = catalog["snapshot"]
    snapshot = InputSnapshot(
        mode=SnapshotMode.CANDIDATE,
        upstream_repository="identity-only",
        upstream_ref="identity-only",
        upstream_commit=raw_snapshot["upstream_commit"],
        fork_repository="identity-only",
        fork_dev_commit=raw_snapshot["fork_dev_commit"],
        work_repository="identity-only",
        work_branch="identity-only",
        work_commit=raw_snapshot["work_commit"],
        work_tree=raw_snapshot["work_tree"],
        manifest_digest=raw_snapshot["manifest_digest"],
        tool_version=raw_snapshot["tool_version"],
        formal_eligible=True,
    )
    components: list[Component] = []
    for raw_component in catalog["components"]:
        members: list[SourceMember] = []
        for raw_member in raw_component["members"]:
            name = unicodedata.normalize(
                "NFC", PurePosixPath(raw_member["path"]).name
            )
            staged_path = (
                f"packages/{raw_component['package_id']}/source/{name}"
            )
            data = files.get(staged_path)
            if data is None:
                return
            members.append(
                SourceMember(
                    path=raw_member["path"],
                    blob_oid=raw_member["blob_oid"],
                    raw_sha256=raw_member["raw_sha256"],
                    role=raw_member["role"],
                    data=data,
                )
            )
        components.append(
            Component(
                source_id=raw_component["source_id"],
                origin=Origin(raw_component["origin"]),
                component_type=raw_component["component_type"],
                vb_name=raw_component["vb_name"],
                members=tuple(members),
                package_id=raw_component["package_id"],
                disposition=raw_component["disposition"],
                encoding_decision=raw_component["encoding_decision"],
            )
        )
    policy = validate_catalog(
        ResolvedCatalog(
            snapshot=snapshot,
            components=tuple(components),
            packages=tuple(catalog["packages"]),
            tools=tuple(catalog["tools"]),
            report=ValidationReport(),
        )
    )
    for finding in policy.diagnostics:
        diagnostics.append(
            _verification_diagnostic(
                "CATALOG_POLICY_INVALID",
                finding.path,
                "embedded catalog does not reproduce clean static policy evidence",
                policy_code=finding.code,
            )
        )
        diagnostics.append(
            _verification_diagnostic(
                "CATALOG_MALFORMED",
                finding.path,
                "embedded component/package/tool graph fails static binding policy",
                policy_code=finding.code,
            )
        )


def _verify_file_map(
    files: Mapping[str, bytes],
    directories: set[str] | None = None,
    *,
    container_name: str | None = None,
    zip_container: bool = False,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    names = tuple(files)
    for name in names:
        diagnostics.extend(_path_diagnostics(name))
    path_report = validate_portable_paths(names)
    for finding in path_report.diagnostics:
        diagnostics.append(
            _verification_diagnostic(
                finding.code, finding.path, finding.message
            )
        )
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
        catalog_errors = _catalog_document_errors(catalog)
        for code, path, message in catalog_errors:
            diagnostics.append(
                _verification_diagnostic(
                    (
                        "CATALOG_NONCANONICAL"
                        if code == "CATALOG_NONCANONICAL"
                        else "CATALOG_MALFORMED"
                    ),
                    path,
                    message,
                    catalog_code=code,
                )
            )
        policy = catalog.get("policy_evidence")
        if not isinstance(policy, dict) or policy.get("compile_status") != "not-run":
            diagnostics.append(
                _verification_diagnostic(
                    "IMMUTABLE_STATUS_INVALID",
                    "catalog.json#/policy_evidence/compile_status",
                    "static policy compile status must remain not-run",
                )
            )
        if not catalog_errors:
            _verify_expected_graph(
                files, catalog, expected_id, diagnostics, directories
            )
            _verify_component_identities(files, catalog, diagnostics)
            _verify_embedded_policy(files, catalog, diagnostics)
        if isinstance(policy, dict) and policy.get("diagnostics") != []:
            diagnostics.append(
                _verification_diagnostic(
                    "IMMUTABLE_STATUS_INVALID",
                    "catalog.json#/policy_evidence/diagnostics",
                    "published kit cannot contain policy diagnostics",
                )
            )
        if container_name is not None:
            required_name = f"{expected_id}.zip" if zip_container else expected_id
            if container_name != required_name:
                diagnostics.append(
                    _verification_diagnostic(
                        "WRONG_CONTAINER_NAME",
                        container_name,
                        "container name does not exactly bind the canonical kit ID",
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
            set(marker) == {"complete", "kit_id", "sha256sums_sha256"}
            and
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

    ancestor = _symlink_ancestor(path)
    if ancestor is not None:
        return (
            files,
            [
                _verification_diagnostic(
                    "SYMLINK_ANCESTOR",
                    os.fspath(ancestor),
                    "kit input has a symlink ancestor",
                )
            ],
            directories,
        )
    try:
        root_status = path.lstat()
    except OSError:
        return (
            files,
            [
                _verification_diagnostic(
                    "KIT_PATH_INVALID", os.fspath(path), "kit path is not a directory or ZIP"
                )
            ],
            directories,
        )
    if stat.S_ISLNK(root_status.st_mode):
        return (
            files,
            [
                _verification_diagnostic(
                    "SYMLINK_ENTRY", os.fspath(path), "kit directory cannot be a symlink"
                )
            ],
            directories,
        )
    if not stat.S_ISDIR(root_status.st_mode):
        return (
            files,
            [
                _verification_diagnostic(
                    "KIT_PATH_INVALID", os.fspath(path), "kit path is not a directory or ZIP"
                )
            ],
            directories,
        )

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(path, flags)
        opened_root = os.fstat(root_descriptor)
    except OSError as error:
        diagnostics.append(
            _verification_diagnostic(
                "KIT_READ_ERROR", os.fspath(path), f"cannot open kit root: {type(error).__name__}"
            )
        )
        return files, diagnostics, directories
    if (
        opened_root.st_dev != root_status.st_dev
        or opened_root.st_ino != root_status.st_ino
        or not stat.S_ISDIR(opened_root.st_mode)
    ):
        os.close(root_descriptor)
        diagnostics.append(
            _verification_diagnostic(
                "FILE_IDENTITY_CHANGED", os.fspath(path), "kit root changed while opening"
            )
        )
        return files, diagnostics, directories

    def visit(descriptor: int, prefix: str) -> None:
        try:
            names = sorted(os.listdir(descriptor))
        except OSError as error:
            diagnostics.append(
                _verification_diagnostic(
                    "KIT_READ_ERROR", prefix or ".", f"cannot list kit directory: {type(error).__name__}"
                )
            )
            return
        for name in names:
            relative = f"{prefix}/{name}" if prefix else name
            diagnostics.extend(_path_diagnostics(relative))
            try:
                before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as error:
                diagnostics.append(
                    _verification_diagnostic(
                        "KIT_READ_ERROR", relative, f"cannot inspect kit entry: {type(error).__name__}"
                    )
                )
                continue
            if stat.S_ISLNK(before.st_mode):
                diagnostics.append(
                    _verification_diagnostic(
                        "SYMLINK_ENTRY", relative, "kit contains a symlink entry"
                    )
                )
                continue
            if stat.S_ISDIR(before.st_mode):
                directories.add(relative)
                try:
                    child_descriptor = os.open(name, flags, dir_fd=descriptor)
                    opened = os.fstat(child_descriptor)
                except OSError as error:
                    diagnostics.append(
                        _verification_diagnostic(
                            "KIT_READ_ERROR", relative, f"cannot open kit directory: {type(error).__name__}"
                        )
                    )
                    continue
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_dev != before.st_dev
                    or opened.st_ino != before.st_ino
                ):
                    diagnostics.append(
                        _verification_diagnostic(
                            "FILE_IDENTITY_CHANGED", relative, "kit directory changed while opening"
                        )
                    )
                    os.close(child_descriptor)
                    continue
                try:
                    visit(child_descriptor, relative)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(before.st_mode):
                diagnostics.append(
                    _verification_diagnostic(
                        "NON_REGULAR_ENTRY", relative, "kit entry is not a regular file"
                    )
                )
                continue
            file_flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                file_flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                file_flags |= os.O_NOFOLLOW
            try:
                file_descriptor = os.open(name, file_flags, dir_fd=descriptor)
                opened = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_dev != before.st_dev
                    or opened.st_ino != before.st_ino
                ):
                    diagnostics.append(
                        _verification_diagnostic(
                            "FILE_IDENTITY_CHANGED", relative, "kit file changed while opening"
                        )
                    )
                    os.close(file_descriptor)
                    continue
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(file_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(file_descriptor)
                os.close(file_descriptor)
                if opened.st_dev != after.st_dev or opened.st_ino != after.st_ino:
                    diagnostics.append(
                        _verification_diagnostic(
                            "FILE_IDENTITY_CHANGED", relative, "kit file changed while reading"
                        )
                    )
                    continue
                files[relative] = b"".join(chunks)
            except OSError as error:
                diagnostics.append(
                    _verification_diagnostic(
                        "KIT_READ_ERROR", relative, f"cannot read kit entry: {type(error).__name__}"
                    )
                )
    try:
        visit(root_descriptor, "")
    finally:
        os.close(root_descriptor)
    return files, diagnostics, directories


def _symlink_ancestor(path: Path) -> Path | None:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            status = current.lstat()
        except OSError:
            return None
        if stat.S_ISLNK(status.st_mode):
            return current
    return None


def _zip_file_map(
    path: Path,
) -> tuple[dict[str, bytes], list[Diagnostic], None]:
    files: dict[str, bytes] = {}
    diagnostics: list[Diagnostic] = []
    ancestor = _symlink_ancestor(path)
    if ancestor is not None:
        diagnostics.append(
            _verification_diagnostic(
                "SYMLINK_ANCESTOR", os.fspath(ancestor), "ZIP input has a symlink ancestor"
            )
        )
        return files, diagnostics, None
    try:
        container_bytes = _read_regular_nofollow(path)
    except InfrastructureError as error:
        code = str(error).split(":", 1)[0]
        diagnostics.append(
            _verification_diagnostic(
                code if code in {"SYMLINK_ENTRY", "NON_REGULAR_ENTRY"} else "ZIP_INVALID",
                os.fspath(path),
                "ZIP input is not an authenticated regular file",
            )
        )
        return files, diagnostics, None
    try:
        with zipfile.ZipFile(io.BytesIO(container_bytes)) as archive:
            if archive.comment:
                diagnostics.append(
                    _verification_diagnostic(
                        "ZIP_METADATA_INVALID", "<archive>", "ZIP comment must be empty"
                    )
                )
            infos = archive.infolist()
            info_names = [info.filename for info in infos]
            if info_names != sorted(info_names) or any(
                unicodedata.normalize("NFC", name) != name for name in info_names
            ):
                diagnostics.append(
                    _verification_diagnostic(
                        "ZIP_ENTRY_ORDER_INVALID",
                        "<archive>",
                        "ZIP entry names must be unique sorted NFC paths",
                    )
                )
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
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        diagnostics.append(
            _verification_diagnostic(
                "ZIP_INVALID", os.fspath(path), f"cannot open ZIP: {type(error).__name__}"
            )
        )
        return files, diagnostics, None

    try:
        canonical_container = _zip_bytes(files)
    except (InfrastructureError, OSError, ValueError) as error:
        diagnostics.append(
            _verification_diagnostic(
                "ZIP_NOT_CANONICAL", path.name, f"ZIP cannot be reconstructed canonically: {type(error).__name__}"
            )
        )
    else:
        if canonical_container != container_bytes:
            diagnostics.append(
                _verification_diagnostic(
                    "ZIP_NOT_CANONICAL", path.name, "ZIP bytes differ from the canonical deterministic representation"
                )
            )

    sidecar = path.with_name(path.name + ".sha256")
    try:
        sidecar_data = _read_regular_nofollow(sidecar)
    except InfrastructureError as error:
        code = str(error).split(":", 1)[0]
        diagnostics.append(
            _verification_diagnostic(
                (
                    "SYMLINK_ENTRY"
                    if code == "SYMLINK_ENTRY"
                    else "ZIP_SIDECAR_MISSING"
                ),
                sidecar.name,
                "ZIP SHA-256 sidecar is missing or unsafe",
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
            actual = sha256_bytes(container_bytes)
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
    is_zip = candidate.suffix.casefold() == ".zip"
    if is_zip:
        files, diagnostics, directories = _zip_file_map(candidate)
    else:
        files, diagnostics, directories = _directory_file_map(candidate)
    diagnostics.extend(
        _verify_file_map(
            files,
            directories,
            container_name=candidate.name,
            zip_container=is_zip,
        )
    )
    stable = _stable_diagnostics((diagnostics,))
    return VerificationReport(ok=not stable, diagnostics=stable)
