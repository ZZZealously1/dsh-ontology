"""Real HermiT and public-API regression checks for frozen reasoning replay."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, XSD

from ontology_tools import infer_owl
from ontology_tools.core import RUN, infer_graph, replay_run, run_cases
from ontology_tools.io import OT, ToolError, parse_rdf, write_graph, write_manifest
from ontology_tools.owl_dl import check_consistency

ROOT = Path(__file__).resolve().parents[1]
EX = Namespace("urn:test:unified:")
PREFIX = """@prefix ex: <urn:test:unified:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:ontology a owl:Ontology .
ex:A a owl:Class .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
ex:a a owl:NamedIndividual, ex:B .
"""


class UnifiedReplayTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("ONTOLOGY_TEST_OUTPUT", ROOT.parent.parent))
        self.temp = tempfile.TemporaryDirectory(prefix="unified-replay-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "model.ttl"
        self.source.write_text(PREFIX, encoding="utf-8")

    def assert_passed(self, output):
        self.assertEqual(Literal("passed"), parse_rdf(output / "execution.ttl").value(RUN, OT.status))

    def test_check_replays_from_snapshot_after_original_changes(self):
        run = check_consistency(self.source, self.root / "check")
        self.source.write_text("source no longer parses", encoding="utf-8")
        replayed = replay_run(run, self.root / "replay")
        self.assert_passed(replayed)

    def test_nonconformant_check_can_be_reproduced_without_becoming_valid(self):
        self.source.write_text(PREFIX + "ex:A owl:disjointWith ex:B .\n", encoding="utf-8")
        run = check_consistency(self.source, self.root / "check")
        self.assertEqual(Literal("nonconformant"), parse_rdf(run / "execution.ttl").value(RUN, OT.status))
        replayed = replay_run(run, self.root / "replay")
        self.assert_passed(replayed)
        self.assertEqual(Literal("nonconformant"),
                         parse_rdf(replayed / "replayed/execution.ttl").value(RUN, OT.status))

    def test_owl_projection_replays_all_semantic_graphs(self):
        run = infer_owl(self.source, self.root / "infer")
        self.assertIn((EX.a, RDF.type, EX.A), parse_rdf(run / "result.ttl"))
        replayed = replay_run(run, self.root / "replay")
        self.assert_passed(replayed)
        paths = set(map(str, parse_rdf(replayed / "replay-report.ttl").objects(None, OT.path)))
        self.assertTrue({"classification.ttl", "candidates.ttl", "facts.ttl",
                         "result.ttl", "closure.ttl", "trace.ttl"} <= paths)

    def test_tampered_saved_input_is_rejected(self):
        run = check_consistency(self.source, self.root / "check")
        with (run / "assembled.rdf").open("a", encoding="utf-8") as stream:
            stream.write("\n<!-- changed -->")
        with self.assertRaisesRegex(ToolError, "Manifest mismatch"):
            replay_run(run, self.root / "replay")

    def test_changed_runtime_fingerprint_is_rejected(self):
        run = check_consistency(self.source, self.root / "check")
        (run / "runtime.sha256").write_text("changed runtime\n", encoding="utf-8")
        (run / "manifest.sha256").unlink()
        write_manifest(run)
        with self.assertRaisesRegex(ToolError, "runtime/dependency fingerprint"):
            replay_run(run, self.root / "replay")

    def test_forged_result_with_refreshed_manifest_fails_semantic_comparison(self):
        run = infer_owl(self.source, self.root / "infer")
        result = parse_rdf(run / "result.ttl")
        result.add((EX.a, EX.inventedResult, Literal(True)))
        write_graph(result, run / "result.ttl")
        (run / "manifest.sha256").unlink()
        write_manifest(run)
        replayed = replay_run(run, self.root / "replay")
        self.assertEqual(Literal("failed"), parse_rdf(replayed / "replay-report.ttl").value(RUN, OT.status))

    def test_projection_replays_from_semantic_package_without_original_sources(self):
        package = self.root / "package"
        shutil.copytree(ROOT / "examples/projection", package)
        run = infer_graph(package, output=self.root / "infer")
        self.assertGreaterEqual(int(parse_rdf(run / "execution.ttl").value(RUN, OT.iterations)), 2)
        (package / "ontology.ttl").write_text("original no longer available", encoding="utf-8")
        replayed = replay_run(run, self.root / "replay")
        self.assert_passed(replayed)
        paths = set(map(str, parse_rdf(replayed / "replay-report.ttl").objects(None, OT.path)))
        self.assertTrue(any(p.startswith("rounds/round-0002/") for p in paths))
        self.assertTrue(any(p.endswith("/swrl-trace.ttl") for p in paths))

    def test_projection_replay_keeps_relative_iri_identity_and_local_imports(self):
        package = self.root / "relative"
        (package / "modules").mkdir(parents=True)
        (package / "inputs").mkdir()
        (package / "ontology.ttl").write_text(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> . '
            '<urn:test:root> a owl:Ontology ; owl:imports <urn:test:module> .', encoding="utf-8")
        (package / "modules/shared.ttl").write_text(
            PREFIX.replace("<urn:test:unified:>", "<#>"), encoding="utf-8")
        # The module header must match its explicit import mapping.
        module = package / "modules/shared.ttl"
        module.write_text(module.read_text(encoding="utf-8").replace(
            "ex:ontology a owl:Ontology .", "<urn:test:module> a owl:Ontology ."), encoding="utf-8")
        (package / "imports-map.ttl").write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '<urn:test:map> a ot:ImportMapping ; ot:ontologyIRI <urn:test:module> ; '
            'ot:path "modules/shared.ttl" .', encoding="utf-8")
        (package / "inputs/facts.ttl").write_text("", encoding="utf-8")
        (package / "shapes.ttl").write_text("", encoding="utf-8")
        (package / "runtime.ttl").write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '<urn:test:runtime> a ot:Runtime ; ot:profile "hermit-swrl-projection-v1" .', encoding="utf-8")
        run = infer_graph(package, output=self.root / "infer")
        original_terms = Namespace(module.as_uri() + "#")
        self.assertIn((original_terms.a, RDF.type, original_terms.A), parse_rdf(run / "result.ttl"))
        module.write_text("source removed", encoding="utf-8")
        self.assert_passed(replay_run(run, self.root / "replay"))

    def test_golden_projection_preserves_original_relative_iri_bases(self):
        package = self.root / "relative-golden"
        (package / "inputs").mkdir(parents=True)
        (package / "tests/inputs").mkdir(parents=True)
        model = package / "ontology.ttl"
        model.write_text(
            '@prefix ex: <#> . '
            '@prefix owl: <http://www.w3.org/2002/07/owl#> . '
            '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . '
            'ex:ontology a owl:Ontology . '
            'ex:A a owl:Class . ex:B a owl:Class ; rdfs:subClassOf ex:A .',
            encoding="utf-8")
        facts = package / "tests/inputs/relative.ttl"
        facts.write_text('<#a> a <../../ontology.ttl#B> .', encoding="utf-8")
        (package / "inputs/facts.ttl").write_text("", encoding="utf-8")
        (package / "shapes.ttl").write_text("", encoding="utf-8")
        (package / "runtime.ttl").write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '<urn:test:runtime> a ot:Runtime ; ot:profile "hermit-swrl-projection-v1" .',
            encoding="utf-8")
        # Expectations are authored from the source document identities, not
        # obtained from either engine's output or the relocated test package.
        model_terms = Namespace(model.as_uri() + "#")
        fact_terms = Namespace(facts.as_uri() + "#")
        expected = (fact_terms.a, RDF.type, model_terms.A)
        cases = package / "tests/cases.ttl"
        cases.write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> . '
            '<urn:test:relative-golden> a ot:Case ; '
            'ot:input "inputs/relative.ttl" ; ot:expectedOutcome "passed" ; '
            'ot:expectedTriple [ rdf:subject ' + fact_terms.a.n3() +
            ' ; rdf:predicate rdf:type ; rdf:object ' + model_terms.A.n3() + ' ] .',
            encoding="utf-8")
        source_bytes = {
            path.relative_to(package): path.read_bytes()
            for path in package.rglob("*") if path.is_file()
        }
        direct = infer_graph(package, facts=facts, output=self.root / "direct")
        self.assert_passed(direct)
        self.assertIn(expected, parse_rdf(direct / "result.ttl"))

        golden = run_cases(package, self.root / "golden")
        self.assert_passed(golden)
        report = parse_rdf(golden / "test-report.ttl")
        self.assertEqual(Literal(1), report.value(RUN, OT.passed))
        self.assertEqual(Literal(0), report.value(RUN, OT.failed))
        case_output = golden / str(report.value(
            Namespace("urn:test:")["relative-golden"], OT.output))
        self.assertIn(expected, parse_rdf(case_output / "result.ttl"))
        for name in ("result.ttl", "closure.ttl", "classification.ttl", "candidates.ttl"):
            self.assertTrue(
                isomorphic(parse_rdf(direct / name), parse_rdf(case_output / name)),
                f"Golden execution changed source-document semantics: {name}")
        for relative, original in source_bytes.items():
            self.assertEqual(original, (golden / "snapshot/package" / relative).read_bytes())
            self.assertEqual(original, (package / relative).read_bytes())

    def test_technical_failure_is_not_replayable(self):
        with self.assertRaises(ToolError):
            check_consistency(self.source, self.root / "failed", java="missing-java-for-test")
        with self.assertRaisesRegex(ToolError, "completed inference or semantic check"):
            replay_run(self.root / "failed", self.root / "replay")


class ExplicitGoldenOutcomes(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("ONTOLOGY_TEST_OUTPUT", ROOT.parent.parent))
        self.temp = tempfile.TemporaryDirectory(prefix="golden-outcomes-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        (self.package / "inputs").mkdir(parents=True)
        (self.package / "tests/inputs").mkdir(parents=True)
        (self.package / "ontology.ttl").write_text(
            PREFIX.replace("ex:a a owl:NamedIndividual, ex:B .", "") +
            "ex:A owl:disjointWith ex:C . ex:C a owl:Class .\n", encoding="utf-8")
        (self.package / "shapes.ttl").write_text("", encoding="utf-8")
        (self.package / "inputs/facts.ttl").write_text("", encoding="utf-8")
        (self.package / "runtime.ttl").write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '<urn:test:runtime> a ot:Runtime ; ot:profile "hermit-swrl-projection-v1" .', encoding="utf-8")
        (self.package / "tests/inputs/conflict.ttl").write_text(
            "@prefix ex: <urn:test:unified:> . ex:a a ex:A, ex:C .", encoding="utf-8")

    def cases(self, outcome):
        (self.package / "tests/cases.ttl").write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '<urn:test:case> a ot:Case ; ot:input "inputs/conflict.ttl" ; '
            f'ot:expectedOutcome "{outcome}" .', encoding="utf-8")

    def test_expected_owl_inconsistency_is_an_independent_successful_test(self):
        self.cases("owl-inconsistent")
        out = run_cases(self.package, self.root / "test")
        self.assertEqual(Literal("passed"), parse_rdf(out / "test-report.ttl").value(RUN, OT.status))

    def test_nonconformant_projection_is_replayable(self):
        run = self.root / "infer"
        with self.assertRaises(ToolError) as failure:
            infer_graph(self.package, facts=self.package / "tests/inputs/conflict.ttl", output=run)
        self.assertEqual(1, failure.exception.exit_code)
        replayed = replay_run(run, self.root / "replay")
        self.assertEqual(Literal("passed"), parse_rdf(replayed / "execution.ttl").value(RUN, OT.status))
        self.assertEqual(Literal("nonconformant"),
                         parse_rdf(replayed / "replayed/execution.ttl").value(RUN, OT.status))

    def test_owl_conflict_does_not_satisfy_shacl_failure_expectation(self):
        self.cases("shacl-invalid")
        out = run_cases(self.package, self.root / "test")
        self.assertEqual(Literal("failed"), parse_rdf(out / "test-report.ttl").value(RUN, OT.status))

    def test_unsatisfiable_class_set_is_compared_separately(self):
        model = self.package / "ontology.ttl"
        model.write_text(model.read_text(encoding="utf-8") + "ex:B rdfs:subClassOf ex:C .\n",
                         encoding="utf-8")
        (self.package / "tests/inputs/conflict.ttl").write_text("", encoding="utf-8")
        self.cases("owl-unsatisfiable")
        cases = self.package / "tests/cases.ttl"
        cases.write_text(cases.read_text(encoding="utf-8") +
                         '\n<urn:test:case> <https://w3id.org/ontology-tools#expectedUnsatisfiableClass> '
                         '<urn:test:unified:B> .\n', encoding="utf-8")
        out = run_cases(self.package, self.root / "test")
        self.assertEqual(Literal("passed"), parse_rdf(out / "test-report.ttl").value(RUN, OT.status))

    def test_unspecified_technical_failure_cannot_pass(self):
        self.cases("failed")
        with patch("ontology_tools.core.infer_graph") as execute:
            out = run_cases(self.package, self.root / "test")
        execute.assert_not_called()
        self.assertEqual(Literal("failed"), parse_rdf(out / "test-report.ttl").value(RUN, OT.status))

    def test_malformed_case_facts_remain_an_expected_technical_failure(self):
        malformed = b"@prefix ex: <urn:test:unified:> .\nex:a ex:broken ["
        facts = self.package / "tests/inputs/conflict.ttl"
        facts.write_bytes(malformed)
        self.cases("failed")
        cases = self.package / "tests/cases.ttl"
        cases.write_text(
            cases.read_text(encoding="utf-8") +
            '\n<urn:test:case> <https://w3id.org/ontology-tools#expectedFailureStage> "inspect" .\n',
            encoding="utf-8")
        out = run_cases(self.package, self.root / "test")
        self.assertEqual(Literal("passed"), parse_rdf(out / "execution.ttl").value(RUN, OT.status))
        report = parse_rdf(out / "test-report.ttl")
        self.assertEqual(Literal(1), report.value(RUN, OT.passed))
        self.assertEqual(Literal(0), report.value(RUN, OT.failed))
        case_output = out / str(report.value(Namespace("urn:test:").case, OT.output))
        execution = parse_rdf(case_output / "execution.ttl")
        self.assertEqual(Literal("failed"), execution.value(RUN, OT.status))
        self.assertEqual(Literal(2), execution.value(RUN, OT.exitCode))
        self.assertEqual(Literal("inspect"), execution.value(RUN, OT.stage))
        self.assertEqual(Literal("unknown"), execution.value(RUN, OT.semanticState))
        self.assertFalse((case_output / "result.ttl").exists())
        self.assertFalse((case_output / "closure.ttl").exists())
        self.assertEqual(malformed, (out / "snapshot/package/tests/inputs/conflict.ttl").read_bytes())
        self.assertEqual(malformed, facts.read_bytes())

    def test_plain_string_golden_matches_rdf11_typed_hasvalue_entailment(self):
        model = self.package / "ontology.ttl"
        model.write_text(
            model.read_text(encoding="utf-8") +
            '\nex:code a owl:DatatypeProperty . '
            'ex:B rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:code ; '
            'owl:hasValue "ready" ] .\n',
            encoding="utf-8")
        (self.package / "tests/inputs/conflict.ttl").write_text(
            "@prefix ex: <urn:test:unified:> . ex:a a ex:B .", encoding="utf-8")
        cases = self.package / "tests/cases.ttl"
        cases.write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> . '
            '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> . '
            '@prefix ex: <urn:test:unified:> . '
            '<urn:test:case> a ot:Case ; ot:input "inputs/conflict.ttl" ; '
            'ot:expectedOutcome "passed" ; '
            'ot:expectedTriple [ rdf:subject ex:a ; rdf:predicate ex:code ; rdf:object "ready" ] .',
            encoding="utf-8")
        out = run_cases(self.package, self.root / "test")
        self.assertEqual(Literal("passed"), parse_rdf(out / "execution.ttl").value(RUN, OT.status))
        report = parse_rdf(out / "test-report.ttl")
        self.assertEqual(Literal(1), report.value(RUN, OT.passed))
        case_output = out / str(report.value(Namespace("urn:test:").case, OT.output))
        self.assertIn(
            (EX.a, EX.code, Literal("ready", datatype=XSD.string)),
            parse_rdf(case_output / "result.ttl"))
        self.assertIn('rdf:object "ready"', cases.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
