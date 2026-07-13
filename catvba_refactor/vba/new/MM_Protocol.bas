Attribute VB_Name = "MM_Protocol"
Option Explicit

Private Const PROTOCOL_VERSION As String = "MM/1"
Private Const REQUEST_FIELD_COUNT As Long = 5
Private Const RESPONSE_FIELD_COUNT As Long = 7
Private Const MAX_DEPTH As Long = 8
Private Const MAX_STRING_LENGTH As Long = 4096
Private Const MAX_ARRAY_LENGTH As Long = 256
Private Const MAX_TOTAL_NODES As Long = 2048
Private Const MAX_DISPLAY_LINES As Long = 500

Public Function TryParseRequest(ByVal request As Variant, ByRef requestId As String, ByRef commandId As String, ByRef context As C_MMContext, ByRef result As C_MMResult) As Boolean
    Dim nodeCount As Long
    On Error GoTo InvalidRequest
    requestId = vbNullString
    commandId = vbNullString
    Set context = Nothing
    Set result = Nothing
    If VarType(request) <> vbArray + vbVariant Then GoTo InvalidRequest
    If Not HasExactLength(request, REQUEST_FIELD_COUNT) Then GoTo InvalidRequest
    If Not ValidateValue(request, 0, nodeCount) Then GoTo InvalidRequest
    If VarType(request(0)) <> vbString Then GoTo InvalidRequest
    If CStr(request(0)) <> PROTOCOL_VERSION Then GoTo InvalidRequest
    If VarType(request(1)) <> vbString Then GoTo InvalidRequest
    If VarType(request(2)) <> vbString Then GoTo InvalidRequest
    If VarType(request(3)) <> vbString Then GoTo InvalidRequest
    requestId = CStr(request(1))
    commandId = LCase$(CStr(request(2)))
    If Len(requestId) = 0 Or Len(commandId) = 0 Or Len(CStr(request(3))) = 0 Then GoTo InvalidRequest
    If Not ValidateKeyValueArray(request(4)) Then GoTo InvalidRequest
    Set context = New C_MMContext
    If Not context.Initialize(request(4)) Then GoTo InvalidRequest
    TryParseRequest = True
CleanExit:
    Exit Function
InvalidRequest:
    Set context = Nothing
    Set result = MM_Error.ValidationFailed("Invalid MM/1 request")
    TryParseRequest = False
    Resume CleanExit
End Function

Public Function BuildResponse(ByVal requestId As String, ByVal result As C_MMResult) As Variant
    Dim candidate As Variant
    Dim nodeCount As Long
    On Error GoTo InvalidResult
    If result Is Nothing Then GoTo InvalidResult
    If Not MM_Error.IsKnownCodeAndStatus(result.Code, result.Status) Then GoTo InvalidResult
    If Len(requestId) > MAX_STRING_LENGTH Then GoTo InvalidResult
    If Not HasValidDisplayMessage(result.DisplayMessage) Then GoTo InvalidResult
    If Not ValidateKeyValueArray(result.Meta) Then GoTo InvalidResult
    candidate = Array(PROTOCOL_VERSION, requestId, result.Status, result.Code, result.DisplayMessage, result.Data, result.Meta)
    If Not HasExactLength(candidate, RESPONSE_FIELD_COUNT) Then GoTo InvalidResult
    If Not ValidateValue(candidate, 0, nodeCount) Then GoTo InvalidResult
    BuildResponse = candidate
CleanExit:
    Exit Function
InvalidResult:
    BuildResponse = Array(PROTOCOL_VERSION, Left$(requestId, MAX_STRING_LENGTH), "INTERNAL_ERROR", CLng(70), "Invalid result", Empty, Empty)
    Resume CleanExit
End Function

Public Function IsTransportValue(ByVal value As Variant) As Boolean
    Dim nodeCount As Long
    On Error GoTo InvalidValue
    IsTransportValue = ValidateValue(value, 0, nodeCount)
CleanExit:
    Exit Function
InvalidValue:
    IsTransportValue = False
    Resume CleanExit
End Function

