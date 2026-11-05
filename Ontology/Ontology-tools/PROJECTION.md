# hermit-swrl-projection-v1 协同能力契约

本配置通过 HermiT 的 OWL DL 推导与有限 SWRL 事实交换，提供可留证、可重放的协同推导。本文件限定 `Ontology-tools 0.3.0` 中此既有配置的范围。它与 [local-rules-v1](PROFILE.md) 是不同配置；原默认配置不变。新增计算与可扩张数据候选使用另一个显式配置 [hermit-swrl-calculation-v1](CALCULATION.md)，不会自动扩大本配置的函数或日期适配范围。单独运行 OWL DL 检查或导出见 [OWL-DL](OWL-DL.md)，多轮合成例见 [examples/projection](examples/projection/README.md)。

**固定点只表示本配置的命名事实投影不再增加，不是完整 OWL DL＋SWRL 联合语义的完备性证明。**需要对匿名个体执行规则、跨析取分支综合规则结论或不受支持的内置函数时，应另选并验证对应后端，不能由大模型补充成“已执行”的确定结论。

## 输入和配置

使用现有扁平包：`ontology.ttl`、可选 `rules.swrl`、`shapes.ttl`、事实及黄金案例。通过 `runtime.ttl` 显式选择：

```turtle
@prefix ot: <https://w3id.org/ontology-tools#> .
<urn:example:runtime> a ot:Runtime ;
    ot:profile "hermit-swrl-projection-v1" ;
    ot:validationOrder "pre-post" ;
    ot:maxIterations 100 ;
    ot:javaTimeout 60 ;
    ot:javaExecutable "java" .
```

`validationOrder` 为 `pre`、`post` 或 `pre-post`；依赖推导类型的形状应选有后置检查的配置。`maxIterations` 默认 100，`javaTimeout` 默认 60 秒，`javaExecutable` 默认 `java`；它们是执行资源与环境配置，不是业务阈值。达到迭代上限仍未稳定或某次 Java 调用超时，保留失败证据，不交付部分结果为成功。

