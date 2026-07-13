Attribute VB_Name = "MM_MenuPresenter"
Option Explicit

Public Sub ShowCoreMenu()
    On Error GoTo Fail
    If Not Cat_Macro_Menu_View.InitializeMenu( _
        MM_MenuCatalog.MM_ToolIds(), _
        MM_MenuCatalog.MM_ToolCaptions(), _
        MM_MenuCatalog.MM_ToolTooltips(), _
        MM_MenuCatalog.MM_ToolGroupIds(), _
        MM_MenuCatalog.MM_ToolGroupCaptions(), _
        MM_MenuCatalog.MM_ToolControlNames(), _
        MM_MenuCatalog.MM_ToolPageNames()) Then GoTo CleanExit
    Cat_Macro_Menu_View.Show vbModeless
CleanExit:
    Exit Sub
Fail:
    Resume CleanExit
End Sub

Public Sub InvokeTool(ByVal toolId As String)
    Dim request As Variant
    Dim requestId As String
    Dim response As Variant
    On Error GoTo Fail
    requestId = "ui-" & CStr(CLng(Timer * 1000#))
    request = Array("MM/1", requestId, toolId, MM_BuildInfo.MM_TOOL_VERSION, Empty)
    response = MM_Dispatch.Core_Invoke(request)
    If IsArray(response) Then
        If Len(CStr(response(4))) > 0 Then MsgBox CStr(response(4)), vbInformation, "Macro Menu"
    End If
CleanExit:
    Exit Sub
Fail:
    Resume CleanExit
End Sub
