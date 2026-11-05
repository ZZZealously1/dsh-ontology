# 格式、版本与遗留数据迁移

## 迁移范围、基线和回退

覆盖三类场景：格式互转、版本升级、旧数据/概念表接入。每次先保存旧文件及来源/版本/字节指纹、规则与约束、输入/预期、依赖与实际后端；列出目标格式/版本、保留与有意变更部分、范围和回退文件。“语义保留、数据无损、可回滚”须落实为可比较证据，不能默认宣称成功。

迁移只写新目录。生产连接、更新和切换均不由本地建模授权推出；本库工具不连接数据库、远程本体或外部API。回退指恢复旧源/映射/加载计划并重建旧集成版本，不自动执行外部回滚。旧包与旧黄金案例继续保留。

## 格式转换

原 `OWL/XML↔Turtle` 代码实为 **RDF/XML↔Turtle**，此处纠正术语。`.owl`/`.swrl`采用RDF/XML；真正OWL/XML须使用另行验证的支持工具。原JSON-LD转换用途归为“其他RDF序列化转换”，由于项目明确不生成JSON，此实现提供RDF/XML、Turtle输出，不生成JSON-LD、不伪装扩展名。

在 `Ontology` 为工作目录：

```powershell
python -B -X utf8 skills/ontology-migration/scripts/local_graph.py convert --source <本地.owl> --format turtle --output <新转换目录>
python -B -X utf8 skills/ontology-migration/scripts/local_graph.py convert --source <本地.ttl> --format xml --output <另一个新转换目录>
```

输入仅为本地 `.owl/.rdf/.swrl`（RDF/XML）、`.ttl`（Turtle）、`.nt`（N-Triples）。XML输入须以 `rdf:RDF` 为根，拒绝DTD/实体声明及OWL/XML；这是辅助工具的保守格式范围。imports三元组只保留、不解析、不联网，图同构报告不证明导入闭包完整。支持单图，不支持命名图数据集。相对IRI以源文件URI或源显式base解析，输出保留解析后的IRI；输入搬家可能改变相对IRI含义，身份跨目录需绝对IRI/base。

脚本关闭RDFLib字面量词法规范化，保留数据类型、语言标签、RDF列表及匿名结构。Turtle结果使用N-Triples子集格式，避免数值缩写把`"007"^^xsd:integer`变成`7`。重新解析输出，要求源图与输出图同构（空白节点标签不影响）；保留源快照和指纹。XML字节排版和前缀可变化，不宣称字节无损；编码、前缀名、注释等非RDF图内容需另有原文件快照。**相同三元组数或差异低于10%都不作为保真条件**。

## 版本升级：新属性与类层次重构

属性新增：记录类IRI、属性IRI、对象/数据属性类型、domain/range、标签、单位/基数/必填约束及来源。domain/range产生类型推断；“给类添加属性”不是自动建立所有实例必填，后者用SHACL。对象属性range是类IRI，数据属性range为正确数据类型/数据范围。

层次重构：列出每个子类的旧父边、新父边、依据、预期分类变化以及受影响规则/shape/事实。保留无关父类，不按字符串局部名盲改全部IRI；继承环可能表示等价，需核对实际意图。

将允许新增写成 `additions.ttl`，待删的**现有具名三元组**写成 `removals.ttl`，然后执行：

```powershell
python -B -X utf8 skills/ontology-migration/scripts/local_graph.py patch --source <原版本.owl> --add <additions.ttl> --remove <removals.ttl> --output <新版本草案目录>
```

`--add`/`--remove`至少一个。待删三元组不存在即拒绝，防止错误版本静默通过；待删图含空白节点时拒绝，因为空白节点ID不跨文件稳定，此时须设计结构匹配迁移并独立验证。新增匿名结构与源空白节点隔离。工具不代填版本号、不自动修改规则/实例、不判断重构语义正确。更新本体版本IRI、文档、加载计划与案例时使用有依据的显式变更，随后重建集成并验收。

## 遗留数据：固定本地导出和RDF映射

关系数据库示例保留“表→类、列→属性、行→实例”方法，执行改为读取用户提供的本地导出。不得执行原 `SELECT *`/连接字符串示例；表名、主键与字段类型来自实际导出及映射，不假设`id`列、单表一行永久代表一个对象。

Excel/CSV先分辨：概念定义表生成TBox，业务记录生成ABox。本地辅助脚本只直接读UTF-8 CSV；Excel先按指定工作表导出值与表头，同时记录原工作簿、工作表、公式值时点、空值规则与导出指纹。脚本不自动选表、不用pandas猜类型/缺值、不把全部表行做类；复杂Excel/复合键/跨表关联需要实际项目适配，不能宣称任意数据库通用迁移。

### 实例映射

映射词汇是工具自有 `urn:ontology:local-migration:`，不是通用RDF标准。每个CSV一个映射：

