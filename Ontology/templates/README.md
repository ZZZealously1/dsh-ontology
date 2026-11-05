# 模板使用方法

先按[总入口](../skills/ontology-builder/SKILL.md)选择文档十阶段、知识库六阶段或专项方法，再在相应阶段填写模板，保存设计、产物和执行证据。

| 模板 | 使用时机 | 填写要点 |
|---|---|---|
| [business-brief.md](business-brief.md) | 接收业务资料 | 直接引用已有信息，未知项不猜测 |
| [project-design.md](project-design.md) | 概念/属性/规则设计及评审阶段 | 建模方法、阶段产物与适配依据；能力问题、领域/身份、条件、后端与缺口 |
| [domain-doc.md](domain-doc.md) | 生成每域说明文档 | 范围与素材、概念/属性定义、规则依据、数据、命令及实际验收；写入docs/ |
| [完整说明书字段](../skills/ontology-builder/references/full-domain-document.md) | 需要逐类、逐属性、逐规则详细说明时 | 保留概述、完整定义、公式与算例、使用、测试及附录全部字段 |
| [runtime-SKILL.md](runtime-SKILL.md) | 包装可执行项目 | 填实际入口、输入/输出、后端和停止条件 |
| [acceptance.md](acceptance.md) | 验证/测试阶段 | 对照建模要求记录实际执行、覆盖、日志与未完成项 |
| [ontology](ontology/README.md) | 学习或复制原生文件结构 | 合成Item标签分类；领域源、规则、ABox、加载清单及可重建集成；未配置业务推理后端 |
| [RAG构建与测试模板](rag-build/README.md) | 从检索材料建立可重复构建的本体 | 原生语义源、通用构建/测试脚本、完整示例及能力边界 |

业务信息与设计记录随建模主流程逐步补齐；进入生成阶段时，可将 `ontology/` 模板复制到用户指定项目目录，替换示例命名空间、来源和规则。运行期Skill与验收模板在 `ontology/` 根目录填写。根据实际后端补齐runtime、依赖与命令，验收后再生成manifest.sha256。

新项目按领域生成 `subontologies/`、`rules/<domain>/`、`data/`、`integration/` 与 `docs/`；单域只需一组源。模型与规则是维护源，集成文件由源重建；默认不混入动态事实。旧扁平业务包不因本模板更新而迁移。详细规范见 [领域组织方法](../references/domain-organization.md)。

示例提供 `scripts/build_integration.py` 和构建依赖，能实际读取其 `load-plan.ttl` 并校验生成物；它不是推理运行器，也不是现有 `Ontology-tools` 的目录适配器。

项目需要算术或基础日期时，先核对[计算能力合同](../Ontology-tools/CALCULATION.md)，再在运行期模板中填写实际 profile、函数、业务精度／时间依据、候选扩张和预算；在验收模板中保存计算、时间适配与重放证据。模板不为项目默认选择舍入、时区或业务阈值。

项目采用[结构化公式配置](../Ontology-tools/FORMULA.md)时，可另设静态 `formulas/<domain>.ttl`，以RDF表达树作为唯一公式执行源，原LaTeX作展示，OWL/SWRL维护诊断与适用性，SHACL校验参数和关联。原生模板的加载清单只给可选角色注释，不表示其构建器已经支持该角色；项目须实现实际适配并分别验证公式图等价，扁平执行目录为 `formulas.ttl`。激活公式逐式独立算例验证，覆盖与SWRL分开统计，运行证据按公式合同填写。

结构示例中的预期独立编写；它可以用于验证解析、输入约束与后端是否真实执行SWRL。不得把模板的结构验证结果沿用为业务项目已验收；不得保留示例来源冒充真实来源。
