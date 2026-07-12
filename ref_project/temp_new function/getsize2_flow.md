> [!CAUTION]
> **Status:** `QUARANTINE`
> **Execution:** `DO NOT EXECUTE`
> **release:** `false`
> **Provenance:** `UNKNOWN`；无许可证或再分发授权记录
>
> 已发现的风险：
>
> - 首段会新建 Drawing、Sheet 和多个生成视图，切换活动视图、执行 `Reframe`，并删除默认 Sheet；
> - 第二段会在活动 Drawing 中新建文本/Leader 后执行 `Selection.Delete` 删除原文本，没有预览、事务或回滚；
> - 依赖 CATIA Drafting、生成视图、Product/Part、活动窗口/选择以及本地化 `StartCommand`，目标许可证和 R2018 行为未验证；
> - 存在确定性缺陷：`InStr(...) <> O` 使用字母 `O`，投影视图把当前行为对象传给自身，且无条件访问 `Leaders.Item(1)`；
> - 文件包含未声明变量、缺少错误恢复、乱码过程名，以及位于过程外的 `StartCommand (...)————...` 文本，不能作为可编译模块使用。


Private Sub �������ɹ���ͼ()
    Dim documents1 As Documents
    Set documents1 = CATIA.Documents
    Dim drawingDocument1 As DrawingDocument
    Dim productDocument1 As Document
    Dim product1 As Product
    Dim drawingView2 As DrawingView
    Dim drawingViewGenerativeLinks2 As DrawingViewGenerativeLinks
    Dim drawingViewGenerativeBehavior2 As DrawingViewGenerativeBehavior
    Dim drawingView3 As DrawingView
    Dim drawingViewGenerativeLinks3 As DrawingViewGenerativeLinks
    Dim drawingViewGenerativeBehavior3 As DrawingViewGenerativeBehavior
    Dim drawingSheets1 As DrawingSheets
    Dim drawingSheet1 As DrawingSheet
    Dim drawingViews1 As DrawingViews
    Dim drawingView1 As DrawingView
    Dim drawingViewGenerativeLinks1 As DrawingViewGenerativeLinks
    Dim drawingViewGenerativeBehavior1 As DrawingViewGenerativeBehavior
    Dim specsAndGeomWindow1 As Window
    Dim viewer3D1 As Viewer
    Dim PaperW As Double, PaperH As Double
    Set drawingDocument1 = documents1.Add("Drawing")
    drawingDocument1.Standard = catISO
    Set drawingSheets1 = drawingDocument1.Sheets
    Dim i As Integer
    For i = 1 To documents1.Count
        Set productDocument1 = documents1.Item(i)
        If TypeName(productDocument1) <> "ProductDocument" And TypeName(productDocument1) <> "PartDocument" Then GoTo NextFor
        Set drawingSheet1 = drawingSheets1.Add(productDocument1.Name)
        drawingSheet1.PaperSize = catPaperA4
        drawingSheet1.[Scale] = 1#
        drawingSheet1.Orientation = catPaperPortrait
        Set drawingViews1 = drawingSheet1.Views
        Set drawingView1 = drawingViews1.Add("AutomaticNaming")
        PaperW = drawingSheet1.GetPaperWidth
        PaperH = drawingSheet1.GetPaperHeight
        drawingView1.x = PaperW / 4
        drawingView1.Y = PaperH * 3 / 4
        drawingView1.[Scale] = 1#
        Set drawingViewGenerativeLinks1 = drawingView1.GenerativeLinks
        Set drawingViewGenerativeBehavior1 = drawingView1.GenerativeBehavior
        Set product1 = productDocument1.Product
        drawingViewGenerativeBehavior1.Document = product1
        drawingViewGenerativeBehavior1.DefineFrontView 1#, 0#, 0#, 0#, 1#, 0#
        drawingViewGenerativeBehavior1.Update
        Set drawingView1 = drawingViews1.Add("AutomaticNaming")
        drawingView1.x = PaperW / 4
        drawingView1.Y = PaperH / 3
        drawingView1.[Scale] = 1#
        Set drawingViewGenerativeLinks1 = drawingView1.GenerativeLinks
        Set drawingViewGenerativeBehavior1 = drawingView1.GenerativeBehavior
        drawingViewGenerativeBehavior1.Document = product1
        Set drawingViewGenerativeBehavior1 = drawingView1.GenerativeBehavior
        drawingViewGenerativeBehavior1.DefineProjectionView drawingViewGenerativeBehavior1, catTopView
        drawingViewGenerativeBehavior1.Update
        Set drawingView1 = drawingViews1.Add("AutomaticNaming")
        drawingView1.x = PaperW * 3 / 4
        drawingView1.Y = PaperH * 3 / 4
        drawingView1.[Scale] = 1#
        Set drawingViewGenerativeLinks1 = drawingView1.GenerativeLinks
        Set drawingViewGenerativeBehavior1 = drawingView1.GenerativeBehavior
        drawingViewGenerativeBehavior1.Document = product1
        Set drawingViewGenerativeBehavior1 = drawingView1.GenerativeBehavior
        drawingViewGenerativeBehavior1.DefineProjectionView drawingViewGenerativeBehavior1, catLeftView
        drawingViewGenerativeBehavior1.Update
        drawingView1.Activate
        Set specsAndGeomWindow1 = CATIA.ActiveWindow
        Set viewer3D1 = specsAndGeomWindow1.ActiveViewer
        viewer3D1.Reframe
NextFor:
    Next
    drawingSheets1.Remove 1
    drawingSheets1.Item(1).Activate
End Sub



Attribute VB_Name = "Module1"
Sub CATMain()

    Dim Slct

    Set Slct = CATIA.ActiveDocument.Selection
    
    Dim view
    Set view = CATIA.ActiveDocument.Sheets.ActiveSheet.Views.ActiveView
    
    Slct.Clear

    For Each Text In view.Texts
        '英文环境下零件序号改为Balloon
        If InStr(Text.Name, "零件序号") <> O Then
        
        Dim MyStr

        MyStr = Text.Text

        Dim TextPosX, TextPosY, LeaderPosX, LeaderPosY
        TextPosX = Text.X
        TextPosY = Text.Y
        Text.Leaders.Item(1).GetPoint 1, LeaderPosX, LeaderPosY
        
        Slct.Add (Text)
        Set t = view.Texts.Add(MyStr, TextPosX, TextPosY)
        Set l = t.Leaders.Add(LeaderPosX, LeaderPosY)
        t.SetFontSize 0, 0, 10
        
    End If
    
Next

Slct.Delete

End Sub



StartCommand ("SpecificationsLevel1")————展开第一层 
StartCommand ("SpecificationsLevel2")————展开第二层 
StartCommand ("SpecificationsLevel3")————展开第三层 
StartCommand ("SpecificationsLevelSelect")————选择展开深度 
StartCommand ("SpecificationsLevelAll")————展开所有层
