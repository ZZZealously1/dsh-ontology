# OWL DL 检查与命名结果导出

`owl-dl` 是独立离线检查入口，profile 为 `owl-dl-hermit-v1`；`owl-infer` 使用 `owl-dl-projection-v1`，在检查通过后导出有限命名结果。工具包版本为 `0.3.0`。两者使用随工具保存的 HermiT 1.4.3.456 制品与 OWLAPI 4.5.29，先核对 OWL 2 DL profile，再判断所加载本体是否全局一致，并在一致时列出具名不可满足类。[Java 桥接](java/README.md)、[依赖版本、许可证和指纹](vendor/owl-dl/README.md)在本工具目录维护；运行不依赖本机 Protégé 安装，也不会下载依赖。该 HermiT 制品的运行 API 自报版本为 1.4.1.432；记录分别保留制品版本与自报版本，并以 JAR 指纹固定实际后端，不能混为两个不同的执行结果。

两个入口仅处理明确加载的 OWL 模型与事实，不执行 SWRL 或 SHACL；含 SWRL 的输入明确拒绝，不静默剥离规则后声称整包通过。需要 OWL 结果与规则多轮交互时，通过包配置选择 [hermit-swrl-projection-v1](PROJECTION.md)；需要受支持算术与日期时选择 [hermit-swrl-calculation-v1](CALCULATION.md)。后者的时间规范化工作视图是显式配置适配，不改变本独立入口或第三方依赖。`local-rules-v1` 的语义范围保持不变。

加载器处理 unionOf/intersectionOf/oneOf 的 RDF 列表及嵌套限制表达，执行严格解析、未解析三元组检查、OWL 2 DL profile 和真实 HermiT 检查；畸形列表报错。列表和声明顺序兼容处理见[Java加载边界](java/README.md)。

## 运行环境和命令

从 `Ontology/Ontology-tools/` 运行，Python 及依赖按 [README](README.md) 准备，Java 必须可通过 `java` 或 `--java` 指定的可执行文件启动。桥接类采用 Java 8 字节码构建，随包依赖运行基线为 Java 11 及以上；字节码目标不证明所有运行环境已通过测试。首次使用当前环境先执行合成案例，失败时报告环境缺项，不自动联网安装。

以下命令检查随方法库提供的纯 TBox 和独立 ABox；输出目录必须尚不存在，且放在输入包之外。模板中的默认 `integration/merged_ontology.owl` 同时含模型与 SWRL，不用作本检查的输入。

```powershell
# 工作目录：Ontology/Ontology-tools
python -B -X utf8 -m ontology_tools owl-dl `
  --ontology ../templates/ontology/subontologies/demo_ontology.owl `
  --facts ../templates/ontology/data/instances_demo.owl `
  --output ../../ontology-runs/demo-owl-dl-01
$owlDlExitCode = $LASTEXITCODE
```

| 参数 | 含义 |
|---|---|
| `--ontology FILE` | 必需，可重复；明确选择本次要联合检查的本体模块 |
| `--facts FILE` | 可选，可重复；明确选择本次事实快照；事实中的公理也参与实际检查，角色标签不是内容隔离器 |
| `--imports-map FILE` | 可选；需要导入时提供下述本地 Turtle 映射 |
| `--output DIR` | 必需；新建证据目录，不覆盖既有运行 |
| `--java EXECUTABLE` | 可选，默认 `java`；使用指定本地 Java |
| `--timeout SECONDS` | 可选，默认 `60`；Java 执行时限，超时为技术失败 |
| `--candidates FILE` | 仅 `owl-infer` 可用；可选冻结候选范围，否则从实际语义输入建立范围 |

文件按明确支持的 RDF 序列化解析：`.ttl` 为 Turtle，`.owl` / `.rdf` 为 RDF/XML，`.nt` 为 N-Triples。OWL/XML 与 RDF/XML 不同，不按后缀假定可读；需要其他格式时先使用经验证的转换并保存保真证据。RDF/XML DTD、外部实体、SWRL 与未解析的 OWL 结构不能当作正常模型忽略。解码后的 XMLLiteral 也会检查 DTD/实体声明标记；采用保守拒绝，注释中出现同类标记也会失败。类、对象/数据属性等缺少 OWL 2 DL 所需声明也可能使 profile 检查失败；应修复源模型，不能绕过 profile 检查继续声称 OWL DL 通过。参与检查的字段证据可采用正确声明的 OWL 公理注解，或保留在单独 provenance 图；任意 RDF reification 不能假定具有相同 OWL 语义。

相对 IRI 按源文件的绝对文件 URI 解析，文件内明确声明的 `@base` / `xml:base` 按 RDF 语法生效；每份输入的默认文档基准记录为 `ot:documentBase`。需要跨目录搬运且保持实体身份时，源模型应使用稳定的绝对 IRI 或显式绝对 base。`assembled.rdf` 已展开相对 IRI，可用于保留原身份的复跑；不能仅移动原始相对 IRI 文件就假定它的语义不变。

Python API 与 CLI 共用实现：

```python
from pathlib import Path
from ontology_tools import check_consistency

