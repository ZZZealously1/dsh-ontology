# Third-party source and notice material

This directory supplements the unchanged Ontology runtime snapshot. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and [the source and rebuilding guide](../docs/THIRD_PARTY.md).

`java-components.tsv` identifies every original JAR and embedded JAR by hash, including repeat copies. Archive LICENSE/NOTICE and metadata files are extracted without changing their contents; archive-path separators in their filenames become `__`. Python wheel metadata and license files are similarly extracted. `origins.tsv` records additional downloaded source/license files and source-header extracts. The source-header files preserve original notices and list their applicable Java files. No upstream binary library is modified.

The HermiT source ZIP, Maven source JAR and POM are provided alongside the binary in this repository and plugin package. Their original upstream licenses apply. The source ZIP includes tests, resources, build configuration and original GPL/LGPL texts; a source-to-release comparison is recorded in `source-verification.txt`.

The BSD-3-Clause standard template is named as a template; original component metadata and source declarations remain available. It does not assign a fabricated copyright owner.

`manifest.sha256` fingerprints this supplemental directory. Runtime dependency fingerprints remain in the unchanged Ontology snapshot. This directory's source/notice archives are not runtime classpath additions.
