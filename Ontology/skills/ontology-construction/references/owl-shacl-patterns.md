# OWL 与 SHACL 表达模式

以下例子说明语法和语义分工，使用虚构的资产与检查记录，不含任何真实业务政策。项目文件布局以[输出规范](../../../CONTRACT.md)为准。示例不是已完成的推理包，也不证明项目后端支持全部相关标准。

## 1. 最小本体结构

这个例子把资产与某一次检查分开，检查编号和发生时间属于检查记录，避免多次检查的值覆盖永久资产。IRI 和版本只是示例。

```turtle
@prefix ex: <https://example.org/demo#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .

<https://example.org/demo> a owl:Ontology ;
    owl:versionInfo "结构示例-1" ;
    dcterms:description "虚构的资产检查模型，仅说明文件结构"@zh .

ex:Asset a owl:Class ;
    rdfs:label "资产"@zh .
ex:Inspection a owl:Class ;
    rdfs:label "检查记录"@zh .

ex:assetId a owl:DatatypeProperty ;
    rdfs:label "资产编号"@zh ;
    rdfs:domain ex:Asset ;
    rdfs:range xsd:string .
ex:recordId a owl:DatatypeProperty ;
    rdfs:label "检查记录编号"@zh ;
    rdfs:domain ex:Inspection ;
    rdfs:range xsd:string .
ex:observedAt a owl:DatatypeProperty ;
    rdfs:label "检查发生时间"@zh ;
    rdfs:domain ex:Inspection ;
    rdfs:range xsd:dateTime .
ex:inspects a owl:ObjectProperty ;
    rdfs:label "检查对象"@zh ;
    rdfs:domain ex:Inspection ;
    rdfs:range ex:Asset .
```

`rdfs:domain ex:Inspection` 表示使用该属性的主语可被推为检查记录，不表示解析器会拒绝其他类型主语。业务输入的必填、值类型和关联目标需另设形状。

## 2. 为明确的数据契约建形状

仅为演示，假设这份虚构样例约定：每个资产有一个非空字符串编号；每次检查有一个非空编号、一个发生时间和一个资产对象。这里的“一个”来自样例契约，不是所有项目的通用要求。

```turtle
@prefix ex: <https://example.org/demo#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:AssetShape a sh:NodeShape ;
    sh:targetClass ex:Asset ;
    sh:property [
        sh:path ex:assetId ;
        sh:datatype xsd:string ;
        sh:minCount 1 ; sh:maxCount 1 ;
        sh:minLength 1
    ] .

ex:InspectionShape a sh:NodeShape ;
    sh:targetClass ex:Inspection ;
    sh:property [
        sh:path ex:recordId ;
        sh:datatype xsd:string ;
        sh:minCount 1 ; sh:maxCount 1 ;
        sh:minLength 1
    ] ;
    sh:property [
        sh:path ex:observedAt ;
        sh:datatype xsd:dateTime ;
        sh:minCount 1 ; sh:maxCount 1
    ] ;
    sh:property [
        sh:path ex:inspects ;
        sh:nodeKind sh:IRI ;
        sh:class ex:Asset ;
        sh:minCount 1 ; sh:maxCount 1
    ] .
```

`sh:minLength 1` 只排除空字符串，不检查是否全为空格；`sh:datatype xsd:dateTime` 本身也不强制值带时区。若项目要求去除空白或显式时区，应按字段契约补充实际支持的约束和反例。这个形状同样未检查全图编号唯一性。

## 3. 独立的事实图

```turtle
@prefix ex: <https://example.org/demo#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:asset-1 a ex:Asset ;
    ex:assetId "A-001" .

ex:record-1 a ex:Inspection ;
    ex:recordId "R-001" ;
    ex:observedAt "2026-01-01T09:00:00+08:00"^^xsd:dateTime ;
    ex:inspects ex:asset-1 .
```

这里只展示业务三元组，完整包仍需事实模式、来源与字段/关系证据。证据结构见[数据契约方法](../../business-ontology-design/references/data-contract.md)。不要以本例省略证据为理由省略项目证据。

适合本例的反例包括删除 `ex:recordId`、将日期写成普通字符串、把关系目标换成没有资产类型的节点、给记录添加第二个资产对象。使用两个不同 IRI 的检查记录却给出相同编号，则需要额外唯一性检查；以上形状不会自动阻止它。

## 4. 属性与关系模式的选择

| 需求 | 可考虑的表达 | 需要核对 |
|---|---|---|
| 一个对象到另一个对象 | 对象属性 | 方向、两端身份、时间范围 |
| 关系本身有金额/角色/时间 | 关联类或事件类 | 事件身份、参与者、生命周期 |
| 对象有多时点状态 | 状态记录或快照 | 当前值选择依据，不能任取最后一条 |
| 共享枚举且有额外语义 | 枚举个体及对象属性 | IRI 稳定、允许成员、是否完整 |
| 简单文字代码 | 数据属性加 `sh:in` | 代码映射、未知代码处理 |
| 同一对象的不同标识 | 经核验的身份映射 | 不能因名称相似就用 `owl:sameAs` |
| 同义术语或多语言标签 | 同一概念的标签/注释 | 先核对定义与作用域，不把同名当同义 |
| 文档内容同时由条文和图表表达 | 内容对象关联呈现对象 | 仅在需要查询文档知识结构时实体化，避免按版式制造业务子类 |

例子中的类与属性只用于解释模式。实际项目保留已批准的业务词汇，不强迫改成相同英文名。

为关系增加特征前先用具体对象检查蕴涵。例如，多名员工可以属于同一部门，因此把 `belongsTo` 一律设为逆函数属性可能导致这些员工被推为同一个体；“相关”也未必在双方业务方向上都成立。若需要双向查询但语义方向不同，可以定义有依据的逆属性，不能因界面需要双向连线便声明对称。

