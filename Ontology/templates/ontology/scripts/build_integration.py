"""Build/check this template's local materialized graph. This is not a reasoner."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath

from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS, OWL

PKG = Namespace("https://example.org/ontology-package#")
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
VERSION = "template-materializer-1"


def one(graph, subject, predicate):
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise ValueError(f"Expected one {predicate} on {subject}; found {len(values)}")
    return values[0]


def local_path(root, value):
    raw = str(value)
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\\" in raw or ":" in raw:
        raise ValueError(f"Unsafe package path: {raw}")
    resolved = (root / raw).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes package: {raw}")
    return resolved


def read_graph(path, fmt):
    content = path.read_bytes()
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError(f"DTD/entities unsupported: {path}")
    graph = Graph().parse(data=content, format=fmt, publicID=path.as_uri())
    if any(graph.triples((None, OWL.imports, None))):
        raise ValueError(f"This sample builder does not resolve imports: {path}")
    return graph


def union_into(target, source):
    # Blank nodes in different source files never denote the same object.
    scope = {}
    for triple in source:
        target.add(tuple(scope.setdefault(term, BNode()) if isinstance(term, BNode) else term
                         for term in triple))


def build(root, check=False):
    root = Path(root).resolve()
    if not check and (root / "manifest.sha256").exists():
        raise ValueError("Frozen package: create and validate a new version before rebuilding")
    plan_path = root / "integration/load-plan.ttl"
    plan = read_graph(plan_path, "turtle")
    plans = list(plan.subjects(RDF.type, PKG.LoadPlan))
    if len(plans) != 1:
        raise ValueError("Expected one LoadPlan")
    entry = plans[0]
    if one(plan, entry, PKG.integrationMode) != PKG.Materialized:
        raise ValueError("Only Materialized mode is supported by this sample builder")
    if one(plan, entry, PKG.includesABox) != Literal(False):
        raise ValueError("This sample builder only integrates TBox and rules")
    if one(plan, entry, PKG.factSelection) != PKG.ExplicitSnapshotOrInput:
        raise ValueError("Unsupported fact selection policy")
    modules = set(plan.objects(entry, PKG.module))
    if not modules:
        raise ValueError("No source modules")
    if set(plan.subjects(RDF.type, PKG.Module)) != modules:
        raise ValueError("Unselected or undeclared source module")
    merged = Graph()
    evidence = Graph()
    evidence.bind("pkg", PKG)
    evidence.add((entry, PKG.builderVersion, Literal(VERSION)))
    paths = set()
    roles = set()
    declarations = {OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                    OWL.Ontology, OWL.Restriction, RDF.Property}
    for module in sorted(modules, key=str):
        role = one(plan, module, PKG.role)
        if role not in {PKG.TBox, PKG.Rules, PKG.ABox}:
            raise ValueError(f"Unsupported module role: {role}")
        domain = one(plan, module, PKG.domain)
        if (domain, RDF.type, PKG.Domain) not in plan:
            raise ValueError(f"Missing domain registration: {domain}")
        one(plan, domain, PKG.domainId)
        one(plan, domain, DCTERMS.description)
        doc = local_path(root, one(plan, domain, PKG.documentation))
        if not doc.is_file():
            raise ValueError(f"Missing domain documentation: {doc}")
        dependencies = set(plan.objects(module, PKG.dependsOn))
        if not dependencies <= modules or module in dependencies:
            raise ValueError(f"Missing dependency or self-dependency: {module}")
        value = one(plan, module, PKG.path)
        path = local_path(root, value)
        if path in paths:
            raise ValueError(f"Repeated source path: {value}")
        paths.add(path)
        roles.add(role)
        fmt = str(one(plan, module, PKG["format"]))
        if fmt != "xml" or path.suffix not in {".owl", ".swrl"}:
            raise ValueError(f"This sample requires RDF/XML .owl/.swrl sources: {value}")
        graph = read_graph(path, fmt)
        version = one(plan, module, PKG.version)
        if not graph:
            raise ValueError(f"Empty source: {value}")
        if role == PKG.TBox:
            iri = one(plan, module, PKG.ontologyIRI)
            if (iri, RDF.type, OWL.Ontology) not in graph or (iri, OWL.versionInfo, version) not in graph:
                raise ValueError(f"Ontology identity/version mismatch: {value}")
            if any(graph.triples((None, RDF.type, SWRL.Imp))):
                raise ValueError(f"SWRL must have its own source role: {value}")
        if role == PKG.Rules and not any(graph.triples((None, RDF.type, SWRL.Imp))):
            raise ValueError(f"Rule source contains no swrl:Imp: {value}")
        if role == PKG.ABox:
            if any(t in declarations or str(t).startswith(str(SWRL)) for t in graph.objects(None, RDF.type)):
                raise ValueError(f"ABox contains a schema/rule declaration: {value}")
        else:
            union_into(merged, graph)
        evidence.add((entry, PKG.module, module))
        for predicate, obj in ((PKG.path, value), (PKG.role, role), (PKG.version, version),
                               (PKG.sha256, Literal(hashlib.sha256(path.read_bytes()).hexdigest()))):
            evidence.add((module, predicate, obj))
    declared_files = {p.resolve() for folder in ("subontologies", "rules", "data")
                      for p in (root / folder).rglob("*") if p.suffix in {".owl", ".swrl", ".ttl"}}
    if declared_files != paths or PKG.TBox not in roles:
        raise ValueError("Source inventory differs from load plan, or TBox is missing")
    iri = one(plan, entry, PKG.entryIRI)
    if not isinstance(iri, URIRef):
        raise ValueError("entryIRI must be an IRI")
    merged.add((iri, RDF.type, OWL.Ontology))
    merged.add((iri, OWL.versionInfo, one(plan, entry, PKG.version)))
    merged.add((iri, RDFS.comment, Literal("Generated TBox + rules; dynamic ABox loaded separately.")))
    for module in modules:
        if one(plan, module, PKG.role) != PKG.ABox:
            merged.add((iri, DCTERMS.source, module))
    for rel in ("integration/load-plan.ttl", "scripts/build_integration.py"):
        node = BNode()
        evidence.add((entry, PKG.buildInput, node))
        evidence.add((node, PKG.path, Literal(rel)))
        evidence.add((node, PKG.sha256, Literal(hashlib.sha256((root / rel).read_bytes()).hexdigest())))
    output = local_path(root, one(plan, entry, PKG.entryFile))
    proof = local_path(root, one(plan, entry, PKG.evidenceFile))
    if output.parent != plan_path.parent or proof.parent != plan_path.parent or output == proof:
        raise ValueError("Generated files must be distinct and in integration/")
    if output in paths or proof in paths or plan_path in {output, proof}:
        raise ValueError("Generated file would overwrite a source")
    if check:
        if not isomorphic(merged, read_graph(output, "xml")):
            raise ValueError("Integrated graph differs from declared source union and generated header")
        if not isomorphic(evidence, read_graph(proof, "turtle")):
            raise ValueError("Build evidence is stale")
    else:
        merged.serialize(destination=output, format="xml", encoding="utf-8")
        evidence.serialize(destination=proof, format="turtle", encoding="utf-8")
    return len(modules), len(merged)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify graph equivalence and source fingerprints without writing")
    args = parser.parse_args()
    try:
        count, triples = build(Path(__file__).resolve().parents[1], args.check)
    except (ValueError, OSError) as error:
        parser.exit(1, f"FAIL: {error}\n")
    print(f"PASS: {'check' if args.check else 'build'}; {count} sources; {triples} integrated triples; ABox-role sources excluded")
