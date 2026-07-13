VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "C_MMStateGuard"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

Private mCapturedDocument As Object
Private mCapturedWindow As Object
Private mCapturedSelectionCount As Long
Private mSelectionCountAvailable As Boolean
Private mDisplayFileAlertsChanged As Boolean
Private mOriginalDisplayFileAlerts As Boolean
Private mRefreshDisplayChanged As Boolean
Private mOriginalRefreshDisplay As Boolean

Public Sub Capture(ByVal context As C_MMContext)
    On Error GoTo Fail
    Set mCapturedDocument = context.ActiveDocument
    Set mCapturedWindow = context.ActiveWindow
    If Not context.Selection Is Nothing Then
        mSelectionCountAvailable = MM_TryGet.TryGetSelectionCount(context.Selection, mCapturedSelectionCount)
    End If
CleanExit:
    Exit Sub
Fail:
    Resume CleanExit
End Sub

Public Function SetDisplayFileAlerts(ByVal context As C_MMContext, ByVal value As Boolean) As Boolean
    On Error GoTo Fail
    If Not mDisplayFileAlertsChanged Then
        If Not MM_TryGet.TryGetDisplayFileAlerts(context.ApplicationObject, mOriginalDisplayFileAlerts) Then GoTo CleanExit
    End If
    context.ApplicationObject.DisplayFileAlerts = value
    mDisplayFileAlertsChanged = True
    SetDisplayFileAlerts = True
CleanExit:
    Exit Function
Fail:
    SetDisplayFileAlerts = False
    Resume CleanExit
End Function

Public Function SetRefreshDisplay(ByVal context As C_MMContext, ByVal value As Boolean) As Boolean
    On Error GoTo Fail
    If Not mRefreshDisplayChanged Then
        If Not MM_TryGet.TryGetRefreshDisplay(context.ApplicationObject, mOriginalRefreshDisplay) Then GoTo CleanExit
    End If
    context.ApplicationObject.RefreshDisplay = value
    mRefreshDisplayChanged = True
    SetRefreshDisplay = True
CleanExit:
    Exit Function
Fail:
    SetRefreshDisplay = False
    Resume CleanExit
End Function

Public Sub Restore(ByVal context As C_MMContext, ByRef originalErrorNumber As Long, ByRef originalErrorDescription As String, ByRef restoreDiagnostics As String)
    Dim preservedErrorNumber As Long
    Dim preservedErrorDescription As String
    preservedErrorNumber = originalErrorNumber
    preservedErrorDescription = originalErrorDescription
    RestoreDisplayFileAlerts context, restoreDiagnostics
    RestoreRefreshDisplay context, restoreDiagnostics
    CheckActiveDocument context, restoreDiagnostics
    CheckActiveWindow context, restoreDiagnostics
    CheckSelection context, restoreDiagnostics
CleanExit:
    originalErrorNumber = preservedErrorNumber
    originalErrorDescription = preservedErrorDescription
    Exit Sub
End Sub

Private Sub RestoreDisplayFileAlerts(ByVal context As C_MMContext, ByRef restoreDiagnostics As String)
    On Error GoTo Failed
    If mDisplayFileAlertsChanged Then context.ApplicationObject.DisplayFileAlerts = mOriginalDisplayFileAlerts
CleanExit:
    Exit Sub
Failed:
    AppendDiagnostic restoreDiagnostics, "display_file_alerts_restore_failed"
    Err.Clear
    Resume CleanExit
End Sub

Private Sub RestoreRefreshDisplay(ByVal context As C_MMContext, ByRef restoreDiagnostics As String)
    On Error GoTo Failed
    If mRefreshDisplayChanged Then context.ApplicationObject.RefreshDisplay = mOriginalRefreshDisplay
CleanExit:
    Exit Sub
Failed:
    AppendDiagnostic restoreDiagnostics, "refresh_display_restore_failed"
    Err.Clear
    Resume CleanExit
End Sub

Private Sub CheckActiveDocument(ByVal context As C_MMContext, ByRef restoreDiagnostics As String)
    Dim currentDocument As Object
    On Error GoTo Failed
    If MM_TryGet.TryGetActiveDocument(context.ApplicationObject, currentDocument) Then
        If Not currentDocument Is mCapturedDocument Then AppendDiagnostic restoreDiagnostics, "active_document_changed"
    ElseIf Not mCapturedDocument Is Nothing Then
        AppendDiagnostic restoreDiagnostics, "active_document_unavailable"
    End If
CleanExit:
    Exit Sub
Failed:
    AppendDiagnostic restoreDiagnostics, "active_document_check_failed"
    Err.Clear
    Resume CleanExit
End Sub

Private Sub CheckActiveWindow(ByVal context As C_MMContext, ByRef restoreDiagnostics As String)
    Dim currentWindow As Object
    On Error GoTo Failed
    If MM_TryGet.TryGetActiveWindow(context.ApplicationObject, currentWindow) Then
        If Not currentWindow Is mCapturedWindow Then AppendDiagnostic restoreDiagnostics, "active_window_changed"
    ElseIf Not mCapturedWindow Is Nothing Then
        AppendDiagnostic restoreDiagnostics, "active_window_unavailable"
    End If
CleanExit:
    Exit Sub
Failed:
    AppendDiagnostic restoreDiagnostics, "active_window_check_failed"
    Err.Clear
    Resume CleanExit
End Sub

Private Sub CheckSelection(ByVal context As C_MMContext, ByRef restoreDiagnostics As String)
    Dim currentSelectionCount As Long
    On Error GoTo Failed
    If mSelectionCountAvailable And Not context.Selection Is Nothing Then
        If MM_TryGet.TryGetSelectionCount(context.Selection, currentSelectionCount) Then
            If currentSelectionCount <> mCapturedSelectionCount Then AppendDiagnostic restoreDiagnostics, "selection_count_changed"
        End If
    End If
CleanExit:
    Exit Sub
Failed:
    AppendDiagnostic restoreDiagnostics, "selection_check_failed"
    Err.Clear
    Resume CleanExit
End Sub

Private Sub AppendDiagnostic(ByRef diagnostics As String, ByVal value As String)
    If Len(diagnostics) > 0 Then diagnostics = diagnostics & ";"
    diagnostics = diagnostics & value
End Sub
