from __future__ import annotations

import re
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
    "PowerShell",
    "ScriptControl",
    "Shell",
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
_OPTION_EXPLICIT = re.compile(
    r"(?:^|:)\s*Option\s+Explicit\s*(?=:|$)", re.IGNORECASE
)
_DECLARE = re.compile(r"(?<![A-Za-z0-9_])Declare(?![A-Za-z0-9_])", re.IGNORECASE)
_PTRSAFE = re.compile(r"(?<![A-Za-z0-9_])PtrSafe(?![A-Za-z0-9_])", re.IGNORECASE)
_PUBLIC_TYPE = re.compile(
    rf"(?:^|:)\s*Public\s+Type\s+({_IDENTIFIER})\b", re.IGNORECASE
)
_PUBLIC_CLASS_MEMBER = re.compile(
    rf"(?:^|:)\s*Public\s+"
    rf"(?:(?:Default|Static)\s+)*"
    rf"(?:Sub|Function|Property\s+(?:Get|Let|Set))\s+"
    rf"{_IDENTIFIER}\b(?P<signature>[^:]*)",
    re.IGNORECASE,
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
    return "".join(result)


def _sanitized_lines(text: str) -> tuple[str, ...]:
    return tuple(_strip_strings_and_comments(line) for line in text.splitlines())


def _logical_statements(lines: tuple[str, ...]) -> tuple[_LogicalStatement, ...]:
    statements: list[_LogicalStatement] = []
    parts: list[str] = []
    start_line = 1

    for line_number, line in enumerate(lines, start=1):
        if not parts:
            start_line = line_number
        continuation = re.search(r"(?:^|\s)_\s*$", line)
        if continuation is None:
            parts.append(line)
            statements.append(
                _LogicalStatement(text=" ".join(parts), line=start_line)
            )
            parts = []
            continue
        parts.append(line[: continuation.start()].rstrip())

    if parts:
        statements.append(_LogicalStatement(text=" ".join(parts), line=start_line))
    return tuple(statements)


def _is_binary_frx(member: SourceMember) -> bool:
    return member.role == "frx" or PurePosixPath(member.path).suffix.casefold() == ".frx"


def _decode_sources(
    components: tuple[Component, ...], diagnostics: list[Diagnostic]
) -> tuple[_SourceText, ...]:
    sources: list[_SourceText] = []
    for component in components:
        for member in component.members:
            if _is_binary_frx(member):
                continue
            try:
                decoded = decode_vba(member.data)
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
            sources.append(
                _SourceText(
                    component=component,
                    member=member,
                    lines=_sanitized_lines(decoded.text),
                )
            )
    return tuple(sources)


def _required_syntax(source: _SourceText, diagnostics: list[Diagnostic]) -> None:
    if not any(_OPTION_EXPLICIT.search(line) for line in source.lines):
        diagnostics.append(
            _diagnostic(
                "OPTION_EXPLICIT_REQUIRED",
                source.member.path,
                "VBA source requires Option Explicit",
                line=1,
                token="Option Explicit",
            )
        )

    for statement in _logical_statements(source.lines):
        declaration = _DECLARE.search(statement.text)
        if declaration is None or _PTRSAFE.search(statement.text) is not None:
            continue
        declare_line = next(
            (
                line_number
                for line_number, line in enumerate(source.lines, start=1)
                if _DECLARE.search(line)
                and line_number >= statement.line
            ),
            statement.line,
        )
        diagnostics.append(
            _diagnostic(
                "DECLARE_PTRSAFE_REQUIRED",
                source.member.path,
                "VBA7 64-bit Declare requires PtrSafe",
                line=declare_line,
                token="Declare",
            )
        )


def _package_records(catalog: ResolvedCatalog) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for record in catalog.packages:
        package_id = record.get("package_id")
        if isinstance(package_id, str) and package_id not in records:
            records[package_id] = record
    return records


def _token_pattern(token: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


def _token_findings(
    source: _SourceText,
    package: dict[str, Any] | None,
    diagnostics: list[Diagnostic],
) -> None:
    if package is None:
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

    hard_tokens: tuple[str, ...] = ()
    if package.get("classification") == "CORE_CANDIDATE":
        hard_tokens = CORE_HARD_DENY_TOKENS

    configured = package.get("additional_deny_tokens", [])
    additional_tokens = (
        tuple(token for token in configured if isinstance(token, str) and token)
        if isinstance(configured, list)
        else ()
    )
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
        for line in source.lines:
            for match in _PUBLIC_TYPE.finditer(line):
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
                if _token_pattern(name).search(signature) is None:
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


def validate_catalog(catalog: ResolvedCatalog) -> ValidationReport:
    """Return deterministic structural policy evidence for an offline catalog.

    This scanner is intentionally not a VBA compiler and does not make runtime,
    reference, license, or target-machine verification claims.
    """
    diagnostics = list(catalog.report.diagnostics)
    sources = _decode_sources(catalog.components, diagnostics)
    packages = _package_records(catalog)

    for source in sources:
        _required_syntax(source, diagnostics)
        package = (
            packages.get(source.component.package_id)
            if isinstance(source.component.package_id, str)
            else None
        )
        _token_findings(source, package, diagnostics)

    _udt_exposure_findings(sources, diagnostics)
    return ValidationReport(_stable_diagnostics(diagnostics))
