"""Offline RDF conversion, explicit patches and CSV mapping. No remote loaders."""
from __future__ import annotations
import argparse
import csv
import hashlib
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlsplit

import rdflib
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, XSD

M = Namespace("urn:ontology:local-migration:")
E = Namespace("urn:ontology:local-evidence:")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Graph:
    path = path.resolve(strict=True)
    formats = {".owl": "xml", ".rdf": "xml", ".swrl": "xml", ".ttl": "turtle", ".nt": "nt"}
    if path.suffix.lower() not in formats or not path.is_file():
        raise ValueError("Only local RDF/XML, Turtle and N-Triples files are supported")
    data = path.read_text(encoding="utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.I):
        raise ValueError("DTD/entities are not supported")
    if formats[path.suffix.lower()] == "xml" and ET.fromstring(data).tag != "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF":
        raise ValueError("This RDF/XML profile requires an rdf:RDF root; OWL/XML is not supported")
    old = rdflib.NORMALIZE_LITERALS
    rdflib.NORMALIZE_LITERALS = False
    try:
        graph = Graph().parse(data=data, format=formats[path.suffix.lower()], publicID=path.as_uri())
    finally:
        rdflib.NORMALIZE_LITERALS = old
    return graph


def fresh_union(graphs: list[Graph]) -> Graph:
    """Keep each document's blank-node scope independent."""
    result = Graph()
    for graph in graphs:
        scoped = {}
        for triple in graph:
            result.add(tuple(scoped.setdefault(t, BNode()) if isinstance(t, BNode) else t for t in triple))
    return result


def emit(graph: Graph, output: Path, inputs: list[Path], operation: str, fmt: str = "turtle", extra: Graph | None = None, runtime_files: list[Path] | None = None) -> Path:
    output = output.resolve()
    inputs = [p.resolve(strict=True) for p in inputs]
    if output.exists():
        raise ValueError("Output must be a new directory; existing evidence is never overwritten")
    if any(output == p or output in p.parents for p in inputs):
        raise ValueError("Output must be separate from all inputs")
    protected = {Path(__file__).resolve().parents[3]}
    for source in inputs:
        for folder in source.parents:
            if any((folder / marker).is_file() for marker in ("ontology.ttl", "integration/load-plan.ttl", "manifest.sha256", "SKILL.md")):
                protected.add(folder)
    if any(output == folder or folder in output.parents for folder in protected):
        raise ValueError("Output must be outside the method library and source ontology/evidence packages")
    output.mkdir(parents=True)
    snapshots = output / "inputs"
    snapshots.mkdir()
    report = extra if extra is not None else Graph()
    run = URIRef("urn:ontology:local-run")
    report.add((run, RDF.type, E.GraphOperation))
    report.add((run, E.operation, Literal(operation)))
    report.add((run, E.rdflibVersion, Literal(rdflib.__version__)))
    report.add((run, E.pythonVersion, Literal(sys.version)))
    report.add((run, E.helperSha256, Literal(digest(Path(__file__)))))
    runtime = output / "runtime"
    runtime.mkdir()
    for index, code in enumerate(dict.fromkeys([Path(__file__).resolve()] + [p.resolve() for p in runtime_files or []])):
        target = runtime / f"{index:03d}-{code.name}"
        shutil.copyfile(code, target)
        item = BNode()
        report.add((run, E.implementation, item))
        report.add((item, E.source, URIRef(code.as_uri())))
        report.add((item, E.snapshot, Literal(target.relative_to(output).as_posix())))
        report.add((item, E.sha256, Literal(digest(target))))
    report.add((run, E.importsResolved, Literal(False)))
    report.add((run, E.consistencyChecked, Literal(False)))
    for index, source in enumerate(inputs):
        target = snapshots / f"{index:03d}-{source.name}"
        shutil.copyfile(source, target)
        item = BNode()
        report.add((run, E.input, item))
        report.add((item, E.source, URIRef(source.as_uri())))
        report.add((item, E.snapshot, Literal(target.relative_to(output).as_posix())))
        report.add((item, E.sha256, Literal(digest(target))))
    result = output / ("result.owl" if fmt == "xml" else "result.ttl")
    # N-Triples is valid Turtle and avoids the Turtle serializer abbreviating
    # numeric literals (for example "007"^^xsd:integer) into canonical tokens.
    graph.serialize(destination=result, format="nt" if fmt == "turtle" else fmt, encoding="utf-8")
    if not isomorphic(graph, load(result)):
        raise ValueError("Serialized output is not graph-isomorphic; evidence retained for diagnosis")
    report.add((run, E.serializationIsomorphic, Literal(True)))
    report.add((run, E.triples, Literal(len(graph))))
    report.add((run, E.status, Literal("passed")))
    report.serialize(destination=output / "report.ttl", format="turtle", encoding="utf-8")
    (output / "report.md").write_text(
        f"# 本地图操作\n\n操作：{operation}。重新解析与待输出图同构。\n\n"
        "此报告不证明业务映射正确或OWL一致性；未解析imports、未执行SWRL。"
        "输入快照和指纹见report.ttl。\n", encoding="utf-8")
    files = sorted(p for p in output.rglob("*") if p.is_file())
    (output / "manifest.sha256").write_text("".join(f"{digest(p)}  {p.relative_to(output).as_posix()}\n" for p in files), encoding="utf-8")
    return result


def one(graph: Graph, subject, predicate, optional: bool = False):
    values = list(graph.objects(subject, predicate))
    if optional and not values:
        return None
    if len(values) != 1:
        raise ValueError(f"Expected exactly one {predicate} on {subject}")
    return values[0]


def iri(value, label: str) -> URIRef:
    if not isinstance(value, URIRef) or not urlsplit(str(value)).scheme or re.search(r'[\s<>"{}|\\^`]', str(value)):
        raise ValueError(f"{label} must be an absolute IRI")
    return value


def convert(source: Path, output: Path, fmt: str):
    source_graph = load(source)
    return emit(source_graph, output, [source], "format-conversion", fmt)


def patch(source: Path, additions: Path | None, removals: Path | None, output: Path):
    if not additions and not removals:
        raise ValueError("Specify explicit additions or removals")
    graph = load(source)
    paths = [source]
    if removals:
        deleted = load(removals)
        if any(isinstance(t, BNode) for triple in deleted for t in triple):
            raise ValueError("Blank-node removals require an explicit structural migration, not blank-node labels")
        if any(t not in graph for t in deleted):
            raise ValueError("A requested removal is not present in the source")
        for triple in deleted:
            graph.remove(triple)
        paths.append(removals)
    if additions:
        graph = fresh_union([graph, load(additions)])
        paths.append(additions)
    return emit(graph, output, paths, "explicit-version-patch")


def typed(value: str, datatype: URIRef):
    allowed = {XSD.string, XSD.integer, XSD.decimal, XSD.boolean, XSD.date, XSD.dateTime}
    if datatype not in allowed:
        raise ValueError(f"Unsupported mapped datatype: {datatype}")
    if datatype == XSD.integer and not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError(f"Invalid integer: {value!r}")
    if datatype == XSD.decimal:
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            raise ValueError(f"Invalid decimal: {value!r}")
        try:
            if not Decimal(value).is_finite():
                raise ValueError("Non-finite decimal")
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal") from exc
    if datatype == XSD.boolean and value not in {"true", "false", "0", "1"}:
        raise ValueError(f"Invalid boolean: {value!r}")
    if datatype == XSD.date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("CSV date profile requires YYYY-MM-DD")
        date.fromisoformat(value)
    if datatype == XSD.dateTime:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
            raise ValueError("CSV dateTime profile requires an ISO dateTime with seconds")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    return Literal(value, datatype=datatype, normalize=False)


def csv_import(source: Path, mapping: Path, output: Path):
    config = load(mapping)
    nodes = list(config.subjects(RDF.type, M.Mapping))
    if len(nodes) != 1:
        raise ValueError("Exactly one mapping per CSV is required")
    node = nodes[0]
    mode = str(one(config, node, M.mode))
    key_column = str(one(config, node, M.keyColumn))
    base = str(iri(one(config, node, M.baseIRI), "baseIRI"))
    if mode not in {"instances", "classes"}:
        raise ValueError("Mapping mode must be instances or classes")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)) or any(not h for h in headers):
            raise ValueError("CSV needs distinct nonempty column headers")
        rows = list(reader)
    if not rows:
        raise ValueError("Empty CSV needs a project-specific completeness decision")
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("CSV rows must have exactly the declared column count")
    if key_column not in headers:
        raise ValueError("Key column missing")
    keys = [row[key_column] for row in rows]
    if any(not key or key != key.strip() for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Missing, whitespace-padded or duplicate business keys")
    identities = {key: URIRef(base + quote(key, safe="")) for key in keys}
    if len(set(identities.values())) != len(keys):
        raise ValueError("IRI collision")
    used = {key_column}
    ignored = set()
    for item in config.objects(node, M.ignore):
        ignored.add(str(one(config, item, M.column)))
        if not str(one(config, item, M.reason)).strip():
            raise ValueError("Ignoring a column requires a reason")
    graph = Graph()
    report = Graph()
    run = URIRef("urn:ontology:local-run")
    if mode == "classes":
        columns = {name: one(config, node, M[name + "Column"], optional=True) for name in ("label", "parent", "comment")}
        used.update(str(c) for c in columns.values() if c is not None)
        if columns["label"] is None:
            raise ValueError("Class mapping needs labelColumn")
        for row in rows:
            subject = identities[row[key_column]]
            graph.add((subject, RDF.type, OWL.Class))
            label = row.get(str(columns["label"]), "")
            if not label:
                raise ValueError("Missing class label")
            graph.add((subject, RDFS.label, Literal(label, lang="zh")))
            if columns["parent"] is not None and (parent := row.get(str(columns["parent"]), "")):
                if parent not in identities:
                    raise ValueError(f"Parent key has no definition in this export: {parent}")
                graph.add((subject, RDFS.subClassOf, identities[parent]))
            if columns["comment"] is not None and (comment := row.get(str(columns["comment"]), "")):
                graph.add((subject, RDFS.comment, Literal(comment, lang="zh")))
    else:
        cls = iri(one(config, node, M.targetClass), "targetClass")
        fields = []
        for item in config.objects(node, M.field):
            col = str(one(config, item, M.column))
            prop = iri(one(config, item, M.property), "property")
            dtype = one(config, item, M.datatype, optional=True)
            object_base = one(config, item, M.iriBase, optional=True)
            if (dtype is None) == (object_base is None):
                raise ValueError("Each field needs exactly one datatype or iriBase")
            if dtype is not None:
                iri(dtype, "datatype")
                typed("0" if dtype in {XSD.integer, XSD.decimal, XSD.boolean} else "2000-01-01" if dtype == XSD.date else "2000-01-01T00:00:00" if dtype == XSD.dateTime else "", dtype)
            else:
                iri(object_base, "iriBase")
            missing = str(one(config, item, M.missing))
            if missing not in {"error", "omit", "empty-string"} or missing == "empty-string" and dtype != XSD.string:
                raise ValueError("Unsupported missing-value policy")
            used.add(col)
            fields.append((col, prop, dtype, object_base, missing))
        if not fields:
            raise ValueError("Instance mapping needs fields")
        if len({f[0] for f in fields}) != len(fields):
            raise ValueError("Duplicate field mapping; split/multi-value transforms need a project adapter")
        for row in rows:
            subject = identities[row[key_column]]
            graph.add((subject, RDF.type, cls))
            for col, prop, dtype, object_base, missing in fields:
                value = row.get(col)
                if value is None:
                    raise ValueError(f"Mapped column missing: {col}")
                if value == "":
                    if missing == "error":
                        raise ValueError(f"Missing value for {col}")
                    if missing == "omit":
                        continue
                obj = typed(value, dtype) if dtype is not None else URIRef(str(object_base) + quote(value, safe=""))
                graph.add((subject, prop, obj))
    if not used.issubset(headers) or not ignored.issubset(headers) or used & ignored or set(headers) - used - ignored:
        raise ValueError("Every CSV column must be mapped or explicitly ignored with a reason")
    for index, row in enumerate(rows, start=1):
        item = BNode()
        report.add((run, E.row, item))
        report.add((item, E.sourceRecord, Literal(index)))
        report.add((item, E.businessKey, Literal(row[key_column])))
        report.add((item, E.entity, identities[row[key_column]]))
    report.add((run, E.sourceRows, Literal(len(rows))))
    return emit(graph, output, [source, mapping], "csv-" + mode, extra=report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    conv = commands.add_parser("convert")
    conv.add_argument("--source", type=Path, required=True)
    conv.add_argument("--format", choices=["xml", "turtle"], required=True)
    conv.add_argument("--output", type=Path, required=True)
    change = commands.add_parser("patch")
    change.add_argument("--source", type=Path, required=True)
    change.add_argument("--add", type=Path)
    change.add_argument("--remove", type=Path)
    change.add_argument("--output", type=Path, required=True)
    csv_cmd = commands.add_parser("csv-import")
    csv_cmd.add_argument("--source", type=Path, required=True)
    csv_cmd.add_argument("--mapping", type=Path, required=True)
    csv_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "convert":
            result = convert(args.source, args.output, args.format)
        elif args.command == "patch":
            result = patch(args.source, args.add, args.remove, args.output)
        else:
            result = csv_import(args.source, args.mapping, args.output)
        print(result)
        return 0
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
