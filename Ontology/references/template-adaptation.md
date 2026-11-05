# 模板与实现约定

模板为项目提供文档和原生文件的起点，流程与语义要求由[建模规范](modeling-principles.md)和[总入口](../skills/ontology-builder/SKILL.md)规定。所有模板位于[本库templates](../templates/README.md)，复制本文件夹即可获取所需方法与示例。

## 从模板生成项目

1. 明确项目路径；指定路径已经是 `ontology/` 时直接作为包根，避免重复嵌套。
2. 按选定流程形成来源、概念、属性和规则设计，再复制需要的原生结构与文档模板。小项目只建实际需要的模块，不生成空目录冒充能力。
3. 替换示例IRI、领域名、合成事实、来源和规则，保留原生OWL/SWRL/SHACL表达；输入资料可为文档或表格，不生成JSON中间文件。
4. 维护领域模型、规则和独立ABox，生成集成入口与加载清单；说明TBox、规则、事实分别如何被实际后端读取。
5. 补齐真实后端、依赖和命令，执行校验、独立案例与集成验证。完整说明所有类、属性、规则和使用方式，实际通过后冻结版本。

## 源文件与生成结果

| 文件 | 约定 |
|---|---|
| `subontologies/<domain>_ontology.owl` | 每域完整TBox，集中类、属性与公理 |
| `rules/<domain>/<domain>_rules.swrl` | 原生规则、稳定ID、来源、适用范围及依赖 |
| `data/instances_<domain>.owl` | 独立ABox，标明快照范围与provided/synthetic来源 |
| `integration/merged_ontology.owl` | 默认由模型与规则源生成物化集成；动态ABox另行加载 |
| `integration/load-plan.ttl` | 模块角色、路径、格式、版本、依赖与本地加载方式 |
| `docs/<domain>_本体说明.md` | 模型的完整阅读视图，随源文件更新 |

导入入口与物化集成分别声明和检查，文件名不证明完整加载。采用 `owl:imports` 时固定本地IRI映射并核对离线闭包；集成构建比较声明范围的图同构，转换语义时另做等价回归，不以三元组数量相近认定保真。

`.owl` 与 `.swrl` 使用RDF/XML，`.ttl`使用Turtle。RDF/XML与OWL/XML是不同序列化，不能混称；文本SWRL和自然语言说明可以用于阅读，不代替真实 `swrl:Imp`、RDF列表和原子。

## 实际工具能力

[原生模板](../templates/ontology/README.md)包含构建脚本和依赖声明，能够读取自身加载清单并构建/检查集成结果；它不执行OWL/SWRL推理。

[RAG构建模板](../templates/rag-build/README.md)进一步提供可复用构建、测试与合成示例。使用前读取其覆盖范围；完整模型的OWL DL检查与显式规则执行模块分别留证，不为迎合受限运行器暗中删除公理。

[Ontology-tools](../Ontology-tools/README.md)中的 `local-rules-v1` 是受限规则执行后端。它读取固定扁平输入，不读取领域加载清单且拒绝imports。选用时须实现并验证领域源到部署包的适配，或者选择支持目标布局和语义的后端。独立 [owl-dl 检查入口](../Ontology-tools/OWL-DL.md)可以显式加载原生领域 TBox / ABox 和递归本地导入映射，检查一致性与具名类可满足性；SWRL 仍须另行执行，不能把该检查当作规则运行适配。模板不预设依赖环境已就绪，也不把运行器限制当作模型标准。

所选后端直接读取原生模型和规则，代码可承担通用解释、转换、构建和测试，不能另写一套同义业务政策。手工补结论、占位断言或只重算公式不证明规则已执行；缺环境时明确未执行范围。

## 复用与变更

既有合法IRI和扁平包可保留。迁移、融合或扩展按[变更与复用](../skills/ontology-validation/references/change-and-reuse.md)执行；本地工具升级和项目模型变更分别验证。复用模板时不继承示例阈值、审批、事实或“通过”结论，正式标准符合性与项目验收都须有本次证据。
