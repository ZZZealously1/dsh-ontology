# 标准文档建模完整参考模型

本参考模型提供标准文档的实体目录、属性、规则主题与检查项。**参考模型及示例资产不能充当国标符合性证据。** 项目声明符合某项标准前，必须核对正式标准全文、版本、适用条款及逐项证据；标准名称、编号、发布日期和生效状态也须由实际来源确认。

阅读次序：通用要求 → 实体目录 → 对象/数据属性表 → 规则 → 扩展 → 模板 → 逐项检查。采用状态、来源定位、调整理由写入项目 design/provenance 文档；完整性不等于必须把整份参考模型塞进每个业务本体。

## 使用前必须分清的语义

- 下方实体树是知识目录。StandardEntity 代表标准文件，不应由目录缩进推出 Organization、Property 等都是标准文件；资产仅保留各真正分支内的候选 subclass 关系。
- 发布机构与出版机构分别使用 IssuingOrganization / PublishingOrganization；标准与条款的约束类型分别使用 standardConstraintType / clauseConstraintType。接入已有数据时明确别名与映射，不静默重命名既有实例。
- NormativeReferences 的父类须由正式来源核验，当前资产不对其声明父类。其他目录分类也仅为可选参考。
- 对象属性表中的 A/B 表示并集；重复 rdfs:domain 声明表示交集。domain/range 会推导类型，不是数据校验。hasNormativeElement 在本参考模型中覆盖两类 ContentElement，不能仅凭名称把它理解为只包含规范性要素；项目采用其他命名时记录映射。
- owl:hasKey 和 FunctionalProperty 不代替闭世界唯一性/必填检查；不同 IRI 默认不保证不同个体。唯一发布机构、强制枚举、层次禁配等均需项目确认后启用。
- 日期语义与后端支持的数据类型须分别确认；可执行合成模板明确使用 ISO YYYY-MM-DD 字符串并以 SHACL 检查词法与次序，不自动改变真实项目日期。跨时区或带时间输入必须另定映射。日期真实有效性还需源解析器核验，正则不能证明日历有效。

## 参考模型的通用要求

### 建模通用要求

以下要求用于设计与评审，项目适用性须有来源依据：

```markdown
□ 实体定义与标准文本中的描述顺序无关
□ 以标准文件的知识内容和语义关系为核心，同时兼顾其组成结构信息
□ 将标准的要素内容与表述形式分开表达
  - 条款和附加信息为要素内容
  - 条文、图、表等为表述形式
  - 要素内容与表述形式为两类独立实体类型
□ 实体类型及关系的定义应面向跨领域、跨系统的知识共享，避免局部语境依赖
```

### 本体核心组成

本参考模型的基本组成：

```markdown
□ 实体类型：表示具有相同属性的实体集合的抽象
□ 属性：
  - 数据属性：描述实体类型的内在特征
  - 对象属性：描述实体类型间关系
□ 公理：定义实体类型与属性的逻辑约束
```

### 形式化要求

```markdown
□ 应采用W3C推荐的本体描述语言（RDF/RDFS、OWL 等；XML 本身只是语法载体）
□ 应使用标准化的序列化格式（如RDF/XML、Turtle 等；本项目不生成 JSON 或 JSON-LD）
□ 应支持基于SHACL的约束验证
```

### 命名方式

```markdown
□ XML命名空间格式：http://example.org/standard-ontology#
  - "example.org"仅为示例占位域名；正式命名空间使用项目确认的稳定IRI
  - "standard-ontology"为标准本体的文档名
□ 每个实体类型、属性均具有全球唯一IRI
□ IRI = XML命名空间 + 本地标识符
□ 实体类型命名：UpperCamelCase（首字母大写）
□ 属性命名：lowerCamelCase（首字母小写）
□ 所有实体应有rdfs:label标签，支持多语言（zh/en）
```

---

## 核心实体类型定义

### 实体类型确定要求

以下要求用于设计与评审，项目适用性须有来源依据：

```markdown
□ 根据标准的知识层次逻辑，将相同或相近语义的知识片段归纳概括为实体类型
□ 实体类型应根据对应实例的细分程度进行定义：
  - 尽可能细化以保证标准的所有语义可展示
  - 恰当切分以避免语义关系缺少和错乱
□ 应根据在标准中的作用定义实体类型及层次结构
□ 实体类型应能在语境中实现对齐和映射
□ 相同实体类型的近义词不应被表示为多个实体类型
□ 现有标准中有相对应概念的，应使用现有标准中的概念名称
□ 当现有本体已存在相关实体类型，应采用现有本体的实体类型
```

### 核心实体类型体系

