Attribute VB_Name = "MM_Error"
Option Explicit

Public Function ResultForCode(ByVal code As Long, ByVal displayMessage As String, ByVal data As Variant, ByVal meta As Variant) As C_MMResult
    Dim result As C_MMResult
    On Error GoTo Fail
    Set result = New C_MMResult
    If Not result.Initialize(StatusForCode(code), code, displayMessage, data, meta) Then GoTo Fail
    Set ResultForCode = result
CleanExit:
    Exit Function
Fail:
    Set ResultForCode = Nothing
    Resume CleanExit
End Function

Public Function IsKnownCodeAndStatus(ByVal code As Long, ByVal status As String) As Boolean
    Dim expectedStatus As String
    On Error GoTo Fail
    expectedStatus = StatusForCode(code)
    IsKnownCodeAndStatus = (Len(expectedStatus) > 0 And StrComp(expectedStatus, status, vbBinaryCompare) = 0)
CleanExit:
    Exit Function
Fail:
    IsKnownCodeAndStatus = False
    Resume CleanExit
End Function

Public Function ValidationFailed(ByVal displayMessage As String) As C_MMResult
    On Error GoTo Fail
    Set ValidationFailed = ResultForCode(40, displayMessage, Empty, Empty)
CleanExit:
    Exit Function
Fail:
    Set ValidationFailed = Nothing
    Resume CleanExit
End Function

Public Function UnknownCommand(ByVal commandId As String) As C_MMResult
    On Error GoTo Fail
    Set UnknownCommand = ResultForCode(90, "Unknown command", Empty, Empty)
CleanExit:
    Exit Function
Fail:
    Set UnknownCommand = Nothing
    Resume CleanExit
End Function

Public Function InternalError(ByVal errorNumber As Long) As C_MMResult
    On Error GoTo Fail
    Set InternalError = ResultForCode(70, "Internal error", Empty, Array(Array("error_number", CLng(errorNumber))))
CleanExit:
    Exit Function
Fail:
    Set InternalError = Nothing
    Resume CleanExit
End Function

Private Function StatusForCode(ByVal code As Long) As String
    Select Case code
        Case 0: StatusForCode = "OK"
        Case 10: StatusForCode = "CANCELLED"
        Case 20: StatusForCode = "NOT_APPLICABLE"
        Case 30: StatusForCode = "CAPABILITY_UNAVAILABLE"
        Case 40: StatusForCode = "VALIDATION_FAILED"
        Case 50: StatusForCode = "STATE_CHANGED"
        Case 60: StatusForCode = "TOOL_FAILED"
        Case 70: StatusForCode = "INTERNAL_ERROR"
        Case 80: StatusForCode = "LIMIT_REACHED"
        Case 90: StatusForCode = "UNKNOWN_COMMAND"
        Case Else: StatusForCode = vbNullString
    End Select
End Function
