# hermit-swrl-calculation-v1 计算能力合同

`Ontology-tools 0.3.0` 的此配置在现有 HermiT／Python SWRL 事实交换流程中增加标量算术、时间计算和输出变量绑定。HermiT 执行 OWL DL 检查与命名事实投影；独立 SWRL 层读取原生规则并计算，新事实交回下一轮 HermiT。它不是完整 OWL DL＋SWRL 联合引擎。

必须在 `runtime.ttl` 显式选择此配置。默认 [local-rules-v1](PROFILE.md)、原有 [hermit-swrl-projection-v1](PROJECTION.md) 及独立 [owl-dl / owl-infer](OWL-DL.md) 的范围不随之扩大；已有项目不自动迁移。多轮算术示例与调用命令见 [examples/calculation](examples/calculation/README.md)。

## 输入与执行配置

沿用扁平运行包、明确模型／规则／事实角色、包内 `imports-map.ttl` 和现有 CLI、Python API；不增加另一套目录标准。模型用 `ontology.ttl`，规则用真实 SWRL RDF/XML `rules.swrl`，动态事实用 `inputs/facts.ttl` 或 `--facts`。动态事实不能修改 TBox、运行参数或规则。

```turtle
@prefix ot: <https://w3id.org/ontology-tools#> .
<urn:example:runtime> a ot:Runtime ;
    ot:profile "hermit-swrl-calculation-v1" ;
    ot:validationOrder "pre-post" ;
    ot:maxIterations 100 ;
    ot:javaTimeout 60 ;
    ot:javaExecutable "java" ;
    ot:maxMatches 100000 ;
    ot:maxEvaluations 100000 ;
    ot:maxGeneratedLiterals 10000 ;
    ot:maxNumericDigits 1000 .
```

上面列出发布默认值。`validationOrder` 可为 `pre`、`post`、`pre-post`；`javaTimeout` 是每次 Java 调用的秒数。其余数值均为正整数执行预算：`maxMatches` 累计匹配检查，`maxEvaluations` 累计函数求值，`maxGeneratedLiterals` 限制成功规则头引入的不同字面量，`maxNumericDigits` 限制数值输入、输出和小数位数的表示规模。预算跨轮累计，不因一次无命中或进入下一轮而清零。它们不表达金额上限、业务数量阈值或审批权限。

`maxMatches` 也计入 `sameAs` 身份替换尝试，避免身份扩展在规则匹配前绕过资源预算。

`inspect / validate / infer / test / replay` 按此配置分发；`query` 仍只读取明确给定的图。`validate` 只检查指定图的 SHACL，不执行 HermiT 或 SWRL。缺依赖、超时、预算耗尽、超轮数或不支持的表达使运行失败；部分结果不能作为成功闭包。

## 函数与参数

运行器登记以下 **13 个函数 IRI**。`swrlb:` 为 `http://www.w3.org/2003/11/swrlb#`；`otfn:` 为工具扩展 `https://w3id.org/ontology-tools/functions#`，后者不冒充标准 SWRL 内建函数。表中的 `?变量` 只是阅读记法，实际文件必须使用 `swrl:Variable` 及 `swrl:arguments` RDF 列表。

| IRI／签名 | 参数与结果 |
|---|---|
| `swrlb:equal(?a, ?b)` | 已绑定的兼容值相等 |
| `swrlb:notEqual(?a, ?b)` | 已绑定的兼容值不相等；不是缺失或逻辑否定 |
| `swrlb:lessThan(?a, ?b)` | 严格小于 |
| `swrlb:lessThanOrEqual(?a, ?b)` | 小于或等于 |
| `swrlb:greaterThan(?a, ?b)` | 严格大于 |
| `swrlb:greaterThanOrEqual(?a, ?b)` | 大于或等于 |
| `swrlb:add(?out, ?a, ?b)` | 精确 `a + b`，仅两个输入 |
| `swrlb:subtract(?out, ?a, ?b)` | 精确 `a - b` |
| `swrlb:multiply(?out, ?a, ?b)` | 精确 `a × b`，仅两个输入 |
| `swrlb:divide(?out, ?a, ?b)` | 精确 `a ÷ b`；无限循环小数明确失败 |
| `otfn:divideRounded(?out, ?a, ?b, ?scale, ?mode)` | 按明确小数位数与模式舍入除法结果 |
| `otfn:secondsBetween(?out, ?end, ?start)` | 两个 UTC 时间点之差，输出 `xsd:decimal` 秒数 |
| `otfn:addSeconds(?out, ?time, ?seconds)` | 按秒偏移时间点；允许负值，输出 UTC `xsd:dateTime` |

比较支持整数／十进制、无语言标签字符串和本配置时间点；布尔值只支持 `equal`、`notEqual`。数值类型之间按精确值比较；不同字符串、数值、时间、布尔种类不能隐式转换。`xsd:float`、`xsd:double`、语言标签字符串、未知计算类型不参与这些内建函数。

