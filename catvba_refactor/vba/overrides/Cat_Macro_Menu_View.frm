VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} Cat_Macro_Menu_View 
   Caption         =   "UserForm1"
   ClientHeight    =   6855
   ClientLeft      =   120
   ClientTop       =   450
   ClientWidth     =   4485
   OleObjectBlob   =   "Cat_Macro_Menu_View.frx":0000
   StartUpPosition =   1  'CenterOwner
End
Attribute VB_Name = "Cat_Macro_Menu_View"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Explicit

Private Const MENU_CONTROL_NAME As String = "mpg_core"
Private Const BUTTON_HEIGHT As Single = 22
Private Const BUTTON_GAP As Single = 4

Private mHandlers As Collection
Private mPageObjects As Collection
Private mPageNames As Collection
Private mPageGroupIds As Collection
Private mMenuPages As MSForms.MultiPage
Private mMenuCreated As Boolean

Public Function InitializeMenu( _
    ByVal toolIds As Variant, _
    ByVal captions As Variant, _
    ByVal tooltips As Variant, _
    ByVal groupIds As Variant, _
    ByVal groupCaptions As Variant, _
    ByVal controlNames As Variant, _
    ByVal pageNames As Variant) As Boolean
    Dim button As MSForms.CommandButton
    Dim handler As C_MMButtonHandler
    Dim index As Long
    Dim page As MSForms.Page
    On Error GoTo Fail

    InitializeMenu = False
    If Not ClearMenu() Then GoTo CleanExit
    If Not IsArray(toolIds) Then GoTo CleanExit
    If Not IsArray(captions) Then GoTo CleanExit
    If Not IsArray(tooltips) Then GoTo CleanExit
    If Not IsArray(groupIds) Then GoTo CleanExit
    If Not IsArray(groupCaptions) Then GoTo CleanExit
    If Not IsArray(controlNames) Then GoTo CleanExit
    If Not IsArray(pageNames) Then GoTo CleanExit
    If Not SameBounds(toolIds, captions) Then GoTo CleanExit
    If Not SameBounds(toolIds, tooltips) Then GoTo CleanExit
    If Not SameBounds(toolIds, groupIds) Then GoTo CleanExit
    If Not SameBounds(toolIds, groupCaptions) Then GoTo CleanExit
    If Not SameBounds(toolIds, controlNames) Then GoTo CleanExit
    If Not SameBounds(toolIds, pageNames) Then GoTo CleanExit
    If UBound(toolIds) - LBound(toolIds) + 1 > 256 Then GoTo CleanExit

    Set mHandlers = New Collection
    Set mPageObjects = New Collection
    Set mPageNames = New Collection
    Set mPageGroupIds = New Collection
    Set mMenuPages = Me.Controls.Add("Forms.MultiPage.1", MENU_CONTROL_NAME, True)
    mMenuCreated = True
    If Not ConfigureMenuPages() Then GoTo Fail

    For index = LBound(toolIds) To UBound(toolIds)
        If Not DescriptorIsComplete( _
            CStr(toolIds(index)), _
            CStr(captions(index)), _
            CStr(tooltips(index)), _
            CStr(groupIds(index)), _
            CStr(groupCaptions(index)), _
            CStr(controlNames(index)), _
            CStr(pageNames(index))) Then GoTo Fail
        Set page = FindOrCreatePage( _
            CStr(pageNames(index)), _
            CStr(groupIds(index)), _
            CStr(groupCaptions(index)))
        If page Is Nothing Then GoTo Fail
        Set button = page.Controls.Add( _
            "Forms.CommandButton.1", CStr(controlNames(index)), True)
        With button
            .Caption = CStr(captions(index))
            .ControlTipText = CStr(tooltips(index))
            .Left = 8
            .Top = 8 + (page.Controls.Count - 1) * (BUTTON_HEIGHT + BUTTON_GAP)
            .Width = 180
            .Height = BUTTON_HEIGHT
        End With
        Set handler = New C_MMButtonHandler
        If Not handler.Initialize(button, CStr(toolIds(index))) Then GoTo Fail
        mHandlers.Add handler
    Next index
    InitializeMenu = True
