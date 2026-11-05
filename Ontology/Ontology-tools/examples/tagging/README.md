# 合成标签分类可执行示例

本例是随工具提供的完整合成标签包，保留 synthetic 来源标记，不含业务审批或阈值。使用本库 `ontology_tools` 0.3.0 的 `local-rules-v1` 后端，直接执行 RDF/XML SWRL：`Item(?x) ∧ tag(?x,"demo") → TaggedItem(?x)`。模型、规则、事实、约束、查询与案例均在本目录内，不依赖其他模板目录。

按[工具说明](../../README.md)准备当前 Python 或本目录工具环境 `.venv`，依赖以工具目录的 `requirements.lock.txt` 为准，不联网安装。从 `Ontology/Ontology-tools` 目录运行：

```powershell
$ontologyPython = 'python'
if (Test-Path -LiteralPath '.venv/Scripts/python.exe') {
    $ontologyPython = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
}
$ontologyRunRoot = '../../ontology-runs/tagging-01'
& $ontologyPython -B -X utf8 -m ontology_tools test --package examples/tagging --output "$ontologyRunRoot/test"
& $ontologyPython -B -X utf8 -m ontology_tools infer --package examples/tagging --output "$ontologyRunRoot/infer"
& $ontologyPython -B -X utf8 -m ontology_tools query --graph "$ontologyRunRoot/infer/closure.ttl" --query examples/tagging/queries/check-result.rq --output "$ontologyRunRoot/query"
& $ontologyPython -B -X utf8 -m ontology_tools replay --run "$ontologyRunRoot/infer" --output "$ontologyRunRoot/replay"
```

每条命令后核对 `$LASTEXITCODE` 和本次输出目录中的报告，失败时停止依赖该结果的命令；每次使用新的输出目录。运行器代码与依赖见 [工具说明](../../README.md)，智能体流程见 [运行 Skill](../../SKILL.md)，支持范围见 [PROFILE](../../PROFILE.md)。这是使用共享工具的示例包，未将引擎复制进包内。

三个独立黄金预期：demo 推得 TaggedItem；other 不新增 TaggedItem（不表示逻辑否定）；缺 identifier 被 SHACL 阻止。`mapping.ttl` 仅记录合成字段含义，未执行外部数据抽取。无需图数据库，未连接 Neo4j 或业务系统。

查询使用 `OPTIONAL + BOUND` 判断指定图中类型是否存在；实际结果由当前运行产生。
