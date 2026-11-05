# 通用本体执行工具

`Ontology-tools` 提供可复用的本地执行内核：检查原生本体包、校验事实、执行受支持的 OWL/SWRL 推导、查询结果、测试独立案例和复跑留证。工具版本为 `0.4.0`。默认 [local-rules-v1](PROFILE.md) 执行有限 OWL/SWRL；独立 [OWL DL 入口](OWL-DL.md) 使用 HermiT 检查一致性并可导出命名事实；显式选择 [hermit-swrl-projection-v1](PROJECTION.md) 可执行有限范围的多轮协同；[hermit-swrl-calculation-v1](CALCULATION.md) 增加算术、基础日期、新数据值与计算证据。[hermit-swrl-formula-v1](FORMULA.md) 新增独立 RDF 公式目录、受限表达式树、科学计算及结果回交。智能体入口见 [SKILL](SKILL.md)。

本目录是 `Ontology/Ontology-tools/` 下的运行器工程，与父目录 [Ontology](../README.md) 中的建模方法与输出格式统一维护。不同项目共用工具，分别提供自己的本体、规则、形状、事实、来源、映射和预期。执行器不会从自然语言重建业务规则，也不自动连接源系统。

## 运行环境与快速开始

以本目录 `Ontology/Ontology-tools/` 为工作目录，使用当前 Python 环境，或本目录 `.venv` 中的 Python。环境不依赖任何兄弟项目目录。直接依赖声明见 [requirements.txt](requirements.txt)，准备可复现环境时使用完整的 [requirements.lock.txt](requirements.lock.txt)。运行器不会自动安装依赖或联网下载。`owl-dl`、`owl-infer` 和协同配置另需本地 Java；HermiT / OWLAPI 依赖随本工具保存，实际命令与版本见 [OWL-DL](OWL-DL.md)。

已验证环境为 CPython 3.12.14。复制 `Ontology` 文件夹后，确认目标机器已有对应 Python 及锁定依赖；如需新建环境，使用已备齐的本地安装材料。离线安装可以先执行 `python -m venv .venv`，再用 `.venv/Scripts/python.exe -m pip install --no-index --find-links <本地wheel目录> -r requirements.lock.txt`；其中目录须替换为实际位置，没有离线材料时记录缺失依赖，不回退联网。工具保存运行环境的实际版本，并在复跑时核对。

在 PowerShell 中运行：

```powershell
# 当前工作目录为复制后的 Ontology/Ontology-tools。
$ontologyPython = 'python'
if (Test-Path -LiteralPath '.venv/Scripts/python.exe') {
    $ontologyPython = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
}
$ontologyRunRoot = '../../ontology-runs/portable-01'
& $ontologyPython -B -m ontology_tools --help
& $ontologyPython -B -X utf8 -m ontology_tools inspect --package examples/tagging --output "$ontologyRunRoot/tagging-inspect"
& $ontologyPython -B -X utf8 -m ontology_tools validate --package examples/tagging --output "$ontologyRunRoot/tagging-validate"
& $ontologyPython -B -X utf8 -m ontology_tools infer --package examples/tagging --output "$ontologyRunRoot/tagging-infer"
& $ontologyPython -B -X utf8 -m ontology_tools query --graph "$ontologyRunRoot/tagging-infer/closure.ttl" --query examples/tagging/queries/check-result.rq --output "$ontologyRunRoot/tagging-query"
& $ontologyPython -B -X utf8 -m ontology_tools test --package examples/tagging --output "$ontologyRunRoot/tagging-test"
& $ontologyPython -B -X utf8 -m ontology_tools replay --run "$ontologyRunRoot/tagging-infer" --output "$ontologyRunRoot/tagging-replay"
```

