# local-rules-v1 支持范围

本文件描述 `Ontology-tools 0.3.0` 中 `local-rules-v1` 的实际执行边界。独立 OWL DL 检查/投影见 [OWL-DL](OWL-DL.md)，HermiT 与有限 SWRL 协同见 [PROJECTION](PROJECTION.md)，新增标量计算见 [CALCULATION](CALCULATION.md)；这些独立配置不扩大本 profile 的范围。本文件是该规则执行器的能力契约，不是 OWL、SWRL 或 SHACL 标准的完整定义。工具采用本地 RDF 图、有限规则前向闭包与显式失败机制，不提供完整 OWL DL 推理、一般一致性证明或业务工作流。

## 输入、配置与固定点

- `ontology.ttl`、`shapes.ttl`、事实、来源、映射、案例和运行配置使用 Turtle；`rules.swrl` 使用真实 SWRL RDF/XML，没有规则时可省略。
- 语义文件按明确角色载入。SWRL 定义应放 `rules.swrl`，不能混入事实图后期望被当作运行配置执行。
- `ontology.ttl` 可以同时包含 TBox 和静态 ABox。`inputs/facts.ttl` / `--facts` 属于动态事实角色，拒绝 TBox 声明/公理和 SWRL 结构，防止本次数据改变已选政策；允许业务实例、`owl:NamedIndividual`、`rdf:Statement` 来源陈述、自定义数据集及标签。这是工具的输入角色约定，不是 OWL 对 TBox/ABox 必须分文件的要求。
- `runtime.ttl` 使用 `https://w3id.org/ontology-tools#` 中的 `Runtime`、`profile`、`validationOrder`、`maxIterations`。默认 profile 为 `local-rules-v1`，校验顺序为 `pre-post`，迭代上限为正整数 `100`。
- `pre` 检查推导前图；`post` 检查闭包图；`pre-post` 两者都做。检查顺序属于项目配置，SHACL 本身不会隐式打开 OWL/SWRL 推理。
- 推理按同步轮次执行，每轮只读取上一轮图。终止条件为没有新增三元组；迭代上限仍有新增事实时失败，不把未收敛结果标为成功。固定点只对本 profile 支持的操作成立。
- 所有加载均为本地文件。拒绝 `owl:imports`、非空 `modules/`、包内越界路径和链接、RDF/XML DTD/实体。HTTP IRI 只作标识，不自动抓取。

## RDFS 与 OWL

| 构造 | 实际行为 |
|---|---|
| `rdfs:subClassOf` | 类层次传递闭包；子类实例获得上位类型 |
| `rdfs:subPropertyOf` | 属性层次传递闭包；子属性断言提升为父属性断言 |
| `rdfs:domain` | 属性断言的主语获得定义域类型 |
| `rdfs:range` | 资源对象获得值域类型；XSD 数据类型值域仅保留声明 |
| `owl:inverseOf` | 可从声明两端的属性断言推导逆向关系 |
| `owl:SymmetricProperty` | 从资源关系生成反向关系 |
| `owl:TransitiveProperty` | 从资源关系链推导传递关系 |

允许类、对象属性、数据属性、注释属性、本体、命名个体的声明，以及版本、标签、说明等受支持注释。类和属性公理的主体/对象必须是命名 IRI；不支持匿名类表达式或改写标准保留词汇的公理。

这不是完整 RDFS 闭包：不生成全部公理性三元组。XSD range 不验证 literal 是否满足数据类型，也不会生成 literal 作主语的三元组；数据完整性和数据类型约束交给 SHACL。

其他 OWL 语义明确拒绝，包括 `sameAs`、`equivalentClass`、`equivalentProperty`、`disjointWith`、限制类、交并补、枚举类、基数、函数/逆函数属性、属性链、键、否定属性断言等。不能用“未发现矛盾”声称一致性已获证明。身份合并、互斥检查与项目完整性要求应选择能满足要求的后端，或建立有明确依据的 SHACL 约束。

## SWRL

