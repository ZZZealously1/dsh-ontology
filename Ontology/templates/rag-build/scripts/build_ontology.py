"""Copy editable native sources and build their exact TBox/SWRL union offline."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import threading
import rdflib
from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL

PKG = Namespace("https://example.org/ontology-package#")
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
VERSION = "rag-native-builder-1"
METHOD_ROOT = Path(__file__).resolve().parents[3]
_PARSE_LOCK = threading.RLock()


def parse(path):
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entities are unsupported")
    with _PARSE_LOCK:
        previous = rdflib.NORMALIZE_LITERALS
        try:
            rdflib.NORMALIZE_LITERALS = False
            graph = Graph().parse(data=raw, format="turtle" if path.suffix == ".ttl" else "xml", publicID=path.as_uri())
        finally:
            rdflib.NORMALIZE_LITERALS = previous
    if any(graph.triples((None, OWL.imports, None))):
        raise ValueError("This builder requires explicit local modules; imports must be resolved separately")
    return graph


def one(graph, subject, predicate):
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise ValueError(f"Expected one {predicate} on {subject}")
    return values[0]


def safe_path(root, relative):
    raw = str(relative)
    parts = PurePosixPath(raw)
    if not raw or parts.is_absolute() or ".." in parts.parts or ":" in raw or "\\" in raw:
        raise ValueError(f"Unsafe relative path: {raw}")
    path = root.joinpath(*parts.parts)
    for step in (path, *path.parents):
        if step == root.parent:
            break
        if step.is_symlink() or (hasattr(step, "is_junction") and step.is_junction()):
            raise ValueError(f"Linked path: {path}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Escaping path: {path}")
    return path


def inventory(root):
    found = {}
    for path in root.rglob("*"):
        checked = safe_path(root, path.relative_to(root).as_posix())
        if checked.is_file():
            if checked.suffix.lower() == ".json":
                raise ValueError("JSON is not part of this template")
            found[path.relative_to(root).as_posix()] = path
    return found


def scoped_union(target, source):
    scope = {}
    for triple in source:
        target.add(tuple(scope.setdefault(term, BNode()) if isinstance(term, BNode) else term for term in triple))


def load(root):
    plan = parse(root / "integration/load-plan.ttl")
    entries = list(plan.subjects(RDF.type, PKG.LoadPlan))
    if len(entries) != 1:
        raise ValueError("Exactly one load plan required")
    entry = entries[0]
    if one(plan, entry, PKG.integrationMode) != PKG.Materialized or one(plan, entry, PKG.includesABox) != Literal(False):
        raise ValueError("Only explicit TBox + rules materialization, with ABox separate, is supported")
    modules = set(plan.objects(entry, PKG.module))
    if not modules or modules != set(plan.subjects(RDF.type, PKG.Module)):
        raise ValueError("Missing, undeclared or unselected modules")
    loaded = []
    for module in sorted(modules, key=str):
        role = one(plan, module, PKG.role)
        if role not in {PKG.TBox, PKG.Rules, PKG.ABox}:
            raise ValueError(f"Unsupported role: {role}")
        path = safe_path(root, one(plan, module, PKG.path))
        graph = parse(path)
        if role != PKG.Rules and any(graph.triples((None, RDF.type, SWRL.Imp))):
            raise ValueError("Rule declarations require Rules role")
        if role == PKG.ABox and any(graph.triples((None, RDF.type, OWL.Ontology))):
            raise ValueError("ABox should contain facts only, without duplicated model header")
        loaded.append((module, role, path, graph))
    expected = {p.resolve() for folder in ("subontologies", "rules", "data") for p in (root / folder).rglob("*") if p.suffix in {".ttl", ".owl", ".swrl"}}
    selected = [path.resolve() for _, _, path, _ in loaded]
    if len(set(selected)) != len(selected) or set(selected) != expected:
        raise ValueError("Declared source inventory differs from native source files")
    return plan, entry, loaded


def build(source, output, check=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.name != "ontology" or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Output must be a separate directory named ontology")
    if output.is_relative_to(METHOD_ROOT):
        raise ValueError("Generated runs must be outside the Ontology method directory")
    files = inventory(source)
    if "manifest.sha256" in files:
        raise ValueError("Use editable sources, not a frozen delivery as input")
    plan, entry, modules = load(source)
    merged, evidence = Graph(), Graph()
    merged.add((URIRef(str(entry)), RDF.type, OWL.Ontology))
    evidence.add((entry, PKG.builderVersion, Literal(VERSION)))
    for module, role, path, graph in modules:
        if role != PKG.ABox:
            scoped_union(merged, graph)
        evidence.add((entry, PKG.module, module))
        evidence.add((module, PKG.role, role))
        evidence.add((module, PKG.path, Literal(path.relative_to(source).as_posix())))
        evidence.add((module, PKG.sha256, Literal(hashlib.sha256(path.read_bytes()).hexdigest())))
    evidence.add((entry, PKG.loadPlanHash, Literal(hashlib.sha256((source / "integration/load-plan.ttl").read_bytes()).hexdigest())))
    evidence.add((entry, PKG.builderHash, Literal(hashlib.sha256(Path(__file__).read_bytes()).hexdigest())))
    generated = {"integration/merged_ontology.owl", "integration/build-evidence.ttl"}
    if generated & set(files):
        raise ValueError("Source tree must not contain generated integration outputs")
    if check:
        output_files = inventory(output)
        if set(output_files) != set(files) | generated:
            raise ValueError("Output inventory differs")
        for relative, path in files.items():
            if path.read_bytes() != (output / relative).read_bytes():
                raise ValueError(f"Source snapshot changed: {relative}")
        if not isomorphic(merged, parse(output / "integration/merged_ontology.owl")) or not isomorphic(evidence, parse(output / "integration/build-evidence.ttl")):
            raise ValueError("Integrated semantics or build evidence differs")
    else:
        if output.exists():
            raise ValueError("Output exists; use --check or choose a new version")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, output)
        merged.serialize(destination=output / "integration/merged_ontology.owl", format="xml", encoding="utf-8")
        evidence.serialize(destination=output / "integration/build-evidence.ttl", format="turtle", encoding="utf-8")
        # Validate the actual serialized output, not only the pre-write in-memory graph.
        if not isomorphic(merged, parse(output / "integration/merged_ontology.owl")) or not isomorphic(evidence, parse(output / "integration/build-evidence.ttl")):
            raise ValueError("Written integration changed graph semantics")
    return len(modules), len(merged)


def main(default_source=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, default=default_source, required=default_source is None)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--check", action="store_true")
    args = cli.parse_args()
    count, triples = build(args.source, args.output, args.check)
    print(f"PASS: {count} native modules; {triples} integration triples; graph equality checked separately from reasoning")


if __name__ == "__main__":
    main()