参考实体目录如下。项目按能力问题选择适用内容，不能据此断言正式标准要求全部使用。

```
StandardEntity (标准实体；以下顶层项是概念目录，不自动断言是其子类)
├── StandardizationObject (标准化对象)
├── Stakeholder (相关方)
│   ├── Organization (机构)
│   │   ├── IssuingOrganization (发布机构)
│   │   ├── Proposer (提出单位)
│   │   ├── Administrator (归口单位)
│   │   ├── Implementer (组织实施单位)
│   │   ├── Drafter (起草单位)
│   │   ├── Suggester (建议方)
│   │   ├── Consultee (征求意见单位)
│   │   └── PublishingOrganization (出版机构)
│   └── Individual (个人)
│       ├── DraftingPerson (起草人)
│       └── Reviewer (评审人)
├── DomainCategory (领域类别)
│   ├── ICS (国际标准分类)
│   └── CCS (中国标准文献分类)
├── ContentElement (要素)
│   ├── NormativeElement (规范性要素)
│   │   ├── Scope (范围)
│   │   ├── TermsAndDefinitions (术语和定义)
│   │   ├── SymbolsAndAbbreviations (符号和缩略语)
│   │   ├── CoreTechnicalElement (核心技术要素)
│   │   └── OtherTechnicalElement (其他技术要素)
│   └── InformativeElement (资料性要素)
│       ├── NormativeReferences (规范性引用文件；归类待正式来源核验)
│       ├── Bibliography (参考文献)
│       └── Index (索引)
├── StructuralElement (层次)
│   ├── Section (章)
│   ├── Clause (条)
│   │   ├── TitledClause (有标题条)
│   │   ├── UntitledClause (无标题条)
│   ├── Paragraph (段)
│   ├── ListItem (列项)
│   │   ├── NumberedListItem (有编号列项)
│   │   ├── UnnumberedListItem (无编号列项)
├── InformationUnit (信息单元)
│   ├── ClauseContent (条款)
│   ├── AdditionalInfo (附加信息)
│   │   ├── Example (示例)
│   │   ├── Note (注)
│   │   ├── Footnote (脚注)
│   │   ├── Checklist (清单)
│   │   ├── List (列表)
├── InformationForm (信息单元表述形式)
│   ├── TextualParagraph (条文)
│   ├── Figure (图)
│   ├── Table (表)
│   ├── MathematicalFormula (数学公式)
│   ├── Appendix (附录)
│   ├── Reference (引用)
│   ├── Tip (提示)
├── Object (对象)
│   ├── StandardObject (标准对象)
│   ├── IndicatorObject (指标对象)
├── Property (特性)
│   ├── DescriptiveProperty (描述型特性)
│   ├── CapabilityProperty (能力型特性)
│   ├── ConstraintProperty (约束型特性)
├── Constraint (约束逻辑)
├── ActionClass (行动)
│   ├── Action (动作)
│   ├── Path (路径)
│   ├── Condition (判断条件)
├── ExternalResource (外部约束)
│   ├── Regulation (法规)
│   ├── Patent (专利)
│   ├── Literature (文献)
│   ├── PublicDatabase (公共数据库)
├── StandardizationProcess (制定程序)
│   ├── PreparationStage (预备阶段)
│   ├── ProjectApprovalStage (立项阶段)
│   ├── DraftingStage (起草阶段)
│   ├── PublicConsultationStage (征求意见阶段)
│   ├── TechnicalReviewStage (技术审查阶段)
│   ├── ApprovalAndReleaseStage (批准发布阶段)
│   ├── PublicationStage (出版阶段)
│   ├── ReviewStage (复审阶段)
│   ├── AbolitionStage (废止阶段)
└── Term (术语)
```

---

## 属性定义

### 通用要求

```markdown
□ 属性应准确、稳定
□ 父类应只保留所有子类真正共有且语义一致的核心属性
□ 数据属性：描述实体类型内在特征
□ 对象属性：描述实体类型间关系
□ 某个实体类型的数据属性应仅描述该实体类型自身的属性
□ 数据属性不应具有传递性、对称性或互逆性
```

### 核心对象属性表

以下为 34 项对象属性参考。编号用于表内定位；与正式标准条款的对应关系须由项目核验。

