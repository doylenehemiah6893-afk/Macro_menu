from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "catvba_refactor" / "vba" / "new"
COMPONENTS_PATH = ROOT / "catvba_refactor" / "config" / "components.json"

FIXED_SOURCES = {
    "MM_Entry.bas",
    "MM_MenuPresenter.bas",
    "MM_Protocol.bas",
    "MM_Error.bas",
    "MM_Log.bas",
    "MM_TryGet.bas",
    "C_MMButtonHandler.cls",
    "C_MMContext.cls",
    "C_MMResult.cls",
    "C_MMStateGuard.cls",
    "MM_HealthCheck.bas",
    "MM_DocumentSummary.bas",
}

def _raw(name: str) -> bytes:
    return (SOURCE_ROOT / name).read_bytes()


def _text(name: str) -> str:
    return _raw(name).decode("cp936", errors="strict")


def test_fixed_core_source_set_is_exactly_bound_as_core_candidates() -> None:
    assert {
        path.name
        for path in SOURCE_ROOT.iterdir()
        if path.suffix in {".bas", ".cls"}
    } == FIXED_SOURCES
    manifest = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
    components = manifest["components"]
    fixed_components = [
        component
        for component in components
        if component["origin"] == "new"
        and component["disposition"] == "candidate"
    ]
    assert {
        (
            component["members"][0]["path"],
            component["members"][0]["role"],
            component["vb_name"],
        )
        for component in fixed_components
    } == {
        (f"catvba_refactor/vba/new/{name}", "source", name.rsplit(".", 1)[0])
        for name in FIXED_SOURCES
    }
    assert all(
        component["package_id"] == "core"
        and len(component["members"]) == 1
        for component in fixed_components
    )
    assert {
        (component["origin"], component["package_id"])
        for component in components
        if component["disposition"] == "candidate"
    } == {("new", "core"), ("override", "core")}


@pytest.mark.parametrize("name", sorted(FIXED_SOURCES))
def test_fixed_sources_are_exact_cp936_crlf_with_one_identity(name: str) -> None:
    raw = _raw(name)
    text = raw.decode("cp936", errors="strict")
    assert text.encode("cp936", errors="strict") == raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert b"\r\n" in raw
    module_name = name.rsplit(".", 1)[0]
    assert re.findall(
        r'^Attribute VB_Name = "([A-Za-z0-9_]+)"\r?$', text, re.MULTILINE
    ) == [module_name]
    assert len(re.findall(r"^Option Explicit\r?$", text, re.MULTILINE)) == 1


def test_generated_dispatch_frozen_protocol_api_is_implemented_once() -> None:
    protocol = _text("MM_Protocol.bas")
    errors = _text("MM_Error.bas")
    assert protocol.count(
        "Public Function TryParseRequest(ByVal request As Variant, ByRef requestId As String, ByRef commandId As String, ByRef context As C_MMContext, ByRef result As C_MMResult) As Boolean"
    ) == 1
    assert protocol.count(
        "Public Function BuildResponse(ByVal requestId As String, ByVal result As C_MMResult) As Variant"
    ) == 1
    assert errors.count(
        "Public Function UnknownCommand(ByVal commandId As String) As C_MMResult"
    ) == 1
    assert errors.count(
        "Public Function InternalError(ByVal errorNumber As Long) As C_MMResult"
    ) == 1
    for name in FIXED_SOURCES - {"MM_Protocol.bas"}:
        assert "BuildResponse(" not in _text(name)


def test_protocol_has_exact_shape_limits_types_and_recursive_validation() -> None:
    text = _text("MM_Protocol.bas")
    for declaration in (
        'Private Const PROTOCOL_VERSION As String = "MM/1"',
        "Private Const REQUEST_FIELD_COUNT As Long = 5",
        "Private Const RESPONSE_FIELD_COUNT As Long = 7",
        "Private Const MAX_DEPTH As Long = 8",
        "Private Const MAX_STRING_LENGTH As Long = 4096",
        "Private Const MAX_ARRAY_LENGTH As Long = 256",
        "Private Const MAX_TOTAL_NODES As Long = 2048",
        "Private Const MAX_DISPLAY_LINES As Long = 500",
    ):
        assert declaration in text
    for token in (
        "vbEmpty",
        "vbBoolean",
        "vbLong",
        "vbDouble",
        "vbString",
        "vbArray + vbVariant",
        "ValidateValue(value(index), depth + 1, nodeCount)",
        "ValidateKeyValueArray",
        "StrComp(previousKey, key, vbBinaryCompare)",
    ):
        assert token in text
    assert "Array(PROTOCOL_VERSION, requestId, result.Status, result.Code, result.DisplayMessage, result.Data, result.Meta)" in text