每条命令执行后核对 `$LASTEXITCODE` 和报告；前置命令失败时停止依赖其产物的命令。输出目录必须不存在，并位于输入包或既有运行目录之外；上述根目录位于 `Ontology` 之外，便于单独保留运行证据。再次运行时使用新目录名，不覆盖前一次证据。[tagging](examples/tagging/README.md)、[family](examples/family/README.md)、[projection](examples/projection/README.md) 和 [calculation](examples/calculation/README.md) 是无真实业务阈值的合成示例；后两个分别展示有限规则与标量计算参与多轮 OWL 交互。执行结果以实际生成的报告为准。开发验收脚本为 [verify_delivery.py](scripts/verify_delivery.py)，实际检查范围写入本次输出报告。

## 调用接口

Python 导入入口为 `ontology_tools`，与 CLI 共用实现：

```python
from ontology_tools import (
    inspect_package, validate_graph, infer_graph,
    query_graph, run_cases, replay_run, check_consistency, infer_owl,
)
```

| API / CLI | 主要输入 | 用途 |
|---|---|---|
| `inspect_package` / `inspect` | `--package --output` | 文件集、可选冻结清单、RDF 解析、profile 与支持范围检查 |
| `validate_graph` / `validate` | `--package --output`，可选 `--facts` | 对原始事实和模型执行本地 SHACL 校验，不隐式执行 SWRL |
| `infer_graph` / `infer` | `--package --output`，可选 `--facts` | 按配置校验，执行固定点推导，保存输入、输出与轨迹 |
| `query_graph` / `query` | `--graph --query --output` | 对明确指定的本地图执行只读 SPARQL 查询 |
| `run_cases` / `test` | `--package --output` | 独立加载案例输入，比较预期与实际，保留逐例证据 |
| `replay_run` / `replay` | `--run --output` | 核验有限规则、独立 OWL DL 或协同运行，从快照复跑并比较语义状态及 RDF 图 |
| `check_consistency` / `owl-dl` | 重复 `--ontology`，可选重复 `--facts`、`--imports-map`，必需 `--output` | 对原生 OWL 文件执行 OWL 2 DL profile、全局一致性与具名类可满足性检查 |
| `infer_owl` / `owl-infer` | 同 `owl-dl`，可选 `--candidates` | 检查通过后导出范围内命名类分类、实例类型、对象/数据属性及身份事实 |

`inspect_package`、`validate_graph` 返回 RDFLib `Graph`；`validate_graph` 校验不符合时也返回报告图，由调用方读取 `sh:conforms`。其他 API 正常完成时返回新输出目录的 `Path`，仍须读取结构化状态判断结果。参数含义与 CLI 一致，Python 签名如下；工具定义的路径或能力错误使用 `ToolError`（`ValueError` 子类），推理中 SHACL 不符合时保存报告后抛出 `ValidationError`。

```python
inspect_package(package, output=None)
validate_graph(package, facts=None, output=None)
infer_graph(package, facts=None, output=None)  # 实际执行必须提供 output
query_graph(graph_path, query_path, output)
run_cases(package, output)
replay_run(run_dir, output)
check_consistency(ontology, output, *, facts=None, imports=None, java="java", timeout=60)
infer_owl(ontology, output, *, facts=None, imports=None, java="java", timeout=60, candidates=None)
```

