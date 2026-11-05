"""Real HermiT acceptance for immutable RDF formulas and OWL/SWRL feedback.

The shared golden-case run avoids repeatedly starting Java for the same case.
No reasoning, formula calculation, or replay is mocked.
"""
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
import unittest

from rdflib import Literal, Namespace
from rdflib.namespace import RDF, XSD

from ontology_tools.core import RUN, infer_graph, inspect_package, replay_run, run_cases
from ontology_tools.formula import F
from ontology_tools.io import OT, ToolError, parse_rdf, write_graph

EX = Namespace("urn:formula-example:")


class FormulaRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="formula-runtime-")
        cls.root = Path(cls.temporary.name)
        cls.package = cls.root / "ontology"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples/formula", cls.package)
        cls.output = run_cases(cls.package, cls.root / "cases")
        cls.report = parse_rdf(cls.output / "test-report.ttl")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def case_directory(self, name):
        return self.output / str(self.report.value(EX["case-" + name], OT.output))

    def test_real_owl_swrl_formula_swrl_owl_feedback(self):
        self.assertEqual(self.report.value(RUN, OT.status), Literal("passed"))
        self.assertEqual(self.report.value(RUN, OT.passed), Literal(6))
        directory = self.case_directory("positive")
        closure = parse_rdf(directory / "closure.ttl")
        self.assertEqual(Decimal(str(closure.value(EX.evaluation, F.result))), Decimal("0.00005"))
        for triple in ((EX.observation, RDF.type, EX.UsableObservation),
                       (EX.evaluation, F.satisfiedCondition, EX.usableObservation),
                       (EX.evaluation, F.calculationStatus, F.Computed),
                       (EX.evaluation, RDF.type, EX.AboveSyntheticReference),
                       (EX.evaluation, RDF.type, EX.NeedsSyntheticReview)):
            self.assertIn(triple, closure)
        execution = parse_rdf(directory / "execution.ttl")
        self.assertGreaterEqual(int(execution.value(RUN, OT.iterations)), 3)
        self.assertEqual(int(execution.value(RUN, OT.pendingFormulaCount)), 0)
        self.assertEqual(set(self.report.objects(RUN, OT.coveredRule)),
                         {EX.permitFromObservation, EX.classifyComputedResult})

    def test_missing_input_and_condition_remain_pending_without_results(self):
        for case, code in (("missing-input", "missing-input"), ("missing-condition", "missing-condition")):
            with self.subTest(case=case):
                directory = self.case_directory(case)
                closure = parse_rdf(directory / "closure.ttl")
                self.assertIsNone(closure.value(EX.evaluation, F.result))
                self.assertNotIn((EX.evaluation, F.calculationStatus, F.Computed), closure)
                execution = parse_rdf(directory / "execution.ttl")
                self.assertEqual(execution.value(RUN, OT.status), Literal("passed"))
                self.assertEqual(int(execution.value(RUN, OT.pendingFormulaCount)), 1)
                diagnostics = parse_rdf(directory / "formula-diagnostics.ttl")
                self.assertIn(Literal(code), set(diagnostics.objects(None, F.code)))

    def test_invalid_units_and_cycles_are_saved_technical_failures(self):
        for case, code in (("invalid-unit", "unit-mismatch"), ("cycle", "dependency-cycle")):
            with self.subTest(case=case):
                directory = self.case_directory(case)
                execution = parse_rdf(directory / "execution.ttl")
                self.assertEqual(execution.value(RUN, OT.stage), Literal("formula-evaluation"))
                self.assertIn(code, str(execution.value(RUN, OT.error)))
                self.assertFalse((directory / "result.ttl").exists())
                self.assertFalse((directory / "closure.ttl").exists())

    def test_result_injection_is_rejected_before_computation(self):
        directory = self.case_directory("result-injection")
        execution = parse_rdf(directory / "execution.ttl")
        self.assertEqual(execution.value(RUN, OT.stage), Literal("inspect"))
        self.assertIn("prewrite calculator outputs", str(execution.value(RUN, OT.error)))
        self.assertFalse((directory / "formula-computations.ttl").exists())

    def test_named_candidates_frozen_and_disabled_ast_excluded(self):
        directory = self.case_directory("positive")
        initial, final = parse_rdf(directory / "initial-candidates.ttl"), parse_rdf(directory / "candidates.ttl")
        self.assertEqual(set(initial.objects(None, OT.individual)), set(final.objects(None, OT.individual)))
        self.assertNotIn(F.Sqrt, set(initial.objects(None, OT.individual)))
        self.assertNotIn(EX.unreviewed, set(initial.objects(None, OT.individual)))
        expected = Literal("0.00005", datatype=XSD.decimal)
        self.assertNotIn(expected, set(initial.objects(None, OT.literal)))
        self.assertIn(expected, set(final.objects(None, OT.literal)))
        computations = parse_rdf(directory / "formula-computations.ttl")
        self.assertIn(F.Sqrt, set(computations.objects(None, F.operator)))
        self.assertIn(Literal(r"L=\sqrt{D\tau}"), set(computations.objects(None, F.latex)))

    def test_legacy_profile_requires_explicit_formula_opt_in(self):
        legacy = self.root / "legacy"
        shutil.copytree(self.package, legacy)
        runtime = parse_rdf(legacy / "runtime.ttl")
        runtime.set((EX.runtime, OT.profile, Literal("hermit-swrl-calculation-v1")))
        runtime.remove((EX.runtime, OT.formulaPrecision, None))
        write_graph(runtime, legacy / "runtime.ttl")
        with self.assertRaises(ToolError) as caught:
            inspect_package(legacy)
        self.assertIn("formula", str(caught.exception).lower())

    def test_replay_reruns_formula_results_and_detects_saved_evidence_tampering(self):
        directory = self.case_directory("positive")
        replayed = replay_run(directory, self.root / "replay")
        execution = parse_rdf(replayed / "execution.ttl")
        self.assertEqual(execution.value(RUN, OT.status), Literal("passed"))
        for relative in ("formulas.ttl", "formula-computations.ttl", "formula-contract.ttl"):
            with self.subTest(relative=relative):
                path = directory / relative
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n# altered evidence\n")
                    with self.assertRaises(ToolError):
                        replay_run(directory, self.root / ("tamper-" + relative.replace(".", "-")))
                finally:
                    path.write_bytes(original)