### 数值和显式舍入

算术输入为 `xsd:integer` 及其受支持的 XSD 整数派生类型，或有限 `xsd:decimal`；派生整数核对其值域。十进制不接受指数记法、NaN 或无穷大。计算使用精确有理数／整数运算，不依赖浮点数或 Python 默认 Decimal 精度。

两项整数做加减乘输出 `xsd:integer`；涉及十进制的加减乘，以及所有除法输出 `xsd:decimal`。输出使用规范字面值，允许去掉没有数值意义的尾零；声明小数位数不等于承诺显示宽度。`1 / 8` 输出精确十进制；`1 / 3` 没有有限十进制表示，`divide` 明确失败。不要为通过而暗中改成浮点近似。

`divideRounded` 的 `scale` 必须是非负整数类型字面量，不能超过实际 `maxNumericDigits`；结果仍须满足数值预算。`mode` 必须是明确字符串，支持：

| 模式 | 行为 |
|---|---|
| `HALF_EVEN` | 取最近值，中点取末位为偶数的一侧 |
| `HALF_UP` | 取最近值，中点远离零 |
| `DOWN` | 向零截断 |
| `FLOOR` | 向负无穷方向 |
| `CEILING` | 向正无穷方向 |

除数为零、非法类型、参数域错误或预算不足均为计算失败。工具不默认金额保留两位、不替项目决定模式、单位或尾差。业务公式及这些参数必须能追溯到项目来源。

### 时间点范围与后端适配

只接受有明确时区的 `xsd:dateTime`、`xsd:dateTimeStamp`。支持年份 `0001—9999`、小时 `00—23`、分钟和秒 `00—59`，小数秒最多三位；时区为 `Z` 或 `-14:00—+14:00` 内合法偏移。转换后的 UTC 时间点也须落在支持年份内。缺失时区、无效日期、超过毫秒精度、闰秒或 `24:00:00` 明确失败，不补机器本地时区、不静默截断。

`secondsBetween` 是结束减开始，允许负数，单位为秒。`addSeconds` 的偏移数乘以 1000 必须为整数毫秒；例如 `0.001` 秒可用，`0.0001` 秒失败。生成时间统一写为 UTC `Z` 的 `xsd:dateTime`，不读取系统当前时钟。不支持月份／年份偏移、工作日、节假日、自然日计数、单独 `xsd:date`、duration 运算或任意日期解析。

**本配置包含显式时间规范化适配。** 随工具固定的 HermiT 在非零时区的同时间点身份判断中存在已复现差异，因此进入 HermiT 的语义时间字面值先规范为相同 UTC `Z` 写法，保留原 `dateTime`／`dateTimeStamp` datatype。模型限制、规则常量与事实中的语义时间采用同一工作视图；SWRL 和后置 SHACL 使用该视图，前置 SHACL 仍检查原始图。注释或元数据中的时间不按业务时间转换。

原始包字节保存在快照中，`input.ttl` 保留适配前的事实时间；工作图与 `temporal-normalization.ttl` 记录实际转换。这是针对实际后端的值保持适配，不是改变来源时间或增加业务事实。重放重新执行并比较规范化映射，不能隐藏转换。独立 OWL 命令及旧协同配置未因此新增时间适配能力，不修改第三方依赖来绕过差异。

这里保持的是 **OWL 时间点值**，不宣称 RDF 词法形式或所有 SHACL 约束整体等价。后置 `sh:pattern`、`sh:minLength`、`sh:maxLength` 和结果查询中的 `STR()` 会看到 UTC `Z` 写法；检查来源格式的约束应放在前置阶段，或对另存的来源词法字段校验。工具不自动放宽正则，也不能将规范化后发生的后置校验失败改写为通过。

注释识别依据明确的 `owl:AnnotationProperty` 声明及内建注释属性，不按命名空间猜测。Dublin Core 命名空间中的属性不会自动获得豁免；如被声明为 `owl:DatatypeProperty`，其时间值仍按语义数据检查和适配。项目应正确声明元数据属性的角色。

## 绑定、候选范围与循环

body 支持 `ClassAtom`、`IndividualPropertyAtom`、`DatavaluedPropertyAtom` 和登记的 `BuiltinAtom`；head 仅前三类 ABox 事实。函数输入全部已绑定才可执行；输出位置可绑定新的数据变量。输出已绑定时检查同值，不能覆盖原绑定。编译器按变量依赖稳定调度，支持连续计算；body 的书写顺序不决定优先级。缺少输入绑定、循环绑定、个体／数据变量混用或不支持原子在检查阶段拒绝。

普通比较为假或已绑定输出不匹配只让当前分支不成立；除零、类型错误和无法表示的计算结果使整个执行失败。不能将失败当成条件为假后继续交付。

