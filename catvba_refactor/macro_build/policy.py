from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .encoding import decode_vba
from .errors import SourceError
from .model import (
    Component,
    Diagnostic,
    ResolvedCatalog,
    SourceMember,
    ValidationReport,
)


CORE_HARD_DENY_POLICY_VERSION = 1

# This tuple is deliberately code-owned. Manifests can append package-specific
# deny tokens, but cannot subtract from or override the Core baseline.
CORE_HARD_DENY_TOKENS = (
    # Runtime source/project inspection and VBIDE/MSAPC coupling.
    "APC",
    "CodeModule",
    "CodeModules",
    "MSAPC",
    "VBE",
    "VBComponent",
    "VBComponents",
    "VBIDE",
    "VBProject",
    "VBProjects",
    # Shell and Windows Script Host execution.
    "CScript",
    "ExecuteScript",
    "PowerShell",
    "ScriptControl",
    "Shell",
    "SystemService",
    "WSH",
    "WScript",
    "WScriptShell",
    # Network and URL APIs.
    "HttpOpenRequest",
    "HttpSendRequest",
    "InternetConnect",
    "InternetOpen",
    "InternetOpenUrl",
    "MSXML2",
    "ServerXMLHTTP",
    "URLDownloadToFile",
    "WebClient",
    "WinHTTP",
    "WinHttpRequest",
    "XMLHTTP",
    # License mutation and repository manipulation.
    "CATSysLicenseSettingCtrl",
    "LicenseSettingAtt",
    "LicensingRepository",
    "LicensingRepositorySettingAtt",
    "SetLicense",
    # Office external integration.
    "Excel",
    "Office",
    "Outlook",
    "Word",
    "Workbook",
    "Workbooks",
    "Worksheet",
    "Worksheets",
    # SPA/FTA early-bound or capability-specific identifiers.
    "AnnotationSet",
    "AnnotationSets",
    "CreateFlagNote",
    "Marker3Ds",
    "SPATypeLib",
    "SPAWorkbench",
    # Explicitly excluded legacy runtime dependencies.
    "A00_Menu",
    "Cls_allBTNEVT",
    "Cls_DynaWD",
    "cls_MnUI",
    "Cls_PDM",
    "Cls_VbaMdlMgr",
    "Cls_XLM",
    "DevTools",
    "KCL",
    "pdm",
    "toMP",
    "xlm",
)


_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_STABLE_TOOL_ID = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")
_OPTION_EXPLICIT = re.compile(r"^\s*Option\s+Explicit\s*$", re.IGNORECASE)
_DECLARE = re.compile(r"(?<![A-Za-z0-9_])Declare(?![A-Za-z0-9_])", re.IGNORECASE)
_DECLARE_PREFIX = re.compile(
    r"^\s*(?:(?:Public|Private)\s+)?$", re.IGNORECASE
)
_VALID_DECLARE_TAIL = re.compile(
    r"Declare\s+PtrSafe\s+(?:Sub|Function)\b",
    re.IGNORECASE,
)
_PROCEDURE_START = re.compile(
    r"^\s*(?:(?:Public|Private|Friend)\s+)?"
    r"(?:(?:Default|Static)\s+)*"
    r"(?P<kind>Sub|Function|Property\s+(?:Get|Let|Set))\b",
    re.IGNORECASE,
)
_PROCEDURE_END = re.compile(
    r"^\s*End\s+(?P<kind>Sub|Function|Property)\s*$", re.IGNORECASE
)
_PUBLIC_TYPE = re.compile(
    rf"^\s*Public\s+Type\s+({_IDENTIFIER})\b", re.IGNORECASE
)
_PUBLIC_CLASS_MEMBER = re.compile(
    rf"^\s*Public\s+"
    rf"(?:(?:Default|Static)\s+)*"
    rf"(?:Sub|Function|Event|Property\s+(?:Get|Let|Set))\s+"
    rf"{_IDENTIFIER}\b(?P<signature>.*)",
    re.IGNORECASE,
)
_PUBLIC_ENTRYPOINT_PREFIX = (
    r"^\s*Public\s+(?:(?:Static)\s+)?(?:Sub|Function)\s+"
)