```turtle
@prefix m: <urn:ontology:local-migration:> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
[] a m:Mapping ; m:mode "instances" ; m:keyColumn "零件编号" ;
  m:baseIRI <urn:example:part:> ; m:targetClass <urn:example:model:SparePart> ;
  m:field [ m:column "零件名称" ; m:property <urn:example:model:name> ;
            m:datatype xsd:string ; m:missing "error" ] ;
  m:field [ m:column "数量" ; m:property <urn:example:model:quantity> ;
            m:datatype xsd:integer ; m:missing "error" ] ;
  m:ignore [ m:column "导出备注" ; m:reason "项目已确认仅为导出说明，原值保留在快照" ] .
```

源主键必须非空、无首尾空白且本文件唯一；IRI由明确base加百分号编码的键生成，编码不等于证明跨快照业务身份。缺键、重复键、重复表头、列数错、未映射且未明确忽略的列都失败，不能静默丢失。多个字段映到同一列、拆分/聚合、复合键或去重需项目适配，辅助工具不猜。

每个字段指定 `m:datatype` 或 `m:iriBase` 二选一。后一种将源值编码到给定IRI前缀，可表达对象关系，但**不核实目标实体存在**，迁移后须用端点集合/SHACL独立检查悬空引用。数据类型支持string、integer、decimal、boolean、date（YYYY-MM-DD）、dateTime（ISO格式到秒，可带小数秒/时区）；超范围类型明确拒绝，不转成字符串混过。

空字符串的 `m:missing` 必须明确为 `error`、`omit`、`empty-string`（仅string）；没有默认补零或默认False。`omit`只影响该字段，原CSV值仍保留；实际源中NULL编码、接口失败、空串含义不同，应在导出/项目适配中区分，本脚本不能从空串恢复缺失原因。数值保留词法形式，如整数`007`，并验证合法数值；日期/时区口径由项目约束进一步确认。

### 概念定义表映射

```turtle
@prefix m: <urn:ontology:local-migration:> .
[] a m:Mapping ; m:mode "classes" ; m:keyColumn "类标识" ;
  m:baseIRI <urn:example:catalog:> ;
  m:labelColumn "类名" ; m:parentColumn "父类标识" ; m:commentColumn "说明" .
```

保留原示例的类名、父类、说明，区分稳定类标识与中文标签。每行声明 `owl:Class`、中文label，非空说明转中文comment；父类以同一导出内的键关联，父键不存在即拒绝。没有父类的空值表示该导出未指定父边，不自动添加业务父类。跨模型父类需另行显式映射；不要将中文文本直接拼出不稳定IRI。

两种模式共用命令：

```powershell
python -B -X utf8 skills/ontology-migration/scripts/local_graph.py csv-import --source <本地.csv> --mapping <mapping.ttl> --output <新迁移目录>
```

输出的 `report.ttl`以 `sourceRecord`记录CSV数据记录序号、业务键与目标实体对应；首条数据记录为1，不包含表头，含引号内换行也只算一个记录，不能把它解释为物理文本行号。支持范围是明确字段映射，不推导业务规则，不自动生成完整TBox声明/SHACL。输出事实须与目标模型合并后验证类型、单位、集合完整性和端点。

## 验证与交付

格式转换：图同构；模型变更：明确增删集合、目标公理和新旧独立能力问题；数据迁移：源业务键集合与目标对应、每个字段的值/类型、成功/拒绝/未映射集合、关系端点、重复和单位/时间转换。不能只比较总量；空源或所有记录被过滤需要明确完整性决定，不默认为成功。

共同输出包括 `result.ttl`或`result.owl`、`inputs/`、`runtime/`、`report.ttl`、`report.md`、`manifest.sha256`；运行脚本快照与指纹保存在证据中。输出必须在Ontology方法库、源本体包和已有运行包之外，不能污染冻结包。CLI0仅表示该本地转换/映射检查成功，CLI2表示失败；成功报告明确 `consistencyChecked false`、`importsResolved false`。未创建输出目录前的失败可能无报告，已生成的部分产物不能当成功。保留失败日志并修正输入/映射，再用新目录重跑。

后续必须选择适用的[五层验证](../../ontology-validation/SKILL.md)：目标模型OWL DL一致性、数据SHACL、真实规则执行与受影响黄金案例。拆分/改名/接口类型调整的语义变更另记录，不能以格式转换同构替代业务验收。

报告应列来源/目标版本、文件/工具指纹、映射依据、转换命令、身份/字段/例外统计、实际检查、失败和未执行项、原新差异及回退说明。保留原八项清单：备份原始文件、记录映射、执行转换、检查语法、验证保真、执行一致性检查、运行测试、记录迁移日志；“执行一致性检查”仍须实际工具证据。
