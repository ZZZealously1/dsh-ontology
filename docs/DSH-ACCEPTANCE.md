# 在真实 DSH 中验收

`scripts/verify-dsh.mjs` 验证真实 SDK 服务组合，适合回归。实际部署还需经官方 `dsh` CLI 启动 Loader、加载 profile 和插件，再调用工具；在线模型验收则进一步要求检查真实模型会话事件、工具调用和保存的推理证据。这三层结果分别记录，不能相互替代。

2026-11-10 验收使用现有 Windows x64 DSH `0.2.0-rc.2` 运行程序和独立 `DSH_HOME`，通过正常插件安装入口加载 `0.1.1`；未启用版本豁免。原来的 `0.1.0` 仅声明 rc.5，会被此版本的正常兼容检查拒绝。

本次实际结果：完整 CLI 宿主检查 26/26 通过；DeepSeek Flash 在线会话在 12 个模型步骤内完成合成公式任务，23/23 检查通过；插件回归 31/31 通过，查询预览改动另有针对性回归通过。工具记录与独立 RDF 校验确认 `0.00005 m`、`Computed` 和 `NeedsSyntheticReview`，黄金案例和 replay 均通过。原方法库 327 个文件的指纹与源目录一致。

在线验收发现并修复了两个产品问题：旧版宿主缺少工作目录服务时无法激活，以及查询只返回产物路径、模型不能直接核对值。验收夹具本身的路径、TSV 引号解析和 scoped guard 问题也已修正后重跑；旧失败记录保留，没有改写成成功。真实业务资料建模与 OCR 不在此次合成执行验收范围内。

## 公开版本 0.2.0：默认沙箱验收

公开版本保留 `fs-sandbox / sandbox-local / subprocess-local`，不再要求替换默认文件服务。实际 DSH `0.2.0-rc.2` CLI 在独立 profile 内创建真实 agent/session，通过其工具注册表运行 **27/27** 项检查：包含环境、十个技能、项目创建、冻结、有限推理、HermiT 公式推理、黄金案例、查询、replay、三种失败退出状态、路径越界以及同一会话切换为 `read-only` 后拒绝写入。未发出模型请求；模型语义质量仍以此前在线合成验收的实际范围为限。

调用由宿主有效会话策略控制。`workspace-write` 允许的输出还必须位于插件配置的 `workspaceRoots`，后者不能放宽会话权限。`ontology_environment` 报告真实 `sandbox.mode` 和 `sandbox.enforcement`；本次 Windows 官方后端报告 `partial`。这不是完整系统隔离或网络隔离的声明。

Windows 验收先在权限不满足要求的目录失败：DSH 设置 ACL 标签报 `SetNamedSecurityInfoW / Win32 5`。工作目录必须由 DSH 用户拥有，且有 FullControl（含 WRITE_OWNER）；仅 Modify 不足。换用权限符合要求的全新用户目录后，全部流程通过。旧失败日志保留；没有改写为成功，没有自动改 ACL，没有关闭沙箱回退。

`0.2.0` 保留 rc.5 的工作目录服务；rc.2 使用真实会话的绝对 `session.header.cwd`。以下只配置插件，不替换宿主沙箱服务。目录应已存在并满足上述权限条件；会话模式通过 DSH 的正常权限控制设置。

```yaml
- id: ontology
  config:
    pythonExecutable: 'C:/tools/ontology-python/Scripts/python.exe'
    javaExecutable: 'C:/Program Files/Java/jdk-25.0.2/bin/java.exe'
    workspaceRoots: ['C:/Users/your-name/ontology-projects']
    timeoutSeconds: 900
```

SDK 服务层回归仍可使用明确选择的裸本地服务，以检查兼容模式；不能据此代替真实沙箱验收。标准 `pnpm pack` 解压后已核验完整源快照和依赖材料。远程 GitHub 安装结果按实际发布验收另记。

## 应核验的结果

1. 官方 CLI 确实启动，Loader 没有插件激活失败，四个 ontology 工具及十个技能可用；SDK stdout 保持合法 JSON-RPC。
2. 经真实工具注册表执行环境、项目创建、检查、冻结、推理、查询和重放。SHACL 不符合、OWL 不一致和技术错误分别检查 `3 / 1 / 2`，不得归并为一种失败。
3. 实际运行公式示例的 HermiT、独立黄金案例和 replay；检查源快照及语义结果，而不是仅看命令返回。
4. 在线模型会话中，配对 `tool/call` 与 `tool/result`，核验所有要求的操作和输出图；独立查询确认预期值及类型。模型口头总结不作为执行证据。
5. 标准 SDK `shutdown` 得到确认且进程正常退出；运行前后确认原有业务配置和凭证存储保持不变。

公式示例的 `0.00005 m` 与 `NeedsSyntheticReview` 是合成测试预期，不能作为真实业务阈值。在线会话只发送合成资料；凭证通过宿主官方凭证解析器在内存中获取，不写入 profile、源码、提示词或验收报告。

每次验收使用新工作区和新输出目录。完整日志、会话事件、推理产物和实际验收报告保存于方法库及 Git 仓库之外；仓库只维护实现、方法与可复用验证入口。
