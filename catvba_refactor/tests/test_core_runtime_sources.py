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
}

MODULE_NAMES = {path.rsplit(".", 1)[0] for path in FIXED_SOURCES}


def _raw(name: str) -> bytes:
    return (SOURCE_ROOT / name).read_bytes()


def _text(name: str) -> str:
    return _raw(name).decode("cp936", errors="strict")


def test_fixed_core_source_set_exists_but_is_not_manifested_yet() -> None:
    assert {path.name for path in SOURCE_ROOT.iterdir() if path.suffix in {".bas", ".cls"}} == FIXED_SOURCES
    manifest = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert all(name not in serialized for name in MODULE_NAMES)


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
    }
    for name, signatures in checks.items():
        text = _text(name)
        for signature in signatures:
            start = text.index(signature)
            match = re.search(r"\r\nEnd (?:Sub|Function)\r\n", text[start:])
            assert match is not None
            body = text[start : start + match.end()]
            assert body.count("CleanExit:") == 1
