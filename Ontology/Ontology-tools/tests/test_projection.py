"""Independent rule-layer and real-HermiT projection acceptance cases."""
import os
from pathlib import Path
import tempfile
import unittest

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SH, XSD

from ontology_tools.backend import (OT, SWRL, SWRLB, UnsupportedSemantics,
                                    apply_swrl_rules, compile_swrl_rules, swrl_seed)
from ontology_tools.io import ToolError, ValidationError, parse_rdf, write_graph
from ontology_tools.projection import (PROFILE, RUN, ProjectionSemanticError,
                                       _scope_owl_trace, infer_projection, inspect_projection, load_projection)

EX = Namespace("urn:projection-test:")
PREFIX = """@prefix : <urn:projection-test:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def graph(text=""):
    return Graph().parse(data=PREFIX + text, format="turtle")


def rule(identifier, body, head):
    result = Graph()
    for variable in (EX.x, EX.y, EX.value):
        result.add((variable, RDF.type, SWRL.Variable))
    result.add((identifier, RDF.type, SWRL.Imp))
    for side, specs in ((SWRL.body, body), (SWRL.head, head)):
        nodes = []
        for kind, predicate, *arguments in specs:
            node = BNode()
            nodes.append(node)
            result.add((node, RDF.type, kind))
            if kind == SWRL.BuiltinAtom:
                result.add((node, SWRL.builtin, predicate))
                root = BNode()
                Collection(result, root, arguments)
                result.add((node, SWRL.arguments, root))
            else:
                result.add((node, SWRL.classPredicate if kind == SWRL.ClassAtom else SWRL.propertyPredicate,
                            predicate))
                for field, argument in zip((SWRL.argument1, SWRL.argument2), arguments):
                    result.add((node, field, argument))
        root = BNode()
        Collection(result, root, nodes)
        result.add((identifier, side, root))
    return result


def candidate_domain(individuals=(), classes=(), objects=(), data=(), literals=()):
    result = Graph()
    result.add((EX.domain, RDF.type, OT.CandidateDomain))
    for predicate, values in ((OT.individual, individuals), (OT["class"], classes),
                              (OT.objectProperty, objects), (OT.dataProperty, data),
                              (OT.literal, literals)):
        for value in values:
            result.add((EX.domain, predicate, value))
    return result


class RuleLayerTests(unittest.TestCase):
    def test_rule_compiler_separate_from_complex_owl(self):
        rules = rule(EX.rule, [(SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.x)])
        self.assertEqual(len(compile_swrl_rules(rules)), 1)
        seed, literals = swrl_seed(rules)
        self.assertIn((EX.A, RDF.type, OWL.Class), seed)
        self.assertFalse(literals)

    def test_named_domain_never_binds_blank_individual(self):
        rules = rule(EX.rule, [(SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.x)])
        facts = graph(":a a :A .")
        facts.add((BNode(), RDF.type, EX.A))
        result = apply_swrl_rules(rules, facts, candidate_domain([EX.a], [EX.A, EX.B]))
        self.assertEqual(set(result.inferred), {(EX.a, RDF.type, EX.B)})

    def test_same_as_constant_and_join_match(self):
        rules = rule(EX.rule, [(SWRL.IndividualPropertyAtom, EX.p, EX.constant, EX.x),
                               (SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.constant)])
        facts = graph(":constant owl:sameAs :alias . :alias :p :b . :b owl:sameAs :c . :c a :A .")
        domain = candidate_domain([EX.constant, EX.alias, EX.b, EX.c], [EX.A, EX.B], [EX.p])
        result = apply_swrl_rules(rules, facts, domain)
        self.assertIn((EX.constant, RDF.type, EX.B), result.inferred)
        self.assertTrue(any(result.trace.triples((None, OT.rule, EX.rule))))
        self.assertFalse(any(s == o for s, _, o in result.closure.triples((None, OWL.sameAs, None))))

    def test_same_as_does_not_rename_punned_class(self):
        facts = graph(":A owl:sameAs :B . :a a :A .")
        result = apply_swrl_rules(Graph(), facts, candidate_domain([EX.a, EX.A, EX.B], [EX.A, EX.B]))
        self.assertNotIn((EX.a, RDF.type, EX.B), result.closure)

    def test_new_head_literal_must_belong_to_domain(self):
        rules = rule(EX.rule, [(SWRL.ClassAtom, EX.A, EX.x)],
                     [(SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, Literal(8))])
        with self.assertRaisesRegex(UnsupportedSemantics, "escapes"):
            apply_swrl_rules(rules, graph(":a a :A ."),
                             candidate_domain([EX.a], [EX.A], data=[EX.amount]))

    def test_unsupported_atoms_and_arithmetic_refused(self):
        rules = rule(EX.rule, [(SWRL.ClassAtom, EX.A, EX.x),
                               (SWRL.BuiltinAtom, SWRLB.add, Literal(1), Literal(2))],
                     [(SWRL.ClassAtom, EX.B, EX.x)])
        with self.assertRaises(UnsupportedSemantics):
            compile_swrl_rules(rules)
        malformed = Graph()
        malformed.add((EX.atom, RDF.type, SWRL.SameIndividualAtom))
        with self.assertRaises(UnsupportedSemantics):
            compile_swrl_rules(malformed)

    def test_six_comparison_semantics_preserved(self):
        for operation, value, expected in (
                (SWRLB.equal, 5, True), (SWRLB.notEqual, 5, False),
                (SWRLB.lessThan, 6, True), (SWRLB.lessThanOrEqual, 5, True),
                (SWRLB.greaterThan, 4, True), (SWRLB.greaterThanOrEqual, 5, True)):
            with self.subTest(operation=operation):
                rules = rule(EX.rule, [(SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, EX.value),
                                       (SWRL.BuiltinAtom, operation, EX.value, Literal(value))],
                             [(SWRL.ClassAtom, EX.B, EX.x)])
                domain = candidate_domain([EX.a], [EX.B], data=[EX.amount], literals=[Literal(5), Literal(value)])
                result = apply_swrl_rules(rules, graph(":a :amount 5 ."), domain)
                self.assertEqual((EX.a, RDF.type, EX.B) in result.inferred, expected)

    def test_each_owl_trace_round_retains_distinct_snapshot_and_conclusion_nodes(self):
        source = Graph()
        entailment = EX["entailment-node"]
        source.add((RUN, RDF.type, OT.EntailmentSnapshot))
        source.add((RUN, OT.entailment, entailment))
        source.add((RUN, OT.inputSnapshot, Literal("input.ttl")))
        source.add((entailment, RDF.subject, RUN))  # business IRI must not be renamed
        source.add((entailment, OT.derivedBy, RUN))
        first, second = _scope_owl_trace(source, 1), _scope_owl_trace(source, 2)
        combined = first + second
        self.assertEqual(len(set(combined.subjects(RDF.type, OT.EntailmentSnapshot))), 2)
        self.assertEqual(len(set(combined.objects(None, OT.entailment))), 2)
        self.assertEqual(set(combined.objects(None, RDF.subject)), {RUN})
        self.assertIn(Literal("rounds/round-0001/owl/input.ttl"), combined.objects(None, OT.inputSnapshot))


class _ProjectionFixture(unittest.TestCase):
    def setUp(self):
        base = os.environ.get("ONTOLOGY_TEST_OUTPUT")
        if base:
            Path(base).mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="projection-", dir=base)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        self.package.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def package_files(self, ontology="", facts="", rules=None, shapes=None, max_rounds=100):
        write_graph(graph(ontology), self.package / "ontology.ttl")
        write_graph(graph(facts), self.package / "inputs/facts.ttl")
        (rules if rules is not None else Graph()).serialize(
            destination=str(self.package / "rules.swrl"), format="xml", encoding="utf-8")
        write_graph(shapes if shapes is not None else Graph(), self.package / "shapes.ttl")
        config = Graph()
        config.add((EX.runtime, RDF.type, OT.Runtime))
        config.add((EX.runtime, OT.profile, Literal(PROFILE)))
        config.add((EX.runtime, OT.maxIterations, Literal(max_rounds)))
        write_graph(config, self.package / "runtime.ttl")


class ProjectionPackageTests(_ProjectionFixture):
    def test_inspection_accepts_complex_model_without_claiming_consistency(self):
        self.package_files(":A a owl:Class; owl:equivalentClass [ a owl:Restriction; owl:onProperty :p; owl:someValuesFrom :B ] . :B a owl:Class . :p a owl:ObjectProperty .")
        result = inspect_projection(self.package)
        self.assertEqual(result.value(RUN, OT.fullOWLConsistency), Literal("not_run"))

    def test_dynamic_schema_refused_but_named_identity_accepted(self):
        self.package_files(":A a owl:Class .", ":a owl:sameAs :b; owl:differentFrom :c .")
        load_projection(self.package)
        write_graph(graph(":A rdfs:subClassOf :B ."), self.package / "inputs/facts.ttl")
        with self.assertRaisesRegex(ToolError, "TBox"):
            load_projection(self.package)

    def test_local_imports_resolve_and_unmapped_imports_refused(self):
        self.package_files(":root a owl:Ontology; owl:imports :imported .")
        write_graph(graph(":imported a owl:Ontology . :A a owl:Class ."), self.package / "modules/shared.ttl")
        with self.assertRaisesRegex(ToolError, "Unmapped"):
            load_projection(self.package)
        mapping = Graph()
        mapping.add((EX.mapping, RDF.type, OT.ImportMapping))
        mapping.add((EX.mapping, OT.ontologyIRI, EX.imported))
        mapping.add((EX.mapping, OT.path, Literal("modules/shared.ttl")))
        write_graph(mapping, self.package / "imports-map.ttl")
        loaded = load_projection(self.package)
        self.assertIn((EX.A, RDF.type, OWL.Class), loaded[2])
        self.assertFalse(any(loaded[2].triples((None, OWL.imports, None))))

    def test_relative_iri_original_document_base_is_retained(self):
        self.package_files()
        (self.package / "ontology.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> . <#A> a owl:Class .", encoding="utf-8")
        loaded = load_projection(self.package)
        self.assertIn((__import__("rdflib").URIRef((self.package / "ontology.ttl").as_uri() + "#A"),
                       RDF.type, OWL.Class), loaded[2])


class ProjectionHermiTTests(_ProjectionFixture):
    """These tests require real Java/HermiT; unavailable tools fail, never skip."""
    def run_projection(self):
        return infer_projection(self.package, output=self.root / "run")

    def test_dl_rule_dl_chain_reaches_multiple_round_fixed_point(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.DeliveryStore, EX.x),
                             (SWRL.ClassAtom, EX.Route, EX.y)],
                     [(SWRL.IndividualPropertyAtom, EX.eligible, EX.x, EX.y)])
        rules += rule(EX.r2, [(SWRL.ClassAtom, EX.RoutedStore, EX.x)],
                      [(SWRL.ClassAtom, EX.ReadyStore, EX.x)])
        self.package_files("""
            :Store a owl:Class . :Delivery a owl:Class . :Route a owl:Class .
            :offers a owl:ObjectProperty . :eligible a owl:ObjectProperty .
            :DeliveryStore a owl:Class; owl:equivalentClass [
                a owl:Class; owl:intersectionOf (:Store
                    [ a owl:Restriction; owl:onProperty :offers; owl:someValuesFrom :Delivery ]) ] .
            :RoutedStore a owl:Class; owl:equivalentClass [
                a owl:Class; owl:intersectionOf (:Store
                    [ a owl:Restriction; owl:onProperty :eligible; owl:someValuesFrom :Route ]) ] .
            :ReadyStore a owl:Class .
        """, ":a a :Store; :offers :service . :service a :Delivery . :route a :Route .", rules)
        out = self.run_projection()
        closure = parse_rdf(out / "closure.ttl")
        for cls in (EX.DeliveryStore, EX.RoutedStore, EX.ReadyStore):
            self.assertIn((EX.a, RDF.type, cls), closure)
        record = parse_rdf(out / "execution.ttl")
        self.assertGreaterEqual(int(record.value(RUN, OT.iterations)), 3)
        self.assertTrue((out / "snapshot/semantic-package/manifest.sha256").is_file())

    def test_has_value_literal_can_trigger_rule(self):
        rules = rule(EX.r1, [(SWRL.DatavaluedPropertyAtom, EX.code, EX.x, Literal("ready", datatype=XSD.string))],
                     [(SWRL.ClassAtom, EX.Ready, EX.x)])
        self.package_files("""
            :A a owl:Class; rdfs:subClassOf [
                a owl:Restriction; owl:onProperty :code; owl:hasValue "ready"^^xsd:string ] .
            :Ready a owl:Class . :code a owl:DatatypeProperty .
        """, ":a a :A .", rules)
        out = self.run_projection()
        self.assertIn((EX.a, RDF.type, EX.Ready), parse_rdf(out / "result.ttl"))

    def test_anonymous_existential_does_not_create_named_witness(self):
        self.package_files("""
            :A a owl:Class; rdfs:subClassOf [
                a owl:Restriction; owl:onProperty :p; owl:someValuesFrom :B ] .
            :B a owl:Class . :p a owl:ObjectProperty .
        """, ":a a :A . :b a owl:NamedIndividual .")
        out = self.run_projection()
        self.assertNotIn((EX.a, EX.p, EX.b), parse_rdf(out / "closure.ttl"))
        self.assertFalse(any(isinstance(s, BNode) for s in parse_rdf(out / "result.ttl").subjects()))

    def test_disjunction_is_an_explicit_joint_reasoning_limit(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.B, EX.x)], [(SWRL.ClassAtom, EX.D, EX.x)])
        rules += rule(EX.r2, [(SWRL.ClassAtom, EX.C, EX.x)], [(SWRL.ClassAtom, EX.D, EX.x)])
        self.package_files("""
            :A a owl:Class; rdfs:subClassOf [ a owl:Class; owl:unionOf (:B :C) ] .
            :B a owl:Class . :C a owl:Class . :D a owl:Class .
        """, ":a a :A .", rules)
        out = self.run_projection()
        closure = parse_rdf(out / "closure.ttl")
        self.assertNotIn((EX.a, RDF.type, EX.D), closure)
        self.assertIn("not complete", (out / "report.md").read_text(encoding="utf-8"))

    def test_rule_contradiction_stops_without_accepted_final_graph(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.x)])
        self.package_files(":A a owl:Class; owl:disjointWith :B . :B a owl:Class .", ":a a :A .", rules)
        with self.assertRaises(ProjectionSemanticError):
            self.run_projection()
        out = self.root / "run"
        self.assertFalse((out / "result.ttl").exists())
        self.assertFalse((out / "closure.ttl").exists())
        self.assertEqual(parse_rdf(out / "execution.ttl").value(RUN, OT.semanticState), Literal("inconsistent"))

    def test_unsatisfiable_class_separate_from_global_inconsistency(self):
        self.package_files(":A a owl:Class; rdfs:subClassOf owl:Nothing .")
        with self.assertRaises(ProjectionSemanticError):
            self.run_projection()
        report = parse_rdf(self.root / "run/execution.ttl")
        self.assertEqual(report.value(RUN, OT.semanticState), Literal("unsatisfiable"))

    def test_same_as_and_different_from_conflict(self):
        self.package_files("", ":a owl:sameAs :b; owl:differentFrom :b .")
        with self.assertRaises(ProjectionSemanticError):
            self.run_projection()

    def test_same_as_rule_constant_head_is_visible_under_all_aliases(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.A, EX.constant)],
                     [(SWRL.ClassAtom, EX.Ready, EX.constant)])
        self.package_files(":A a owl:Class . :Ready a owl:Class .",
                           ":alias a :A; owl:sameAs :constant .", rules)
        out = self.run_projection()
        result = parse_rdf(out / "result.ttl")
        self.assertIn((EX.constant, RDF.type, EX.Ready), result)
        self.assertIn((EX.alias, RDF.type, EX.Ready), result)

    def test_shacl_rejection_has_independent_exit_code(self):
        shapes = Graph()
        shapes.add((EX.shape, RDF.type, SH.NodeShape))
        shapes.add((EX.shape, SH.targetNode, EX.a))
        shapes.add((EX.shape, SH["class"], EX.A))
        self.package_files(":A a owl:Class .", shapes=shapes)
        with self.assertRaises(ValidationError):
            self.run_projection()
        record = parse_rdf(self.root / "run/execution.ttl")
        self.assertEqual(record.value(RUN, OT.exitCode), Literal(3))
        self.assertEqual(record.value(RUN, OT.stage), Literal("pre-validation"))

    def test_post_shacl_rejection_publishes_no_accepted_final_graph(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.x)])
        shapes = Graph()
        shapes.add((EX.shape, RDF.type, SH.NodeShape))
        shapes.add((EX.shape, SH.targetClass, EX.B))
        shapes.add((EX.shape, SH.property, EX.propertyShape))
        shapes.add((EX.propertyShape, SH.path, EX.key))
        shapes.add((EX.propertyShape, SH.minCount, Literal(1)))
        self.package_files(":A a owl:Class . :B a owl:Class . :key a owl:DatatypeProperty .",
                           ":a a :A .", rules, shapes)
        with self.assertRaises(ValidationError):
            self.run_projection()
        record = parse_rdf(self.root / "run/execution.ttl")
        self.assertEqual(record.value(RUN, OT.stage), Literal("post-validation"))
        self.assertFalse((self.root / "run/closure.ttl").exists())
        self.assertFalse((self.root / "run/result.ttl").exists())

    def test_rule_head_literal_constant_is_frozen_before_execution(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.A, EX.x)],
                     [(SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, Literal(8))])
        self.package_files(":A a owl:Class . :amount a owl:DatatypeProperty .", ":a a :A .", rules)
        out = self.run_projection()
        candidates = parse_rdf(out / "candidates.ttl")
        self.assertIn(Literal(8), candidates.objects(None, OT.literal))
        self.assertIn((EX.a, EX.amount, Literal(8)), parse_rdf(out / "result.ttl"))

    def test_plain_string_rule_body_and_head_have_one_rdf11_value(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.A, EX.x)],
                     [(SWRL.DatavaluedPropertyAtom, EX.code, EX.x, Literal("ready"))])
        rules += rule(EX.r2, [(SWRL.DatavaluedPropertyAtom, EX.code, EX.x,
                              Literal("ready", datatype=XSD.string))],
                      [(SWRL.ClassAtom, EX.B, EX.x)])
        self.package_files(":A a owl:Class . :B a owl:Class . :code a owl:DatatypeProperty .",
                           ":a a :A .", rules)
        out = self.run_projection()
        result = parse_rdf(out / "result.ttl")
        self.assertIn((EX.a, RDF.type, EX.B), result)
        self.assertEqual(set(result.objects(EX.a, EX.code)), {Literal("ready", datatype=XSD.string)})
        self.assertLessEqual(int(parse_rdf(out / "execution.ttl").value(RUN, OT.iterations)), 3)

    def test_explicitly_mapped_modules_are_loaded_by_real_reasoner(self):
        self.package_files(":root a owl:Ontology; owl:imports :imported .", ":a a :A .")
        write_graph(graph(":imported a owl:Ontology . :A a owl:Class; rdfs:subClassOf :B . :B a owl:Class ."),
                    self.package / "modules/shared.ttl")
        mapping = Graph()
        mapping.add((EX.mapping, RDF.type, OT.ImportMapping))
        mapping.add((EX.mapping, OT.ontologyIRI, EX.imported))
        mapping.add((EX.mapping, OT.path, Literal("modules/shared.ttl")))
        write_graph(mapping, self.package / "imports-map.ttl")
        out = self.run_projection()
        self.assertIn((EX.a, RDF.type, EX.B), parse_rdf(out / "result.ttl"))

    def test_iteration_exhaustion_is_technical_not_semantic_failure(self):
        rules = rule(EX.r1, [(SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.x)])
        self.package_files(":A a owl:Class . :B a owl:Class .", ":a a :A .", rules, max_rounds=1)
        with self.assertRaisesRegex(ToolError, "fixed point"):
            self.run_projection()
        record = parse_rdf(self.root / "run/execution.ttl")
        self.assertEqual(record.value(RUN, OT.exitCode), Literal(2))
        self.assertEqual(record.value(RUN, OT.semanticState), Literal("unknown"))
        self.assertIsNone(record.value(RUN, OT.consistent))
        self.assertFalse((self.root / "run/result.ttl").exists())


if __name__ == "__main__":
    unittest.main()
