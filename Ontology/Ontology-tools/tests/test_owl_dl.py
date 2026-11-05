"""Independent OWL 2 DL acceptance cases, executed by the real HermiT backend.

Run from Ontology-tools:
    python -B -m unittest discover -s tests -p test_owl_dl.py -v
Use ONTOLOGY_DL_JAVA only to select an already installed local Java executable.
The tests never install dependencies or retrieve imported ontologies.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF

from ontology_tools.io import ToolError, verify_manifest
from ontology_tools.owl_dl import check_consistency


HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
FIXTURES = HERE / "fixtures" / "owl_dl"
EX = Namespace("urn:test:owl-dl:")
OT = Namespace("https://w3id.org/ontology-tools#")
JAVA = os.environ.get("ONTOLOGY_DL_JAVA", "java")


def fingerprint(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*") if path.is_file()
    }


def rdf(path: Path) -> Graph:
    return Graph().parse(path, format="turtle")


class OWLDLAcceptance(unittest.TestCase):
    def setUp(self):
        # Keep subprocess inputs in the writable workspace: some Windows
        # sandboxes let Python create user-Temp files that Java cannot read.
        # Evidence must also stay outside the protected tool installation.
        self.scratch = tempfile.TemporaryDirectory(prefix="ontology-dl-acceptance-", dir=TOOL_ROOT.parent.parent)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.inputs = self.root / "inputs"
        shutil.copytree(FIXTURES, self.inputs)
        self.before = fingerprint(self.inputs)
        self.network_guards = []
        for target in ("socket.create_connection", "urllib.request.urlopen"):
            guard = patch(target, side_effect=AssertionError("OWL DL tests forbid network access"))
            self.network_guards.append(guard.start())
            self.addCleanup(guard.stop)

    def tearDown(self):
        self.assertEqual(self.before, fingerprint(self.inputs), "Checking must not modify source files")
        for guard in self.network_guards:
            guard.assert_not_called()
        forbidden = [p for p in self.root.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".ndjson"}]
        self.assertEqual([], forbidden, "OWL DL checks must preserve the native RDF evidence format")

    def require_java(self):
        if not (Path(JAVA).is_file() or shutil.which(JAVA)):
            self.skipTest("Real HermiT integration requires local Java; set ONTOLOGY_DL_JAVA")

    def check(self, name: str, run="run", **kwargs) -> Path:
        self.require_java()
        output = self.root / run
        result = check_consistency(self.inputs / name, output, java=JAVA, **kwargs)
        self.assertEqual(output.resolve(), result.resolve())
        self.assertTrue(verify_manifest(output, required=True))
        return output

    def assert_result(self, output: Path, consistent: bool, unsatisfiable=(), status=None):
        report = rdf(output / "report.ttl")
        reports = set(report.subjects(RDF.type, OT.OWLConsistencyReport))
        self.assertEqual(1, len(reports), "One run must have exactly one OWL consistency result")
        subject = next(iter(reports))
        self.assertEqual({Literal(consistent)}, set(report.objects(subject, OT.consistent)))
        self.assertEqual({Literal(True)}, set(report.objects(subject, OT.profileConforms)))
        actual_unsatisfiable = set(report.objects(subject, OT.unsatisfiableClass))
        self.assertNotIn(OWL.Nothing, actual_unsatisfiable)
        if consistent:
            self.assertEqual(set(unsatisfiable), actual_unsatisfiable,
                             "Compare every unsatisfiable class, not only one example member")
        else:
            self.assertEqual(set(), actual_unsatisfiable,
                             "An inconsistent ontology must not expose a fabricated classification result")
        expected_status = status or ("passed" if consistent and not unsatisfiable else "nonconformant")
        execution = rdf(output / "execution.ttl")
        self.assertEqual({Literal(expected_status)}, set(execution.objects(None, OT.status)))
        self.assertTrue((output / "manifest.sha256").is_file())

    def assert_failed_without_verdict(self, output: Path):
        self.assertTrue((output / "execution.ttl").is_file(), "Failures must retain execution evidence")
        execution = rdf(output / "execution.ttl")
        self.assertEqual({Literal("failed")}, set(execution.objects(None, OT.status)))
        # An evidence run may preserve a deliberately malformed raw input file;
        # verdicts belong to generated reports, not arbitrary source snapshots.
        for filename in ("report.ttl", "execution.ttl"):
            path = output / filename
            if path.exists():
                self.assertEqual(set(), set(rdf(path).objects(None, OT.consistent)),
                                 f"A failed run cannot make an OWL consistency claim: {path.name}")

    def test_consistent_model_has_no_unsatisfiable_named_classes(self):
        self.assert_result(self.check("consistent.ttl"), True)

    def inline_model(self, body, name="inline"):
        path = self.root / (name + ".ttl")
        path.write_text(
            '@prefix ex: <urn:test:owl-dl:> .\n'
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n'
            '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
            '@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'
            'ex:model a owl:Ontology .\n' + body, encoding="utf-8")
        return path

    def check_inline(self, body, consistent, unsatisfiable=()):
        self.require_java()
        source = self.inline_model(body)
        before = source.read_bytes()
        output = self.root / "inline-run"
        check_consistency(source, output, java=JAVA)
        self.assert_result(output, consistent, unsatisfiable)
        self.assertEqual(before, source.read_bytes())

    def test_union_and_intersection_class_lists_are_loaded(self):
        self.check_inline('''
            ex:A a owl:Class . ex:B a owl:Class .
            ex:Union a owl:Class; owl:equivalentClass [a owl:Class; owl:unionOf (ex:A ex:B)] .
            ex:Both a owl:Class; owl:equivalentClass [a owl:Class; owl:intersectionOf (ex:A ex:B)] .
            ex:x a owl:NamedIndividual, ex:Both .
        ''', True)

    def test_union_semantics_participate_in_inconsistency(self):
        self.check_inline('''
            ex:A a owl:Class . ex:B a owl:Class .
            ex:Union a owl:Class; owl:equivalentClass [a owl:Class; owl:unionOf (ex:A ex:B)] .
            ex:Neither a owl:Class; owl:disjointWith ex:A, ex:B .
            ex:x a owl:NamedIndividual, ex:Union, ex:Neither .
        ''', False)

    def test_intersection_semantics_identify_unsatisfiable_class(self):
        self.check_inline('''
            ex:A a owl:Class; owl:disjointWith ex:B . ex:B a owl:Class .
            ex:Impossible a owl:Class; owl:equivalentClass [a owl:Class; owl:intersectionOf (ex:A ex:B)] .
        ''', True, {EX.Impossible})

    def test_nominal_enumeration_accepts_member(self):
        self.check_inline('''
            ex:Choice a owl:Class; owl:equivalentClass [a owl:Class; owl:oneOf (ex:one ex:two)] .
            ex:one a owl:NamedIndividual, ex:Choice . ex:two a owl:NamedIndividual .
        ''', True)

    def test_nominal_enumeration_rejects_explicitly_different_nonmember(self):
        self.check_inline('''
            ex:Choice a owl:Class; owl:equivalentClass [a owl:Class; owl:oneOf (ex:one ex:two)] .
            ex:one a owl:NamedIndividual . ex:two a owl:NamedIndividual .
            ex:x a owl:NamedIndividual, ex:Choice; owl:differentFrom ex:one, ex:two .
        ''', False)

    def test_literal_enumeration_is_not_confused_with_resource_list(self):
        self.check_inline('''
            ex:p a owl:DatatypeProperty; rdfs:range [a rdfs:Datatype; owl:oneOf ("a" "b")] .
            ex:x a owl:NamedIndividual; ex:p "b" .
        ''', True)

    def test_literal_enumeration_rejects_outside_value(self):
        self.check_inline('''
            ex:p a owl:DatatypeProperty; rdfs:range [a rdfs:Datatype; owl:oneOf ("a" "b")] .
            ex:x a owl:NamedIndividual; ex:p "c" .
        ''', False)

    def test_nested_all_values_from_union_uses_complete_declarations(self):
        self.check_inline('''
            ex:X a owl:Class; rdfs:subClassOf [a owl:Restriction; owl:onProperty ex:p;
                owl:allValuesFrom [a owl:Class; owl:unionOf (ex:A ex:B)]] .
            ex:x a owl:NamedIndividual, ex:X; ex:p ex:y .
            ex:y a owl:NamedIndividual, ex:Neither .
            ex:Neither a owl:Class; owl:disjointWith ex:A, ex:B .
            ex:A a owl:Class . ex:B a owl:Class . ex:p a owl:ObjectProperty .
        ''', False)

    def test_bad_rdf_lists_fail_without_a_semantic_verdict(self):
        self.require_java()
        bodies = (
            '_:l rdf:first ex:A .',
            '_:l rdf:rest rdf:nil .',
            '_:l rdf:first ex:A; rdf:rest "invalid" .',
            '_:l rdf:first ex:A, ex:B; rdf:rest rdf:nil .',
            '_:l rdf:first ex:A, "mixed"; rdf:rest rdf:nil .',
            '_:l rdf:first ex:A; rdf:rest _:l .',
            '_:l rdf:first ex:A; rdf:rest _:tail .',
        )
        for index, tail in enumerate(bodies):
            with self.subTest(list_shape=index):
                source = self.inline_model('''
                    ex:A a owl:Class . ex:B a owl:Class .
                    ex:Union a owl:Class; owl:equivalentClass [a owl:Class; owl:unionOf _:l] .
                ''' + tail, f"bad-list-{index}")
                output = self.root / f"bad-list-run-{index}"
                with self.assertRaises(ToolError):
                    check_consistency(source, output, java=JAVA)
                self.assert_failed_without_verdict(output)

    def test_list_compatibility_does_not_invent_missing_class_declaration(self):
        self.require_java()
        source = self.inline_model('''
            ex:A a owl:Class .
            ex:Union a owl:Class; owl:equivalentClass [a owl:Class; owl:unionOf (ex:A ex:Undeclared)] .
        ''')
        output = self.root / "undeclared-list-run"
        with self.assertRaises(ToolError):
            check_consistency(source, output, java=JAVA)
        self.assert_failed_without_verdict(output)

    def shared_tail_model(self):
        return '''
            ex:A a owl:Class; owl:disjointWith ex:B .
            ex:C a owl:Class; owl:disjointWith ex:B .
            ex:B a owl:Class . ex:D a owl:Class . ex:E a owl:Class .
            ex:I a owl:Class; owl:equivalentClass [a owl:Class; owl:intersectionOf _:l] .
            ex:J a owl:Class; owl:equivalentClass [a owl:Class; owl:intersectionOf _:k] .
            _:l rdf:first ex:C; rdf:rest _:l2 . _:l2 rdf:first ex:D; rdf:rest _:m .
            _:k rdf:first ex:A; rdf:rest _:k2 . _:k2 rdf:first ex:E; rdf:rest _:m .
            _:m rdf:first ex:B; rdf:rest rdf:nil .
        '''

    def test_shared_resource_list_tail_preserves_every_conjunct(self):
        self.check_inline(self.shared_tail_model(), True, {EX.I, EX.J})

    def test_shared_tail_must_not_hide_global_inconsistency(self):
        self.check_inline(self.shared_tail_model() + '''
            ex:U a owl:Class; owl:equivalentClass [a owl:Class; owl:unionOf (ex:I ex:J)] .
            ex:x a owl:NamedIndividual, ex:U .
        ''', False)

    def test_shared_literal_list_tail_preserves_every_value(self):
        self.check_inline('''
            ex:p a owl:DatatypeProperty; rdfs:range [a rdfs:Datatype; owl:oneOf _:l] .
            ex:q a owl:DatatypeProperty; rdfs:range [a rdfs:Datatype; owl:oneOf _:k] .
            _:l rdf:first "red"; rdf:rest _:m .
            _:k rdf:first "blue"; rdf:rest _:m .
            _:m rdf:first "shared-one"; rdf:rest _:n .
            _:n rdf:first "shared-two"; rdf:rest rdf:nil .
            ex:x a owl:NamedIndividual; ex:p "shared-two"; ex:q "shared-two" .
        ''', True)

    def test_mixed_literal_resource_enumeration_cannot_be_silently_truncated(self):
        self.require_java()
        for index, members in enumerate(('"a" ex:B', 'ex:B "a"')):
            with self.subTest(order=index):
                source = self.inline_model('''
                    ex:B a owl:NamedIndividual .
                    ex:p a owl:DatatypeProperty; rdfs:range [a rdfs:Datatype; owl:oneOf ('''
                    + members + ''')] .
                    ex:x a owl:NamedIndividual; ex:p "a" .
                ''', f"mixed-enum-{index}")
                output = self.root / f"mixed-enum-run-{index}"
                with self.assertRaises(ToolError):
                    check_consistency(source, output, java=JAVA)
                self.assert_failed_without_verdict(output)

    def test_unsatisfiable_classes_do_not_make_empty_tbox_inconsistent(self):
        self.assert_result(self.check("unsatisfiable_classes.ttl"), True,
                           {EX.Impossible, EX.AlsoImpossible}, "nonconformant")

    def test_inherited_disjoint_types_make_existing_individual_inconsistent(self):
        self.assert_result(self.check("inherited_conflict.ttl"), False)

    def test_equivalent_class_implication_is_checked(self):
        self.assert_result(self.check("equivalent_conflict.ttl"), False)

    def test_qualified_cardinality_with_distinct_fillers_is_inconsistent(self):
        self.assert_result(self.check("cardinality_conflict.ttl"), False)

    def test_distinct_iris_do_not_imply_distinct_individuals(self):
        self.assert_result(self.check("cardinality_without_difference.ttl"), True)

    def test_separate_facts_participate_in_global_consistency(self):
        self.assert_result(self.check("consistent.ttl", facts=self.inputs / "extra_facts.ttl"), False)

    def test_multiple_model_files_and_fact_lists_are_supported(self):
        self.require_java()
        output = self.root / "run"
        check_consistency([self.inputs / "consistent.ttl", self.inputs / "unsatisfiable_classes.ttl"],
                          output, facts=[self.inputs / "extra_facts.ttl"], java=JAVA)
        self.assert_result(output, False)

    def test_full_local_import_closure_affects_verdict(self):
        self.assert_result(self.check("imports/root.ttl", imports=self.inputs / "imports/mapping.ttl"), False)

    def test_unmapped_import_is_rejected_before_java_without_network(self):
        output = self.root / "run"
        with patch("subprocess.run") as launch:
            with self.assertRaises(ToolError):
                check_consistency(self.inputs / "imports/root.ttl", output, java=JAVA)
            launch.assert_not_called()
        self.assert_failed_without_verdict(output)

    def test_missing_transitive_import_mapping_is_rejected(self):
        mapping = self.root / "incomplete-mapping.ttl"
        mapping.write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> .\n'
            '[] a ot:ImportMapping; ot:ontologyIRI <https://example.invalid/owl-dl/branch>; '
            'ot:path "inputs/imports/branch.ttl" .\n', encoding="utf-8")
        output = self.root / "run"
        with patch("subprocess.run") as launch:
            with self.assertRaises(ToolError):
                check_consistency(self.inputs / "imports/root.ttl", output, imports=mapping, java=JAVA)
            launch.assert_not_called()
        self.assert_failed_without_verdict(output)

    def test_import_mapping_cannot_escape_its_directory(self):
        mapping_root = self.root / "mapping"
        mapping_root.mkdir()
        mapping = mapping_root / "mapping.ttl"
        mapping.write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> .\n'
            '[] a ot:ImportMapping; ot:ontologyIRI <https://example.invalid/owl-dl/branch>; '
            'ot:path "../inputs/imports/branch.ttl" .\n', encoding="utf-8")
        output = self.root / "run"
        with self.assertRaises(ToolError):
            check_consistency(self.inputs / "imports/root.ttl", output, imports=mapping, java=JAVA)
        self.assert_failed_without_verdict(output)

    def test_import_mapping_must_match_declared_ontology_iri(self):
        mapping = self.root / "wrong-iri.ttl"
        mapping.write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> .\n'
            '[] a ot:ImportMapping; ot:ontologyIRI <https://example.invalid/owl-dl/branch>; '
            'ot:path "inputs/imports/leaf.ttl" .\n', encoding="utf-8")
        output = self.root / "run"
        with self.assertRaises(ToolError):
            check_consistency(self.inputs / "imports/root.ttl", output, imports=mapping, java=JAVA)
        self.assert_failed_without_verdict(output)

    def test_non_simple_role_cardinality_fails_owl2dl_profile(self):
        self.require_java()
        output = self.root / "run"
        with self.assertRaises(ToolError):
            check_consistency(self.inputs / "outside_profile.ttl", output, java=JAVA)
        self.assert_failed_without_verdict(output)
        report = rdf(output / "report.ttl")
        self.assertEqual({Literal(False)}, set(report.objects(None, OT.profileConforms)))

    def test_swrl_is_explicitly_rejected_before_reasoning(self):
        output = self.root / "run"
        with patch("subprocess.run") as launch:
            with self.assertRaisesRegex(ToolError, "(?i)swrl"):
                check_consistency(self.inputs / "with_swrl.ttl", output, java=JAVA)
            launch.assert_not_called()
        self.assert_failed_without_verdict(output)

    def test_malformed_rdf_is_failure_not_consistency(self):
        output = self.root / "run"
        with self.assertRaises(ToolError):
            check_consistency(self.inputs / "invalid.ttl", output, java=JAVA)
        self.assert_failed_without_verdict(output)

    def test_timeout_does_not_emit_a_consistency_verdict(self):
        output = self.root / "run"
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired([JAVA], 0.01)) as launch:
            with self.assertRaisesRegex(ToolError, "(?i)timed out"):
                check_consistency(self.inputs / "consistent.ttl", output, java=JAVA, timeout=0.01)
            launch.assert_called_once()
        self.assert_failed_without_verdict(output)

    def test_missing_java_does_not_emit_a_consistency_verdict(self):
        output = self.root / "run"
        missing_java = str(self.root / "java-not-installed")
        with self.assertRaisesRegex(ToolError, "(?i)(java-not-installed|WinError 2|No such file)"):
            check_consistency(self.inputs / "consistent.ttl", output, java=missing_java)
        self.assert_failed_without_verdict(output)

    def test_incomplete_or_contradictory_bridge_output_cannot_be_a_verdict(self):
        valid_prefix = (
            "PROTOCOL\towl-dl-v1\nOWLAPI\t4.5.29\nAXIOMS\t0\nLOGICAL_AXIOMS\t0\n"
            "PROFILE\ttrue\nREASONER\tHermiT\nVERSION\t1.4.1.432\n"
        )
        for index, (stdout, returncode) in enumerate((
            (valid_prefix + "CONSISTENT\ttrue\n", 0),
            (valid_prefix + "CONSISTENT\ttrue\nCONSISTENT\tfalse\nEND\towl-dl-v1\n", 0),
            (valid_prefix + "CONSISTENT\ttrue\nEND\towl-dl-v1\n", 2),
        )):
            with self.subTest(case=index):
                output = self.root / f"protocol-{index}"
                process = subprocess.CompletedProcess([JAVA], returncode, stdout, "")
                with patch("subprocess.run", return_value=process) as launch:
                    with self.assertRaises(ToolError):
                        check_consistency(self.inputs / "consistent.ttl", output, java=JAVA)
                    launch.assert_called_once()
                self.assert_failed_without_verdict(output)

    def test_existing_output_is_rejected_without_overwrite(self):
        output = self.root / "run"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("prior evidence", encoding="utf-8")
        with self.assertRaises(ToolError):
            check_consistency(self.inputs / "consistent.ttl", output, java=JAVA)
        self.assertEqual({"keep.txt": hashlib.sha256(b"prior evidence").hexdigest()}, fingerprint(output))

    def test_encoded_xml_literal_doctype_is_rejected_before_java(self):
        source = self.root / "encoded-xml.ttl"
        source.write_text(
            '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n'
            '<urn:subject> <urn:property> "\\u003C!DOCTYPE x []><x/>"^^rdf:XMLLiteral .\n',
            encoding="utf-8")
        output = self.root / "run"
        with patch("subprocess.run") as launch:
            with self.assertRaisesRegex(ToolError, "(?i)(DTD|entities)"):
                check_consistency(source, output, java=JAVA)
            launch.assert_not_called()
        self.assert_failed_without_verdict(output)

    def test_output_cannot_be_created_inside_a_recursively_imported_native_package(self):
        native = self.root / "native"
        (native / "integration").mkdir(parents=True)
        (native / "integration/load-plan.ttl").write_text("# Native package marker\n", encoding="utf-8")
        (native / "model.ttl").write_text(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '<urn:test:imported> a owl:Ontology .\n', encoding="utf-8")
        entry = self.root / "entry.ttl"
        entry.write_text(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '<urn:test:entry> a owl:Ontology; owl:imports <urn:test:imported> .\n', encoding="utf-8")
        mapping = self.root / "map.ttl"
        mapping.write_text(
            '@prefix ot: <https://w3id.org/ontology-tools#> .\n'
            '[] a ot:ImportMapping; ot:ontologyIRI <urn:test:imported>; ot:path "native/model.ttl" .\n', encoding="utf-8")
        before = fingerprint(native)
        output = native / "unexpected-run"
        with self.assertRaisesRegex(ToolError, "(?i)outside"):
            check_consistency(entry, output, imports=mapping, java=JAVA)
        self.assertFalse(output.exists())
        self.assertEqual(before, fingerprint(native))

    def test_repeated_runs_preserve_semantic_result(self):
        first = self.check("unsatisfiable_classes.ttl", "first")
        second = self.check("unsatisfiable_classes.ttl", "second")
        for output in (first, second):
            self.assert_result(output, True, {EX.Impossible, EX.AlsoImpossible}, "nonconformant")

    def test_evidence_binds_complete_import_closure_runtime_and_actual_command(self):
        output = self.check("imports/root.ttl", imports=self.inputs / "imports/mapping.ttl")
        execution = rdf(output / "execution.ttl")
        sources = set(execution.objects(None, OT.input))
        expected = {self.inputs / "imports" / name for name in ("root.ttl", "branch.ttl", "leaf.ttl", "mapping.ttl")}
        actual = set()
        for source in sources:
            source_paths = set(execution.objects(source, OT.sourcePath))
            snapshots = set(execution.objects(source, OT.snapshot))
            digests = set(execution.objects(source, OT.sha256))
            self.assertEqual(1, len(source_paths))
            self.assertEqual(1, len(snapshots))
            self.assertEqual(1, len(digests))
            source_path = Path(str(next(iter(source_paths))))
            actual.add(source_path)
            snapshot = output / str(next(iter(snapshots)))
            self.assertTrue(snapshot.resolve().is_relative_to(output.resolve()))
            self.assertEqual(source_path.read_bytes(), snapshot.read_bytes())
            self.assertEqual({Literal(hashlib.sha256(source_path.read_bytes()).hexdigest())}, digests)
        self.assertEqual({p.resolve() for p in expected}, {p.resolve() for p in actual})
        self.assertEqual({Literal("HermiT")}, set(execution.objects(None, OT.reasoner)))
        self.assertTrue(set(execution.objects(None, OT.reasonerVersion)))
        self.assertTrue(set(execution.objects(None, OT.owlapiVersion)))
        self.assertEqual({Literal(0)}, set(execution.objects(None, OT.javaExitCode)))
        runtime_bytes = (output / "runtime.sha256").read_bytes()
        self.assertEqual({Literal(hashlib.sha256(runtime_bytes).hexdigest())},
                         set(execution.objects(None, OT.runtimeDigest)))
        command = (output / "command.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(JAVA, command[0])
        self.assertIn("OwlDlCheck", command)
        self.assertEqual((output / "assembled.rdf").resolve(), Path(command[-1]).resolve())
        self.assertFalse(list(Graph().parse(output / "assembled.rdf", format="xml").triples((None, OWL.imports, None))))

    def test_cli_returns_distinct_completion_nonconformance_and_error_codes(self):
        self.require_java()
        for filename, expected_code in (
            ("consistent.ttl", 0),
            ("unsatisfiable_classes.ttl", 1),
            ("inherited_conflict.ttl", 1),
            ("outside_profile.ttl", 2),
            ("with_swrl.ttl", 2),
            ("invalid.ttl", 2),
        ):
            with self.subTest(input=filename):
                output = self.root / f"cli-{Path(filename).stem}"
                completed = subprocess.run(
                    [sys.executable, "-B", "-X", "utf8", "-m", "ontology_tools", "owl-dl",
                     "--ontology", str(self.inputs / filename), "--output", str(output),
                     "--java", JAVA, "--timeout", "60"],
                    cwd=TOOL_ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90,
                )
                self.assertEqual(expected_code, completed.returncode,
                                 f"stdout={completed.stdout}\nstderr={completed.stderr}")
                if expected_code == 2:
                    self.assert_failed_without_verdict(output)

    def test_cli_repeated_ontology_and_fact_flags_include_all_inputs(self):
        self.require_java()
        output = self.root / "cli-multiple"
        completed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-m", "ontology_tools", "owl-dl",
             "--ontology", str(self.inputs / "consistent.ttl"),
             "--ontology", str(self.inputs / "unsatisfiable_classes.ttl"),
             "--facts", str(self.inputs / "extra_facts.ttl"),
             "--output", str(output), "--java", JAVA],
            cwd=TOOL_ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90,
        )
        self.assertEqual(1, completed.returncode,
                         f"stdout={completed.stdout}\nstderr={completed.stderr}")
        self.assert_result(output, False)

    def test_document_relative_classes_match_absolute_references_in_separate_facts(self):
        self.require_java()
        source_root = self.root / "relative-sources"
        source_root.mkdir()
        ontology = source_root / "source.ttl"
        facts = source_root / "facts.ttl"
        ontology.write_text(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '<urn:test:owl-dl:relative-source> a owl:Ontology .\n'
            '<#A> a owl:Class; owl:disjointWith <#B> .\n'
            '<#B> a owl:Class .\n', encoding="utf-8")
        facts.write_text(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            f'<urn:test:owl-dl:relative-instance> a owl:NamedIndividual, <{ontology.as_uri()}#A>, <{ontology.as_uri()}#B> .\n',
            encoding="utf-8")
        output = self.root / "relative-run"
        check_consistency(ontology, output, facts=facts, java=JAVA)
        self.assert_result(output, False)
        execution = rdf(output / "execution.ttl")
        for path in (ontology, facts):
            source_nodes = set(execution.subjects(OT.sourcePath, Literal(str(path))))
            self.assertEqual(1, len(source_nodes))
            self.assertEqual({URIRef(path.as_uri())},
                             set(execution.objects(next(iter(source_nodes)), OT.documentBase)))

    def test_same_relative_class_fragment_in_distinct_documents_stays_distinct(self):
        self.require_java()
        source_root = self.root / "independent-bases"
        source_root.mkdir()
        first = source_root / "first.ttl"
        second = source_root / "second.ttl"
        prefix = '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
        first.write_text(
            prefix + '<urn:test:owl-dl:first> a owl:Ontology .\n'
            '<#C> a owl:Class; owl:disjointWith <urn:test:owl-dl:D> .\n'
            '<urn:test:owl-dl:D> a owl:Class .\n', encoding="utf-8")
        second.write_text(
            prefix + '<urn:test:owl-dl:second> a owl:Ontology .\n'
            '<#C> a owl:Class .\n'
            '<urn:test:owl-dl:i> a owl:NamedIndividual, <#C>, <urn:test:owl-dl:D> .\n',
            encoding="utf-8")
        output = self.root / "independent-run"
        check_consistency([first, second], output, java=JAVA)
        self.assert_result(output, True)
        assembled = Graph().parse(output / "assembled.rdf", format="xml")
        first_class, second_class = URIRef(first.as_uri() + "#C"), URIRef(second.as_uri() + "#C")
        self.assertNotEqual(first_class, second_class)
        self.assertIn((first_class, RDF.type, OWL.Class), assembled)
        self.assertIn((second_class, RDF.type, OWL.Class), assembled)

    def test_explicit_shared_base_preserves_shared_class_identity(self):
        self.require_java()
        source_root = self.root / "shared-base"
        source_root.mkdir()
        first = source_root / "first.ttl"
        second = source_root / "second.ttl"
        prefix = ('@base <https://example.invalid/shared-ontology> .\n'
                  '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n')
        first.write_text(
            prefix + '<urn:test:owl-dl:shared-first> a owl:Ontology .\n'
            '<#C> a owl:Class; owl:disjointWith <#D> .\n'
            '<#D> a owl:Class .\n', encoding="utf-8")
        second.write_text(
            prefix + '<urn:test:owl-dl:shared-second> a owl:Ontology .\n'
            '<#C> a owl:Class .\n'
            '<urn:test:owl-dl:shared-i> a owl:NamedIndividual, <#C>, <#D> .\n',
            encoding="utf-8")
        output = self.root / "shared-run"
        check_consistency([first, second], output, java=JAVA)
        self.assert_result(output, False)

    def test_invalid_version_iri_is_not_hidden_by_header_normalization(self):
        for filename in ("version_iri_literal.ttl", "version_iri_multiple.ttl", "version_iri_non_header.ttl"):
            with self.subTest(input=filename):
                output = self.root / Path(filename).stem
                with patch("subprocess.run") as launch:
                    with self.assertRaisesRegex(ToolError, "versionIRI"):
                        check_consistency(self.inputs / filename, output, java=JAVA)
                    launch.assert_not_called()
                self.assert_failed_without_verdict(output)

    def test_imports_on_non_ontology_subject_is_rejected_before_normalization(self):
        output = self.root / "non-header-imports"
        with patch("subprocess.run") as launch:
            with self.assertRaisesRegex(ToolError, "(?i)imports.*ontology header"):
                check_consistency(self.inputs / "imports/non_header.ttl", output,
                                  imports=self.inputs / "imports/mapping.ttl", java=JAVA)
            launch.assert_not_called()
        self.assert_failed_without_verdict(output)

    def test_rdf_xml_literal_is_checked_by_real_reasoner(self):
        self.assert_result(self.check("xml_literal.ttl"), True)


if __name__ == "__main__":
    unittest.main()