| 项目 | 支持范围 |
|---|---|
| 规则 | 有稳定命名 IRI 的 `swrl:Imp`，非空 body/head，合法 RDF 列表 |
| body 原子 | `ClassAtom`、`IndividualPropertyAtom`、`DatavaluedPropertyAtom`、受限 `BuiltinAtom` |
| head 原子 | 前三种类/属性原子；不支持 head builtin |
| 类/属性谓词 | 非标准保留词汇的命名 IRI |
| 个体 | 既有命名 IRI 与空白节点资源可绑定变量；规则中显式个体常量必须是命名 IRI，不创建新个体 |
| 变量 | 以命名 IRI 声明 `swrl:Variable`；head 和 builtin 变量须由 body 类/属性原子绑定 |
| 连接与过滤 | 先连接类/属性原子，再进行 builtin 过滤；body 顺序不作为流程顺序 |
| 递归 | 可在有限既有项上多轮执行，以固定点和迭代上限终止 |

仅支持命名空间 `http://www.w3.org/2003/11/swrlb#` 的六个二元比较内建：`equal`、`notEqual`、`lessThan`、`lessThanOrEqual`、`greaterThan`、`greaterThanOrEqual`。

同一变量同时作为个体和数据值使用时拒绝。所有合法 `swrl:Imp` 都参与执行，项目自定义 `status` 等注解不会成为开关。对精确 IRI `http://swrl.stanford.edu/ontologies/3.3/swrla.owl#isRuleEnabled`，值非 `true` 时直接拒绝，不静默忽略禁用标记后继续执行。需要停用规则时，应在有依据的新模型版本中明确调整活动规则集并重新验收。

比较的实际类型支持如下：

- `xsd:integer` 及有界派生整数：验证有效值与范围，按精确数值比较。
- 有限 `xsd:decimal`：以精确十进制数比较；不接受 NaN、无穷大或指数形式充当 decimal。
- 无语言标签的普通字符串、`xsd:string`：按字符串比较。
- `xsd:boolean`：只支持 `equal`、`notEqual`。
- 不兼容的类型、浮点数、日期/时间、带语言标签的字符串比较明确拒绝。

普通 RDF literal 的保存不等于该类型支持内建计算。本 profile 不支持算术、聚合、日期计算、字符串函数、新值构造、否定、优先级、业务规则互斥、撤销结论和新个体生成。`notEqual` 是已绑定值的不相等比较，不是“条件未证明就算否定”。没有推导出某结论也不是该结论的 OWL 否定。

不支持的 OWL/SWRL 构造和 builtin 常量在静态检查阶段拒绝；builtin 变量值的类型要等匹配后才能检查，运行时绑定到不支持的类型即失败。仅某个样例未触发失败，不证明其他数据类型受支持。

## SHACL 与 SPARQL

SHACL 使用本地 pySHACL，在指定图上验证 Core 约束，关闭隐式推理和高级执行模式。SHACL-SPARQL、自定义执行约束、JS、规则执行与远程依赖不属于当前 profile；相关构造不能静默跳过后报告通过。SHACL 通过只表示所选图满足已声明形状，不证明数据真实、源集合完整或业务政策正确。

SPARQL 使用 RDFLib 对显式指定的本地图执行 `SELECT`、`ASK`、`CONSTRUCT`、`DESCRIBE`。拒绝 UPDATE、`SERVICE`、`FROM` 和外部数据集加载。查询本次闭包必须明确传入 `closure.ttl`，查询原始事实不会自动继承此前进程的推导结果。

不宣称完整 SPARQL 实现。锁定版本已发现 SELECT 投影位置的 EXISTS 表达式不能正确执行；该错误会原样留证并返回失败。随包示例使用等价的 `OPTIONAL + BOUND` 表达图中是否存在指定三元组，工具不会自动改写用户查询。

## 黄金案例协议

规范命名空间为 `https://w3id.org/ontology-tools#`；兼容 `https://example.org/ontology-template/meta#` 的以下同名词汇。

