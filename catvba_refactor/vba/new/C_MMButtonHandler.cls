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

Public Sub Initialize(ByVal button As MSForms.CommandButton, ByVal toolId As String)
    On Error GoTo Fail
    Set mButton = button
    mToolId = LCase$(toolId)
CleanExit:
    Exit Sub
Fail:
    Set mButton = Nothing
    mToolId = vbNullString
    Resume CleanExit
End Sub

Private Sub mButton_Click()
    On Error GoTo Fail
    MM_MenuPresenter.InvokeTool mToolId
CleanExit:
    Exit Sub
Fail:
    Resume CleanExit
End Sub
