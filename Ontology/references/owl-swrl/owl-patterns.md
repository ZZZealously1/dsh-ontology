# OWL 构造、命名与实例

以下是独立片段，不是可直接组合为一个业务政策的模板；完整、声明齐全的资产在 [示例说明](example-and-validation.md)。Turtle 片段采用下列前缀，保存为 `.owl` 时真正序列化为 RDF/XML。`.owl` 不是语法名称，OWL/XML 与 RDF/XML 不同；本工具不把 OWL/XML 当 RDF/XML 读取。

## 1. 命名空间

```turtle
@prefix : <https://example.org/spare-parts#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix swrl: <http://www.w3.org/2003/11/swrl#> .
@prefix swrlb: <http://www.w3.org/2003/11/swrlb#> .
@prefix core: <https://example.org/business/core#> .
@prefix inv: <https://example.org/business/inventory#> .
@prefix sup: <https://example.org/business/supplier#> .
@prefix qual: <https://example.org/business/quality#> .
```

按项目真实领域设计稳定 IRI；这些 example.org 地址只是示例，不需联网读取。共享词汇、库存、供应商、质量可以分域，但领域不强制对应不同命名空间；命名方式不自动证明符合某标准。保留既有公开 IRI，改名需明确迁移映射。

## 2. 类、继承、不相交和枚举

```turtle
:备件 a owl:Class ; rdfs:label "备件"@zh ;
    rdfs:comment "用于设备维修更换的零部件"@zh .
:战略备件 a owl:Class ; rdfs:label "战略备件"@zh ;
    rdfs:comment "关键性、采购周期和价格的具体判定由项目来源给出"@zh ;
    rdfs:subClassOf :备件 .
:进口备件 a owl:Class .
:核级备件 a owl:Class .
:进口核级备件 a owl:Class ; rdfs:subClassOf :进口备件, :核级备件 .
:安全级备件 a owl:Class ; owl:disjointWith :非安全级备件 .
:非安全级备件 a owl:Class .
:A类备件 a owl:Class .
:B类备件 a owl:Class .
:C类备件 a owl:Class .
[] a owl:AllDisjointClasses ; owl:members ( :A类备件 :B类备件 :C类备件 ) .
```

多父类是两个 subclass 公理，不表示两个父类等价。不相交是逻辑断言，须有来源。

```turtle
# 个体枚举：owl:Class 的 oneOf 成员必须是个体。
:ABC分类 a owl:Class ; rdfs:label "ABC分类"@zh ;
    owl:equivalentClass [ a owl:Class ; owl:oneOf ( :A类 :B类 :C类 ) ] .
:A类 a owl:NamedIndividual, :ABC分类 ; rdfs:label "A类"@zh .
:B类 a owl:NamedIndividual, :ABC分类 ; rdfs:label "B类"@zh .
:C类 a owl:NamedIndividual, :ABC分类 ; rdfs:label "C类"@zh .
# 字面量枚举：使用数据范围，不把字符串塞进个体枚举。
:SafetyLevelCode a rdfs:Datatype ;
    owl:equivalentClass [ a rdfs:Datatype ; owl:oneOf ( "SC1" "SC2" "SC3" "非安全级" ) ] .
:hasSafetyClass a owl:DatatypeProperty ; rdfs:range :SafetyLevelCode .
```

枚举成员 IRI 不自动互异；若推理依赖互异性，使用有依据的 `owl:AllDifferent`。示例 A 类的“年消耗金额 > 100 万”仅为合成阈值，不能写入真实业务定义，且“类备件”与“分类代码个体”是不同概念。

## 3. hasValue、存在、全称与基数

```turtle
:供应商 a owl:Class .
:有效许可证 a owl:Class .
:hasRiskLevel a owl:DatatypeProperty ; rdfs:range xsd:string .
:hasLicense a owl:ObjectProperty .
:suppliedBy a owl:ObjectProperty .
:高风险供应商 a owl:Class ; owl:equivalentClass [ a owl:Class ;
    owl:intersectionOf ( :供应商
        [ a owl:Restriction ; owl:onProperty :hasRiskLevel ; owl:hasValue "高" ] ) ] .
:持有效许可证供应商 a owl:Class ; owl:equivalentClass [ a owl:Class ;
    owl:intersectionOf ( :供应商
        [ a owl:Restriction ; owl:onProperty :hasLicense ; owl:someValuesFrom :有效许可证 ] ) ] .
:合格供应商 a owl:Class ; owl:equivalentClass [ a owl:Class ;
    owl:intersectionOf ( :供应商
        [ a owl:Restriction ; owl:onProperty :hasLicense ; owl:allValuesFrom :有效许可证 ] ) ] .
:单一供应商备件 a owl:Class ; owl:equivalentClass [ a owl:Class ;
    owl:intersectionOf ( :备件
        [ a owl:Restriction ; owl:onProperty :suppliedBy ;
          owl:cardinality "1"^^xsd:nonNegativeInteger ] ) ] .
```

hasValue 限定具体值，someValuesFrom 要求存在某类值，二者不能互换。allValuesFrom 只约束已有/可能的值，不保证至少存在一张许可证；无许可证也不因该限制自动不合格。基数限制是 OWL 语义，不是数据库行数验证；需要必填与上限时用 SHACL，并注意 OWL 2 DL 非简单属性不能用于相应基数限制。资产不强行把“合格”替换为真实业务资格。

