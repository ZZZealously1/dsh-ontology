# 完整内置函数条目与执行状态

这 37 项说明函数意图、参数示意和候选名称，供规则设计及后端选型时查阅；不构成所列 IRI 已全部标准化或后端支持的声明。名字相近不证明签名相同；候选替代名仅用于检索，选定后端后须核验命名空间、参数方向、绑定模式、数值/日期类型、异常和边界案例。

表中 `?x` 是人类可读记法，不能放进 Turtle RDF 文件。真正写法见[原生 SWRL](swrl-patterns.md)。`local-rules-v1` 不支持算术/字符串/日期/布尔/列表扩展，准确范围见 [PROFILE](../../Ontology-tools/PROFILE.md)；HermiT `owl-dl` 不执行任何 SWRL。显式 [hermit-swrl-calculation-v1](../../Ontology-tools/CALCULATION.md) 支持下述四则的二元形式、六种比较，以及该合同单独登记的三种 `otfn:` 扩展。未选择此配置时不能沿用其计算能力；其余候选条目仍须独立核验。


### 数学运算

| 函数 | 语法 | 说明  当前处理 |
|------|------|----------------|
| add | swrlb:add(?sum, ?a, ?b) | ?sum = ?a + ?b；计算配置支持整数／十进制精确二元运算，local-rules-v1 不支持 |
| subtract | swrlb:subtract(?diff, ?a, ?b) | ?diff = ?a - ?b；计算配置支持，类型同上 |
| multiply | swrlb:multiply(?prod, ?a, ?b) | ?prod = ?a × ?b；计算配置支持二元形式 |
| divide | swrlb:divide(?quot, ?a, ?b) | ?quot = ?a ÷ ?b；计算配置要求精确有限十进制，除零或无限十进制失败；舍入另用显式扩展 |
| sqrt | swrlb:sqrt(?root, ?x) | ?root = √?x  别名/后端扩展候选；不要假定 swrlb:sqrt 已获支持 |
| pow | swrlb:pow(?result, ?base, ?exp) | ?result = ?base^?exp  别名/后端扩展候选；不要猜测标准 power 与其等价 |
| abs | swrlb:abs(?absVal, ?x) | ?absVal = abs(?x)  候选标准数学函数；当前本地规则器不支持 |
| round | swrlb:round(?rounded, ?x) | 取整候选；不得直接承诺商业四舍五入，负数/中点与舍入方向须按后端核验 |
| floor | swrlb:floor(?result, ?x) | 向下取整  候选；当前不支持 |
| ceiling | swrlb:ceiling(?result, ?x) | 向上取整  候选；当前不支持 |

### 比较运算

| 函数 | 语法 | 说明  当前处理 |
|------|------|----------------|
| equal | swrlb:equal(?a, ?b) | ?a == ?b  local-rules-v1 支持；以实际字面量域为准 |
| notEqual | swrlb:notEqual(?a, ?b) | ?a != ?b  local-rules-v1 支持；不是缺失/否定证明 |
| lessThan | swrlb:lessThan(?a, ?b) | ?a < ?b  local-rules-v1 支持；仅后端允许的数值/字符串类型 |
| lessThanOrEqual | swrlb:lessThanOrEqual(?a, ?b) | ?a ≤ ?b  同上 |
| greaterThan | swrlb:greaterThan(?a, ?b) | ?a > ?b  同上 |
| greaterThanOrEqual | swrlb:greaterThanOrEqual(?a, ?b) | ?a ≥ ?b  同上 |

### 字符串运算

| 函数 | 语法 | 说明  当前处理 |
|------|------|----------------|
| contains | swrlb:contains(?str, "substr") | 包含子串  候选字符串函数；当前不支持 |
| startsWith | swrlb:startsWith(?str, "prefix") | 以...开头  候选字符串函数；当前不支持 |
| endsWith | swrlb:endsWith(?str, "suffix") | 以...结尾  候选字符串函数；当前不支持 |
| length | swrlb:length(?len, ?str) | 字符串长度  简写候选；候选名称 stringLength，IRI/参数须按后端核验 |
| concat | swrlb:concat(?result, ?a, ?b) | 连接字符串  简写候选；候选名称 stringConcat，IRI/参数须核验 |
| substring | swrlb:substring(?sub, ?str, ?start, ?len) | 子串  候选；起始索引与长度规则须核验，当前不支持 |
| toLower | swrlb:toLower(?lower, ?str) | 转小写  简写候选；候选名称 lowerCase，IRI/参数须核验 |
| toUpper | swrlb:toUpper(?upper, ?str) | 转大写  简写候选；候选名称 upperCase，IRI/参数须核验 |

### 时间运算

| 函数 | 语法 | 说明  当前处理 |
|------|------|----------------|
| year | swrlb:year(?y, ?date) | 年份  候选名称，未证实该 swrlb IRI；后端扩展待核验 |
| month | swrlb:month(?m, ?date) | 月份  同上 |
| day | swrlb:day(?d, ?date) | 日  同上 |
| hours | swrlb:hours(?h, ?time) | 小时  同上 |
| minutes | swrlb:minutes(?m, ?time) | 分钟  同上 |
| addDays | swrlb:addDays(?newDate, ?date, ?days) | 加天数  简写候选；日期/时区/历法与 duration 接口须核验 |
| addMonths | swrlb:addMonths(?newDate, ?date, ?months) | 加月份  同上；月底进位语义待核验 |

### 布尔运算

| 函数 | 语法 | 说明  当前处理 |
|------|------|----------------|
| not | swrlb:not(?result, ?x) | 逻辑非  候选名称，未证实该 swrlb IRI；不能代表开放世界下的缺失即否定 |
| and | swrlb:and(?result, ?a, ?b) | 逻辑与  候选名称，未证实该 swrlb IRI；SWRL body 列表本身为合取 |
| or | swrlb:or(?result, ?a, ?b) | 逻辑或  候选名称，未证实该 swrlb IRI；不能据此给 SWRL 规则头引入任意析取 |

### 列表运算

| 函数 | 语法 | 说明  当前处理 |
|------|------|----------------|
| size | swrlb:size(?len, ?list) | 列表长度  候选名称，未证实该 swrlb IRI；列表表示/后端扩展待核验 |
| first | swrlb:first(?first, ?list) | 第一个元素  候选名称，候选 list:first 不代表已核验 IRI 或支持 |
| rest | swrlb:rest(?rest, ?list) | 剩余元素  候选名称，列表表示/后端扩展待核验 |

---
