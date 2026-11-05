"""Behavioral tests for offline conversion, mappings and fusion helpers."""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FUSION = Path(__file__).resolve().parents[2] / "ontology-fusion" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(FUSION))
import local_graph as migration
import fuse_local as fusion
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, XSD

EX = Namespace("urn:example:test:")
PRE = '@prefix ex: <urn:example:test:> . @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'
MPRE = '@prefix m: <urn:ontology:local-migration:> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'


class LocalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("ONTOLOGY_TEST_OUTPUT"))
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.assertFalse(list(self.root.rglob("*.json")))
        self.assertFalse(list(self.root.rglob("*.jsonld")))
        self.temp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def csv_map(self, datatype="integer", missing="error"):
        return self.write("mapping.ttl", MPRE + f'''[] a m:Mapping ; m:mode "instances" ; m:keyColumn "id" ; m:baseIRI <urn:example:part:> ; m:targetClass <urn:example:model:Part> ;
          m:field [ m:column "value" ; m:property <urn:example:model:value> ; m:datatype xsd:{datatype} ; m:missing "{missing}" ] .''')

    def test_roundtrip_preserves_blank_nodes_lists_language_and_lexical_value(self):
        source = self.write("source.ttl", PRE + 'ex:A a owl:Class ; rdfs:label "甲"@zh ; owl:unionOf ( ex:B ex:C ) . ex:x ex:v "007"^^xsd:integer .')
        before = source.read_bytes()
        result = migration.convert(source, self.root / "xml", "xml")
        restored = migration.convert(result, self.root / "ttl", "turtle")
        self.assertTrue(isomorphic(migration.load(source), migration.load(restored)))
        self.assertIn((EX.x, EX.v, Literal("007", datatype=XSD.integer, normalize=False)), migration.load(restored))
        self.assertEqual(before, source.read_bytes())

    def test_relative_iri_retains_source_base_after_move(self):
        source = self.write("relative.ttl", '<item> <urn:test:p> "v" .')
        result = migration.convert(source, self.root / "moved", "xml")
        self.assertTrue(isomorphic(migration.load(source), migration.load(result)))
        self.assertIn(URIRef((self.root / "item").as_uri()), set(migration.load(result).subjects()))

    def test_equal_triple_counts_do_not_prove_equivalence(self):
        left = self.write("a.ttl", PRE + 'ex:a ex:p "before" .')
        right = self.write("b.ttl", PRE + 'ex:a ex:p "after" .')
        self.assertEqual(len(migration.load(left)), len(migration.load(right)))
        self.assertFalse(isomorphic(migration.load(left), migration.load(right)))

    def test_output_cannot_overwrite_evidence(self):
        source = self.write("a.ttl", PRE + "ex:A a owl:Class .")
        migration.convert(source, self.root / "run", "turtle")
        with self.assertRaises(ValueError):
            migration.convert(source, self.root / "run", "turtle")
        with self.assertRaises(ValueError):
            migration.convert(source, source, "turtle")

    def test_dtd_and_owlxml_are_rejected(self):
        dtd = self.write("evil.owl", '<!DOCTYPE rdf:RDF [<!ENTITY a SYSTEM "https://invalid.example/file">]><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>')
        owlxml = self.write("unsupported.owl", '<Ontology xmlns="http://www.w3.org/2002/07/owl#" ontologyIRI="urn:example:o"/>')
        for source in (dtd, owlxml):
            with self.assertRaises(ValueError):
                migration.load(source)

    def test_outputs_cannot_pollute_method_or_source_package(self):
        source = self.write("ontology.ttl", PRE + "ex:A a owl:Class .")
        for output in (self.root / "inside-package", SCRIPTS.parent / "forbidden-test-output"):
            with self.assertRaises(ValueError):
                migration.convert(source, output, "turtle")
            self.assertFalse(output.exists())

    def test_conversion_preserves_imports_without_fetch(self):
        source = self.write("a.ttl", PRE + 'ex:ontology a owl:Ontology ; owl:imports <https://invalid.example/unavailable> .')
        result = migration.convert(source, self.root / "out", "xml")
        self.assertIn((EX.ontology, OWL.imports, URIRef("https://invalid.example/unavailable")), migration.load(result))

    def test_patch_changes_only_explicit_triples(self):
        source = self.write("source.ttl", PRE + "ex:C a owl:Class ; rdfs:subClassOf ex:Old, ex:Other .")
        remove = self.write("remove.ttl", PRE + "ex:C rdfs:subClassOf ex:Old .")
        add = self.write("add.ttl", PRE + "ex:C rdfs:subClassOf ex:New .")
        before = source.read_bytes()
        result = migration.patch(source, add, remove, self.root / "patch")
        graph = migration.load(result)
        self.assertNotIn((EX.C, RDFS.subClassOf, EX.Old), graph)
        self.assertIn((EX.C, RDFS.subClassOf, EX.New), graph)
        self.assertIn((EX.C, RDFS.subClassOf, EX.Other), graph)
        self.assertEqual(before, source.read_bytes())

    def test_patch_missing_or_blank_removal_is_rejected(self):
        source = self.write("source.ttl", PRE + "ex:C a owl:Class .")
        for index, text in enumerate(("ex:C rdfs:subClassOf ex:Missing .", "ex:C ex:p [] .")):
            removal = self.write(f"remove{index}.ttl", PRE + text)
            with self.assertRaises(ValueError):
                migration.patch(source, None, removal, self.root / f"bad{index}")

    def test_csv_instances_identity_and_typed_value(self):
        source = self.write("rows.csv", "id,value\nA/1,007\nA%2F1,0\n")
        result = migration.csv_import(source, self.csv_map(), self.root / "out")
        graph = migration.load(result)
        self.assertIn((URIRef("urn:example:part:A%2F1"), URIRef("urn:example:model:value"), Literal("007", datatype=XSD.integer, normalize=False)), graph)
        self.assertIn(URIRef("urn:example:part:A%252F1"), set(graph.subjects()))
        evidence = migration.load(self.root / "out" / "report.ttl")
        self.assertEqual(2, len(list(evidence.objects(None, migration.E.businessKey))))

    def test_csv_invalid_integer_is_not_coerced(self):
        source = self.write("rows.csv", "id,value\nx,1.5\n")
        with self.assertRaises(ValueError):
            migration.csv_import(source, self.csv_map(), self.root / "out")

    def test_csv_zero_false_and_missing_remain_distinct(self):
        source = self.write("rows.csv", "id,value\nx,false\ny,\n")
        graph = migration.load(migration.csv_import(source, self.csv_map("boolean", "omit"), self.root / "out"))
        self.assertIn((URIRef("urn:example:part:x"), URIRef("urn:example:model:value"), Literal(False)), graph)
        self.assertEqual([], list(graph.objects(URIRef("urn:example:part:y"), URIRef("urn:example:model:value"))))

    def test_csv_rejects_duplicate_keys_unmapped_columns_and_missing(self):
        mapping = self.csv_map()
        for index, rows in enumerate(("id,value\nx,1\nx,2\n", "id,value,extra\nx,1,orphan\n", "id,value\nx,\n", "id,value\n,1\n", "id,value\nx,1,extra\n")):
            with self.assertRaises(ValueError):
                migration.csv_import(self.write(f"bad{index}.csv", rows), mapping, self.root / f"out{index}")

    def test_csv_class_definition_preserves_labels_parent_comment(self):
        source = self.write("classes.csv", "key,label,parent,description\nRoot,根,,共同实体\nChild,子,Root,具体实体\n")
        mapping = self.write("classes-map.ttl", MPRE + '[] a m:Mapping ; m:mode "classes" ; m:keyColumn "key" ; m:baseIRI <urn:example:class:> ; m:labelColumn "label" ; m:parentColumn "parent" ; m:commentColumn "description" .')
        graph = migration.load(migration.csv_import(source, mapping, self.root / "classes"))
        self.assertIn((URIRef("urn:example:class:Child"), RDFS.subClassOf, URIRef("urn:example:class:Root")), graph)
        self.assertIn((URIRef("urn:example:class:Root"), RDFS.label, Literal("根", lang="zh")), graph)
        self.assertIn((URIRef("urn:example:class:Child"), RDFS.comment, Literal("具体实体", lang="zh")), graph)

    def test_csv_missing_parent_rejected(self):
        source = self.write("classes.csv", "key,label,parent\nChild,子,Unknown\n")
        mapping = self.write("classes-map.ttl", MPRE + '[] a m:Mapping ; m:mode "classes" ; m:keyColumn "key" ; m:baseIRI <urn:example:class:> ; m:labelColumn "label" ; m:parentColumn "parent" .')
        with self.assertRaises(ValueError):
            migration.csv_import(source, mapping, self.root / "out")

    def test_multiline_csv_has_record_numbers_not_physical_lines(self):
        source = self.write("multiline.csv", 'id,value\nx,"first\nsecond"\ny,last\n')
        migration.csv_import(source, self.csv_map("string"), self.root / "out")
        evidence = migration.load(self.root / "out" / "report.ttl")
        self.assertEqual({1, 2}, {int(v) for v in evidence.objects(None, migration.E.sourceRecord)})
        self.assertEqual([], list(evidence.triples((None, migration.E.line, None))))

    def test_candidates_preserve_one_to_many_without_equivalence(self):
        left = self.write("left.ttl", PRE + 'ex:A a owl:Class ; rdfs:label "件"@zh . ex:B a owl:Class ; rdfs:label "件"@zh .')
        right = self.write("right.ttl", PRE + 'ex:C a owl:Class ; rdfs:label "件"@zh . ex:D a owl:Class ; rdfs:label "件"@en .')
        graph = migration.load(fusion.candidates(left, right, self.root / "out"))
        self.assertEqual(2, len(set(graph.subjects(RDF.type, fusion.F.Alignment))))
        self.assertEqual(set(), set(graph.triples((None, OWL.equivalentClass, None))))
        self.assertNotIn(EX.D, set(graph.objects(None, fusion.F.target)))

    def test_merge_preserves_blank_node_scopes(self):
        left = self.write("left.ttl", PRE + 'ex:A ex:p _:same . _:same ex:value "left" .')
        right = self.write("right.ttl", PRE + 'ex:B ex:p _:same . _:same ex:value "right" .')
        graph = migration.load(fusion.merge([left, right], None, self.root / "out"))
        a = graph.value(EX.A, EX.p)
        b = graph.value(EX.B, EX.p)
        self.assertNotEqual(a, b)
        self.assertEqual({Literal("left")}, set(graph.objects(a, EX.value)))
        self.assertEqual({Literal("right")}, set(graph.objects(b, EX.value)))

    def test_approved_mapping_adds_only_requested_axiom(self):
        left = self.write("left.ttl", PRE + 'ex:A a owl:Class ; rdfs:label "A" .')
        right = self.write("right.ttl", PRE + 'ex:B a owl:Class ; rdfs:label "B" .')
        mapping = self.write("decisions.ttl", PRE + '@prefix f: <urn:ontology:local-fusion:> . [] a f:Alignment ; f:source ex:A ; f:target ex:B ; f:relation owl:equivalentClass ; f:status "approved" ; f:evidence <urn:example:review> ; f:reason "Definitions verified" .')
        graph = migration.load(fusion.merge([left, right], mapping, self.root / "out"))
        expected = migration.fresh_union([migration.load(left), migration.load(right)])
        expected.add((EX.A, OWL.equivalentClass, EX.B))
        self.assertTrue(isomorphic(expected, graph))
        report = migration.load(self.root / "out" / "report.ttl")
        recorded = {str(report.value(item, migration.E.source)).rsplit("/", 1)[-1] for item in report.objects(None, migration.E.implementation)}
        self.assertEqual({"fuse_local.py", "local_graph.py"}, recorded)

    def test_candidate_mapping_and_wrong_entity_type_rejected(self):
        left = self.write("left.ttl", PRE + "ex:A a owl:Class .")
        right = self.write("right.ttl", PRE + "ex:B a owl:DatatypeProperty .")
        for index, status in enumerate(("candidate", "approved")):
            mapping = self.write(f"m{index}.ttl", PRE + f'@prefix f: <urn:ontology:local-fusion:> . [] a f:Alignment ; f:source ex:A ; f:target ex:B ; f:relation owl:equivalentClass ; f:status "{status}" ; f:evidence "source" ; f:reason "test" .')
            with self.assertRaises(ValueError):
                fusion.merge([left, right], mapping, self.root / f"out{index}")

    def test_unresolved_imports_rejected_for_merge(self):
        left = self.write("left.ttl", PRE + "ex:O a owl:Ontology ; owl:imports <https://invalid.example/no> .")
        right = self.write("right.ttl", PRE + "ex:B a owl:Class .")
        with self.assertRaises(ValueError):
            fusion.merge([left, right], None, self.root / "out")

    def test_cli_runs_and_manifest_matches_actual_files(self):
        source = self.write("source.ttl", PRE + "ex:A a owl:Class .")
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "local_graph.py"), "convert", "--source", str(source), "--format", "xml", "--output", str(self.root / "cli")], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        for line in (self.root / "cli" / "manifest.sha256").read_text().splitlines():
            checksum, relative = line.split("  ", 1)
            self.assertEqual(checksum, hashlib.sha256((self.root / "cli" / relative).read_bytes()).hexdigest())
        report = migration.load(self.root / "cli" / "report.ttl")
        self.assertEqual(Literal(False), report.value(URIRef("urn:ontology:local-run"), migration.E.consistencyChecked))


if __name__ == "__main__":
    unittest.main()
