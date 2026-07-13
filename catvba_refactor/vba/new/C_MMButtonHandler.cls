VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "C_MMButtonHandler"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

Private WithEvents mButton As MSForms.CommandButton
Private mToolId As String

Public Function Initialize(ByVal button As MSForms.CommandButton, ByVal toolId As String) As Boolean
    On Error GoTo Fail
    Initialize = False
    Set mButton = button
    mToolId = toolId
    Initialize = True
CleanExit:
    Exit Function
Fail:
    Set mButton = Nothing
    mToolId = vbNullString
    Initialize = False
    Resume CleanExit
End Function

Private Sub mButton_Click()
    On Error GoTo Fail
    MM_MenuPresenter.InvokeTool mToolId
CleanExit:
    Exit Sub
Fail:
    Resume CleanExit
End Sub
