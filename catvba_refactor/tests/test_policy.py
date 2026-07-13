from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.encoding import decode_vba
from catvba_refactor.macro_build.errors import SourceError
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


ROOT = Path(__file__).resolve().parents[2]
CORE_SOURCE_ROOT = ROOT / "catvba_refactor" / "vba" / "new"
CORE_OVERRIDE_ROOT = ROOT / "catvba_refactor" / "vba" / "overrides"


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
        encoding_decision=None,
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
    tools: tuple[dict[str, Any], ...] = (),
    diagnostics: tuple[Diagnostic, ...] = (),
) -> ResolvedCatalog:
    return ResolvedCatalog(
        snapshot=_snapshot(),
        components=components,
        packages=packages
        or (_package("core", "CORE_CANDIDATE"),),
        tools=tools,
        report=ValidationReport(diagnostics),
    )


def _source(body: str = "") -> str:
    return (
        'Attribute VB_Name = "SafeModule"\r\n'
        "Option Explicit\r\n"
        f"{body}"
    )


def _tool(
    tool_id: str = "core.safe",
    *,
    package_id: str = "core",
    module_name: str = "SafeModule",
    entrypoint: str = "Run",
) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "caption": "Safe",
        "group_id": "core.general",
        "package_id": package_id,
        "module_name": module_name,
        "entrypoint": entrypoint,
        "document_types": ["none"],
        "required_capabilities": [],
        "risk_level": "read-only",
    }


@pytest.mark.parametrize(
    ("declaration", "accepted"),
    [
        (
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult",
            True,
        ),
        ("Public Sub Run(ByVal context As C_MMContext)", False),
        ("Public Function Run() As C_MMResult", False),
        (
            "Public Function Run(ByRef context As C_MMContext) As C_MMResult",
            False,
        ),
        ("Public Function Run(ByVal context As Object) As C_MMResult", False),
        (
            "Public Function Run(ByVal context As C_MMContext, ByVal extra As Long) As C_MMResult",
            False,
        ),
        ("Public Function Run(ByVal context As C_MMContext) As Variant", False),
    ],
)
def test_tool_entrypoint_requires_the_exact_core_context_result_abi(
    declaration: str, accepted: bool
) -> None:
    component = _component(
        "core.safe",
        "standard_module",
        "SafeModule",
        _source(f"{declaration}\r\nEnd {'Function' if 'Function' in declaration else 'Sub'}\r\n"),
    )

    report = validate_catalog(_catalog((component,), tools=(_tool(),)))

    if accepted:
        assert report.ok
    else:
        assert [finding.code for finding in report.diagnostics] == [
            "TOOL_ENTRYPOINT_BINDING_INVALID"
        ]
        assert report.diagnostics[0].path == "tools.json#/tools/0/entrypoint"


@pytest.mark.parametrize(
    ("source_id", "module_name", "entrypoint"),
    [
        ("core.healthcheck", "MM_HealthCheck", "RunHealthCheck"),
        ("core.document-summary", "MM_DocumentSummary", "RunDocumentSummary"),
    ],
)
def test_first_core_tool_sources_pass_policy_with_exact_abi(
    source_id: str, module_name: str, entrypoint: str
) -> None:
    text = (CORE_SOURCE_ROOT / f"{module_name}.bas").read_bytes().decode(
        "cp936", errors="strict"
    )
    component = _component(source_id, "standard_module", module_name, text)
    tool = _tool(
        source_id,
        module_name=module_name,
        entrypoint=entrypoint,
    )

    assert validate_catalog(_catalog((component,), tools=(tool,))).ok


def test_core_form_override_passes_core_policy_without_legacy_bindings() -> None:
    text = (CORE_OVERRIDE_ROOT / "Cat_Macro_Menu_View.frm").read_bytes().decode(
        "cp936", errors="strict"
    )
    component = _component(
        "core.menu-form",
        "user_form",
        "Cat_Macro_Menu_View",
        text,
    )

    assert validate_catalog(_catalog((component,))).ok


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
            "    Rem SystemService ExecuteScript VBProject\r\n"
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
        encoding_decision=None,
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
        encoding_decision=None,
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


