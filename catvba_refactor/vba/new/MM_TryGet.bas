Attribute VB_Name = "MM_TryGet"
Option Explicit

Public Function TryGetActiveDocument(ByVal applicationObject As Object, ByRef value As Object) As Boolean
    Dim errorNumber As Long
    On Error Resume Next
    Set value = applicationObject.ActiveDocument
    errorNumber = Err.Number
    Err.Clear
    On Error GoTo 0
    TryGetActiveDocument = (errorNumber = 0 And Not value Is Nothing)
CleanExit:
    Exit Function
End Function

Public Function TryGetActiveWindow(ByVal applicationObject As Object, ByRef value As Object) As Boolean
    Dim errorNumber As Long
    On Error Resume Next
    Set value = applicationObject.ActiveWindow
    errorNumber = Err.Number
    Err.Clear
    On Error GoTo 0
    TryGetActiveWindow = (errorNumber = 0 And Not value Is Nothing)
CleanExit:
    Exit Function
End Function

Public Function TryGetSelection(ByVal documentObject As Object, ByRef value As Object) As Boolean
    Dim errorNumber As Long
    On Error Resume Next
    Set value = documentObject.Selection
    errorNumber = Err.Number
    Err.Clear
    On Error GoTo 0
    TryGetSelection = (errorNumber = 0 And Not value Is Nothing)
CleanExit:
    Exit Function
End Function

Public Function TryGetSelectionCount(ByVal selectionObject As Object, ByRef value As Long) As Boolean
    Dim errorNumber As Long
    On Error Resume Next
    value = CLng(selectionObject.Count2)
    errorNumber = Err.Number
    Err.Clear
    On Error GoTo 0
    TryGetSelectionCount = (errorNumber = 0)
CleanExit:
    Exit Function
End Function

Public Function TryGetDisplayFileAlerts(ByVal applicationObject As Object, ByRef value As Boolean) As Boolean
    Dim errorNumber As Long
    On Error Resume Next
    value = CBool(applicationObject.DisplayFileAlerts)
    errorNumber = Err.Number
    Err.Clear
    On Error GoTo 0
    TryGetDisplayFileAlerts = (errorNumber = 0)
CleanExit:
    Exit Function
End Function

Public Function TryGetRefreshDisplay(ByVal applicationObject As Object, ByRef value As Boolean) As Boolean
    Dim errorNumber As Long
    On Error Resume Next
    value = CBool(applicationObject.RefreshDisplay)
    errorNumber = Err.Number
    Err.Clear
    On Error GoTo 0
    TryGetRefreshDisplay = (errorNumber = 0)
CleanExit:
    Exit Function
End Function
