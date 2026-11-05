"""Preserve valid Turtle decimal shorthand and explicit lexical evidence.

The lexical adapter must affect decimal tokens only, keep RDF base/prefix
semantics, and continue rejecting explicitly malformed literals in HermiT.
"""
from pathlib import Path
import shutil
import tempfile
import unittest

import rdflib
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import XSD
from rdflib.plugins.parsers.notation3 import BadSyntax, RDFSink

from ontology_tools.io import OT, ToolError, _PARSE_LOCK, parse_rdf, write_graph
from ontology_tools.owl_dl import RUN, _parse, check_consistency

EX = Namespace("urn:decimal-parsing:")
PREFIX = """@prefix ex: <urn:decimal-parsing:> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""
TOOL_ROOT = Path(__file__).resolve().parents[1]


class DecimalParsingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="decimal-parse-", dir=TOOL_ROOT.parent.parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def source(self, text, name="source.ttl"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def both(self, text):
        path = self.source(PREFIX + text)
        original = path.read_bytes()
        graphs = (parse_rdf(path), _parse(original, path))
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(isomorphic(*graphs))
        return graphs

    def test_tiny_negative_tiny_and_large_bare_decimals_keep_valid_lexical_forms(self):
        tiny = "0.00000000000000000016"
        negative = "-0.00000000000000000016"
        huge = "1" + "0" * 250 + ".125"
        for graph in self.both(f"ex:item ex:tiny {tiny}; ex:negative {negative}; ex:huge {huge} ."):
            for predicate, expected in ((EX.tiny, tiny), (EX.negative, negative), (EX.huge, huge)):
                with self.subTest(predicate=predicate):
                    value = graph.value(EX.item, predicate)
                    self.assertEqual(value.datatype, XSD.decimal)
                    self.assertEqual(str(value), expected)
                    self.assertNotIn("e", str(value).lower())

    def test_explicit_valid_typed_decimals_preserve_spelling(self):
        for graph in self.both('ex:item ex:value "+000.0000000000000000001600"^^xsd:decimal; ex:other "01.2300"^^xsd:decimal .'):
            self.assertEqual(str(graph.value(EX.item, EX.value)), "+000.0000000000000000001600")
            self.assertEqual(str(graph.value(EX.item, EX.other)), "01.2300")

    def test_explicit_decimal_exponent_is_not_silently_repaired(self):
        for graph in self.both('ex:item ex:value "1.6e-19"^^xsd:decimal .'):
            self.assertEqual(str(graph.value(EX.item, EX.value)), "1.6e-19")
            self.assertEqual(graph.value(EX.item, EX.value).datatype, XSD.decimal)

    def test_normalization_setting_and_global_parser_class_restore_on_success_and_failure(self):
        good = self.source(PREFIX + "ex:item ex:value 0.00000000000000000016 .")
        bad = self.source(PREFIX + "ex:item ex:value [ .", "broken.ttl")
        normalise = RDFSink.normalise
        with _PARSE_LOCK:
            before = rdflib.NORMALIZE_LITERALS
            try:
                for setting in (True, False):
                    rdflib.NORMALIZE_LITERALS = setting
                    for parse in (lambda path: parse_rdf(path), lambda path: _parse(path.read_bytes(), path)):
                        with self.subTest(setting=setting, parse=parse):
                            parse(good)
                            self.assertIs(rdflib.NORMALIZE_LITERALS, setting)
                            with self.assertRaises(BadSyntax):
                                parse(bad)
                            self.assertIs(rdflib.NORMALIZE_LITERALS, setting)
                            self.assertIs(RDFSink.normalise, normalise)
            finally:
                rdflib.NORMALIZE_LITERALS = before

    def test_base_relative_prefix_and_relative_resources_preserve_rdf_meaning(self):
        text = """@base <https://example.test/a/b/> .
