"""Independent integration acceptance for scalar SWRL and real OWL DL feedback.

No mocked Java backend: an unavailable HermiT runtime is a test failure.
The expected numbers, times and triples below are authored independently.
"""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import rdflib
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, SH, XSD

from ontology_tools.backend import SWRL, SWRLB
from ontology_tools.core import RUN, infer_graph, replay_run, run_cases
from ontology_tools.io import OT, ToolError, ValidationError, _PARSE_LOCK, parse_rdf, write_graph
from ontology_tools.projection import ProjectionSemanticError


EX = Namespace("urn:calculation-acceptance:")
FN = Namespace("https://w3id.org/ontology-tools/functions#")
PROFILE = "hermit-swrl-calculation-v1"
PREFIX = """@prefix : <urn:calculation-acceptance:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def graph(text=""):
    # Test source spellings are part of the datatype contract: RDFLib's default
    # conversion expands .001 to .001000 before the runtime can inspect it.
    with _PARSE_LOCK:
        previous = rdflib.NORMALIZE_LITERALS
        rdflib.NORMALIZE_LITERALS = False
        try:
            return Graph().parse(data=PREFIX + text, format="turtle")
        finally:
            rdflib.NORMALIZE_LITERALS = previous


def rule(identifier, body, head):
    result = Graph()
    for variable in (EX.x, EX.y, EX.value, EX.computed, EX.final, EX.time):
        result.add((variable, RDF.type, SWRL.Variable))
    result.add((identifier, RDF.type, SWRL.Imp))
    for side, specs in ((SWRL.body, body), (SWRL.head, head)):
        nodes = []
        for kind, predicate, *arguments in specs:
            atom = BNode()
            nodes.append(atom)
            result.add((atom, RDF.type, kind))
            if kind == SWRL.BuiltinAtom:
                result.add((atom, SWRL.builtin, predicate))
                args = BNode()
                Collection(result, args, arguments)
                result.add((atom, SWRL.arguments, args))
            else:
                result.add((atom, SWRL.classPredicate if kind == SWRL.ClassAtom
                            else SWRL.propertyPredicate, predicate))
                for field, arg in zip((SWRL.argument1, SWRL.argument2), arguments):
                    result.add((atom, field, arg))
        sequence = BNode()
        Collection(result, sequence, nodes)
        result.add((identifier, side, sequence))
    return result


class CalculationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        base = os.environ.get("ONTOLOGY_TEST_OUTPUT")
        if base:
            Path(base).mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="calculation-", dir=base)
        self.root = Path(self.temporary.name)
        self.package = self.root / "ontology"
        self.package.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def package_files(self, ontology="", facts="", rules=None, shapes=None, **options):
        write_graph(graph(ontology), self.package / "ontology.ttl")
        write_graph(graph(facts), self.package / "inputs/facts.ttl")
        (rules if rules is not None else Graph()).serialize(
            destination=str(self.package / "rules.swrl"), format="xml", encoding="utf-8")
        write_graph(shapes if shapes is not None else Graph(), self.package / "shapes.ttl")
        config = Graph()
        config.add((EX.runtime, RDF.type, OT.Runtime))
        config.add((EX.runtime, OT.profile, Literal(PROFILE)))
        for name, value in options.items():
            config.add((EX.runtime, OT[name], Literal(value)))
        write_graph(config, self.package / "runtime.ttl")

    def run_inference(self):
        return infer_graph(self.package, output=self.root / "run")

    def arithmetic_rule(self, operation=SWRLB.add, left=None, right=None):
        return rule(EX.calculate,
                    [(SWRL.ClassAtom, EX.Source, EX.x),
                     (SWRL.BuiltinAtom, operation, EX.computed,
                      Literal(2) if left is None else left,
                      Literal(3) if right is None else right)],
                    [(SWRL.DatavaluedPropertyAtom, EX.result, EX.x, EX.computed)])

    def chain_package(self):
        rules = rule(EX.add,
                     [(SWRL.ClassAtom, EX.Eligible, EX.x),
                      (SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, EX.value),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.computed, EX.value, Literal(3))],
                     [(SWRL.DatavaluedPropertyAtom, EX.subtotal, EX.x, EX.computed)])
        rules += rule(EX.multiply,
                      [(SWRL.ClassAtom, EX.Five, EX.x),
                       (SWRL.DatavaluedPropertyAtom, EX.subtotal, EX.x, EX.value),
                       (SWRL.BuiltinAtom, SWRLB.multiply, EX.final, EX.value, Literal(2))],
                      [(SWRL.DatavaluedPropertyAtom, EX.result, EX.x, EX.final)])
        self.package_files("""
            :Source a owl:Class; rdfs:subClassOf :Eligible .
            :Eligible a owl:Class .
            :Five a owl:Class; owl:equivalentClass [ a owl:Restriction;
                owl:onProperty :subtotal; owl:hasValue 5 ] .
            :Finished a owl:Class; owl:equivalentClass [ a owl:Restriction;
                owl:onProperty :result; owl:someValuesFrom [ a rdfs:Datatype;
                    owl:onDatatype xsd:integer; owl:withRestrictions ([ xsd:minExclusive 9 ]) ] ] .
            :amount a owl:DatatypeProperty . :subtotal a owl:DatatypeProperty .
            :result a owl:DatatypeProperty .
        """, ":a a :Source; :amount 2 .", rules)

    def test_real_dl_calculation_dl_calculation_fixed_point_and_candidates(self):
        self.chain_package()
        out = self.run_inference()
        closure = parse_rdf(out / "closure.ttl")
        for triple in ((EX.a, RDF.type, EX.Eligible), (EX.a, EX.subtotal, Literal(5)),
                       (EX.a, RDF.type, EX.Five), (EX.a, EX.result, Literal(10)),
                       (EX.a, RDF.type, EX.Finished)):
            self.assertIn(triple, closure)
        record = parse_rdf(out / "execution.ttl")
        self.assertEqual(record.value(RUN, OT.status), Literal("passed"))
        self.assertGreaterEqual(int(record.value(RUN, OT.iterations)), 3)
        initial = set(parse_rdf(out / "initial-candidates.ttl").objects(None, OT.literal))
        final = set(parse_rdf(out / "candidates.ttl").objects(None, OT.literal))
        self.assertNotIn(Literal(10), initial)
        self.assertIn(Literal(10), final)
        rounds = sorted(out.glob("rounds/round-*/candidates.ttl"))
        self.assertGreaterEqual(len(rounds), 3)
        self.assertNotIn(Literal(10), parse_rdf(rounds[0]).objects(None, OT.literal))
        self.assertIn(Literal(10), parse_rdf(rounds[-1]).objects(None, OT.literal))
        calculations = parse_rdf(out / "computations.ttl")
        self.assertIn(SWRLB.add, set(calculations.objects()))
        self.assertIn(SWRLB.multiply, set(calculations.objects()))

    def test_timezone_leap_day_offset_enters_dl_classification(self):
        rules = rule(EX.advance,
                     [(SWRL.DatavaluedPropertyAtom, EX.start, EX.x, EX.time),
                      (SWRL.BuiltinAtom, FN.addSeconds, EX.computed, EX.time, Literal(1))],
                     [(SWRL.DatavaluedPropertyAtom, EX.next, EX.x, EX.computed)])
        self.package_files("""
            :start a owl:DatatypeProperty . :next a owl:DatatypeProperty .
            :Scheduled a owl:Class; owl:equivalentClass [ a owl:Restriction;
                owl:onProperty :next; owl:someValuesFrom xsd:dateTime ] .
        """, ':a :start "2024-03-01T07:59:59+08:00"^^xsd:dateTimeStamp .', rules)
        out = self.run_inference()
        closure = parse_rdf(out / "closure.ttl")
        expected = Literal("2024-03-01T00:00:00Z", datatype=XSD.dateTime, normalize=False)
        self.assertTrue(any(value.eq(expected) for value in closure.objects(EX.a, EX.next)))
        self.assertIn((EX.a, RDF.type, EX.Scheduled), closure)
        self.assertTrue(any(value.eq(expected) for value in
                            parse_rdf(out / "candidates.ttl").objects(None, OT.literal)
                            if value.datatype == XSD.dateTime))

    def test_date_time_difference_and_comparison_use_actual_instant(self):
        earlier = Literal("2024-02-29T23:59:59.250Z", datatype=XSD.dateTime, normalize=False)
        later = Literal("2024-03-01T08:00:00.750+08:00", datatype=XSD.dateTime, normalize=False)
        rules = rule(EX.difference,
                     [(SWRL.ClassAtom, EX.Source, EX.x),
                      (SWRL.BuiltinAtom, SWRLB.lessThan, earlier, later),
                      (SWRL.BuiltinAtom, FN.secondsBetween, EX.computed, later, earlier)],
                     [(SWRL.DatavaluedPropertyAtom, EX.elapsed, EX.x, EX.computed)])
        self.package_files(":Source a owl:Class . :elapsed a owl:DatatypeProperty .",
                           ":a a :Source .", rules)
        out = self.run_inference()
        self.assertIn((EX.a, EX.elapsed, Literal("1.5", datatype=XSD.decimal)),
                      parse_rdf(out / "result.ttl"))

    def test_same_as_constant_join_and_generated_value_propagation(self):
        rules = rule(EX.alias,
                     [(SWRL.ClassAtom, EX.Source, EX.anchor),
                      (SWRL.DatavaluedPropertyAtom, EX.amount, EX.anchor, EX.value),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.computed, EX.value, Literal(3))],
                     [(SWRL.DatavaluedPropertyAtom, EX.result, EX.anchor, EX.computed)])
        self.package_files(":Source a owl:Class . :amount a owl:DatatypeProperty . :result a owl:DatatypeProperty .",
                           ":alias a :Source; :amount 2; owl:sameAs :anchor .", rules)
        result = parse_rdf(self.run_inference() / "result.ttl")
        self.assertIn((EX.anchor, EX.result, Literal(5)), result)
        self.assertIn((EX.alias, EX.result, Literal(5)), result)

    def test_unmatched_branch_intermediate_value_does_not_expand_candidates(self):
        rules = rule(EX.filtered,
                     [(SWRL.ClassAtom, EX.Source, EX.x),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.computed, Literal(2), Literal(3)),
                      (SWRL.BuiltinAtom, SWRLB.greaterThan, EX.computed, Literal(9))],
                     [(SWRL.DatavaluedPropertyAtom, EX.result, EX.x, EX.computed)])
        self.package_files(":Source a owl:Class . :result a owl:DatatypeProperty .",
                           ":a a :Source .", rules)
        out = self.run_inference()
        self.assertNotIn(Literal(5), parse_rdf(out / "candidates.ttl").objects(None, OT.literal))
        self.assertFalse(list(parse_rdf(out / "closure.ttl").objects(EX.a, EX.result)))

    def test_generated_negative_value_causes_real_owl_inconsistency(self):
        self.package_files("""
            :Source a owl:Class .
            :result a owl:DatatypeProperty; rdfs:range xsd:nonNegativeInteger .
        """, ":a a :Source .", self.arithmetic_rule(SWRLB.subtract))
        with self.assertRaises(ProjectionSemanticError):
            self.run_inference()
        out = self.root / "run"
        execution = parse_rdf(out / "execution.ttl")
        self.assertEqual(execution.value(RUN, OT.status), Literal("nonconformant"))
        self.assertEqual(execution.value(RUN, OT.semanticState), Literal("inconsistent"))
        self.assertEqual(execution.value(RUN, OT.exitCode), Literal(1))
        self.assertFalse((out / "result.ttl").exists())
        self.assertFalse((out / "closure.ttl").exists())
        replayed = replay_run(out, self.root / "replay-inconsistent")
        self.assertEqual(parse_rdf(replayed / "execution.ttl").value(RUN, OT.status), Literal("passed"))
        self.assertEqual(parse_rdf(replayed / "execution.ttl").value(RUN, OT.replayedStatus), Literal("nonconformant"))

    def test_unsatisfiable_named_class_is_a_distinct_semantic_outcome(self):
        self.package_files(":Impossible a owl:Class; rdfs:subClassOf owl:Nothing .")
        with self.assertRaises(ProjectionSemanticError):
            self.run_inference()
        execution = parse_rdf(self.root / "run/execution.ttl")
        self.assertEqual(execution.value(RUN, OT.semanticState), Literal("unsatisfiable"))
        self.assertEqual(execution.value(RUN, OT.consistent), Literal(True))
        self.assertIn(EX.Impossible, execution.objects(RUN, OT.unsatisfiableClass))

    def test_nonterminating_decimal_division_is_technical_failure_not_inconsistency(self):
        self.package_files(":Source a owl:Class . :result a owl:DatatypeProperty .",
                           ":a a :Source .", self.arithmetic_rule(SWRLB.divide, Literal(1), Literal(3)))
        with self.assertRaises(ToolError) as raised:
            self.run_inference()
        self.assertEqual(raised.exception.exit_code, 2)
        out = self.root / "run"
        execution = parse_rdf(out / "execution.ttl")
        self.assertEqual(execution.value(RUN, OT.status), Literal("failed"))
        self.assertEqual(execution.value(RUN, OT.stage), Literal("swrl-inference"))
        self.assertEqual(execution.value(RUN, OT.semanticState), Literal("unknown"))
        self.assertFalse((out / "result.ttl").exists())
        with self.assertRaises(ToolError):
            replay_run(out, self.root / "replay-failure")

    def test_post_shacl_is_separate_from_owl_and_calculation_failure(self):
        rules = self.arithmetic_rule()
        shapes = Graph()
        shapes.add((EX.shape, RDF.type, SH.NodeShape))
        shapes.add((EX.shape, SH.targetSubjectsOf, EX.result))
        shapes.add((EX.shape, SH.property, EX.receiptShape))
        shapes.add((EX.receiptShape, SH.path, EX.receipt))
        shapes.add((EX.receiptShape, SH.minCount, Literal(1)))
        self.package_files(":Source a owl:Class . :result a owl:DatatypeProperty . :receipt a owl:DatatypeProperty .",
                           ":a a :Source .", rules, shapes)
        with self.assertRaises(ValidationError):
            self.run_inference()
        execution = parse_rdf(self.root / "run/execution.ttl")
        self.assertEqual(execution.value(RUN, OT.exitCode), Literal(3))
        self.assertEqual(execution.value(RUN, OT.stage), Literal("post-validation"))
        self.assertFalse((self.root / "run/result.ttl").exists())

    def test_unknown_values_do_not_generate_facts_or_named_witnesses(self):
        rules = rule(EX.missing,
                     [(SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, EX.value),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.computed, EX.value, Literal(3))],
                     [(SWRL.DatavaluedPropertyAtom, EX.result, EX.x, EX.computed)])
        self.package_files("""
            :Source a owl:Class; rdfs:subClassOf [ a owl:Restriction;
                owl:onProperty :amount; owl:someValuesFrom xsd:integer ] .
            :amount a owl:DatatypeProperty . :result a owl:DatatypeProperty .
        """, ":a a :Source .", rules)
        out = self.run_inference()
        closure = parse_rdf(out / "closure.ttl")
        self.assertFalse(list(closure.objects(EX.a, EX.result)))
        self.assertFalse(list(closure.objects(EX.a, EX.amount)))

    def test_disjunction_joint_entailment_boundary_is_preserved(self):
        rules = rule(EX.left, [(SWRL.ClassAtom, EX.B, EX.x)], [(SWRL.ClassAtom, EX.D, EX.x)])
        rules += rule(EX.right, [(SWRL.ClassAtom, EX.C, EX.x)], [(SWRL.ClassAtom, EX.D, EX.x)])
        self.package_files("""
            :A a owl:Class; rdfs:subClassOf [ a owl:Class; owl:unionOf (:B :C) ] .
            :B a owl:Class . :C a owl:Class . :D a owl:Class .
        """, ":a a :A .", rules)
        out = self.run_inference()
        closure = parse_rdf(out / "closure.ttl")
        self.assertNotIn((EX.a, RDF.type, EX.D), closure)
        self.assertNotIn((EX.a, RDF.type, EX.B), closure)
        self.assertNotIn((EX.a, RDF.type, EX.C), closure)

    def test_snapshot_replay_does_not_depend_on_original_package(self):
        self.package_files(":Source a owl:Class . :result a owl:DatatypeProperty .",
                           ":a a :Source .", self.arithmetic_rule())
        out = self.run_inference()
        # Changing the original source is allowed; replay must use its own snapshot.
        (self.package / "inputs/facts.ttl").write_text("# original is no longer available\n", encoding="utf-8")
        replayed = replay_run(out, self.root / "replay")
        self.assertEqual(parse_rdf(replayed / "execution.ttl").value(RUN, OT.status), Literal("passed"))
        comparison = parse_rdf(replayed / "replay-report.ttl")
        paths = {str(value) for value in comparison.objects(None, OT.path)}
        self.assertIn("computations.ttl", paths)
        self.assertIn("initial-candidates.ttl", paths)
        self.assertTrue(any(path.startswith("rounds/") and path.endswith("candidates.ttl") for path in paths))

    def test_tampered_calculations_candidates_result_and_snapshot_are_rejected(self):
        self.package_files(":Source a owl:Class . :result a owl:DatatypeProperty .",
                           ":a a :Source .", self.arithmetic_rule())
        out = self.run_inference()
        for relative in ("computations.ttl", "initial-candidates.ttl", "candidates.ttl", "result.ttl", "runtime.sha256",
                         "snapshot/semantic-package/inputs/facts.ttl"):
            with self.subTest(file=relative):
                target = out / relative
                self.assertTrue(target.is_file())
                original = target.read_bytes()
                try:
                    target.write_bytes(original + b"\n<urn:changed> <urn:value> 999 .\n")
                    with self.assertRaises(ToolError):
                        replay_run(out, self.root / ("replay-" + relative.replace("/", "-")))
                finally:
                    target.write_bytes(original)

    def test_independent_calculation_example_golden_cases_use_real_hermit(self):
        example = Path(__file__).resolve().parents[1] / "examples/calculation"
        shutil.copytree(example, self.package, dirs_exist_ok=True)
        out = run_cases(self.package, self.root / "cases")
        self.assertEqual(parse_rdf(out / "execution.ttl").value(RUN, OT.status), Literal("passed"))


if __name__ == "__main__":
    unittest.main()
