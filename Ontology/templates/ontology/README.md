# 原生文件结构示例：合成标签分类

状态：`draft-template`。本目录供复制、阅读和校验文件结构使用，提供集成构建脚本及其依赖，尚未配置业务推理后端、运行期Skill、验收或冻结清单，不能作为已可执行的业务包交付。

能力问题：对于给定合成Item，原生SWRL能否从 `tag="demo"` 推导其属于 `TaggedItem`？唯一规则为 `Item(?x) ∧ tag(?x,"demo") → TaggedItem(?x)`。这是结构演示，不是审批、阈值或真实业务政策。

## 文件与格式

| 文件 | 内容 |
|---|---|
| subontologies/demo_ontology.owl | demo领域TBox：Item、TaggedItem、identifier和tag，模型/字段来源 |
| rules/demo/demo_rules.swrl | RDF/XML形式的一条真实SWRL规则，body两原子，head分类原子 |
| data/instances_demo.owl | ABox正向快照、合成Dataset和字段级RDF证据 |
| integration/load-plan.ttl | demo域登记、模型/规则/事实模块、路径、格式、版本及依赖 |
| integration/merged_ontology.owl | 由TBox与规则生成的RDF/XML集成入口，不含动态ABox |
| integration/build-evidence.ttl | 构建器版本，源文件、加载清单及脚本的SHA256 |
| docs/demo_本体说明.md | 域范围、能力问题、概念、规则、依赖及未验证项 |
| scripts/build_integration.py | 本例物化集成与图同构/源指纹检查，不执行推理 |
| requirements.txt | 仅构建器依赖，项目选定后端后另补对应依赖 |
| shapes.ttl | identifier与tag为必填单值字符串 |
| provenance.ttl | 合成来源、示例能力问题与规则关联 |
| mapping.ttl | 合成输入字段映射；没有已实现ETL的声明 |
| tests/cases.ttl | 正向推导、反向不产出、非法输入三个独立预期 |
| tests/inputs/*.ttl | demo、other及缺identifier的输入 |
| queries/check-result.rq | 查询实际合并输入/推导图中是否含TaggedItem断言 |

标准前缀来自RDF/OWL/XSD/SHACL/SWRL和Dublin Core。`ex:`是 `https://example.org/ontology-template/demo#`；`meta:`是本示例的 `https://example.org/ontology-template/meta#`，这些IRI用于标识，不要求访问网页。

新生成的 `.owl`、`.swrl` 使用RDF/XML，`.ttl` 使用Turtle。单域只提供一组领域源，不为目录形式制造额外业务域。本例没有 `owl:imports` 或外部依赖；集成入口默认用于查看模型和规则，实际运行还须显式载入本次事实。

科学/工程公式项目可依[结构化公式合同](../../Ontology-tools/FORMULA.md)增加 `formulas/<domain>.ttl` 和独立 `FormulaCatalog` 静态角色，实际适配到新配置的 `formulas.ttl` 并证明图等价。本例没有公式，加载清单只保留扩展注释，当前构建器的角色支持仍限TBox/Rules/ABox；不能未经实现就启用新角色或改写本例SWRL演示。

`meta:Dataset/mode`标记synthetic；`meta:Source`登记sourceId、status、authority和locator。`meta:Mapping`记录sourceField/targetProperty及执行状态。参与 OWL DL 检查的 ABox 字段证据使用 `owl:Axiom` 与 `owl:annotatedSource/annotatedProperty/annotatedTarget` 指向实际断言，并用 `dct:source` 和 `meta:locator` 定位；相关注释属性在 TBox 中显式声明。一般 RDF reification 可保存在单独 provenance 图，不将任意 `rdf:Statement` 结构直接混入 OWL DL 检查并假定会被正确解释。

`meta:Case`有标识、相对 `tests/cases.ttl`目录的input、validationExpectation。正向 `expectedTriple`表示指定运行结果应包含该三元组；反向 `notExpectedInferredTriple`只检查本次推导未产出该三元组，不表示OWL否定事实。非法案例为invalid且不得作正常业务推理。`queries/check-result.rq`中的false也仅表示查询图未包含该类型。

## 加载契约与实际构建

`pkg:` 为本模板自定义的 `https://example.org/ontology-package#`，不是OWL标准加载协议。`plan:` 为 `https://example.org/ontology-template/load-plan#` 中的清单资源。构建器实际读取下列词汇：

| 词汇 | 含义与实现 |
|---|---|
| LoadPlan、module | 唯一计划与明确选定的全部源模块，不用目录顺序猜测 |
| Domain、domainId、description、documentation | 域身份、范围与包内说明；不建立新的业务类 |
| Module、domain、role | 模块归属；角色限定TBox、Rules、ABox |
| path、format、ontologyIRI、version、dependsOn | 包根相对路径、解析格式、本体IRI（存在时）、版本和模块依赖；本例无imports，依赖模块须在清单中 |
| integrationMode、entryFile、entryIRI、evidenceFile | 本例只支持Materialized，输出图和证据均在integration目录 |
| includesABox、factSelection | 本例固定false、ExplicitSnapshotOrInput：构建时检查已列ABox但不合并；运行时需显式选快照或本次输入 |
| builderVersion、buildInput、sha256 | 构建证据，不是推理证据 |

构建器支持多个按同一契约登记的本地域模块，核对源文件清单、基本角色声明与依赖存在性；将TBox和规则的空白节点分别定域后作图并集，添加声明的集成本体头。它不实现语义对齐、完整角色检查、OWL一致性检查、SHACL或SWRL执行；这些仍由项目后端与验收负责。纯imports项目需另配离线加载器，本脚本明确拒绝imports，不将该实现限制作为本体标准。

在包根、已安装Python及 `rdflib==7.1.4` 的环境运行：

```powershell
python scripts/build_integration.py
python scripts/build_integration.py --check
```

首个命令只写两个派生产物；后者不写文件，比较所选TBox与Rules源图并集加固定头部与集成图的同构性，并核验源文件和构建器指纹。成功退出0，检查失败退出非0；源变化须重建。已存在 `manifest.sha256` 时拒绝原地构建，应在新版本中重新验收。修改脚本或清单后也要重建。

本脚本不是目录到扁平包的适配器。当前 `Ontology-tools/local-rules-v1` 规则执行接口只读取 `ontology.ttl`、`rules.swrl`、`inputs/facts.ttl` 等固定扁平路径，不识别此清单且拒绝imports。选用该规则后端时，项目须实际实现和验证兼容导出，或改选支持本布局的后端；不能直接把本模板交给旧命令并宣称可运行。

独立的 [OWL DL 检查器](../../Ontology-tools/OWL-DL.md)可直接选择 `subontologies/demo_ontology.owl` 和 `data/instances_demo.owl` 检查全局一致性与具名类可满足性；具体可执行命令见该说明。它不解释本加载清单且拒绝 SWRL，默认 `integration/merged_ontology.owl` 含规则，不作为该检查的输入。此能力不代表模板的业务规则已经执行。

## 使用步骤

1. 复制到用户指定目录，按业务能力问题替换命名空间、来源、字段、规则、形状和独立案例；删除不适用的示例，不把synthetic改成provided冒充资料。
2. 更新域登记、源模块与依赖，运行上述构建及检查命令。根据项目后端说明实现加载/适配，验证转换等价；不要把构建脚本当作推理引擎。
3. 从[运行期Skill模板](../runtime-SKILL.md)生成根SKILL，从[验收模板](../acceptance.md)生成acceptance.md；填实际命令和依赖，配置runtime。没有实际命令前保持草案。
4. 解析原生文件，实际运行 OWL DL profile、全局一致性与具名类可满足性检查，SWRL 单独验证；再按项目顺序运行SHACL、对三个案例实际调用规则后端并对照预期。不能手动补TaggedItem三元组使案例通过；查询必须读取实际保存的推导图。
5. 记录规则、公理、数据和查询图指纹，完成验收后生成manifest.sha256。新增运行输出存包外。

本示例不需要持续关系存储或路径查询，本地RDF快照足够；未选择Neo4j，未进行数据库连接。语法/SHACL校验不代表SWRL已运行。

本例只演示单对象字段类型与基数，未实现复合身份、跨周期关系或聚合集合约束；具体项目须按数据契约补齐，不能以本例SHACL通过代替复杂业务验收。
