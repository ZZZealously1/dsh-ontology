"""Independent rule-layer cases: computed bindings, evidence and finite entities."""
import unittest

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_tools.backend import OT, SWRL, SWRLB, UnsupportedSemantics, compile_swrl_rules
from ontology_tools.calculation_rules import (CalculationBudget, CalculationExecutionError,
    apply_calculation_rules, calculation_seed, compile_calculation_rules)

EX = Namespace("urn:calculation-rule-test:")
FN = Namespace("https://w3id.org/ontology-tools/functions#")
VARS = (EX.x, EX.y, EX.v, EX.w, EX.z, EX.result)


def rule(body, head, identifier=EX.rule):
    result = Graph()
    for variable in VARS:
        result.add((variable, RDF.type, SWRL.Variable))
    result.add((identifier, RDF.type, SWRL.Imp))
    for predicate, atoms in ((SWRL.body, body), (SWRL.head, head)):
        nodes = []
        for kind, operation, *arguments in atoms:
            node = BNode()
            nodes.append(node)
            result.add((node, RDF.type, kind))
            if kind == SWRL.BuiltinAtom:
                root = BNode()
                Collection(result, root, arguments)
                result.add((node, SWRL.builtin, operation))
                result.add((node, SWRL.arguments, root))
            else:
                result.add((node, SWRL.classPredicate if kind == SWRL.ClassAtom else SWRL.propertyPredicate,
                            operation))
                for name, value in zip((SWRL.argument1, SWRL.argument2), arguments):
                    result.add((node, name, value))
        root = BNode()
        Collection(result, root, nodes)
        result.add((identifier, predicate, root))
    return result


def facts(*triples):
    result = Graph()
    for triple in triples:
        result.add(triple)
    return result


def domain(data):
    result = Graph()
    result.add((EX.domain, RDF.type, OT.CandidateDomain))
    for name, values in ((OT.individual, (EX.a, EX.b, EX.alias)),
                         (OT["class"], (EX.A, EX.B)),
                         (OT.dataProperty, (EX.p, EX.q, EX.r, EX.s)),
                         (OT.objectProperty, (EX.link,)),
                         (OT.literal, tuple(o for _, _, o in data if isinstance(o, Literal)))):
        for value in values:
            result.add((EX.domain, name, value))
    return result


def arithmetic(operation=SWRLB.add, right=Literal(2)):
    return rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                 (SWRL.BuiltinAtom, operation, EX.result, EX.v, right)],
                [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)])


