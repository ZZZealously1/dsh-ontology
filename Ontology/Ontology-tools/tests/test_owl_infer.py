"""Independent finite HermiT projection tests; no semantic test is skipped."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_tools.io import OT, ToolError, verify_manifest, write_graph
from ontology_tools.owl_dl import (DOMAIN, RUN, collect_candidates, infer_owl,
                                   check_consistency, _projection_protocol)

ROOT = Path(__file__).resolve().parents[1]
EX = Namespace("urn:test:projection:")
JAVA = os.environ.get("ONTOLOGY_DL_JAVA", "java")
PREFIX = """@prefix ex: <urn:test:projection:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:ontology a owl:Ontology .
"""


class OWLProjectionAcceptance(unittest.TestCase):
    def setUp(self):
        run_root = Path(os.environ.get("ONTOLOGY_TEST_OUTPUT", ROOT.parent.parent))
        self.temp = tempfile.TemporaryDirectory(prefix="owl-projection-test-", dir=run_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.number = 0

    def model(self, body):
        self.number += 1
        path = self.root / f"model-{self.number}.ttl"
        path.write_text(PREFIX + body, encoding="utf-8")
        return path

    def run_model(self, body, **kwargs):
        source = self.model(body)
        before = source.read_bytes()
        output = infer_owl(source, self.root / f"run-{self.number}", java=JAVA, **kwargs)
        self.assertEqual(before, source.read_bytes())
        self.assertTrue(verify_manifest(output, required=True))
        return output

    @staticmethod
    def graph(output, name):
        return Graph().parse(output / name, format="turtle")

    def assert_status(self, output, status):
        self.assertEqual(Literal(status), self.graph(output, "execution.ttl").value(RUN, OT.status))

    def test_equivalent_existential_type_and_classification(self):
        output = self.run_model("""
          ex:Store a owl:Class . ex:Service a owl:Class .
          ex:DeliveryStore a owl:Class; owl:equivalentClass [
            a owl:Class; owl:intersectionOf (ex:Store [
              a owl:Restriction; owl:onProperty ex:offers; owl:someValuesFrom ex:Service ]) ] .
          ex:Alias a owl:Class; owl:equivalentClass ex:DeliveryStore .
          ex:offers a owl:ObjectProperty .
          ex:s a owl:NamedIndividual, ex:Store; ex:offers ex:v .
          ex:v a owl:NamedIndividual, ex:Service .
        """)
        self.assert_status(output, "passed")
        self.assertIn((EX.s, RDF.type, EX.DeliveryStore), self.graph(output, "result.ttl"))
        self.assertIn((EX.s, RDF.type, EX.Alias), self.graph(output, "facts.ttl"))
        self.assertIn((EX.Alias, OWL.equivalentClass, EX.DeliveryStore), self.graph(output, "classification.ttl"))
        self.assertIn((EX.DeliveryStore, RDFS.subClassOf, EX.Store), self.graph(output, "classification.ttl"))
        self.assertNotIn((EX.s, RDF.type, EX.Store), self.graph(output, "result.ttl"))

    def test_sameas_propagates_type_object_and_data_values(self):
        output = self.run_model("""
          ex:A a owl:Class . ex:p a owl:ObjectProperty . ex:q a owl:ObjectProperty; owl:inverseOf ex:p .
          ex:score a owl:DatatypeProperty .
          ex:x a owl:NamedIndividual, ex:A; owl:sameAs ex:y; ex:p ex:z; ex:score "7"^^xsd:integer .
          ex:y a owl:NamedIndividual . ex:z a owl:NamedIndividual; owl:sameAs ex:w .
          ex:w a owl:NamedIndividual .
        """)
        facts = self.graph(output, "facts.ttl")
        for triple in ((EX.y, RDF.type, EX.A), (EX.y, EX.p, EX.w), (EX.w, EX.q, EX.y),
                       (EX.y, EX.score, Literal(7)), (EX.y, OWL.sameAs, EX.x)):
            self.assertIn(triple, facts)

    def test_data_hasvalue_is_entailed_without_explicit_assertion(self):
        output = self.run_model("""
          ex:Eligible a owl:Class; rdfs:subClassOf [
            a owl:Restriction; owl:onProperty ex:status; owl:hasValue "ready" ] .
          ex:status a owl:DatatypeProperty .
          ex:x a owl:NamedIndividual, ex:Eligible .
        """)
        facts = self.graph(output, "facts.ttl")
        self.assertIn((EX.x, EX.status, Literal("ready", datatype=XSD.string)), facts)
        self.assertNotIn((EX.x, EX.status, Literal("ready", datatype=XSD.string)), self.graph(output, "input.ttl"))

    def test_no_named_witness_or_unknown_negation(self):
        output = self.run_model("""
          ex:A a owl:Class; rdfs:subClassOf [ a owl:Restriction; owl:onProperty ex:p; owl:someValuesFrom ex:B ] .
          ex:B a owl:Class . ex:NotB a owl:Class; owl:equivalentClass [a owl:Class; owl:complementOf ex:B] .
          ex:p a owl:ObjectProperty . ex:x a owl:NamedIndividual, ex:A .
          ex:y a owl:NamedIndividual .
        """)
        facts = self.graph(output, "facts.ttl")
        self.assertEqual(set(), set(facts.triples((None, EX.p, None))))
        self.assertNotIn((EX.y, RDF.type, EX.NotB), facts)
        self.assertTrue(set(facts.subjects()).issubset({EX.x, EX.y}))

    def test_collect_candidates_excludes_all_annotation_literals(self):
        source = self.model("""
          ex:A a owl:Class; rdfs:label "LABEL-ONLY" .
          ex:p a owl:DatatypeProperty . ex:x a owl:NamedIndividual, ex:A; ex:p "business" .
          [] a owl:Axiom; owl:annotatedSource ex:x; owl:annotatedProperty ex:p;
             owl:annotatedTarget "business"; rdfs:comment "AXIOM-ONLY" .
          ex:ontology rdfs:comment "HEADER-ONLY" .
        """)
        output = collect_candidates(source, self.root / "collection", java=JAVA)
        self.assert_status(output, "passed")
        domain = self.graph(output, "candidates.ttl")
        self.assertEqual({"business"}, {str(v) for v in domain.objects(None, OT.literal)})
        self.assertEqual(set(), set(self.graph(output, "report.ttl").objects(None, OT.consistent)))
        self.assertFalse((output / "facts.ttl").exists())

    def test_fixed_domain_never_expands_from_new_semantic_inputs(self):
        source = self.model("""
          ex:A a owl:Class . ex:B a owl:Class; rdfs:subClassOf ex:A .
          ex:x a ex:B . ex:y a ex:B .
          ex:p a owl:DatatypeProperty . ex:x ex:p "existing" .
        """)
        candidate = Graph()
        candidate.add((DOMAIN, RDF.type, OT.CandidateDomain))
        candidate.add((DOMAIN, OT.individual, EX.x))
        candidate.add((DOMAIN, OT["class"], EX.A))
        candidate.add((DOMAIN, OT.dataProperty, EX.p))
        candidate.add((DOMAIN, OT.literal, Literal("other")))
        path = self.root / "scope.ttl"
        candidate.serialize(path, format="turtle")
        output = infer_owl(source, self.root / "frozen", candidates=path, java=JAVA)
        facts = self.graph(output, "facts.ttl")
        self.assertIn((EX.x, RDF.type, EX.A), facts)
        self.assertNotIn((EX.x, RDF.type, EX.B), facts)
        self.assertNotIn(EX.y, set(facts.all_nodes()))
        self.assertEqual(set(), set(facts.triples((None, EX.p, None))))

    def test_automatic_domain_can_be_frozen_without_explicit_individual_declaration(self):
        source = self.model("ex:A a owl:Class . ex:x a ex:A .")
        collected = collect_candidates(source, self.root / "collection", java=JAVA)
        output = infer_owl(source, self.root / "frozen", candidates=collected / "candidates.ttl", java=JAVA)
        self.assertIn((EX.x, RDF.type, EX.A), self.graph(output, "facts.ttl"))

    def test_candidate_entity_role_mismatch_is_rejected(self):
        source = self.model("ex:A a owl:Class . ex:x a owl:NamedIndividual, ex:A .")
        domain = self.root / "scope.ttl"
        domain.write_text("@prefix ot: <https://w3id.org/ontology-tools#> .\n"
                          "<urn:scope> a ot:CandidateDomain; ot:objectProperty <urn:test:projection:A> .", encoding="utf-8")
        with self.assertRaises(ToolError):
            infer_owl(source, self.root / "rejected", candidates=domain, java=JAVA)
        self.assert_status(self.root / "rejected", "failed")
        self.assertFalse((self.root / "rejected" / "facts.ttl").exists())

    def test_language_candidate_roundtrips_through_frozen_domain(self):
        source = self.model('ex:p a owl:DatatypeProperty . ex:x a owl:NamedIndividual; ex:p "茶饮"@zh .')
        collected = collect_candidates(source, self.root / "collection", java=JAVA)
        output = infer_owl(source, self.root / "language", candidates=collected / "candidates.ttl", java=JAVA)
        self.assertIn((EX.x, EX.p, Literal("茶饮", lang="zh")), self.graph(output, "facts.ttl"))

    def test_exported_closure_is_valid_reusable_owl_without_self_tautologies(self):
        output = self.run_model("""
          ex:A a owl:Class . ex:B a owl:Class; owl:equivalentClass ex:A .
          ex:p a owl:ObjectProperty .
          ex:x a owl:NamedIndividual, ex:A; owl:sameAs ex:y; ex:p ex:y .
          ex:y a owl:NamedIndividual .
        """)
        projected = self.graph(output, "classification.ttl") + self.graph(output, "facts.ttl")
        for subject, predicate, obj in projected:
            if predicate in {OWL.sameAs, OWL.equivalentClass, RDFS.subClassOf}:
                self.assertNotEqual(subject, obj)
        rechecked = check_consistency(output / "closure.ttl", self.root / "closure-check", java=JAVA)
        self.assert_status(rechecked, "passed")

    def test_plain_and_typed_string_candidate_union_is_one_rdf11_value(self):
        source = self.model('ex:p a owl:DatatypeProperty . ex:x a owl:NamedIndividual; ex:p "ready" .')
        domain = Graph()
        domain.add((DOMAIN, RDF.type, OT.CandidateDomain))
        domain.add((DOMAIN, OT.individual, EX.x))
        domain.add((DOMAIN, OT.dataProperty, EX.p))
        domain.add((DOMAIN, OT.literal, Literal("ready")))
        domain.add((DOMAIN, OT.literal, Literal("ready", datatype=XSD.string)))
        path = self.root / "scope.ttl"
        write_graph(domain, path)
        output = infer_owl(source, self.root / "string-union", candidates=path, java=JAVA)
        self.assertIn((EX.x, EX.p, Literal("ready", datatype=XSD.string)), self.graph(output, "facts.ttl"))
        self.assertEqual(1, len(set(self.graph(output, "candidates.ttl").objects(None, OT.literal))))

    def test_nonconformant_never_publishes_usable_projection(self):
        for body in (
            "ex:A a owl:Class; owl:disjointWith ex:B . ex:B a owl:Class . ex:x a owl:NamedIndividual, ex:A, ex:B .",
            "ex:A a owl:Class; rdfs:subClassOf owl:Nothing .",
            "ex:x a owl:NamedIndividual; owl:sameAs ex:y; owl:differentFrom ex:y . ex:y a owl:NamedIndividual .",
        ):
            with self.subTest(body=body):
                output = self.run_model(body)
                self.assert_status(output, "nonconformant")
                for name in ("facts.ttl", "classification.ttl", "result.ttl", "closure.ttl", "trace.ttl"):
                    self.assertFalse((output / name).exists())

    def test_timeout_preserves_failure_evidence_without_verdict(self):
        source = self.model("ex:A a owl:Class .")
        output = self.root / "timeout"
        with patch("ontology_tools.owl_dl.subprocess.run", side_effect=subprocess.TimeoutExpired("java", 0.1)):
            with self.assertRaisesRegex(ToolError, "timed out"):
                infer_owl(source, output, timeout=0.1)
        self.assert_status(output, "failed")
        self.assertEqual(set(), set(self.graph(output, "report.ttl").objects(None, OT.consistent)))
        self.assertFalse((output / "facts.ttl").exists())

    def test_frozen_numeric_lexical_forms_are_preserved_as_candidates(self):
        source = self.model('ex:p a owl:DatatypeProperty . ex:x a owl:NamedIndividual; ex:p "1"^^xsd:integer .')
        domain = Graph()
        domain.add((DOMAIN, RDF.type, OT.CandidateDomain))
        domain.add((DOMAIN, OT.individual, EX.x))
        domain.add((DOMAIN, OT.dataProperty, EX.p))
        for text in ("01", "1"):
            domain.add((DOMAIN, OT.literal, Literal(text, datatype=XSD.integer, normalize=False)))
        path = self.root / "scope.ttl"
        write_graph(domain, path)
        output = infer_owl(source, self.root / "lexical", candidates=path, java=JAVA)
        # parse with normalization disabled to verify the recorded lexical scope
        raw = (output / "candidates.ttl").read_text(encoding="utf-8")
        self.assertIn('"01"^^', raw)
        self.assertIn('"1"^^', raw)


class ProjectionProtocolTests(unittest.TestCase):
    @staticmethod
    def output(rows):
        b64 = lambda value: base64.b64encode(value.encode()).decode()
        payload = [key + "\t" + "\t".join(b64(v) for v in values) for key, values in rows]
        text = [
            "PROTOCOL\towl-projection-v1", "MODE\tinfer", "OWLAPI\t4.5.29",
            "AXIOMS\t3", "LOGICAL_AXIOMS\t1", "PROFILE\ttrue", "REASONER\tHermiT",
            "VERSION\t1", "CONSISTENT\ttrue", *payload,
            f"CANDIDATE_COUNT\t{sum(k.startswith('CAND_') for k, _ in rows)}",
            f"CLASSIFICATION_COUNT\t{sum(k in ('SUBCLASS', 'EQUIVALENT') for k, _ in rows)}",
            f"FACT_COUNT\t{sum(k in ('TYPE', 'SAME', 'OBJECT', 'DATA') for k, _ in rows)}",
            "PROJECTION_SHA256\t" + hashlib.sha256("".join(v + "\n" for v in payload).encode()).hexdigest(),
            "END\towl-projection-v1",
        ]
        return "\n".join(text)

    def test_complete_typed_domain_is_accepted(self):
        output = self.output([("CAND_INDIVIDUAL", [str(EX.x)]), ("CAND_CLASS", [str(EX.A)]),
                              ("TYPE", [str(EX.x), str(EX.A)])])
        _, _, _, facts = _projection_protocol(output, "infer")
        self.assertIn((EX.x, RDF.type, EX.A), facts)

    def test_truncation_count_and_duplicate_rows_are_rejected(self):
        valid = self.output([("CAND_INDIVIDUAL", [str(EX.x)])])
        for output in (valid.rsplit("\n", 1)[0], valid.replace("CANDIDATE_COUNT\t1", "CANDIDATE_COUNT\t0"),
                       valid.replace("MODE\tinfer", "MODE\tinfer\nMODE\tinfer")):
            with self.subTest(output=output), self.assertRaises(ToolError):
                _projection_protocol(output, "infer")

    def test_semantically_out_of_domain_row_is_rejected_even_with_valid_digest(self):
        output = self.output([("CAND_INDIVIDUAL", [str(EX.x)]), ("CAND_CLASS", [str(EX.A)]),
                              ("TYPE", [str(EX.y), str(EX.A)])])
        with self.assertRaisesRegex(ToolError, "outside frozen domain"):
            _projection_protocol(output, "infer")


if __name__ == "__main__":
    unittest.main()
