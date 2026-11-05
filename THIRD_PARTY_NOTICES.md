# Third-party notices

This repository preserves the existing Ontology snapshot and its dependency archives. This notice does not relicense upstream components or grant a new license to project-specific source or methods. Each third-party component retains its own copyright and license terms.

## Ontology Java dependencies

The 17 original classpath JARs are under `Ontology/Ontology-tools/vendor/owl-dl/lib/`. Their recorded versions, provenance and SHA-256 values are in [sources.tsv](Ontology/Ontology-tools/vendor/owl-dl/sources.tsv); the existing [manifest](Ontology/Ontology-tools/vendor/owl-dl/manifest.sha256) is retained without changes. Extraction provenance, version details and the scope of the original license records are described in the [vendor README](Ontology/Ontology-tools/vendor/owl-dl/README.md).

The included [licenses directory](Ontology/Ontology-tools/vendor/owl-dl/licenses) preserves extracted LICENSE/NOTICE files, JAR manifests and available Maven POM metadata, including LGPL-3.0, GPL-3.0 and Apache-2.0 texts. HermiT's recorded upstream declaration is LGPL 3; OWLAPI's recorded declaration is Apache/LGPL dual licensing. Other components keep their declarations in the corresponding archives and retained metadata.

The original vendor documentation explicitly states that its existing records are not a complete external redistribution audit. This plugin preserves that limitation and does not claim that copying the notice alone fulfills every upstream redistribution obligation or supplies all corresponding source. Keep the recorded notices and verify the requirements of each component for any wider distribution.

## Offline Python wheels

Eight unchanged wheels are retained in [python-wheels](Ontology/Ontology-tools/vendor/python-wheels). Their embedded distribution metadata and license files remain inside the wheels. The installed versions are governed by [requirements.lock.txt](Ontology/Ontology-tools/requirements.lock.txt), rather than by this summary.

| Component | Bundled version | License information recorded in wheel metadata |
|---|---|---|
| html5rdf | 1.2.1 | MIT license text |
| owlrl | 7.1.4 | W3C Software and Document Notice License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| prettytable | 3.18.0 | BSD-3-Clause |
| pyparsing | 3.3.3 | MIT |
| pyshacl | 0.30.1 | Apache-2.0 license text |
| rdflib | 7.1.4 | BSD-3-Clause |
| wcwidth | 0.9.2 | MIT classifier and embedded distribution metadata |

## DSH and Node dependencies

DeepSeek Harness and its dependencies are obtained through the versions declared in the plugin package manifest and lockfile. Installed packages retain their own upstream license files; `node_modules/` is not part of the source snapshot. The DSH project source and its current notices are available from [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness).

Runtime Python, Java and Node installations are separate prerequisites. The plugin does not assert ownership of or a new license for those runtimes.