允许通过包内 `imports-map.ttl` 加载明确映射的本地模型导入；映射词汇和递归离线解析要求见 [OWL DL 加载协议](OWL-DL.md#多模块与离线导入)。所有导入文件仍须在包内，缺失或越界不回退联网。领域包的 `integration/load-plan.ttl` 继续由实际适配流程处理，本配置不会仅凭该文件自动加载领域目录。

模型和事实交给 HermiT，SWRL 交给独立规则执行层；规则结构不进入 HermiT 模型。复杂 OWL 构造须通过真实 OWL 2 DL profile 检查，不经过 `local-rules-v1` 的有限公理白名单。规则只能新增 ABox 类型或属性断言，不能改写 TBox、属性公理或运行配置。

## 冻结的有限投影范围

运行开始时固定模型、事实、规则、命名个体、类、属性和候选数据值，并保存 `candidates.ttl`。候选范围来自实际语义输入及规则常量；注释文本不是业务数据值来源，不从未知实体或不存在的文字值扩大范围。

| 投影内容 | 实际含义 |
|---|---|
| 命名类分类 | 命名类之间的子类和等价类关系 |
| 个体类型 | 冻结范围内的命名个体所属命名类 |
| 对象属性 | 冻结命名个体之间可被蕴含的对象属性断言 |
| 数据属性 | 针对冻结候选 literal 逐项检查相应断言是否被蕴含 |
| 身份关系 | 冻结命名个体间可被蕴含的 `owl:sameAs` |

不会将存在限制中的匿名见证创建为新的业务 IRI。数据属性值投影不宣称枚举整个数据域；不能把普通数据属性取值 API 的返回集合等同所有隐含值。新增数据值、新个体、算术和日期计算不在本配置范围内。

导出投影省略 `sameAs`、`equivalentClass`、`subClassOf` 的自反恒真三元组，避免无意义增量及重载时的单元素公理问题；这不表示删除输入中已有的动态身份断言。本配置按 RDF 1.1 将无语言标签的普通字符串与 `xsd:string` 规范化为同一字符串表示，原始文件字节快照仍保留；该行为不改变 `local-rules-v1` 的既有处理。

`sameAs` 参与个体类型、关系、规则常量和变量连接匹配，原 IRI 保留。一个 IRI 同时作为类和个体使用时，个体身份等价不自动合并对应的类或属性角色。未显式给出不同个体并不表示它们不同；未推导出结论也不表示逻辑否定。

## SWRL 与执行循环

规则原子和六种比较函数沿用 [SWRL 子集](PROFILE.md#swrl)：body 支持类、对象属性、数据属性及比较；head 只支持前三种事实原子。比较函数为 `equal`、`notEqual`、`lessThan`、`lessThanOrEqual`、`greaterThan`、`greaterThanOrEqual`，数据类型和变量安全要求沿用该契约。

本配置的个体变量**仅绑定冻结的命名个体**，不采用 `local-rules-v1` 的空白节点资源绑定范围；数据变量只绑定冻结的候选值。规则常量也属于预先冻结范围。不能在循环中凭规则生成新的项或把缺失当成否定。

1. 冻结并检查输入，按配置执行前置 SHACL。
2. HermiT 对当前模型与事实执行 OWL 2 DL、全局一致性与命名类可满足性检查。
3. 检查通过后，导出范围内分类及事实；执行受支持的 SWRL，保存新增事实及规则直接前提。
4. 将新增 ABox 事实传入下一轮 HermiT，重新检查并推导；无新事实时收敛。
5. 按配置执行后置 SHACL，保存最终图、状态、版本、指纹和逐轮证据。

任何一轮不一致或存在不可满足命名类时停止；规则引起的矛盾不能沿用上一轮“一致”的状态。`nonconformant` 表示检查实际完成但不符合，`failed` 表示环境、输入、profile、超时或执行失败；SHACL 不符合另读其报告。不要把不同失败合并成一种正常业务拒绝。

事实交换可能漏掉完整联合语义下成立的结论。例如 `A(x) 或 B(x)`，以及 `A(x)→C(x)`、`B(x)→C(x)` 两条规则，完整联合语义可要求 `C(x)`，但单独 OWL 不必蕴含任一分支类型；本配置没有事实可交给规则，因此不承诺推出 `C(x)`。这不是“未知即否定”，也不能用增加无来源类型断言修补。

## 调用、证据和重放

通过现有 `inspect / validate / infer / test / replay` 与对应 Python API 使用本配置；配置未选择它时仍按原后端执行。`validate` 仅做指定图的 SHACL，不暗中运行 SWRL。示例命令见 [多轮示例](examples/projection/README.md#智能体运行)。

先读取实际退出码和 `execution.ttl`，再解释结果：

| 文件或目录 | 读取方式 |
|---|---|
| `input.ttl` | 本次独立事实快照 |
| `candidates.ttl` | 本次冻结的命名对象和数据候选范围 |
| `classification.ttl` | 最终 OWL 命名类分类 |
| `result.ttl` | 相对载入图新增的 ABox 事实；类层次分类另见 `classification.ttl` |
| `closure.ttl` | 最终可查询图，显式交给 `query` |
| `trace.ttl` | SWRL 直接前提及 OWL 运行级结论依据 |
| `rounds/` | 各轮交给 HermiT 的输入、检查/投影结果、规则阶段证据 |
| `execution.ttl`、`report.md` | 状态、实际配置、轮次、环境与限制 |
| `snapshot/package/`、`manifest.sha256` | 可复跑包快照与运行精确文件指纹 |

OWL 证据定位到实际后端、轮次与输入快照，不是逐公理证明或最小冲突集。SWRL 证据记录实际规则及直接前提；同一结论只记录稳定的首次推导依据，不等同所有可能证明或全部规则触发次数。

`replay` 只使用保存的快照和本地依赖，核验程序、依赖及运行指纹后重新执行并比较语义状态和图结果。可复核实际完成的 OWL 不符合结果；技术失败不得当作成功重放。篡改快照或结果、版本失配均不能绕过检查。复跑通过表示同环境下复现了已记录结果，不表示不符合的本体已变成正确。

黄金案例可分别表达 `passed`、`shacl-invalid`、`owl-inconsistent`、`owl-unsatisfiable` 与 `failed`，见 [案例协议](PROFILE.md#黄金案例协议)。复现工具不替代独立黄金预期，也不验证来源真实性、业务批准或外部动作。

黄金执行保留 `snapshot/package/` 中的原始字节，并在 `snapshot/semantic-package/` 中按各原始文档的 base 固定绝对 IRI，再执行案例；复制目录不会改变实体身份。语义副本重新生成文件清单。故意损坏的案例文件保留原字节，由实际执行阶段报告技术失败，不能在生成副本时将其替换为正常输入。
