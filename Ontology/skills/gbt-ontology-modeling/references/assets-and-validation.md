# 原生资产、候选约束与使用方法

| 资产 | 完整用途与加载要求 |
|---|---|
| [standard-model.owl](../assets/standard-model.owl) | RDF/XML；82 个目录概念，加日期异常辅助类；34 项对象属性；19 项分域数据属性，加废止日期辅助属性。顶层目录不强制继承 StandardEntity，待核验的 NormativeReferences 父类不激活。 |
| [standard-candidate-axioms.owl](../assets/standard-candidate-axioms.owl) | 不相交、hasKey、issuedBy 功能性、无标题条零子条限制。仅为合成候选，用时须与 model 同时显式加载；无 imports，不联网。 |
| [standard-date-rules.swrl](../assets/standard-date-rules.swrl) | 日期先后错误的类型推导，采用真实 SWRL RDF 原子/变量/列表。此合成模板输入日期明确为 ISO 日期字符串；原日期类型、时区和语义不能被默认替换。 |
| [standard-candidate-shapes.ttl](../assets/standard-candidate-shapes.ttl) | 必填/单值标识、日期字符串与顺序、状态/语言/约束类型/条款类型枚举、发布机构上限、无标题条、跨节点重复标识和废止替代检查。含 SHACL-SPARQL，须明确选择支持它的引擎。 |

这些是可检查的参考资产，不是已获批准的项目约束。候选文件不由加载机制自动启用；不要把它们混入本体集成后靠 `draft` 注释试图禁用。正式标准条款尚待核验，必须逐项选择/确认并记录。

## 专门规则的适配

- 参考属性表使用 `xsd:date`；本合成资产以 `xsd:string` 承载固定格式 `YYYY-MM-DD`，使示例在当前 OWL DL 与规则后端有明确数据域。此选择不允许自动改写既有日期字段。SHACL 正则仅检查词法形状，日历有效性（如闰年/月份天数）仍需经验证的日期解析；跨时区时间不能按此字符串模型直接比较。
- `owl:hasKey` 可能推导身份相等；SHACL-SPARQL 查出不同 RDF 节点共享 ID 后，仍需判断别名还是重复记录，不能自动删除。标准编号功能性/单值由 SHACL `maxCount` 表达，不用对象属性反功能性错误套在字符串编号上。
- `issuedBy` “只能一个发布机构”缺乏正式条款证据，作为显式候选保留；允许联合发布的项目不要加载该功能性和上限约束。
- 源 `replaces` 方向为“新版 → 旧版”。因此废止旧标准的替代检查使用入边 `?new replaces $this`，或旧标准的 `abolishedDate`，不会用反方向误判。
- 章可有零个或多个条，不加虚构的最少一个约束。无标题条不含子条保留为候选 `maxCardinality 0` 与 SHACL `maxCount 0`。
- 标准间引用（cites/references）与条款引用（citesStandard/referencesClause）保留不同属性；属性表中所有关系方向、原中文用途均保留。
- 扩展案例保留电力 `power:`、核电 `nuclear:` 与共享 `core:` 的命名空间用途。新项目可选择稳定扩展命名空间，但命名空间本身不证明兼容性，扩展须对照实际核心版本与回归。

## 运行

从 `Ontology/Ontology-tools/` 运行；输出目录放包外且尚不存在：

```powershell
python -B -X utf8 -m ontology_tools owl-dl `
  --ontology ../skills/gbt-ontology-modeling/assets/standard-model.owl `
  --ontology ../skills/gbt-ontology-modeling/assets/standard-candidate-axioms.owl `
  --output ../../ontology-runs/standard-reference-dl-01
```

这是对明确启用候选的合成检查；真实项目先确认其适用性。SWRL 文件不能传给 `owl-dl`。

当前 `ontology_tools validate` 的 Core profile 拒绝 `sh:sparql`，不能用它直接执行候选形状。选择本机已安装并支持 SHACL-SPARQL 的 pySHACL API，传入本地数据图、形状图和 TBox；例如：

```python
from rdflib import Graph
from pyshacl import validate

data = Graph().parse('facts.owl', format='xml')
model = Graph().parse('standard-model.owl', format='xml')
shapes = Graph().parse('standard-candidate-shapes.ttl', format='turtle')
conforms, report_graph, report_text = validate(
    data, shacl_graph=shapes, ont_graph=model,
    inference='rdfs', advanced=False, do_owl_imports=False,
)
report_graph.serialize('shacl-report.ttl', format='turtle')
print(conforms, report_text)
```

路径替换为所选项目的本地文件；此调用不会连接业务系统。独立黄金案例应覆盖日期顺序、同日、缺值、无效日历、重复标识、联合发布、枚举越界、废止无替代、无标题条有子条及边界适用性。测试期望来自所选来源，不能只把推理结果存成预期。

实际验证记录放在项目验收报告中；RDF 可解析、SHACL 通过、OWL DL 一致和业务标准符合性分别报告，不能互相替代。