运行开始冻结模型、规则、事实、类、属性和命名个体。初始数据候选来自语义输入与规则常量。规则不能生成新个体、匿名存在见证、类或属性；`sameAs` 对个体类型、关系、常量和连接匹配生效，保留原 IRI，不合并同名类或属性角色。

只有完整 body 成立且 head 生成数据属性事实时，新字面值才能进入下一轮候选。中间计算值保留在绑定和轨迹中；后续条件不成立的分支不能扩张候选。规则匹配对受支持类型采用值语义，候选图仍保存带 datatype 的 RDF 字面项：值相等不等于将所有 datatype 或原始表示合成一个 RDF 项。

执行顺序为：冻结并检查 → 按配置前置 SHACL → 时间工作视图 → HermiT 检查／投影 → SWRL 计算 → 保存规则头新事实并扩展候选 → 下一轮 HermiT。每次 HermiT 投影使用该轮完整候选，数据属性仍逐候选检查蕴含。事实和候选均无新增才达到固定点，再按配置后置 SHACL，发布最终结果。

每轮重新检查全局一致性与命名类可满足性。计算事实引起矛盾时必须停止，不能继承上一轮“一致”的状态。静态检查保守拒绝包含计算生成的数据依赖环，覆盖规则转发、子属性和等价属性回流，并报告路径；它不是任意 OWL 协同程序的终止性证明。运行预算是另一层停止保障。

匿名对象规则匹配、跨析取分支综合、聚合计数／求和、撤销事实、优先级、字符串生成及新个体生成仍不支持。SPARQL 可对保存图做 `SUM`／`COUNT` 查询，但不会将查询结果自动写回 SWRL 推理。

## 证据、错误与重放

先检查真实退出码及 `execution.ttl`。`0` 表示本次入口完成；`1` 表示完成 OWL 检查但不符合，或黄金／重放比较失败；`2` 表示技术执行失败；`3` 表示 SHACL 不符合。语义报告分别标明不一致、不可满足类和未知。比较分支不成立不产生错误；函数错误记录规则、函数、参数和阶段 `swrl-inference`。检查阶段发现的签名、绑定或生成依赖环错误留在 `inspect` 阶段。

| 产物 | 含义 |
|---|---|
| `input.ttl`、`snapshot/package/` | 适配前事实及原始源文件字节快照 |
| `prepared/`、`temporal-normalization.ttl` | 时间规范化后的工作输入和转换映射 |
| `initial-candidates.ttl`、`candidates.ttl` | 初始及最终数据候选；命名实体范围保持冻结 |
| `rounds/round-*/candidates.ttl` | 交给该轮 HermiT 的候选范围 |
| `computations.ttl`、逐轮同名文件 | 函数 IRI／版本、参数位置及 datatype、输出、匹配状态、舍入／时间约定、直接前提和计算链 |
| `calculation-contract.ttl` | 本次函数签名、语义版本、数值与时间合同及实际配置 |
| `budget.ttl`、逐轮预算记录 | 实际资源预算与使用量 |
| `classification.ttl`、`result.ttl`、`closure.ttl` | 分类、新增 ABox 事实及本配置范围内的最终查询图 |
| `trace.ttl`、`rounds/` | SWRL 直接前提及计算关联、OWL 轮次、输入与实际 HermiT 执行依据 |
| `execution.ttl`、`report.md`、指纹文件 | 状态、环境、实际轮次与配置、限制及完整文件指纹 |

计算轨迹保存实际求值，包括未命中或失败分支；它不等同业务规则全部命中。SWRL 证据到规则、直接前提和函数步骤，OWL 证据到结论、后端、轮次及输入快照，不提供逐公理证明或最小冲突解释。

`replay` 只使用保存的快照及本地依赖，核验指纹与环境后重新计算，比较语义状态、分类、结果、候选变化、计算合同／轨迹、时间规范化和预算证据。输入、依赖、配置或结果篡改时拒绝通过。旧版本记录继续执行其版本／运行时匹配要求，不能升级后绕过旧指纹声称同环境复现。已完成的 OWL 不符合可复核，技术失败不算成功重放；复现矛盾不表示本体通过。

## 验收与交付边界

计算能力需用独立预期覆盖精确算术、显式舍入、绑定／原子重排、时区同值、日期边界、新候选、sameAs、多轮分类、矛盾、依赖环、资源预算及篡改重放。涉及 OWL 的关键案例必须实际运行 HermiT，缺环境或跳过不能记为通过。来源、业务口径、工具能力、项目验收和外部操作分别判断。

工具测试、合成黄金及方法维护检查的实际命令与数量写入包外验收目录；本合同和示例不预先宣称当次环境全部通过。项目按 [验收模板](../templates/acceptance.md) 保存结果，工具与必要参考留在 `Ontology`，运行证据放在方法库外。全程使用原生 OWL、SWRL、Turtle、Markdown 等格式，不生成 JSON，不连接或修改外部系统。
