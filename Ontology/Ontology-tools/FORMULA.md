# hermit-swrl-formula-v1：原生 RDF 公式执行合同

工具 `0.4.0` 新增此显式配置。OWL/SWRL 维护诊断、分类与适用条件；原生 RDF 表达式树维护公式；SHACL 维护约束；通用解释器读取表达式求值。它继承有限 HermiT/SWRL 交换边界，不是完整 OWL DL＋SWRL 联合求解器。既有三个 profile 不自动迁移；旧配置不能静默忽略 `formulas.ttl`。

## 文件角色与维护源

扁平执行包增加 `formulas.ttl`，命名空间 `f: <https://w3id.org/ontology-tools/formula#>`。领域项目可用 `formulas/<domain>.ttl` 维护，再通过经图等价验证的适配器导出。公式目录作为独立角色进入快照、指纹与重放，不把整棵 AST 加入 HermiT。

每条公式是 `f:Formula`：`enabled`、`verified` 为布尔值；`parameters` 为参数 RDF 列表；`expression` 为根；`outputSymbol`、`outputUnit`、`latex` 为字符串。每个参数是具名 `f:Parameter`，有 `key`、`symbol`、`unit`，可声明 `minInclusive/minExclusive/maxInclusive/maxExclusive`（按参数声明单位检查）。每个输入必须在表达式中实际出现。`requiredCondition` 是完整的必要条件 IRI 集合；确实无条件的合成公式须显式 `unconditional true`，不能两者都省略或同时声明。

参数还可用 `lessThanParameter/lessThanOrEqualParameter/greaterThanParameter/greaterThanOrEqualParameter` 指向同公式中的另一参数。两端必须维度兼容，全部绑定归一为 SI 后检查所有关系；违反返回 `parameter-domain`。这类关系维护在原生目录，不由解释器硬编码领域判断。

只编译 `enabled true` 条目；激活条目必须核验、结构合法且可执行，任何激活编译错误使包检查失败。停用/不支持/冲突候选可另存来源台账；停用条目不会执行，也不计为计算能力。

表达式支持三类节点：

| 节点 | 必需内容 |
|---|---|
| `f:Constant` | `f:value` 数字；可选显式 `f:unit`，默认无量纲 |
| `f:ParameterRef` | `f:parameter` 指向本公式的具名参数 |
| `f:Operation` | `f:operator` 运算 IRI；`f:arguments` 为有序 RDF 列表 |

运算白名单：`Add/Subtract/Multiply/Divide/Pow`（二元）及 `Negate/Sqrt/Exp/Ln`（一元）。不执行 Python 文本、任意 LaTeX、远程资源或用户函数。LaTeX 是来源展示；树是唯一可执行公式源。`render_formula(catalog, iri)` 返回保存的原写法；`render_expression(catalog, iri)` 从树重建含左侧符号的规范 LaTeX，二者都可展示。不宣称重新生成原书的字号、版面或逐像素排版。

## 计算请求与适用性

运行前创建具名 `f:Evaluation`，以 `f:formula` 指向公式，以 `f:context` 指向器件/工况快照；以 `f:binding` 关联显式 `f:Binding`。直接绑定含 `f:parameter/f:value/f:unit/f:context`；依赖绑定用 `f:fromEvaluation` 代替 value/unit，上游必须同上下文、具名且预先创建。

OWL/SWRL 以 `f:satisfiedCondition` 为评估记录提供条件证据。所有必要条件均得到证据、所有参数数值唯一且单位/域正确后才计算。缺参和缺条件为 pending，保留候选诊断和具体缺项，不把缺失当作否定。非法单位、互不相等的多值、跨上下文、循环、非法数学域及资源超限为明确执行错误。

原始动态输入不能写 `f:result/resultUnit/calculationStatus`，不能修改静态目录。规则也不能伪写计算器输出。只有完整成功的公式输出追加到已有 Evaluation：`f:result`（decimal）、`f:resultUnit`、`f:calculationStatus f:Computed`。中间值仅在轨迹中，不回灌为业务事实。

本版允许结果沿预先声明的无环 `fromEvaluation` 依赖计算，并细化诊断；拒绝计算结果经规则再次生成计算适用许可（包括经中间规则的反馈）。适用性来自观测与独立语义条件。这一保守限制避免循环自许可；联立方程、反解和固定点数值迭代不在本版范围。

## 数值、单位与资源

