"""Independent numeric expectations and fail-closed RDF formula contracts."""
from decimal import Decimal, localcontext
import json
import unittest

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import RDF, XSD

from ontology_tools.formula import (
    F, FormulaError, compile_catalog, evaluate_catalog, render_expression,
    render_formula, scientific_metadata, normalize_numeric_facts,
)

EX = Namespace("urn:formula-test:")


def number(value, datatype=XSD.decimal):
    return Literal(str(value), datatype=datatype, normalize=False)


def node(graph, expression):
    identifier = BNode()
    if isinstance(expression, str):
        graph.add((identifier, RDF.type, F.ParameterRef))
        graph.add((identifier, F.parameter, EX[expression]))
    elif isinstance(expression, tuple):
        graph.add((identifier, RDF.type, F.Operation))
        graph.add((identifier, F.operator, F[expression[0]]))
        arguments = BNode()
        Collection(graph, arguments, [node(graph, child) for child in expression[1:]])
        graph.add((identifier, F.arguments, arguments))
    else:
        graph.add((identifier, RDF.type, F.Constant))
        graph.add((identifier, F.value, number(expression)))
    return identifier


def formula(expression, *, parameters=("x", "y"), units=None, output_unit="1",
            formula_id=EX.formula, graph=None, condition=EX.condition,
            latex=r"z=x+y", output_symbol="z"):
    graph = Graph() if graph is None else graph
    units = {} if units is None else units
    graph.add((formula_id, RDF.type, F.Formula))
    for predicate, value in ((F.enabled, Literal(True)), (F.verified, Literal(True)),
        (F.outputSymbol, Literal(output_symbol)), (F.outputUnit, Literal(output_unit)),
        (F.latex, Literal(latex))):
        graph.add((formula_id, predicate, value))
    head = BNode() if parameters else RDF.nil
    Collection(graph, head, [EX[name] for name in parameters])
    graph.add((formula_id, F.parameters, head))
    for name in parameters:
        for predicate, value in ((RDF.type, F.Parameter), (F.key, Literal(name)),
            (F.symbol, Literal(r"\tau" if name == "tau" else name)),
            (F.unit, Literal(units.get(name, "1")))):
            graph.add((EX[name], predicate, value))
    graph.add((formula_id, F.expression, node(graph, expression)))
    graph.add((formula_id, F.requiredCondition, condition))
    return graph


def request(values, *, evaluation=EX.evaluation, formula_id=EX.formula,
            graph=None, context=EX.context, units=None, satisfied=True):
    graph = Graph() if graph is None else graph
    units = {} if units is None else units
    for predicate, value in ((RDF.type, F.Evaluation), (F.formula, formula_id), (F.context, context)):
        graph.add((evaluation, predicate, value))
    if satisfied:
        graph.add((evaluation, F.satisfiedCondition, EX.condition))
    for name, value in values.items():
        binding = EX[f"binding-{str(evaluation).split(':')[-1]}-{name}"]
        graph.add((evaluation, F.binding, binding))
        for predicate, item in ((RDF.type, F.Binding), (F.parameter, EX[name]),
            (F.context, context), (F.value, number(value)), (F.unit, Literal(units.get(name, "1")))):
            graph.add((binding, predicate, item))
    return graph