CleanExit:
    Exit Function
Fail:
    InitializeMenu = False
    If Not ClearMenu() Then Err.Clear
    Resume CleanExit
End Function

Private Function SameBounds( _
    ByVal referenceValues As Variant, _
    ByVal candidateValues As Variant) As Boolean
    On Error GoTo Fail
    SameBounds = (LBound(referenceValues) = LBound(candidateValues)) _
        And (UBound(referenceValues) = UBound(candidateValues))
CleanExit:
    Exit Function
Fail:
    SameBounds = False
    Resume CleanExit
End Function

Private Function DescriptorIsComplete( _
    ByVal toolId As String, _
    ByVal caption As String, _
    ByVal tooltip As String, _
    ByVal groupId As String, _
    ByVal groupCaption As String, _
    ByVal controlName As String, _
    ByVal pageName As String) As Boolean
    On Error GoTo Fail
    DescriptorIsComplete = (Len(toolId) > 0) _
        And (Len(caption) > 0) _
        And (Len(tooltip) > 0) _
        And (Len(groupId) > 0) _
        And (Len(groupCaption) > 0) _
        And (Len(controlName) > 0) _
        And (Len(pageName) > 0)
CleanExit:
    Exit Function
Fail:
    DescriptorIsComplete = False
    Resume CleanExit
End Function

Private Function FindOrCreatePage( _
    ByVal pageName As String, _
    ByVal groupId As String, _
    ByVal groupCaption As String) As MSForms.Page
    Dim index As Long
    Dim page As MSForms.Page
    On Error GoTo Fail

    For index = 1 To mPageNames.Count
        If StrComp(CStr(mPageNames.Item(index)), pageName, vbBinaryCompare) = 0 Then
            If StrComp(CStr(mPageGroupIds.Item(index)), groupId, vbBinaryCompare) <> 0 Then GoTo Fail
            Set page = mPageObjects.Item(index)
            If StrComp(page.Caption, groupCaption, vbBinaryCompare) <> 0 Then GoTo Fail
            Set FindOrCreatePage = page
            GoTo CleanExit
        End If
    Next index

    Set page = mMenuPages.Pages.Add( _
        pageName, groupCaption, mMenuPages.Pages.Count)
    mPageNames.Add pageName
    mPageGroupIds.Add groupId
    mPageObjects.Add page
    Set FindOrCreatePage = page
CleanExit:
    Exit Function
Fail:
    Set FindOrCreatePage = Nothing
    Resume CleanExit
End Function

Private Function ConfigureMenuPages() As Boolean
    On Error GoTo Fail
    ConfigureMenuPages = False
    With mMenuPages
        .Left = 8
        .Top = 8
        .Width = 220
        .Height = 300
        .TabOrientation = fmTabOrientationTop
        .Style = fmTabStyleTabs
    End With
    Me.Caption = "Macro Menu"
    Me.Width = 250
    Me.Height = 350
    ConfigureMenuPages = True
CleanExit:
    Exit Function
Fail:
    ConfigureMenuPages = False
    Resume CleanExit
End Function

Private Function ClearMenu() As Boolean
    On Error GoTo Fail
    ClearMenu = False
    Set mHandlers = Nothing
    Set mPageObjects = Nothing
    Set mPageNames = Nothing
    Set mPageGroupIds = Nothing
    Set mMenuPages = Nothing
    If mMenuCreated Then Me.Controls.Remove MENU_CONTROL_NAME
    mMenuCreated = False
    ClearMenu = True
CleanExit:
    Exit Function
Fail:
    ClearMenu = False
    Err.Clear
    Resume CleanExit
End Function
