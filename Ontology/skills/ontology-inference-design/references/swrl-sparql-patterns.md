# SWRL 与 SPARQL 表达参考

示例用于设计审查，未附执行后端，未在此声明运行通过。正式文件遵循 [输出规范](../../../CONTRACT.md)：领域模型、实例 `.owl` 和 `.swrl` 使用 RDF/XML，`.ttl` 使用 Turtle；Turtle片段用于解释语义，不代表必须使用旧扁平布局。RDF/XML 与 OWL/XML 是不同序列化；RDFLib 的 `format="xml"` 解析的是 RDF/XML。所有业务来源和测试须在项目中补齐，设计与回译方法见[规则设计与测试](rule-design-and-tests.md)。

## SWRL 原生结构

下例表示“同一快照中的库存小于安全库存时，推导需复核标记”。两个数值都从事实绑定，没有硬编码业务阈值。`example.org` 和 `urn:example:` 仅为演示命名空间，演示来源不构成真实业务依据。相关类、属性、类型、单位、时点和身份应在本体与 SHACL 中定义。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:swrl="http://www.w3.org/2003/11/swrl#"
  xmlns:dct="http://purl.org/dc/terms/"
  xmlns:meta="urn:example:metadata:">
  <swrl:Variable rdf:about="urn:example:var:snapshot"/>
  <swrl:Variable rdf:about="urn:example:var:stock"/>
  <swrl:Variable rdf:about="urn:example:var:safety"/>
  <swrl:Imp rdf:about="urn:example:rule:stock-review">
    <dct:source rdf:resource="urn:example:source:demonstration"/>
    <meta:status>draft</meta:status>
    <swrl:body rdf:parseType="Collection">
      <swrl:ClassAtom>
        <swrl:classPredicate rdf:resource="https://example.org/inventory#Snapshot"/>
        <swrl:argument1 rdf:resource="urn:example:var:snapshot"/>
      </swrl:ClassAtom>
      <swrl:DatavaluedPropertyAtom>
        <swrl:propertyPredicate rdf:resource="https://example.org/inventory#stock"/>
        <swrl:argument1 rdf:resource="urn:example:var:snapshot"/>
        <swrl:argument2 rdf:resource="urn:example:var:stock"/>
      </swrl:DatavaluedPropertyAtom>
      <swrl:DatavaluedPropertyAtom>
        <swrl:propertyPredicate rdf:resource="https://example.org/inventory#safetyStock"/>
        <swrl:argument1 rdf:resource="urn:example:var:snapshot"/>
        <swrl:argument2 rdf:resource="urn:example:var:safety"/>
      </swrl:DatavaluedPropertyAtom>
      <swrl:BuiltinAtom>
        <swrl:builtin rdf:resource="http://www.w3.org/2003/11/swrlb#lessThan"/>
        <swrl:arguments rdf:parseType="Collection">
          <rdf:Description rdf:about="urn:example:var:stock"/>
          <rdf:Description rdf:about="urn:example:var:safety"/>
        </swrl:arguments>
      </swrl:BuiltinAtom>
    </swrl:body>
    <swrl:head rdf:parseType="Collection">
      <swrl:DatavaluedPropertyAtom>
        <swrl:propertyPredicate rdf:resource="https://example.org/inventory#needsReview"/>
        <swrl:argument1 rdf:resource="urn:example:var:snapshot"/>
        <swrl:argument2 rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</swrl:argument2>
      </swrl:DatavaluedPropertyAtom>
    </swrl:head>
  </swrl:Imp>