class FormulaTests(unittest.TestCase):
    def evaluate(self, expression, values=None, **kwargs):
        parameters = tuple((values or {}).keys())
        graph = formula(expression, parameters=parameters, **kwargs)
        catalog = compile_catalog(graph)
        self.assertEqual(catalog.issues, ())
        return evaluate_catalog(catalog, request(values or {}))

    def result(self, output, evaluation=EX.evaluation):
        self.assertEqual(output.diagnostics, [])
        return Decimal(str(output.facts.value(evaluation, F.result)))

    def error(self, output, code):
        self.assertIn(code, {item["code"] for item in output.diagnostics})
        self.assertNotIn((EX.evaluation, F.calculationStatus, F.Computed), output.facts)

    def test_addition_independent_decimal_result(self):
        self.assertEqual(self.result(self.evaluate(("Add", "x", "y"), {"x": "0.1", "y": "0.2"})), Decimal("0.3"))

    def test_subtraction(self):
        self.assertEqual(self.result(self.evaluate(("Subtract", "x", "y"), {"x": 7, "y": 12})), -5)

    def test_multiplication(self):
        self.assertEqual(self.result(self.evaluate(("Multiply", "x", "y"), {"x": "1.25", "y": 8})), 10)

    def test_division_fifty_significant_digits(self):
        self.assertEqual(self.result(self.evaluate(("Divide", "x", "y"), {"x": 1, "y": 3})), Decimal("0." + "3" * 50))

    def test_negation(self):
        self.assertEqual(self.result(self.evaluate(("Negate", "x"), {"x": "-2.75"})), Decimal("2.75"))

    def test_square_root_independent_reference(self):
        self.assertEqual(self.result(self.evaluate(("Sqrt", "x"), {"x": 2})), Decimal("1.4142135623730950488016887242096980785696718753769"))

    def test_exponential_independent_reference(self):
        self.assertEqual(self.result(self.evaluate(("Exp", "x"), {"x": 1})), Decimal("2.7182818284590452353602874713526624977572470937000"))

    def test_natural_log_independent_reference(self):
        self.assertEqual(self.result(self.evaluate(("Ln", "x"), {"x": 2})), Decimal("0.69314718055994530941723212145817656807550013436026"))

    def test_fractional_and_negative_integer_power(self):
        self.assertEqual(self.result(self.evaluate(("Pow", "x", "y"), {"x": 9, "y": "0.5"})), 3)
        self.assertEqual(self.result(self.evaluate(("Pow", "x", "y"), {"x": -2, "y": 3})), -8)
        self.assertEqual(self.result(self.evaluate(("Pow", "x", "y"), {"x": 2, "y": -3})), Decimal("0.125"))

    def test_constants_do_not_require_dummy_parameters(self):
        self.assertEqual(self.result(self.evaluate(("Add", 2, 3))), 5)

    def test_half_even_and_global_decimal_context_independence(self):
        catalog = compile_catalog(formula(("Divide", "x", "y")))
        with localcontext() as context:
            context.prec = 2
            first = evaluate_catalog(catalog, request({"x": 125, "y": 100}), precision=2)
            second = evaluate_catalog(catalog, request({"x": 135, "y": 100}), precision=2)
        self.assertEqual(self.result(first), Decimal("1.2"))
        self.assertEqual(self.result(second), Decimal("1.4"))

    def test_diffusion_length_unit_conversion_and_formula_preservation(self):
        raw = r"L=\sqrt{D\tau}"
        graph = formula(("Sqrt", ("Multiply", "D", "tau")), parameters=("D", "tau"),
            units={"D": "m^2/s", "tau": "s"}, output_unit="um", latex=raw, output_symbol="L")
        catalog = compile_catalog(graph)
        out = evaluate_catalog(catalog, request({"D": 25, "tau": "0.000001"}, units={"D": "cm^2/s", "tau": "s"}))
        self.assertEqual(self.result(out), 50)
        self.assertEqual(out.facts.value(EX.evaluation, F.resultUnit), Literal("um"))
        self.assertEqual(render_formula(catalog, EX.formula), raw)
        self.assertIn(r"\sqrt{", render_expression(catalog, EX.formula))
        self.assertIn(r"\tau", render_expression(catalog, EX.formula))
        self.assertTrue(render_expression(catalog, EX.formula).startswith("L="))

    def test_render_parenthesizes_composite_exponents_and_fraction(self):
        graph = formula(("Pow", ("Add", "x", "y"), ("Divide", "x", "y")))
        rendered = render_expression(compile_catalog(graph), EX.formula)
        self.assertEqual(rendered, r"z=\left(\left(x+y\right)\right)^{\frac{x}{y}}")

    def test_addition_converts_compatible_units_to_si(self):
        graph = formula(("Add", "x", "y"), units={"x": "m", "y": "m"}, output_unit="cm")
        out = evaluate_catalog(compile_catalog(graph), request({"x": 2, "y": 30}, units={"x": "m", "y": "cm"}))
        self.assertEqual(self.result(out), 230)

    def test_addition_different_dimensions_rejected(self):
        graph = formula(("Add", "x", "y"), units={"x": "m", "y": "s"}, output_unit="m")
        out = evaluate_catalog(compile_catalog(graph), request({"x": 2, "y": 3}, units={"x": "m", "y": "s"}))
        self.error(out, "dimension-mismatch")

    def test_dimensionless_exponential_and_logarithm_contract(self):
        for operator in ("Exp", "Ln"):
            with self.subTest(operator=operator):
                graph = formula((operator, "x"), parameters=("x",), units={"x": "m"})
                self.error(evaluate_catalog(compile_catalog(graph), request({"x": 1}, units={"x": "m"})), "dimension-mismatch")

    def test_output_dimension_contract(self):
        graph = formula(("Multiply", "x", "y"), units={"x": "m", "y": "m"}, output_unit="s")
        self.error(evaluate_catalog(compile_catalog(graph), request({"x": 1, "y": 1}, units={"x": "m", "y": "m"})), "dimension-mismatch")

    def test_pow_rational_dimension(self):
        graph = formula(("Pow", "x", "y"), units={"x": "m^2", "y": "1"}, output_unit="m")
        out = evaluate_catalog(compile_catalog(graph), request({"x": 4, "y": "0.5"}, units={"x": "m^2"}))
        self.assertEqual(self.result(out), 2)

    def test_custom_unit_requires_explicit_dimensions_and_scale(self):
        graph = formula(("Negate", "x"), parameters=("x",), units={"x": "custom-length"}, output_unit="m")
        for predicate, value in ((RDF.type, F.Unit), (F.key, Literal("custom-length")),
            (F.scale, number("0.25")), (F.dimensions, Literal("length:1"))):
            graph.add((EX.customUnit, predicate, value))
        self.assertEqual(self.result(evaluate_catalog(compile_catalog(graph), request({"x": 8}, units={"x": "custom-length"}))), -2)

    def test_unit_redefinition_is_globally_rejected(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        for predicate, value in ((RDF.type, F.Unit), (F.key, Literal("m")),
            (F.scale, number(2)), (F.dimensions, Literal("length:1"))):
            graph.add((EX.unit, predicate, value))
        with self.assertRaises(FormulaError) as caught:
            compile_catalog(graph)
        self.assertEqual(caught.exception.code, "unit-redefinition")

    def test_unknown_unit_is_never_guessed(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        self.error(evaluate_catalog(compile_catalog(graph), request({"x": 1}, units={"x": "meters-ish"})), "unknown-unit")

    def test_parameter_unit_mismatch(self):
        graph = formula(("Negate", "x"), parameters=("x",), units={"x": "m"}, output_unit="m")
        self.error(evaluate_catalog(compile_catalog(graph), request({"x": 1}, units={"x": "s"})), "unit-mismatch")

    def test_disabled_malformed_catalog_entry_does_not_block_valid_one(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        graph.add((EX.broken, RDF.type, F.Formula))
        graph.add((EX.broken, F.enabled, Literal(False)))
        catalog = compile_catalog(graph)
        self.assertEqual(catalog.issues, ())
        self.assertEqual(catalog.inactive, (str(EX.broken),))
        self.assertEqual(self.result(evaluate_catalog(catalog, request({"x": 2}))), -2)

    def test_enabled_unverified_formula_is_not_executable(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        graph.set((EX.formula, F.verified, Literal(False)))
        catalog = compile_catalog(graph)
        self.assertEqual(catalog.issues[0]["code"], "unverified-formula")
        self.error(evaluate_catalog(catalog, request({"x": 1})), "unavailable-formula")

    def test_applicability_must_be_explicit_at_compile_time(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        graph.remove((EX.formula, F.requiredCondition, None))
        self.assertEqual(compile_catalog(graph).issues[0]["code"], "missing-applicability")
        graph.add((EX.formula, F.unconditional, Literal(True)))
        self.assertEqual(compile_catalog(graph).issues, ())

    def test_missing_condition_never_produces_result(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        out = evaluate_catalog(compile_catalog(graph), request({"x": 1}, satisfied=False))
        self.error(out, "missing-condition")
        self.assertEqual(len(out.facts), 0)

    def test_missing_parameter_never_produces_partial_result(self):
        graph = formula(("Add", "x", "y"))
        self.error(evaluate_catalog(compile_catalog(graph), request({"x": 1})), "missing-input")

    def test_multivalue_binding_is_not_resolved_arbitrarily(self):
        graph = formula(("Add", "x", "y"))
        facts = request({"x": 1, "y": 2})
        facts.add((EX["binding-evaluation-x"], F.value, number(9)))
        self.error(evaluate_catalog(compile_catalog(graph), facts), "cardinality")

    def test_semantically_equal_numeric_aliases_are_unified_without_rounding(self):
        catalog = compile_catalog(formula(("Add", "x", "y")))
        facts = request({"x": "0.10", "y": 1})
        facts.add((EX["binding-evaluation-x"], F.value, number("0.1")))
        facts.add((EX["binding-evaluation-y"], F.value, number("1", XSD.integer)))
        before = set(facts)
        out = evaluate_catalog(catalog, facts)
        self.assertEqual(self.result(out), Decimal("1.1"))
        self.assertEqual(set(facts), before)
        normalized = normalize_numeric_facts(facts)
        self.assertEqual(set(normalized.objects(EX["binding-evaluation-x"], F.value)), {number("0.1")})
        self.assertEqual(set(normalized.objects(EX["binding-evaluation-y"], F.value)), {number("1.0")})
        self.assertEqual(len(out.trace[0]["bindings"][0]["source_numeric_literals"]), 2)

    def test_numeric_normalization_preserves_invalid_terms_and_conflicting_values(self):
        catalog = compile_catalog(formula(("Negate", "x"), parameters=("x",)))
        facts = request({"x": 1})
        facts.add((EX["binding-evaluation-x"], F.value, number("1.0000000000000000000000000000000000000000000000001")))
        normalized = normalize_numeric_facts(facts)
        self.assertEqual(len(set(normalized.objects(EX["binding-evaluation-x"], F.value))), 2)
        self.error(evaluate_catalog(catalog, normalized), "cardinality")
        malformed = number("1e-19")
        facts = request({"x": 1})
        facts.set((EX["binding-evaluation-x"], F.value, malformed))
        normalized = normalize_numeric_facts(facts)
        self.assertIn((EX["binding-evaluation-x"], F.value, malformed), normalized)
        self.error(evaluate_catalog(catalog, normalized), "invalid-number")

    def test_recomputation_accepts_only_equal_numeric_result_aliases(self):
        catalog = compile_catalog(formula(("Add", "x", "y")))
        facts = request({"x": "0.10", "y": "0.90"})
        facts.add((EX.evaluation, F.result, number("1")))
        facts.add((EX.evaluation, F.result, number("1.0")))
        facts.add((EX.evaluation, F.result, number("1", XSD.integer)))
        facts.add((EX.evaluation, F.resultUnit, Literal("1")))
        facts.add((EX.evaluation, F.calculationStatus, F.Computed))
        out = evaluate_catalog(catalog, facts)
        self.assertEqual(out.diagnostics, [])
        facts.add((EX.evaluation, F.result, number("2")))
        self.error(evaluate_catalog(catalog, facts), "output-conflict")

    def test_multiple_bindings_for_same_parameter_are_rejected(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        facts = request({"x": 1})
        facts.add((EX.evaluation, F.binding, EX.duplicate))
        for predicate, value in list(facts.predicate_objects(EX["binding-evaluation-x"])):
            facts.add((EX.duplicate, predicate, value))
        self.error(evaluate_catalog(compile_catalog(graph), facts), "multiple-values")

    def test_cross_context_binding_is_rejected(self):
        facts = request({"x": 1})
        facts.set((EX["binding-evaluation-x"], F.context, EX.otherContext))
        graph = formula(("Negate", "x"), parameters=("x",))
        self.error(evaluate_catalog(compile_catalog(graph), facts), "context-mismatch")

    def test_parameter_domain_checked_after_unit_conversion(self):
        graph = formula(("Negate", "x"), parameters=("x",), units={"x": "m"}, output_unit="m")
        graph.add((EX.x, F.minExclusive, number(1)))
        self.error(evaluate_catalog(compile_catalog(graph), request({"x": 50}, units={"x": "cm"})), "parameter-domain")

    def test_all_parameter_relations_boundaries_and_counterexamples(self):
        expectations = {
            "lessThanParameter": ((1, True), (2, False), (3, False)),
            "lessThanOrEqualParameter": ((1, True), (2, True), (3, False)),
            "greaterThanParameter": ((1, False), (2, False), (3, True)),
            "greaterThanOrEqualParameter": ((1, False), (2, True), (3, True)),
        }
        for relation, examples in expectations.items():
            graph = formula(("Add", "x", "y"))
            graph.add((EX.x, F[relation], EX.y))
            catalog = compile_catalog(graph)
            self.assertEqual(catalog.issues, ())
            for left, accepted in examples:
                with self.subTest(relation=relation, left=left, right=2):
                    out = evaluate_catalog(catalog, request({"x": left, "y": 2}))
                    if accepted:
                        self.assertEqual(self.result(out), left + 2)
                        self.assertTrue(out.trace[0]["parameter_relations"][0]["satisfied"])
                    else:
                        self.error(out, "parameter-domain")
                        self.assertEqual(len(out.facts), 0)
                        self.assertFalse(out.trace[0]["parameter_relations"][0]["satisfied"])

    def test_parameter_relation_compares_si_values_across_declared_and_input_units(self):
        graph = formula(("Add", "x", "y"), units={"x": "m", "y": "cm"}, output_unit="m")
        graph.add((EX.x, F.greaterThanParameter, EX.y))
        catalog = compile_catalog(graph)
        positive = evaluate_catalog(catalog, request({"x": 125, "y": 1}, units={"x": "cm", "y": "m"}))
        self.assertEqual(self.result(positive), Decimal("2.25"))
        relation = positive.trace[0]["parameter_relations"][0]
        self.assertEqual((relation["left_si"], relation["right_si"]), ("1.25", "1.0"))
        negative = evaluate_catalog(catalog, request({"x": 99, "y": 1}, units={"x": "cm", "y": "m"}))
        self.error(negative, "parameter-domain")

    def test_parameter_relation_rejects_foreign_or_incompatible_targets_at_compile_time(self):
        foreign = formula(("Add", "x", "y"))
        foreign.add((EX.x, F.lessThanParameter, EX.foreign))
        self.assertEqual(compile_catalog(foreign).issues[0]["code"], "unknown-parameter")
        incompatible = formula(("Multiply", "x", "y"), units={"x": "m", "y": "s"}, output_unit="m")
        incompatible.add((EX.x, F.lessThanOrEqualParameter, EX.y))
        self.assertEqual(compile_catalog(incompatible).issues[0]["code"], "dimension-mismatch")

    def test_internal_binding_and_operation_budget_stops_before_result(self):
        catalog = compile_catalog(formula(("Add", "x", "y")))
        facts = request({"x": 1, "y": 2})
        self.assertEqual(self.result(evaluate_catalog(catalog, facts, max_evaluations=3)), 3)
        stopped = evaluate_catalog(catalog, facts, max_evaluations=2)
        self.error(stopped, "evaluation-budget")
        self.assertEqual(len(stopped.facts), 0)

    def test_domain_errors_return_diagnostics_without_results(self):
        for expression, values, expected in (
            (("Divide", "x", "y"), {"x": 1, "y": 0}, "division-by-zero"),
            (("Sqrt", "x"), {"x": -1}, "invalid-domain"),
            (("Ln", "x"), {"x": 0}, "invalid-domain"),
            (("Ln", "x"), {"x": -1}, "invalid-domain"),
            (("Pow", "x", "y"), {"x": 0, "y": 0}, "invalid-domain"),
            (("Pow", "x", "y"), {"x": -1, "y": "0.5"}, "invalid-domain"),
        ):
            with self.subTest(expression=expression, values=values):
                out = self.evaluate(expression, values)
                self.error(out, expected)
                self.assertEqual(len(out.facts), 0)

    def test_expression_cycle_and_rdf_list_cycle_rejected(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        root = graph.value(EX.formula, F.expression)
        head = graph.value(root, F.arguments)
        graph.set((head, RDF.first, root))
        self.assertEqual(compile_catalog(graph).issues[0]["code"], "expression-cycle")
        graph.set((head, RDF.first, EX.someLeaf))
        graph.set((head, RDF.rest, head))
        self.assertEqual(compile_catalog(graph).issues[0]["code"], "list-cycle")

    def test_wrong_arity_and_unknown_operator_injection_rejected(self):
        for expression, code in ((("Add", "x"), "arity"), (("lambda:__import__('os')", "x"), "unknown-operator")):
            with self.subTest(expression=expression):
                catalog = compile_catalog(formula(expression, parameters=("x",)))
                self.assertEqual(catalog.issues[0]["code"], code)

    def test_literal_injection_nonfinite_and_subtype_violations_rejected(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        with self.assertLogs("rdflib.term", level="WARNING"):
            bad_integer = number("1e2", XSD.integer)
        for value in (Literal("__import__('os').system('echo bad')"), number("NaN", XSD.double),
                      number("INF", XSD.double), number("-1", XSD.positiveInteger), bad_integer):
            with self.subTest(value=value):
                facts = request({"x": 1})
                facts.set((EX["binding-evaluation-x"], F.value, value))
                self.error(evaluate_catalog(compile_catalog(graph), facts), "invalid-number")

    def test_numeric_resource_limits_and_invalid_budgets(self):
        graph = formula(("Exp", "x"), parameters=("x",))
        self.error(evaluate_catalog(compile_catalog(graph), request({"x": 10000})), "numeric-budget")
        facts = request({"x": 1})
        facts.set((EX["binding-evaluation-x"], F.value, number("1" + "0" * 100001)))
        self.error(evaluate_catalog(compile_catalog(graph), facts), "numeric-budget")
        for kwargs in ({"precision": True}, {"max_evaluations": 0}, {"max_numeric_digits": 10}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FormulaError):
                evaluate_catalog(compile_catalog(graph), request({"x": 1}), **kwargs)

    def test_repeated_rounds_do_not_mutate_inputs_or_add_duplicate_results(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        catalog, facts = compile_catalog(graph), request({"x": 1})
        before = set(facts)
        first = evaluate_catalog(catalog, facts)
        self.assertEqual(set(facts), before)
        self.assertEqual(len(first.facts), 3)
        facts += first.facts
        second = evaluate_catalog(catalog, facts, iteration=2)
        self.assertEqual(len(second.facts), 0)
        self.assertEqual(second.diagnostics, [])

    def test_existing_conflicting_results_cannot_be_blessed(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        facts = request({"x": 1})
        facts.add((EX.evaluation, F.result, number(999)))
        out = evaluate_catalog(compile_catalog(graph), facts)
        self.error(out, "output-conflict")
        self.assertEqual(len(out.facts), 0)

    def test_recomputed_result_accepts_semantically_equal_typed_strings(self):
        graph = formula(("Negate", "x"), parameters=("x",))
        facts = request({"x": 1})
        facts.add((EX.evaluation, F.result, number("-1.000")))
        facts.add((EX.evaluation, F.resultUnit, Literal("1", datatype=XSD.string)))
        facts.add((EX.evaluation, F.calculationStatus, F.Computed))
        out = evaluate_catalog(compile_catalog(graph), facts)
        self.assertEqual(out.diagnostics, [])
        self.assertEqual(len(out.facts), 0)

    def dependency_fixture(self, other_context=False):
        graph = formula(("Multiply", "x", 2), parameters=("x",), formula_id=EX.upstream)
        formula(("Add", "y", 1), parameters=("y",), formula_id=EX.downstream, graph=graph)
        facts = request({"x": 3}, evaluation=EX.first, formula_id=EX.upstream)
        request({}, evaluation=EX.second, formula_id=EX.downstream, graph=facts,
                context=EX.otherContext if other_context else EX.context)
        facts.add((EX.second, F.binding, EX.link))
        for predicate, value in ((RDF.type, F.Binding), (F.parameter, EX.y),
            (F.context, EX.otherContext if other_context else EX.context), (F.fromEvaluation, EX.first)):
            facts.add((EX.link, predicate, value))
        return compile_catalog(graph), facts

    def test_dependency_chain_uses_complete_same_context_upstream_result(self):
        catalog, facts = self.dependency_fixture()
        out = evaluate_catalog(catalog, facts)
        self.assertEqual(self.result(out, EX.first), 6)
        self.assertEqual(self.result(out, EX.second), 7)
        self.assertEqual(len(out.facts), 6)
        self.assertEqual(len(out.trace), 2)

    def test_dependency_context_isolation(self):
        catalog, facts = self.dependency_fixture(other_context=True)
        out = evaluate_catalog(catalog, facts)
        self.assertIn("context-mismatch", {d["code"] for d in out.diagnostics})
        self.assertIsNone(out.facts.value(EX.second, F.result))

    def test_dependency_cycles_and_ambiguous_direct_values_are_rejected(self):
        catalog, facts = self.dependency_fixture()
        binding = EX["binding-first-x"]
        facts.remove((binding, F.value, None))
        facts.remove((binding, F.unit, None))
        facts.add((binding, F.fromEvaluation, EX.second))
        out = evaluate_catalog(catalog, facts)
        self.assertEqual({d["code"] for d in out.diagnostics}, {"dependency-cycle"})
        self.assertEqual(len(out.facts), 0)
        catalog, facts = self.dependency_fixture()
        facts.add((EX.link, F.value, number(2)))
        out = evaluate_catalog(catalog, facts)
        self.assertIn("ambiguous-binding", {d["code"] for d in out.diagnostics})

    def test_missing_dependency_cannot_be_created_by_engine(self):
        catalog, facts = self.dependency_fixture()
        facts.set((EX.link, F.fromEvaluation, EX.absent))
        out = evaluate_catalog(catalog, facts)
        self.assertIn("missing-dependency", {d["code"] for d in out.diagnostics})
        self.assertIsNone(out.facts.value(EX.absent, RDF.type))

    def test_trace_serializes_actual_operations_library_and_normalization(self):
        out = self.evaluate(("Ln", ("Add", "x", "y")), {"x": 1, "y": 1})
        self.assertEqual(self.result(out), Decimal("0.69314718055994530941723212145817656807550013436026"))
        self.assertEqual([operation["operator"] for operation in out.trace[0]["operations"]], [str(F.Add), str(F.Ln)])
        self.assertEqual(out.trace[0]["operations"][0]["inputs"], ["1.0", "1.0"])
        self.assertEqual(out.trace[0]["operations"][0]["output"], "2.0")
        self.assertEqual(out.metadata["precision"], 50)
        self.assertEqual(out.metadata["implementation"], "python._pydecimal")
        self.assertEqual(len(out.metadata["implementation_sha256"]), 64)
        self.assertEqual(out.metadata["implementation_sha256"], scientific_metadata()["implementation_sha256"])
        self.assertTrue(out.trace[0]["inexact"])
        json.dumps({"trace": out.trace, "metadata": out.metadata, "diagnostics": out.diagnostics})

    def test_operation_rounding_flags_are_local_and_chain_flags_accumulate(self):
        out = self.evaluate(("Subtract", ("Divide", "x", "y"), ("Divide", "x", "y")), {"x": 1, "y": 3})
        self.assertEqual(self.result(out), 0)
        operations = out.trace[0]["operations"]
        self.assertEqual([item["inexact"] for item in operations], [True, True, False])
        self.assertTrue(out.trace[0]["inexact"])


if __name__ == "__main__":
    unittest.main()
