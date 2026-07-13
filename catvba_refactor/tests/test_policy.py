from __future__ import annotations

import hashlib
from typing import Any

import pytest

from catvba_refactor.macro_build.model import (
    Component,
    Diagnostic,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    SnapshotMode,
    SourceMember,
    ValidationReport,
)
from catvba_refactor.macro_build.policy import (
    CORE_HARD_DENY_POLICY_VERSION,
    CORE_HARD_DENY_TOKENS,
    validate_catalog,
)


def _snapshot() -> InputSnapshot:
    return InputSnapshot(
        mode=SnapshotMode.CANDIDATE,
        upstream_repository="verysolecd/Macro_menu",
        upstream_ref="dev",
        upstream_commit="1" * 40,
        fork_repository="doylenehemiah6893-afk/Macro_menu",
        fork_dev_commit="2" * 40,
        work_repository="doylenehemiah6893-afk/Macro_menu",
        work_branch="codex/dev-review-report",
        work_commit="3" * 40,
        work_tree="4" * 40,
        manifest_digest="5" * 64,
        tool_version="0.1.0",
        formal_eligible=True,
    )


def _member(path: str, text: str, *, role: str = "source") -> SourceMember:
    data = text.encode("utf-8")
    return SourceMember(
        path=path,
        blob_oid=hashlib.sha1(data).hexdigest(),
        raw_sha256=hashlib.sha256(data).hexdigest(),
        role=role,
        data=data,
    )


def _component(
    source_id: str,
    component_type: str,
    vb_name: str,
    text: str,
    *,
    package_id: str = "core",
) -> Component:
    extension = {
        "standard_module": "bas",
        "class_module": "cls",
        "user_form": "frm",
    }[component_type]
    return Component(
        source_id=source_id,
        origin=Origin.NEW,
        component_type=component_type,
        vb_name=vb_name,
        members=(
            _member(
                f"catvba_refactor/vba/new/{vb_name}.{extension}",
                text,
                role="frm" if component_type == "user_form" else "source",
            ),
        ),
        package_id=package_id,
        disposition="candidate",
    )


def _package(
    package_id: str,
    classification: str,
    *,
    additional_deny_tokens: list[str] | None = None,
    reference_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "package_id": package_id,
        "classification": classification,
    }
    if additional_deny_tokens is not None:
        result["additional_deny_tokens"] = additional_deny_tokens
    if reference_allowlist is not None:
        result["reference_allowlist"] = reference_allowlist
    return result