</rdf:RDF>
```

解析出 `swrl:Imp` 只证明结构可读。必须另用案例证明 body 匹配、内建比较和 head 推导都被实际后端执行；不支持此结构的决策专用执行器不能宣称已支持本例。

### 原子、谓词和变量必须一致

| 原子类型 | 结构与参数 | 容易混淆的地方 |
|---|---|---|
| `swrl:ClassAtom` | `classPredicate` 指向类，`argument1` 为个体或变量 | 类型推导与设置字符串分类代码不同 |
| `swrl:IndividualPropertyAtom` | `propertyPredicate` 指向对象属性，两个参数绑定个体 | RDF 表示不用 `swrl:ObjectPropertyAtom` 或泛化的 `swrl:PropertyAtom`；对象参数不能填代码字符串 |
| `swrl:DatavaluedPropertyAtom` | `propertyPredicate` 指向数据属性，第二参数为字面量或数据变量 | 声明为对象属性的分类关系不能用数据原子输出 `"A"` |
| `swrl:BuiltinAtom` | `builtin` 为精确函数 IRI，`arguments` 为 RDF 列表 | 核对参数数量、顺序、输入/输出绑定及类型；名称看似相同不证明同一函数 |

变量在 RDF 文件中是声明为 `swrl:Variable` 的资源，由原子引用同一 IRI；不要在 Turtle 数据中直接使用 SPARQL 的 `?x`。函数式 `Class(?x) ∧ property(?x, ?v) → Result(?x)` 可作为阅读视图，代码块应标为 `text`，不能称作可解析 Turtle。`swrlx:buildURI(...)` 等扩展也不能代替上述 RDF 结构。其他原子和扩展按实际后端支持范围使用，表内类型并不代表完整 SWRL 能力清单。

校验不仅查到 body/head 属性，还须遍历 RDF 列表、检查终止节点、原子结构、谓词声明及变量作用域；结合模型核对对象属性/数据属性混用。规则标签和注释用于中文可读性，IRI 使用项目已约定的稳定命名方式，不因显示名称变化重建身份。

## 内建和变量审查

比较可涉及 `swrlb:equal`、`notEqual`、`lessThan`、`lessThanOrEqual`、`greaterThan`、`greaterThanOrEqual`，但所选引擎是否支持、支持哪些数据类型仍需能力探针。`notEqual` 比较两个已知值，不表示“没有这个字段”。

算术、字符串、日期和舍入函数不在此提供通用可用清单。项目须核对后端文档中的精确 IRI、参数方向、类型、异常行为和能力测试，不根据名称猜测；也不能把某个 `round` 的数值行为直接解释为项目财务舍入制度。

本库的实际计算子集见 [hermit-swrl-calculation-v1](../../../Ontology-tools/CALCULATION.md)：四则用 `swrlb:`，显式舍入、秒差和秒偏移用工具自己的 `otfn:` 命名空间。输出参数在前，输入必须可绑定；已绑定输出是同值检查。无业务依据的舍入模式、金额位数或时区不能代填；带时区时间交给后端前的 UTC 规范化是留证适配，不能混同原始输入。

不能把参考资料中的 `sqrt`、`length`、`concat`、`year`、`addDays`、布尔或列表运算名称统一加上 `swrlb:` 就宣称为标准且可执行。标准词汇、引擎扩展和应用函数分别登记；每个实际使用的函数至少有成功与异常输入的能力证据。`xsd:decimal` 也不保证后端内部始终采用精确十进制，尤其涉及除法、开方和舍入时需验证实际数值行为。

head 变量需要由 body 约束。计算内建可能绑定输出变量，其可用性、绑定方向与求值条件属于具体后端能力；body 顺序不构成通用的过程控制语义。若引擎要求固定顺序，在 profile 中声明并以正反例验证。

## SPARQL 查询图与查询目的

查询前记录所用原始图、推导图及其指纹，并说明是否取并集或命名图。只把原始文件重新载入查询器，无法读取另一个进程内未保存的推导结果。

```sparql
PREFIX inv: <https://example.org/inventory#>
SELECT DISTINCT ?snapshot ?item
WHERE {
  ?snapshot a inv:Snapshot ;
            inv:forItem ?item ;
            inv:needsReview true .
}
ORDER BY ?snapshot ?item
```

该查询只是读取指定图中已有的断言。图中没有该标记可能表示未推理、条件不成立、缺数据或后端不支持，不能自动解释成“无需复核”。

| 路径 | 含义 | 审查点 |
|---|---|---|
| `inv:forItem/inv:suppliedBy` | 顺序两跳 | 中间对象类型和关系方向 |
| `inv:partOf+` | 一跳或多跳 | 环、重复和业务允许的范围 |
| `inv:partOf*` | 零跳或多跳 | 会包含节点本身是否合意 |
| `^inv:suppliedBy` | 反向遍历 | 查询反向，不等于新增 OWL 逆属性公理 |
| `(inv:parentA\|inv:parentB)+` | 两种关系的可达路径 | 可混用两种关系，不要求轮流交替 |

属性路径回答可达性，不自动给出每一条边的完整证明路径。需要解释链时另查边及其证据，并核对最终对象。

## 缺失、聚合和结果输出

`OPTIONAL` 可暴露缺字段；`FILTER NOT EXISTS` 判断指定图中没有匹配模式，不证明现实中不存在。使用业务否定需要已声明的完整性范围。

`COUNT(DISTINCT ?object)` 可避免某些连接重复，但不代替业务去重键、分页完整性或时间过滤。聚合前先验证集合和口径，报告中保留过滤条件及未覆盖范围。展示截断和实际查询完整性分开：限制界面展示的行数不能悄悄限制正式验收集合。

查询建议只读，按项目实际支持选择 SELECT / ASK / CONSTRUCT。SELECT 结果可交付 TSV、CSV 或 Markdown，图结果为 Turtle，ASK 结果可记录在 RDF 执行报告。不要输出 JSON。涉及远程 `SERVICE`、数据加载、UPDATE 或数据库写入时，按用户授权另行处理，不能从“查询本体”推定已获授权。
