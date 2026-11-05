# 合成 RAG 建模示例

本例用于验证原生构建、规则执行与OWL DL检查，不对应真实业务。术语命名空间为 `https://example.org/rag-starter#`。

`rule_vocabulary.owl` 定义文档、组织、分类、组件、服务器等 7 个具名类，4 个对象属性和 3 个数据属性；两个文档标记类由原生 SWRL 导出。`constraints.owl` 保存文档键、文档/组织互斥、安全级别枚举、至少一个所属组织、存在所属组织、函数属性及跨组件/服务器的并集定义域。词汇层的 inverseOf 与 TransitiveProperty 也保留。完整两模块必须联合检查。

| 规则 | 类别 | 含义 | 独立预期 |
|---|---|---|---|
| R01 | 分类 | Document 且 securityLevel 为“敏感”→RestrictedDocument | 敏感命中，公开不命中；缺值/越界由 SHACL 停止 |
| R02 | 分类 | Document 且 pageCount ≥ **10**→LargeDocument | 11/10 命中，9/0 不命中；10 为合成边界 |

阈值 **10** 仅为测试常量，不源于业务制度。`tests/cases.ttl` 保存四个合法与两个非法输入的独立预期；真实规则由 `rules/starter/starter_rules.swrl` 读取，不在 Python 中重写。

三个本地 SPARQL 查询在 `queries/`：敏感文档、分类祖先、测试阈值。查询默认不启动推理，若需要已推导标记应显式选择 `closure.ttl`。Python 实际调用示例：

```python
from pathlib import Path
from ontology_tools import run_cases, infer_graph, check_consistency

run_cases(Path("rule-package"), Path("runs/golden-01"))
infer_graph(Path("rule-package"), output=Path("runs/infer-01"))
check_consistency(
    [Path("ontology/subontologies/rule_vocabulary.owl"),
     Path("ontology/subontologies/constraints.owl")],
    Path("runs/owl-01"), facts=Path("ontology/data/instances_starter.owl"))
```

本例的规则测试作用域与完整 OWL DL 是分开执行的验证，不是全 OWL DL+SWRL 联合推理的等价证明。完整两模块直接给 `local-rules-v1` 会因不支持的复杂公理而失败。来源为本模板的明确合成设计；验收须保存本次实际运行报告，不暗示真实项目已完成。