def test_error_codes_and_result_boundary_are_fixed() -> None:
    errors = _text("MM_Error.bas")
    for code, label in (
        (0, "OK"),
        (10, "CANCELLED"),
        (20, "NOT_APPLICABLE"),
        (30, "CAPABILITY_UNAVAILABLE"),
        (40, "VALIDATION_FAILED"),
        (50, "STATE_CHANGED"),
        (60, "TOOL_FAILED"),
        (70, "INTERNAL_ERROR"),
        (80, "LIMIT_REACHED"),
        (90, "UNKNOWN_COMMAND"),
    ):
        assert f'Case {code}: StatusForCode = "{label}"' in errors
    result = _text("C_MMResult.cls")
    assert "Private mData As Variant" in result
    assert "Private mMeta As Variant" in result
    assert "If Not MM_Protocol.IsTransportValue(data) Then GoTo InvalidValue" in result
    assert "If Not MM_Protocol.IsMetaValue(meta) Then GoTo InvalidValue" in result
    assert "If Not MM_Error.IsKnownCodeAndStatus(code, status) Then GoTo InvalidValue" in result
    assert "Set mData" not in result
    assert "Set mMeta" not in result
    assert "Set Data" not in result
    assert "Set Meta" not in result
    assert "Public Property Get Data() As Variant" in result
    assert "Public Property Get Meta() As Variant" in result
    protocol = _text("MM_Protocol.bas")
    assert "If Not MM_Error.IsKnownCodeAndStatus(result.Code, result.Status) Then GoTo InvalidResult" in protocol
    assert "Public Function IsTransportValue(ByVal value As Variant) As Boolean" in protocol
    assert "Public Function IsMetaValue(ByVal value As Variant) As Boolean" in protocol


def test_framework_uses_late_bound_per_call_context_and_state_tracking() -> None:
    context = _text("C_MMContext.cls")
    guard = _text("C_MMStateGuard.cls")
    assert "Private mApplication As Object" in context
    assert "Private mActiveDocument As Object" in context
    assert "Private mActiveWindow As Object" in context
    assert "Private mSelection As Object" in context
    assert "As New" not in context
    assert "Static " not in context
    for token in (
        "mCapturedDocument",
        "mCapturedWindow",
        "mCapturedSelectionCount",
        "mDisplayFileAlertsChanged",
        "mRefreshDisplayChanged",
        "originalErrorNumber",
        "restoreDiagnostics",
    ):
        assert token in guard


def test_state_restore_isolates_every_action_and_preserves_caller_error() -> None:
    guard = _text("C_MMStateGuard.cls")
    restore_start = guard.index("Public Sub Restore(")
    restore_end = guard.index("End Sub", restore_start)
    restore = guard[restore_start:restore_end]
    assert "ByRef originalErrorNumber As Long" in restore
    assert "ByRef originalErrorDescription As String" in restore
    calls = (
        "RestoreDisplayFileAlerts context, restoreDiagnostics",
        "RestoreRefreshDisplay context, restoreDiagnostics",
        "CheckActiveDocument context, restoreDiagnostics",
        "CheckActiveWindow context, restoreDiagnostics",
        "CheckSelection context, restoreDiagnostics",
    )
    positions = [restore.index(call) for call in calls]
    assert positions == sorted(positions)
    assert "preservedErrorNumber = originalErrorNumber" in restore
    assert "preservedErrorDescription = originalErrorDescription" in restore
    assert "originalErrorNumber = preservedErrorNumber" in restore
    assert "originalErrorDescription = preservedErrorDescription" in restore
    for helper in (
        "RestoreDisplayFileAlerts",
        "RestoreRefreshDisplay",
        "CheckActiveDocument",
        "CheckActiveWindow",
        "CheckSelection",
    ):
        start = guard.index(f"Private Sub {helper}(")
        end = guard.index("End Sub", start)
        body = guard[start:end]
        assert "On Error GoTo Failed" in body
        assert "Failed:" in body
        assert "AppendDiagnostic" in body
        assert "Err.Clear" in body
        assert "Resume CleanExit" in body
    assert "Err.Description" not in guard


def test_display_line_normalization_includes_unicode_separators() -> None:
    protocol = _text("MM_Protocol.bas")
    assert "ChrW(&H2028)" in protocol
    assert "ChrW(&H2029)" in protocol


def test_entry_presenter_and_button_handler_keep_dispatch_narrow() -> None:
    entry = _text("MM_Entry.bas")
    presenter = _text("MM_MenuPresenter.bas")
    handler = _text("C_MMButtonHandler.cls")
    assert "Public Sub CATMain()" in entry
    assert "MM_MenuPresenter.ShowCoreMenu" in entry
    assert "MM_Dispatch.Core_Invoke(request)" in presenter
    assert "Private mToolId As String" in handler
    assert "MM_MenuPresenter.InvokeTool mToolId" in handler
    assert "moduleName" not in handler
    assert "procedureName" not in handler
    assert "Public Function Initialize(" in handler
    assert ") As Boolean" in handler
    assert "Initialize = True" in handler
    assert "Initialize = False" in handler
    assert "mToolId = toolId" in handler
    assert "LCase$(" not in handler


