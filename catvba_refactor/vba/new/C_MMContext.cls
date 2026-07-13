VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "C_MMContext"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

Private mApplication As Object
Private mActiveDocument As Object
Private mActiveWindow As Object
Private mSelection As Object
Private mDocumentType As String
Private mOptions As Variant

Public Function Initialize(ByVal options As Variant) As Boolean
    On Error GoTo Fail
    Set mApplication = CATIA
    mOptions = options
    If MM_TryGet.TryGetActiveDocument(mApplication, mActiveDocument) Then
        mDocumentType = TypeName(mActiveDocument)
        MM_TryGet.TryGetSelection mActiveDocument, mSelection
    Else
        mDocumentType = "None"
    End If
    MM_TryGet.TryGetActiveWindow mApplication, mActiveWindow
    Initialize = True
CleanExit:
    Exit Function
Fail:
    Initialize = False
    Resume CleanExit
End Function

Public Property Get ApplicationObject() As Object
    Set ApplicationObject = mApplication
End Property

Public Property Get ActiveDocument() As Object
    Set ActiveDocument = mActiveDocument
End Property

Public Property Get ActiveWindow() As Object
    Set ActiveWindow = mActiveWindow
End Property

Public Property Get Selection() As Object
    Set Selection = mSelection
End Property

Public Property Get DocumentType() As String
    DocumentType = mDocumentType
End Property

Public Property Get Options() As Variant
    Options = mOptions
End Property

Public Property Get HasActiveDocument() As Boolean
    HasActiveDocument = Not mActiveDocument Is Nothing
End Property
