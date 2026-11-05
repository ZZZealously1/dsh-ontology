"""Independent end-to-end acceptance tests for the public offline tool API.

The synthetic parcel and sensor policies are intentionally unrelated. Expected
triples are fixed here and in fixture cases, never copied from runtime output.
Run from Ontology-tools: python -B -m unittest discover -s tests -v
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, SH, XSD
from rdflib.util import from_n3

from ontology_tools import core
from ontology_tools.io import ToolError, ValidationError


HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
PARCEL = Namespace("urn:test:parcel:")
SENSOR = Namespace("urn:test:sensor:")
OT = Namespace("https://w3id.org/ontology-tools#")
RUN = URIRef("urn:ontology-tools:run")


def read_graph(path: Path) -> Graph:
    return Graph().parse(path, format="turtle")


def fingerprint(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*") if path.is_file()
    }


def freeze(directory: Path) -> None:
    # Independent implementation, not the production manifest writer.
    entries = fingerprint(directory)
    entries.pop("manifest.sha256", None)
    (directory / "manifest.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items())),
        encoding="utf-8",
    )


class PublicApiAcceptance(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="ontology-acceptance-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.package = self.copy_package("parcel")
        self.network_guards = []
        for target in ("socket.create_connection", "urllib.request.urlopen"):
            guard = patch(target, side_effect=AssertionError("Network access is forbidden in acceptance tests"))
            self.network_guards.append(guard.start())
            self.addCleanup(guard.stop)

    def tearDown(self):
        for guard in self.network_guards:
            guard.assert_not_called()
        forbidden = [p for p in self.root.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".ndjson"}]
        self.assertEqual([], forbidden, "The native-RDF workflow must not create JSON artifacts")

    def copy_package(self, name: str) -> Path:
        destination = self.root / name
        shutil.copytree(FIXTURES / name, destination)
        return destination

    def infer(self, name="run", package=None, facts=None) -> Path:
        result = core.infer_graph(package or self.package, facts=facts, output=self.root / name)
        self.assertEqual(self.root / name, result)
        return result

    def assert_rejected(self, operation, *args, **kwargs):
        with self.assertRaises(ToolError):
            operation(*args, **kwargs)

    def test_inspect_parses_real_native_package(self):
        report = core.inspect_package(self.package)
        self.assertIsInstance(report, Graph)
        self.assertIn(Literal("passed"), list(report.objects(None, OT.status)))

    def test_input_validation_report_contains_real_shacl_verdict(self):
        valid = core.validate_graph(self.package)
        self.assertIn(Literal(True), list(valid.objects(None, SH.conforms)))
        invalid = core.validate_graph(self.package, facts=self.package / "tests/inputs/invalid.ttl")
        self.assertIn(Literal(False), list(invalid.objects(None, SH.conforms)))
        self.assertTrue(list(invalid.subjects(RDF.type, SH.ValidationResult)))

    def test_swrl_and_subclass_reach_fixed_point_without_mutating_package(self):
        before = fingerprint(self.package)
        output = self.infer()
        inferred = read_graph(output / "result.ttl")
        self.assertIn((PARCEL.ready, RDF.type, PARCEL.ReadyParcel), inferred)
        self.assertIn((PARCEL.ready, RDF.type, PARCEL.ProcessableParcel), inferred)
        self.assertNotIn((PARCEL.other, RDF.type, PARCEL.ReadyParcel), inferred)
        self.assertNotIn((PARCEL.ready, PARCEL.tag, Literal("ready")), inferred)
        self.assertIn((PARCEL.ready, PARCEL.tag, Literal("ready")), read_graph(output / "input.ttl"))
        self.assertIn((PARCEL.ready, PARCEL.tag, Literal("ready")), read_graph(output / "closure.ttl"))
        self.assertEqual(before, fingerprint(self.package))

    def test_second_domain_joins_preserve_identity_and_decimal_boundary(self):
        sensor = self.copy_package("sensor")
        output = self.infer(package=sensor)
        inferred = read_graph(output / "result.ttl")
        yes = Literal(True, datatype=XSD.boolean)
        self.assertIn((SENSOR.atBoundary, SENSOR.requiresAttention, yes), inferred)
        self.assertIn((SENSOR.above, SENSOR.requiresAttention, yes), inferred)
        self.assertNotIn((SENSOR.below, SENSOR.requiresAttention, yes), inferred)
        self.assertNotIn((SENSOR.r1, SENSOR.requiresAttention, yes), inferred)

    def test_shacl_failure_stops_business_inference_and_keeps_report(self):
        output = self.root / "invalid-run"
        with self.assertRaises(ValidationError):
            core.infer_graph(self.package, facts=self.package / "tests/inputs/invalid.ttl", output=output)
        self.assertTrue((output / "execution.ttl").exists())
        execution = read_graph(output / "execution.ttl")
        self.assertIn((RUN, OT.status, Literal("failed")), execution)
        if (output / "result.ttl").exists():
            self.assertEqual(0, len(read_graph(output / "result.ttl")))
        shacl_reports = list(output.glob("*shacl*.ttl"))
        self.assertTrue(shacl_reports)
        self.assertTrue(any(Literal(False) in set(read_graph(path).objects(None, SH.conforms)) for path in shacl_reports))

    def test_execution_and_trace_bind_rule_input_and_engine(self):
        output = self.infer()
        execution = read_graph(output / "execution.ttl")
        self.assertIn((RUN, OT.status, Literal("passed")), execution)
        self.assertTrue(list(execution.objects(RUN, OT.engineDigest)))
        self.assertTrue(list(execution.objects(RUN, OT.profile)))
        trace = read_graph(output / "trace.ttl")
        self.assertTrue(list(trace.triples((None, None, PARCEL["rule-ready"]))))
        self.assertIn(PARCEL.ready, set(trace.objects(None, RDF.subject)))
        self.assertIn(PARCEL.ReadyParcel, set(trace.objects(None, RDF.object)))
        self.assertTrue((output / "manifest.sha256").exists())

    def test_repeated_runs_have_identical_semantic_artifacts(self):
        first = self.infer("first")
        second = self.infer("second")
        for filename in ("input.ttl", "result.ttl", "closure.ttl", "trace.ttl"):
            with self.subTest(artifact=filename):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

    def test_replay_uses_frozen_snapshot_after_original_model_changes(self):
        first = self.infer("first")
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\n<urn:test:changed> <urn:test:note> "changed after the run" .\n')
        replayed = core.replay_run(first, self.root / "replay")
        self.assertTrue(isomorphic(read_graph(first / "result.ttl"), read_graph(replayed / "replayed/result.ttl")))
        self.assertTrue(isomorphic(read_graph(first / "trace.ttl"), read_graph(replayed / "replayed/trace.ttl")))
        self.assertIn((RUN, OT.status, Literal("passed")), read_graph(replayed / "replay-report.ttl"))

    def test_replay_detects_tampered_output(self):
        first = self.infer()
        with (first / "result.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\n<urn:forged> <urn:forged> "injected" .\n')
        self.assert_rejected(core.replay_run, first, self.root / "replay")

    def test_replay_detects_extra_unmanifested_artifact(self):
        first = self.infer()
        (first / "extra.ttl").write_text("", encoding="utf-8")
        self.assert_rejected(core.replay_run, first, self.root / "replay")

    def test_replay_rejects_engine_fingerprint_mismatch(self):
        first = self.infer()
        execution = read_graph(first / "execution.ttl")
        execution.set((RUN, OT.engineDigest, Literal("0" * 64)))
        execution.serialize(first / "execution.ttl", format="turtle")
        # Rebuild the test manifest deliberately to reach the engine check,
        # rather than merely repeating the file-tamper rejection test.
        freeze(first)
        with self.assertRaisesRegex(ToolError, "fingerprint changed"):
            core.replay_run(first, self.root / "replay")

    def test_replay_rejects_dependency_version_mismatch(self):
        first = self.infer()
        execution = read_graph(first / "execution.ttl")
        dependency = next(node for node in execution.objects(RUN, OT.dependency)
                          if execution.value(node, OT.name) == Literal("rdflib"))
        execution.set((dependency, OT.version, Literal("0.0-test-incompatible")))
        execution.serialize(first / "execution.ttl", format="turtle")
        freeze(first)
        with self.assertRaisesRegex(ToolError, "versions differ"):
            core.replay_run(first, self.root / "replay")

    def test_replay_recomputes_result_even_with_rebuilt_manifest(self):
        first = self.infer()
        result = read_graph(first / "result.ttl")
        result.add((PARCEL.other, RDF.type, PARCEL.ReadyParcel))
        result.serialize(first / "result.ttl", format="turtle")
        freeze(first)
        replayed = core.replay_run(first, self.root / "replay")
        report = read_graph(replayed / "replay-report.ttl")
        self.assertIn((RUN, OT.status, Literal("failed")), report)
        self.assertIn(Literal(False), list(report.objects(None, OT.isomorphic)))

    def test_external_local_facts_are_snapshotted_for_replay(self):
        facts = self.root / "explicit-facts.ttl"
        facts.write_bytes((self.package / "inputs/facts.ttl").read_bytes())
        first = self.infer(facts=facts)
        facts.write_text("# old source no longer contains the data\n", encoding="utf-8")
        replayed = core.replay_run(first, self.root / "replay")
        self.assertTrue(isomorphic(read_graph(first / "result.ttl"), read_graph(replayed / "replayed/result.ttl")))

    def test_output_cannot_modify_package_or_existing_run(self):
        before = fingerprint(self.package)
        self.assert_rejected(core.infer_graph, self.package, output=self.package / "results")
        self.assertEqual(before, fingerprint(self.package))
        first = self.infer()
        saved = fingerprint(first)
        self.assert_rejected(core.infer_graph, self.package, output=first)
        self.assertEqual(saved, fingerprint(first))

    def test_remote_import_is_rejected_without_network_attempt(self):
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\n<urn:test:parcel:ontology> <http://www.w3.org/2002/07/owl#imports> <https://invalid.example/remote.ttl> .\n')
        self.assert_rejected(core.inspect_package, self.package)

    def test_rdfxml_external_entity_is_rejected_before_parsing(self):
        rules = self.package / "rules.swrl"
        content = rules.read_text(encoding="utf-8")
        content = content.replace('?>', '?>\n<!DOCTYPE rdf:RDF [<!ENTITY external SYSTEM "https://invalid.example/entity">]>', 1)
        rules.write_text(content, encoding="utf-8")
        self.assert_rejected(core.inspect_package, self.package)

    def test_unsupported_owl_expression_is_not_silently_ignored(self):
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\n<urn:test:parcel:ReadyParcel> <http://www.w3.org/2002/07/owl#complementOf> <urn:test:parcel:Parcel> .\n')
        self.assert_rejected(core.inspect_package, self.package)

    def test_unknown_swrl_builtin_is_rejected(self):
        sensor = self.copy_package("sensor")
        rules = sensor / "rules.swrl"
        rules.write_text(rules.read_text(encoding="utf-8").replace("#greaterThanOrEqual", "#sin"), encoding="utf-8")
        self.assert_rejected(core.inspect_package, sensor)

    def test_unbound_head_variable_is_rejected(self):
        rules = self.package / "rules.swrl"
        content = rules.read_text(encoding="utf-8")
        content = content.replace('<swrl:Variable rdf:about="urn:test:parcel:x"/>', '<swrl:Variable rdf:about="urn:test:parcel:x"/><swrl:Variable rdf:about="urn:test:parcel:unbound"/>')
        head, tail = content.split("<swrl:head", 1)
        content = head + "<swrl:head" + tail.replace('rdf:resource="urn:test:parcel:x"', 'rdf:resource="urn:test:parcel:unbound"')
        rules.write_text(content, encoding="utf-8")
        self.assert_rejected(core.inspect_package, self.package)

    def test_dynamic_facts_cannot_inject_schema_policy(self):
        with (self.package / "inputs/facts.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\nex:Parcel <http://www.w3.org/2000/01/rdf-schema#subClassOf> ex:ReadyParcel .\n')
        self.assert_rejected(core.inspect_package, self.package)
        self.assert_rejected(core.infer_graph, self.package, output=self.root / "injected")

    def test_dynamic_facts_swrl_definition_is_rejected_by_inspection(self):
        with (self.package / "inputs/facts.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\nex:injected a <http://www.w3.org/2003/11/swrl#Imp> .\n')
        self.assert_rejected(core.inspect_package, self.package)

    def test_rules_embedded_in_ontology_are_rejected_before_execution(self):
        # The current engine only executes the dedicated rules graph. Inspect
        # must reject misplaced definitions instead of passing a partial load.
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\nex:misplacedRule a <http://www.w3.org/2003/11/swrl#Imp> .\n')
        self.assert_rejected(core.inspect_package, self.package)

    def test_static_abox_can_still_live_in_ontology_file(self):
        # This is a role contract for dynamic inputs, not a claim that RDF/OWL
        # prohibit keeping a TBox and static ABox in the same physical file.
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\nex:staticParcel a ex:Parcel ; ex:identifier "P3" ; ex:tag "ready" .\n')
        output = self.infer()
        self.assertIn((PARCEL.staticParcel, RDF.type, PARCEL.ReadyParcel), read_graph(output / "result.ttl"))

    def test_static_blank_node_is_not_duplicated_by_post_validation(self):
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write('''
ex:Child a owl:Class .
ex:Container a owl:Class .
ex:child a owl:ObjectProperty .
ex:parent a ex:Container ; ex:child [ a ex:Child ] .
''')
        with (self.package / "shapes.ttl").open("a", encoding="utf-8") as stream:
            stream.write('''
ex:ParentShape a sh:NodeShape ; sh:targetNode ex:parent ;
  sh:property [ sh:path ex:child ; sh:minCount 1 ; sh:maxCount 1 ; sh:class ex:Child ] .
''')
        output = self.infer()
        closure = read_graph(output / "closure.ttl")
        self.assertEqual(1, len(list(closure.objects(PARCEL.parent, PARCEL.child))))
        self.assertIn(Literal(True), list(read_graph(output / "post-shacl-report.ttl").objects(None, SH.conforms)))

    def test_frozen_package_detects_changed_missing_and_extra_files(self):
        freeze(self.package)
        self.assertIsInstance(core.inspect_package(self.package), Graph)
        facts = self.package / "inputs/facts.ttl"
        original = facts.read_bytes()
        facts.write_bytes(original + b"\n# changed\n")
        self.assert_rejected(core.inspect_package, self.package)
        facts.write_bytes(original)
        facts.unlink()
        self.assert_rejected(core.inspect_package, self.package)
        facts.write_bytes(original)
        (self.package / "extra.txt").write_text("extra", encoding="utf-8")
        self.assert_rejected(core.inspect_package, self.package)

    def test_manifest_traversal_is_rejected(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        (self.package / "manifest.sha256").write_text(f"{digest}  ../outside.txt\n", encoding="utf-8")
        self.assert_rejected(core.inspect_package, self.package)

    def test_golden_suite_checks_positive_negative_and_invalid_input(self):
        output = core.run_cases(self.package, self.root / "cases")
        report = read_graph(output / "test-report.ttl")
        self.assertIn(Literal(2), list(report.objects(None, OT.total)))
        self.assertIn(Literal(2), list(report.objects(None, OT.passed)))
        self.assertIn(Literal(0), list(report.objects(None, OT.failed)))

    def test_golden_wrong_expectation_is_preserved_as_failure(self):
        cases = self.package / "tests/cases.ttl"
        cases.write_text(cases.read_text(encoding="utf-8").replace("rdf:object ex:ReadyParcel", "rdf:object ex:NeverDerived"), encoding="utf-8")
        output = core.run_cases(self.package, self.root / "cases")
        report = read_graph(output / "test-report.ttl")
        self.assertTrue(any(int(count) > 0 for count in report.objects(None, OT.failed)))
        self.assertIn(Literal("failed"), list(report.objects(None, OT.status)))
        self.assertFalse(list(report.objects(None, OT.coveredRule)))

    def test_golden_preseeded_answer_does_not_count_as_inference(self):
        facts = self.package / "tests/inputs/positive.ttl"
        with facts.open("a", encoding="utf-8") as stream:
            stream.write("\nex:ready a ex:ReadyParcel .\n")
        output = core.run_cases(self.package, self.root / "cases")
        report = read_graph(output / "test-report.ttl")
        self.assertTrue(any(int(count) > 0 for count in report.objects(None, OT.failed)))

    def test_golden_must_stop_flag_cannot_be_ignored_on_conforming_case(self):
        cases = self.package / "tests/cases.ttl"
        with cases.open("a", encoding="utf-8") as stream:
            stream.write('\nex:positive meta:reasoningMustStop true .\n')
        output = core.run_cases(self.package, self.root / "cases")
        report = read_graph(output / "test-report.ttl")
        self.assertIn((PARCEL.positive, OT.status, Literal("failed")), report)

    def test_case_path_traversal_is_rejected(self):
        cases = self.package / "tests/cases.ttl"
        cases.write_text(cases.read_text(encoding="utf-8").replace('"inputs/positive.ttl"', '"../../outside.ttl"'), encoding="utf-8")
        output = core.run_cases(self.package, self.root / "cases")
        report = read_graph(output / "test-report.ttl")
        self.assertIn((PARCEL.positive, OT.status, Literal("failed")), report)
        self.assertIn("Unsafe relative path", str(report.value(PARCEL.positive, OT.detail)))

    def test_query_uses_saved_closure_and_allows_service_word_in_literal(self):
        output = self.infer()
        query = self.root / "local.rq"
        query.write_text('SELECT ?parcel ("SERVICE" AS ?label) WHERE { ?parcel a <urn:test:parcel:ReadyParcel> }', encoding="utf-8")
        queried = core.query_graph(output / "closure.ttl", query, self.root / "query")
        rows = (queried / "query-result.tsv").read_text(encoding="utf-8")
        self.assertIn("<urn:test:parcel:ready>", rows)
        self.assertNotIn("<urn:test:parcel:other>", rows)
        self.assertIn("SERVICE", rows)
        self.assertIn((RUN, OT.rowCount, Literal(1)), read_graph(queried / "execution.ttl"))

    def test_query_ask_records_false_without_claiming_owl_negation(self):
        output = self.infer()
        query = self.root / "ask.rq"
        query.write_text('ASK { <urn:test:parcel:other> a <urn:test:parcel:ReadyParcel> }', encoding="utf-8")
        queried = core.query_graph(output / "closure.ttl", query, self.root / "query")
        self.assertIn((RUN, OT.askResult, Literal(False)), read_graph(queried / "query-result.ttl"))

    def test_query_optional_bound_returns_positive_and_negative_boolean_rows(self):
        output = self.infer()
        query = self.root / "optional-bound.rq"
        query.write_text('''
PREFIX ex: <urn:test:parcel:>
SELECT ?parcel (BOUND(?readyType) AS ?isReady)
WHERE {
  ?parcel a ex:Parcel .
  OPTIONAL {
    ?parcel a ?readyType .
    FILTER(?readyType = ex:ReadyParcel)
  }
}
ORDER BY ?parcel
''', encoding="utf-8")
        queried = core.query_graph(output / "closure.ttl", query, self.root / "query")
        with (queried / "query-result.tsv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(2, len(rows))
        actual = {from_n3(row["parcel"]): from_n3(row["isReady"]) for row in rows}
        self.assertEqual({PARCEL.ready: Literal(True), PARCEL.other: Literal(False)}, actual)

    def test_query_output_cannot_write_to_input_package_ancestor(self):
        query = self.root / "local-input.rq"
        query.write_text("SELECT * WHERE { ?s ?p ?o }", encoding="utf-8")
        before = fingerprint(self.package)
        self.assert_rejected(
            core.query_graph, self.package / "inputs/facts.ttl", query,
            self.package / "new-query-output",
        )
        self.assertEqual(before, fingerprint(self.package))

    def test_query_checks_frozen_manifest_in_input_ancestor(self):
        freeze(self.package)
        with (self.package / "ontology.ttl").open("a", encoding="utf-8") as stream:
            stream.write("\n# The package was changed after freezing.\n")
        query = self.root / "frozen-input.rq"
        query.write_text("SELECT * WHERE { ?s ?p ?o }", encoding="utf-8")
        self.assert_rejected(
            core.query_graph, self.package / "inputs/facts.ttl", query,
            self.root / "external-query-output",
        )

    def test_query_output_cannot_modify_separate_frozen_query_package(self):
        query_package = self.copy_package("sensor")
        (query_package / "queries").mkdir()
        query = query_package / "queries/read.rq"
        query.write_text("SELECT * WHERE { ?s ?p ?o }", encoding="utf-8")
        freeze(query_package)
        before = fingerprint(query_package)
        self.assert_rejected(
            core.query_graph, self.package / "inputs/facts.ttl", query,
            query_package / "new-query-output",
        )
        self.assertEqual(before, fingerprint(query_package))

    def test_post_validation_rejects_inferred_graph_and_keeps_unaccepted_result(self):
        with (self.package / "shapes.ttl").open("a", encoding="utf-8") as stream:
            stream.write('''
ex:DerivedShape a sh:NodeShape ; sh:targetClass ex:ReadyParcel ;
  sh:property [ sh:path ex:dispatchConfirmation ; sh:minCount 1 ] .
''')
        out = self.root / "post-invalid"
        with self.assertRaises(ValidationError):
            core.infer_graph(self.package, output=out)
        self.assertTrue((out / "result.ttl").exists())
        report = read_graph(out / "execution.ttl")
        self.assertIn((RUN, OT.status, Literal("failed")), report)
        self.assertIn((RUN, OT.stage, Literal("post-validation")), report)

    def test_explicit_post_validation_can_use_inferred_property(self):
        sensor = self.copy_package("sensor")
        with (sensor / "shapes.ttl").open("a", encoding="utf-8") as stream:
            stream.write('''
ex:ExpectedDerivedShape a sh:NodeShape ; sh:targetNode ex:atBoundary ;
  sh:property [ sh:path ex:requiresAttention ; sh:hasValue true ] .
''')
        (sensor / "runtime.ttl").write_text('''
@prefix ot: <https://w3id.org/ontology-tools#> .
<urn:runtime> a ot:Runtime ; ot:profile "local-rules-v1" ; ot:validationOrder "post" .
''', encoding="utf-8")
        output = self.infer(package=sensor)
        self.assertFalse((output / "shacl-report.ttl").exists())
        self.assertIn(Literal(True), set(read_graph(output / "post-shacl-report.ttl").objects(None, SH.conforms)))

    def test_iteration_limit_is_failure_not_partial_success(self):
        (self.package / "runtime.ttl").write_text('''
@prefix ot: <https://w3id.org/ontology-tools#> .
<urn:runtime> a ot:Runtime ; ot:profile "local-rules-v1" ; ot:maxIterations 1 .
''', encoding="utf-8")
        out = self.root / "limited"
        self.assert_rejected(core.infer_graph, self.package, output=out)
        self.assertIn((RUN, OT.status, Literal("failed")), read_graph(out / "execution.ttl"))

    def test_cli_exit_codes_distinguish_success_and_invalid_input(self):
        def run_cli(*args):
            return subprocess.run(
                [sys.executable, "-B", "-X", "utf8", "-m", "ontology_tools", *map(str, args)],
                cwd=TOOL_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
        inspected = run_cli("inspect", "--package", self.package, "--output", self.root / "cli-inspect")
        self.assertEqual(0, inspected.returncode, inspected.stdout + inspected.stderr)
        invalid = run_cli("infer", "--package", self.package, "--facts", self.package / "tests/inputs/invalid.ttl", "--output", self.root / "cli-invalid")
        self.assertEqual(3, invalid.returncode, invalid.stdout + invalid.stderr)

    def test_sparql_service_is_rejected_before_network_access(self):
        output = self.infer()
        query = self.root / "remote.rq"
        query.write_text('SELECT * WHERE { SERVICE <https://invalid.example/sparql> { ?s ?p ?o } }', encoding="utf-8")
        self.assert_rejected(core.query_graph, output / "closure.ttl", query, self.root / "query")

    def test_sparql_from_remote_dataset_is_rejected(self):
        output = self.infer()
        query = self.root / "remote-dataset.rq"
        query.write_text('SELECT * FROM <https://invalid.example/remote.ttl> WHERE { ?s ?p ?o }', encoding="utf-8")
        self.assert_rejected(core.query_graph, output / "closure.ttl", query, self.root / "query")

    def test_shacl_service_cannot_bypass_offline_policy(self):
        shapes = self.package / "shapes.ttl"
        with shapes.open("a", encoding="utf-8") as stream:
            stream.write('''
ex:NetworkShape a sh:NodeShape ; sh:targetClass ex:Parcel ;
  sh:sparql [ sh:select "SELECT $this WHERE { SERVICE <https://invalid.example/sparql> { $this ?p ?o } }" ] .
''')
        self.assert_rejected(core.inspect_package, self.package)

    def test_unknown_reserved_shacl_extension_is_not_silently_ignored(self):
        with (self.package / "shapes.ttl").open("a", encoding="utf-8") as stream:
            stream.write('\nex:ParcelShape sh:expression [ sh:count ( ex:identifier ) ] .\n')
        self.assert_rejected(core.inspect_package, self.package)


if __name__ == "__main__":
    unittest.main()