def test_presenter_initializes_form_from_all_generated_catalog_arrays() -> None:
    presenter = _text("MM_MenuPresenter.bas")
    initialize = "Cat_Macro_Menu_View.InitializeMenu("
    show = "Cat_Macro_Menu_View.Show vbModeless"
    assert presenter.count(initialize) == 1
    assert presenter.index(initialize) < presenter.index(show)
    for function_name in (
        "MM_ToolIds",
        "MM_ToolCaptions",
        "MM_ToolTooltips",
        "MM_ToolGroupIds",
        "MM_ToolGroupCaptions",
        "MM_ToolControlNames",
        "MM_ToolPageNames",
    ):
        assert f"MM_MenuCatalog.{function_name}()" in presenter


def test_logging_is_scalar_redacted_and_production_sink_is_disabled() -> None:
    text = _text("MM_Log.bas")
    assert "Private Const PRODUCTION_SINK_ENABLED As Boolean = False" in text
    assert "On Error GoTo LogFail" in text
    for field in (
        "utcTimestamp As String",
        "buildId As String",
        "requestId As String",
        "toolId As String",
        "resultCode As Long",
        "durationMilliseconds As Long",
        "itemCount As Long",
        "documentType As String",
    ):
        assert field in text


def test_forbidden_runtime_constructs_and_response_values_are_absent() -> None:
    forbidden = (
        "vbproject",
        "vbcomponents",
        "codemodule",
        "executescript",
        "callbyname",
        "createobject",
        "getobject",
        "dictionary",
        "collection",
        "shell",
        "powershell",
        "wsh",
        "xmlhttp",
        "winhttp",
        "office",
        "excel",
        "spaworkbench",
        "annotationset",
        "cls_pdm",
        "kcl",
    )
    for name in FIXED_SOURCES:
        folded = _text(name).casefold()
        assert all(token not in folded for token in forbidden), name
        if name != "MM_TryGet.bas":
            assert "on error resume next" not in folded
        assert not re.search(
            r"Public\s+Function\s+\w+\s*\([^\r\n]*\)\s+As\s+Object",
            _text(name),
            re.IGNORECASE,
        )


def test_public_runtime_entrypoints_have_one_clean_exit_path() -> None:
    checks = {
        "MM_Entry.bas": ("Public Sub CATMain()",),
        "MM_MenuPresenter.bas": (
            "Public Sub ShowCoreMenu()",
            "Public Sub InvokeTool(ByVal toolId As String)",
        ),
        "MM_Protocol.bas": (
            "Public Function TryParseRequest(",
            "Public Function BuildResponse(",
        ),
        "C_MMButtonHandler.cls": ("Private Sub mButton_Click()",),
        "MM_HealthCheck.bas": (
            "Public Function RunHealthCheck(ByVal context As C_MMContext) As C_MMResult",
        ),
        "MM_DocumentSummary.bas": (
            "Public Function RunDocumentSummary(ByVal context As C_MMContext) As C_MMResult",
        ),
    }
    for name, signatures in checks.items():
        text = _text(name)
        for signature in signatures:
            start = text.index(signature)
            match = re.search(r"\r\nEnd (?:Sub|Function)\r\n", text[start:])
            assert match is not None
            body = text[start : start + match.end()]
            assert body.count("CleanExit:") == 1


def _data_keys(name: str) -> list[str]:
    return re.findall(r'Array\("([a-z0-9_.]+)",', _text(name))


def test_healthcheck_reports_only_bounded_non_sensitive_core_facts() -> None:
    text = _text("MM_HealthCheck.bas")
    assert text.count(
        "Public Function RunHealthCheck(ByVal context As C_MMContext) As C_MMResult"
    ) == 1
    for token in (
        "MM_BuildInfo.MM_PROTOCOL_VERSION",
        "MM_BuildInfo.MM_MANIFEST_DIGEST",
        "MM_BuildInfo.MM_WORK_COMMIT",
        "MM_BuildInfo.MM_WORK_TREE",
        "MM_BuildInfo.MM_TOOL_VERSION",
        "#If VBA7 Then",
        "#If Win64 Then",
        "MM_TryGet.TryGetCATIARelease",
        '"core.status", "READY"',
        '"tool.id", "core.healthcheck"',
        "context.DocumentType",
    ):
        assert token in text
    keys = _data_keys("MM_HealthCheck.bas")
    assert keys == sorted(set(keys))
    assert keys == [
        "build.manifest_digest",
        "build.protocol_version",
        "build.tool_version",
        "build.work_commit",
        "build.work_tree",
        "catia.release.available",
        "catia.release.value",
        "compile.vba7",
        "compile.win64",
        "context.document_type",
        "core.status",
        "tool.id",
    ]
    forbidden = (
        "references",
        "license",
        "licensing",
        "profile",
        "spa",
        "fta",
        ".path",
        "username",
        ".name",
        "update",
        "save",
        "open",
        "selection.clear",
    )
    assert all(token not in text.casefold() for token in forbidden)