`runtime.ttl` 使用 `ot:profile "hermit-swrl-formula-v1"`，继承 [计算配置](CALCULATION.md) 的预算及时间规范化，增加 `ot:formulaPrecision`，默认50，范围2至 maxNumericDigits。全部科学运算使用固定 Python 的纯 Python `_pydecimal`、独立 Context、`HALF_EVEN`；记录实现文件 SHA256、Python、精度、近似/舍入标志。算法精度不是测量有效数字、物理误差或业务容差。

只接收有限 XSD integer/decimal；拒绝 float/double、NaN、Inf及伪造词法。用户原话中的科学计数法由事实准备阶段精确展开为 decimal，并保留原句。除法按有效位求值；旧 `swrlb:divide` 保持原来的精确有限除法合同。

仅本配置在工作图、OWL回流及最终输出的 `f:value/f:result` 上，将合法精确 integer/decimal 按值合一为统一 decimal 表示。例如 `"1"^^xsd:integer`、`"1"^^xsd:decimal`、`"1.00"^^xsd:decimal` 统一为 `"1.0"^^xsd:decimal`，不使用运算精度对输入值舍入。原始 `facts-source`、`input.ttl` 和源文件快照保留原词法；不同数值仍保留并作为冲突拒绝。显式非法 decimal 词法不会被归一化修复，仍须拒绝。该策略不应用于旧 profile，也不改变独立黄金预期；最终数值验收仍要求统一工作结果恰好一个值。

单位采用显式白名单或目录中的 `f:Unit` 定义：`f:key` 字符串、`f:scale` 正decimal（对SI的倍率）、`f:dimensions` 字符串（如 `length:2;time:-1`）。不猜测未知单位拼写；不支持偏移单位。保留输入单位和值，记录对声明单位与SI工作值的转换。加减要求同量纲；exp/ln要求无量纲；幂指数无量纲；输出维度必须匹配声明。单位定义必须可追溯，不能重定义内建单位。

开方要求非负、对数要求正、除数非零；负底数仅允许整数幂，拒绝0^0及零负幂。拒绝静默溢出/下溢归零及不受支持运算。表达式/依赖限深128、每式节点上限10000；继承的累计匹配/计算/字面量/数值长度预算另外限制运行。超过预算不发布成功闭包。

## 实际执行与证据

仍使用现有 `inspect/validate/infer/query/test/replay` CLI 与 Python API。顺序：冻结并检查 → 前置SHACL → 每轮HermiT → SWRL → 全条件检查与公式计算 → 成功完整结果/新字面量回交HermiT → 固定点 → 后置SHACL。检查失败不能用语言手算替代执行。

| 产物 | 内容 |
|---|---|
| `formulas.ttl`、`snapshot/package/` | 目录图与原始字节快照 |
| `formula-contract.ttl` | 数值实现/版本、实际精度、单位与适用性合同 |
| `formula-computations.ttl` | 所有轮次的公式、参数绑定、单位转换、原LaTeX、树重建、逐操作输入/输出及舍入标志 |
| `formula-diagnostics.ttl` | 最终轮的缺参/缺条件；技术错误另见execution状态 |
| `rounds/round-*/formula-result.ttl` | 该轮完整成功新增结果 |
| `budget.ttl`、`initial-candidates.ttl`、`candidates.ttl` | 累计预算与实际候选扩张 |

继续保留计算配置、SWRL、OWL轮次、SHACL和环境证据。`replay` 核对代码/Python/依赖/Java和完整文件指纹，比较包括目录、公式合同、绑定/计算/诊断及逐轮结果在内的RDF图；不能以相同结果文字冒充重放。公式错误时没有被接受的顶层 result/closure。

## 独立验收

每个激活公式必须有独立算例及来源/预期，核对完整结果集合、单位、对象和适用条件。公式覆盖与SWRL实际执行覆盖分开统计，不能将公式数加入规则命中率。科学数值案例可以用 `ot:expectedNumeric`，字段为 `rdf:subject/rdf:predicate/rdf:value`，显式非负 `ot:absoluteTolerance` 或 `ot:relativeTolerance`，可配 `ot:unitPredicate/ot:unit`；结果必须恰好单值，容许误差为 `max(absTol, relTol*abs(reference))`。零容差允许，无隐含默认容差。

必须真实验证公式→HermiT→后续规则、缺参/缺条件、同一条件集合只满足一项、单位/量纲错误、非法域、跨对象/快照、多值、依赖循环、预写结果、预算耗尽、重放及篡改。参考值先固定，不能调用被测求值器现场生成黄金预期。合成示例见 [examples/formula](examples/formula/README.md)，具体通过状态读取当次证据。
