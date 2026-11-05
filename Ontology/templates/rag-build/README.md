# RAG 建模可运行模板

提供通用构建/测试脚本、原生模型和知识库说明补充。仅依赖本 `Ontology/` 中的工具与本地Python/Java；不调用知识库、不下载依赖、不生成JSON。

新项目使用 `models/starter/ontology/` 合成示例，修改原生模型、规则、事实与独立案例；示例阈值不代表业务制度。

采用[结构化公式配置](../../Ontology-tools/FORMULA.md)的项目可另设 `formulas/<domain>.ttl` 和 `FormulaCatalog` 静态角色，RDF表达树为唯一公式执行源。示例加载清单仅给扩展注释；现有构建/适配脚本未因此新增角色支持，项目须明确扩展实际实现，分别验证到扁平 `formulas.ttl` 的图等价、全部激活公式的独立算例和公式证据重放。原演示规则与旧profile行为保持原合同。

| 路径 | 用途 |
|---|---|
| `scripts/rdf_authoring.py` | 初次著录的无政策RDF辅助函数，含类、属性、实例、列表与复杂OWL构造 |
| `scripts/build_ontology.py` | 从原生源及本地加载清单构建新目录，或只读检查现有生成物 |
| `scripts/prepare_rule_tests.py` | 按明确测试范围转换完整词汇模块、原样复制规则并保存图同构证据 |
| `tests/test_native_template.py` | 构建保真、源保护、原生规则黄金案例、固定点、真实OWL DL及不支持语义的失败检查 |
| [说明补充](docs/doc_outline.md) | 在完整领域说明模板上增加检索证据、覆盖与查询示例 |
| [验证与故障处理](docs/validation.md) | 构建与规则测试的语义范围、验证要求和常见故障处理 |

## 合成示例的构建与执行

工作目录为 `Ontology/templates/rag-build/`；`python`须已安装工具锁定的RDFLib/pySHACL等依赖，Java经 `java` 可用。输出存 `Ontology/` 外，目标目录不得已存在。

```powershell
python -B -X utf8 scripts/build_ontology.py --source models/starter/ontology --output ../../../ontology-runs/rag-starter-01/ontology
python -B -X utf8 scripts/build_ontology.py --source models/starter/ontology --output ../../../ontology-runs/rag-starter-01/ontology --check
python -B -X utf8 scripts/prepare_rule_tests.py --source models/starter/ontology --output ../../../ontology-runs/rag-rule-package-01
$env:RAG_BUILD_TEST_OUTPUT = (Resolve-Path ../../../ontology-runs).Path
python -B -X utf8 -m unittest discover -s tests -v
```

从 `Ontology/Ontology-tools/` 执行：

```powershell
python -B -X utf8 -m ontology_tools owl-dl `
  --ontology ../templates/rag-build/models/starter/ontology/subontologies/rule_vocabulary.owl `
  --ontology ../templates/rag-build/models/starter/ontology/subontologies/constraints.owl `
  --facts ../templates/rag-build/models/starter/ontology/data/instances_starter.owl `
  --output ../../ontology-runs/rag-owl-01
python -B -X utf8 -m ontology_tools test --package ../../ontology-runs/rag-rule-package-01 --output ../../ontology-runs/rag-golden-01
python -B -X utf8 -m ontology_tools infer --package ../../ontology-runs/rag-rule-package-01 --output ../../ontology-runs/rag-infer-01
```

`build --check`核对快照字节与集成图同构，不执行推理。构建器保留旧版本，不覆盖现有目录或反向重置原生源。完整TBox用OWL DL检查，受限规则包用 `local-rules-v1` 执行；保存实际报告、结果、闭包、轨迹和指纹，两类后端结果不能互相替代。项目验收应以本次实际运行证据为准，不能用合成示例通过代替业务验收。