def test_policy_accepts_inventory_decided_ambiguous_cp936_without_replacement() -> None:
    ambiguous_bytes = (
        b'Attribute VB_Name = "Ambiguous"\r\n'
        b"Option Explicit\r\n"
        b"Public Sub Run()\r\n"
        b'    Dim caption As String: caption = "\xc2\xa1"\r\n'
        b"End Sub\r\n"
    )
    assert decode_vba(ambiguous_bytes, "cp936").encoding == "cp936"
    with pytest.raises(SourceError, match="ENC_AMBIGUOUS"):
        decode_vba(ambiguous_bytes)
    member = SourceMember(
        path="catvba_refactor/vba/new/Ambiguous.bas",
        blob_oid="a" * 40,
        raw_sha256=hashlib.sha256(ambiguous_bytes).hexdigest(),
        role="source",
        data=ambiguous_bytes,
    )
    component = Component(
        source_id="core.ambiguous",
        origin=Origin.NEW,
        component_type="standard_module",
        vb_name="Ambiguous",
        members=(member,),
        package_id="core",
        disposition="candidate",
        encoding_decision="cp936",
    )

    assert validate_catalog(_catalog((component,))).ok


def test_policy_rejects_ambiguous_source_without_encoding_decision() -> None:
    data = (
        b'Attribute VB_Name = "AmbiguousDenied"\r\n'
        b"Option Explicit\r\n"
        b"Public Sub Run()\r\n"
        b'    Dim caption As String: caption = "\xc2\xa1"\r\n'
        b"    Call VBProject\r\n"
        b"End Sub\r\n"
    )
    member = SourceMember(
        path="catvba_refactor/vba/new/AmbiguousDenied.bas",
        blob_oid="b" * 40,
        raw_sha256=hashlib.sha256(data).hexdigest(),
        role="source",
        data=data,
    )
    component = Component(
        source_id="core.ambiguous-denied",
        origin=Origin.NEW,
        component_type="standard_module",
        vb_name="AmbiguousDenied",
        members=(member,),
        package_id="core",
        disposition="candidate",
        encoding_decision=None,
    )

    report = validate_catalog(_catalog((component,)))

    assert [(item.code, item.details) for item in report.diagnostics] == [
        ("POLICY_SOURCE_ENCODING", {"line": 1, "token": "ENC_AMBIGUOUS"})
    ]


@pytest.mark.parametrize(
    "body",
    [
        "Public Sub Run(): Option Explicit: End Sub\r\n",
        "Public Sub Run()\r\n    Option Explicit\r\nEnd Sub\r\n",
        "Public Sub Run(): End Sub: Option Explicit\r\n",
    ],
)
def test_option_explicit_inside_or_after_a_procedure_does_not_satisfy_policy(
    body: str,
) -> None:
    component = _component(
        "core.misplaced-option",
        "standard_module",
        "MisplacedOption",
        'Attribute VB_Name = "MisplacedOption"\r\n' + body,
    )

    report = validate_catalog(_catalog((component,)))

    assert [item.code for item in report.diagnostics] == [
        "OPTION_EXPLICIT_REQUIRED"
    ]


def test_module_level_option_before_colon_delimited_procedure_is_accepted() -> None:
    component = _component(
        "core.colon-option",
        "standard_module",
        "ColonOption",
        'Attribute VB_Name = "ColonOption"\r\n'
        "Option Explicit: Public Sub Run(): End Sub\r\n",
    )

    assert validate_catalog(_catalog((component,))).ok


def test_every_colon_delimited_declare_requires_adjacent_ptrsafe_grammar() -> None:
    component = _component(
        "core.declares",
        "standard_module",
        "Declares",
        'Attribute VB_Name = "Declares"\r\n'
        "Option Explicit\r\n"
        'Private Declare Function UnsafeA Lib "x" () As Long: '
        'Private Declare PtrSafe Function SafeA Lib "x" () As Long\r\n'
        'Private Declare Function UnsafeB Lib "x" () As Long PtrSafe\r\n',
    )

    report = validate_catalog(_catalog((component,)))

    assert [(item.code, item.details) for item in report.diagnostics] == [
        ("DECLARE_PTRSAFE_REQUIRED", {"line": 3, "token": "Declare"}),
        ("DECLARE_PTRSAFE_REQUIRED", {"line": 4, "token": "Declare"}),
    ]