| 序号 | 中文属性名 | 英文属性名 | 定义域 | 值域 | 语义说明 |
|------|------------|------------|--------|------|----------|
| 1 | 采用 | adopts | StandardEntity | StandardEntity | 表示本标准采用（等同、修改）了另一个标准的内容 |
| 2 | 代替 | replaces | StandardEntity | StandardEntity | 表示新版标准代替旧版标准 |
| 3 | 引用标准 | cites | StandardEntity | StandardEntity | 表示标准在内容中引用了另一个标准 |
| 4 | 参考 | references | StandardEntity | StandardEntity | 表示标准资料性参考了另一个标准 |
| 5 | 有部分 | hasPart | StandardEntity | StandardEntity | 表示本标准由多个部分系列标准组成 |
| 6 | 发布于 | issuedBy | StandardEntity | Organization | 表示标准由某机构正式发布 |
| 7 | 提出于 | proposedBy | StandardEntity | Organization | 表示标准由某单位提出 |
| 8 | 归口于 | administeredBy | StandardEntity | Organization | 表示标准由某单位归口管理 |
| 9 | 起草于 | draftedBy | StandardEntity | Organization/Individual | 表示标准由某起草单位或起草人起草 |
| 10 | 出版于 | publishedBy | StandardEntity | Organization | 表示标准由某出版机构出版 |
| 11 | 属于领域 | classifiedUnder | StandardEntity | DomainCategory | 表示标准按领域分类（如ICS、CCS） |
| 12 | 标准化对象 | standardizes | StandardEntity | StandardizationObject | 表示本标准所规范的主题对象 |
| 13 | 包含要素 | hasNormativeElement | StandardEntity | ContentElement | 表示标准包含规范性要素或资料性要素 |
| 14 | 包含层次 | hasStructuralElement | StandardEntity/StructuralElement | StructuralElement | 表示标准或其内部结构包含章、条、段等层级结构 |
| 15 | 包含条款 | hasClause | ContentElement/StructuralElement | InformationUnit | 表示标准的某个要素或结构层次包含了一个具体的条款 |
| 16 | 包含子条 | hasSubClause | Clause | Clause | 表示条包含子条，用于构建层次结构 |
| 17 | 界定 | defines | StandardEntity/ContentElement | Term | 表示标准或"术语和定义"要素界定了某个术语 |
| 18 | 提及术语 | usesTerm | InformationUnit | Term | 表示信息单元提及了某个术语 |
| 19 | 具有表述形式 | hasRepresentationForm | InformationUnit | InformationForm | 表示信息单元有内容形式（条文、图、表等） |
| 20 | 有示例 | hasExample | ClauseContent | AdditionalInfo | 表示条款关联示例 |
| 21 | 有注 | hasNote | ClauseContent | AdditionalInfo | 表示条款关联注 |
| 22 | 引用标准条款 | citesStandard | ClauseContent | StandardEntity | 表示条款内容中引用了某个标准 |
| 23 | 引用章条 | referencesClause | InformationUnit | StructuralElement | 表示条款引用了本标准内的章、条、段、列项 |
| 24 | 涉及对象 | involvesObject | ClauseContent | Object | 表示条款内容中提及或描述的实体 |
| 25 | 规定特性 | specifiesCharacteristic | ClauseContent | Property | 表示条款对某个对象的特性做出了规定 |
| 26 | 有特性 | hasCharacteristic | Object | Property | 表示对象具有某种可量化或描述的属性特征 |
| 27 | 施加约束 | imposesConstraint | InformationUnit/Property | Constraint | 表示条款或特性包含了具体的约束条件 |
| 28 | 约束对象 | constrainsObject | Constraint | Object | 表示约束条件应用于某个对象 |
| 29 | 约束特性 | constrainsCharacteristic | Constraint | Property | 表示约束条件应用于对象的某个特定特性 |
| 30 | 描述行动 | describesAction | InformationUnit | ActionClass | 表示条款规定需执行的动作或步骤 |
| 31 | 引用外部资源 | referencesExternalResource | StandardEntity/ClauseContent | ExternalResource | 表示标准或条款引用了法规、专利、文献等外部资源 |
| 32 | 与专利有关 | isRelatedToPatent | ClauseContent | Patent | 表示条款的技术内容与某项专利有关 |
| 33 | 处于阶段 | hasDevelopmentStage | StandardEntity | StandardizationProcess | 表示标准当前所处的生命周期阶段 |
| 34 | 包含标准 | includesStandard | StandardizationProcess | StandardEntity | 制定程序阶段包含处于该阶段的标准 |

### 核心数据属性

以下为 19 项数据属性参考；与正式标准条款的对应关系须由项目核验。

#### 标准实体（StandardEntity）数据属性