run_dir = check_consistency(
    [Path("model-a.owl"), Path("model-b.owl")],
    Path("../runs/owl-dl-01"),
    facts=Path("facts.ttl"),
    imports=None,
    java="java",
    timeout=60,
)
```

`ontology` 和 `facts` 接受单个 `Path` 或 `Path` 列表。语义检查正常完成时返回输出 `Path`，调用方仍须读取结果；操作失败抛出 `ToolError`；已为本次运行成功建立目录时保留实际错误证据。未建立运行目录前的错误可能没有完整报告。

## 命名分类与事实投影

需要实际推导结果时，使用同样的输入参数调用：

```powershell
python -B -X utf8 -m ontology_tools owl-infer `
  --ontology examples/projection/ontology.ttl `
  --facts examples/projection/inputs/facts.ttl `
  --output ../../ontology-runs/demo-owl-infer-01
```

```python
from ontology_tools import infer_owl

run_dir = infer_owl(
    Path("model.owl"), Path("../runs/owl-infer-01"),
    facts=Path("facts.ttl"), imports=None,
    java="java", timeout=60, candidates=None,
)
```

自动候选范围从实际 OWL 语义签名与逻辑公理中的 literal 建立，不从注释文字抽取数据值。提供候选文件时使用该冻结范围，不在运行中扩张；实际候选图保存为 `candidates.ttl`。类/属性/个体的角色分别记录，不能把同名类当作个体身份合并。

自定义候选文件只有一个 `ot:CandidateDomain` 节点，其 `ot:individual`、`ot:class`、`ot:objectProperty`、`ot:dataProperty` 值为命名 IRI，`ot:literal` 值为 RDF literal。实体须以相应角色存在于实际 OWL 语义签名中；候选文件不加入业务事实或注释。例如：

```turtle
@prefix ot: <https://w3id.org/ontology-tools#> .
@prefix ex: <https://example.org/model#> .
<urn:example:candidates> a ot:CandidateDomain ;
    ot:individual ex:itemA ;
    ot:class ex:Item, ex:EligibleItem ;
    ot:dataProperty ex:status ;
    ot:literal "ready" .
```

这是候选协议示意，须替换为当前模型实际实体；未列入的实体和值不在导出范围内。候选文件只限定可询问的蕴含，不证明这些候选事实已经成立。

检查全部通过后才导出：命名类的子类/等价关系，候选命名个体的类型，对象属性关系，以及个体 `sameAs`。数据属性对候选值逐项做蕴含检查，包括可从 `hasValue` 限制推出的值；不将普通取值 API 返回集合视为全部隐含数据值。匿名存在见证不命名、不导出为业务实体。有限范围的结果不称为“全部 OWL 闭包”。

导出投影省略 `sameAs`、`equivalentClass`、`subClassOf` 的自反恒真三元组，避免无意义增量和 OWLAPI 重载单元素公理的问题；输入快照中的既有身份断言保留。新投影配置按 RDF 1.1 将无语言标签的普通字符串与 `xsd:string` 规范化为同一字符串表示，原始文件字节快照仍保留；旧 `local-rules-v1` 不随之改变。

| 额外文件 | 含义 |
|---|---|
| `input.ttl` | 装配后的语义输入图 |
| `candidates.ttl` | 本次冻结的类、属性、命名个体与数据候选范围 |
| `classification.ttl` | 投影范围内命名类子类及等价关系 |
| `facts.ttl` | 范围内被蕴含的类型、对象/数据属性和个体等价事实 |
| `result.ttl` | `classification ∪ facts` 相对 `input` 新增的三元组 |
| `closure.ttl` | 输入与新增结果并集，作为明确的查询图 |
| `trace.ttl` | 结论对应的实际运行与输入快照级证据 |

`trace.ttl` 不提供逐公理证明或最小冲突解释。全局不一致、存在不可满足命名类、profile 失败或技术失败时，不把已产生的诊断文件交付为有效推导结论。

## 多模块与离线导入

重复 `--ontology` 联合检查明确选中的领域模型。该入口不解释 `integration/load-plan.ttl`，调用方须按项目加载计划核对所选文件；少选了一个模块不能靠一致性报告发现全部业务遗漏。对多个源图保持各自空白节点作用域，原文件不修改。

输入使用 `owl:imports` 时，每个传递导入 IRI 都须显式映射到本地文件。例如保存为 `imports.ttl`：

```turtle
@prefix ot: <https://w3id.org/ontology-tools#> .

[] a ot:ImportMapping ;
   ot:ontologyIRI <https://example.org/shared/1.0> ;
   ot:path "modules/shared.owl" .
```

