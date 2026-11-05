# 多轮 OWL DL 与有限 SWRL 协同示例

能力问题：由 `storeA offers serviceB`、门店/服务/路线的原始类型，能否自动归类门店、关联路线，再自动归类为 `ReadyStore`？

这是 synthetic 合成夹具，不代表真实配送资格、路线分配、审批或业务动作。两个等价类定义在 [ontology.ttl](ontology.ttl)，两条规则定义在 [rules.swrl](rules.swrl)。输入不预写推导结论，来源与直接夹具映射分别见 [provenance.ttl](provenance.ttl) 和 [mapping.ttl](mapping.ttl)。

## 能力问题与独立预期

1. `DeliveryStore` 等价于 `Store` 且 `offers` 至少一个 `DeliveryService`。HermiT 从原始事实推出 `storeA a DeliveryStore`。
2. 规则 `rule-route` 将已分类的 `DeliveryStore` 关联到既有 `Route`，产生 `storeA eligibleFor routeR`。
3. `RoutedStore` 等价于 `Store` 且 `eligibleFor` 至少一个 `Route`。下一轮 HermiT 从新增关系推出 `storeA a RoutedStore`。
4. 规则 `rule-ready` 推出 `storeA a ReadyStore`；继续执行直到没有新增事实，并完成后置 SHACL。

这条链要求 OWL 与规则至少交互两轮。最终固定点轮次和分类内容以本次 `execution.ttl`、`trace.ttl` 及 `rounds/` 为准，不能仅凭类名出现在文件中判断完成。

三项独立案例在 [tests/cases.ttl](tests/cases.ttl)：完整输入要求四项新增结论；缺 `offers` 关系时四项结论都不新增；缺 `storeKey` 时必须由前置 SHACL 拒绝。负例的“未推得”不是 OWL 否定。形状只约束合成夹具的身份字段，没有真实业务金额或审批阈值。

## 智能体运行

运行环境按 [工具 README](../../README.md) 准备，Java 与离线依赖按 [OWL DL](../../OWL-DL.md) 核对。执行配置为 `hermit-swrl-projection-v1`，范围见 [协同能力契约](../../PROJECTION.md)。从 `Ontology/Ontology-tools` 运行：

```powershell
$ontologyPython = 'python'
if (Test-Path -LiteralPath '.venv/Scripts/python.exe') {
    $ontologyPython = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
}
$ontologyRunRoot = '../../ontology-runs/projection-01'
& $ontologyPython -B -X utf8 -m ontology_tools inspect --package examples/projection --output "$ontologyRunRoot/inspect"
& $ontologyPython -B -X utf8 -m ontology_tools test --package examples/projection --output "$ontologyRunRoot/test"
& $ontologyPython -B -X utf8 -m ontology_tools infer --package examples/projection --output "$ontologyRunRoot/infer"
# 确认上一命令退出 0，且 infer/execution.ttl 为 passed，再查询和重放。
& $ontologyPython -B -X utf8 -m ontology_tools query --graph "$ontologyRunRoot/infer/closure.ttl" --query examples/projection/queries/check-result.rq --output "$ontologyRunRoot/query"
& $ontologyPython -B -X utf8 -m ontology_tools replay --run "$ontologyRunRoot/infer" --output "$ontologyRunRoot/replay"
```

每条命令后核对实际退出码和结构化状态；失败即停止依赖该结果的命令。每次使用包外的新目录，不覆盖前次证据。

读取顺序为 `execution.ttl` 状态 → `result.ttl` 新增结论与 `classification.ttl` 分类 → `trace.ttl` 及逐轮证据 → 对本次 `closure.ttl` 查询。SWRL 轨迹含直接前提；OWL 记录为某轮 HermiT 对冻结输入的推导，不提供逐公理证明。`replay` 核验输入和环境后从快照运行，不重新查询原始外部系统。

此例展示命名事实的有限投影交换，不是完整 OWL DL＋SWRL 联合推理。不存在匿名对象命名、未知转否定、算术或业务动作。示例文件不构成验收通过声明，实际结果读取本次工具输出。