@prefix ex: <../vocabulary/> .
<../part> ex:value 0.00000000000000000016; ex:related <target> .
"""
        path = self.source(text)
        for graph in (parse_rdf(path), _parse(path.read_bytes(), path)):
            subject = URIRef("https://example.test/a/part")
            predicate = URIRef("https://example.test/a/vocabulary/value")
            self.assertEqual(str(graph.value(subject, predicate)), "0.00000000000000000016")
            self.assertIn((subject, URIRef("https://example.test/a/vocabulary/related"),
                           URIRef("https://example.test/a/b/target")), graph)
            self.assertEqual(dict(graph.namespaces())["ex"], URIRef("https://example.test/a/vocabulary/"))

    def test_owl_parser_without_declared_base_uses_original_document_uri(self):
        path = self.source('@prefix ex: <vocabulary/> . <subject> ex:related <target> .')
        graph = _parse(path.read_bytes(), path)
        self.assertIn((URIRef((self.root / "subject").as_uri()),
                       URIRef((self.root / "vocabulary/related").as_uri()),
                       URIRef((self.root / "target").as_uri())), graph)

    def test_number_like_strings_comments_and_iris_are_unchanged(self):
        text = '''# 0.00000000000000000016 and "1.6e-19"^^xsd:decimal in a comment
ex:item ex:text "0.00000000000000000016";
    ex:longText """negative -0.00000000000000000016; exponent 1.6e-19""";
    ex:resource <https://example.test/0.00000000000000000016>;
    ex:value 0.00000000000000000016 .
'''
        for graph in self.both(text):
            self.assertEqual(len(graph), 4)
            self.assertEqual(str(graph.value(EX.item, EX.text)), "0.00000000000000000016")
            self.assertEqual(str(graph.value(EX.item, EX.longText)), "negative -0.00000000000000000016; exponent 1.6e-19")
            self.assertEqual(graph.value(EX.item, EX.resource), URIRef("https://example.test/0.00000000000000000016"))

    def test_nt_and_xml_keep_explicit_numeric_literal_behavior(self):
        formats = {
            "source.nt": '<urn:decimal-parsing:item> <urn:decimal-parsing:value> "01.2300"^^<http://www.w3.org/2001/XMLSchema#decimal> .\n'
                         '<urn:decimal-parsing:item> <urn:decimal-parsing:bad> "1.6e-19"^^<http://www.w3.org/2001/XMLSchema#decimal> .\n',
            "source.rdf": '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:ex="urn:decimal-parsing:">
 <rdf:Description rdf:about="urn:decimal-parsing:item">
  <ex:value rdf:datatype="http://www.w3.org/2001/XMLSchema#decimal">01.2300</ex:value>
  <ex:bad rdf:datatype="http://www.w3.org/2001/XMLSchema#decimal">1.6e-19</ex:bad>
 </rdf:Description>
</rdf:RDF>''',
        }
        for name, text in formats.items():
            path = self.source(text, name)
            for graph in (parse_rdf(path), _parse(path.read_bytes(), path)):
                with self.subTest(name=name):
                    self.assertEqual(str(graph.value(EX.item, EX.value)), "01.2300")
                    self.assertEqual(str(graph.value(EX.item, EX.bad)), "1.6e-19")

    def test_graph_writer_preserves_mixed_line_endings_over_repeated_snapshots(self):
        values = {EX.lf: "line one\nline two", EX.crlf: "line one\r\nline two",
                  EX.cr: "line one\rline two", EX.mixed: "LF\nCRLF\r\nCR\rend"}
        current = Graph()
        for predicate, text in values.items():
            current.add((EX.item, predicate, Literal(text)))
        for iteration in range(4):
            path = self.root / f"snapshot-{iteration}.ttl"
            write_graph(current, path)
            for reloaded in (parse_rdf(path), _parse(path.read_bytes(), path)):
                for predicate, expected in values.items():
                    with self.subTest(iteration=iteration, predicate=predicate):
                        self.assertEqual(str(reloaded.value(EX.item, predicate)), expected)
                self.assertTrue(isomorphic(current, reloaded))
            current = _parse(path.read_bytes(), path)

    def test_real_formula_replay_preserves_source_latex_line_endings(self):
        from ontology_tools.core import infer_graph, replay_run
        from ontology_tools.formula import F
        package = self.root / "ontology"
        shutil.copytree(TOOL_ROOT / "examples/formula", package)
        catalog = parse_rdf(package / "formulas.ttl")
        synthetic = Namespace("urn:formula-example:")
        source_latex = "$${\r\nL=\\sqrt{D\\tau}\n}\r\n$$"
        catalog.add((synthetic.transportLength, EX.sourceLatex, Literal(source_latex)))
        write_graph(catalog, package / "formulas.ttl")
        inferred = infer_graph(package, output=self.root / "formula-infer")
        replayed = replay_run(inferred, self.root / "formula-replay")
        before = parse_rdf(inferred / "formulas.ttl")
        after = parse_rdf(replayed / "replayed/formulas.ttl")
        self.assertEqual(str(before.value(synthetic.transportLength, EX.sourceLatex)), source_latex)
        self.assertEqual(str(after.value(synthetic.transportLength, EX.sourceLatex)), source_latex)
        self.assertTrue(isomorphic(before, after))
        self.assertEqual(parse_rdf(replayed / "execution.ttl").value(RUN, OT.status), Literal("passed"))

    def test_real_hermit_accepts_bare_tiny_and_rejects_explicit_decimal_exponent(self):
        prefix = PREFIX + """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:model a owl:Ontology .
ex:value a owl:DatatypeProperty; rdfs:range xsd:decimal .
"""
        valid = self.source(prefix + "ex:item ex:value 0.00000000000000000016 .", "valid.ttl")
        valid_run = check_consistency(valid, self.root / "valid-run")
        execution = parse_rdf(valid_run / "execution.ttl")
        self.assertEqual(execution.value(RUN, OT.status), Literal("passed"))
        self.assertEqual(parse_rdf(valid_run / "report.ttl").value(RUN, OT.consistent), Literal(True))
        assembled = parse_rdf(valid_run / "assembled.rdf")
        self.assertEqual(str(assembled.value(EX.item, EX.value)), "0.00000000000000000016")
        invalid = self.source(prefix + 'ex:item ex:value "1.6e-19"^^xsd:decimal .', "invalid.ttl")
        with self.assertRaises(ToolError):
            check_consistency(invalid, self.root / "invalid-run")
        execution = parse_rdf(self.root / "invalid-run/execution.ttl")
        self.assertEqual(execution.value(RUN, OT.status), Literal("failed"))
        self.assertIsNone(parse_rdf(self.root / "invalid-run/report.ttl").value(RUN, OT.consistent))


if __name__ == "__main__":
    unittest.main()
