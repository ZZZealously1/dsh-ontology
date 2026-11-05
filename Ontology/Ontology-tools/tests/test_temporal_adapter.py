"""Preserve OWL annotation linkage while adapting semantic temporal values."""
import unittest

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, XSD

from ontology_tools.projection import _temporal_working_graphs
from ontology_tools.scalar import validate_temporal_literals

EX = Namespace("urn:temporal-adapter-test:")


def reified_property(value, declaration, kind=OWL.Axiom):
    graph, node = Graph(), BNode()
    for triple in ((EX.value, RDF.type, declaration), (EX.source, EX.value, value),
                   (node, RDF.type, kind), (node, OWL.annotatedSource, EX.source),
                   (node, OWL.annotatedProperty, EX.value), (node, OWL.annotatedTarget, value)):
        graph.add(triple)
    return graph, node


class TemporalAdapterTests(unittest.TestCase):
    def test_annotation_and_reified_target_retain_original_lexical_value(self):
        value = Literal("2024-03-01T08:00:00+08:00", datatype=XSD.dateTime, normalize=False)
        for kind in (OWL.Axiom, OWL.Annotation):
            with self.subTest(kind=kind):
                source, node = reified_property(value, OWL.AnnotationProperty, kind)
                validate_temporal_literals(source)
                converted, _, _, _, _ = _temporal_working_graphs(source, Graph(), Graph(), Graph())
                self.assertEqual(set(converted), set(source))
                self.assertEqual(converted.value(node, OWL.annotatedTarget), value)

    def test_reified_annotation_without_timezone_is_not_a_semantic_time(self):
        value = Literal("2024-03-01T08:00:00", datatype=XSD.dateTime, normalize=False)
        source, node = reified_property(value, OWL.AnnotationProperty)
        validate_temporal_literals(source)
        converted, _, _, _, _ = _temporal_working_graphs(source, Graph(), Graph(), Graph())
        self.assertIn((EX.source, EX.value, value), converted)
        self.assertIn((node, OWL.annotatedTarget, value), converted)

    def test_data_assertion_and_reified_target_are_converted_together(self):
        value = Literal("2024-03-01T08:00:00+08:00", datatype=XSD.dateTimeStamp, normalize=False)
        expected = Literal("2024-03-01T00:00:00Z", datatype=XSD.dateTimeStamp, normalize=False)
        source, node = reified_property(value, OWL.DatatypeProperty)
        validate_temporal_literals(source)
        converted, _, _, _, _ = _temporal_working_graphs(source, Graph(), Graph(), Graph())
        self.assertIn((EX.source, EX.value, expected), converted)
        self.assertIn((node, OWL.annotatedTarget, expected), converted)
        self.assertNotIn((EX.source, EX.value, value), converted)
        self.assertNotIn((node, OWL.annotatedTarget, value), converted)
        self.assertIn((EX.source, EX.value, value), source)


if __name__ == "__main__":
    unittest.main()