CLI 退出码：`0` 成功，`1` 黄金预期/复跑比较失败，或独立/协同 OWL DL 检查发现不一致或具名不可满足类，`2` 模型、路径、环境或支持范围错误，`3` 图校验不符合。独立 OWL 命令的完整状态见 [OWL-DL](OWL-DL.md#结果和退出状态)，协同范围见 [PROJECTION](PROJECTION.md)。退出 `0` 只表示该命令完成其技术检查，不代表业务已获批准或动作已完成。

附加命令 `freeze --package <目录>` 首次创建精确文件清单。已有清单时拒绝覆盖；模型变化应形成新版本。冻结不是业务验收，SHA256 证明文件未变化，不证明来源可信或数据真实。

## 项目包与配置

四种包执行配置共用这些扁平路径；`owl-dl` / `owl-infer` 直接接受显式文件清单，详见 [OWL-DL](OWL-DL.md)：

```text
ontology/
├── ontology.ttl
├── rules.swrl                 # 有 SWRL 时提供，RDF/XML
├── shapes.ttl
├── formulas.ttl               # 仅 formula profile；独立原生 RDF 公式目录
├── runtime.ttl                # 可省略，使用下述默认配置
├── imports-map.ttl            # 协同配置需要本地模型导入时提供
├── inputs/facts.ttl
├── provenance.ttl             # 提供时做 RDF 解析检查
├── mapping.ttl                # 提供时做 RDF 解析检查
├── tests/cases.ttl            # test 时使用
├── tests/inputs/*.ttl
├── queries/*.rq
└── manifest.sha256            # 冻结后提供，存在则校验
```

项目文档、来源和验收内容仍按 [Ontology 输出规范](../CONTRACT.md) 交付。工具完成 `mapping.ttl`、`provenance.ttl` 的语法检查，不代表已实现源字段抽取、转换或来源完整性审计。`local-rules-v1` 仍拒绝 `owl:imports` 和非空 `modules/`；协同配置可按包内 `imports-map.ttl` 解析离线模型导入。四种配置均不直接读取领域加载清单，需要经验证的适配。`ontology.ttl` 可包含 TBox 与静态 ABox；包执行的动态事实文件只接受事实角色，不能通过 `--facts` 修改类/属性公理或注入规则。

配置使用 Turtle；以下与默认配置一致：

```turtle
@prefix ot: <https://w3id.org/ontology-tools#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:example:runtime> a ot:Runtime ;
    ot:profile "local-rules-v1" ;
    ot:validationOrder "pre-post" ;
    ot:maxIterations "100"^^xsd:integer .
```

`validationOrder` 可为 `pre`、`post`、`pre-post`。项目根据约束依赖原始事实还是推导类型选择，并写明依据；`post` 不代表已做前置检查。`maxIterations` 是正整数资源上限，不是业务阈值；达到上限仍未稳定时按失败处理，不交付部分闭包为成功结论。

需要 HermiT 分类结果与 SWRL 多轮交互时，显式设置 `ot:profile "hermit-swrl-projection-v1"`。其 Java 配置、候选范围、身份语义和不完备边界见 [PROJECTION](PROJECTION.md)。需要算术、显式舍入或基础日期并让结果回交 HermiT 时，显式选择 `hermit-swrl-calculation-v1`，按 [计算合同](CALCULATION.md) 核对函数、精度、时间适配、生成值和资源预算。配置遗漏时仍采用 `local-rules-v1`；已有项目不自动迁移。结构化公式采用 [FORMULA](FORMULA.md) 的独立配置，OWL/SWRL 负责诊断与适用性，原生 RDF AST 是唯一公式执行源。

案例词汇支持 `https://w3id.org/ontology-tools#`，并兼容方法模板的 `https://example.org/ontology-template/meta#`。案例结构及预期语义见 [PROFILE](PROFILE.md) 和示例 `tests/cases.ttl`。每例使用独立输入，禁止将本次引擎答案反写成黄金预期。

## 运行证据与复现

推理运行目录中的核心产物：

| 文件 | 含义 |
|---|---|
| `input.ttl` | 本次事实快照 |
| `result.ttl` | 相对载入图新增的推导三元组 |
| `closure.ttl` | 本次可查询的闭包图 |
| `trace.ttl` | SWRL/有限 OWL 的直接依据；HermiT 结论为运行和输入快照级证据 |
| `classification.ttl`、`candidates.ttl` | OWL 投影/协同运行的命名类分类及实际候选范围；计算配置允许规则头新值扩张 |
| `initial-candidates.ttl`、`computations.ttl`、`calculation-contract.ttl`、`budget.ttl` | 计算配置的初始范围、计算轨迹、实际合同与预算 |
| `temporal-normalization.ttl`、`prepared/` | 计算配置的时间规范化映射与工作视图；原始快照保留 |
| `rounds/` | 协同运行每轮的 OWL 与规则输入、结果和状态 |
| `shacl-report.ttl` | 前置校验报告，是否执行以运行记录为准 |
| `post-shacl-report.ttl` | 后置校验报告，是否执行以运行记录为准 |
| `execution.ttl` / `report.md` | 结构化状态与可读摘要、版本、依赖和指纹 |
| `snapshot/package/` | 供复跑的原始包文件快照 |
| `manifest.sha256` | 运行目录的精确文件指纹清单 |

失败时保留已产生的证据和失败记录，不声称后续步骤完成；失败发生在产物建立之前时不会有完整成功产物。读取状态再读取结果，不能仅凭文件存在判断通过。

`replay` 支持成功的有限规则推导、独立 `owl-dl` / `owl-infer` 以及协同运行，也可复核已完成的 OWL 不符合结果；技术失败、单独查询、包检查和测试汇总不作为成功推理重放。它先核验运行清单、快照和当前程序/依赖版本，再从快照重新运行，按对应入口比较语义状态、分类、推导图及适用的校验/轨迹证据。它检验相同冻结输入在相同环境下的结果一致性，不要求 Turtle 排版、空白节点标签、时间戳或报告文字逐字一致。代码或依赖不匹配会明确失败，升级不能绕过旧证据指纹；重新查询原业务编号不能替代输入快照复跑。复现一个不一致结果不等于本体通过验收。

运行结果不会生成 JSON。RDF 输出可能采用按行排序的三元组形式，它仍是合法 Turtle。模型中的 HTTP IRI 仅作标识；禁止远程 `SERVICE`、`FROM`、自动 imports、RDF/XML 外部实体及 SHACL 的执行扩展。

查询另存 `query-input.ttl`、`query.rq`、执行记录和清单。`SELECT` 输出列名加 N3 值的 TSV，使用 CSV 引号转义，可用 Python `csv.reader(..., delimiter="\t")` 读取；这是本工具的表格格式，不宣称是标准 SPARQL Results TSV。`ASK` 在 `query-result.ttl` 中保存 `ot:askResult` 布尔值，`CONSTRUCT` / `DESCRIBE` 输出 RDF 图；查询不是 SPARQL UPDATE，不修改输入图。

## 通用与项目专用的分工

| 层 | 放在哪里 | 是否每项目重写 |
|---|---|---|
| 解析、profile 检查、推导、SHACL、查询、测试、留证与复跑 | 本工具 | 共用；按版本升级与测试 |
| 类、属性、领域规则、约束、事实、来源、映射、案例 | 各项目的 `ontology/` 目录 | 按该项目定义，以 OWL/SWRL/SHACL 为语义源 |
| 源接口或文件抽取、复杂聚合、超出计算合同的业务时间或分摊语义 | 经声明与验收的项目适配器或新后端 | 仅有实际需求时实现；输出可追溯事实或扩展支持能力 |

`local-rules-v1` 不提供完整 OWL DL 推理。独立 [owl-dl / owl-infer](OWL-DL.md) 使用 HermiT，后者只导出有限命名投影；[协同配置](PROJECTION.md) 把该投影交给受限 SWRL 并迭代，不宣称完整 OWL DL＋SWRL 联合语义。HermiT 证据不提供逐公理证明或最小冲突解释。[计算配置](CALCULATION.md) 支持声明的 13 个比较／算术／时间函数，并保存逐轮新候选与计算依据；项目仍须提供舍入、单位和时间口径。它也不承诺完整联合推理。本工具不提供外部数据连接或业务审批/动作执行。示例文件本身不构成通过声明，应读取当前环境实际生成的报告。

需要核验工具运行环境时，从本工具目录执行 `python -B -X utf8 scripts/verify_delivery.py --output ../../ontology-runs/tool-check-01`，运行开发测试、合成示例、独立 OWL 检查/投影及重放，并将实际命令、退出码与报告写入包外新目录。该工具检查不代替项目业务验收。
