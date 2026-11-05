---
name: projection-example
description: 运行合成门店的 OWL DL 与有限 SWRL 多轮协同示例，读取分类、逐轮证据并验证快照重放。
---

# 运行多轮协同示例

先读本包 [README](README.md) 与工具 [协同能力契约](../../PROJECTION.md)。这是直接合成的门店/服务/路线夹具，不能作为真实资格或审批政策。

1. 从工具工作目录运行本包 `inspect`，检查 `runtime.ttl` 选择 `hermit-swrl-projection-v1`，并核对本地 Python、Java 与依赖。模型中的匿名限制由 HermiT 处理，不删除等价类来迎合有限后端。
2. 使用本包 [tests/cases.ttl](tests/cases.ttl) 的独立预期执行 `test`，分别读取正例、无触发反例与 SHACL 拒绝证据。
3. 对 `inputs/facts.ttl` 执行 `infer`，输出放包外新目录。先检查退出码及 `execution.ttl`；非 `passed` 时不交付诊断图为有效结论。
4. 读取 `result.ttl`、`classification.ttl`、`trace.ttl` 与 `rounds/`，确认规则输出参与下一轮 DL 分类，解释最终固定点及实际轮次。OWL 证据只到对应轮次与输入，不补造逐公理证明。
5. 显式查询本次 `closure.ttl`，再运行 `replay` 核验快照、后端和图结果。未知、未推得、SHACL 不符合、OWL 不符合和技术失败分别说明。

不要改输入预填四项预期结果，不生成 JSON，不连接外部系统。运行成功只证明本例在声明的有限投影范围内执行成功。
