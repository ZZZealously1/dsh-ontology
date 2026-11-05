"""Assemble an explicitly selected rule test scope, preserving every selected triple."""
from pathlib import Path
import argparse
import hashlib
import shutil
from rdflib import Graph, Literal, RDF, URIRef
from rdflib.compare import isomorphic
from build_ontology import PKG, METHOD_ROOT, inventory, one, parse, safe_path


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Choose a new output outside the source tree")
    if output.is_relative_to(METHOD_ROOT):
        raise ValueError("Rule test outputs must be outside the Ontology method directory")
    inventory(source)  # Reject linked or escaping test files before copytree follows them.
    mapping = parse(source / "tests/runtime-source.ttl")
    scopes = list(mapping.subjects(RDF.type, PKG.RuleTestScope))
    if len(scopes) != 1:
        raise ValueError("Exactly one declared rule test scope required")
    scope = scopes[0]
    roles = {PKG.model: "ontology.ttl", PKG.rules: "rules.swrl", PKG.facts: "inputs/facts.ttl",
             PKG.shapes: "shapes.ttl", PKG.cases: "tests/cases.ttl"}
    selected = [(predicate, safe_path(source, one(mapping, scope, predicate)), target)
                for predicate, target in roles.items()]
    graphs = {predicate: parse(path) for predicate, path, _ in selected}
    from ontology_tools.backend import inspect_semantics
    errors = inspect_semantics(graphs[PKG.model] + graphs[PKG.facts], graphs[PKG.rules])
    if errors:
        raise ValueError("Selected rule scope unsupported: " + "; ".join(errors))
    output.mkdir(parents=True)
    evidence = Graph()
    for predicate, path, relative in selected:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == ".ttl":
            graphs[predicate].serialize(destination=target, format="turtle", encoding="utf-8")
        else:
            shutil.copyfile(path, target)
        if not isomorphic(graphs[predicate], parse(target)):
            raise ValueError("Serialization changed selected source semantics")
        node = URIRef("urn:rag-test-source:" + relative)
        evidence.add((node, PKG.path, Literal(path.relative_to(source).as_posix())))
        evidence.add((node, PKG.sha256, Literal(hashlib.sha256(path.read_bytes()).hexdigest())))
        evidence.add((node, PKG.target, Literal(relative)))
        evidence.add((node, PKG.graphIsomorphic, Literal(True)))
    shutil.copytree(source / "tests/inputs", output / "tests/inputs")
    evidence.serialize(destination=output / "scope-evidence.ttl", format="turtle", encoding="utf-8")
    (output / "scope.txt").write_text("Rule-module tests only. Every selected model/rule triple is preserved.\n"
        "No claim of equivalence to full OWL DL + SWRL execution. Full TBox constraints require the separate OWL DL check.\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--tools", type=Path, default=Path(__file__).resolve().parents[3] / "Ontology-tools")
    args = cli.parse_args()
    import sys
    sys.path.insert(0, str(args.tools.resolve()))
    print(prepare(args.source, args.output))