def test_document_summary_is_read_only_and_strictly_bounds_selection_count() -> None:
    text = _text("MM_DocumentSummary.bas")
    assert text.count(
        "Public Function RunDocumentSummary(ByVal context As C_MMContext) As C_MMResult"
    ) == 1
    for token in (
        "If Not context.HasActiveDocument Then",
        "MM_Error.ResultForCode(20",
        "MM_Error.ResultForCode(0",
        "MM_TryGet.TryGetDocumentSaved",
        "MM_TryGet.TryGetDocumentReadOnly",
        "MM_TryGet.TryGetSelectionCount",
        "Private Const MAX_SELECTION_COUNT As Long = 10000",
        "If selectionCount > MAX_SELECTION_COUNT Then",
    ):
        assert token in text
    keys = _data_keys("MM_DocumentSummary.bas")
    assert keys == sorted(set(keys))
    assert keys == [
        "context.document_type",
        "document.read_only.available",
        "document.read_only.value",
        "document.saved.available",
        "document.saved.value",
        "selection.count",
        "selection.count.available",
        "selection.count.cap",
        "selection.count.truncated",
    ]
    forbidden = (
        r"\.update\b",
        r"\.save(?:as)?\b",
        r"\.open\b",
        r"selection\s*\.\s*clear\b",
        r"document\s*\.\s*name\b",
        r"document\s*\.\s*path\b",
        r"\bfullname\b",
        r"\bpartnumber\b",
        r"\bmeasure\w*\b",
        r"\bworkbench\w*\b",
        r"\bknowledge\w*\b",
        r"\bformula\w*\b",
        r"\brelation\w*\b",
    )
    assert all(re.search(pattern, text, re.IGNORECASE) is None for pattern in forbidden)


@pytest.mark.parametrize(
    ("signature", "reset", "access"),
    [
        (
            "Public Function TryGetActiveDocument(ByVal applicationObject As Object, ByRef value As Object) As Boolean",
            "Set value = Nothing",
            "applicationObject.ActiveDocument",
        ),
        (
            "Public Function TryGetActiveWindow(ByVal applicationObject As Object, ByRef value As Object) As Boolean",
            "Set value = Nothing",
            "applicationObject.ActiveWindow",
        ),
        (
            "Public Function TryGetSelection(ByVal documentObject As Object, ByRef value As Object) As Boolean",
            "Set value = Nothing",
            "documentObject.Selection",
        ),
        (
            "Public Function TryGetSelectionCount(ByVal selectionObject As Object, ByRef value As Long) As Boolean",
            "value = 0",
            "selectionObject.Count2",
        ),
        (
            "Public Function TryGetDisplayFileAlerts(ByVal applicationObject As Object, ByRef value As Boolean) As Boolean",
            "value = False",
            "applicationObject.DisplayFileAlerts",
        ),
        (
            "Public Function TryGetRefreshDisplay(ByVal applicationObject As Object, ByRef value As Boolean) As Boolean",
            "value = False",
            "applicationObject.RefreshDisplay",
        ),
        (
            "Public Function TryGetCATIARelease(ByVal applicationObject As Object, ByRef value As String) As Boolean",
            "value = vbNullString",
            "applicationObject.SystemConfiguration.Release",
        ),
        (
            "Public Function TryGetDocumentSaved(ByVal documentObject As Object, ByRef value As Boolean) As Boolean",
            "value = False",
            "documentObject.Saved",
        ),
        (
            "Public Function TryGetDocumentReadOnly(ByVal documentObject As Object, ByRef value As Boolean) As Boolean",
            "value = False",
            "documentObject.ReadOnly",
        ),
    ],
)
def test_try_get_wrappers_reset_outputs_before_isolated_compatibility_reads(
    signature: str, reset: str, access: str
) -> None:
    text = _text("MM_TryGet.bas")
    start = text.index(signature)
    end = text.index("End Function", start)
    body = text[start:end]
    assert body.count(reset) == 1
    assert access in body
    assert body.count("On Error Resume Next") == 1
    assert body.index(reset) < body.index("On Error Resume Next") < body.index(access)
    assert body.index(access) < body.index("errorNumber = Err.Number") < body.index("Err.Clear")
    assert body.index("Err.Clear") < body.index("On Error GoTo 0")
