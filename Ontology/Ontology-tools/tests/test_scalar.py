"""Independent expected values for deterministic arithmetic and instant helpers."""
from decimal import getcontext, localcontext
import unittest
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_tools.scalar import (
    OTFN, REGISTRY, SWRLB, ScalarError, canonical_temporal_literal, compare, evaluate, get_spec,
    same_value, validate_temporal_literals,
)

EX = Namespace("urn:scalar-test:")


def integer(value, datatype=XSD.integer):
    return Literal(str(value), datatype=datatype, normalize=False)


def decimal(value):
    return Literal(str(value), datatype=XSD.decimal, normalize=False)


def instant(value, datatype=XSD.dateTime):
    return Literal(value, datatype=datatype, normalize=False)


class ScalarTests(unittest.TestCase):
    def error(self, code, fn, *args, **kwargs):
        with self.assertRaises(ScalarError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_registry_contract_and_immutability(self):
        self.assertEqual(len(REGISTRY), 13)
        add = get_spec(SWRLB.add)
        self.assertEqual((add.arity, add.input_positions, add.output_position), (3, (1, 2), 0))
        self.assertEqual(add.version, "1")
        self.assertFalse(add.is_comparison)
        self.assertTrue(get_spec(SWRLB.equal).is_comparison)
        self.assertEqual(get_spec(OTFN.divideRounded).input_positions, (1, 2, 3, 4))
        with self.assertRaises(TypeError):
            REGISTRY[EX.unknown] = add

    def test_unknown_functions_arity_and_non_literals_fail(self):
        self.error("unknown-function", evaluate, EX.unknown, ())
        self.error("unknown-comparison", compare, SWRLB.add, integer(1), integer(2))
        self.error("arity", evaluate, SWRLB.add, (integer(1),))
        self.error("invalid-argument", evaluate, SWRLB.add, (EX.value, integer(2)))
        self.error("invalid-budget", evaluate, SWRLB.add, (integer(1), integer(2)), max_numeric_digits=True)

    def test_integer_arithmetic_and_derived_datatype_output(self):
        for operation, expected in ((SWRLB.add, "5"), (SWRLB.subtract, "9"), (SWRLB.multiply, "-14")):
            with self.subTest(operation=operation):
                result = evaluate(operation, (integer(7, XSD.short), integer(-2, XSD.byte)))
                self.assertEqual((str(result), result.datatype), (expected, XSD.integer))

    def test_decimal_mixed_type_and_canonical_negative_zero(self):
        self.assertEqual(evaluate(SWRLB.add, (integer(2), decimal("0.50"))), decimal("2.5"))
        self.assertEqual(evaluate(SWRLB.multiply, (decimal("-0.00"), integer(9))), decimal("0.0"))
        self.assertEqual(evaluate(SWRLB.subtract, (decimal(".50"), decimal("+2."))), decimal("-1.5"))

    def test_decimal_context_does_not_change_results(self):
        before = getcontext().prec
        with localcontext() as context:
            context.prec = 2
            for signal in context.traps:
                context.traps[signal] = False
            actual = evaluate(SWRLB.multiply, (decimal("12345678901234567890.123"), decimal("0.001")))
            self.assertEqual(actual, decimal("12345678901234567.890123"))
            self.assertEqual(evaluate(SWRLB.add, (decimal("9999999999999999999999999999.9"), decimal("0.1"))),
                             decimal("10000000000000000000000000000.0"))
        self.assertEqual(getcontext().prec, before)

    def test_exact_division_outputs_decimal(self):
        for left, right, expected in ((1, 8, "0.125"), (10, -4, "-2.5"), (0, 7, "0.0"), (6, 3, "2.0")):
            with self.subTest(left=left, right=right):
                self.assertEqual(evaluate(SWRLB.divide, (integer(left), integer(right))), decimal(expected))

    def test_nonterminating_and_zero_division_are_errors(self):
        self.error("non-terminating-decimal", evaluate, SWRLB.divide, (integer(1), integer(3)))
        self.error("division-by-zero", evaluate, SWRLB.divide, (decimal("1.0"), decimal("-0.0")))

    def test_rounded_division_all_modes_and_negative_ties(self):
        for mode, positive, negative in (
            ("HALF_EVEN", "1.2", "-1.2"), ("HALF_UP", "1.3", "-1.3"),
            ("DOWN", "1.2", "-1.2"), ("FLOOR", "1.2", "-1.3"), ("CEILING", "1.3", "-1.2"),
        ):
            for sign, expected in ((1, positive), (-1, negative)):
                with self.subTest(mode=mode, sign=sign):
                    self.assertEqual(evaluate(OTFN.divideRounded,
                        (integer(sign * 5), integer(4), integer(1), Literal(mode))), decimal(expected))
        self.assertEqual(evaluate(OTFN.divideRounded,
            (integer(27), integer(20), integer(1), Literal("HALF_EVEN"))), decimal("1.4"))
        self.assertEqual(evaluate(OTFN.divideRounded,
            (integer(1), integer(3), integer(3), Literal("HALF_UP"))), decimal("0.333"))

    def test_rounded_scale_zero_and_exact_values(self):
        for mode in ("HALF_EVEN", "HALF_UP", "DOWN", "FLOOR", "CEILING"):
            self.assertEqual(evaluate(OTFN.divideRounded,
                (integer(-4), integer(2), integer(0), Literal(mode))), decimal("-2.0"))
        self.assertEqual(evaluate(OTFN.divideRounded,
            (integer(1), integer(10), integer(0), Literal("DOWN"))), decimal("0.0"))

    def test_rounding_policy_must_be_explicit_and_valid(self):
        self.error("invalid-scale", evaluate, OTFN.divideRounded,
                   (integer(1), integer(3), integer(-1), Literal("HALF_UP")))
        self.error("invalid-scale", evaluate, OTFN.divideRounded,
                   (integer(1), integer(3), decimal("2"), Literal("HALF_UP")))
        self.error("invalid-rounding", evaluate, OTFN.divideRounded,
                   (integer(1), integer(3), integer(2), Literal("half_up")))
        self.error("division-by-zero", evaluate, OTFN.divideRounded,
                   (integer(1), integer(0), integer(2), Literal("HALF_UP")))

    def test_invalid_numeric_lexical_forms(self):
        for value in ("1e2", "NaN", "INF", "1 2", "", "++1", ".", "\u00a01"):
            with self.subTest(value=value):
                self.error("invalid-number", evaluate, SWRLB.add, (decimal(value), integer(1)))
        self.error("invalid-number", evaluate, SWRLB.add, (integer("1.0"), integer(1)))

    def test_derived_integer_ranges(self):
        for datatype, bad in ((XSD.byte, 128), (XSD.byte, -129), (XSD.unsignedByte, 256),
                              (XSD.unsignedInt, -1), (XSD.positiveInteger, 0),
                              (XSD.nonPositiveInteger, 1), (XSD.negativeInteger, 0),
                              (XSD.long, 2**63), (XSD.unsignedLong, 2**64)):
            with self.subTest(datatype=datatype, value=bad):
                self.error("integer-range", evaluate, SWRLB.add, (integer(bad, datatype), integer(0)))
        self.assertEqual(evaluate(SWRLB.add, (integer(255, XSD.unsignedByte), integer(0))), integer(255))

    def test_no_float_or_string_to_number_coercion(self):
        for item in (Literal(0.5), Literal("3"), Literal("NaN", datatype=XSD.double, normalize=False), Literal("2", lang="en")):
            self.error("unsupported-datatype", evaluate, SWRLB.add, (item, integer(1)))

    def test_numeric_input_output_and_scale_budgets(self):
        self.error("numeric-budget", evaluate, SWRLB.add, (integer(1000), integer(0)), max_numeric_digits=3)
        self.error("numeric-budget", evaluate, SWRLB.add, (integer(999), integer(1)), max_numeric_digits=3)
        self.error("numeric-budget", evaluate, SWRLB.divide, (integer(1), integer(8)), max_numeric_digits=3)
        self.error("numeric-budget", evaluate, OTFN.divideRounded,
                   (integer(1), integer(3), integer(6), Literal("HALF_UP")), max_numeric_digits=5)
        self.error("numeric-budget", evaluate, SWRLB.multiply, (decimal("0.01"), decimal("0.01")), max_numeric_digits=4)

    def test_oversized_coefficient_is_rejected_before_integer_construction(self):
        with patch("ontology_tools.scalar._digit_int", side_effect=AssertionError("unbounded conversion")):
            self.error("numeric-budget", evaluate, SWRLB.add,
                       (integer("9999"), integer(0)), max_numeric_digits=3)
            self.error("numeric-budget", evaluate, SWRLB.add,
                       (decimal("0.0001"), integer(0)), max_numeric_digits=3)
        self.error("numeric-budget", evaluate, OTFN.divideRounded,
                   (integer(1), integer(3), integer("9" * 100), Literal("HALF_UP")))

    def test_canonical_integral_decimal_budget_is_stable(self):
        result = evaluate(SWRLB.divide, (integer(999), integer(1)), max_numeric_digits=3)
        self.assertEqual(result, decimal("999.0"))
        self.assertEqual(evaluate(SWRLB.add, (result, integer(0)), max_numeric_digits=3), result)
        self.assertEqual(evaluate(SWRLB.add, (decimal("0.000"), integer(0)), max_numeric_digits=1), decimal("0.0"))

    def test_long_values_do_not_depend_on_python_int_string_limit(self):
        # Larger than Python 3.11's usual 4,300 digit conversion limit.
        value = integer("7" * 4400)
        result = evaluate(SWRLB.add, (value, integer(0)), max_numeric_digits=4500)
        self.assertEqual(str(result), "7" * 4400)

    def test_comparisons_numeric_string_boolean_and_filter_false(self):
        self.assertTrue(compare(SWRLB.equal, integer(2), decimal("2.00")))
        self.assertFalse(evaluate(SWRLB.lessThan, (integer(2), integer(1))))
        self.assertTrue(compare(SWRLB.notEqual, integer(2), integer(1)))
        self.assertTrue(compare(SWRLB.lessThanOrEqual, decimal("1.0"), integer(1)))
        self.assertTrue(compare(SWRLB.greaterThan, Literal("b"), Literal("a", datatype=XSD.string)))
        self.assertTrue(compare(SWRLB.greaterThanOrEqual, integer(1), decimal("1.0")))
        self.assertTrue(compare(SWRLB.equal, Literal("1", datatype=XSD.boolean, normalize=False), Literal(True)))
        self.error("unsupported-comparison", compare, SWRLB.lessThan, Literal(False), Literal(True))
        self.error("incompatible-datatypes", compare, SWRLB.equal, Literal("1"), integer(1))

    def test_invalid_boolean_and_unsupported_comparison(self):
        self.error("invalid-boolean", compare, SWRLB.equal,
                   Literal("maybe", datatype=XSD.boolean, normalize=False), Literal(True))
        self.error("unsupported-datatype", compare, SWRLB.equal, Literal(1.0), Literal(1.0))

    def test_same_value_supported_types_and_unknown_fallback(self):
        self.assertTrue(same_value(integer("+0002"), decimal("2.000")))
        self.assertTrue(same_value(Literal("abc"), Literal("abc", datatype=XSD.string)))
        self.assertFalse(same_value(Literal("2"), integer(2)))
        unknown = URIRef("urn:scalar-test:datatype")
        self.assertTrue(same_value(Literal("x", datatype=unknown), Literal("x", datatype=unknown)))
        self.assertFalse(same_value(Literal("02", datatype=unknown), Literal("2", datatype=unknown)))
        self.assertTrue(same_value(Literal("x", lang="en"), Literal("x", lang="en")))
        self.assertFalse(same_value(EX.one, EX.two))
        self.error("integer-range", same_value, integer(128, XSD.byte), integer(128, XSD.byte))

    def test_same_instant_different_offsets_and_stamp(self):
        a = instant("2026-10-21T08:00:00+08:00")
        b = instant("2026-10-21T00:00:00Z", XSD.dateTimeStamp)
        self.assertTrue(same_value(a, b))
        self.assertTrue(compare(SWRLB.equal, a, b))
        self.assertEqual(evaluate(OTFN.secondsBetween, (a, b)), decimal("0.0"))
        self.assertEqual(evaluate(OTFN.addSeconds, (a, integer(0))), instant("2026-10-21T00:00:00Z"))

    def test_temporal_difference_positive_negative_and_leap_date(self):
        start = instant("2024-02-28T23:59:59.999Z")
        end = instant("2024-02-29T00:00:00.001Z")
        self.assertEqual(evaluate(OTFN.secondsBetween, (end, start)), decimal("0.002"))
        self.assertEqual(evaluate(OTFN.secondsBetween, (start, end)), decimal("-0.002"))
        self.assertEqual(evaluate(OTFN.secondsBetween,
            (instant("2024-03-01T00:00:00Z"), instant("2024-02-28T00:00:00Z"))), decimal("172800.0"))

    def test_add_seconds_cross_day_and_negative(self):
        self.assertEqual(evaluate(OTFN.addSeconds,
            (instant("2026-12-31T23:59:59.9Z"), decimal("0.1"))), instant("2027-01-01T00:00:00Z"))
        self.assertEqual(evaluate(OTFN.addSeconds,
            (instant("2024-03-01T00:00:00Z"), integer(-1))), instant("2024-02-29T23:59:59Z"))
        self.assertEqual(evaluate(OTFN.addSeconds,
            (instant("2026-10-21T00:00:00Z"), decimal("0.001"))), instant("2026-10-21T00:00:00.001Z"))

    def test_temporal_ordering_and_exact_timezone_boundaries(self):
        early = instant("2026-10-21T00:00:00+14:00")
        late = instant("2026-10-21T00:00:00-14:00")
        self.assertTrue(compare(SWRLB.lessThan, early, late))
        self.assertEqual(evaluate(OTFN.secondsBetween, (late, early)), decimal("100800.0"))

    def test_date_lexical_contract_and_millisecond_precision(self):
        for text in ("2026-10-21T00:00:00", "2026-10-21T24:00:00Z", "2026-10-21T23:59:60Z",
                     "2026-10-21T00:00:00.0001Z", "2026-10-21T00:00:00.1000Z",
                     "2026-10-21T00:00:00+14:01", "2026-10-21T00:00:00+15:00",
                     "2026-10-21T00:00:00+01:60", "2025-02-29T00:00:00Z", "0000-01-01T00:00:00Z",
                     "10000-01-01T00:00:00Z", "2026-10-21 00:00:00Z"):
            with self.subTest(text=text):
                self.error("invalid-datetime", evaluate, OTFN.addSeconds, (instant(text), integer(0)))
        self.error("datetime-precision", evaluate, OTFN.addSeconds,
                   (instant("2026-10-21T00:00:00Z"), decimal("0.0001")))

    def test_datetime_utc_range_before_and_after_computation(self):
        for text in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"):
            self.error("datetime-range", evaluate, OTFN.addSeconds, (instant(text), integer(0)))
        self.error("datetime-range", evaluate, OTFN.addSeconds,
                   (instant("0001-01-01T00:00:00Z"), decimal("-0.001")))
        self.error("datetime-range", evaluate, OTFN.addSeconds,
                   (instant("9999-12-31T23:59:59.999Z"), decimal("0.001")))
        self.assertEqual(evaluate(OTFN.addSeconds,
            (instant("0001-01-01T00:00:00Z"), integer(0))), instant("0001-01-01T00:00:00Z"))

    def test_no_date_or_duration_implicit_conversion(self):
        self.error("unsupported-datatype", evaluate, OTFN.addSeconds,
                   (Literal("2026-10-21", datatype=XSD.date, normalize=False), integer(0)))
        self.error("unsupported-datatype", evaluate, OTFN.addSeconds,
                   (instant("2026-10-21T00:00:00Z"), Literal("PT1S", datatype=XSD.dayTimeDuration, normalize=False)))

    def test_temporal_validation_ignores_only_annotations(self):
        invalid = instant("2026-10-21T00:00:00.123456Z")
        graph = Graph()
        graph.add((EX.note, RDF.type, OWL.AnnotationProperty))
        graph.add((URIRef("http://purl.org/dc/terms/created"), RDF.type, OWL.AnnotationProperty))
        graph.add((EX.a, EX.note, invalid))
        graph.add((EX.a, RDFS.comment, invalid))
        graph.add((EX.a, URIRef("http://purl.org/dc/terms/created"), invalid))
        validate_temporal_literals(graph)
        graph.add((EX.a, EX.start, invalid))
        self.error("invalid-datetime", validate_temporal_literals, graph)

    def test_temporal_validation_has_no_namespace_annotation_exemption(self):
        graph = Graph()
        predicate = URIRef("http://purl.org/dc/terms/business-time")
        graph.add((predicate, RDF.type, OWL.DatatypeProperty))
        graph.add((EX.a, predicate, instant("2026-10-21T00:00:00.123456Z")))
        self.error("invalid-datetime", validate_temporal_literals, graph)

    def test_temporal_validation_includes_rules_and_restrictions(self):
        for predicate in (RDF.first, OWL.hasValue, URIRef("http://www.w3.org/2003/11/swrl#argument2")):
            graph = Graph()
            graph.add((EX.a, predicate, instant("2026-10-21T00:00:00")))
            self.error("invalid-datetime", validate_temporal_literals, graph)

    def test_temporal_input_is_not_mutated(self):
        value = instant("2026-10-21T08:00:00.100+08:00")
        self.assertEqual(evaluate(OTFN.addSeconds, (value, integer(0))), instant("2026-10-21T00:00:00.1Z"))
        self.assertEqual(str(value), "2026-10-21T08:00:00.100+08:00")

    def test_canonical_temporal_bridge_value_preservation(self):
        value = instant("2026-10-20T19:00:00.010-05:00", XSD.dateTimeStamp)
        canonical = canonical_temporal_literal(value)
        self.assertEqual(canonical, instant("2026-10-21T00:00:00.01Z", XSD.dateTimeStamp))
        self.assertEqual(canonical_temporal_literal(value, preserve_datatype=False),
                         instant("2026-10-21T00:00:00.01Z"))
        self.assertTrue(same_value(value, canonical))
        self.assertEqual(str(value), "2026-10-20T19:00:00.010-05:00")
        self.error("invalid-datetime", canonical_temporal_literal, instant("2026-10-20T19:00:00Z "+"x"))


if __name__ == "__main__":
    unittest.main()
