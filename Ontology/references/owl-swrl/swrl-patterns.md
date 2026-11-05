# 原生 SWRL 与规则模式

## RDF 结构

前缀沿用 [OWL 构造](owl-patterns.md)。以下是可解析 Turtle 片段：变量是 IRI `:x`、`:c`，并声明为 `swrl:Variable`；小括号是真实 RDF collection。body 是合取前提，head 是合取结论。普通规则中不使用字符串 `"?x"`、SPARQL 变量 `?x` 或 `swrlx:buildURI` 伪造原子。

```turtle
:x a swrl:Variable .
:c a swrl:Variable .
:abcClassificationA a swrl:Imp ;
    rdfs:label "ABC 分类 A（合成）"@zh ;
    rdfs:comment "演示原生语法；阈值不是用户项目业务规则"@zh ;
    swrl:body (
        [ a swrl:ClassAtom ; swrl:classPredicate :备件 ; swrl:argument1 :x ]
        [ a swrl:DatavaluedPropertyAtom ; swrl:propertyPredicate :hasAnnualConsumption ;
          swrl:argument1 :x ; swrl:argument2 :c ]
        [ a swrl:BuiltinAtom ; swrl:builtin swrlb:greaterThan ; swrl:arguments ( :c 1000000 ) ]
    ) ;
    swrl:head (
        [ a swrl:IndividualPropertyAtom ; swrl:propertyPredicate :hasABCClass ;
          swrl:argument1 :x ; swrl:argument2 :A类 ]
    ) .
```

`:hasABCClass` 是对象属性，所以结论是 `IndividualPropertyAtom` 与枚举个体 `:A类`；不能使用 `DatavaluedPropertyAtom` 输出字符串 `"A"`。若项目选择代码字符串表示，则应另行选择数据属性并统一 TBox 与规则，而不是混用。

## 原子类型

| 原子 | RDF 必要字段 | 含义与本地支持 |
|---|---|---|
| `swrl:ClassAtom` | classPredicate、argument1 | 类型前提/结论；本地规则器支持具名类 |
| `swrl:IndividualPropertyAtom` | propertyPredicate、argument1、argument2 | 对象属性；本地支持 |
| `swrl:DatavaluedPropertyAtom` | propertyPredicate、argument1、argument2 | 数据属性；本地支持 |
| `swrl:BuiltinAtom` | builtin、arguments（RDF 列表） | 仅 6 个比较内置可在本地 body 使用 |
| `swrl:DataRangeAtom` | dataRange、argument1 | 补充标准原子；当前本地不支持 |
| `swrl:SameIndividualAtom` | argument1、argument2 | 个体相等；当前本地不支持 |
| `swrl:DifferentIndividualsAtom` | argument1、argument2 | 个体不同；当前本地不支持 |

表中前四种原子是常见构造，后三类补充相等、互异和数据范围表达；当前工具遇到不支持语义应拒绝，不转换成自然语言后声称执行。

## 推导、计算、预警与分类模式

以下 `text` 块是人类可读的规则记法，**不是 Turtle 或可直接交给后端的文件**。完整可执行的比较分类/预警例子在 [规则资产](assets/spare-rules.swrl)。`Supplier` 等英文名与中文概念的对应必须明确，不能混入未经声明的第二套词汇。

```text
# 条件推导属性：示例 SC1 → QA1，仅为合成映射。
SparePart(?x) ∧ hasSafetyClass(?x, "SC1") → hasQALevel(?x, "QA1")
# 条件推导类型：90 是合成示例值，不是客户政策。
Supplier(?x) ∧ hasRating(?x, ?r) ∧ greaterThan(?r, 90) → StrategicSupplier(?x)
```

```text
# EOQ 示例意图：sqrt(2 × 年需求量 × 单次订货成本 / 单位持有成本)
SparePart(?x) ∧ hasAnnualDemand(?x, ?d) ∧ hasOrderCost(?x, ?s)
∧ hasHoldingCost(?x, ?h) ∧ multiply(?ds, ?d, ?s)
∧ multiply(?ds2, 2, ?ds) ∧ divide(?ds2h, ?ds2, ?h)
∧ sqrt(?eoq, ?ds2h) → hasEOQ(?x, ?eoq)
```

EOQ 全部前提、中间变量和输出用途保留；它不是当前运行器可执行规则，尤其 `sqrt` IRI 和赋值型 built-in 能力待所选后端核验。确认单位周期一致、持有成本大于零、数值精度与舍入，覆盖缺值、除零和负数反例后才能执行。不要将其另写成 Python 业务函数来冒充 SWRL 执行。

```text
# 库存预警；不能把缺失 safetyStock 当零。
SparePart(?x) ∧ hasStockQuantity(?x, ?qty) ∧ hasSafetyStock(?x, ?ss)
∧ lessThan(?qty, ?ss) → hasReplenishmentNeed(?x, true)

# ABC 分类；A/B/C 是枚举个体（以下为示意）。
SparePart(?x) ∧ hasAnnualConsumption(?x, ?c) ∧ greaterThan(?c, 1000000)
→ hasABCClass(?x, A)
SparePart(?x) ∧ hasAnnualConsumption(?x, ?c) ∧ lessThanOrEqual(?c, 1000000)
∧ greaterThan(?c, 100000) → hasABCClass(?x, B)
SparePart(?x) ∧ hasAnnualConsumption(?x, ?c) ∧ lessThanOrEqual(?c, 100000)
→ hasABCClass(?x, C)
```

1000000、100000 的边界及全分支见合成规则资产；真实项目只有在明确来源支持时才采用。SWRL 正向推导不等于触发补货、审批或其他外部动作。多值、负值、单位缺失应由项目输入约束决定，不默默补政策。`rdfs:comment "draft"` 不会禁用规则；未获确认的候选规则必须排除在实际加载图外。

## 执行边界

- [完整函数表](builtins.md)列出函数意图、候选写法及待核验点。`local-rules-v1` 是有限正向具名项规则器，不是完整 OWL DL + SWRL 推理器。
- [OWL DL 检查器](../../Ontology-tools/OWL-DL.md)分别检查无 SWRL 的模型/事实，不能将其成功作为规则执行成功。
- 不使用 OWL 的开放世界语义推断缺失字段为 false。SWRL 不提供任意非单调否定、规则优先级或业务动作授权；这些需求需要明确建模与实际后端支持。
- body/head、arguments 的列表必须完整无环，变量应有合法绑定；规则依据、输入和独立预期均要留下证据。
