# demo：合成标签分类示例域

状态：draft-template；全部数据与来源均为合成演示，没有真实业务政策。维护责任尚未指定，项目使用时填写。

## 范围与能力问题

给定一个Item，能否由 `tag="demo"` 推导其属于TaggedItem？域ID为 `demo`，TBox IRI为 `https://example.org/ontology-template/demo`，术语命名空间为该IRI加 `#`，模块版本为 `template-1`。不涉及审批、费用、时间窗口、跨域关系或多对象关联。本例没有共享域或跨域依赖，规则和事实只依赖本域模型。

## 模型与规则

领域模型在 [demo_ontology.owl](../subontologies/demo_ontology.owl)：`Item` 为输入对象，`TaggedItem` 是其子类。`identifier` 与 `tag` 均为Item的字符串数据属性。每个字段必填且单值的要求在 [shapes.ttl](../shapes.ttl) 中表达，不能从domain/range自动推定。

[demo_rules.swrl](../rules/demo/demo_rules.swrl) 的 `rule-tagged` 表达 `Item(?x) ∧ tag(?x,"demo") → TaggedItem(?x)`。这是用于核验原生SWRL真实执行的合成规则；唯一维护源为规则文件，本文仅解释。依据在 [provenance.ttl](../provenance.ttl)。本例无对象属性，后续添加关系须声明方向和两端身份。

## 事实与集成

[instances_demo.owl](../data/instances_demo.owl) 是一个正向合成快照，有基于 OWL 公理注解的字段级来源证据，适合与该 TBox 一起进行 OWL DL 检查。字段映射见 [mapping.ttl](../mapping.ttl)；未实现从任意上传文件抽取的ETL。

[加载清单](../integration/load-plan.ttl) 登记域、模型/规则/事实三个角色、版本及本地相对路径。[集成文件](../integration/merged_ontology.owl) 由构建脚本生成，含TBox、规则及集成头部，不含动态ABox。事实由运行时显式选择，不能把此文件能在编辑器打开当作已加载实例或已执行规则。

## 命令与验收边界

在包根运行 `python scripts/build_integration.py` 重建，运行 `python scripts/build_integration.py --check` 校验图同构与源指纹。具体词汇、依赖及限制见 [README](../README.md)。这是实际可用的构建命令，没有配置业务推理命令。

[独立案例](../tests/cases.ttl) 包含正向分类、其他标签不产出分类、缺identifier拒绝输入三种预期。后端选定后逐项实际执行，不倒填预期。本目录没有业务验收报告或冻结清单；本体一致性、SWRL执行、SHACL输入校验分别留证。
