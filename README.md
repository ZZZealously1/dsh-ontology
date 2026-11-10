# DSH Ontology

将独立的 `Ontology` 方法库接入 DeepSeek Harness：智能体按来源建模，通过本地 Python／HermiT 执行校验与推理，再读取可重放的证据。方法和内核完整随包提供，不依赖原始工作区路径。

开源插件，第一方代码与方法采用 **MIT**。当前插件版本 `0.2.0`，内核版本 `0.4.0`，适配 DSH `0.2.0-rc.2` 和 `0.2.1-rc.5`。验证平台为 **Windows x64**；支持本地执行服务及 DSH 默认本地沙箱，远程执行服务不在支持范围。详细运行边界见 [PORTABILITY](docs/PORTABILITY.md)，真实宿主验收方法见 [DSH 验收](docs/DSH-ACCEPTANCE.md)。

## 包含什么

- 原有九个建模技能、共享规范、模板及建模/迁移脚本；另增加 `ontology-dsh` 接入技能。原方法目录的 326 个文件逐字节保留；排除 Python 缓存和不参与执行的 `Ontology-tools/.gitignore`，使标准 GitHub/npm 打包能完整核验。
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

在 DSH **插件 → 添加插件** 中输入公开仓库地址：

```text
https://github.com/ZZZealously1/dsh-ontology
```

不需要此仓库的 GitHub 授权。命令行安装相同插件：

```powershell
dsh plugin --profile web add 'github:ZZZealously1/dsh-ontology#v0.2.0'
```

需要固定归档或无法使用 Git 时，可从 [Releases](https://github.com/ZZZealously1/dsh-ontology/releases) 下载 `.tgz`，在添加插件窗口输入其绝对路径，或用 `dsh plugin --profile web add <文件.tgz>` 安装。尚未发布到 npm，因此不要直接输入裸包名 `dsh-ontology`。

插件内包含预构建入口、方法库、推理内核和 Java 库；**Python 与 Java 可执行环境仍需用户准备**。本次验证使用 Node.js 24+、CPython 3.12.14、Java 25.0.2。可先将公开源代码克隆到工具目录，建立独立 Python 环境；仅准备 Python 环境不需要构建 Node 项目：

```powershell
git clone --branch v0.2.0 https://github.com/ZZZealously1/dsh-ontology.git
cd dsh-ontology
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\Ontology\Ontology-tools\vendor\python-wheels -r .\Ontology\Ontology-tools\requirements.lock.txt
java -version
```

上述离线 wheel 适用 Windows x64。已有 Python 环境也可使用，但必须满足锁定依赖并通过 `ontology_environment`。其他平台可从 PyPI 准备锁定依赖；尚未完成跨平台验收。推理期间不会自动联网安装依赖。

安装入口与插件规范见 [DSH 官方 CLI 说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/README.md)。包内 `dsh.bundle.patch` 指向 [cordis.patch.yml](cordis.patch.yml)。

在 DSH 插件配置中找到部署项 **`ontology`**，设置：

| 配置项 | 值 |
|---|---|
| `pythonExecutable` | 上述 `.venv/Scripts/python.exe` 的绝对路径 |
| `javaExecutable` | 实际 `java.exe` 的绝对路径 |
| `workspaceRoots` | 允许项目输入、输出所在的现存绝对目录数组，例如 `['D:/ontology-projects']` |
| `timeoutSeconds` | 单次工具执行预算，默认 900 秒 |

默认空 `workspaceRoots` 允许读取方法和检查环境，项目操作会提示配置缺项。宿主必须挂载 `tools / skills / fs / subprocess` 服务，使用本地子进程以及本地或本地沙箱文件服务。rc.5 的 `workingDirectory` 存在时优先使用；rc.2 使用调用者会话中已验证的绝对 `cwd`，缺失时拒绝执行。修改配置后重启对应 profile，先调用 `ontology_environment` 确认 `ready`。

DSH 默认沙箱下，插件按每次调用所属会话的策略执行 Python 和 Java，项目模板写入也经过宿主文件服务。创建项目、推理和其他证据输出需要会话具有 `workspace-write` 权限，且目标同时位于会话工作区与插件的 `workspaceRoots` 内。只读会话不会因安装插件自动获得写权限。宿主沙箱不可用时明确失败，不回退为裸本地进程。Windows 的工作区还须由运行 DSH 的用户拥有并具有 FullControl（含 WRITE_OWNER）；仅 Modify 会使 DSH 的 ACL 设置失败。应选用权限符合要求的用户工作目录。插件不会自行更改目录 ACL。Windows 宿主报告的隔离强度为 `partial`，不宣称完整系统隔离。

使用 DSH 自己初始化的 profile；不要在 profile 内额外安装这些同名 DSH peer 包，也不要自行开启 `autoInstallPeers`。DSH 的标准解析器会从宿主提供它们；重复安装 SDK 副本可能使 provider 身份检查拒绝加载，应修正依赖树而不是关闭检查。

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

项目文件放 `ontology/`，运行证据放其外部的新目录。插件拒绝覆盖已存在输出、写入安装目录、普通路径越界、包内链接及元数据指定额外可执行程序。运行和取消通过 DSH 子进程服务管理；采用沙箱服务时继承宿主的实际文件隔离；裸本地服务仅有路径和协议防护，不是操作系统沙箱。默认单次 Java 调用仍为 60 秒，轮数等预算沿用项目配置；预算不是业务阈值。

## 开发与验证

```powershell
$env:ONTOLOGY_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
$env:ONTOLOGY_JAVA = (Get-Command java).Source
# 可选：把测试证据写至指定的包外目录；默认写系统临时目录
$env:ONTOLOGY_PLUGIN_TEST_OUTPUT = 'D:/ontology-tests'
pnpm install --frozen-lockfile
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
- Python 离线包中有 Windows x64 专用 wheel。其他平台或远程执行域需要另行验收，不能直接宣称支持。
- 升级代码、Python、Java 或依赖后，旧 replay 可能被指纹检查拒绝；不绕过检查冒称同环境复现。第一方授权见 [LICENSE](LICENSE)，第三方库继续遵守 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) 所列许可证。MIT 不覆盖或替换第三方许可证。
