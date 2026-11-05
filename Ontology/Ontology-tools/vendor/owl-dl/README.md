# OWL DL 离线依赖

依赖从已有 Protégé 5.6.9 Windows 安装包本地复制，未下载、未修改 JAR。运行时仅使用本目录；不读取原 Protégé 目录。`sources.tsv` 记录每个 JAR 的版本、安装包内来源及 SHA-256，`manifest.sha256` 覆盖依赖与附带记录，检测遗漏、变更和额外文件。

主要组件为 HermiT `1.4.3.456`、OWLAPI `4.5.29`、Guava `18.0`、SLF4J API `1.7.36`。普通 Java classpath 不展开 OSGi 的嵌套 JAR，因此将实际需要的 automaton、hppcrt、caffeine、jsr305、commons-io、xz，以及 HermiT XMLLiteral 所需 axiom API/c14n/impl/dom 与 commons-logging 提取为原始字节，并加入本地 javax.inject 与 Jakarta Activation API 1.2.2（`javax.activation` 包），共 17 个 classpath JAR。根 JAR 保持原样，内含未启用的其他格式解析器/依赖；桥只注册 RDF/XML parser。

## 许可证与版本依据

- HermiT：原始 Manifest 与 Maven POM 声明 LGPL 3。`licenses/LGPL-3.0.txt` 与 `GPL-3.0.txt` 是本机 Git 随附的原版通用许可证全文，分别取自 libunistring 的 `LICENSE.LIB` 与 xz 的 `COPYING.GPLv3`，未修改文本。
- OWLAPI：原 Manifest 声明 Apache/LGPL 双许可；Guava、jsr305、caffeine 等的许可证声明与嵌入文本保留在 `licenses/`。通用 `Apache-2.0.txt` 原文取自本机 javax.inject bundle 的 `META-INF/LICENSE`。
- 已提取各个 JAR 中实际包含的 LICENSE/NOTICE、Manifest、含许可声明的 POM；未删除原 JAR 内其他版权与来源信息。
- 原始分发包中的部分依赖没有独立许可证全文，现有记录不构成完整的对外再分发许可证审计，也不虚构这些缺失文本。此目录供本项目本地运行；若另行对外分发，应按各上游许可证取得相应版权声明、许可文本和所需源码。

HermiT 的 JAR Manifest/POM 版本是 `1.4.3.456`，其 API `getReasonerVersion()` 自报 `1.4.1.432`。报告同时记录二者，避免假定它们相等。

版本更新时应重新取得完整依赖集，核对原有许可记录，运行正反及 profile、不可满足类、加载失败案例，然后更新来源和哈希；不要仅替换 JAR 文件绕过指纹验证。
