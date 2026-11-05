"""Independent golden numeric protocol tests, including real outcome execution."""
from decimal import localcontext
from pathlib import Path
import shutil
import tempfile
import unittest

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, XSD

from ontology_tools.core import RUN, _check_numeric_expectations, _outcome_case
from ontology_tools.formula import F
from ontology_tools.io import OT, ToolError, parse_rdf, write_graph

EX = Namespace("urn:numeric-golden:")
SYNTHETIC = Namespace("urn:formula-example:")


def decimal(value):
    return Literal(str(value), datatype=XSD.decimal, normalize=False)


def expectation(reference, actual, *, absolute="0", relative=None, unit="m", actual_unit="m"):
    cases, result = Graph(), Graph()
    cases.add((EX.case, OT.expectedNumeric, EX.expectation))
    for predicate, value in ((RDF.subject, EX.subject), (RDF.predicate, EX.result),
                             (RDF.value, decimal(reference))):
        cases.add((EX.expectation, predicate, value))
    if absolute is not None:
        cases.add((EX.expectation, OT.absoluteTolerance, decimal(absolute)))
    if relative is not None:
        cases.add((EX.expectation, OT.relativeTolerance, decimal(relative)))
    if unit is not None:
        cases.add((EX.expectation, OT.unit, Literal(unit)))
        cases.add((EX.expectation, OT.unitPredicate, EX.unit))
    if actual is not None:
        result.add((EX.subject, EX.result, decimal(actual)))
    if actual_unit is not None:
        result.add((EX.subject, EX.unit, Literal(actual_unit)))
    return cases, result


class NumericExpectationTests(unittest.TestCase):
    def check(self, reference, actual, expected, **kwargs):
        cases, result = expectation(reference, actual, **kwargs)
        checks, details = _check_numeric_expectations(cases, EX.case, result)
        self.assertEqual(checks, [expected])
        self.assertEqual(len(details), 1)

    def test_explicit_zero_requires_exact_equal_value(self):
        self.check("0", "-0.000", True)
        self.check("1.00", "1.000", True)
        self.check("1", "1.0000000000000000000000000000000000000000000000001", False)

    def test_absolute_tolerance_inclusive_boundary(self):
        self.check("10", "10.5", True, absolute="0.5")
        self.check("10", "9.5", True, absolute="0.5")
        self.check("10", "10.500001", False, absolute="0.5")

    def test_relative_tolerance_uses_absolute_reference_magnitude(self):
        self.check("-100", "-105", True, absolute=None, relative="0.05")
        self.check("-100", "-105.00001", False, absolute=None, relative="0.05")
        self.check("0", "0.001", False, absolute=None, relative="0.99")

    def test_absolute_and_relative_tolerance_use_larger_bound(self):
        self.check("100", "102", True, absolute="0.1", relative="0.02")
        self.check("100", "102.1", False, absolute="0.1", relative="0.02")
        self.check("1", "1.5", True, absolute="0.5", relative="0.02")

    def test_declared_unit_mismatch_or_absence_fails(self):
        self.check("1", "1", False, actual_unit="cm")
        self.check("1", "1", False, actual_unit=None)
        self.check("1", "1", True, unit=None, actual_unit=None)

    def test_additional_wrong_result_or_unit_is_not_hidden(self):
        cases, result = expectation("1", "1")
        result.add((EX.subject, EX.result, decimal("999")))
        self.assertEqual(_check_numeric_expectations(cases, EX.case, result)[0], [False])
        cases, result = expectation("1", "1")
        result.add((EX.subject, EX.unit, Literal("s")))
        self.assertEqual(_check_numeric_expectations(cases, EX.case, result)[0], [False])
        self.check("1", None, False)

    def test_missing_or_negative_tolerance_is_rejected(self):
        for kwargs in ({"absolute": None}, {"absolute": "-0.1"}, {"absolute": None, "relative": "-0.1"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ToolError):
                cases, result = expectation("1", "1", **kwargs)
                _check_numeric_expectations(cases, EX.case, result)

    def test_nonfinite_reference_actual_and_tolerance_are_rejected(self):
        for reference, actual, kwargs in (("NaN", "1", {}), ("1", "NaN", {}),
                                         ("1", "1", {"absolute": "NaN"})):
            with self.subTest(reference=reference, actual=actual, kwargs=kwargs), self.assertRaises(ToolError):
                cases, result = expectation(reference, actual, **kwargs)
                _check_numeric_expectations(cases, EX.case, result)

    def test_extremely_small_values_are_compared_exactly(self):
        one = "0." + "0" * 799 + "1"
        two = "0." + "0" * 799 + "2"
        self.check(one, two, False)
        self.check(one, two, True, absolute=one)

    def test_fifty_digit_relative_boundary_does_not_use_decimal_default_precision(self):
        reference = "1.2345678901234567890123456789012345678901234567890"
        exactly_on_bound = "1.3580246791358024679135802467913580246791358024679"
        beyond_bound = "1.3580246791358024679135802467913580246791358024680"
        for precision in (2, 28, 50):
            with self.subTest(precision=precision), localcontext() as context:
                context.prec = precision
                self.check(reference, exactly_on_bound, True, absolute=None, relative="0.1")
                self.check(reference, beyond_bound, False, absolute=None, relative="0.1")

    def test_half_unit_contract_is_rejected(self):
        cases, result = expectation("1", "1")
        cases.remove((EX.expectation, OT.unitPredicate, None))
        with self.assertRaises(ToolError):
            _check_numeric_expectations(cases, EX.case, result)


class NumericOutcomeExecutionTests(unittest.TestCase):
    def test_real_outcome_case_accepts_correct_and_rejects_wrong_numeric_reference(self):
        with tempfile.TemporaryDirectory(prefix="numeric-outcome-") as temporary:
            root = Path(temporary)
            package = root / "ontology"
            shutil.copytree(Path(__file__).resolve().parents[1] / "examples/formula", package)
            cases = Graph()
            for identifier, expected in ((EX.correct, "0.00005"), (EX.wrong, "0.00006")):
                item = Namespace(str(identifier) + ":").numeric
                cases.add((identifier, OT.expectedOutcome, Literal("passed")))
                cases.add((identifier, OT.expectedNumeric, item))
                for predicate, value in ((RDF.subject, SYNTHETIC.evaluation), (RDF.predicate, F.result),
                    (RDF.value, decimal(expected)), (OT.absoluteTolerance, decimal("0")),
                    (OT.unit, Literal("m")), (OT.unitPredicate, F.resultUnit)):
                    cases.add((item, predicate, value))
            write_graph(cases, package / "tests/cases.ttl")
            for identifier, expected_ok, directory in ((EX.correct, True, root / "correct"),
                                                       (EX.wrong, False, root / "wrong")):
                with self.subTest(identifier=identifier):
                    ok, detail, covered = _outcome_case(cases, identifier, package,
                        package / "inputs/facts.ttl", directory)
                    self.assertEqual(ok, expected_ok, detail)
                    # Both actual reasoner executions succeed; only the hand-
                    # authored incorrect golden numeric expectation must fail.
                    execution = parse_rdf(directory / "execution.ttl")
                    self.assertEqual(execution.value(RUN, OT.status), Literal("passed"))
                    self.assertEqual(bool(covered), expected_ok)


if __name__ == "__main__":
    unittest.main()
