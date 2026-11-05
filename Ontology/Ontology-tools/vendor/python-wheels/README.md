# 离线 Python 依赖

本目录保存 `requirements.lock.txt` 所需的本地缓存 wheel，供 CPython 3.12 / Windows x64 离线安装。未访问网络；每个 wheel 内保留其许可证与发行元数据。`html5rdf` 是 `pyshacl → rdflib[html]` 的传递依赖，现已显式锁定。

从 `Ontology-tools` 目录执行：

```powershell
uv venv --offline --python <本地CPython3.12路径> .venv
uv pip install --offline --python .venv/Scripts/python.exe --no-index --find-links vendor/python-wheels -r requirements.lock.txt
```

这里提供依赖安装材料，不声称安装、推理或项目验收已通过。实际环境版本与 wheel 指纹写入当次运行记录。
