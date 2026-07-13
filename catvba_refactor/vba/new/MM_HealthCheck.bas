Attribute VB_Name = "MM_HealthCheck"
Option Explicit

Public Function RunHealthCheck(ByVal context As C_MMContext) As C_MMResult
    Dim data As Variant
    Dim releaseAvailable As Boolean
    Dim releaseText As String
    Dim releaseValue As Variant
    Dim result As C_MMResult
    Dim vba7Enabled As Boolean
    Dim win64Enabled As Boolean
    On Error GoTo Fail

#If VBA7 Then
    vba7Enabled = True
#Else
    vba7Enabled = False
#End If
#If Win64 Then
    win64Enabled = True
#Else
    win64Enabled = False
#End If

    releaseAvailable = MM_TryGet.TryGetCATIARelease(context.ApplicationObject, releaseText)
    If releaseAvailable Then
        releaseValue = releaseText
    Else
        releaseValue = Empty
    End If
    data = Array( _
        Array("build.manifest_digest", MM_BuildInfo.MM_MANIFEST_DIGEST), _
        Array("build.protocol_version", MM_BuildInfo.MM_PROTOCOL_VERSION), _
        Array("build.tool_version", MM_BuildInfo.MM_TOOL_VERSION), _
        Array("build.work_commit", MM_BuildInfo.MM_WORK_COMMIT), _
        Array("build.work_tree", MM_BuildInfo.MM_WORK_TREE), _
        Array("catia.release.available", releaseAvailable), _
        Array("catia.release.value", releaseValue), _
        Array("compile.vba7", vba7Enabled), _
        Array("compile.win64", win64Enabled), _
        Array("context.document_type", context.DocumentType), _
        Array("core.status", "READY"), _
        Array("tool.id", "core.healthcheck"))
    Set result = MM_Error.ResultForCode(0, "Core runtime ready", data, Empty)
CleanExit:
    Set RunHealthCheck = result
    Exit Function
Fail:
    Set result = MM_Error.ResultForCode(60, "Health check failed", Empty, Empty)
    Err.Clear
    Resume CleanExit
End Function