class CalculationRuleTests(unittest.TestCase):
    def apply(self, rules, data, **kwargs):
        return apply_calculation_rules(rules, data, domain(data), **kwargs)

    def test_arithmetic_outputs_are_new_values(self):
        data = facts((EX.a, EX.p, Literal(8)))
        for operation, expected in ((SWRLB.add, 10), (SWRLB.subtract, 6),
                                    (SWRLB.multiply, 16), (SWRLB.divide, 4)):
            with self.subTest(operation=operation):
                result = self.apply(arithmetic(operation), data)
                output = result.inferred.value(EX.a, EX.q)
                self.assertEqual(output.toPython(), expected)
                self.assertEqual(result.generated_literals, frozenset({output}))

    def test_old_profile_does_not_accept_computations(self):
        with self.assertRaises(UnsupportedSemantics):
            compile_swrl_rules(arithmetic())

    def test_dependent_builtins_work_with_reversed_source_order(self):
        body = [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                (SWRL.BuiltinAtom, SWRLB.add, EX.w, EX.v, Literal(2)),
                (SWRL.BuiltinAtom, SWRLB.multiply, EX.result, EX.w, Literal(3))]
        head = [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)]
        data = facts((EX.a, EX.p, Literal(4)))
        left = self.apply(rule(body, head), data)
        right = self.apply(rule(list(reversed(body)), head), data)
        self.assertEqual(set(left.inferred), {(EX.a, EX.q, Literal(18))})
        self.assertTrue(isomorphic(left.computations, right.computations))
        self.assertTrue(isomorphic(left.trace, right.trace))
        self.assertNotIn(Literal(6), left.generated_literals)

    def test_bound_output_is_checked_and_not_overwritten(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.w),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.w, EX.v, Literal(2))],
                     [(SWRL.ClassAtom, EX.B, EX.x)])
        for expected, matched in ((6, True), (7, False)):
            result = self.apply(rules, facts((EX.a, EX.p, Literal(4)), (EX.a, EX.q, Literal(expected))))
            self.assertEqual((EX.a, RDF.type, EX.B) in result.inferred, matched)
            self.assertEqual(bool(result.generated_literals), False)
            self.assertIn(Literal(0), set(result.computations.objects(None, OT.position)))

    def test_constant_output_mismatch_is_not_error(self):
        rules = rule([(SWRL.ClassAtom, EX.A, EX.x),
                      (SWRL.BuiltinAtom, SWRLB.add, Literal(9), Literal(2), Literal(3))],
                     [(SWRL.ClassAtom, EX.B, EX.x)])
        result = self.apply(rules, facts((EX.a, RDF.type, EX.A)))
        self.assertFalse(result.inferred)
        self.assertIn(Literal("unmatched"), result.computations.objects(None, OT.status))

    def test_unbound_inputs_and_binding_cycles_rejected(self):
        for atoms in ([(SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.v, Literal(2))],
                      [(SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.v, Literal(2)),
                       (SWRL.BuiltinAtom, SWRLB.add, EX.v, EX.result, Literal(3))]):
            rules = rule([(SWRL.ClassAtom, EX.A, EX.x), *atoms],
                         [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)])
            with self.assertRaisesRegex(UnsupportedSemantics, "Unbound calculation"):
                compile_calculation_rules(rules)

    def test_unbound_head_and_mixed_roles_rejected(self):
        with self.assertRaisesRegex(UnsupportedSemantics, "head variables"):
            compile_calculation_rules(rule([(SWRL.ClassAtom, EX.A, EX.x)],
                [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.result)]))
        with self.assertRaisesRegex(UnsupportedSemantics, "both an individual"):
            compile_calculation_rules(rule([(SWRL.ClassAtom, EX.A, EX.x),
                (SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.x, Literal(1))],
                [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.result)]))

    def test_division_error_contains_rule_function_and_failure_evidence(self):
        for denominator in (0, 3):
            with self.assertRaises(CalculationExecutionError) as caught:
                self.apply(arithmetic(SWRLB.divide, Literal(denominator)), facts((EX.a, EX.p, Literal(1))))
            failure = caught.exception
            self.assertEqual(failure.rule, EX.rule)
            self.assertEqual(failure.predicate, SWRLB.divide)
            self.assertIn(str(EX.rule), str(failure))
            self.assertIn(Literal("failed"), failure.computations.objects(None, OT.status))
            self.assertTrue(set(failure.computations.objects(None, OT.premise)))

    def test_false_comparison_does_not_generate_candidate(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.v, Literal(2)),
                      (SWRL.BuiltinAtom, SWRLB.greaterThan, EX.result, Literal(50))],
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)])
        result = self.apply(rules, facts((EX.a, EX.p, Literal(4))))
        self.assertFalse(result.inferred)
        self.assertFalse(result.generated_literals)
        self.assertEqual(len(set(result.computations.subjects(RDF.type, OT.Computation))), 2)

    def test_numeric_value_join_and_no_duplicate_fact_spelling(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.v)],
                     [(SWRL.ClassAtom, EX.B, EX.x)])
        result = self.apply(rules, facts((EX.a, EX.p, Literal(5)),
                                       (EX.a, EX.q, Literal("5.00", datatype=XSD.decimal, normalize=False))))
        self.assertIn((EX.a, RDF.type, EX.B), result.inferred)
        result = self.apply(arithmetic(), facts((EX.a, EX.p, Literal(3)),
                          (EX.a, EX.q, Literal("5.00", datatype=XSD.decimal, normalize=False))))
        self.assertFalse(result.inferred)
        self.assertEqual(result.generated_literals, frozenset({Literal(5)}))

    def test_generated_datetime_retains_type_when_timestamp_value_already_exists(self):
        moment = Literal("2024-02-29T00:00:00Z", datatype=XSD.dateTimeStamp, normalize=False)
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.BuiltinAtom, FN.addSeconds, EX.result, EX.v, Literal(0))],
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)])
        result = self.apply(rules, facts((EX.a, EX.p, moment), (EX.a, EX.q, moment)))
        self.assertFalse(result.inferred)
        self.assertEqual(result.generated_literals, frozenset({
            Literal("2024-02-29T00:00:00Z", datatype=XSD.dateTime, normalize=False)}))

    def test_ready_guard_short_circuits_division_independent_of_source_order(self):
        body = [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                (SWRL.BuiltinAtom, SWRLB.divide, EX.result, Literal(4), EX.v),
                (SWRL.BuiltinAtom, SWRLB.greaterThan, EX.v, Literal(0))]
        head = [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)]
        data = facts((EX.a, EX.p, Literal(0)))
        left = self.apply(rule(body, head), data)
        right = self.apply(rule(list(reversed(body)), head), data)
        self.assertFalse(left.inferred)
        self.assertFalse(left.generated_literals)
        self.assertEqual(set(left.computations.objects(None, OT.function)), {SWRLB.greaterThan})
        self.assertTrue(isomorphic(left.computations, right.computations))

    def test_temporal_value_join(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.v)],
                     [(SWRL.ClassAtom, EX.B, EX.x)])
        result = self.apply(rules, facts(
            (EX.a, EX.p, Literal("2024-02-29T08:00:00+08:00", datatype=XSD.dateTime, normalize=False)),
            (EX.a, EX.q, Literal("2024-02-29T00:00:00Z", datatype=XSD.dateTime, normalize=False))))
        self.assertIn((EX.a, RDF.type, EX.B), result.inferred)

    def test_date_offset_and_difference(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.BuiltinAtom, FN.addSeconds, EX.w, EX.v, Literal(-1)),
                      (SWRL.BuiltinAtom, FN.secondsBetween, EX.result, EX.w, EX.v)],
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)])
        result = self.apply(rules, facts((EX.a, EX.p,
                           Literal("2024-03-01T00:00:00Z", datatype=XSD.dateTime, normalize=False))))
        self.assertEqual(result.inferred.value(EX.a, EX.q).toPython(), -1)
        self.assertTrue(set(result.computations.objects(None, OT.timeConvention)))

    def test_rounding_policy_and_ordered_arguments_are_evidence(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.BuiltinAtom, FN.divideRounded, EX.result, EX.v,
                       Literal(3), Literal(2), Literal("HALF_UP"))],
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)])
        result = self.apply(rules, facts((EX.a, EX.p, Literal(1))))
        self.assertEqual(str(result.inferred.value(EX.a, EX.q)), "0.33")
        self.assertEqual(set(result.computations.objects(None, OT.position)), {Literal(i) for i in (1, 2, 3, 4)})
        self.assertEqual(set(result.computations.objects(None, OT.decimalPlaces)), {Literal(2)})
        self.assertEqual({str(v) for v in result.computations.objects(None, OT.roundingMode)}, {"HALF_UP"})
        self.assertTrue(set(result.computations.objects(None, OT.functionVersion)))
        self.assertTrue(set(result.trace.objects(None, OT.computation)))

    def test_same_as_alias_connections_remain_available(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.alias, EX.v),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.v, Literal(2))],
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.alias, EX.result)])
        result = self.apply(rules, facts((EX.a, OWL.sameAs, EX.alias), (EX.a, EX.p, Literal(4))))
        self.assertIn((EX.alias, EX.q, Literal(6)), result.inferred)

    def test_same_as_expansion_consumes_budget_before_rule_matching(self):
        data = facts((EX.a, OWL.sameAs, EX.alias), (EX.alias, OWL.sameAs, EX.b),
                     (EX.a, EX.p, Literal(4)))
        budget = CalculationBudget(max_matches=2)
        with self.assertRaisesRegex(CalculationExecutionError, "sameAs expansion") as caught:
            self.apply(arithmetic(), data, budget=budget)
        self.assertEqual(budget.matches, 3)
        self.assertEqual(budget.evaluations, 0)
        self.assertFalse(budget.generated_literals)
        self.assertIsInstance(caught.exception.trace, Graph)
        self.assertIsInstance(caught.exception.computations, Graph)
        self.assertFalse(caught.exception.computations)
        self.assertNotIn(EX.rule, caught.exception.trace.objects(None, OT.rule))

    def test_frozen_entities_cannot_be_extended(self):
        rules = rule([(SWRL.ClassAtom, EX.A, EX.x)], [(SWRL.ClassAtom, EX.B, EX.unknown)])
        with self.assertRaisesRegex(CalculationExecutionError, "frozen named entity"):
            self.apply(rules, facts((EX.a, RDF.type, EX.A)))

    def test_direct_generated_recursion_rejected(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v),
                      (SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.v, Literal(1))],
                     [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.result)])
        with self.assertRaisesRegex(UnsupportedSemantics, "dependency cycle"):
            compile_calculation_rules(rules)

    def test_rule_forwarding_recursion_rejected(self):
        rules = arithmetic() + rule([(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.v)],
                  [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v)], EX.forward)
        with self.assertRaisesRegex(UnsupportedSemantics, "forward"):
            compile_calculation_rules(rules)

    def test_owl_sub_and_equivalent_property_recursion_rejected(self):
        for model in (facts((EX.q, RDFS.subPropertyOf, EX.p)),
                      facts((EX.q, OWL.equivalentProperty, EX.p)),
                      facts((EX.q, RDFS.subPropertyOf, EX.r), (EX.r, RDFS.subPropertyOf, EX.s),
                            (EX.s, RDFS.subPropertyOf, EX.p))):
            with self.assertRaisesRegex(UnsupportedSemantics, "dependency cycle"):
                compile_calculation_rules(arithmetic(), model)

    def test_non_generating_cycle_is_allowed(self):
        rules = rule([(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v)],
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.v)]) + rule(
                     [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.v)],
                     [(SWRL.DatavaluedPropertyAtom, EX.p, EX.x, EX.v)], EX.reverse)
        self.assertEqual(len(compile_calculation_rules(rules)), 2)

    def test_match_and_function_budgets_are_cumulative_across_rounds(self):
        data = facts((EX.a, EX.p, Literal(1)))
        for budget in (CalculationBudget(max_matches=1), CalculationBudget(max_evaluations=1)):
            self.apply(arithmetic(), data, budget=budget)
            with self.assertRaisesRegex(CalculationExecutionError, "budget exhausted"):
                self.apply(arithmetic(), data, budget=budget, iteration=2)

    def test_single_round_candidate_explosion_is_bounded(self):
        data = facts((EX.a, EX.p, Literal(1)), (EX.b, EX.p, Literal(2)))
        with self.assertRaisesRegex(CalculationExecutionError, "match budget"):
            self.apply(arithmetic(), data, budget=CalculationBudget(max_matches=1))
        with self.assertRaisesRegex(CalculationExecutionError, "generated literal budget"):
            self.apply(arithmetic(), data, budget=CalculationBudget(max_generated_literals=1))

    def test_invalid_budget_and_function_signature_rejected(self):
        with self.assertRaises(ValueError):
            CalculationBudget(max_evaluations=0)
        for atom in ((SWRL.BuiltinAtom, SWRLB.add, EX.result, Literal(1)),
                     (SWRL.BuiltinAtom, FN.unknown, EX.result, Literal(1), Literal(2)),
                     (SWRL.BuiltinAtom, SWRLB.add, EX.result, EX.named, Literal(1))):
            with self.assertRaises(UnsupportedSemantics):
                compile_calculation_rules(rule([(SWRL.ClassAtom, EX.A, EX.x), atom],
                    [(SWRL.DatavaluedPropertyAtom, EX.q, EX.x, EX.result)]))

    def test_seed_contains_constants_and_declarations_not_computed_values(self):
        seed, literals = calculation_seed(arithmetic())
        self.assertIn((EX.p, RDF.type, OWL.DatatypeProperty), seed)
        self.assertEqual(literals, frozenset({Literal(2)}))


if __name__ == "__main__":
    unittest.main()
