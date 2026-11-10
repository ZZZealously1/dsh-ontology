# DSH Ontology

将独立的 `Ontology` 方法库接入 DeepSeek Harness：智能体按来源建模，通过本地 Python／HermiT 执行校验与推理，再读取可重放的证据。方法和内核完整随包提供，不依赖原始工作区路径。

当前插件版本 `0.1.1`，内核版本 `0.4.0`，适配 DSH `0.2.0-rc.2` 和 `0.2.1-rc.5`。面向 **Windows x64、本地文件系统及本地子进程**；远程或沙箱 provider 会明确拒绝加载。详细运行边界见 [PORTABILITY](docs/PORTABILITY.md)，真实宿主验收方法见 [DSH 验收](docs/DSH-ACCEPTANCE.md)。

## 包含什么

- 原有九个建模技能、共享规范、模板及建模/迁移脚本；另增加 `ontology-dsh` 接入技能。原方法目录的 327 个文件逐字节保留，排除 Python 缓存。
- 有限 OWL／SWRL、本地 SHACL、独立 HermiT 检查与结果导出、有限 OWL／SWRL 交互、算术和基础日期、结构化公式、独立案例及 replay。各 profile 的边界以 [内核契约](Ontology/CONTRACT.md) 和 [工具说明](Ontology/Ontology-tools/README.md) 为准。
- 17 个原有 Java 依赖 JAR、8 个 Python 离线安装包，以及来源指纹。Python 和 Java 可执行环境需单独准备。

| DSH 工具 | 用途 |
|---|---|
| `ontology_environment` | 检查实际 Python、Java、依赖和内核指纹；不自动安装 |
| `ontology_read_method` | 分段读取随包方法和参考，默认加载建模总入口 |
| `ontology_new_project` | 将合成示例复制为可编辑的项目 `ontology/`；移除旧冻结清单 |
| `ontology_run` | 执行 `inspect / validate / infer / test / query / replay / owl-dl / owl-infer / freeze` |

本体、规则、事实、公式与证据继续使用 OWL／SWRL／Turtle／Markdown；JSON 仅用于 DSH 必需的包元数据和内存中的工具通信，不生成业务 JSON 本体。

## 安装

先安装匹配版本的 DSH、Node.js 24+、pnpm 11，以及 Python 和 Java。本次验证使用 CPython 3.12.14、Java 25.0.2。以下命令在仓库根目录执行，路径由部署者选择：

```powershell
gh repo clone ZZZealously1/dsh-ontology
cd dsh-ontology
pnpm install --frozen-lockfile
pnpm build
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\Ontology\Ontology-tools\vendor\python-wheels -r .\Ontology\Ontology-tools\requirements.lock.txt
pnpm verify:package
python -B scripts/pack.py --output ..\dsh-ontology-0.1.1.tgz
dsh plugin --profile web add ..\dsh-ontology-0.1.1.tgz
```

`dsh plugin --profile <名称> <pnpm参数>` 是 DSH 的插件安装入口，见[官方 CLI 说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/README.md)。包内 `dsh.bundle.patch` 指向 [cordis.patch.yml](cordis.patch.yml)。此仓库为私有仓库，需要 GitHub 读取权限；没有发布到公共 npm。使用仓库的保真打包脚本，避免普通 `pnpm pack` 省略原库 `.gitignore` 后造成快照缺项；产物仍是标准 npm tarball。

在 DSH 插件配置中找到部署项 **`ontology`**，设置：

| 配置项 | 值 |
|---|---|
| `pythonExecutable` | 上述 `.venv/Scripts/python.exe` 的绝对路径 |
| `javaExecutable` | 实际 `java.exe` 的绝对路径 |
| `workspaceRoots` | 允许项目输入、输出所在的现存绝对目录数组，例如 `['D:/ontology-projects']` |
| `timeoutSeconds` | 单次工具执行预算，默认 900 秒 |

默认空 `workspaceRoots` 允许读取方法和检查环境，项目操作会提示配置缺项。宿主必须挂载 `tools / skills / fs / subprocess` 服务，并使用 `dsh-fs-local` 与 `dsh-subprocess-local`。rc.5 的 `workingDirectory` 存在时优先使用；rc.2 使用调用者会话中已验证的绝对 `cwd`，缺失时拒绝执行。修改配置后重启对应 profile，先调用 `ontology_environment` 确认 `ready`。

DSH 默认 profile 可能使用 `dsh-fs-sandbox`；此时安装成功不代表插件能够激活。请先用独立验收 profile 和 [本地运行覆盖配置](docs/DSH-ACCEPTANCE.md) 验证，不直接修改正在使用的业务 profile。严格的本地 provider 检查继续保留。