| 属性名 | 英文名 | 类型 | 说明 |
|--------|--------|------|------|
| 文件编号 | standardNumber | xsd:string | 文件编号；GB/T 1.1 格式映射待正式来源核验 |
| 文件名称 | documentName | xsd:string | 标准的完整名称 |
| 发布日期 | issuedDate | xsd:date | 标准的官方发布日期（YYYY-MM-DD） |
| 实施日期 | effectiveDate | xsd:date | 标准开始实施的日期 |
| 编制目的 | purpose | xsd:string | 说明该标准的制定目标 |
| 语言版本 | languageVersion | xsd:string | 枚举：中文版本、英文版本 |
| 标准状态 | status | xsd:string | 枚举：草案、现行、废止、修订中 |
| 约束类型 | standardConstraintType | xsd:string | 枚举候选：强制性、推荐性 |

#### 组织（Organization）数据属性

| 属性名 | 英文名 | 类型 | 说明 |
|--------|--------|------|------|
| 名称 | orgName | xsd:string | 机构的法定或通用名称 |
| 统一信用代码 | creditCode | xsd:string | 作为字符串保存，正式长度、代码格式与校验位须按适用来源核验 |
| 所在地 | orgLocation | xsd:string | 机构的实际办公或注册地址 |

#### 个人（Individual）数据属性

| 属性名 | 英文名 | 类型 | 说明 |
|--------|--------|------|------|
| 姓名 | personName | xsd:string | 个人法定姓名 |
| 所属单位 | affiliation | xsd:string | 个人所属的机构或组织名称 |
| 联系电话 | phone | xsd:string | 示例：+86-区号-号码；不能据此排除手机或其他地区号码 |
| 联系地址 | address | xsd:string | 个人联系地址 |

#### 信息单元（InformationUnit）数据属性

| 属性名 | 英文名 | 类型 | 说明 |
|--------|--------|------|------|
| 唯一标识符 | uniqueIdentifier | xsd:string | 信息单元的唯一编码（如IU-001） |
| 内容描述 | contentDescription | xsd:string | 信息单元的详细描述文本 |

#### 条款（ClauseContent）数据属性

| 属性名 | 英文名 | 类型 | 说明 |
|--------|--------|------|------|
| 条款类型 | clauseType | xsd:string | 枚举：要求型、推荐型、指示型、允许型、陈述型 |
| 约束类型 | clauseConstraintType | xsd:string | 枚举候选：强制、推荐、描述 |

---

## 公理与规则

### 通则

参考模型以公理表达类型、属性与实例间约束。

### 核心规则要求

逐项评估以下候选规则；只有来源确认后才能作为项目规则启用：

#### a) 实体类型规则

```markdown
□ 实体类型不相交规则：互斥的实体类型应声明不相交
  - 规范性要素与资料性要素互斥
  - 章与条互斥（作为层次子类）

□ 全局唯一标识规则：需要唯一标识的实体类型应定义唯一性约束
  - 信息单元需要全局唯一标识符
  - 标准实体需要唯一的标准编号
```

OWL示例：
```turtle
# 不相交声明
:NormativeElement owl:disjointWith :InformativeElement .
:Section owl:disjointWith :Clause .

# 唯一键约束
:InformationUnit owl:hasKey (:uniqueIdentifier) .
:StandardEntity owl:hasKey (:standardNumber) .
```

#### b) 属性规则

```markdown
□ 属性唯一性约束规则：需要保持唯一值的属性
  - 标准编号需保持唯一性

□ 日期有效性验证规则：具有时序关系的日期属性
  - 实施日期应晚于或等于发布日期

□ 枚举值约束规则：取值需要限定的属性
  - 标准状态取值限定在预定义枚举范围内

□ 取值约束规则：具有特定取值范围的属性
  - 约束类型取值限定为强制性或推荐性
```

对应可解析资产见 [候选规则与约束](assets-and-validation.md)。日期先后用 SHACL 检查已知值；日期异常分类另提供原生 SWRL 合成示例。该示例按明确的 ISO 日期字符串比较，不能替代真实日期类型、日历有效性或时区验证；结构可解析也不证明已经执行。

`issuedBy a owl:FunctionalProperty` 表示最多一个对象值（可能推出两个名称是同一个机构），并不表示恰好一个发布机构，也不应在无来源时启用。标准可能联合发布；源材料若没有“最多一个”限制则不加此公理。

#### c) 关系规则

```markdown
□ 功能性属性约束规则：具有功能性约束的对象属性
  - 每个标准只能由一个机构发布

□ 版本替代关系规则：实体间的替代关系
  - 废止标准必须指向替代标准或标明废止日期

□ 层次结构约束规则：
  - 父子层级包含关系：章可包含零个或多个条
  - 结构限制规则：无标题条不可包含任何子条

□ 引用关系区分规则：不同类型的引用关系需区分
  - 标准间引用与条款引用通过不同属性实现
```