def test_declare_on_own_line_inside_procedure_is_still_checked() -> None:
    component = _component(
        "core.procedure-declare",
        "standard_module",
        "ProcedureDeclare",
        'Attribute VB_Name = "ProcedureDeclare"\r\n'
        "Option Explicit\r\n"
        "Public Sub Run()\r\n"
        'Private Declare Sub Unsafe Lib "x" ()\r\n'
        "End Sub\r\n",
    )

    report = validate_catalog(_catalog((component,)))

    assert [(item.code, item.details) for item in report.diagnostics] == [
        ("DECLARE_PTRSAFE_REQUIRED", {"line": 4, "token": "Declare"})
    ]


def test_later_declare_token_cannot_hide_behind_a_safe_declare_prefix() -> None:
    component = _component(
        "core.double-declare",
        "standard_module",
        "DoubleDeclare",
        'Attribute VB_Name = "DoubleDeclare"\r\n'
        "Option Explicit\r\n"
        'Private Declare PtrSafe Function SafeOne Lib "x" () As Long '
        'Declare Function UnsafeTwo Lib "x" () As Long\r\n',
    )

    report = validate_catalog(_catalog((component,)))

    assert [item.code for item in report.diagnostics] == [
        "DECLARE_PTRSAFE_REQUIRED"
    ]


@pytest.mark.parametrize(
    "packages",
    [
        (
            _package("core", "CORE_CANDIDATE"),
            _package("core", "FLEET_EXTENSION_SPA"),
        ),
        (
            _package("core", "FLEET_EXTENSION_SPA"),
            _package("core", "CORE_CANDIDATE"),
        ),
    ],
)
def test_duplicate_package_ids_are_ambiguous_and_cannot_weaken_core_policy(
    packages: tuple[dict[str, Any], ...],
) -> None:
    component = _component(
        "core.duplicate-package",
        "standard_module",
        "DuplicatePackage",
        _source("Public Sub Run()\r\n    Call VBProject\r\nEnd Sub\r\n"),
    )

    report = validate_catalog(_catalog((component,), packages=packages))

    assert [item.code for item in report.diagnostics] == [
        "CORE_TOKEN_DENIED",
        "DUPLICATE_PACKAGE_ID",
        "PACKAGE_BINDING_INVALID",
    ]


def test_system_service_execute_script_self_call_is_code_owned_core_deny() -> None:
    component = _component(
        "core.self-call",
        "standard_module",
        "SelfCall",
        _source(
            "Public Sub Run()\r\n"
            "    Call Application.SystemService.ExecuteScript()\r\n"
            "End Sub\r\n"
        ),
    )
    packages = (
        _package(
            "core",
            "CORE_CANDIDATE",
            reference_allowlist=["SystemService", "ExecuteScript"],
        ),
    )

    report = validate_catalog(_catalog((component,), packages=packages))

    assert [(item.code, item.details["token"]) for item in report.diagnostics] == [
        ("CORE_TOKEN_DENIED", "ExecuteScript"),
        ("CORE_TOKEN_DENIED", "SystemService"),
    ]


@pytest.mark.parametrize("token", ["SystemService", "ExecuteScript"])
def test_generated_dispatch_cannot_make_runtime_location_tokens_safe(
    token: str,
) -> None:
    component = _component(
        "core.dispatch-location",
        "standard_module",
        "DispatchLocation",
        _source(
            "Public Function Core_Invoke(ByVal request As Variant) As Variant\r\n"
            f"    Call {token}\r\n"
            "End Function\r\n"
        ),
    )

    report = validate_catalog(_catalog((component,)))

    assert [(item.code, item.details["token"]) for item in report.diagnostics] == [
        ("CORE_TOKEN_DENIED", token)
    ]


def test_udt_name_used_only_as_parameter_name_is_not_a_type_exposure() -> None:
    standard = _component(
        "core.contract-name",
        "standard_module",
        "ContractName",
        _source("Public Type MM_Result\r\nValue As Long\r\nEnd Type\r\n"),
    )
    class_module = _component(
        "core.gateway-name",
        "class_module",
        "GatewayName",
        _source(
            "Public Function ReadResult(ByVal MM_Result As Long) As Long\r\n"
            "End Function\r\n"
        ),
    )

    assert validate_catalog(_catalog((standard, class_module))).ok


