> [!CAUTION]
> **文档状态：SUPERSEDED（历史 BOM 重构提案）**
> **核对基线：** 2026-07-13，Git `b0085868`
> **当前 Authority：** [`KCL.bas`](../Src/KCL.bas)、[`Cls_PDM.cls`](../Src/Cls_PDM.cls)、[`Cls_XLM.cls`](../Src/Cls_XLM.cls) 与 [`RW_Cbom.bas`](../Src/RW_Cbom.bas)
> **执行策略：** DO NOT EXECUTE。“最终版”和“立即执行”仅是历史提案措辞，不得按正文再次创建、删除或迁移模块。
> **许可证/部署边界：** 目标架构计划把 Excel COM 隔离为 Optional；当前单体尚未完成隔离，`Cls_XLM` 经 `Cls_WsEvt` 仍早绑定 `Workbook`，可能要求 Excel 类型库才能编译。本文未证明无 Office 可构建，也未证明任何 CATIA 产品配置、KWA 或 DSLS 权益，须以当前架构与目标机验证为准。

## 当前实施结果（不改写历史提案）

| 历史提案项 | 当前核对结果 |
|---|---|
| `A00_globalVar.bas` | historical, absent；没有创建该模块。 |
| `BOMItem` / `ParamItem` | 当前使用 `KCL.Bomline` 与 `KCL.ParamItem`；`BOMItem` 不存在。 |
| `Cls_Para.cls` | historical, absent。 |
| `Cls_PDM.ProduceBOM` | 当前返回 `Bomline()`。 |
| `Cls_XLM.InjectBOM_Typed` | 不存在；当前 BOM 路径使用 `inject_Bom` / `inject_GXbom` 接收二维 `Variant`，另有 `inject_RvData(data() As Bomline)`。 |
| `RW_Cbom` | 当前先以 `ConvertBOM_Standard` / `ConvertBOM_GX` 转换 `Bomline()`，再调用对应注入方法。 |

# BOM 生成重构方案 (最终版)

本方案将 [RW_Cbom.bas](../Src/RW_Cbom.bas)、`Cls_PDM` 和 `Cls_XLM` 的 BOM 数据流重构为基于结构体（Type）的模式，并将所有公共 Type 定义在 `A00_globalVar.bas`（historical, absent；当前类型定义见 [KCL.bas](../Src/KCL.bas)）中。同时废弃 `Cls_Para` 类。

## 核心变更点
1.  **数据中心化**: `A00_globalVar.bas`（historical, absent；当前类型定义见 [KCL.bas](../Src/KCL.bas)）承载 `BOMItem` 和 `ParamItem` 定义。
2.  **移除冗余**: 删除 `Cls_Para.cls`（historical, absent）。
3.  **类型安全**: `Cls_PDM` 产出 Type 数组，`Cls_XLM` 消费 Type 数组。

## 详细步骤

### 1. [修改] `A00_globalVar.bas`（historical, absent；当前类型定义见 [KCL.bas](../Src/KCL.bas)）
在文件头部添加全局 Type 定义：
```vb
Public Type BOMItem
    Level As Integer        ' 层级
    PartNumber As String    ' 件号
    Nomenclature As String  ' 英文名称
    Definition As String    ' 中文名称
    InstanceName As String  ' 实例名
    Quantity As Long        ' 数量
    Mass As Double          ' 单重
    Material As String      ' 材质
    Thickness As Double     ' 厚度 AB对应10
    Density As Double       ' 密度
    TotalMass As Double     ' 总重
    ' 预留扩展
    UserProp1 As String
    UserProp2 As String
End Type

Public Type ParamItem
    Name As String
    ParamType As String
    Value As Variant
    Target As Object    ' 指向 CATIA Parameter 对象
    Description As String
End Type
```

### 2. [删除] `Cls_Para.cls`（historical, absent）
该类功能已完全由 `ParamItem` 替代，直接从项目中移除。

### 3. [修改] [Cls_PDM.cls](../Src/Cls_PDM.cls)
- **替换 Cls_Para**: 将所有 `New Cls_Para` 的代码替换为 `Dim p As ParamItem`。
- **重构 infoPrd**:
    ```vb
    Public Function infoPrd(oPrd As Object) As BOMItem
        Dim item As BOMItem
        ' ... 赋值逻辑 ...
        infoPrd = item
    End Function
    ```
- **重构 ProduceBOM**: 返回 `BOMItem()` 数组。

### 4. [修改] [Cls_XLM.cls](../Src/Cls_XLM.cls)
- **新增 InjectBOM_Typed(data() As BOMItem)**:
    - 内部将 `BOMItem` 数组转换为二维 Variant 数组。
    - 一次性写入 Excel。
    - **列映射逻辑**: 在转换过程中，显式指定 `Arr(i, 3) = item.Nomenclature`。

### 5. [修改] [RW_Cbom.bas](../Src/RW_Cbom.bas)
- 协调调用 `pdm.ProduceBOM` 和 `xlm.InjectBOM_Typed`。

## 立即执行
如果确认无误，我将按照此方案开始编写代码：
1. 修改 `A00_globalVar.bas`（historical, absent；当前类型定义见 [KCL.bas](../Src/KCL.bas)）
2. 修改 [Cls_PDM.cls](../Src/Cls_PDM.cls)
3. 修改 [Cls_XLM.cls](../Src/Cls_XLM.cls)
4. 修改 [RW_Cbom.bas](../Src/RW_Cbom.bas)
5. 删除 `Cls_Para.cls`（historical, absent）