`ot:path` 相对映射文件所在目录，不能越界或回退远程地址。目标文件必须声明与键匹配的本体 IRI 或版本 IRI；递归导入仍遵守同一映射。缺映射、缺文件、IRI 不符或不支持内容均失败，不联网兜底。检查器保存来源与指纹，完成闭包装配后只在派生检查图中移除已解析的 `owl:imports`，避免 Java 再次解析远程地址；源文件保持不变。多个源的本体头装配为 `urn:ontology-tools:assembled`，源本体身份和版本保留在原文件快照；规范化的是包头元数据，不能据此合并或重命名业务实体。为兼容 OWLAPI 4.5.29 的严格 RDF 解析，装配器对匿名 `owl:Restriction` 补充语义冗余的 `rdf:type owl:Class`，在 `ot:normalizedRestrictions` 与规范化说明中记录；只修改 `assembled.rdf`，不修改源文件。

`ot:ImportMapping` 是本检查器的加载协议，不是 OWL 标准映射格式，也不是源字段映射 `mapping.ttl`。项目若采用其他后端，按该后端实际支持的本地映射说明加载行为。

装配前校验本体头：`owl:versionIRI` 必须是具名本体头上的唯一 IRI，`owl:imports` 必须属于明确声明的本体头；本体头同时充当逻辑实体、或有未声明为注解属性的头部内容时拒绝装配。不能通过头归一丢弃非法声明后再报告一致。

## 结果和退出状态

命名空间 `ot:` 为 `https://w3id.org/ontology-tools#`，运行资源为 `urn:ontology-tools:run`。

| CLI 退出码 | `execution.ttl` 的 `ot:status` | 解释 |
|---|---|---|
| `0` | `passed` | OWL 2 DL 检查完成；本体全局一致，且无具名不可满足类 |
| `1` | `nonconformant` | 检查完成；本体全局不一致，或全局一致但存在具名不可满足类 |
| `2` | `failed` | 输入、profile、依赖、超时或推理器执行失败；没有有效一致性结论 |

`report.ttl` 的报告类型在 `owl-dl` 中为 `ot:OWLConsistencyReport`，在 `owl-infer` 中为 `ot:OWLProjectionReport`。`ot:profileConforms` 记录实际 profile 检查结果；只有推理器真实完成相应判断时才有 `ot:consistent` 布尔值。一致但含不可满足类时 `ot:consistent true`，每个类以 `ot:unsatisfiableClass` 给出 IRI；内置底类 `owl:Nothing` 不计入问题类。全局不一致时，不把所有类随意列成独立缺陷；先修复全局矛盾，再检查类可满足性。

例如，一个类同时属于两个互斥类且没有实例，可能只是该类不可满足，而全局本体仍一致；给这个类加入实例后才可能使整个本体不一致。因此 `consistent=true` 不能单独当作全部检查通过。

两个入口保留 `report.ttl`、`execution.ttl`、`report.md`，以及以下证据；`owl-infer` 另有前述投影文件：

| 文件或目录 | 用途 |
|---|---|
| `inputs/` | 实际读取的原始本体、事实与导入映射快照 |
| `assembled.rdf` | 交给 Java 的离线装配图 |
| `runtime.sha256` | 当前运行器与依赖文件的指纹 |
| `runtime/` | Python、Java 桥接源码/类和依赖声明快照；依赖 JAR 按原工具包指纹核对 |
| `command.txt` | 实际 Java 参数，每行一个参数；不是可直接粘贴执行的 shell 脚本 |
| `java-stdout.txt` / `java-stderr.txt` | 实际 Java 输出与诊断 |
| `manifest.sha256` | 本次运行目录的精确文件清单与指纹 |

读取状态后再解释结果。报告证明所记录输入在该版本后端中的检查结果，不提供最小冲突公理集、逐步证明轨迹、业务批准或事实真实性证明。

## 复核和建模中的使用

本体构建、合并、公共公理或身份变更后，检查完整 TBox 集合与明确选择的 ABox；需要区分问题来源时另外检查纯 TBox。保存模型、事实、导入映射、装配图、程序与依赖版本。

`replay --run <已有运行> --output <新目录>` 支持两个入口：先核验运行清单、快照、程序、依赖及 Java 环境，再从保存的输入和候选范围重新运行，比较全局一致性、不可满足类及适用的分类/事实/结果图。实际完成的 `nonconformant` 也可复核；技术 `failed` 不算可接受的成功重放。复现不一致结论不等于一致性检查通过。

不能仅用新版本重新运行后跳过旧指纹核验，声称“同环境复现”。使用 `--ontology <旧运行>/assembled.rdf` 可以另外执行一次明确标记的新检查，但不替代统一重放的证据与环境核验。时间戳和日志排版不必相同；原始导入加载的审查另看 `inputs/` 及加载证据。

工具已尝试但缺 Java、超时或 profile 不支持时，记录 `failed` 且一致性结论未知；尚未启动的检查标记 `not_run`，项目验收阻塞可标记 `blocked` 并说明原因，不以 SHACL、RDF 解析或大模型阅读代替。检测到真实不一致或不可满足类时保留报告，回到有依据的源公理修复，再生成新的检查记录。SWRL 规则执行仍须由相应后端与独立黄金案例验证；手动组合时显式保存每次事实快照，或使用已声明范围的 [协同配置](PROJECTION.md) 留下逐轮证据。
