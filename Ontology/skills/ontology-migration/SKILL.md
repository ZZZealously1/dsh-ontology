---
name: ontology-migration
description: 本地本体序列化转换、版本升级与遗留文件迁移；固定RDF映射、身份和回退基线，验证图保真、数据集合及实际业务回归。
---

# 本体迁移

适用于RDF/XML与Turtle互转、模型版本升级、类层次/属性重构，以及已导出的CSV/Excel/关系表转本体。先区分格式转换、模型变更和事实迁移；遵守[公共原则](../../common_rules.md)、[输出格式](../../CONTRACT.md)及[变更主方法](../ontology-validation/references/change-and-reuse.md)。不连接数据库，不生成JSON/JSON-LD。

1. 保存来源文件、版本、程序与旧预期，不覆盖输入；声明目标、允许差异、不可丢失内容及回退方法。
2. 序列化转换使用[本地工具](scripts/local_graph.py)，显式选择格式并检查图同构。版本变更使用明确增删图，不隐式改变政策。
3. 遗留源使用本地导出，区分定义表TBox与业务记录ABox；将主键、字段、类型、空值和例外写成RDF映射。缺规则时保留未决，不硬编码列名`id`。
4. 按[迁移手册](references/migration-workflow.md)核对源记录集合、字段值、关系端点及实际规则回归；图同构只证明同一RDF图转换保真。
5. 输出新版本 `ontology/`、映射、快照、日志、指纹、失败与回退说明；不因本地生成成功而声称生产切换完成。
