"""Independent capability and refusal tests for the generic finite backend."""
import unittest

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_tools.backend import (
    InferenceLimitError, OT, SWRL, SWRLB, UnsupportedSemantics,
    infer, inspect_semantics,
)

EX = Namespace("urn:test:")


def graph(*triples):
    result = Graph()
    for triple in triples:
        result.add(triple)
    return result


def rule(rule_id=EX.rule, body=None, head=None):
    """Create native SWRL graphs, not an alternative execution rule format."""
    result = Graph()
    for variable in (EX.x, EX.y, EX.z, EX.value, EX.other):
        result.add((variable, RDF.type, SWRL.Variable))
    result.add((rule_id, RDF.type, SWRL.Imp))
    for side, atom_specs in ((SWRL.body, body or [(SWRL.ClassAtom, EX.A, EX.x)]),
                             (SWRL.head, head or [(SWRL.ClassAtom, EX.B, EX.x)])):
        atom_nodes = []
        for kind, predicate, *args in atom_specs:
            atom = BNode()
            result.add((atom, RDF.type, kind))
            if kind == SWRL.BuiltinAtom:
                result.add((atom, SWRL.builtin, predicate))
                arg_list = BNode()
                Collection(result, arg_list, args)
                result.add((atom, SWRL.arguments, arg_list))
            else:
                field = SWRL.classPredicate if kind == SWRL.ClassAtom else SWRL.propertyPredicate
                result.add((atom, field, predicate))
                for field, value in zip((SWRL.argument1, SWRL.argument2), args):
                    result.add((atom, field, value))
            atom_nodes.append(atom)
        root = BNode()
        Collection(result, root, atom_nodes)
        result.add((rule_id, side, root))
    return result


def comparison(operator, threshold):
    return rule(body=[
        # Put the builtin before its binder to verify conjunction semantics.
        (SWRL.BuiltinAtom, operator, EX.value, threshold),
        (SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, EX.value),
    ])


