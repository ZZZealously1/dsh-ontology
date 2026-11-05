"""Independent checks for native building, actual SWRL execution and OWL DL."""
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, XSD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT.parents[1] / "Ontology-tools"))
from build_ontology import PKG, build, parse, load
from prepare_rule_tests import prepare
from ontology_tools import check_consistency, run_cases
from ontology_tools.backend import infer as reason
from ontology_tools.io import ToolError

N = Namespace("https://example.org/rag-starter#")
OT = Namespace("https://w3id.org/ontology-tools#")
RUN = URIRef("urn:ontology-tools:run")
WORK = Path(os.environ.get("RAG_BUILD_TEST_OUTPUT", tempfile.gettempdir())).resolve()


class NativeTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(prefix="rag-build-", dir=WORK))
        cls.starter = ROOT / "models/starter/ontology"
        cls.runtime = prepare(cls.starter, cls.work / "rule-runtime")

    def test_native_source_all_parse_and_named_terms_have_labels(self):
        for _, _, _, graph in load(self.starter)[2]:
            for kind in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty):
                for term in graph.subjects(RDF.type, kind):
                    if isinstance(term, URIRef):
                        self.assertTrue(list(graph.objects(term, RDFS.label)), term)

    def test_named_class_and_property_conventions(self):
        for _, _, _, graph in load(self.starter)[2]:
            for kind in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty):
                for term in graph.subjects(RDF.type, kind):
                    if not isinstance(term, URIRef): continue
                    self.assertEqual(str(term).split("#")[0], str(N).rstrip("#"))
                    local = str(term).split("#")[-1]
                    self.assertTrue(local[0].isupper() if kind == OWL.Class else local[0].islower())

    def test_explicit_named_hierarchy_has_no_editorial_cycle(self):
        # Editorial quality of these examples; cycles alone do not prove OWL inconsistency.
        graph = Graph()
        for _, _, _, module in load(self.starter)[2]: graph += module
        visiting, visited = set(), set()
        def visit(node):
            self.assertNotIn(node, visiting)
            if node in visited: return
            visiting.add(node)
            for parent in graph.objects(node, RDFS.subClassOf):
                if isinstance(parent, URIRef): visit(parent)
            visiting.remove(node); visited.add(node)
        for node in graph.subjects(RDF.type, OWL.Class):
            if isinstance(node, URIRef): visit(node)

    def test_rebuild_semantically_identical_and_source_bytes_unchanged(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.starter.rglob("*") if p.is_file()}
        a, b = self.work / "build-a/ontology", self.work / "build-b/ontology"
        build(self.starter, a); build(self.starter, b)
        build(self.starter, a, check=True)
        self.assertTrue(isomorphic(parse(a / "integration/merged_ontology.owl"), parse(b / "integration/merged_ontology.owl")))
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_existing_output_refused_and_tamper_detected(self):
        dest = self.work / "tamper/ontology"
        build(self.starter, dest)
        with self.assertRaises(ValueError): build(self.starter, dest)
        with (dest / "subontologies/rule_vocabulary.owl").open("ab") as handle: handle.write(b"\n<!-- changed -->")
        with self.assertRaisesRegex(ValueError, "snapshot changed"): build(self.starter, dest, check=True)

    def test_noncanonical_numeric_lexical_form_preserved(self):
        source = self.work / "lexical-source"
        shutil.copytree(self.starter, source)
        path = source / "data/instances_starter.owl"
        facts = parse(path)
        facts.set((N["sensitive-11"], N.pageCount, Literal("007", datatype=XSD.integer, normalize=False)))
        facts.serialize(destination=path, format="xml")
        before = path.read_bytes()
        destination = self.work / "lexical-build/ontology"
        build(source, destination); build(source, destination, check=True)
        self.assertEqual(str(parse(destination / "data/instances_starter.owl").value(N["sensitive-11"], N.pageCount)), "007")
        self.assertEqual((destination / "data/instances_starter.owl").read_bytes(), before)

    def test_output_cannot_enter_method_library(self):
        with self.assertRaisesRegex(ValueError, "outside the Ontology"):
            build(self.starter, ROOT / "generated-not-allowed/ontology")
        with self.assertRaisesRegex(ValueError, "outside the Ontology"):
            prepare(self.starter, ROOT / "runtime-not-allowed")

    def test_selected_rule_test_scope_preserves_all_source_triples(self):
        self.assertTrue(isomorphic(parse(self.starter / "subontologies/rule_vocabulary.owl"), parse(self.runtime / "ontology.ttl")))
        self.assertEqual((self.starter / "rules/starter/starter_rules.swrl").read_bytes(), (self.runtime / "rules.swrl").read_bytes())

    def test_native_swrl_six_independent_golden_cases(self):
        output = run_cases(self.runtime, self.work / "golden")
        execution = parse(output / "execution.ttl")
        self.assertEqual(execution.value(RUN, OT.status), Literal("passed"))

    def test_rule_engine_second_pass_adds_nothing(self):
        model = parse(self.runtime / "ontology.ttl")
        rules = parse(self.runtime / "rules.swrl")
        facts = parse(self.runtime / "inputs/facts.ttl")
        first = reason(model, rules, facts)
        self.assertIn((N["sensitive-11"], RDF.type, N.RestrictedDocument), first.inferred)
        self.assertIn((N["sensitive-11"], RDF.type, N.LargeDocument), first.inferred)
        self.assertEqual(len(reason(first.closure, rules, Graph()).inferred), 0)

    def test_full_schema_not_silently_accepted_by_rule_engine(self):
        from ontology_tools.backend import UnsupportedSemantics
        full = parse(self.starter / "subontologies/rule_vocabulary.owl") + parse(self.starter / "subontologies/constraints.owl")
        with self.assertRaises(UnsupportedSemantics): reason(full, parse(self.runtime / "rules.swrl"), Graph())

    def dl(self, facts, label, source=None):
        source = source or self.starter
        models = [path for _, role, path, _ in load(source)[2] if str(role).endswith("TBox")]
        output = check_consistency(models, self.work / label, facts=facts)
        return parse(output / "report.ttl"), parse(output / "execution.ttl")

    def test_full_starter_actual_hermit_consistent(self):
        report, execution = self.dl(self.starter / "data/instances_starter.owl", "owl-starter")
        self.assertEqual(report.value(RUN, OT.consistent), Literal(True))
        self.assertEqual(execution.value(RUN, OT.status), Literal("passed"))

    def test_disjointness_conflict_detected_by_actual_hermit(self):
        facts = parse(self.starter / "data/instances_starter.owl")
        facts.remove((N["sensitive-11"], RDF.type, N.Document))
        facts.add((N["sensitive-11"], RDF.type, N.RestrictedDocument))
        facts.add((N["sensitive-11"], RDF.type, N.Organization))
        path = self.work / "contradiction.ttl"; facts.serialize(destination=path, format="turtle")
        report, execution = self.dl(path, "owl-disjoint")
        self.assertEqual(report.value(RUN, OT.consistent), Literal(False))
        self.assertEqual(execution.value(RUN, OT.status), Literal("nonconformant"))

    def test_enum_conflict_after_domain_inference(self):
        facts = parse(self.starter / "data/instances_starter.owl")
        facts.remove((N["sensitive-11"], RDF.type, N.Document))
        facts.set((N["sensitive-11"], N.securityLevel, Literal("不在枚举中", datatype=XSD.string)))
        path = self.work / "enum-conflict.ttl"; facts.serialize(destination=path, format="turtle")
        report, _ = self.dl(path, "owl-enum")
        self.assertEqual(report.value(RUN, OT.consistent), Literal(False))

    def test_functional_property_conflict_uses_distinct_individuals(self):
        facts = parse(self.starter / "data/instances_starter.owl")
        for owner in (N.ownerA, N.ownerB):
            facts.add((owner, RDF.type, N.Organization))
            facts.add((N["sensitive-11"], N.hasOwner, owner))
        facts.add((N.ownerA, OWL.differentFrom, N.ownerB))
        path = self.work / "functional-conflict.ttl"; facts.serialize(destination=path, format="turtle")
        report, _ = self.dl(path, "owl-functional")
        self.assertEqual(report.value(RUN, OT.consistent), Literal(False))

    def test_key_is_identity_axiom_not_database_unique_constraint(self):
        facts = parse(self.starter / "data/instances_starter.owl")
        facts.add((N.other, RDF.type, N.Document)); facts.add((N.other, N.docId, Literal("sensitive-11", datatype=XSD.string)))
        facts.add((N.other, OWL.differentFrom, N["sensitive-11"]))
        path = self.work / "key-conflict.ttl"; facts.serialize(destination=path, format="turtle")
        report, _ = self.dl(path, "owl-key")
        self.assertEqual(report.value(RUN, OT.consistent), Literal(False))

    def date_fixture(self, label):
        """A minimal synthetic source; unsupported types must survive authoring/building."""
        source = self.work / label
        example = Namespace("https://example.org/date-fixture#")
        model, facts, plan = Graph(), Graph(), Graph()
        model.add((URIRef(str(example).rstrip("#")), RDF.type, OWL.Ontology))
        model.add((example.Event, RDF.type, OWL.Class))
        model.add((example.Event, RDFS.label, Literal("事件", lang="zh")))
        model.add((example.eventDate, RDF.type, OWL.DatatypeProperty))
        model.add((example.eventDate, RDFS.label, Literal("发生日期", lang="zh")))
        model.add((example.eventDate, RDFS.domain, example.Event))
        model.add((example.eventDate, RDFS.range, XSD.date))
        facts.add((example.sample, RDF.type, OWL.NamedIndividual))
        facts.add((example.sample, RDF.type, example.Event))
        facts.add((example.sample, example.eventDate, Literal("2026-01-01", datatype=XSD.date, normalize=False)))
        entry = URIRef("urn:date-fixture:load-plan")
        plan.add((entry, RDF.type, PKG.LoadPlan))
        plan.add((entry, PKG.integrationMode, PKG.Materialized))
        plan.add((entry, PKG.includesABox, Literal(False)))
        for role, relative, graph in (
            (PKG.TBox, "subontologies/date.owl", model),
            (PKG.ABox, "data/date.owl", facts),
        ):
            node = URIRef("urn:date-fixture:" + str(role).split("#")[-1])
            plan.add((entry, PKG.module, node))
            plan.add((node, RDF.type, PKG.Module))
            plan.add((node, PKG.role, role))
            plan.add((node, PKG.path, Literal(relative)))
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            graph.serialize(destination=path, format="xml", encoding="utf-8")
        (source / "integration").mkdir()
        plan.serialize(destination=source / "integration/load-plan.ttl", format="turtle", encoding="utf-8")
        return source, example

    def test_build_preserves_synthetic_date_source_semantics(self):
        source, example = self.date_fixture("date-build-source")
        before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
        dest = self.work / "date-build/ontology"
        build(source, dest); build(source, dest, check=True)
        for _, _, path, graph in load(source)[2]:
            copied = dest / path.relative_to(source)
            self.assertEqual(copied.read_bytes(), before[path])
            self.assertTrue(isomorphic(graph, parse(copied)))
        self.assertIn((example.eventDate, RDFS.range, XSD.date), parse(dest / "integration/merged_ontology.owl"))
        self.assertEqual(parse(dest / "data/date.owl").value(example.sample, example.eventDate).datatype, XSD.date)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_unsupported_date_reports_failure_without_rewriting_sources(self):
        source, _ = self.date_fixture("date-rejection-source")
        before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
        output = self.work / "owl-unsupported-date"
        with self.assertRaises(ToolError):
            check_consistency(source / "subontologies/date.owl", output, facts=source / "data/date.owl")
        report = parse(output / "report.ttl")
        self.assertIsNone(report.value(RUN, OT.consistent))
        self.assertEqual(parse(output / "execution.ttl").value(RUN, OT.status), Literal("failed"))
        self.assertIn("eventDate", (output / "java-stderr.txt").read_text(encoding="utf-8"))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_no_json_outputs(self):
        self.assertFalse(list(self.work.rglob("*.json")))


if __name__ == "__main__":
    unittest.main()
