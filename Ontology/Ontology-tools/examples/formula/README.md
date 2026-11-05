# 结构化公式与 OWL/SWRL 循环示例

这是纯合成验收包，所有输入与比较参考值均为测试夹具，不代表实际器件的诊断阈值。

`formulas.ttl` 独立保存原始公式 `L=\sqrt{D\tau}`、参数、适用条件、单位和 RDF 表达式树。该目录不会送入 HermiT。OWL 先将显式 `ValidatedObservation` 分类为 `UsableObservation`；SWRL 根据观察支持计算条件；通用解释器计算 `sqrt(0.0025 × 0.000001) = 0.00005 m`；下一轮 SWRL 对合成参考值 `0.00004 m` 比较，随后真实 HermiT 导出继承类 `NeedsSyntheticReview`。

运行（先激活工具依赖环境）：

```powershell
python -m ontology_tools infer --package examples/formula --output <新的运行目录>
python -m ontology_tools test --package examples/formula --output <新的验收目录>
python -m ontology_tools replay --run <已有运行目录> --output <新的回放目录>
```

验收包含正常计算、缺参数、缺条件、单位错误、结果注入和依赖循环。缺参数及缺条件保留 pending 诊断；错误数据使执行失败，不产生成功的结果文件。`formula-computations.ttl` 保存参数换算、原始/重建 LaTeX、每步运算、精度、舍入与实际 `_pydecimal` 实现指纹。原始公式使用 `render_formula` 展示，AST 可由 `render_expression` 独立重建以供检查。

`tests/cases.ttl` 的参考值和期望三元组在运行前编写；`tests/inputs` 中每个文件都是独立事实快照。`unreviewed` 是禁用的不可执行候选，故意不补齐表达式，以证明大目录可保留待核验条目。
