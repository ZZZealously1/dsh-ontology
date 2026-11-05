# OWL DL 独立合成案例

这些固定预期不从执行器输出生成，也不代表任何真实业务规则。命名空间统一使用 `urn:test:owl-dl:`。

| 输入 | 独立预期 |
|---|---|
| `consistent.ttl` | OWL 2 DL；一致；命名不可满足类为空 |
| `unsatisfiable_classes.ttl` | 一致；恰好 `Impossible`、`AlsoImpossible` 两个命名不可满足类，不包含 `owl:Nothing` |
| `inherited_conflict.ttl` | 继承得到互斥类型，已有个体使本体不一致 |
| `equivalent_conflict.ttl` | 等价类传播得到互斥类型，本体不一致 |
| `cardinality_conflict.ttl` | 最大限定基数为 1，两个显式不同的填充个体，本体不一致 |
| `cardinality_without_difference.ttl` | 一致；OWL 不把不同 IRI 自动当作不同个体 |
| `outside_profile.ttl` | 非简单的传递属性用于最大基数限制，不属于 OWL 2 DL；不能输出一致结论 |
| `with_swrl.ttl` | OWL DL 检查拒绝 SWRL；不能静默忽略规则后宣布整个输入通过 |
| `consistent.ttl` + `extra_facts.ttl` | 额外事实与模型中的已有个体类型冲突，本体不一致 |
| `imports/root.ttl` | 在两个 import IRI 都显式映射到本地文件时，三文件闭包不一致；缺任一映射时拒绝，禁止网络回退 |
| `invalid.ttl` | 语法错误；没有一致结论 |
| `version_iri_literal.ttl` / `version_iri_multiple.ttl` / `version_iri_non_header.ttl` | `owl:versionIRI` 分别为字面值、多值、出现在非本体头上；归一本体头前拒绝，不能删掉错误后报告通过 |
| `imports/non_header.ttl` | `owl:imports` 的主体不是本体头；即使目标有本地映射，也须拒绝 |
| `xml_literal.ttl` | 包含真实 `rdf:XMLLiteral` 数据属性断言；本体一致，实际调用 HermiT 的数据类型处理 |

测试代码还按临时文件的实际 URI 动态构造三组文档基址案例：相对类 IRI 与其他文件中的绝对引用必须相同；不同无 `@base` 文档中的同名片段必须独立；显式共享 `@base` 时应保持共同身份。临时文件不会写入固定输入目录。

测试同时检查超时与环境错误不能被写作 `consistent=true`、证据绑定实际输入与后端、不修改输入、不生成 JSON、重复执行的语义结果相同。真实推理用 HermiT；后端确实不可用时明确跳过对应集成测试，不能以模拟结果代替通过。
