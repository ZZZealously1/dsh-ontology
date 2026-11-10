# Third-party distribution and source guide

MIT covers this project's own code and methods. Java/Python components retain their upstream licenses. This guide records the materials supplied with this release; it does not replace the licenses or provide a legal warranty.

## Supplied records

- `third-party/java-components.tsv`: all top-level and nested JAR locations, SHA-256 values, license summaries and record directories. There are 54 locations / 43 unique archive contents.
- `third-party/licenses/`: extracted JAR and wheel notices, original Maven metadata, supplemental upstream license texts, and source-level attribution. This includes six nested HermiT JARs and 31 nested OWLAPI JARs, whether or not directly used by the classpath.
- `third-party/sources/`: complete exact HermiT upstream source, Maven source artifact and POM; OBOFormat's source artifact with original declarations.
- `third-party/origins.tsv`, `third-party/manifest.sha256`: supplemental material's origins and fingerprints.

The old vendor README describes incomplete records from its original local snapshot. It is retained unchanged for provenance. Additional public-distribution material is supplied beside that snapshot, without altering the old runtime fingerprints.

## Exact HermiT source

The artifact coordinate is `net.sourceforge.owlapi:org.semanticweb.hermit:1.4.3.456`. The official binary from [Maven Central](https://repo.maven.apache.org/maven2/net/sourceforge/owlapi/org.semanticweb.hermit/1.4.3.456/) has SHA-256 `4a402a3d6f35c57b2dc67228db3db7775bb027b45029bcbaec32e6c907e3a409`, exactly matching the bundled JAR. The source JAR has SHA-256 `a9dd3d221cd236cf53dd1c148ca68cd4af303a65a0ad2fa66c527dce53337cff`.

The complete source tree is from [commit dd2a021a01d4f847c3f8c283bdabb23e74070882](https://github.com/owlcs/hermit-reasoner/tree/dd2a021a01d4f847c3f8c283bdabb23e74070882). All 255 Java files in the official source JAR match that tree after CRLF/LF normalization. Its `pom.xml` exactly matches the official Maven POM. The full tree also includes original build configuration, resources, tests, examples, README and GPL/LGPL texts.

No upstream Java library was modified for this plugin. Source correspondence was checked; a bit-for-bit rebuild of HermiT was not performed. The historical binary records JDK 1.8.0_144; timestamps and build environments can affect archive bytes.

## Rebuilding and replacing HermiT

Library modification and reverse engineering for debugging modifications are permitted by the upstream licenses. The plugin's MIT code adds no prohibition. Application source, Java bridge source and corresponding library source are included so users can rebuild and relink their own version.

1. Extract `third-party/sources/hermit-1.4.3.456-dd2a021a01d4f847c3f8c283bdabb23e74070882.zip` into a separate development directory.
2. Install a compatible JDK and Maven. The supplied POM targets Java 8 and declares Maven 3.0.5 or later. Use its declared build dependencies, including OWLAPI 4.5.6; do not substitute versions from this plugin's runtime OWLAPI 4.5.29 without reviewing compatibility.
3. From the extracted source root, run `mvn -DskipTests package`. Run `mvn test` for upstream tests. Source rebuilding may download build dependencies; normal ontology reasoning does not run these commands.
4. In a development fork, replace `Ontology/Ontology-tools/vendor/owl-dl/lib/org.semanticweb.hermit-1.4.3.456.jar` with an interface-compatible modified build. Preserve its notices, identify modifications and version, and provide the corresponding modified source when redistributing.
5. Refresh the fork's `vendor/owl-dl/manifest.sha256` for its actual files, excluding the manifest itself. Run `python -B Ontology/Ontology-tools/java/build.py` to compile the bridge against the local JARs and refresh the Java manifest. Refresh `source-manifest.sha256` for the resulting `Ontology/` snapshot and assign the fork a new release identity.
6. Run bridge checks, plugin tests and applicable ontology semantic/golden tests before using or distributing the new version.

These fingerprint changes create a **new runtime version**. They must not be used to pass replay of an old run: runs recorded with old dependency fingerprints still require that old runtime. All fingerprint-check code is supplied; the checks record provenance rather than prohibit user modification.

## Mixed license records

- HermiT's historical README describes bundled JAutomata/rationals as LGPL-2.1, while individual source files carry BSD-style notices. Full corresponding rationals source, LGPL-2.1 text and supplied notices are retained without overwriting their declarations.
- OWLAPI declares Apache/LGPL alternatives. Apache is selected for its dual-licensed code. The OBOFormat POM separately declares BSD-3-Clause and identifies [owlcollab/oboformat](https://github.com/owlcollab/oboformat) as its original code/author source. The exact source JAR and metadata are preserved. `BSD-3-Clause-template.txt` is the SPDX standard template, not an invented component copyright notice.
- jsr305's POM declares Apache-2.0. `GuardedBy`, `Immutable`, `NotThreadSafe` and `ThreadSafe` have `Copyright (c) 2005 Brian Goetz`, a [CC BY 2.5 license URI](https://creativecommons.org/licenses/by/2.5/), and [JCIP](https://jcip.net/) attribution. Their source notices are separately retained.
- Guava has public-domain JSR-166-derived files. Jackson Core includes FastDoubleParser and other third-party notices. HPPC-RT's NOTICE credits HPPC, Lucene, Fastutil, Koloboke and Cliff Moon. These records are included.

## Redistributing

Ship `LICENSE`, `THIRD_PARTY_NOTICES.md` and the full `third-party/` directory alongside the original dependency notices. HermiT corresponding source is available in the same downloadable repository and plugin package as its binary, without a separate request or charge. First-party MIT terms do not remove conditions in upstream licenses.

This inventory covers the supplied versions. Updating a dependency requires reviewing its license and source material again and repeating semantic regression tests. Source provenance verification is not a security audit or a certification of future versions.
