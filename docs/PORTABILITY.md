# 能力保留与运行边界

插件将 DSH 接入代码放在 `Ontology/` 外，随包保留 `Ontology-tools 0.4.0` 的实现、方法、模板和测试。当前快照共有 327 个文件，26,842,500 字节；排除了原目录中的 16 个 Python 字节码缓存，其余被收录文件逐字节保留。指纹清单见 [source-manifest.sha256](../source-manifest.sha256)，相对路径以随包 `Ontology/` 为根。

## 保留的内容

| 层次 | 随包内容 | 验证方式 |
|---|---|---|
| 方法 | 九个建模 Skill、共享规范、来源/身份/领域方法、原生文件与验收模板 | 文件指纹、技能与链接检查、真实业务任务验收 |
| 语义 | OWL、SWRL、SHACL、RDF 结构化公式、来源和映射契约 | 原生图校验、独立案例、支持范围检查 |
| 执行 | Python 内核、Java 桥接、17 个原始 classpath JAR | 真实执行、错误状态、依赖指纹 |
| 复用 | 本地构建、融合、迁移脚本和工具 API／CLI | 对应测试、图保真与业务回归 |
| 证据 | 原始快照、逐轮推导、公式/计算轨迹、预算、黄金案例和 replay | 记录与重新执行结果比较 |

插件封装不改变既有 profile 的默认值或语义边界。领域源到扁平运行包仍需实际适配并证明图等价；结构化公式有独立角色，不能以重命名目录宣称加载完成。

## 环境条件

- Python 可执行环境及依赖独立于 DSH 的 Node 环境。当前验证基线是 CPython 3.12.14；内核依赖版本由 [requirements.lock.txt](../Ontology/Ontology-tools/requirements.lock.txt) 固定。
- [python-wheels](../Ontology/Ontology-tools/vendor/python-wheels) 保留了八个原始离线安装包。`wcwidth-0.9.2-cp310-abi3-win_amd64.whl` 适用于 Windows x64；其他系统或不兼容解释器需要另行准备与锁定版本匹配的 wheel，不能据此宣称所有平台开箱即用。缺包时报告缺项，不由推理器联网补装。
- OWL DL 需要真正可运行的 Java。HermiT／OWLAPI JAR 随包提供不代表 Java 可执行环境也已安装。JAR Manifest 版本与 HermiT API 自报版本分别保留，见[原依赖说明](../Ontology/Ontology-tools/vendor/owl-dl/README.md)。
- 首版只接受真实的 `dsh-fs-local` 与 `dsh-subprocess-local` 服务，远程或沙箱 provider 会明确拒绝。适配器自身使用本地文件系统，不能声称远程 provider 配置已经隔离了这些读写。浏览器前端本身不能承担本地 Python／Java 任务。
- `workspaceRoots` 默认空列表，此时可读方法和检查环境；执行项目操作前须由部署者配置现存的绝对目录，模型工具参数不能放宽该边界。这是受信本地运行环境中的路径与协议防护，不是操作系统沙箱。
- 文档读取、OCR、知识库取材、概念和规则设计由宿主模型及其可用工具共同完成。现有方法规定如何核对这些环节，不是一套涵盖所有输入格式的独立解析器。模型、上下文策略或读取工具变化后，需要端到端业务案例验收。

## 源快照核验与更新

从插件仓库根目录运行：

```powershell
python -B -X utf8 scripts/sync-ontology.py
```

命令默认只读核验随包快照，不下载文件、不写方法库、不更新指纹。若维护者还有明确的原始方法目录，可同时比对：

```powershell
python -B -X utf8 scripts/sync-ontology.py --source '<原始 Ontology 目录>'
```

构建一个尚无 `Ontology/` 和清单的新插件快照时，才使用 `--import --source <目录>`。导入目标固定为脚本所在仓库的 `Ontology/`，拒绝已存在的目标或清单；发现差异时不静默覆盖已修改内容。源与复制结果均核对后才记录指纹。修改核心能力应形成新的源快照和版本，经审查及回归后再打包，不能通过重写指纹掩盖不明差异。

方法维护检查从仓库根目录运行：

```powershell
python -B -X utf8 Ontology/scripts/check_portability.py
python -B -X utf8 -m unittest discover -s Ontology/scripts/tests -v
```

工具完整验收的实际入口为 `Ontology/Ontology-tools/scripts/verify_delivery.py`。命令及输出要求见[工具说明](../Ontology/Ontology-tools/README.md)。运行结果保存在包外的新目录；检查链接和语法不代表推理或业务验收已经通过。

插件发布归档使用 `scripts/pack.py --output <仓库外的新文件.tgz>`。它先运行包资源校验，再按 `package.json` 的字面文件白名单创建标准 `package/` 前缀归档，保留原始 `.gitignore` 字节并复核全部本体指纹；通用 npm/pnpm 打包会忽略该原始文件，不能替代此命令。

## 重放与项目生命周期

插件资源、用户项目、单次运行证据分别保存。新项目继续使用 `ontology/`；源码、规则和公式维持一个维护源，集成文件从源重建。冻结包后不在其中写日志或运行结果。

内核 replay 核对 Python、依赖、Java、代码和源文件指纹。单纯搬运路径不必然改变内核指纹，但升级 Python、Java、依赖或代码后，旧记录可能被正确拒绝；不能放宽检查以声称相同环境复现。DSH 的会话记录与本体推理的 replay 是不同证据，二者不能相互替代。

插件可保留当前实现的确定性能力，不能仅凭复制方法文件保证换模型后的建模质量相同。完整保留声明应依据 DSH 中的实际工具调用、所有适用黄金案例，以及从业务资料到交付的端到端验证。未完成的部分单独记录。
