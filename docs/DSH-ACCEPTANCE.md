# 在真实 DSH 中验收

`scripts/verify-dsh.mjs` 验证真实 SDK 服务组合，适合回归。实际部署还需经官方 `dsh` CLI 启动 Loader、加载 profile 和插件，再调用工具；在线模型验收则进一步要求检查真实模型会话事件、工具调用和保存的推理证据。这三层结果分别记录，不能相互替代。

2026-11-10 验收使用现有 Windows x64 DSH `0.2.0-rc.2` 运行程序和独立 `DSH_HOME`，通过正常插件安装入口加载 `0.1.1`；未启用版本豁免。原来的 `0.1.0` 仅声明 rc.5，会被此版本的正常兼容检查拒绝。

本次实际结果：完整 CLI 宿主检查 26/26 通过；DeepSeek Flash 在线会话在 12 个模型步骤内完成合成公式任务，23/23 检查通过；插件回归 31/31 通过，查询预览改动另有针对性回归通过。工具记录与独立 RDF 校验确认 `0.00005 m`、`Computed` 和 `NeedsSyntheticReview`，黄金案例和 replay 均通过。原方法库 327 个文件的指纹与源目录一致。

在线验收发现并修复了两个产品问题：旧版宿主缺少工作目录服务时无法激活，以及查询只返回产物路径、模型不能直接核对值。验收夹具本身的路径、TSV 引号解析和 scoped guard 问题也已修正后重跑；旧失败记录保留，没有改写成成功。真实业务资料建模与 OCR 不在此次合成执行验收范围内。

## 配置与版本差异

插件 `0.1.1` 保留 rc.5 的有效工作目录服务；在没有该服务的 rc.2 中，使用当前 agent 的绝对 `session.header.cwd`。非 agent 调用才使用可选 `defaultDirectory` 或宿主启动目录，不把一个会话的文件落到另一个会话。

完整 SDK profile 默认带 `fs-sandbox`。插件目前只有裸本地执行适配，需在独立验收 profile 的覆盖文件中显式配置：

```yaml
- id: fs-sandbox
  disabled: true
- insert:
    - id: ontology-acceptance-fs-local
      name: '@deepseek-ai/dsh-fs-local'
      config:
        cwd: 'D:/ontology-acceptance/workspace'
- id: ontology
  config:
    pythonExecutable: 'D:/tools/ontology-python/Scripts/python.exe'
    javaExecutable: 'C:/Program Files/Java/jdk-25.0.2/bin/java.exe'
    workspaceRoots: ['D:/ontology-acceptance/workspace']
    timeoutSeconds: 900
```

在 rc.2 的配置补丁中，已有条目的 `name` 是匹配断言，不是重命名。不能用 `id: fs-sandbox` 配另一个 `name` 来更换服务；应禁用旧条目并插入新条目。此覆盖改变整个验收 profile 的文件服务，仅用于经部署者明确选择的本地运行环境，不能作为项目 RDF 输入的一部分。

## 应核验的结果

1. 官方 CLI 确实启动，Loader 没有插件激活失败，四个 ontology 工具及十个技能可用；SDK stdout 保持合法 JSON-RPC。
2. 经真实工具注册表执行环境、项目创建、检查、冻结、推理、查询和重放。SHACL 不符合、OWL 不一致和技术错误分别检查 `3 / 1 / 2`，不得归并为一种失败。
3. 实际运行公式示例的 HermiT、独立黄金案例和 replay；检查源快照及语义结果，而不是仅看命令返回。
4. 在线模型会话中，配对 `tool/call` 与 `tool/result`，核验所有要求的操作和输出图；独立查询确认预期值及类型。模型口头总结不作为执行证据。
5. 标准 SDK `shutdown` 得到确认且进程正常退出；运行前后确认原有业务配置和凭证存储保持不变。

公式示例的 `0.00005 m` 与 `NeedsSyntheticReview` 是合成测试预期，不能作为真实业务阈值。在线会话只发送合成资料；凭证通过宿主官方凭证解析器在内存中获取，不写入 profile、源码、提示词或验收报告。

每次验收使用新工作区和新输出目录。完整日志、会话事件、推理产物和实际验收报告保存于方法库及 Git 仓库之外；仓库只维护实现、方法与可复用验证入口。