| 词汇 | 含义 |
|---|---|
| `Case` | 一个独立测试案例 |
| `input` | 相对 `tests/` 的安全事实路径，如 `inputs/positive.ttl` |
| `validationExpectation` | `conforms` 或 `invalid` |
| `expectedTriple` | 用 `rdf:subject/predicate/object` 表达预期在 `result.ttl` 中新增的三元组 |
| `notExpectedInferredTriple` | 本次推导不应新增该三元组；不是逻辑否定断言 |
| `expectedClosureTriple` | 预期在 `closure.ttl` 中出现的三元组，可以是原始事实或推导事实 |
| `reasoningMustStop` | 非法输入案例要求停止后续正常推理 |
| `expectedOutcome` | 可选，明确预期为 `passed`、`shacl-invalid`、`owl-inconsistent`、`owl-unsatisfiable` 或 `failed` |
| `expectedUnsatisfiableClass` | `owl-unsatisfiable` 必需；命名类 IRI 集合须与实际不可满足类集合完全相同 |
| `expectedFailureStage` | `failed` 必需；只接受指定阶段的技术失败 |
| `expectedErrorContains` | `failed` 可选；进一步核对实际错误信息包含指定文本 |

每例输入独立加载。预期三元组的取值须使用稳定 IRI/literal，不能依赖文件中的空白节点标签进行跨图身份比较；用于组织预期的 RDF Statement 节点可以是空白节点。正常案例至少给出一种结果预期。预期来自来源规则与业务人工判断，不能由正在验收的引擎自行生成。只有校验失败符合独立预期的案例，才可以把该案例测试视作通过；它仍不是一次成功业务推理。测试报告应结合逐例证据阅读，不能把测试数当作全部业务边界已经覆盖。

没有 `expectedOutcome` 的已有案例保持原协议。显式使用 `expectedOutcome` 时，不能同时填写旧协议的 `validationExpectation` 或 `reasoningMustStop`；非 `passed` 预期也不能声明成功推导三元组。OWL 不一致、不可满足类、SHACL 不符合与技术失败分别核验，不能用同一“非法输入”预期接受任意失败。`owl-unsatisfiable` 要求全局仍一致并且指定类集合吻合，`owl-inconsistent` 要求实际全局不一致。该扩展协议用于按实际 profile 执行的包测试，不扩大 `local-rules-v1` 的 OWL 能力。

## 结果、证明与复跑

- `input.ttl` 保存本次事实；`closure.ttl` 包含载入模型、规则文件内受支持 schema 与事实的闭包；`result.ttl` 仅为新增推导三元组。SWRL 原子及注解、形状图和来源/映射说明不自动作为业务事实并入闭包；规则文件中的业务断言明确拒绝。
- `trace.ttl` 用 `ot:Derivation`、`ot:conclusion`、`ot:premise` 关联 RDF Statement；`ot:rule` 指向规则 IRI，`ot:axiom` 指向公理陈述，`ot:iteration` 保存实际轮次。
- 每个新增三元组只保留第一次产生它的稳定证明，不收集全部可能证明，也不记录所有冗余规则触发。轨迹中的规则数量是实际保存证明的规则数量，不能冒充完整规则覆盖率或全部命中次数。
- 空白节点的身份范围属于各自 RDF 文档，不能按标签跨文件直接关联。轨迹中的重述前提和结论可在轨迹图内部追溯；跨图对照空白节点使用结构或图同构。需要跨文件、跨运行引用的业务实体应使用稳定 IRI。
- 工具记录输入快照、输出指纹、程序指纹、程序版本与实际依赖版本。复跑先验证清单和环境，再从原始快照执行，按 RDF 图同构比较结果。
- SHA256 与图同构共同服务于复核：前者核对字节变化，后者避免 Turtle 排版、三元组顺序和空白节点标签影响语义比较。执行时间与报告文字不要求逐字重复。
- 失败留下失败状态；重试使用新目录。程序/依赖不匹配、快照变更、语义不支持、输入校验失败或迭代不终止，不能以人工改报告的方式修正为通过。

通用工具不替项目定义人工状态优先级、混合责任金额、舍入、超权审批或接口契约。此类需求先落实项目依据，再确定由原生规则表达、事实适配器实现，还是升级执行后端；没有依据时继续保留待确认或已确认的人工处理。
