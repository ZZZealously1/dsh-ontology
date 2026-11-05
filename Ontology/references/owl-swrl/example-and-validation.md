# 完整示例与验证

“核电备件管理”示例按原生文件组织，所有数据和阈值都是合成演示，不代表真实供应商关系或业务政策：

| 文件 | 内容 |
|---|---|
| [spare-model.owl](assets/spare-model.owl) | TBox；备件、战略备件、供应商、ABC 分类，2 对象属性、5 数据属性及域/值域 |
| [spare-owl-axioms.owl](assets/spare-owl-axioms.owl) | ABC 个体枚举的 OWL equivalentClass/oneOf 公理；与 model 联合加载 |
| [spare-facts.owl](assets/spare-facts.owl) | 独立 ABox；A/B/C 个体、合成供应商与主泵密封环，库存 10、安全库存 20、年消耗金额 1500000 |
| [spare-rules.swrl](assets/spare-rules.swrl) | 原 ABC-A 和补货预警，加原规则模式中的 B/C 分支；变量 IRI、RDF 列表与对象属性结论已纠正 |
| [owl-patterns.owl](assets/owl-patterns.owl) | [OWL 构造参考](owl-patterns.md)中的全部可解析片段，含类继承、不相交、个体/字面量枚举、hasValue/some/all/基数、关系特征、属性层次与实例；用于独立语法和 DL 检查，不是项目政策 |

## 明确加载范围

`spare-model.owl` 与 `spare-owl-axioms.owl` 分文件不是抛弃枚举语义。完整 OWL 检查必须联合加载两者和明确事实。`local-rules-v1` 不支持 oneOf/equivalentClass，只能在显式选择的基本模型与事实范围内执行比较规则；该检查**不证明一个完整 OWL DL + SWRL 联合后端已经实现**。若项目依赖枚举公理与规则互相触发的联合闭包，应选择并验证相应后端。

从 `Ontology/Ontology-tools/` 执行：

```powershell
python -B -X utf8 -m ontology_tools owl-dl `
  --ontology ../references/owl-swrl/assets/spare-model.owl `
  --ontology ../references/owl-swrl/assets/spare-owl-axioms.owl `
  --facts ../references/owl-swrl/assets/spare-facts.owl `
  --output ../../ontology-runs/spare-reference-dl-01
python -B -X utf8 -m ontology_tools owl-dl `
  --ontology ../references/owl-swrl/assets/owl-patterns.owl `
  --output ../../ontology-runs/owl-patterns-dl-01
```

规则后端的底层 Python API 可在上述明确子集上执行，不改写原生规则：

```python
from pathlib import Path
from rdflib import Graph
from ontology_tools.backend import infer

assets = Path('../references/owl-swrl/assets')
model = Graph().parse(assets/'spare-model.owl', format='xml')
rules = Graph().parse(assets/'spare-rules.swrl', format='xml')
facts = Graph().parse(assets/'spare-facts.owl', format='xml')
result = infer(model, rules, facts)
result.inferred.serialize('inferred.ttl', format='turtle')
result.trace.serialize('trace.ttl', format='turtle')
```

这段是 API 用法，不提供 CLI 的冻结快照、环境指纹与完整报告；需要可审计项目执行时按 [运行工具契约](../../Ontology-tools/README.md)制作并冻结部署包。不得把单次 API 调用当成项目全部验收。

## 独立预期

原示例事实应推出 `备件001 hasABCClass A类` 和 `备件001 hasReplenishmentNeed true`。验证还应包含：金额 1000000 为 B、100000 为 C、两阈值相邻值、缺失消耗金额不分类、库存等于安全库存不预警、缺失安全库存不自行补零。完整方法对缺失字段的处理与数据限制由项目来源决定，这些预期只检验该合成正向规则。

源例中的 EOQ 算术、评级 90 与 SC1→QA1 两个推导模式均保留在 [规则模式](swrl-patterns.md)，函数和参数见 [全部 37 项函数条目](builtins.md)。EOQ 未被伪装成当前后端已支持的执行规则。

[计算配置](../../Ontology-tools/CALCULATION.md)已提供二元四则，但没有开方函数，因此不能据此把 EOQ 的 `sqrt(40)` 声明为已支持。其实际可运行的多轮算术示例见 [calculation](../../Ontology-tools/examples/calculation/README.md)。