## 4. 对象属性及特征

```turtle
:suppliedBy a owl:ObjectProperty ; rdfs:label "供应商"@zh ;
    rdfs:comment "备件的供应来源"@zh ; rdfs:domain :备件 ; rdfs:range :供应商 .
:设备 a owl:Class .
:hasAncestor a owl:ObjectProperty, owl:TransitiveProperty ;
    rdfs:label "上级（允许跨层）"@zh ; rdfs:domain :设备 ; rdfs:range :设备 ;
    owl:inverseOf :hasDescendant .
:hasDescendant a owl:ObjectProperty .
:hasId a owl:ObjectProperty, owl:FunctionalProperty ; rdfs:label "标识对象"@zh .
:manages a owl:ObjectProperty, owl:AsymmetricProperty .
:isRelatedTo a owl:ObjectProperty, owl:SymmetricProperty .
```

只有跨层祖先/后代关系适合本例的传递性声明，命名应准确反映这一含义。若是直接父级，不加传递性。`hasId` 在这里连接标识对象；字符串编号另用数据属性。FunctionalProperty 是最多一个值，可能导致个体相等，不等于必填或拒绝第二条记录。domain/range 用于推导，不是输入过滤器。

## 5. 数据属性、数据范围与属性层次

```turtle
:hasPartName a owl:DatatypeProperty ; rdfs:label "部件名称"@zh ;
    rdfs:domain :备件 ; rdfs:range xsd:string .
:hasStockQuantity a owl:DatatypeProperty ; rdfs:label "库存数量"@zh ;
    rdfs:domain :备件 ; rdfs:range xsd:integer .
:hasAnnualDemand a owl:DatatypeProperty ; rdfs:label "年需求量"@zh ;
    rdfs:domain :备件 ; rdfs:range xsd:decimal ;
    rdfs:comment "原示例单位为件/年；正数约束需由项目确认并用数据范围或 SHACL 实现"@zh .
:hasStatus a owl:DatatypeProperty ; rdfs:label "状态"@zh ;
    rdfs:range [ a rdfs:Datatype ; owl:oneOf ( "正常" "预警" "缺货" ) ] .
:hasSupplier a owl:ObjectProperty ; rdfs:label "供应商"@zh .
:hasPrimarySupplier a owl:ObjectProperty ; rdfs:label "主供应商"@zh ; rdfs:subPropertyOf :hasSupplier .
:hasAlternateSupplier a owl:ObjectProperty ; rdfs:label "备用供应商"@zh ; rdfs:subPropertyOf :hasSupplier .
```

注释“必须为正”不产生任何约束。数据属性不能声明对象属性的传递、对称或逆属性特征；数值类型、量纲、单位和舍入从真实来源确定。

## 6. 实例与命名

```turtle
:hasPartNumber a owl:DatatypeProperty ; rdfs:range xsd:string .
:供应商A a owl:NamedIndividual, :供应商 ; rdfs:label "合成供应商 A"@zh .
:备件001 a owl:NamedIndividual, :备件 ; rdfs:label "主泵密封环（合成）"@zh ;
    :hasPartNumber "PN-001" ; :hasStockQuantity 10 ; :suppliedBy :供应商A .
# 无需稳定标识的匿名实体可用空白节点；不用于跨运行业务主键。
[] a :备件 .
```

| 对象 | 英文 IRI 约定 | 中文本地名或标签示例 |
|---|---|---|
| 实体类 | UpperCamelCase | 备件、供应商 |
| 角色类 | UpperCamelCase | 战略供应商、合格供应商 |
| 枚举类 | UpperCamelCase | ABC分类、安全等级 |
| 事件类 | UpperCamelCase + Event | 入库事件、审批事件 |
| 对象属性 | has + 名词，或动词 + 名词 | hasSupplier、hasPart、suppliedBy、manages |
| 数据属性 | lowerCamelCase；has + 名词可选 | hasPartName、hasQuantity |
| 布尔属性 | is + 形容词可选 | isActive、isValid |
| 具体实例 | 稳定业务前缀 + 编号 | 备件001、供应商A |
| 枚举值个体 | 稳定代码或名称 | A类、SC1级 |
| 匿名实例 | 空白节点 | `[ a :备件 ]` |
| 规则 | 稳定功能 ID | replenishment-alert |

类、属性、规则配 `rdfs:label` 与必要的 `rdfs:comment`，中文至少用 `@zh`，有准确译文再补 `@en`；实例至少提供可读标签。英文 UpperCamelCase 不适用于中文大小写，中文 IRI 与英文 IRI 均可选，项目内统一且不破坏已有身份。

| 数据类型 | XSD | Turtle 字面量示例 |
|---|---|---|
| 字符串 | xsd:string | `"文本"` |
| 整数 | xsd:integer | `100` |
| 小数 | xsd:decimal | `"3.14"^^xsd:decimal` |
| 日期 | xsd:date | `"2024-01-01"^^xsd:date`（RDF 可表达，OWL DL 及规则后端支持另验） |
| 布尔 | xsd:boolean | `true` / `false` |

不加 datatype 的 `"2024-01-01"` 只是字符串。格式合法、模型一致与业务数据真实是不同检查结果。