class BackendTests(unittest.TestCase):
    def test_subclass_fixed_point_and_input_not_mutated(self):
        ontology = graph((EX.A, RDFS.subClassOf, EX.B), (EX.B, RDFS.subClassOf, EX.C))
        facts = graph((EX.item, RDF.type, EX.A))
        result = infer(ontology, Graph(), facts)
        self.assertIn((EX.item, RDF.type, EX.C), result.inferred)
        self.assertIn((EX.A, RDFS.subClassOf, EX.C), result.inferred)
        self.assertEqual(len(facts), 1)
        self.assertGreaterEqual(result.iterations, 2)

    def test_property_promotion_domain_range_and_multiple_domains(self):
        ontology = graph((EX.p, RDFS.subPropertyOf, EX.q), (EX.q, RDFS.subPropertyOf, EX.r),
            (EX.r, RDFS.domain, EX.A), (EX.r, RDFS.domain, EX.B), (EX.r, RDFS.range, EX.C))
        result = infer(ontology, Graph(), graph((EX.a, EX.p, EX.b)))
        for expected in [(EX.a, EX.r, EX.b), (EX.a, RDF.type, EX.A),
                         (EX.a, RDF.type, EX.B), (EX.b, RDF.type, EX.C)]:
            self.assertIn(expected, result.inferred)

    def test_inverse_symmetric_and_transitive(self):
        ontology = graph((EX.parent, OWL.inverseOf, EX.child),
            (EX.ancestor, RDF.type, OWL.TransitiveProperty),
            (EX.neighbor, RDF.type, OWL.SymmetricProperty))
        facts = graph((EX.a, EX.parent, EX.b), (EX.c, EX.child, EX.b),
            (EX.a, EX.ancestor, EX.b), (EX.b, EX.ancestor, EX.c),
            (EX.a, EX.neighbor, EX.b))
        result = infer(ontology, Graph(), facts)
        for expected in [(EX.b, EX.child, EX.a), (EX.b, EX.parent, EX.c),
                         (EX.a, EX.ancestor, EX.c), (EX.b, EX.neighbor, EX.a)]:
            self.assertIn(expected, result.inferred)

    def test_no_datatype_literal_subject(self):
        result = infer(graph((EX.amount, RDFS.range, XSD.decimal)), Graph(),
                       graph((EX.a, EX.amount, Literal("0.10", datatype=XSD.decimal))))
        self.assertFalse(any(isinstance(s, Literal) for s, _, _ in result.closure))

    def test_object_join_and_data_property_head(self):
        rules = rule(body=[(SWRL.IndividualPropertyAtom, EX.parent, EX.x, EX.y),
                           (SWRL.ClassAtom, EX.A, EX.y)],
                     head=[(SWRL.DatavaluedPropertyAtom, EX.mark, EX.x, Literal(True))])
        facts = graph((EX.a, EX.parent, EX.b), (EX.b, RDF.type, EX.A),
                      (EX.c, EX.parent, EX.d), (EX.e, RDF.type, EX.A))
        result = infer(Graph(), rules, facts)
        self.assertIn((EX.a, EX.mark, Literal(True)), result.inferred)
        self.assertNotIn((EX.c, EX.mark, Literal(True)), result.closure)

    def test_object_head_and_recursive_rule(self):
        rules = rule(body=[(SWRL.IndividualPropertyAtom, EX.reach, EX.x, EX.y),
                           (SWRL.IndividualPropertyAtom, EX.reach, EX.y, EX.z)],
                     head=[(SWRL.IndividualPropertyAtom, EX.reach, EX.x, EX.z)])
        result = infer(Graph(), rules, graph((EX.a, EX.reach, EX.b),
            (EX.b, EX.reach, EX.c), (EX.c, EX.reach, EX.d)))
        self.assertIn((EX.a, EX.reach, EX.d), result.inferred)

    def test_all_comparison_boundaries(self):
        for operator, expected in [(SWRLB.equal, {2}), (SWRLB.notEqual, {1, 3}),
            (SWRLB.lessThan, {1}), (SWRLB.lessThanOrEqual, {1, 2}),
            (SWRLB.greaterThan, {3}), (SWRLB.greaterThanOrEqual, {2, 3})]:
            with self.subTest(operator=operator):
                facts = graph(*[(EX[f"a{n}"], EX.amount, Literal(n)) for n in (1, 2, 3)])
                result = infer(Graph(), comparison(operator, Literal(2)), facts)
                self.assertEqual(set(result.inferred.subjects(RDF.type, EX.B)),
                                 {EX[f"a{n}"] for n in expected})

    def test_decimal_precision_not_float(self):
        threshold = Literal("0.1000000000000000000000000001", datatype=XSD.decimal)
        rules = comparison(SWRLB.lessThan, threshold)
        result = infer(Graph(), rules, graph((EX.a, EX.amount,
            Literal("0.1000000000000000000000000000", datatype=XSD.decimal))))
        self.assertIn((EX.a, RDF.type, EX.B), result.inferred)

    def test_integer_decimal_value_equality(self):
        result = infer(Graph(), comparison(SWRLB.equal, Literal("2.0", datatype=XSD.decimal)),
                       graph((EX.a, EX.amount, Literal(2))))
        self.assertIn((EX.a, RDF.type, EX.B), result.inferred)

    def test_string_and_boolean_comparisons(self):
        for value, threshold, operator in [(Literal("a"), Literal("b"), SWRLB.lessThan),
            (Literal(True), Literal(True), SWRLB.equal),
            (Literal(False), Literal(True), SWRLB.notEqual)]:
            result = infer(Graph(), comparison(operator, threshold), graph((EX.a, EX.amount, value)))
            self.assertIn((EX.a, RDF.type, EX.B), result.inferred)

    def test_missing_value_is_not_negative_or_zero(self):
        result = infer(Graph(), comparison(SWRLB.lessThan, Literal(0)),
                       graph((EX.a, RDF.type, EX.A)))
        self.assertEqual(len(result.inferred), 0)
        self.assertEqual(result.iterations, 0)

    def test_float_comparison_refused_when_bound(self):
        with self.assertRaises(UnsupportedSemantics):
            infer(Graph(), comparison(SWRLB.lessThan, Literal(2)),
                  graph((EX.a, EX.amount, Literal(1.5))))

    def test_bad_constant_type_refused_without_matching_fact(self):
        for literal in [Literal(1.5), Literal("2026-10-01", datatype=XSD.date),
                        Literal("bonjour", lang="fr")]:
            self.assertTrue(inspect_semantics(Graph(), comparison(SWRLB.equal, literal)))

    def test_incompatible_comparison_types_refused(self):
        with self.assertRaises(UnsupportedSemantics):
            infer(Graph(), comparison(SWRLB.equal, Literal(2)),
                  graph((EX.a, EX.amount, Literal("2"))))

    def test_unsupported_owl_and_facts_injection_refused(self):
        for axiom in [(EX.A, OWL.equivalentClass, EX.B), (EX.a, OWL.sameAs, EX.b),
            (EX.A, OWL.disjointWith, EX.B), (EX.prop, RDF.type, OWL.FunctionalProperty),
            (EX.ontology, OWL.imports, EX.remote), (EX.restriction, RDF.type, OWL.Restriction)]:
            with self.subTest(axiom=axiom):
                with self.assertRaises(UnsupportedSemantics):
                    infer(Graph(), Graph(), graph(axiom))

    def test_unsupported_builtin_refused_even_without_match(self):
        self.assertTrue(inspect_semantics(Graph(), comparison(SWRLB.add, Literal(2))))

    def test_unbound_head_variable_refused(self):
        rules = rule(head=[(SWRL.ClassAtom, EX.B, EX.y)])
        self.assertTrue(inspect_semantics(Graph(), rules))

    def test_mixed_individual_data_variable_refused(self):
        rules = rule(body=[(SWRL.ClassAtom, EX.A, EX.x),
                           (SWRL.DatavaluedPropertyAtom, EX.amount, EX.x, EX.x)])
        self.assertTrue(inspect_semantics(Graph(), rules))

    def test_malformed_list_refused(self):
        rules = rule()
        root = next(rules.objects(EX.rule, SWRL.body))
        rules.set((root, RDF.rest, root))
        self.assertTrue(inspect_semantics(Graph(), rules))

    def test_duplicate_atom_argument_and_orphan_atom_refused(self):
        rules = rule()
        atom = next(rules.subjects(RDF.type, SWRL.ClassAtom))
        rules.add((atom, SWRL.argument1, EX.y))
        self.assertTrue(inspect_semantics(Graph(), rules))
        orphan = graph((EX.unused, RDF.type, SWRL.ClassAtom),
                       (EX.unused, SWRL.classPredicate, EX.A), (EX.unused, SWRL.argument1, EX.x))
        self.assertTrue(inspect_semantics(Graph(), orphan))

    def test_fixed_point_budget_and_no_partial_success(self):
        ontology = graph((EX.A, RDFS.subClassOf, EX.B), (EX.B, RDFS.subClassOf, EX.C))
        with self.assertRaises(InferenceLimitError):
            infer(ontology, Graph(), graph((EX.a, RDF.type, EX.A)), max_iterations=1)
        result = infer(graph((EX.A, RDFS.subClassOf, EX.B)), Graph(),
                       graph((EX.a, RDF.type, EX.A)), max_iterations=1)
        self.assertEqual(result.iterations, 1)

    def test_blank_node_swrL_and_stable_trace_across_parses(self):
        rules1, rules2 = rule(), rule()
        result1 = infer(Graph(), rules1, graph((BNode("first"), RDF.type, EX.A)))
        result2 = infer(Graph(), rules2, graph((BNode("second"), RDF.type, EX.A)))
        self.assertEqual(set(result1.inferred), set(result2.inferred))
        self.assertEqual(set(result1.trace), set(result2.trace))
        self.assertEqual(len(list(result1.inferred.subjects(RDF.type, EX.B))), 1)

    def test_blank_nodes_are_scoped_between_inputs(self):
        ontology = graph((BNode("same"), EX.tag, Literal("schema")))
        facts = graph((BNode("same"), EX.tag, Literal("fact")))
        result = infer(ontology, Graph(), facts)
        self.assertEqual(len(set(result.closure.subjects(EX.tag, None))), 2)

    def test_trace_is_grounded_in_prior_facts_or_derived_facts(self):
        ontology = graph((EX.A, RDFS.subClassOf, EX.B))
        rules = rule(body=[(SWRL.ClassAtom, EX.B, EX.x)], head=[(SWRL.ClassAtom, EX.C, EX.x)])
        result = infer(ontology, rules, graph((EX.a, RDF.type, EX.A)))
        self.assertEqual(len(set(result.trace.subjects(RDF.type, OT.Derivation))), len(result.inferred))
        for derivation in result.trace.subjects(RDF.type, OT.Derivation):
            self.assertTrue(list(result.trace.objects(derivation, OT.rule)) or
                            list(result.trace.objects(derivation, OT.axiom)))
            for statement in result.trace.objects(derivation, OT.premise):
                triple = tuple(result.trace.value(statement, p) for p in (RDF.subject, RDF.predicate, RDF.object))
                self.assertIn(triple, result.closure)

    def test_first_proof_stable_with_two_rules(self):
        rules = rule(EX.rule1) + rule(EX.rule2)
        result = infer(Graph(), rules, graph((EX.a, RDF.type, EX.A)))
        self.assertEqual(len(set(result.trace.subjects(RDF.type, OT.Derivation))), 1)
        self.assertEqual(set(result.trace.objects(None, OT.rule)), {EX.rule1})

    def test_schema_in_rule_file_used_and_business_fact_refused(self):
        rules = rule()
        rules.add((EX.B, RDFS.subClassOf, EX.C))
        result = infer(Graph(), rules, graph((EX.a, RDF.type, EX.A)))
        self.assertIn((EX.a, RDF.type, EX.C), result.inferred)
        rules.add((EX.unrelated, EX.amount, Literal(100)))
        self.assertTrue(inspect_semantics(Graph(), rules))

    def test_rules_cannot_be_smuggled_in_fact_graph(self):
        with self.assertRaises(UnsupportedSemantics):
            infer(Graph(), Graph(), rule())

    def test_disabled_rule_not_silently_executed(self):
        rules = rule()
        from rdflib import URIRef
        rules.add((EX.rule, URIRef("http://swrl.stanford.edu/ontologies/3.3/swrla.owl#isRuleEnabled"), Literal(False)))
        self.assertTrue(inspect_semantics(Graph(), rules))

    def test_bad_numeric_lexical_and_bounds_refused(self):
        for literal in [Literal("1_0", datatype=XSD.integer, normalize=False),
                        Literal("1E2", datatype=XSD.decimal, normalize=False),
                        Literal("256", datatype=XSD.unsignedByte, normalize=False)]:
            with self.subTest(literal=literal):
                self.assertTrue(inspect_semantics(graph((EX.a, EX.amount, literal)), Graph()))

    def test_object_and_literal_role_mismatch_refused(self):
        for ontology, rules, facts in [
            (graph((EX.p, RDF.type, OWL.ObjectProperty)), Graph(), graph((EX.a, EX.p, Literal("bad")))),
            (Graph(), comparison(SWRLB.lessThan, Literal(2)), graph((EX.a, EX.amount, EX.resource))),
            (graph((EX.p, RDF.type, OWL.ObjectProperty), (EX.q, RDFS.subPropertyOf, EX.p)),
             Graph(), graph((EX.a, EX.q, Literal("bad after promotion"))))]:
            with self.assertRaises(UnsupportedSemantics):
                infer(ontology, rules, facts)

    def test_rdf_rdfs_outside_profile_refused(self):
        for triple in [(EX.member, RDF.type, RDFS.ContainerMembershipProperty),
                       (EX.seq, RDF.type, RDF.Seq), (EX.seq, RDF["_1"], EX.a)]:
            self.assertTrue(inspect_semantics(graph(triple), Graph()))

    def test_inspection_diagnostics_stable_with_blank_nodes(self):
        rules1, rules2 = rule(), rule()
        for rules in (rules1, rules2):
            atom = next(rules.subjects(RDF.type, SWRL.ClassAtom))
            rules.remove((atom, SWRL.argument1, None))
        self.assertEqual(inspect_semantics(Graph(), rules1), inspect_semantics(Graph(), rules2))


if __name__ == "__main__":
    unittest.main()