使用 DSH 自己初始化的 profile；不要在 profile 内额外安装这些同名 DSH peer 包，也不要自行开启 `autoInstallPeers`。DSH 的标准解析器会从宿主提供它们；重复安装 SDK 副本可能使严格的本地 provider 身份检查拒绝加载，应修正依赖树而不是关闭检查。

也可在对应 profile 的 `cordis.patch.yml` 中添加覆盖项。`config` 会整项替换，因此写全配置；以下路径只是示例：

```yaml
- id: ontology
  config:
    pythonExecutable: 'D:/tools/dsh-ontology/.venv/Scripts/python.exe'
    javaExecutable: 'C:/Program Files/Java/jdk-25.0.2/bin/java.exe'
    workspaceRoots:
      - 'D:/ontology-projects'
    timeoutSeconds: 900
```

这一格式已核对 `dsh-app-boot@0.2.1-rc.5` 实现；可参考[官方 bundle 覆盖示例](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/web-app/cordis.patch.yml)。

## 如何使用

可以向 DSH 发送：

> 使用 ontology-dsh 技能，根据我的业务资料构建项目 ontology。先核对来源和业务规格；缺失关键口径时列出待确认项。执行模型检查、独立案例、SHACL 和所选推理后端，交付规则依据、数据映射、运行命令和真实验收结果。不要连接外部业务系统。

开发调试时，工具参数可按下列顺序填写；路径均相对当前智能体工作目录，也可使用授权根目录中的绝对路径：

```yaml
# ontology_new_project：只是演示起点，不是由业务资料生成的完成模型
destination: demo/ontology
example: formula

# ontology_run：先独立检查，再执行对应操作，每次输出必须是新目录
operation: inspect
package: demo/ontology
output: demo/runs/inspect-001
```

随后分别调用 `test`、`infer`，令 `output` 指向不同新目录。查询使用 `operation: query`，`graph` 指向推理结果的 `closure.ttl`，`query` 指向实际 `.rq` 文件。重放使用 `operation: replay`，`run` 指向原运行目录，`output` 指向新的目录。推理后端由项目 `runtime.ttl` 选择，不由模型自由声称。

读取 `status`、`exitCode`、`semanticState` 和证据文件：`0` 是命令通过；`1` 可表示已完成的语义不符合或案例/重放不通过；`2` 是技术或输入错误；`3` 是 SHACL 不符合。`replay` 通过只表示原结果被复现，原结果仍可能是不一致。查看 `report.ttl`、`shacl-report.ttl` 或 `replay-report.ttl`，不能只凭“工具执行成功”判断业务验收。

`query` 成功时，工具 `summary` 会附带真实 `query-result.tsv` 的前 12,000 个字符，模型可直接读取结果值。截断时会明确标记，完整结果始终保存在原 TSV 文件中。

项目文件放 `ontology/`，运行证据放其外部的新目录。插件拒绝覆盖已存在输出、写入安装目录、普通路径越界、包内链接及元数据指定额外可执行程序。运行和取消通过 DSH 子进程服务管理；这些是受信本地环境中的防护，并非操作系统沙箱。默认单次 Java 调用仍为 60 秒，轮数等预算沿用项目配置；预算不是业务阈值。

## 开发与验证

```powershell
$env:ONTOLOGY_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
$env:ONTOLOGY_JAVA = (Get-Command java).Source
# 可选：把测试证据写至指定的包外目录；默认写系统临时目录
$env:ONTOLOGY_PLUGIN_TEST_OUTPUT = 'D:/ontology-tests'
pnpm build
pnpm typecheck
pnpm test
pnpm test:integration
pnpm verify:package
python -B scripts/sync-ontology.py
```

`pnpm test` 使用真实 Python／Java 和 DSH 进程服务，缺少环境会失败，不静默跳过。`test:integration` 经真实 Cordis、工具注册、技能注册和本地进程服务执行完整工具调用；不需要模型 API。原内核的全量检查入口、环境条件及快照升级方式见 [PORTABILITY](docs/PORTABILITY.md)。验收报告、日志和运行结果留在仓库外。

## 范围限制

- 保留的是当前已实现的方法和确定性执行能力。没有宣称完整 OWL DL＋SWRL 联合语义，也没有增加任意 Python 业务函数生成、自动方法自进化或外部系统操作。
- PDF、Word、表格和扫描件的读取依赖 DSH 宿主可用的解析器、OCR 与模型。宿主和合成示例验收不能替代“真实资料上传→建模→业务调优”的业务验收，也不代表不同模型的建模质量完全一致。
- Python 离线包中有 Windows x64 专用 wheel。其他平台、沙箱或远程执行域需要另行适配和验收，不能直接宣称支持。
- 升级代码、Python、Java 或依赖后，旧 replay 可能被指纹检查拒绝；不绕过检查冒称同环境复现。依赖授权见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)，当前不授予公开再分发许可。
