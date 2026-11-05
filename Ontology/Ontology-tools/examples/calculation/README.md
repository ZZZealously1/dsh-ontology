# OWL DL 与 SWRL 计算协同示例

此包展示 **DL 分类 → 加法 → DL 分类 → 乘法 → DL 分类**。它使用 `hermit-swrl-calculation-v1`，HermiT 与 Python SWRL 执行层分别运行并逐轮交换事实。公式与分类条件全部来自本目录的合成夹具，不代表真实金额、资格、审批或外部动作。

## 独立预期

输入只有 `sampleA a Sample`、标识和 `amount 2`。模型在 [ontology.ttl](ontology.ttl)，两条可执行规则在 [rules.swrl](rules.swrl)：

1. HermiT 根据 `Sample` 的父类推出 `Eligible`。
2. `rule-add` 从 `amount 2` 计算 `2 + 3 = 5`，新增 `subtotal 5`。
3. 下一轮 HermiT 根据 `subtotal hasValue 5` 推出 `Five`。
4. `rule-multiply` 计算 `5 × 2 = 10`，新增 `result 10`。
5. 下一轮 HermiT 根据数值限制推出 `Finished`，继续到无新增事实的固定点。

`5` 因模型中已有 `hasValue` 而属于初始候选。`10` 不在模型、输入或规则常量中，必须由成功规则头生成后进入候选。不能把中间计算值全部加入候选，也不能在输入中预填结论。

[五项黄金案例](tests/cases.ttl) 的预期独立手写：正常链、缺少数值时不计算、缺身份字段导致 SHACL 不符合、生成结果导致 OWL 不一致、非法算术类型导致执行失败。类不可满足、日期计算和更多精度边界由工具的独立测试覆盖。黄金文件是预期，实际通过状态读取本次运行输出。

来源与直接夹具映射见 [provenance.ttl](provenance.ttl)、[mapping.ttl](mapping.ttl)。完整计算范围及精度限制见 [计算能力合同](../../CALCULATION.md)。

## 智能体调用

先按 [工具说明](../../README.md) 准备本地 Python、Java 与离线依赖。从 `Ontology/Ontology-tools` 执行；将 `python` 替换为已安装所需依赖的解释器。输出目录位于方法库外，并且每次使用一个新目录：

```powershell
$ontologyPython = 'python'
$ontologyRunRoot = '../../ontology-runs/calculation-demo-01'
& $ontologyPython -B -X utf8 -m ontology_tools inspect --package examples/calculation --output "$ontologyRunRoot/inspect"
if ($LASTEXITCODE -ne 0) { throw 'inspect failed' }
& $ontologyPython -B -X utf8 -m ontology_tools test --package examples/calculation --output "$ontologyRunRoot/test"
if ($LASTEXITCODE -ne 0) { throw 'golden cases failed' }
& $ontologyPython -B -X utf8 -m ontology_tools infer --package examples/calculation --output "$ontologyRunRoot/infer"
if ($LASTEXITCODE -ne 0) { throw 'inference failed' }
& $ontologyPython -B -X utf8 -m ontology_tools query --graph "$ontologyRunRoot/infer/closure.ttl" --query examples/calculation/queries/check-result.rq --output "$ontologyRunRoot/query"
if ($LASTEXITCODE -ne 0) { throw 'query failed' }
& $ontologyPython -B -X utf8 -m ontology_tools replay --run "$ontologyRunRoot/infer" --output "$ontologyRunRoot/replay"
if ($LASTEXITCODE -ne 0) { throw 'replay failed' }
```

也可在已配置工具导入路径的 Python 中调用：

```python
from pathlib import Path
from ontology_tools.core import infer_graph, replay_run
from ontology_tools.io import OT, parse_rdf
from rdflib import URIRef

run = infer_graph(Path('examples/calculation'), output=Path('../../ontology-runs/calculation-api-01/infer'))
state = parse_rdf(run / 'execution.ttl')
assert str(state.value(URIRef('urn:ontology-tools:run'), OT.status)) == 'passed'
replay_run(run, Path('../../ontology-runs/calculation-api-01/replay'))
```

## 读取结果和依据

- 先读 `execution.ttl` 的状态、退出码、实际预算和轮次；失败时诊断图不能作为有效结论交付。
- `result.ttl` 是新增事实，`closure.ttl` 是本配置范围内的最终图，`classification.ttl` 是分类结果。查询应得到 `sampleA`、`5`、`10`。
- `initial-candidates.ttl` 和 `candidates.ttl` 分别保存初始、最终候选；`rounds/round-*/candidates.ttl` 保存交给该轮 HermiT 的范围。
- `computations.ttl` 记录函数、参数、结果和版本；`trace.ttl` 与逐轮证据连接规则、直接前提、计算及 OWL 结论。
- 有语义时间输入时，`temporal-normalization.ttl` 留存原始时间到 UTC 工作视图的映射，`calculation-contract.ttl` 和 `budget.ttl` 保存实际计算合同与资源使用；重放同时检查这些证据。
- `replay-report.ttl` 必须为 `passed`。重放使用保存的输入与本地依赖，重新计算并比较候选、计算轨迹、分类和结果；原始项目文件不必再次提供。

这仍是命名事实交换，不是完整 OWL DL＋SWRL 联合推理。未知值不等于否定，匿名存在对象不会变成命名实体。日期、聚合和新个体生成的具体支持边界以计算能力合同为准。
