# 合成关系推导示例

能力问题：已知 Alice →parent Bob →parent Carol，能否推得 Alice →ancestor Carol、Carol →child Bob，以及 Person 属于 Entity？由 `rdfs:subClassOf`、`rdfs:subPropertyOf`、`owl:inverseOf` 和 `owl:TransitiveProperty` 直接推导；本例无 SWRL，因此省略 rules.swrl。

所有人物、数据和关系为 synthetic，只验证通用工具跨领域复用，不代表法律亲属认定。`provenance.ttl` 登记合成来源，`mapping.ttl` 说明直接合成 RDF，不声称已连接数据源。

使用共享 `ontology_tools` 0.3.0，profile `local-rules-v1`；按[工具说明](../../README.md)准备当前 Python 或工具目录 `.venv`，依赖以工具目录 `requirements.lock.txt` 为准，不联网安装，限制见[PROFILE](../../PROFILE.md)。从 `Ontology/Ontology-tools` 运行：

```powershell
$ontologyPython = 'python'
if (Test-Path -LiteralPath '.venv/Scripts/python.exe') {
    $ontologyPython = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
}
$ontologyRunRoot = '../../ontology-runs/family-01'
& $ontologyPython -B -X utf8 -m ontology_tools test --package examples/family --output "$ontologyRunRoot/test"
& $ontologyPython -B -X utf8 -m ontology_tools infer --package examples/family --output "$ontologyRunRoot/infer"
& $ontologyPython -B -X utf8 -m ontology_tools query --graph "$ontologyRunRoot/infer/closure.ttl" --query examples/family/queries/ancestors.rq --output "$ontologyRunRoot/query"
& $ontologyPython -B -X utf8 -m ontology_tools replay --run "$ontologyRunRoot/infer" --output "$ontologyRunRoot/replay"
```

每条命令后核对 `$LASTEXITCODE` 和本次输出目录中的报告，失败时停止依赖该结果的命令；每次使用新输出目录。三个独立案例验证多步关系/类型推导、断链反例和缺名称的输入拒绝。输出仅说明声明子集下的推导，不是完整 OWL 一致性证明。无需数据库或任何外部连接。
