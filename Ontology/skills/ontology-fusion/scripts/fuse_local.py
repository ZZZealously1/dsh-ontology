"""Local alignment candidates and explicit graph assembly, never semantic auto-fusion."""
from __future__ import annotations
import argparse
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ontology-migration" / "scripts"))
from local_graph import emit, fresh_union, iri, load, one
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

F = Namespace("urn:ontology:local-fusion:")
KINDS = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.NamedIndividual)


def closed_files(paths):
    graphs = [load(path) for path in paths]
    if any(any(graph.triples((None, OWL.imports, None))) for graph in graphs):
        raise ValueError("Resolve the declared import closure explicitly before candidate matching or assembly")
    return graphs


def candidates(left: Path, right: Path, output: Path):
    graphs = closed_files([left, right])
    indices = []
    for graph in graphs:
        index = {}
        for kind in KINDS:
            for entity in graph.subjects(RDF.type, kind):
                if not isinstance(entity, URIRef):
                    continue
                for label in graph.objects(entity, RDFS.label):
                    if isinstance(label, Literal) and str(label).strip():
                        index.setdefault((kind, label), set()).add(entity)
        indices.append(index)
    result = Graph()
    for key in sorted(set(indices[0]) & set(indices[1]), key=str):
        kind, label = key
        for source, target in sorted(product(indices[0][key], indices[1][key]), key=str):
            entry = BNode()
            result.add((entry, RDF.type, F.Alignment))
            result.add((entry, F.source, source))
            result.add((entry, F.target, target))
            result.add((entry, F.entityKind, kind))
            result.add((entry, F.label, label))
            result.add((entry, F.status, Literal("candidate")))
            result.add((entry, F.method, Literal("exact-label-and-language")))
            for side, graph, entity in (("source", graphs[0], source), ("target", graphs[1], target)):
                # Preserve observed signature evidence; unequal parents are not proof of conflict.
                for predicate in (RDFS.subClassOf, RDFS.domain, RDFS.range):
                    for value in graph.objects(entity, predicate):
                        if isinstance(value, URIRef):
                            record = BNode()
                            result.add((entry, F.signature, record))
                            result.add((record, F.side, Literal(side)))
                            result.add((record, F.predicate, predicate))
                            result.add((record, F.value, value))
    return emit(result, output, [left, right], "alignment-candidates", runtime_files=[Path(__file__)])


def merge(paths: list[Path], mapping: Path | None, output: Path):
    if len(paths) < 2:
        raise ValueError("Assembly requires at least two explicit source files")
    graph = fresh_union(closed_files(paths))
    evidence = Graph()
    if mapping:
        decisions = load(mapping)
        entries = set(decisions.subjects(RDF.type, F.Alignment))
        if not entries:
            raise ValueError("Mapping contains no explicit alignment decisions")
        for entry in entries:
            if str(one(decisions, entry, F.status)) != "approved":
                raise ValueError("Candidate or unresolved mappings cannot generate logical axioms")
            source = iri(one(decisions, entry, F.source), "source")
            target = iri(one(decisions, entry, F.target), "target")
            relation = iri(one(decisions, entry, F.relation), "relation")
            if not str(one(decisions, entry, F.evidence)).strip() or not str(one(decisions, entry, F.reason)).strip():
                raise ValueError("Approved mappings need evidence and rationale")
            kinds = {
                OWL.equivalentClass: (OWL.Class,), RDFS.subClassOf: (OWL.Class,),
                OWL.equivalentProperty: (OWL.ObjectProperty, OWL.DatatypeProperty),
                RDFS.subPropertyOf: (OWL.ObjectProperty, OWL.DatatypeProperty),
                OWL.inverseOf: (OWL.ObjectProperty,), OWL.sameAs: (OWL.NamedIndividual,),
            }
            if relation not in kinds:
                raise ValueError("Unsupported mapping relation; use an explicit reviewed source edit")
            if not any((source, RDF.type, kind) in graph and (target, RDF.type, kind) in graph for kind in kinds[relation]):
                raise ValueError("Mapping endpoints need compatible explicit OWL entity declarations")
            graph.add((source, relation, target))
            evidence += decisions
        paths = paths + [mapping]
    return emit(graph, output, paths, "explicit-graph-assembly", extra=evidence, runtime_files=[Path(__file__)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    match = commands.add_parser("candidates")
    match.add_argument("--left", type=Path, required=True)
    match.add_argument("--right", type=Path, required=True)
    match.add_argument("--output", type=Path, required=True)
    assemble = commands.add_parser("merge")
    assemble.add_argument("--source", type=Path, action="append", required=True)
    assemble.add_argument("--mapping", type=Path)
    assemble.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = candidates(args.left, args.right, args.output) if args.command == "candidates" else merge(args.source, args.mapping, args.output)
        print(result)
        return 0
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
