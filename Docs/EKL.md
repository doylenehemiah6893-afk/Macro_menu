# EKL 语法手册（历史参考 / 待目标验证）

> **Status: REFERENCE / target-validation-required**
>
> 本页只作语法索引，不是可直接执行的 B28 脚本集。类型、方法、知识包、编辑器和许可证可用性必须在目标 CATIA V5-6R2018（R28/B28）环境中用 Language Browser 重新确认。

EKL 用于达索系统 CATIA V5、V6 和 3DEXPERIENCE 的知识工程、自动化和业务逻辑定制。达索 CATIA User Community 将其称为 Enterprise Knowledge Language，并明确说明它适用于 V5 与 V6/3DEXPERIENCE；具体版本中的名称、编辑器和可用对象仍以该目标环境的 Language Browser 为准。

**产品边界：** CATIA V5 中的对应产品是 Knowledge Advisor 2（KWA）；3DEXPERIENCE 中的对应应用包括 Engineering Rules Capture。两者的 EKL 概念相关，但 UI、对象模型、可用包和 Action 输入方式不应默认完全等同。KWA 不能预设属于 AB3/MD2/HD2 Core；相关功能暂按 `Optional-KWA candidate` 物理隔离，最终分类必须由三个基线 profile 和客户 R2018 DSLS 证据决定。

---

## 1. 基础语法

### 1.1 注释
注释是写给代码阅读者看的，不会被程序执行。
- **单行注释**：使用 `//`
- **多行注释**：使用 `/* 注释内容 */`

### 1.2 变量声明
在 EKL 中，变量必须先声明再使用。使用 `let` 关键字。
```ekl
let 变量名 (类型)
let i (Integer)    /* 声明一个整数变量 i */
let s (String)     /* 声明一个字符串变量 s */
let b (Boolean)    /* 声明一个布尔变量 b */
```

### 1.3 常用数据类型
- **Integer**: 整数 (如: 1, 100, -5)
- **Real**: 实数/浮点数 (如: 3.14, 0.5)
- **String**: 字符串 (用双引号括起来，如: "Hello CATIA")
- **Boolean**: 布尔值 (`true` 或 `false`)
- **List**: 列表 (可以存储多个对象的集合)
- **Feature**: 基础对象类型 (代表 CATIA 中的任何元素)

---

## 2. 运算符

### 2.1 算术运算
`+` (加), `-` (减), `*` (乘), `/` (除), `**` (乘方)

### 2.2 比较运算
`==` (等于), `<>` (不等于), `>` (大于), `<` (小于), `>=` (大于等于), `<=` (小于等于)

### 2.3 逻辑运算
- `NOT` : 非
- `AND` : 与
- `OR` : 或

---

## 3. 控制结构

### 3.1 条件判断 (If...Else)
```ekl
if (条件) 
{
    /* 条件为真时执行的代码 */
}
else if (其他条件)
{
    /* 其他条件为真时执行的代码 */
}
else
{
    /* 以上条件都不满足时执行的代码 */
}
```

### 3.2 循环结构 (For)
- **While 型循环**：
```ekl
let i (Integer)
i = 1
for i while i <= 10
{
    /* 重复执行的代码 */
}
```

- **集合遍历型循环**：
```ekl
let obj (Feature)
for obj inside 列表变量
{
    /* 遍历列表中的每一个元素 */
}
```

---

## 4. 常用函数与方法

### 4.1 消息弹窗
- `Message("内容")`: 弹出标准对话框。
- `Notify("内容")`: 在屏幕右上角显示静默通知。
- `Trace(级别, "消息")`: 在控制台输出调试信息。

### 4.2 字符串操作
- `s.Size()`: 获取字符串长度。
- `s.Extract(开始位置, 长度)`: 截取字符串。
- `ToString(变量)`: 将其他类型转换为字符串。

### 4.3 列表操作
- `list.Size()`: 获取列表元素个数。
- `list.GetItem(索引)`: 获取指定位置的元素 (注意：EKL 索引通常从 1 开始)。
- `list.Append(对象)`: 向列表末尾添加元素。

---

## 5. 核心对象操作 (A-EKL)

在 CATIA 中，我们经常需要获取对象的属性：
- **获取属性名列表**: `obj.ListAttributeNames("类型过滤", DynamicOnly)`
- **获取属性值**: `obj.GetAttributeReal("属性名")` 或 `obj.GetAttributeString("属性名")`

`DynamicOnly` 是布尔型的“仅动态属性”过滤开关，不是递归开关。`ListAttributeNames` 本身不递归；读取参数时需在其直接父 Parameter Set 上调用并在目标版本中核对类型过滤值。

---

## 6. 实战示例

### 示例 1：显示零件的所有属性清单
这个脚本会遍历当前选中对象的所有属性，并将它们拼接到一个字符串中最后通过弹窗显示出来。

在 Action Editor 的输入/参数区先定义一个占位输入，例如 `Target: Feature`；运行 Action 时再由用户选择真实对象。`Target` 不是仓库中某个固定 CATIA 对象名。

```ekl
/* 定义变量 */
let attrList (List)    /* 存储属性名的列表 */
let attrName (String)  /* 单个属性名 */
let i (Integer)        /* 循环计数器 */
let temp (String)      /* 用于拼接结果的字符串 */

/* Target 是 Action Editor 中声明的 Feature 输入 */
/* 获取该对象的所有字符串类型的属性名 */
attrList = Target -> ListAttributeNames("String", False)

temp = "找到的属性如下：\n"
i = 1

/* 遍历列表 */
for i while i <= attrList.Size()
{
	attrName = attrList.GetItem(i)
	Trace(2, "处理属性: " + attrName)
	temp = temp + " - " + attrName + "\n"
}

/* 最终弹窗显示 */
Message(temp)
```

---

## 7. 学习资源

- [Dassault Systèmes CATIA User Community：EKL 适用于 V5 与 V6/3DEXPERIENCE](https://3dswym.3dexperience.3ds.com/post/catia-user-community/best-practice-enterprise-knowledge-language-overview-and-usage-3dexperience-r2020x_mNJwwoHaQwuxzCNENxESmg)
- [Dassault Systèmes：CATIA Knowledge Advisor 2（KWA）产品边界](https://3dswym.3dexperience.3ds.com/wiki/catia-user-community/catia-knowledge-advisor-2-kwa_jKbzQs4hTpKtOxtpYIks5Q)
- [Dassault Systèmes：V5-6R2018 至 V5-6R2023 课程目录（Knowledge Advisor）](https://www.3ds.com/assets/edu/document/course-catalog-v5-6r2018-to-v5-6r2023.pdf)
- [3DEXPERIENCE 帮助文档镜像：Comments](https://help-3dexperience.aesvietnam.com/English/EKLRefMap/kwa-r-comments.htm)
- [3DEXPERIENCE 帮助文档镜像：`ListAttributeNames`](https://help-3dexperience.aesvietnam.com/English/EKLRefMap/eklkwa-r-StandardMethods.htm)
- [3DEXPERIENCE 帮助文档镜像：Creating an Action 及 Action 输入示例](https://help-3dexperience.aesvietnam.com/English/KwaUserMap/kwa-t-ActionFreatureUse.htm)
- [3DEXPERIENCE 帮助文档镜像：Engineering Rules Capture 应用边界](https://help-3dexperience.aesvietnam.com/English/KwaUserMap/kwa-c-ov.htm)

---
*提示：在编写 EKL 时，善用编辑器中的 "Language Browser" (语言浏览器)，它可以帮助你快速查找可用的函数和对象方法。*
