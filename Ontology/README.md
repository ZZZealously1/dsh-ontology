# 本体建模与推理方法库

根据业务问题、制度、流程、接口字段和样例，建立可追溯的本体与规则，交付到项目的 `ontology/`。使用原生 OWL、SWRL、SHACL；所需方法、模板和本地工具都在本目录，可单独复制使用。实际运行仍需项目资料及 Python/Java 环境。

从 [ontology-builder](skills/ontology-builder/SKILL.md) 进入，按输入选择[文档十阶段](skills/ontology-builder/references/document-route.md)或[知识库六阶段](skills/ontology-builder/references/rag-route.md)；已有本体的小范围修改只处理受影响阶段。详细手册按当前任务加载。

| 方法 | 入口与用途 |
|---|---|
| 总流程 | [ontology-builder](skills/ontology-builder/SKILL.md)：选择输入路线、阶段调度和交付 |
| 业务设计 | [business-ontology-design](skills/business-ontology-design/SKILL.md)：能力问题、来源、对象身份、领域与数据契约 |
| 原生构建 | [ontology-construction](skills/ontology-construction/SKILL.md)：OWL、SWRL、SHACL、实例与模块集成 |
| 规则设计与实现 | [ontology-inference-design](skills/ontology-inference-design/SKILL.md)：前提、公式、回译、原生表达、查询与独立预期 |
| 验证与验收 | [ontology-validation](skills/ontology-validation/SKILL.md)：意图复核、五层验证、覆盖验收、冻结与演进 |
| 执行 | [ontology-execution](skills/ontology-execution/SKILL.md)：后端选择、实际加载、推理查询与留证复跑 |
| 标准文档建模 | [gbt-ontology-modeling](skills/gbt-ontology-modeling/SKILL.md)：内容结构、实体属性与参考模型；正式符合性另核 |
| 融合 | [ontology-fusion](skills/ontology-fusion/SKILL.md)：对齐、冲突处理、装配与回归 |
| 迁移 | [ontology-migration](skills/ontology-migration/SKILL.md)：格式/版本/数据转换、保真与回退 |

以上为九个方法入口。[工具入口](Ontology-tools/SKILL.md)专门说明现有命令与能力范围，各示例包的运行期技能用于演示项目使用，不计入建模方法。共享要求只在以下位置维护：

- [公共原则](common_rules.md)：来源、身份、业务缺口、语义边界与授权。
- [建模规范](references/modeling-principles.md)：概念、属性、公理、命名与复用。
- [OWL/SWRL参考](references/owl-swrl/index.md)：OWL构造、SWRL原子、函数与原生示例，编写或审查时按需查阅。
- [输出规范](CONTRACT.md)：领域布局、TBox/ABox、规则、集成、证据与交付格式。
- [模板目录](templates/README.md)：项目说明和原生文件骨架。
- [验收清单](skills/ontology-validation/references/acceptance-checklist.md)：独立预期、覆盖口径、实际执行与验收状态。

推荐指令：

> 使用 `Ontology/skills/ontology-builder/SKILL.md`，根据提供的业务资料建立本体与规则，输出到指定项目的 `ontology/`。先核对来源，影响业务结论的缺口列待确认；不编造阈值、审批或人工处理口径。说明实际后端，运行规格检查、OWL DL 检查、独立黄金案例和 SHACL 校验，交付依据、映射、命令和实际结果。不生成 JSON，不连接或修改外部系统。

[本地工具](Ontology-tools/README.md)版本 `0.3.0` 提供以下使用方向：[local-rules-v1](Ontology-tools/PROFILE.md)执行有限 OWL/SWRL；[HermiT 入口](Ontology-tools/OWL-DL.md)检查 OWL DL 并可导出命名分类和事实；[有限投影协同](Ontology-tools/PROJECTION.md)将 HermiT 与受支持 SWRL 的结论多轮交换；[计算协同](Ontology-tools/CALCULATION.md)增加算术、基础日期、规则头新值及计算证据。旧配置不自动迁移。统一重放核验输入和环境。包执行仍使用扁平布局，领域目录须经验证适配；协同固定点不代表完整 OWL DL＋SWRL 联合语义完备。

`skills/`、`references/` 保存现行方法，`templates/` 保存可复制骨架，`Ontology-tools/` 保存运行器及独立测试。业务资料和运行结果放在项目或包外目录。本目录不依赖历史原稿、移植记录或外部归档。

从 `Ontology/` 的父目录运行[自包含检查](scripts/check_portability.py)，核对当前方法入口、本地引用、必要工具和模板：

```powershell
python -B -X utf8 Ontology/scripts/check_portability.py
python -B -X utf8 -m unittest discover -s Ontology/scripts/tests -v
```

目录检查不代替实际模型的OWL DL、SWRL、SHACL和黄金案例验证。工具与模板各自提供真实运行命令，结果写到包外新目录。
