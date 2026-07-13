from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from .encoding import decode_vba
from .errors import SourceError
from .manifests import ManifestSet
from .model import (
    Component,
    Diagnostic,
    GeneratedSourceSet,
    Origin,
    ResolvedCatalog,
    ResolvedSourceSet,
    SourceMember,
    ValidationReport,
)
from .policy import validate_catalog
from .portable_paths import portable_key, validate_portable_paths


GENERATED_SOURCE_ID = "generated.tool-catalog"
GENERATED_VB_NAME = "MM_GeneratedCatalog"
GENERATED_PATH = "generated/MM_GeneratedCatalog.bas"
GENERATED_PACKAGE_ID = "core"

_LEGAL_VB_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VB_NAME_ATTRIBUTE = re.compile(
    r'^Attribute\s+VB_Name\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*$',
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class _CatalogView:
    components: tuple[Component, ...]
    packages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    report: ValidationReport


def _diagnostic(
    code: str,
    message: str,
    *,
    line: int,
    token: str,
    path: str = GENERATED_PATH,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        path=path,
        message=message,
        details={"line": line, "token": token},
    )


def _frozen_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(
            (str(key), _frozen_detail(nested))
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_detail(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_frozen_detail(item) for item in value), key=repr))
    return value


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[Any, ...]:
    return (
        diagnostic.code,
        diagnostic.path,
        diagnostic.message,
        _frozen_detail(diagnostic.details),
    )


def _report(*groups: tuple[Diagnostic, ...] | list[Diagnostic]) -> ValidationReport:
    unique: dict[tuple[Any, ...], Diagnostic] = {}
    for group in groups:
        for diagnostic in group:
            unique.setdefault(_diagnostic_key(diagnostic), diagnostic)
    return ValidationReport(tuple(unique[key] for key in sorted(unique)))


def _contains_forbidden_generated_character(value: str) -> bool:
    return any(
        ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        or character in {"\u2028", "\u2029"}
        for character in value
    )


def _tool_records(
    manifests: ManifestSet,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, Any], ...]:
    records = manifests.tools.get("tools", [])
    if not isinstance(records, list):
        diagnostics.append(
            _diagnostic(
                "TOOL_RECORD_INVALID",
                "tool catalog is not an array",
                path="tools.json#/tools",
                line=1,
                token="tools",
            )
        )
        return ()

    valid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            diagnostics.append(
                _diagnostic(
                    "TOOL_RECORD_INVALID",
                    "tool entry is not an object",
                    path=f"tools.json#/tools/{index}",
                    line=1,
                    token="tool",
                )
            )
            continue
        tool_id = record.get("tool_id")
        caption = record.get("caption")
        if not isinstance(tool_id, str) or not isinstance(caption, str):
            diagnostics.append(
                _diagnostic(
                    "TOOL_RECORD_INVALID",
                    "tool entry requires string tool_id and caption fields",
                    path=f"tools.json#/tools/{index}",
                    line=1,
                    token="tool_id/caption",
                )
            )
            continue
        invalid_field = next(
            (
                field
                for field, value in (("tool_id", tool_id), ("caption", caption))
                if _contains_forbidden_generated_character(value)
            ),
            None,
        )
        if invalid_field is not None:
            diagnostics.append(
                _diagnostic(
                    "GENERATED_STRING_INVALID",
                    "generated VBA string cannot contain controls or line separators",
                    path=f"tools.json#/tools/{index}/{invalid_field}",
                    line=1,
                    token=invalid_field,
                )
            )
            continue
        if tool_id in seen_ids:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_TOOL_ID",
                    "tool_id is not unique",
                    path=f"tools.json#/tools/{index}/tool_id",
                    line=1,
                    token=tool_id,
                )
            )
            continue
        seen_ids.add(tool_id)
        valid.append(record)
    return tuple(sorted(valid, key=lambda record: cast(str, record["tool_id"])))