@dataclass(frozen=True)
class _SourceText:
    component: Component
    member: SourceMember
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _LogicalStatement:
    text: str
    line: int


@dataclass(frozen=True)
class _ProcedureFrame:
    kind: str
    candidate_line: int | None


def _diagnostic(
    code: str,
    path: str,
    message: str,
    *,
    line: int,
    token: str,
    **details: Any,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        path=path,
        message=message,
        details={**details, "line": line, "token": token},
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


def _stable_diagnostics(
    diagnostics: Iterable[Diagnostic],
) -> tuple[Diagnostic, ...]:
    unique: dict[tuple[Any, ...], Diagnostic] = {}
    for diagnostic in diagnostics:
        unique.setdefault(_diagnostic_key(diagnostic), diagnostic)
    return tuple(unique[key] for key in sorted(unique))


def _strip_strings_and_comments(line: str) -> str:
    """Blank VBA strings/comments while preserving token positions."""
    result = list(line)
    index = 0
    in_string = False
    while index < len(line):
        character = line[index]
        if in_string:
            result[index] = " "
            if character == '"':
                if index + 1 < len(line) and line[index + 1] == '"':
                    result[index + 1] = " "
                    index += 2
                    continue
                in_string = False
            index += 1
            continue

        if character == '"':
            result[index] = " "
            in_string = True
            index += 1
            continue
        if character == "'":
            for tail in range(index, len(result)):
                result[tail] = " "
            break
        index += 1
    sanitized = "".join(result)
    rem_comment = re.search(
        r"(?:^|:)\s*Rem(?:\s|$)", sanitized, re.IGNORECASE
    )
    if rem_comment is not None:
        start = rem_comment.start()
        if sanitized[start : start + 1] == ":":
            start += 1
        sanitized = sanitized[:start] + " " * (len(sanitized) - start)
    return sanitized


def _sanitized_lines(text: str) -> tuple[str, ...]:
    return tuple(_strip_strings_and_comments(line) for line in text.splitlines())


def _logical_statements(lines: tuple[str, ...]) -> tuple[_LogicalStatement, ...]:
    statements: list[_LogicalStatement] = []
    parts: list[str] = []
    start_line = 1

    def append_logical(text: str, line: int) -> None:
        # Strings and comments have already been blanked, so each remaining
        # colon is a real VBA statement separator rather than literal data.
        statements.extend(
            _LogicalStatement(text=part, line=line) for part in text.split(":")
        )

    for line_number, line in enumerate(lines, start=1):
        if not parts:
            start_line = line_number
        continuation = re.search(r"(?:^|\s)_\s*$", line)
        if continuation is None:
            parts.append(line)
            append_logical(" ".join(parts), start_line)
            parts = []
            continue
        parts.append(line[: continuation.start()].rstrip())

    if parts:
        append_logical(" ".join(parts), start_line)
    return tuple(statements)


def _is_binary_frx(member: SourceMember) -> bool:
    return member.role == "frx" or PurePosixPath(member.path).suffix.casefold() == ".frx"


def _policy_text_variants(
    data: bytes, declared_encoding: str | None
) -> tuple[str, ...]:
    """Decode exactly the text identity already decided by inventory."""
    return (decode_vba(data, declared_encoding).text,)


def _decode_sources(
    components: tuple[Component, ...], diagnostics: list[Diagnostic]
) -> tuple[_SourceText, ...]:
    sources: list[_SourceText] = []
    for component in components:
        for member in component.members:
            if _is_binary_frx(member):
                continue
            try:
                variants = _policy_text_variants(
                    member.data, component.encoding_decision
                )
            except SourceError as error:
                diagnostics.append(
                    _diagnostic(
                        "POLICY_SOURCE_ENCODING",
                        member.path,
                        "VBA policy source cannot be decoded without replacement",
                        line=1,
                        token=str(error),
                    )
                )
                continue

            # Different strict decodings often differ only within strings.
            # Deduplicate identical sanitized variants before scanning.
            seen_lines: set[tuple[str, ...]] = set()
            for text in variants:
                lines = _sanitized_lines(text)
                if lines in seen_lines:
                    continue
                seen_lines.add(lines)
                sources.append(
                    _SourceText(
                        component=component,
                        member=member,
                        lines=lines,
                    )
                )
    return tuple(sources)


def _required_syntax(source: _SourceText, diagnostics: list[Diagnostic]) -> None:
    statements = _logical_statements(source.lines)
    in_procedure = False
    procedure_seen = False
    valid_option = False
    for statement in statements:
        text = statement.text
        if _PROCEDURE_END.fullmatch(text):
            in_procedure = False
            continue
        if _PROCEDURE_START.match(text):
            in_procedure = True
            procedure_seen = True
            continue
        if (
            _OPTION_EXPLICIT.fullmatch(text)
            and not in_procedure
            and not procedure_seen
        ):
            valid_option = True

    if not valid_option:
        diagnostics.append(
            _diagnostic(
                "OPTION_EXPLICIT_REQUIRED",
                source.member.path,
                "VBA source requires Option Explicit",
                line=1,
                token="Option Explicit",
            )
        )

    for statement in statements:
        for declaration in _DECLARE.finditer(statement.text):
            prefix = statement.text[: declaration.start()]
            if (
                _DECLARE_PREFIX.fullmatch(prefix) is not None
                and _VALID_DECLARE_TAIL.match(
                    statement.text, declaration.start()
                )
                is not None
            ):
                continue
            diagnostics.append(
                _diagnostic(
                    "DECLARE_PTRSAFE_REQUIRED",
                    source.member.path,
                    "VBA7 64-bit Declare requires PtrSafe",
                    line=statement.line,
                    token="Declare",
                )
            )


def _package_records(
    catalog: ResolvedCatalog, diagnostics: list[Diagnostic]
) -> dict[str, tuple[dict[str, Any], ...]]:
    indexed: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, record in enumerate(catalog.packages):
        if not isinstance(record, dict):
            continue
        package_id = record.get("package_id")
        if isinstance(package_id, str):
            indexed[package_id].append((index, record))

    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for package_id in sorted(indexed):
        matches = indexed[package_id]
        result[package_id] = tuple(record for _index, record in matches)
        if len(matches) > 1:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_PACKAGE_ID",
                    f"packages.json#/packages/{matches[1][0]}/package_id",
                    "package_id is not unique",
                    line=1,
                    token=package_id,
                )
            )
    return result


