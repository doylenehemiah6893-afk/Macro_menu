Attribute VB_Name = "MM_DocumentSummary"
Option Explicit

Private Const MAX_SELECTION_COUNT As Long = 10000

Public Function RunDocumentSummary(ByVal context As C_MMContext) As C_MMResult
    Dim activeDocument As Object
    Dim data As Variant
    Dim readOnlyAvailable As Boolean
    Dim readOnlyValue As Boolean
    Dim readOnlyResult As Variant
    Dim result As C_MMResult
    Dim savedAvailable As Boolean
    Dim savedValue As Boolean
    Dim savedResult As Variant
    Dim selectionAvailable As Boolean
    Dim selectionCount As Long
    Dim selectionObject As Object
    Dim selectionResult As Variant
    Dim selectionTruncated As Boolean
    On Error GoTo Fail

    If Not context.HasActiveDocument Then
        Set result = MM_Error.ResultForCode(20, "No active document", Empty, Empty)
        GoTo CleanExit
    End If

    Set activeDocument = context.ActiveDocument
    savedAvailable = MM_TryGet.TryGetDocumentSaved(activeDocument, savedValue)
    If savedAvailable Then
        savedResult = savedValue
    Else
        savedResult = Empty
    End If
    readOnlyAvailable = MM_TryGet.TryGetDocumentReadOnly(activeDocument, readOnlyValue)
    If readOnlyAvailable Then
        readOnlyResult = readOnlyValue
    Else
        readOnlyResult = Empty
    End If

    Set selectionObject = context.Selection
    If Not selectionObject Is Nothing Then
        selectionAvailable = MM_TryGet.TryGetSelectionCount(selectionObject, selectionCount)
    End If
    If selectionAvailable Then
        If selectionCount > MAX_SELECTION_COUNT Then
            selectionResult = CLng(MAX_SELECTION_COUNT)
            selectionTruncated = True
        ElseIf selectionCount < 0 Then
            selectionResult = CLng(0)
            selectionTruncated = True
        Else
            selectionResult = CLng(selectionCount)
        End If
    Else
        selectionResult = Empty
    End If

    data = Array( _
        Array("context.document_type", context.DocumentType), _
        Array("document.read_only.available", readOnlyAvailable), _
        Array("document.read_only.value", readOnlyResult), _
        Array("document.saved.available", savedAvailable), _
        Array("document.saved.value", savedResult), _
        Array("selection.count", selectionResult), _
        Array("selection.count.available", selectionAvailable), _
        Array("selection.count.cap", CLng(MAX_SELECTION_COUNT)), _
        Array("selection.count.truncated", selectionTruncated))
    Set result = MM_Error.ResultForCode(0, "Document summary ready", data, Empty)
CleanExit:
    Set RunDocumentSummary = result
    Exit Function
Fail:
    Set result = MM_Error.ResultForCode(60, "Document summary failed", Empty, Empty)
    Err.Clear
    Resume CleanExit
End Function
