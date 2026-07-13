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
    GeneratedSourceDescriptor,
    GeneratedSourceSet,
    GIT_OBJECT_ID_PATTERN,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    ResolvedSourceSet,
    SHA256_DIGEST_PATTERN,
    SourceMember,
    TOOL_VERSION_PATTERN,
    ValidationReport,
)
from .policy import validate_catalog
from .portable_paths import portable_key, validate_portable_paths
from .runtime_contract import PROTOCOL_VERSION, control_name, page_name


GENERATED_PACKAGE_ID = "core"
GENERATED_SOURCE_DESCRIPTORS = (
    GeneratedSourceDescriptor(
        source_id="generated.build-info",
        vb_name="MM_BuildInfo",
        path="generated/MM_BuildInfo.bas",
    ),
    GeneratedSourceDescriptor(
        source_id="generated.dispatch",
        vb_name="MM_Dispatch",
        path="generated/MM_Dispatch.bas",
    ),
    GeneratedSourceDescriptor(
        source_id="generated.menu-catalog",
        vb_name="MM_MenuCatalog",
        path="generated/MM_MenuCatalog.bas",
    ),
)

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
    path: str = "generated",
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
        required_strings = (
            "tool_id",
            "caption",
            "tooltip",
            "group_id",
            "group_caption",
            "module_name",
            "entrypoint",
        )
        values = {field: record.get(field) for field in required_strings}
        if any(not isinstance(value, str) for value in values.values()):
            diagnostics.append(
                _diagnostic(
                    "TOOL_RECORD_INVALID",
                    "tool entry requires all generated fields to be strings",
                    path=f"tools.json#/tools/{index}",
                    line=1,
                    token="/".join(required_strings),
                )
            )
            continue
        tool_id = cast(str, values["tool_id"])
        invalid_identifier = next(
            (
                field
                for field in ("module_name", "entrypoint")
                if _LEGAL_VB_NAME.fullmatch(cast(str, values[field])) is None
            ),
            None,
        )
        if invalid_identifier is not None:
            diagnostics.append(
                _diagnostic(
                    "TOOL_RECORD_INVALID",
                    "dispatcher bindings must be plain VBA identifiers",
                    path=f"tools.json#/tools/{index}/{invalid_identifier}",
                    line=1,
                    token=invalid_identifier,
                )
            )
            continue
        invalid_field = next(
            (
                field
                for field, value in values.items()
                if isinstance(value, str)
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


def _array_assignment(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    encoded = ", ".join(_vba_string(value) for value in values)
    return (
        f"Public Function {name}() As Variant",
        f"    {name} = Array({encoded})",
        "End Function",
        "",
    )


def _menu_catalog_text(tools: tuple[dict[str, Any], ...]) -> str:
    fields = (
        ("MM_ToolIds", "tool_id"),
        ("MM_ToolCaptions", "caption"),
        ("MM_ToolTooltips", "tooltip"),
        ("MM_ToolGroupIds", "group_id"),
        ("MM_ToolGroupCaptions", "group_caption"),
    )
    lines: tuple[str, ...] = (
        'Attribute VB_Name = "MM_MenuCatalog"',
        "Option Explicit",
        "",
    )
    for function_name, field in fields:
        lines += _array_assignment(
            function_name,
            tuple(cast(str, tool[field]) for tool in tools),
        )
    lines += _array_assignment(
        "MM_ToolControlNames",
        tuple(control_name(cast(str, tool["tool_id"])) for tool in tools),
    )
    lines += _array_assignment(
        "MM_ToolPageNames",
        tuple(page_name(cast(str, tool["group_id"])) for tool in tools),
    )
    return "\n".join(lines)


def _dispatch_text(tools: tuple[dict[str, Any], ...]) -> str:
    cases: list[str] = []
    for tool in tools:
        tool_id = _vba_string(cast(str, tool["tool_id"]))
        module_name = cast(str, tool["module_name"])
        entrypoint = cast(str, tool["entrypoint"])
        cases.extend(
            (
                f"        Case {tool_id}",
                f"            Set result = {module_name}.{entrypoint}(context)",
            )
        )
    lines = (
        'Attribute VB_Name = "MM_Dispatch"',
        "Option Explicit",
        "",
        "Public Function Core_Invoke(ByVal request As Variant) As Variant",
        "    Dim requestId As String",
        "    Dim commandId As String",
        "    Dim context As C_MMContext",
        "    Dim result As C_MMResult",
        "    On Error GoTo Fail",
        "    If Not MM_Protocol.TryParseRequest(request, requestId, commandId, context, result) Then GoTo CleanExit",
        "    Select Case commandId",
        *cases,
        "        Case Else",
        "            Set result = MM_Error.UnknownCommand(commandId)",
        "    End Select",
        "CleanExit:",
        "    Core_Invoke = MM_Protocol.BuildResponse(requestId, result)",
        "    Exit Function",
        "Fail:",
        "    Set result = MM_Error.InternalError(Err.Number)",
        "    Resume CleanExit",
        "End Function",
        "",
    )
    return "\n".join(lines)


def _build_info_text(snapshot: InputSnapshot) -> str:
    lines = (
        'Attribute VB_Name = "MM_BuildInfo"',
        "Option Explicit",
        "",
        f"Public Const MM_PROTOCOL_VERSION As String = {_vba_string(PROTOCOL_VERSION)}",
        f"Public Const MM_MANIFEST_DIGEST As String = {_vba_string(snapshot.manifest_digest)}",
        f"Public Const MM_WORK_COMMIT As String = {_vba_string(snapshot.work_commit)}",
        f"Public Const MM_WORK_TREE As String = {_vba_string(snapshot.work_tree)}",
        f"Public Const MM_TOOL_VERSION As String = {_vba_string(snapshot.tool_version)}",
        "",
    )
    return "\n".join(lines)


def _source_texts(
    tools: tuple[dict[str, Any], ...], snapshot: InputSnapshot
) -> dict[str, str]:
    return {
        "generated.menu-catalog": _menu_catalog_text(tools),
        "generated.dispatch": _dispatch_text(tools),
        "generated.build-info": _build_info_text(snapshot),
    }


def _encode_source(
    text: str, path: str, diagnostics: list[Diagnostic]
) -> bytes | None:
    try:
        return text.replace("\n", "\r\n").encode("cp936", errors="strict")
    except UnicodeEncodeError as error:
        line = text[: error.start].count("\n") + 1
        diagnostics.append(
            _diagnostic(
                "GENERATED_CP936_UNENCODABLE",
                "generated catalog is not representable in strict CP936",
                path=path,
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


def _snapshot_diagnostics(snapshot: InputSnapshot) -> tuple[Diagnostic, ...]:
    fields = (
        ("work_commit", snapshot.work_commit, GIT_OBJECT_ID_PATTERN),
        ("work_tree", snapshot.work_tree, GIT_OBJECT_ID_PATTERN),
        ("manifest_digest", snapshot.manifest_digest, SHA256_DIGEST_PATTERN),
        ("tool_version", snapshot.tool_version, TOOL_VERSION_PATTERN),
    )
    return tuple(
        _diagnostic(
            "GENERATED_SNAPSHOT_INVALID",
            "generated BuildInfo snapshot field is invalid",
            path=f"snapshot/{field}",
            line=1,
            token=field,
        )
        for field, value, pattern in fields
        if type(value) is not str or pattern.fullmatch(value) is None
    )


def _vb_name_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _generated_collision_diagnostics(
    resolved: ResolvedSourceSet, diagnostics: list[Diagnostic]
) -> None:
    descriptors_by_source = {
        descriptor.source_id: descriptor for descriptor in GENERATED_SOURCE_DESCRIPTORS
    }
    descriptors_by_path = {
        portable_key(descriptor.path): descriptor
        for descriptor in GENERATED_SOURCE_DESCRIPTORS
    }
    descriptors_by_basename = {
        portable_key(PurePosixPath(descriptor.path).name): descriptor
        for descriptor in GENERATED_SOURCE_DESCRIPTORS
    }
    descriptors_by_vb_name = {
        _vb_name_key(descriptor.vb_name): descriptor
        for descriptor in GENERATED_SOURCE_DESCRIPTORS
    }

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
            default="generated",
        )
        source_collision = descriptors_by_source.get(component.source_id)
        if source_collision is not None:
            diagnostics.append(
                _diagnostic(
                    "GENERATED_SOURCE_ID_COLLISION",
                    "generated source_id collides with a resolved component",
                    path=first_path,
                    line=1,
                    token=source_collision.source_id,
                )
            )

        name_collision = descriptors_by_vb_name.get(
            _vb_name_key(component.vb_name)
        )
        if (
            component.package_id == GENERATED_PACKAGE_ID
            and name_collision is not None
        ):
            diagnostics.append(
                _diagnostic(
                    "GENERATED_VB_NAME_COLLISION",
                    "generated VB_Name collides within its package",
                    path=first_path,
                    line=1,
                    token=name_collision.vb_name,
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
            path_collision = descriptors_by_path.get(member_path_key)
            if path_collision is not None:
                diagnostics.append(
                    _diagnostic(
                        "GENERATED_PATH_SHADOW",
                        "generated path shadows a resolved member portable path",
                        path=member.path,
                        line=1,
                        token=path_collision.path,
                    )
                )
            basename_collision = descriptors_by_basename.get(basename_key)
            if (
                component.package_id == GENERATED_PACKAGE_ID
                and basename_collision is not None
            ):
                diagnostics.append(
                    _diagnostic(
                        "GENERATED_OUTPUT_BASENAME_COLLISION",
                        "generated output basename collides within its package",
                        path=member.path,
                        line=1,
                        token=PurePosixPath(basename_collision.path).name,
                    )
                )


def _validate_identity(
    component: Component,
    descriptor: GeneratedSourceDescriptor,
    diagnostics: list[Diagnostic],
) -> None:
    if (
        component.source_id != descriptor.source_id
        or component.origin is not Origin.GENERATED
        or component.component_type != "standard_module"
        or component.vb_name != descriptor.vb_name
        or not _LEGAL_VB_NAME.fullmatch(component.vb_name)
        or component.package_id != GENERATED_PACKAGE_ID
        or component.disposition != "candidate"
        or len(component.members) != 1
        or component.members[0].path != descriptor.path
        or component.members[0].role != "source"
    ):
        diagnostics.append(
            _diagnostic(
                "GENERATED_IDENTITY_INVALID",
                "generated component identity is invalid",
                path=descriptor.path,
                line=1,
                token=descriptor.vb_name,
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
                path=descriptor.path,
                line=1,
                token=str(error),
            )
        )
        return
    names = _VB_NAME_ATTRIBUTE.findall(decoded.text)
    if names != [descriptor.vb_name]:
        diagnostics.append(
            _diagnostic(
                "GENERATED_IDENTITY_INVALID",
                "generated Attribute VB_Name does not match component identity",
                path=descriptor.path,
                line=1,
                token=descriptor.vb_name,
            )
        )


def generate_sources(
    resolved: ResolvedSourceSet,
    manifests: ManifestSet,
    snapshot: InputSnapshot,
) -> GeneratedSourceSet:
    """Generate the exact deterministic CP936/CRLF Core runtime modules."""
    inherited = _report(
        list(manifests.report.diagnostics),
        list(resolved.report.diagnostics),
    )
    if not inherited.ok:
        return GeneratedSourceSet(components=(), report=inherited)

    diagnostics = list(_snapshot_diagnostics(snapshot))
    if diagnostics:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))
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
    core_package = _core_package(manifests, diagnostics)
    _generated_collision_diagnostics(resolved, diagnostics)
    if core_package is None or diagnostics:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))

    core_tools = tuple(
        tool for tool in tools if tool.get("package_id") == GENERATED_PACKAGE_ID
    )
    texts = _source_texts(core_tools, snapshot)
    components: list[Component] = []
    for descriptor in GENERATED_SOURCE_DESCRIPTORS:
        data = _encode_source(
            texts[descriptor.source_id], descriptor.path, diagnostics
        )
        if data is None:
            continue
        member = SourceMember(
            path=descriptor.path,
            blob_oid=None,
            raw_sha256=hashlib.sha256(data).hexdigest(),
            role="source",
            data=data,
        )
        component = Component(
            source_id=descriptor.source_id,
            origin=Origin.GENERATED,
            component_type="standard_module",
            vb_name=descriptor.vb_name,
            members=(member,),
            package_id=GENERATED_PACKAGE_ID,
            disposition="candidate",
            encoding_decision="cp936",
        )
        _validate_identity(component, descriptor, diagnostics)
        components.append(component)

    path_report = validate_portable_paths(
        tuple(
            member.path
            for component in components
            for member in component.members
        )
    )
    for finding in path_report.diagnostics:
        diagnostics.append(
            _diagnostic(
                finding.code,
                finding.message,
                path=finding.path,
                line=1,
                token=finding.path,
            )
        )
    if diagnostics:
        return GeneratedSourceSet(components=(), report=_report(diagnostics))

    policy_catalog = _CatalogView(
        components=(*resolved.components, *components),
        packages=packages,
        tools=tools,
        report=ValidationReport(),
    )
    policy_report = validate_catalog(cast(ResolvedCatalog, policy_catalog))
    diagnostics.extend(policy_report.diagnostics)
    report = _report(diagnostics)
    if not report.ok:
        return GeneratedSourceSet(components=(), report=report)
    return GeneratedSourceSet(
        components=tuple(sorted(components, key=lambda item: item.source_id)),
        report=inherited,
    )
