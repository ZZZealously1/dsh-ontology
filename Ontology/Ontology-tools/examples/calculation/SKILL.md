---
name: calculation-example
description: 运行合成的 OWL DL 与 SWRL 算术多轮协同示例，核对新增字面值、计算依据、黄金案例与快照重放。
---

# 运行计算协同示例

先读本包 [README](README.md) 与 [计算能力合同](../../CALCULATION.md)。本例的数值和分类条件都是合成夹具，不用来判断真实业务。

1. 用 `inspect` 核对显式配置 `hermit-swrl-calculation-v1`，随后执行 [独立黄金案例](tests/cases.ttl)。SHACL 不符合、OWL 不一致和计算失败分别核对，不能统一记成非法输入。
2. 依 README 的命令对 `inputs/facts.ttl` 执行 `infer`，输出到包外的新目录。检查退出码和 `execution.ttl`，仅在 `passed` 时使用最终结果。
3. 读取 `result.ttl`、`classification.ttl`、`computations.ttl`、候选快照与 `rounds/`，确认 `subtotal 5` 和 `result 10` 由计算产生，并实际反馈到后续 HermiT 分类。未命中的计算分支不能增加候选值。
4. 对最终 `closure.ttl` 运行本包查询，再执行 `replay`。依据计算轨迹说明函数和直接前提，依据 OWL 轮次及快照说明分类，不补造逐公理证明。

不要预填预期结果、修改黄金预期迎合输出或连接外部系统。本例成功证明声明范围内的协同计算，不证明完整联合推理。
