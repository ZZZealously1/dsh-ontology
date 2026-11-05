# OWL 2 DL Java bridge

`OwlDlCheck.java` 使用随包 OWLAPI 4.5.29 与 HermiT 1.4.3.456，检查一个已经本地装配的 RDF/XML 本体。它先进行 OWL 2 DL profile 检查，通过后实际调用 HermiT `isConsistent()`；仅当本体一致时，调用 `getUnsatisfiableClasses()` 并排除 `owl:Nothing`。不可满足类与整体不一致分开报告。

源码和已编译的 Java 8 字节码都在此目录。随包依赖运行基线采用 Java 11 及以上；重新编译需要支持 `--release 8` 的 JDK。不需要 Maven、Protégé、网络或原依赖来源目录。底层库在较新 JDK 上可能将兼容性提示写入 stderr；stdout 仅用于协议。

从 `Ontology-tools/` 运行：

```powershell
python -B java/build.py --check
python -B java/build.py
java '-Dfile.encoding=UTF-8' -cp 'java/classes;vendor/owl-dl/lib/*' OwlDlCheck assembled.rdf
java '-Dfile.encoding=UTF-8' -cp 'java/classes;vendor/owl-dl/lib/*' OwlDlCheck assembled.rdf candidates
java '-Dfile.encoding=UTF-8' -cp 'java/classes;vendor/owl-dl/lib/*' OwlDlCheck assembled.rdf infer candidate-domain.tsv
```

POSIX 的 classpath 分隔符为 `:`。业务使用应通过 Python CLI，不能直接把包含 SWRL 的集成图塞进此桥。

## 加载边界

- 使用安全 XML 预检，禁止 DTD、外部实体和 imports；OWLAPI IRI mapper 再次拒绝导入解析。
- 仅启用 RDF/XML parser，`strict=true`、禁止 illegal-punning 修复；检查 parser metadata，出现未解析三元组即报错，不把剩余图当完整本体。
- OWLAPI 4.5.29 流式处理会消耗列表边，后续严格转换器再次查找这些边时可能拒绝合法的 unionOf/intersectionOf/oneOf。桥为列表提供只读的原始边缓存，并将原有 `rdf:type` 声明先交给 consumer，处理匿名表达式对声明顺序的依赖。不添加命名类/属性声明，不切换到 lax 模式；重复 first/rest、资源/字面量 first 冲突、字面量 rest、循环和断链均拒绝。
- 多个表达式可以共用列表尾节点。缓存同时用于严格校验查询和实际 list translator 的 `getFirstResource`/`getRest` 读取；先调用原消费方法，再返回原始成员，`rdf:nil` 按库接口转换为终止值。否则第二次读取可能静默丢失约束，未解析三元组检查本身不能发现。资源交集与字面量枚举的共享尾部均有真实语义回归。
- 当前OWL检查入口还拒绝一条列表链跨节点混用资源和字面量，以避免库将错误的混合枚举静默截短；这不是通用RDF列表的格式限制，SWRL参数列表也不在本入口处理范围。
- 必须先本地解析完整 imports 闭包并归一到一个本体头。不能以删除 imports 后只检查入口图代替闭包检查。SWRL 不属于本检查范围，桥发现 SWRL 直接拒绝。
- OWLAPI 4.5.29 的 strict RDF parser 不将仅声明为 `owl:Restriction` 的匿名节点登记为类表达式。Python 装配步骤为这些匿名节点补显式 `rdf:type owl:Class`，这是冗余的解析兼容声明，不修改源模型；新增声明和头归一必须记录在装配证据中。不得补缺失的命名类或属性声明来掩盖错误。
- 一致性与分类没有执行完成时，不输出可用的 `CONSISTENT` 结论；调用方必须设置进程超时并把超时/错误记为未完成。

## stdout 协议

每行 `KEY<TAB>VALUE`，UTF-8，无 JSON。首行 `PROTOCOL\towl-dl-v1`，正常完成末行为 `END\towl-dl-v1`。值为完整字符串，含空白的诊断、IRI使用 UTF-8 Base64。

| Key | 内容 |
|---|---|
| `OWLAPI`、`HERMIT_ARTIFACT` | 随包依赖版本 |
| `JAVA_VERSION`、`JAVA_VENDOR` | 实际 Java 环境 |
| `AXIOMS`、`LOGICAL_AXIOMS` | OWLAPI 实际加载数量 |
| `PROFILE` | `true` 或 `false` |
| `VIOLATION` | 每条 profile 违规的 Base64 文本，可重复 |
| `REASONER`、`VERSION` | 推理器运行时报告的名称/版本；当前 HermiT 自报 `1.4.1.432`，与包版本不同，均保留 |
| `CONSISTENT` | HermiT 执行结果，profile 不通过时不存在 |
| `UNSAT` | 每个不可满足命名类 IRI 的 Base64，排序后输出；整体不一致时不输出 |
| `ERROR` | Base64 错误内容，退出码 2，无完成标记 |

已完成但发现不一致、不可满足类、profile 不通过时，桥退出码为 0；Python CLI 负责将检查结果映射为验收失败。不能仅凭进程退出码或找到 `CONSISTENT` 行判断成功，必须检查完整协议与 `END`。

## 有限命名事实投影

`candidates` 和 `infer` 模式使用 `owl-projection-v1` 协议；原有单参数检查仍使用 `owl-dl-v1`。`candidates` 只提取通过完整加载与 OWL 2 DL profile 校验后的语义签名及逻辑公理字面量，不运行 HermiT、不输出一致性结论。逻辑公理的注释、实体标签和本体注释不进入候选字面量。

`infer` 在一致性及命名类可满足性检查通过后，输出有限候选域内的命名类上下位／等价、个体类型、对象属性、数据属性、`sameAs`。排除 `sameAs(a,a)`、`equivalentClass(A,A)` 和 `subClassOf(A,A)` 自反恒真式：它们没有新增业务含义，前两类回读时可能被 OWLAPI 转为违反最小元数的单实体公理。数据属性逐个调用 `isEntailed` 检查候选值；不以 `getDataPropertyValues` 代替蕴含检查。不创建匿名存在约束的命名见证。

可选的 `candidate-domain.tsv` 由 Python 从 `ot:CandidateDomain` Turtle 生成，是投影范围元数据，不作为本体事实加载。提供后不再扩大范围；每个实体角色必须存在于已加载语义签名中，内建 OWL 实体除外。未提供时自动抽取。候选域中的语言字面量和字符串按 RDF 1.1 的 `rdf:langString`／`xsd:string` 输出，兼容 OWLAPI 4 内部的 `rdf:PlainLiteral` 表示。

协议增加 `MODE`、`CAND_INDIVIDUAL/CLASS/OBJECT/DATA/LITERAL`、`SUBCLASS/EQUIVALENT/TYPE/SAME/OBJECT/DATA` 行。每个数据字段独立采用 UTF-8 Base64 编码；命名三元组和候选行都需通过数量与 `PROJECTION_SHA256` 完整性校验。Python 再校验实体类型、精确冻结域和输出范围。未完成、全局不一致或存在不可满足命名类时不输出可接受的投影行；完整协议验证前不能接受部分输出。

依赖来源和许可证记录见 [vendor/owl-dl](../vendor/owl-dl/README.md)。重编译会更新本目录 `manifest.sha256`；依赖清单验证失败时停止编译。