---

## 扩展方式和原则

### 扩展基本原则

扩展时按下述参考原则逐项确定项目约定：

```markdown
□ 扩展的实体类型、属性和关系应采用新的命名空间
□ 扩展的实体类型、属性和关系的名称不应与已有名称相同和定义相矛盾
□ 扩展内容应满足本文件所规定的约束条件，可在已有约束条件基础上进一步限定
□ 针对行业特有的标准本体建模，以模块化形式扩展
□ 不同行业的特殊知识应通过扩展实体类型的子类和属性来实现，不应修改核心定义
```

### 扩展命名空间规范

```turtle
# 核心本体命名空间
@prefix core: <http://example.org/standard-ontology#> .

# 行业扩展命名空间（示例：电力行业）
@prefix power: <http://example.org/power-standard-ontology#> .

# 行业扩展命名空间（示例：核电行业）
@prefix nuclear: <http://example.org/nuclear-standard-ontology#> .

# 扩展类定义示例
power:PowerStandard a owl:Class ;
    rdfs:label "电力标准"@zh ;
    rdfs:subClassOf core:StandardEntity .
```

---

## OWL本体模板

[standard-model.owl](../assets/standard-model.owl)使用 RDF/XML，包含本体头、双语标签、核心类及注释、真实继承关系、34 项对象属性和 19 项分域数据属性，另有日期异常与废止日期辅助定义。候选不相交、信息单元与标准编号键、发布机构功能性、层次限制另放候选公理文件；加载方式见[资产与校验说明](assets-and-validation.md)。

使用模板时区分目录与继承，确保包括 Term 在内的全部被引用概念已声明；斜杠域/值域按语义使用 unionOf；机构角色与约束类型保持消歧。需要互斥、键或发布机构数量约束时，逐项确认候选公理适用性。

---

## 验证检查清单

以下要求用于设计与评审，项目适用性须有来源依据：

### 基本要求验证

```markdown
□ 实体定义是否与标准文本描述顺序无关
□ 是否以知识内容和语义关系为核心
□ 是否将要素内容与表述形式分开
□ 实体类型是否面向跨领域共享
```

### 形式化要求验证

```markdown
□ 是否使用W3C推荐的本体语言（OWL/RDFS）
□ 是否使用标准化序列化格式
□ 是否支持SHACL约束验证
□ 命名空间是否符合规范
□ IRI是否唯一且格式正确
```

### 核心实体类型验证

```markdown
□ 是否包含所有核心实体类型
□ 实体类型层次结构是否正确
□ 不相交类是否正确声明
□ 唯一键约束是否定义
```

### 属性验证

```markdown
□ 对象属性定义域/值域是否正确
□ 数据属性类型是否正确
□ 核心对象属性是否全部定义
□ 属性命名是否符合规范
□ 有依据且适用的功能性/反功能性属性是否声明；不要为所有属性添加
```

### 公理验证

```markdown
□ 不相交规则是否定义
□ 唯一性约束是否定义
□ 日期有效性规则是否定义
□ 枚举值约束是否定义
□ 层次结构约束是否定义
```

### 扩展验证（如有扩展）

```markdown
□ 扩展是否使用新命名空间
□ 扩展是否与核心定义不矛盾
□ 扩展是否满足核心约束条件
□ 扩展是否采用模块化形式
```

---

## Red Flags - STOP and Fix

以下情况应检查来源并定位原因，不能自动修改真实数据使其通过：

```markdown
□ 已确认范围内的核心实体类型缺失 → 补充或记录不适用依据
□ 命名空间不符合规范 → 必须修正
□ IRI不唯一 → 必须修正
□ 不相交类有共同实例 → 必须修正分类
□ 标识重复 → 区分同一实体别名与重复记录，SHACL 查重并复核身份；OWL hasKey 可能合并身份而不是报错
□ 发布日期晚于实施日期 → 报告冲突，核对原件与例外；不自行改日期
□ 扩展修改核心定义 → 复核兼容性并受控演进；无授权依据的修改回退
```

---


## 配合方法与参考资料

本专题在[总构建流程](../../ontology-builder/SKILL.md)的标准文档场景使用；规则设计见[规则设计与实现](../../ontology-inference-design/SKILL.md)，验证、融合和迁移分别进入对应专题；语法见[OWL/SWRL参考](../../../references/owl-swrl/index.md)。它不是其他所有业务建模的强制前置。

按项目范围核对标准数字化、本体建模、标准编写、元数据注册与分类等适用标准。记录正式编号、版本、条款定位、适用理由与证据；参考模型本身不证明标准有效、适用或已经符合，也不构成项目批准。