class FormulaNumericAliasRuntimeTests(unittest.TestCase):
    """Real OWL feedback must not turn equal numeric spellings into conflicts."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="formula-aliases-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "ontology"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples/formula", self.package)

    def test_real_hermit_equal_decimal_and_integer_aliases_and_result_feedback(self):
        catalog = parse_rdf(self.package / "formulas.ttl")
        catalog.set((EX.D, F.unit, Literal("m^2/s")))
        write_graph(catalog, self.package / "formulas.ttl")
        facts = parse_rdf(self.package / "inputs/facts.ttl")
        facts.set((EX.bindingD, F.value, Literal("1.00", datatype=XSD.decimal, normalize=False)))
        facts.add((EX.bindingD, F.value, Literal("1", datatype=XSD.integer, normalize=False)))
        facts.set((EX.bindingTau, F.value, Literal("1.000", datatype=XSD.decimal, normalize=False)))
        facts.add((EX.bindingTau, F.value, Literal("1.0", datatype=XSD.decimal, normalize=False)))
        source = self.package / "inputs/facts.ttl"
        write_graph(facts, source)
        original = source.read_bytes()
        inferred = infer_graph(self.package, output=self.root / "infer")
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((inferred / "facts-source.ttl").read_bytes(), original)
        raw = parse_rdf(inferred / "input.ttl")
        self.assertEqual(len(set(raw.objects(EX.bindingD, F.value))), 2)
        closure = parse_rdf(inferred / "closure.ttl")
        result = parse_rdf(inferred / "result.ttl")
        canonical = Literal("1.0", datatype=XSD.decimal, normalize=False)
        self.assertEqual(set(closure.objects(EX.bindingD, F.value)), {canonical})
        self.assertEqual(set(closure.objects(EX.bindingTau, F.value)), {canonical})
        self.assertEqual(set(result.objects(EX.evaluation, F.result)), {canonical})
        self.assertIn((EX.evaluation, RDF.type, EX.NeedsSyntheticReview), closure)
        self.assertGreaterEqual(int(parse_rdf(inferred / "execution.ttl").value(RUN, OT.iterations)), 3)
        replayed = replay_run(inferred, self.root / "replay")
        self.assertEqual(parse_rdf(replayed / "execution.ttl").value(RUN, OT.status), Literal("passed"))

    def test_real_hermit_different_values_and_malformed_decimal_still_rejected(self):
        for label, extra in (("different", Literal("0.003", datatype=XSD.decimal, normalize=False)),
                             ("malformed", Literal("1e-19", datatype=XSD.decimal, normalize=False))):
            with self.subTest(label=label):
                package = self.root / label
                shutil.copytree(self.package, package)
                facts = parse_rdf(package / "inputs/facts.ttl")
                facts.add((EX.bindingD, F.value, extra))
                write_graph(facts, package / "inputs/facts.ttl")
                with self.assertRaises(ToolError):
                    infer_graph(package, output=self.root / (label + "-run"))
                self.assertFalse((self.root / (label + "-run/result.ttl")).exists())


if __name__ == "__main__":
    unittest.main()