def test_public_event_signature_exposing_public_udt_is_diagnosed() -> None:
    standard = _component(
        "core.contract-event",
        "standard_module",
        "ContractEvent",
        _source("Public Type MM_Result\r\nValue As Long\r\nEnd Type\r\n"),
    )
    class_module = _component(
        "core.gateway-event",
        "class_module",
        "GatewayEvent",
        _source("Public Event Completed(ByVal result As MM_Result)\r\n"),
    )

    report = validate_catalog(_catalog((standard, class_module)))

    assert [(item.code, item.details) for item in report.diagnostics] == [
        (
            "PUBLIC_UDT_EXPOSED",
            {
                "declared_path": "catvba_refactor/vba/new/ContractEvent.bas",
                "line": 3,
                "token": "MM_Result",
            },
        )
    ]


def test_public_property_signature_exposing_public_udt_is_diagnosed() -> None:
    standard = _component(
        "core.contract-property",
        "standard_module",
        "ContractProperty",
        _source("Public Type MM_Result\r\nValue As Long\r\nEnd Type\r\n"),
    )
    class_module = _component(
        "core.gateway-property",
        "class_module",
        "GatewayProperty",
        _source(
            "Public Property Get Result() As MM_Result\r\n"
            "End Property\r\n"
        ),
    )

    report = validate_catalog(_catalog((standard, class_module)))

    assert [item.code for item in report.diagnostics] == ["PUBLIC_UDT_EXPOSED"]
    assert report.diagnostics[0].details["line"] == 3
    assert report.diagnostics[0].details["token"] == "MM_Result"


def test_valid_tool_binds_to_exact_public_standard_module_entrypoint() -> None:
    module = _component(
        "core.safe-module",
        "standard_module",
        "SafeModule",
        _source(
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
            "End Function\r\n"
        ),
    )

    assert validate_catalog(_catalog((module,), tools=(_tool(),))).ok


def test_valid_tool_binding_uses_vba_case_insensitive_abi_semantics() -> None:
    module = _component(
        "core.safe-function",
        "standard_module",
        "SafeModule",
        _source(
            "public function run(byval CONTEXT as c_mmcontext) as c_mmresult\r\n"
            "end function\r\n"
        ),
    )

    assert validate_catalog(_catalog((module,), tools=(_tool(),))).ok


@pytest.mark.parametrize(
    "body",
    [
        (
            "Public Sub Outer()\r\n"
            "Public Sub Nested()\r\n"
            "End Sub\r\n"
            "Public Sub Run()\r\n"
            "End Sub\r\n"
            "End Sub\r\n"
        ),
        (
            "Public Sub Outer(): Public Function Nested() As Variant: "
            "End Function: Public Sub Run(): End Sub: End Sub\r\n"
        ),
    ],
)
def test_tool_entrypoint_nested_inside_a_procedure_is_not_module_scope(
    body: str,
) -> None:
    module = _component(
        "core.nested-entrypoint",
        "standard_module",
        "SafeModule",
        _source(body),
    )

    report = validate_catalog(_catalog((module,), tools=(_tool(),)))

    assert [item.code for item in report.diagnostics] == [
        "TOOL_ENTRYPOINT_BINDING_INVALID"
    ]


@pytest.mark.parametrize(
    "body",
    [
        (
            "Private Sub Broken()\r\n"
            "End Function\r\n"
            "Public Sub Run()\r\n"
            "End Sub\r\n"
        ),
        (
            "Private Function Broken() As Boolean\r\n"
            "End Property\r\n"
            "Public Function Run() As Variant\r\n"
            "End Function\r\n"
        ),
        (
            "Private Property Get Broken() As Long\r\n"
            "End Sub\r\n"
            "Public Sub Run()\r\n"
            "End Sub\r\n"
        ),
        (
            "End Sub\r\n"
            "Public Sub Run()\r\n"
            "End Sub\r\n"
        ),
        "Public Sub Run()\r\n",
        (
            "Public Sub Run()\r\n"
            "End Sub\r\n"
            "Private Function Dangling() As Boolean\r\n"
        ),
    ],
    ids=[
        "sub-closed-by-function",
        "function-closed-by-property",
        "property-closed-by-sub",
        "stray-end-before-entrypoint",
        "unclosed-entrypoint",
        "unclosed-trailing-procedure",
    ],
)
def test_tool_entrypoint_scope_parser_fails_closed_for_malformed_procedures(
    body: str,
) -> None:
    module = _component(
        "core.malformed-procedure-scope",
        "standard_module",
        "SafeModule",
        _source(body),
    )

    report = validate_catalog(_catalog((module,), tools=(_tool(),)))

    assert [item.code for item in report.diagnostics] == [
        "TOOL_ENTRYPOINT_BINDING_INVALID"
    ]