def _vba_string(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _source_text(tools: tuple[dict[str, Any], ...]) -> str:
    tool_ids = ", ".join(_vba_string(cast(str, tool["tool_id"])) for tool in tools)
    captions = ", ".join(_vba_string(cast(str, tool["caption"])) for tool in tools)
    lines = (
        f'Attribute VB_Name = "{GENERATED_VB_NAME}"',
        "Option Explicit",
        "",
        "Public Function MM_ToolIds() As Variant",
        f"    MM_ToolIds = Array({tool_ids})",
        "End Function",
        "",
        "Public Function MM_ToolCaptions() As Variant",
        f"    MM_ToolCaptions = Array({captions})",
        "End Function",
        "",
    )
    return "\n".join(lines)


def _encode_source(text: str, diagnostics: list[Diagnostic]) -> bytes | None:
    try:
        return text.replace("\n", "\r\n").encode("cp936", errors="strict")
    except UnicodeEncodeError as error:
        line = text[: error.start].count("\n") + 1
        diagnostics.append(
            _diagnostic(
                "GENERATED_CP936_UNENCODABLE",
                "generated catalog is not representable in strict CP936",
                line=line,
                token="cp936",
            )
        )
        return None


def _core_package(
    manifests: ManifestSet, diagnostics: list[Diagnostic]
) -> dict[str, Any] | None:
    records = manifests.packages.get("packages", [])
    matches = (
        [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("package_id") == GENERATED_PACKAGE_ID
        ]
        if isinstance(records, list)
        else []
    )
    if len(matches) != 1 or matches[0].get("classification") != "CORE_CANDIDATE":
        diagnostics.append(
            _diagnostic(
                "GENERATED_PACKAGE_INVALID",
                "generated catalog requires exactly one Core candidate package",
                line=1,
                token=GENERATED_PACKAGE_ID,
            )
        )
        return None
    return matches[0]


def _vb_name_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _generated_collision_diagnostics(
    resolved: ResolvedSourceSet, diagnostics: list[Diagnostic]
) -> None:
    generated_path_key = portable_key(GENERATED_PATH)
    generated_basename = PurePosixPath(GENERATED_PATH).name
    generated_basename_key = portable_key(generated_basename)
    generated_name_key = _vb_name_key(GENERATED_VB_NAME)

    for component in sorted(
        resolved.components,
        key=lambda item: (
            item.source_id,
            item.package_id or "",
            item.vb_name,
            tuple(member.path for member in item.members),
        ),
    ):
        first_path = min(
            (member.path for member in component.members),
            default=GENERATED_PATH,
        )
        if component.source_id == GENERATED_SOURCE_ID:
            diagnostics.append(
                _diagnostic(
                    "GENERATED_SOURCE_ID_COLLISION",
                    "generated source_id collides with a resolved component",
                    path=first_path,
                    line=1,
                    token=GENERATED_SOURCE_ID,
                )
            )

        if (
            component.package_id == GENERATED_PACKAGE_ID
            and _vb_name_key(component.vb_name) == generated_name_key
        ):
            diagnostics.append(
                _diagnostic(
                    "GENERATED_VB_NAME_COLLISION",
                    "generated VB_Name collides within its package",
                    path=first_path,
                    line=1,
                    token=GENERATED_VB_NAME,
                )
            )

        for member in component.members:
            try:
                member_path_key = portable_key(member.path)
                basename_key = portable_key(
                    PurePosixPath(member.path.replace("\\", "/")).name
                )
            except SourceError:
                diagnostics.append(
                    _diagnostic(
                        "GENERATED_COLLISION_CHECK_FAILED",
                        "resolved member path cannot be checked for generated collisions",
                        path=member.path,
                        line=1,
                        token=member.path,
                    )
                )
                continue
            if member_path_key == generated_path_key:
                diagnostics.append(
                    _diagnostic(
                        "GENERATED_PATH_SHADOW",
                        "generated path shadows a resolved member portable path",
                        path=member.path,
                        line=1,
                        token=GENERATED_PATH,
                    )
                )
            if (
                component.package_id == GENERATED_PACKAGE_ID
                and basename_key == generated_basename_key
            ):
                diagnostics.append(
                    _diagnostic(
                        "GENERATED_OUTPUT_BASENAME_COLLISION",
                        "generated output basename collides within its package",
                        path=member.path,
                        line=1,
                        token=generated_basename,
                    )
                )


def _validate_identity(component: Component, diagnostics: list[Diagnostic]) -> None:
    if (
        component.source_id != GENERATED_SOURCE_ID
        or component.origin is not Origin.GENERATED
        or component.component_type != "standard_module"
        or component.vb_name != GENERATED_VB_NAME
        or not _LEGAL_VB_NAME.fullmatch(component.vb_name)
        or component.package_id != GENERATED_PACKAGE_ID
        or component.disposition != "candidate"
        or len(component.members) != 1
        or component.members[0].role != "source"
    ):
        diagnostics.append(
            _diagnostic(
                "GENERATED_IDENTITY_INVALID",
                "generated component identity is invalid",
                line=1,
                token=GENERATED_VB_NAME,
            )
        )
        return

    try:
        decoded = decode_vba(component.members[0].data, "cp936")
    except SourceError as error:
        diagnostics.append(
            _diagnostic(
                "GENERATED_IDENTITY_INVALID",
                "generated component cannot be decoded for identity validation",
                line=1,
                token=str(error),
            )
        )
        return
    names = _VB_NAME_ATTRIBUTE.findall(decoded.text)
    if names != [GENERATED_VB_NAME]:
        diagnostics.append(
            _diagnostic(
                "GENERATED_IDENTITY_INVALID",
                "generated Attribute VB_Name does not match component identity",
                line=1,
                token=GENERATED_VB_NAME,
            )
        )


def generate_sources(
    resolved: ResolvedSourceSet,
    manifests: ManifestSet,
) -> GeneratedSourceSet:
    """Generate deterministic CP936/CRLF static catalog source offline."""
    inherited = _report(
        list(manifests.report.diagnostics),
        list(resolved.report.diagnostics),
    )
    if not inherited.ok:
        return GeneratedSourceSet(components=(), report=inherited)

    diagnostics: list[Diagnostic] = []
    tools = _tool_records(manifests, diagnostics)
    if diagnostics:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))

    packages = tuple(
        record
        for record in manifests.packages.get("packages", [])
        if isinstance(record, dict)
    )
    resolved_policy_catalog = _CatalogView(
        components=resolved.components,
        packages=packages,
        tools=tools,
        report=ValidationReport(),
    )
    resolved_policy_report = validate_catalog(
        cast(ResolvedCatalog, resolved_policy_catalog)
    )
    diagnostics.extend(resolved_policy_report.diagnostics)
    if diagnostics:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))
    if not tools:
        return GeneratedSourceSet(components=(), report=inherited)

    core_package = _core_package(manifests, diagnostics)
    _generated_collision_diagnostics(resolved, diagnostics)
    if core_package is None or diagnostics:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))

    text = _source_text(tools)
    data = _encode_source(text, diagnostics)
    if data is None:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))

    member = SourceMember(
        path=GENERATED_PATH,
        blob_oid=None,
        raw_sha256=hashlib.sha256(data).hexdigest(),
        role="source",
        data=data,
    )
    component = Component(
        source_id=GENERATED_SOURCE_ID,
        origin=Origin.GENERATED,
        component_type="standard_module",
        vb_name=GENERATED_VB_NAME,
        members=(member,),
        package_id=GENERATED_PACKAGE_ID,
        disposition="candidate",
    )

    path_report = validate_portable_paths((member.path,))
    for finding in path_report.diagnostics:
        diagnostics.append(
            _diagnostic(
                finding.code,
                finding.message,
                line=1,
                token=member.path,
            )
        )
    _validate_identity(component, diagnostics)

    policy_catalog = _CatalogView(
        components=(*resolved.components, component),
        packages=packages,
        tools=tools,
        report=ValidationReport(),
    )
    policy_report = validate_catalog(cast(ResolvedCatalog, policy_catalog))
    diagnostics.extend(policy_report.diagnostics)
    report = _report(diagnostics)
    if not report.ok:
        return GeneratedSourceSet(components=(), report=report)
    return GeneratedSourceSet(components=(component,), report=inherited)