def _token_pattern(token: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


def _token_findings(
    source: _SourceText,
    packages: tuple[dict[str, Any], ...],
    diagnostics: list[Diagnostic],
) -> None:
    if not packages:
        diagnostics.append(
            _diagnostic(
                "PACKAGE_BINDING_INVALID",
                source.member.path,
                "source component references an unknown package",
                line=1,
                token=source.component.package_id or "<missing>",
            )
        )
        return

    if len(packages) != 1:
        diagnostics.append(
            _diagnostic(
                "PACKAGE_BINDING_INVALID",
                source.member.path,
                "source component package binding is ambiguous",
                line=1,
                token=source.component.package_id or "<missing>",
            )
        )

    hard_tokens: tuple[str, ...] = ()
    if any(
        package.get("classification") == "CORE_CANDIDATE"
        for package in packages
    ):
        hard_tokens = CORE_HARD_DENY_TOKENS

    configured_tokens: list[str] = []
    for package in packages:
        configured = package.get("additional_deny_tokens", [])
        if isinstance(configured, list):
            configured_tokens.extend(
                token for token in configured if isinstance(token, str) and token
            )
    additional_tokens = tuple(configured_tokens)
    hard_keys = {token.casefold() for token in hard_tokens}
    additional_tokens = tuple(
        token for token in additional_tokens if token.casefold() not in hard_keys
    )

    policies = (
        (
            "CORE_TOKEN_DENIED",
            "Core source contains a code-owned denied token",
            hard_tokens,
        ),
        (
            "PACKAGE_TOKEN_DENIED",
            "source contains a package-specific denied token",
            additional_tokens,
        ),
    )
    for code, message, tokens in policies:
        for token in sorted(tokens, key=lambda value: (value.casefold(), value)):
            pattern = _token_pattern(token)
            for line_number, line in enumerate(source.lines, start=1):
                if pattern.search(line) is not None:
                    diagnostics.append(
                        _diagnostic(
                            code,
                            source.member.path,
                            message,
                            line=line_number,
                            token=token,
                        )
                    )


def _public_udts(
    sources: tuple[_SourceText, ...],
) -> dict[str, tuple[str, str]]:
    declarations: dict[str, tuple[str, str]] = {}
    for source in sources:
        if source.component.component_type != "standard_module":
            continue
        for statement in _logical_statements(source.lines):
            for match in _PUBLIC_TYPE.finditer(statement.text):
                name = match.group(1)
                candidate = (name, source.member.path)
                current = declarations.get(name.casefold())
                if current is None or candidate < current:
                    declarations[name.casefold()] = candidate
    return declarations


def _udt_exposure_findings(
    sources: tuple[_SourceText, ...], diagnostics: list[Diagnostic]
) -> None:
    declarations = _public_udts(sources)
    if not declarations:
        return

    for source in sources:
        if source.component.component_type != "class_module":
            continue
        for statement in _logical_statements(source.lines):
            public_member = _PUBLIC_CLASS_MEMBER.search(statement.text)
            if public_member is None:
                continue
            signature = public_member.group("signature")
            for folded_name in sorted(declarations):
                name, declared_path = declarations[folded_name]
                type_use = re.compile(
                    rf"(?<![A-Za-z0-9_])As\s+{re.escape(name)}"
                    rf"(?![A-Za-z0-9_])",
                    re.IGNORECASE,
                )
                if type_use.search(signature) is None:
                    continue
                diagnostics.append(
                    _diagnostic(
                        "PUBLIC_UDT_EXPOSED",
                        source.member.path,
                        "public class signature exposes a standard-module public UDT",
                        declared_path=declared_path,
                        line=statement.line,
                        token=name,
                    )
                )


def _module_scope_entrypoint_lines(
    source: _SourceText, entrypoint_pattern: re.Pattern[str]
) -> tuple[int, ...]:
    lines: list[int] = []
    procedure_stack: list[_ProcedureFrame] = []
    poisoned = False
    for statement in _logical_statements(source.lines):
        text = statement.text
        procedure_end = _PROCEDURE_END.fullmatch(text)
        if procedure_end is not None:
            if not procedure_stack:
                poisoned = True
                continue

            frame = procedure_stack.pop()
            closing_kind = procedure_end.group("kind").casefold()
            if frame.kind != closing_kind:
                poisoned = True
                continue
            if not procedure_stack and frame.candidate_line is not None:
                lines.append(frame.candidate_line)
            continue

        procedure_start = _PROCEDURE_START.match(text)
        if procedure_start is None:
            continue

        at_module_scope = not procedure_stack
        if not at_module_scope:
            poisoned = True
        raw_kind = procedure_start.group("kind").casefold()
        kind = "property" if raw_kind.startswith("property") else raw_kind
        candidate_line = (
            statement.line
            if at_module_scope and entrypoint_pattern.match(text) is not None
            else None
        )
        procedure_stack.append(_ProcedureFrame(kind, candidate_line))

    if procedure_stack:
        poisoned = True
    return () if poisoned else tuple(lines)


def _tool_binding_findings(
    catalog: ResolvedCatalog,
    sources: tuple[_SourceText, ...],
    packages: dict[str, tuple[dict[str, Any], ...]],
    diagnostics: list[Diagnostic],
) -> None:
    source_variants: dict[int, list[_SourceText]] = defaultdict(list)
    for source in sources:
        source_variants[id(source.component)].append(source)

    seen_ids: dict[str, int] = {}
    required_fields = ("tool_id", "package_id", "module_name", "entrypoint")
    for index, tool in enumerate(catalog.tools):
        record_path = f"tools.json#/tools/{index}"
        if not isinstance(tool, dict) or any(
            not isinstance(tool.get(field), str) or not tool.get(field)
            for field in required_fields
        ):
            diagnostics.append(
                _diagnostic(
                    "TOOL_RECORD_INVALID",
                    record_path,
                    "tool requires non-empty string identity and binding fields",
                    line=1,
                    token="tool",
                )
            )
            continue

        tool_id = tool["tool_id"]
        if _STABLE_TOOL_ID.fullmatch(tool_id) is None:
            diagnostics.append(
                _diagnostic(
                    "TOOL_ID_INVALID",
                    f"{record_path}/tool_id",
                    "tool_id does not use the stable catalog ID grammar",
                    line=1,
                    token=tool_id,
                )
            )
        if tool_id in seen_ids:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_TOOL_ID",
                    f"{record_path}/tool_id",
                    "tool_id is not unique",
                    line=1,
                    token=tool_id,
                )
            )
        else:
            seen_ids[tool_id] = index

        package_id = tool["package_id"]
        package_matches = packages.get(package_id, ())
        if len(package_matches) != 1:
            diagnostics.append(
                _diagnostic(
                    "TOOL_PACKAGE_BINDING_INVALID",
                    f"{record_path}/package_id",
                    "tool must bind to exactly one existing package",
                    line=1,
                    token=package_id,
                )
            )
            continue

        module_name = tool["module_name"]
        module_matches = [
            component
            for component in catalog.components
            if component.package_id == package_id
            and component.vb_name == module_name
        ]
        if (
            len(module_matches) != 1
            or module_matches[0].component_type != "standard_module"
        ):
            diagnostics.append(
                _diagnostic(
                    "TOOL_MODULE_BINDING_INVALID",
                    f"{record_path}/module_name",
                    "tool module must resolve to one standard module in its package",
                    line=1,
                    token=module_name,
                )
            )
            continue

        component = module_matches[0]
        entrypoint = tool["entrypoint"]
        entrypoint_pattern = re.compile(
            _PUBLIC_ENTRYPOINT_PREFIX
            + re.escape(entrypoint)
            + r"(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        variants = source_variants.get(id(component), [])
        variant_matches: list[tuple[int, ...]] = []
        for source in variants:
            variant_matches.append(
                _module_scope_entrypoint_lines(source, entrypoint_pattern)
            )
        if not variant_matches or any(
            len(lines) != 1 for lines in variant_matches
        ):
            found_lines = tuple(
                line for lines in variant_matches for line in lines
            )
            diagnostics.append(
                _diagnostic(
                    "TOOL_ENTRYPOINT_BINDING_INVALID",
                    f"{record_path}/entrypoint",
                    "tool entrypoint must resolve to one exact public Sub or Function",
                    line=min(found_lines, default=1),
                    token=entrypoint,
                )
            )


def validate_catalog(catalog: ResolvedCatalog) -> ValidationReport:
    """Return deterministic structural policy evidence for an offline catalog.

    This scanner is intentionally not a VBA compiler and does not make runtime,
    reference, license, or target-machine verification claims.
    """
    diagnostics = list(catalog.report.diagnostics)
    sources = _decode_sources(catalog.components, diagnostics)
    packages = _package_records(catalog, diagnostics)

    for source in sources:
        _required_syntax(source, diagnostics)
        package_matches = (
            packages.get(source.component.package_id)
            if isinstance(source.component.package_id, str)
            else None
        )
        _token_findings(source, package_matches or (), diagnostics)

    _udt_exposure_findings(sources, diagnostics)
    _tool_binding_findings(catalog, sources, packages, diagnostics)
    return ValidationReport(_stable_diagnostics(diagnostics))