复用已有类/属性优先保留权威 IRI、定义、版本和本地依赖。扩展先检查是否可用子类、子属性或独立关联表达；独立维护且需避免标识碰撞时可设扩展命名空间，并保留对核心定义的引用。不是每新增一个属性都必须新建命名空间，也不能通过重新定义核心 IRI 隐藏语义变化。

## 5. OWL 与 SHACL 不能互相替代

| 现象 | OWL/RDFS 可能意味着什么 | 输入检查应做什么 |
|---|---|---|
| 使用具有 domain 的属性 | 主语获得该类型蕴涵 | 检查原始类型与允许对象范围 |
| 对象缺少某字段 | 开放世界下可能尚未知 | 按阶段契约决定是否必填 |
| 函数对象属性出现两个值 | 在相应条件下可能推出两值同一 | 如需两个显式值即违规，用基数检查 |
| 不同 IRI 编号相同 | 不自动等于数据库重复报错 | 按键与作用域执行唯一性检查 |
| 未推得类别成员关系 | 不能直接推出该对象不属于此类 | 输出未知或使用已声明的其他语义 |
| SHACL 没有违规 | 本次目标与约束满足 | 仍需检查目标覆盖、事实来源和实际推理 |

本体构建、集成或公理变更后，使用实际具备 OWL DL 能力的后端检查全局一致性与具名类可满足性，并记录版本、profile 与加载范围。本库提供独立 [owl-dl 检查器](../../../Ontology-tools/OWL-DL.md)，SWRL 单独验证。RDF 语法解析、简单规则物化和 SHACL 校验都不能冒称完整 OWL DL 一致性证明。

以下公理同样按实际含义及后端支持选用，不为“功能完整”强制全部加入：

| 表达 | 实际含义 | 需要避免的混用 |
|---|---|---|
| `owl:someValuesFrom` | 至少存在一个满足指定类或数据范围的取值 | 不等于某个指定的值；开放世界下不保证输入列出了该值 |
| `owl:allValuesFrom` | 对该属性的所有取值施加指定类型范围 | 不要求存在至少一个取值，不能代替必填 |
| `owl:hasValue` | 与某个指定个体或字面量具有关联 | 不是 `someValuesFrom` 的同名替代 |
| 类的 `owl:oneOf` | 类由列举的个体组成 | 不把字符串字面量当作类的个体列表 |
| 数据范围的 `owl:oneOf` | 数据范围由列举的字面量组成 | 按数据范围构造表达；若目标是输入枚举检查，可采用 `sh:in` |
| `owl:intersectionOf` / `owl:unionOf` | 类表达式的交集或并集，成员通过 RDF 列表给出 | 多个独立 domain 声明是交集效果，不能用它表达任一类型即可 |
| `owl:complementOf` | 相对于对象域的逻辑补类 | 缺少某个类型断言并不使对象自动进入该类的补类 |
| `owl:minCardinality` / `owl:maxCardinality` / `owl:cardinality` | 限制类中该属性取值的最小、最大或精确数量 | 计数服从逻辑身份语义；未列出值可能仍满足存在性，不等于显式输入字段计数 |
| 限定基数 | 用 `owl:minQualifiedCardinality`、`owl:maxQualifiedCardinality` 或 `owl:qualifiedCardinality`，配合 `owl:onClass` 或 `owl:onDataRange` 限定所计取值 | 检查后端支持；不能遗漏限定类型，或把所有值的数量与限定类型的数量混用 |
| `owl:hasKey` | 在所属类及键语义适用范围内，根据共同键值推导个体同一性 | 不自动检查缺键、重复行或跨系统身份；输入唯一性另按数据契约校验 |

限制类使用 `owl:Restriction` 与 `owl:onProperty` 指定属性，再添加对应量化或基数条件；限制是否作为必要条件或完整定义，分别由 `rdfs:subClassOf` 或适用的等价类公理表达。基数字面量使用非负整数；枚举、交并集和键列表保持 RDF 列表结构完整。类表达式不是普通数据值，不能将其写成看似公式的字符串。

例如“父亲”通常指直接父子关系；把 `hasParent` 声明为传递关系会把祖父母也推成直接父母。只有业务定义本来表达所有祖先时才采用相应传递关系；文件中的关系名和示例公理都需核对实际业务含义。

## 6. 模块、规则与加载

跨领域拆分应由真实复用和维护边界驱动。若采用 `owl:imports`，把依赖固定为包内文件并记录本地解析映射；只出现导入 IRI 不表示所需内容已经加载。禁止未经授权在构建或运行时连接外部系统获取依赖。

SWRL 使用真实 `swrl:Imp`、body/head 列表和原子，新包 `rules/<domain>/<domain>_rules.swrl` 固定为 RDF/XML。本文Turtle片段用于说明OWL/SHACL语义；领域 `.owl` 文件按[输出规范](../../../CONTRACT.md)序列化为RDF/XML。规则语义与变量约束参见[规则设计与实现](../../ontology-inference-design/SKILL.md)。不要将演示中的 Turtle 代码块改名为 `.swrl` 后声称符合项目序列化约定。

RDF/XML 与 OWL/XML 是不同序列化，不能混称为“OWL/XML（RDF/XML语法）”。读取已有文件先识别实际格式；转换时用所支持的解析器，并以图同构或适合该表达的语义核对验证结果，不以 `.owl` 后缀判定格式。

本目录不指定固定加载命令、退出码或某个库。项目应通过所选后端验证加载组合、推理与校验顺序，并将实际命令写入项目的 `ontology/README.md`。
