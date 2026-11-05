# 知识库本体说明补充

使用[完整领域说明模板](../../../skills/ontology-builder/references/full-domain-document.md)的七章结构，生成 `ontology/docs/<domain>_本体说明.md`；项目记录交接见[领域说明入口](../../domain-doc.md)。逐类、逐属性、逐规则字段及通用运行/验收内容不在此重复。

知识库建模在对应章节增加以下内容：

| 章节 | RAG特有内容与填写要求 |
|---|---|
| 1 概述 | 领域背景、知识库与文档清单、检索覆盖和域边界；架构图说明领域依赖，不把检索分类树直接等同类继承。统计区分具名类与匿名表达式、实际执行与未运行案例 |
| 2 类定义 | 候选术语的原文定位、采用/排除和歧义记录；推导标记类链接原生规则IRI，复用模板的完整类字段 |
| 3 属性定义 | 检索到的方向、域和值域与原文核对；多个domain表示同时满足，候选并集须明确建模。枚举、多值及数据类型兼容性与SHACL输入要求分别记录 |
| 4 规则详解 | 前提所依赖的片段、版本和上下文是否充分；规则类别、计算边界、支持后端和案例按完整模板记录 |
| 5 使用指南 | 给出适用的敏感资产筛选、层级继承查询、阈值筛选三类示例；领域不适用时说明替代能力问题。查询仅对明确选择的事实或闭包图执行 |
| 6 验证报告 | 记录素材覆盖缺口怎样影响模型与案例；构建保真、规则测试和OWL DL检查分别给结果，三元组数量相同不能证明语义等价 |
| 7 附录 | 知识库名称/IndexId、检索主题、实际参数、分页/文档覆盖、原文位置、来源冲突和缺失；版本变更、实际审批依据、SHACL缺项、后端未支持及后续扩展 |

第5章可引用随模板的[sensitive.rq](../models/starter/ontology/queries/sensitive.rq)、[hierarchy.rq](../models/starter/ontology/queries/hierarchy.rq)、[threshold.rq](../models/starter/ontology/queries/threshold.rq)，替换项目IRI与参数。Python调用示例采用实际通用API `run_cases`、`infer_graph`、`check_consistency`，不另写平行的 `forward_chain` 业务政策；解释 `execution.ttl`、`result.ttl`、`closure.ttl`、`trace.ttl` 的实际用途与状态。

标准适用性按完整模板核验；引用标准条款时应核对正式正文、版本、适用范围与符合性证据。
