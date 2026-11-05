# OWL / SWRL 语法参考

1. 先识别实际序列化与所选后端。新 `.owl` / `.swrl` 使用 RDF/XML，`.ttl` 使用 Turtle；**OWL/XML 是另一种语法**，不能只改扩展名代替转换。输出遵守[交付规范](../../CONTRACT.md)，不生成 JSON。
2. 编写类、属性、公理或实例时，按需读取[OWL 构造与命名](owl-patterns.md)。把数据范围与个体枚举、存在与全称限制、数据校验与开放世界公理分清。
3. 编写规则时读取[原生 SWRL 与规则模式](swrl-patterns.md)。SWRL 变量是声明过的 IRI，body/head 是 RDF 列表；人类可读的 `?x` 蕴含式仅用于说明，不冒充 Turtle。
4. 查函数时使用[完整函数表及支持状态](builtins.md)。表中 37 个条目的名称、IRI、参数和数据类型必须由所选后端实际验证。`local-rules-v1` 只支持表中的 6 个比较内置；数学、字符串、日期、布尔和列表运算不能因在表中就宣称可运行。
5. 参考[完整分文件示例](example-and-validation.md)，解析源文件，检查 OWL DL、规则结构和独立结果。HermiT `owl-dl` 检查拒绝含 SWRL 的输入；将 TBox/ABox 和规则分别加载到相应工具。检查通过仅覆盖实际输入、引擎和案例。

完整规则仍由 OWL/SWRL 维护，不另写一套 Python 业务规则。