Public Function IsMetaValue(ByVal value As Variant) As Boolean
    Dim nodeCount As Long
    On Error GoTo InvalidValue
    If Not ValidateValue(value, 0, nodeCount) Then GoTo InvalidValue
    If Not ValidateKeyValueArray(value) Then GoTo InvalidValue
    IsMetaValue = True
CleanExit:
    Exit Function
InvalidValue:
    IsMetaValue = False
    Resume CleanExit
End Function

Private Function ValidateValue(ByVal value As Variant, ByVal depth As Long, ByRef nodeCount As Long) As Boolean
    Dim index As Long
    Dim valueType As VbVarType
    On Error GoTo InvalidValue
    If depth > MAX_DEPTH Then GoTo InvalidValue
    nodeCount = nodeCount + 1
    If nodeCount > MAX_TOTAL_NODES Then GoTo InvalidValue
    valueType = VarType(value)
    Select Case valueType
        Case vbEmpty, vbBoolean, vbLong, vbDouble
            ValidateValue = True
        Case vbString
            ValidateValue = (Len(CStr(value)) <= MAX_STRING_LENGTH)
        Case vbArray + vbVariant
            If Not HasBoundedArray(value) Then GoTo InvalidValue
            For index = LBound(value) To UBound(value)
                If Not ValidateValue(value(index), depth + 1, nodeCount) Then GoTo InvalidValue
            Next index
            ValidateValue = True
        Case Else
            ValidateValue = False
    End Select
CleanExit:
    Exit Function
InvalidValue:
    ValidateValue = False
    Resume CleanExit
End Function

Private Function ValidateKeyValueArray(ByVal value As Variant) As Boolean
    Dim index As Long
    Dim key As String
    Dim previousKey As String
    Dim row As Variant
    On Error GoTo InvalidArray
    If IsEmpty(value) Then
        ValidateKeyValueArray = True
        GoTo CleanExit
    End If
    If VarType(value) <> vbArray + vbVariant Then GoTo InvalidArray
    If Not HasBoundedArray(value) Then GoTo InvalidArray
    For index = LBound(value) To UBound(value)
        row = value(index)
        If VarType(row) <> vbArray + vbVariant Then GoTo InvalidArray
        If Not HasExactLength(row, 2) Then GoTo InvalidArray
        If VarType(row(0)) <> vbString Then GoTo InvalidArray
        key = CStr(row(0))
        If Len(key) = 0 Or Len(key) > MAX_STRING_LENGTH Then GoTo InvalidArray
        If index > LBound(value) Then
            If StrComp(previousKey, key, vbBinaryCompare) >= 0 Then GoTo InvalidArray
        End If
        previousKey = key
    Next index
    ValidateKeyValueArray = True
CleanExit:
    Exit Function
InvalidArray:
    ValidateKeyValueArray = False
    Resume CleanExit
End Function

Private Function HasBoundedArray(ByVal value As Variant) As Boolean
    Dim itemCount As Long
    On Error GoTo InvalidArray
    itemCount = UBound(value) - LBound(value) + 1
    HasBoundedArray = (itemCount >= 0 And itemCount <= MAX_ARRAY_LENGTH)
CleanExit:
    Exit Function
InvalidArray:
    HasBoundedArray = False
    Resume CleanExit
End Function

Private Function HasExactLength(ByVal value As Variant, ByVal expectedLength As Long) As Boolean
    On Error GoTo InvalidArray
    HasExactLength = (LBound(value) = 0 And UBound(value) = expectedLength - 1)
CleanExit:
    Exit Function
InvalidArray:
    HasExactLength = False
    Resume CleanExit
End Function

Private Function HasValidDisplayMessage(ByVal displayMessage As String) As Boolean
    Dim lineCount As Long
    Dim normalized As String
    If Len(displayMessage) > MAX_STRING_LENGTH Then Exit Function
    If Len(displayMessage) = 0 Then
        HasValidDisplayMessage = True
        Exit Function
    End If
    normalized = Replace(Replace(displayMessage, vbCrLf, vbLf), vbCr, vbLf)
    normalized = Replace(normalized, ChrW(&H2028), vbLf)
    normalized = Replace(normalized, ChrW(&H2029), vbLf)
    lineCount = UBound(Split(normalized, vbLf)) + 1
    HasValidDisplayMessage = (lineCount <= MAX_DISPLAY_LINES)
End Function
