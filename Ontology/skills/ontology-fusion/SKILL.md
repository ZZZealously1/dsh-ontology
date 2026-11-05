---
name: ontology-fusion
description: 融合或装配多个本体，分析概念、属性和身份差异，形成有依据的对齐与冲突决策，并验证集成后的保真、一致性及业务回归。
---

# 本体融合

用于多个子本体/领域模型整合、不同来源本体对齐、同名异义/异名同义处理及命名空间协调。先区别“图装配”和“语义融合”。遵守[公共原则](../../common_rules.md)及[变更与复用原则](../ontology-validation/references/change-and-reuse.md)。

流程：**输入与差异盘点 → 候选对齐 → 冲突检测 → 有依据处理 → 构建 → 联合验证 → 报告与回退**。

- 使用[融合手册](references/fusion-workflow.md)逐项核对概念、层次、属性、事实与规则；标签命中只是候选，不能自动生成等价或默认置信度。
- 本地脚本 [fuse_local.py](scripts/fuse_local.py) 提供候选和显式映射图装配。它读取明确本地文件，不解析远程imports，不自动决定语义，输出不是一致性证明。
- 结果在新版本 `ontology/` 维护源模块，重建集成入口。联合运行[OWL DL检查](../../Ontology-tools/OWL-DL.md)、数据验证与受影响规则案例；保留未决差异及来源。
