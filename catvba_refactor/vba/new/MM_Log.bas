Attribute VB_Name = "MM_Log"
Option Explicit

Private Const PRODUCTION_SINK_ENABLED As Boolean = False

Public Sub WriteResult(ByVal utcTimestamp As String, ByVal buildId As String, ByVal requestId As String, ByVal toolId As String, ByVal resultCode As Long, ByVal durationMilliseconds As Long, ByVal itemCount As Long, ByVal documentType As String)
    Dim record As String
    On Error GoTo LogFail
    If Not PRODUCTION_SINK_ENABLED Then GoTo CleanExit
    record = utcTimestamp & "|" & buildId & "|" & requestId & "|" & toolId & "|" & CStr(resultCode) & "|" & CStr(durationMilliseconds) & "|" & CStr(itemCount) & "|" & documentType
CleanExit:
    Exit Sub
LogFail:
    Err.Clear
    Resume CleanExit
End Sub
