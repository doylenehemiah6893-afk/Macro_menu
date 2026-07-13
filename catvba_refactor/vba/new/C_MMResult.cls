VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "C_MMResult"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

Private mStatus As String
Private mCode As Long
Private mDisplayMessage As String
Private mData As Variant
Private mMeta As Variant

Public Function Initialize(ByVal status As String, ByVal code As Long, ByVal displayMessage As String, ByVal data As Variant, ByVal meta As Variant) As Boolean
    On Error GoTo InvalidValue
    If Not MM_Error.IsKnownCodeAndStatus(code, status) Then GoTo InvalidValue
    If Not MM_Protocol.IsTransportValue(data) Then GoTo InvalidValue
    If Not MM_Protocol.IsMetaValue(meta) Then GoTo InvalidValue
    mStatus = status
    mCode = code
    mDisplayMessage = displayMessage
    mData = data
    mMeta = meta
    Initialize = True
CleanExit:
    Exit Function
InvalidValue:
    mStatus = "INTERNAL_ERROR"
    mCode = 70
    mDisplayMessage = "Invalid result value"
    mData = Empty
    mMeta = Empty
    Initialize = False
    Resume CleanExit
End Function

Public Property Get Status() As String
    Status = mStatus
End Property

Public Property Get Code() As Long
    Code = mCode
End Property

Public Property Get DisplayMessage() As String
    DisplayMessage = mDisplayMessage
End Property

Public Property Get Data() As Variant
    Data = mData
End Property

Public Property Get Meta() As Variant
    Meta = mMeta
End Property
