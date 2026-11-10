# Third-party notices

The [MIT license](LICENSE) applies to this project's own code and methods. It does not relicense third-party libraries, source archives, or license texts. Each component retains its upstream copyright and license terms.

## Ontology Java dependencies

The 17 original classpath JARs are under `Ontology/Ontology-tools/vendor/owl-dl/lib/`. Their recorded versions, provenance and SHA-256 values are in [sources.tsv](Ontology/Ontology-tools/vendor/owl-dl/sources.tsv); the existing [manifest](Ontology/Ontology-tools/vendor/owl-dl/manifest.sha256) is retained without changes. Extraction provenance, version details and the scope of the original license records are described in the [vendor README](Ontology/Ontology-tools/vendor/owl-dl/README.md).

The included [licenses directory](Ontology/Ontology-tools/vendor/owl-dl/licenses) preserves extracted LICENSE/NOTICE files, JAR manifests and available Maven POM metadata, including LGPL-3.0, GPL-3.0 and Apache-2.0 texts. HermiT's recorded upstream declaration is LGPL 3; OWLAPI's recorded declaration is Apache/LGPL dual licensing. Other components keep their declarations in the corresponding archives and retained metadata.

This release adds [supplemental notices](third-party/licenses), a [complete nested-JAR inventory](third-party/java-components.tsv), and [the source/rebuilding guide](docs/THIRD_PARTY.md) beside the unchanged historical snapshot. The inventory covers 54 archive locations / 43 unique JAR contents: 17 top-level JARs, six nested in HermiT, and 31 nested in OWLAPI. Nested components keep their own licenses even when not directly used by the runtime classpath.

HermiT 1.4.3.456 is used under **LGPL-3.0-or-later**, as declared in its source headers. Copyright belongs to the Oxford University Computing Laboratory / University of Oxford and contributors. Copies of [LGPL-3.0](third-party/licenses/LGPL-3.0.txt), [GPL-3.0](third-party/licenses/GPL-3.0.txt), the [complete corresponding upstream source tree](third-party/sources/hermit-1.4.3.456-dd2a021a01d4f847c3f8c283bdabb23e74070882.zip), [exact Maven source artifact](third-party/sources/org.semanticweb.hermit-1.4.3.456-sources.jar), and [POM](third-party/sources/org.semanticweb.hermit-1.4.3.456.pom) accompany this repository and plugin package at no additional charge.

The bundled HermiT binary matches the official Maven artifact by SHA-256. All 255 Java files in the Maven source artifact match the supplied complete upstream tree after CRLF/LF normalization, and its POM matches byte-for-byte. See [source verification](third-party/source-verification.txt). This establishes recorded provenance; it does not claim a byte-identical rebuild. The library has not been modified for this plugin.

The embedded `rationals` / JAutomata source is included. HermiT's historical README describes it as LGPL-2.1; some files carry BSD-style notices. Both the [LGPL-2.1 text](third-party/licenses/LGPL-2.1.txt) and [original source notices](third-party/licenses/org.semanticweb.hermit-1.4.3.456-SOURCE-NOTICES.txt) are retained. This project does not prohibit modification of the library or reverse engineering for debugging such modifications. See the [rebuilding and relinking instructions](docs/THIRD_PARTY.md#rebuilding-and-replacing-hermit).

### Supplemental Java attribution

| Components | License records |
|---|---|
| OWLAPI 4.5.29 | Apache-2.0 or LGPL-3.0; this distribution selects Apache for dual-licensed code. OBOFormat's separate BSD-3-Clause declaration, metadata and source are preserved. |
| dk.brics.automaton 1.11-8 | BSD-3-Clause; original Anders Moeller notice. |
| HPPC-RT, Caffeine, Apache Axiom/Commons, HttpClient/HttpCore, Jackson, jsonld-java, javax.inject wrapper | Apache-2.0 and original LICENSE/NOTICE records. Jackson Core also includes FastDoubleParser/third-party notices. |
| Guava 18.0 | Apache-2.0; four JSR-166-derived files have separately retained public-domain declarations. |
| jsr305 3.0.2 | Apache-2.0 in POM. Four concurrent annotations also carry Brian Goetz's [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/) notices and [JCIP](https://jcip.net/) attribution. |
| SLF4J API 1.7.36 | MIT. |
| XZ for Java 1.9 | Upstream public-domain dedication and warranty disclaimer. |
| Jakarta Activation API 1.2.2 | Original BSD-style LICENSE and NOTICE. |
| RDF4J 3.7.7 modules in OWLAPI | Eclipse Distribution License / BSD-style license text and copyright. |

This table is an index; the original records remain authoritative. The original vendor README describes the older local inventory, while the supplemental records supply the additional source and notices used for this release.

## Offline Python wheels

Eight unchanged wheels are retained in [python-wheels](Ontology/Ontology-tools/vendor/python-wheels). Their metadata and license files remain inside the wheels and are also extracted under [third-party/licenses](third-party/licenses). The installed versions are governed by [requirements.lock.txt](Ontology/Ontology-tools/requirements.lock.txt), rather than by this summary.

| Component | Bundled version | License information recorded in wheel metadata |
|---|---|---|
| html5rdf | 1.2.1 | MIT license text |
| owlrl | 7.1.4 | W3C Software and Document Notice License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| prettytable | 3.18.0 | BSD-3-Clause |
| pyparsing | 3.3.3 | MIT |
| pyshacl | 0.30.1 | Apache-2.0 license text |
| rdflib | 7.1.4 | BSD-3-Clause |
| wcwidth | 0.9.2 | MIT plus the original Markus Kuhn permissive notice |

## DSH and Node dependencies

DeepSeek Harness and its dependencies are obtained through the versions declared in the plugin package manifest and lockfile. Installed packages retain their own upstream license files; `node_modules/` is not part of the source snapshot. The DSH project source and its current notices are available from [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness).

Runtime Python, Java and Node installations are separate prerequisites. The plugin does not assert ownership of or a new license for those runtimes.

When redistributing, retain this file, the first-party license, original archive notices, and the full `third-party/` source and license material. Review the corresponding source and notices again when changing dependency versions. This release inventory is not a legal warranty or a security audit.
