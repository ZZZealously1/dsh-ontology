---
name: ontology-builder
description: 从本地文档、制度、字段、样例或已授权知识库素材构建本体的统一入口；按输入选择文档十阶段或知识库六阶段，组织原生OWL/SWRL/SHACL构建、实际验证与中文交付到项目ontology目录。
---

# 本体建模总入口

本入口统一承接文档与知识库建模，负责选择路线、安排阶段和检查交付。先读[建模规范](../../references/modeling-principles.md)、[公共原则](../../common_rules.md)和[输出规范](../../CONTRACT.md)，再按当前任务加载一条路线及所需专题。所需方法与工具均在本 `Ontology/` 内；已有材料和会话能够回答的信息直接采用。

## 任务路由

| 任务 | 使用的方法 |
|---|---|
| 从本地PDF、Word、表格、文本、制度、流程、字段或样例建模 | [文档建模十阶段](references/document-route.md)；执行当前阶段时按需读[操作手册](references/document-workflow.md) |
| 从已授权知识库检索结果或其本地快照建模 | [知识库建模六阶段](references/rag-route.md)；需要取材时读[检索操作](references/rag-retrieval.md)，设计映射时读[检索到模型](../business-ontology-design/references/retrieval-to-model.md) |
| 标准文档内容建模 | [标准文档模型](../gbt-ontology-modeling/SKILL.md)，结合上面一条建模流程；正式符合性另核 |
| OWL/SWRL表达、命名或公理问题 | [共享语法参考](../../references/owl-swrl/index.md)、[原生构建](../ontology-construction/SKILL.md) |
| 规则新增、调整或排错 | [规则设计与实现](../ontology-inference-design/SKILL.md)，统一设计前提、结论、独立预期及执行方式 |
| 模型复核、测试和验收 | [验证与验收](../ontology-validation/SKILL.md)，统一完成模型检查、测试、覆盖评审与版本冻结 |
| 多本体语义融合 | [融合方法与本地工具](../ontology-fusion/SKILL.md) |
| 格式、版本或数据迁移 | [迁移方法与本地工具](../ontology-migration/SKILL.md) |
| 使用已有包回答问题 | 项目包内运行期SKILL及[执行方法](../ontology-execution/SKILL.md) |

混合输入选择主要路线，再嵌入需要的素材获取步骤，不重复执行两套全流程。已有本体融合或局部修改只回到受影响阶段及必要回归，记录范围与不适用理由。知识库命中是来源证据，不自动成为权威业务规则；离线任务使用已提供的导出资料与检索记录，不据方法说明连接外部系统。

## 阶段导航

- 文档十阶段：文件提取 → 资料查找 → 概念层次 → 属性设计 → 规则设计 → OWL生成 → 集成 → 一致性检查 → 规则测试 → 文档生成。每阶段动作与证据以文档路线及其操作手册为准。
- 知识库六阶段：检索取材 → 概念设计 → 原生源构建 → 规则设计 → 验证测试 → 说明交付。检索接口按实际能力与授权选择；原生源构建须可重复，规则保存为可供相应后端读取的SWRL。
- 阶段交接：问题、来源、身份和字段由[业务设计](../business-ontology-design/SKILL.md)确定；[构建](../ontology-construction/SKILL.md)落实原生模型与[领域集成](../../references/domain-organization.md)；规则、执行、验证分别采用上表方法。需要的文档和源文件骨架从[模板目录](../../templates/README.md)选择。
- 说明交付：两条路线均按[完整领域说明模板](references/full-domain-document.md)覆盖所有实际类、属性和规则；知识库路线补充其要求的检索证据及查询示例。只加载当前阶段需要的细节，不把所有参考拼接进入口。

## 完成条件

1. 按所选流程记录范围、阶段产物与必要适配，交付到项目 `ontology/`；OWL/SWRL维护概念与推理规则，SHACL维护约束。采用[结构化公式配置](../../Ontology-tools/FORMULA.md)时，RDF表达树是唯一公式执行源；不生成JSON或平行Python政策。
2. 每个能力问题可追溯到来源、模型/规则/查询、字段映射和独立预期；决定性缺口保留，已确认人工处理的事项按原决定执行。
3. 完成本次适用的[验证与验收](../ontology-validation/references/acceptance-checklist.md)：包括实际OWL DL全局一致性与具名类可满足性检查，SWRL和SHACL分别留证。所有适用规则有单元测试，实际规则执行覆盖率至少80%，分母、证据和未覆盖项按该清单记录，比例不豁免失败。
4. 推理能力有实际非空推导并对照独立预期，纯查询有真实查询结果比对；后端、命令、输入、产物、限制和未运行项可核对。缺少后端时交付草案与具体缺项，不能以解析或SHACL通过代替推理完成。
5. 所有类、属性和规则有完整中文说明，并交付运行期SKILL、验收记录与版本指纹；解析、OWL、SWRL、SHACL、外部联调和业务批准状态分别报告。
6. 结构化公式按领域独立维护静态目录，候选/激活和来源核验状态分开。全部激活公式具有独立算例，公式覆盖单列；适用性未知、参数缺失或来源冲突不得通过语言推测补成可计算状态。

可复用[本地工具](../../Ontology-tools/README.md)，但须核对各入口的支持范围、依赖和布局适配；工具限制不改变业务语义。