def _catalog(
    components: tuple[Component, ...],
    *,
    packages: tuple[dict[str, Any], ...] | None = None,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> ResolvedCatalog:
    return ResolvedCatalog(
        snapshot=_snapshot(),
        components=components,
        packages=packages
        or (_package("core", "CORE_CANDIDATE"),),
        tools=(),
        report=ValidationReport(diagnostics),
    )


def _source(body: str = "") -> str:
    return (
        'Attribute VB_Name = "SafeModule"\r\n'
        "Option Explicit\r\n"
        f"{body}"
    )


def test_requires_option_explicit_and_reports_exact_source_location() -> None:
    component = _component(
        "core.no-option",
        "standard_module",
        "NoOption",
        'Attribute VB_Name = "NoOption"\r\nPublic Sub Run()\r\nEnd Sub\r\n',
    )

    report = validate_catalog(_catalog((component,)))

    assert [item.code for item in report.diagnostics] == [
        "OPTION_EXPLICIT_REQUIRED"
    ]
    finding = report.diagnostics[0]
    assert finding.path == "catvba_refactor/vba/new/NoOption.bas"
    assert finding.details == {"line": 1, "token": "Option Explicit"}


def test_requires_ptrsafe_on_every_vba_declare_but_accepts_vba7_form() -> None:
    unsafe = _component(
        "core.unsafe-declare",
        "standard_module",
        "UnsafeDeclare",
        _source(
            "Private Declare Function GetTickCount Lib \"kernel32\" () As Long\r\n"
        ),
    )
    safe = _component(
        "core.safe-declare",
        "standard_module",
        "SafeDeclare",
        _source(
            "Private Declare PtrSafe Function GetTickCount64 Lib \"kernel32\" () As LongLong\r\n"
        ),
    )

    report = validate_catalog(_catalog((unsafe, safe)))

    assert [item.code for item in report.diagnostics] == [
        "DECLARE_PTRSAFE_REQUIRED"
    ]
    assert report.diagnostics[0].details == {"line": 3, "token": "Declare"}


@pytest.mark.parametrize(
    "token",
    [
        "VBProject",
        "VBComponents",
        "CodeModule",
        "VBIDE",
        "MSAPC",
        "Shell",
        "PowerShell",
        "WSH",
        "WinHttpRequest",
        "XMLHTTP",
        "URLDownloadToFile",
        "InternetOpen",
        "SetLicense",
        "LicensingRepository",
        "Office",
        "Excel",
        "SPAWorkbench",
        "SPATypeLib",
        "AnnotationSet",
        "Cls_PDM",
        "Cls_XLM",
        "KCL",
        "Cls_DynaWD",
        "Cls_VbaMdlMgr",
        "Cls_allBTNEVT",
        "cls_MnUI",
    ],
)
def test_versioned_core_hard_deny_tokens_are_exact_findings(token: str) -> None:
    component = _component(
        "core.denied",
        "standard_module",
        "Denied",
        _source(f"Public Sub Probe()\r\n    Call {token}\r\nEnd Sub\r\n"),
    )

    report = validate_catalog(_catalog((component,)))

    assert CORE_HARD_DENY_POLICY_VERSION == 1
    assert token.casefold() in {item.casefold() for item in CORE_HARD_DENY_TOKENS}
    assert [item.code for item in report.diagnostics] == ["CORE_TOKEN_DENIED"]
    finding = report.diagnostics[0]
    assert finding.path == "catvba_refactor/vba/new/Denied.bas"
    assert finding.details == {"line": 4, "token": token}


def test_strings_comments_and_identifier_substrings_do_not_trigger_tokens() -> None:
    component = _component(
        "core.lexical",
        "standard_module",
        "Lexical",
        _source(
            "Public Sub Probe()\r\n"
            "    Dim VBProjectCache As String\r\n"
            "    Dim ExcelReport As String\r\n"
            "    VBProjectCache = \"Shell \"\"VBProject\"\" Excel\" ' PowerShell WSH\r\n"
            "    ' URLDownloadToFile SetLicense SPAWorkbench AnnotationSet Cls_PDM\r\n"
            "End Sub\r\n"
        ),
    )

    report = validate_catalog(_catalog((component,)))

    assert report.ok


def test_declare_text_in_strings_and_comments_is_not_a_declaration() -> None:
    component = _component(
        "core.declare-text",
        "standard_module",
        "DeclareText",
        _source(
            "Public Sub Probe()\r\n"
            "    Dim note As String\r\n"
            "    note = \"Private Declare Function Example\"\r\n"
            "    ' Private Declare Function Example\r\n"
            "End Sub\r\n"
        ),
    )

    assert validate_catalog(_catalog((component,))).ok


def test_package_deny_tokens_only_tighten_and_reference_allowlist_cannot_relax_core() -> None:
    component = _component(
        "core.tightened",
        "standard_module",
        "Tightened",
        _source(
            "Public Sub Probe()\r\n"
            "    Call DangerApi\r\n"
            "    Call VBProject\r\n"
            "End Sub\r\n"
        ),
    )
    packages = (
        _package(
            "core",
            "CORE_CANDIDATE",
            additional_deny_tokens=["DangerApi"],
            reference_allowlist=["VBProject"],
        ),
    )

    report = validate_catalog(_catalog((component,), packages=packages))

    assert [(item.code, item.details) for item in report.diagnostics] == [
        ("CORE_TOKEN_DENIED", {"line": 5, "token": "VBProject"}),
        ("PACKAGE_TOKEN_DENIED", {"line": 4, "token": "DangerApi"}),
    ]


def test_spa_and_fta_identifiers_are_isolated_to_their_fleet_packages() -> None:
    spa = _component(
        "fleet-spa.probe",
        "standard_module",
        "SpaProbe",
        _source("Public Sub Probe()\r\n    Call SPAWorkbench\r\nEnd Sub\r\n"),
        package_id="fleet-spa",
    )
    fta = _component(
        "fleet-fta.probe",
        "standard_module",
        "FtaProbe",
        _source("Public Sub Probe()\r\n    Call AnnotationSet\r\nEnd Sub\r\n"),
        package_id="fleet-fta",
    )
    packages = (
        _package("core", "CORE_CANDIDATE"),
        _package("fleet-spa", "FLEET_EXTENSION_SPA"),
        _package("fleet-fta", "FLEET_EXTENSION_FTA"),
    )

    report = validate_catalog(_catalog((fta, spa), packages=packages))

    assert report.ok


def test_public_standard_module_udt_cannot_cross_a_public_class_signature() -> None:
    standard = _component(
        "core.contract",
        "standard_module",
        "Contract",
        _source(
            "Public Type MM_Result\r\n"
            "    Value As Long\r\n"
            "End Type\r\n"
        ),
    )
    class_module = _component(
        "core.gateway",
        "class_module",
        "Gateway",
        _source(
            "Public Function ReadResult(ByVal seed As Long) As MM_Result\r\n"
            "End Function\r\n"
        ),
    )

    report = validate_catalog(_catalog((class_module, standard)))

    assert [item.code for item in report.diagnostics] == ["PUBLIC_UDT_EXPOSED"]
    finding = report.diagnostics[0]
    assert finding.path == "catvba_refactor/vba/new/Gateway.cls"
    assert finding.details == {
        "declared_path": "catvba_refactor/vba/new/Contract.bas",
        "line": 3,
        "token": "MM_Result",
    }


def test_binary_frx_is_never_decoded_or_lexically_scanned() -> None:
    frm = _member(
        "catvba_refactor/vba/new/Menu.frm",
        'VERSION 5.00\r\nAttribute VB_Name = "Menu"\r\nOption Explicit\r\n',
        role="frm",
    )
    binary = SourceMember(
        path="catvba_refactor/vba/new/Menu.frx",
        blob_oid="a" * 40,
        raw_sha256=hashlib.sha256(b"\xff\x00VBProject").hexdigest(),
        role="frx",
        data=b"\xff\x00VBProject",
    )
    form = Component(
        source_id="core.menu",
        origin=Origin.NEW,
        component_type="user_form",
        vb_name="Menu",
        members=(frm, binary),
        package_id="core",
        disposition="candidate",
    )

    assert validate_catalog(_catalog((form,))).ok


def test_undecodable_source_fails_closed_with_stable_diagnostic() -> None:
    data = b"\x81"
    member = SourceMember(
        path="catvba_refactor/vba/new/Broken.bas",
        blob_oid="b" * 40,
        raw_sha256=hashlib.sha256(data).hexdigest(),
        role="source",
        data=data,
    )
    component = Component(
        source_id="core.broken",
        origin=Origin.NEW,
        component_type="standard_module",
        vb_name="Broken",
        members=(member,),
        package_id="core",
        disposition="candidate",
    )

    report = validate_catalog(_catalog((component,)))

    assert [item.code for item in report.diagnostics] == [
        "POLICY_SOURCE_ENCODING"
    ]
    assert report.diagnostics[0].details == {"line": 1, "token": "ENC_INVALID"}


def test_existing_diagnostics_are_preserved_and_all_findings_sort_stably() -> None:
    component = _component(
        "core.no-option",
        "standard_module",
        "NoOption",
        'Attribute VB_Name = "NoOption"\r\n',
    )
    existing = Diagnostic("Z_EXISTING", "z.json", "existing evidence")

    report = validate_catalog(
        _catalog((component,), diagnostics=(existing,))
    )

    assert [item.code for item in report.diagnostics] == [
        "OPTION_EXPLICIT_REQUIRED",
        "Z_EXISTING",
    ]
    assert report.diagnostics[1] is existing
