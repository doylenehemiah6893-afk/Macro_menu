from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERRIDE_ROOT = ROOT / "catvba_refactor" / "vba" / "overrides"
UPSTREAM_ROOT = ROOT / "Src"
FORM_NAME = "Cat_Macro_Menu_View"
EXPECTED_FRX_SHA256 = (
    "12529f95a32b090015bb4d7f623aa53545cfb3226048c86c47b8e92224e5942e"
)


def _raw(extension: str) -> bytes:
    return (OVERRIDE_ROOT / f"{FORM_NAME}.{extension}").read_bytes()


def _text() -> str:
    return _raw("frm").decode("cp936", errors="strict")


def test_override_preserves_exact_form_storage_bundle() -> None:
    frm = _raw("frm")
    frx = _raw("frx")
    upstream = (UPSTREAM_ROOT / f"{FORM_NAME}.frm").read_bytes()
    marker = b"Attribute VB_Exposed = False\n"
    storage_end = upstream.index(marker) + len(marker)
    expected_storage = upstream[:storage_end].replace(b"\n", b"\r\n")

    assert frm[: len(expected_storage)] == expected_storage
    assert hashlib.sha256(frx).hexdigest() == EXPECTED_FRX_SHA256
    assert frx == (UPSTREAM_ROOT / f"{FORM_NAME}.frx").read_bytes()
    assert b'OleObjectBlob   =   "Cat_Macro_Menu_View.frx":0000\r\n' in frm
    assert b"Attribute VB_PredeclaredId = True\r\n" in frm
    assert b"\n" not in frm.replace(b"\r\n", b"")
    assert _text().encode("cp936", errors="strict") == frm


def test_initialize_menu_consumes_seven_generated_descriptor_arrays() -> None:
    text = _text()
    signature = re.search(
        r"Public Function InitializeMenu\((.*?)\) As Boolean",
        text,
        re.DOTALL,
    )
    assert signature is not None
    parameters = signature.group(1)
    for name in (
        "toolIds",
        "captions",
        "tooltips",
        "groupIds",
        "groupCaptions",
        "controlNames",
        "pageNames",
    ):
        assert f"ByVal {name} As Variant" in parameters
    assert text.count("IsArray(") == 7
    assert "LBound(toolIds)" in text
    assert "UBound(toolIds)" in text
    for value in (
        "CStr(controlNames(index))",
        "CStr(captions(index))",
        "CStr(tooltips(index))",
        "CStr(pageNames(index))",
        "CStr(groupCaptions(index))",
        "CStr(groupIds(index))",
    ):
        assert value in text
    assert 'Controls.Add("Forms.MultiPage.1"' in text
    assert '"Forms.CommandButton.1", CStr(controlNames(index)), True' in text
    assert ".ControlTipText = CStr(tooltips(index))" in text
    assert "If Not ConfigureMenuPages() Then GoTo Fail" in text
    assert "Private Function ConfigureMenuPages() As Boolean" in text
    assert "ConfigureMenuPages = True" in text
    assert "If UBound(toolIds) - LBound(toolIds) + 1 > 256 Then GoTo CleanExit" in text


def test_descriptor_validation_rejects_empty_tooltip_and_failed_handler_binding() -> None:
    text = _text()
    descriptor_start = text.index("Private Function DescriptorIsComplete(")
    descriptor_end = text.index("End Function", descriptor_start)
    descriptor = text[descriptor_start:descriptor_end]
    assert "ByVal tooltip As String" in descriptor
    assert "And (Len(tooltip) > 0)" in descriptor
    assert "If Not handler.Initialize(button, CStr(toolIds(index))) Then GoTo Fail" in text
    assert text.index("If Not handler.Initialize(") < text.index("mHandlers.Add handler")


def test_override_reuses_pages_and_retains_canonical_tool_handlers() -> None:
    text = _text()
    assert "Private mHandlers As Collection" in text
    assert "Set mHandlers = New Collection" in text
    assert "Private mPageObjects As Collection" in text
    assert "FindOrCreatePage" in text
    assert "Set handler = New C_MMButtonHandler" in text
    assert "handler.Initialize(button, CStr(toolIds(index)))" in text
    assert "mHandlers.Add handler" in text
    assert "LCase$(" not in text
    assert "Replace(" not in text


def test_override_has_no_legacy_or_dynamic_project_dependencies() -> None:
    folded = _text().casefold()
    forbidden = (
        "cls_pdm",
        "pdm",
        "tomp",
        "kcl",
        "cls_allbtnevt",
        "a00_menu",
        "vbproject",
        "vbcomponents",
        "codemodule",
        "callbyname",
        "try_setproperty",
        "on error resume next",
    )
    assert all(token not in folded for token in forbidden)
    assert "on error goto fail" in folded
    assert "cleanexit:" in folded


def test_cleanup_retains_created_state_when_control_removal_fails() -> None:
    text = _text()
    clear_start = text.index("Private Function ClearMenu() As Boolean")
    clear_end = text.index("End Function", clear_start)
    clear = text[clear_start:clear_end]
    fail = clear[clear.index("Fail:") :]
    assert clear.index("Me.Controls.Remove MENU_CONTROL_NAME") < clear.index(
        "mMenuCreated = False"
    )
    assert "mMenuCreated = False" not in fail
    assert "ClearMenu = False" in fail
