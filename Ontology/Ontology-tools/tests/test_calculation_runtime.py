"""Real-engine regressions for calculation adapters, budgets and replay."""
import unittest
from rdflib import Graph, Literal
from rdflib.namespace import RDF, OWL, SH, XSD

import test_calculation as fixtures
from ontology_tools.backend import SWRL, SWRLB
from ontology_tools.core import RUN, infer_graph, replay_run
from ontology_tools.io import OT, ToolError, parse_rdf, write_graph
from ontology_tools.projection import ProjectionSemanticError

EX, FN, rule = fixtures.EX, fixtures.FN, fixtures.rule


class CalculationRuntimeTests(unittest.TestCase):
    setUp = fixtures.CalculationAcceptanceTests.setUp
    tearDown = fixtures.CalculationAcceptanceTests.tearDown
    package_files = fixtures.CalculationAcceptanceTests.package_files
    run_inference = fixtures.CalculationAcceptanceTests.run_inference
    arithmetic_rule = fixtures.CalculationAcceptanceTests.arithmetic_rule

    def test_timezone_adapter_preserves_source_and_replays_owl_hasvalue(self):
        self.package_files('''
            :when a owl:DatatypeProperty, owl:FunctionalProperty .
            :Match a owl:Class; owl:equivalentClass [ a owl:Restriction;
                owl:onProperty :when;
                owl:hasValue "2026-10-21T00:00:00.001Z"^^xsd:dateTimeStamp ] .
        ''', ''':a :when "2026-10-21T08:00:00.001+08:00"^^xsd:dateTime,
                         "2026-10-21T00:00:00.001Z"^^xsd:dateTimeStamp .''')
        out = self.run_inference()
        self.assertIn((EX.a, RDF.type, EX.Match), parse_rdf(out / 'closure.ttl'))
        original = Literal('2026-10-21T08:00:00.001+08:00', datatype=XSD.dateTime, normalize=False)
        self.assertIn((EX.a, EX.when, original), parse_rdf(out / 'input.ttl'))
        self.assertNotIn(original, parse_rdf(out / 'prepared/facts.ttl').objects())
        self.assertIn(original, parse_rdf(out / 'temporal-normalization.ttl').objects(None, OT.originalValue))
        replayed = replay_run(out, self.root / 'replay')
        report = parse_rdf(replayed / 'replay-report.ttl')
        self.assertEqual(report.value(RUN, OT.status), Literal('passed'))
        self.assertIn(Literal('temporal-normalization.ttl'), report.objects(None, OT.path))

    def test_different_milliseconds_remain_inconsistent_after_adapter(self):
        self.package_files(':when a owl:DatatypeProperty, owl:FunctionalProperty .',
            ''':a :when "2026-10-21T08:00:00.001+08:00"^^xsd:dateTime,
                       "2026-10-21T00:00:00.002Z"^^xsd:dateTime .''')
        with self.assertRaises(ProjectionSemanticError):
            self.run_inference()
        self.assertFalse((self.root / 'run/result.ttl').exists())
        self.assertEqual(parse_rdf(self.root / 'run/execution.ttl').value(RUN, OT.semanticState), Literal('inconsistent'))

    def test_post_shapes_use_same_time_view_and_annotations_stay_original(self):
        when = Literal('2026-10-21T08:00:00+08:00', datatype=XSD.dateTime, normalize=False)
        shapes = Graph()
        for triple in ((EX.shape, RDF.type, SH.NodeShape), (EX.shape, SH.targetNode, EX.a),
                       (EX.shape, SH.property, EX.constraint), (EX.constraint, SH.path, EX.when),
                       (EX.constraint, SH.hasValue, when)):
            shapes.add(triple)
        self.package_files(':when a owl:DatatypeProperty . :notedAt a owl:AnnotationProperty .',
            ''':a :when "2026-10-21T08:00:00+08:00"^^xsd:dateTime;
                  :notedAt "2026-10-21T08:00:00.000001+08:00"^^xsd:dateTime .''', shapes=shapes)
        out = self.run_inference()
        self.assertTrue(next(parse_rdf(out / 'post-shacl-report.ttl').objects(None, SH.conforms)).toPython())
        annotation = next(parse_rdf(out / 'prepared/facts.ttl').objects(EX.a, EX.notedAt))
        self.assertEqual(str(annotation), '2026-10-21T08:00:00.000001+08:00')

    def test_lexical_post_shape_failure_is_reported_after_utc_adapter(self):
        shapes = Graph()
        for triple in ((EX.shape, RDF.type, SH.NodeShape), (EX.shape, SH.targetNode, EX.a),
                       (EX.shape, SH.property, EX.constraint), (EX.constraint, SH.path, EX.when),
                       (EX.constraint, SH.pattern, Literal(r'\+08:00$'))):
            shapes.add(triple)
        self.package_files(':when a owl:DatatypeProperty .',
            ':a :when "2026-10-21T08:00:00+08:00"^^xsd:dateTime .', shapes=shapes)
        with self.assertRaises(fixtures.ValidationError):
            self.run_inference()
        out = self.root / 'run'
        self.assertTrue(next(parse_rdf(out / 'shacl-report.ttl').objects(None, SH.conforms)).toPython())
        self.assertFalse(next(parse_rdf(out / 'post-shacl-report.ttl').objects(None, SH.conforms)).toPython())
        self.assertEqual(parse_rdf(out / 'execution.ttl').value(RUN, OT.stage), Literal('post-validation'))
        self.assertFalse((out / 'result.ttl').exists())

    def test_submillisecond_semantic_input_is_rejected_before_java(self):
        self.package_files(':when a owl:DatatypeProperty .')
        graph = Graph()
        graph.add((EX.a, EX.when, Literal('2026-10-21T00:00:00.0000001Z', datatype=XSD.dateTime, normalize=False)))
        write_graph(graph, self.package / 'inputs/facts.ttl')
        with self.assertRaises(ToolError):
            self.run_inference()
        out = self.root / 'run'
        self.assertFalse((out / 'rounds').exists())
        self.assertEqual(parse_rdf(out / 'execution.ttl').value(RUN, OT.profile), Literal(fixtures.PROFILE))

    def test_equal_decimal_candidate_does_not_erase_integer_output(self):
        self.package_files(':Source a owl:Class . :result a owl:DatatypeProperty . :other a owl:DatatypeProperty .',
                           ':a a :Source . :b :other "5.0"^^xsd:decimal .', self.arithmetic_rule())
        out = self.run_inference()
        self.assertIn((EX.a, EX.result, Literal(5)), parse_rdf(out / 'result.ttl'))
        self.assertIn(Literal(5), parse_rdf(out / 'candidates.ttl').objects(None, OT.literal))

    def test_generation_budget_failure_is_not_a_partial_success(self):
        rules = self.arithmetic_rule()
        rules += rule(EX.second,
            [(SWRL.ClassAtom, EX.Source, EX.x),
             (SWRL.BuiltinAtom, SWRLB.multiply, EX.final, Literal(2), Literal(3))],
            [(SWRL.DatavaluedPropertyAtom, EX.other, EX.x, EX.final)])
        self.package_files(':Source a owl:Class . :result a owl:DatatypeProperty . :other a owl:DatatypeProperty .',
                           ':a a :Source .', rules, maxGeneratedLiterals=1)
        with self.assertRaises(ToolError):
            self.run_inference()
        out = self.root / 'run'
        self.assertFalse((out / 'closure.ttl').exists())
        self.assertFalse((out / 'result.ttl').exists())
        execution = parse_rdf(out / 'execution.ttl')
        self.assertEqual(execution.value(RUN, OT.status), Literal('failed'))
        self.assertEqual(execution.value(RUN, OT.exitCode), Literal(2))
        self.assertEqual(execution.value(RUN, OT.maxGeneratedLiterals), Literal(1))
        self.assertTrue((out / 'computations.ttl').exists())
        self.assertTrue((out / 'budget.ttl').exists())


if __name__ == '__main__':
    unittest.main()
