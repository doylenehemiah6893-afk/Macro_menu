Attribute VB_Name = "MM_Entry"
Option Explicit

Public Sub CATMain()
    On Error GoTo Fail
    MM_MenuPresenter.ShowCoreMenu
CleanExit:
    Exit Sub
Fail:
    Resume CleanExit
End Sub