@pytest.mark.parametrize(
    "body",
    [
        (
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
            "End Function\r\n"
        ),
        (
            "Private Function Prepare() As Boolean\r\n"
            "End Function\r\n"
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
            "End Function\r\n"
        ),
        (
            "Private Property Get Ready() As Boolean\r\n"
            "End Property\r\n"
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
            "End Function\r\n"
        ),
        (
            "Private Sub Prepare(): End Sub: "
            "Private Function IsReady() As Boolean: End Function: "
            "Private Property Get Ready() As Boolean: End Property: "
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult: End Function\r\n"
        ),
    ],
)
def test_tool_entrypoint_module_scope_declarations_are_accepted(
    body: str,
) -> None:
    module = _component(
        "core.module-entrypoint",
        "standard_module",
        "SafeModule",
        _source(body),
    )

    assert validate_catalog(_catalog((module,), tools=(_tool(),))).ok


@pytest.mark.parametrize(
    ("tools", "expected_code", "expected_path"),
    [
        (
            ({"tool_id": "core.malformed"},),
            "TOOL_RECORD_INVALID",
            "tools.json#/tools/0",
        ),
        (
            (_tool("Core Invalid"),),
            "TOOL_ID_INVALID",
            "tools.json#/tools/0/tool_id",
        ),
        (
            (_tool(), _tool()),
            "DUPLICATE_TOOL_ID",
            "tools.json#/tools/1/tool_id",
        ),
        (
            (_tool(package_id="missing"),),
            "TOOL_PACKAGE_BINDING_INVALID",
            "tools.json#/tools/0/package_id",
        ),
    ],
)
def test_tool_records_fail_closed_with_stable_pointer_diagnostics(
    tools: tuple[dict[str, Any], ...],
    expected_code: str,
    expected_path: str,
) -> None:
    module = _component(
        "core.safe-module",
        "standard_module",
        "SafeModule",
        _source(
            "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
            "End Function\r\n"
        ),
    )

    report = validate_catalog(_catalog((module,), tools=tools))

    finding = next(item for item in report.diagnostics if item.code == expected_code)
    assert finding.path == expected_path
    assert finding.details["line"] >= 1
    assert finding.details["token"]


@pytest.mark.parametrize(
    ("components", "tool", "expected_code"),
    [
        (
            (),
            _tool(module_name="Missing"),
            "TOOL_MODULE_BINDING_INVALID",
        ),
        (
            (
                _component(
                    "core.class",
                    "class_module",
                    "SafeModule",
                    _source("Public Sub Run()\r\nEnd Sub\r\n"),
                ),
            ),
            _tool(),
            "TOOL_MODULE_BINDING_INVALID",
        ),
        (
            (
                _component(
                    "core.module-one",
                    "standard_module",
                    "SafeModule",
                    _source("Public Sub Run()\r\nEnd Sub\r\n"),
                ),
                _component(
                    "core.module-two",
                    "standard_module",
                    "SafeModule",
                    _source("Public Sub Run()\r\nEnd Sub\r\n"),
                ),
            ),
            _tool(),
            "TOOL_MODULE_BINDING_INVALID",
        ),
        (
            (
                _component(
                    "core.private",
                    "standard_module",
                    "SafeModule",
                    _source("Private Sub Run()\r\nEnd Sub\r\n"),
                ),
            ),
            _tool(),
            "TOOL_ENTRYPOINT_BINDING_INVALID",
        ),
        (
            (
                _component(
                    "core.duplicate-entry",
                    "standard_module",
                    "SafeModule",
                    _source(
                        "Public Sub Run()\r\nEnd Sub\r\n"
                        "Public Function Run() As Variant\r\nEnd Function\r\n"
                    ),
                ),
            ),
            _tool(),
            "TOOL_ENTRYPOINT_BINDING_INVALID",
        ),
    ],
)
def test_tool_module_and_entrypoint_binding_is_exact_and_unambiguous(
    components: tuple[Component, ...],
    tool: dict[str, Any],
    expected_code: str,
) -> None:
    report = validate_catalog(_catalog(components, tools=(tool,)))

    finding = next(item for item in report.diagnostics if item.code == expected_code)
    assert finding.path.startswith("tools.json#/tools/0/")
    assert finding.details["line"] >= 1
    assert finding.details["token"]
