"""Offline OWL 2 DL profile, consistency and named-class satisfiability checks.

HermiT executes the semantic checks. Python assembles explicit local imports,
records exact inputs and validates the bridge's complete, non-JSON protocol.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import subprocess

import rdflib
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from .io import (OT, ToolError, _PARSE_LOCK, code_files, enclosing_packages,
                 new_output, parse_graph_lexically, safe_path, sha256, verify_manifest, write_graph,
                 write_manifest)

RUN = URIRef("urn:ontology-tools:run")
PROFILE = "owl-dl-hermit-v1"
INFER_PROFILE = "owl-dl-projection-v1"
ROOT = Path(__file__).resolve().parent.parent
SWRL_NAMESPACES = ("http://www.w3.org/2003/11/swrl#", "http://www.w3.org/2003/11/swrlb#")


def _paths(value, *, required=False) -> list[Path]:
    values = [] if value is None else [value] if isinstance(value, (str, Path)) else list(value)
    if required and not values:
        raise ToolError("At least one local ontology file is required")
    return [Path(p).resolve() for p in values]


def _parse(raw: bytes, path: Path) -> Graph:
    suffix = path.suffix.lower()
    if suffix not in {".ttl", ".nt", ".owl", ".rdf", ".swrl"}:
        raise ToolError(f"Unsupported RDF format: {suffix}")
    text = raw.decode("utf-8-sig")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.I):
        raise ToolError("RDF/XML DTD and entities are disabled")
    fmt = "turtle" if suffix == ".ttl" else "nt" if suffix == ".nt" else "xml"
    graph = Graph()
    with _PARSE_LOCK:
        normalize = rdflib.NORMALIZE_LITERALS
        try:
            rdflib.NORMALIZE_LITERALS = False
            # RDF relative IRIs belong to this document unless it declares its
            # own base. A shared invented base would silently merge entities
            # from unrelated modules or disconnect absolute references.
            parse_graph_lexically(graph, text, fmt, path.as_uri())
        finally:
            rdflib.NORMALIZE_LITERALS = normalize
    for value in graph.objects():
        if (isinstance(value, Literal) and value.datatype == RDF.XMLLiteral
                and re.search(r"<!\s*(DOCTYPE|ENTITY)\b", str(value), re.I)):
            # Check decoded literal content as well: Turtle Unicode escapes
            # must not smuggle an external-entity declaration to a datatype parser.
            raise ToolError("DTD and entities are disabled inside rdf:XMLLiteral")
    return graph


def _merge(target: Graph, source: Graph, index: int):
    # Blank node identifiers are scoped to a source document, not the whole run.
    blanks = {}

    def scoped(term):
        if isinstance(term, BNode):
            return blanks.setdefault(term, BNode(f"s{index}n{len(blanks)}"))
        return term

    for triple in source:
        target.add(tuple(scoped(term) for term in triple))


def _protected_roots(path: Path) -> list[Path]:
    roots = [path, *enclosing_packages(path)]
    roots.extend(parent for parent in path.parents
                 if (parent / "integration" / "load-plan.ttl").is_file())
    return roots


def _snapshot(path: Path, role: str, output: Path, evidence: Graph, index: int) -> tuple[Graph, bytes]:
    if not path.is_file():
        raise ToolError(f"Missing local RDF file: {path}")
    for protected in _protected_roots(path):
        if output.is_relative_to(protected):
            raise ToolError(f"Output must be outside the input package: {protected}")
    raw = path.read_bytes()
    relative = f"inputs/{index:04d}{path.suffix.lower()}"
    snapshot = output / relative
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_bytes(raw)
    node = URIRef(f"urn:ontology-tools:input:{index}")
    evidence.add((RUN, OT.input, node))
    evidence.add((node, OT.role, Literal(role)))
    evidence.add((node, OT.sourcePath, Literal(str(path))))
    evidence.add((node, OT.documentBase, URIRef(path.as_uri())))
    evidence.add((node, OT.snapshot, Literal(relative)))
    evidence.add((node, OT.sha256, Literal(hashlib.sha256(raw).hexdigest())))
    return _parse(raw, path), raw


def _load_inputs(ontologies, facts, imports, output, evidence):
    mappings = {}
    counter = 0
    if imports is not None:
        imports = Path(imports).resolve()
        mapping_graph, _ = _snapshot(imports, "ImportMapping", output, evidence, counter)
        counter += 1
        for item in mapping_graph.subjects(RDF.type, OT.ImportMapping):
            iris = list(mapping_graph.objects(item, OT.ontologyIRI))
            paths = list(mapping_graph.objects(item, OT.path))
            if len(iris) != 1 or not isinstance(iris[0], URIRef) or len(paths) != 1 or not isinstance(paths[0], Literal):
                raise ToolError("ImportMapping requires one ontologyIRI and one local path")
            if iris[0] in mappings:
                raise ToolError(f"Duplicate import mapping: {iris[0]}")
            mappings[iris[0]] = safe_path(imports.parent, str(paths[0])).resolve()
    combined = Graph()
    loaded = {}
    pending = [(p, "TBox", None) for p in ontologies] + [(p, "ABox", None) for p in facts]
    while pending:
        path, role, imported_iri = pending.pop(0)
        if path in loaded:
            graph = loaded[path]
        else:
            graph, _ = _snapshot(path, role, output, evidence, counter)
            counter += 1
            if any(isinstance(term, URIRef) and str(term).startswith(SWRL_NAMESPACES)
                   for triple in graph for term in triple):
                raise ToolError(f"SWRL is outside the OWL DL check; provide the TBox/ABox separately: {path}")
            loaded[path] = graph
            for subject in graph.subjects(OWL.imports, None):
                if (subject, RDF.type, OWL.Ontology) not in graph:
                    raise ToolError("owl:imports must belong to an explicitly declared ontology header")
            for imported in sorted(set(graph.objects(None, OWL.imports)), key=str):
                if not isinstance(imported, URIRef) or imported not in mappings:
                    raise ToolError(f"Unmapped owl:imports; no network resolution is allowed: {imported}")
                pending.append((mappings[imported], "Import", imported))
            semantic = Graph()
            for triple in graph:
                if triple[1] != OWL.imports:
                    semantic.add(triple)
            _merge(combined, semantic, counter)
        if imported_iri is not None:
            heads = set(graph.subjects(RDF.type, OWL.Ontology))
            identities = heads | {v for h in heads for v in graph.objects(h, OWL.versionIRI)}
            if imported_iri not in identities:
                raise ToolError(f"Import mapping IRI does not match the file's ontology/version IRI: {imported_iri} -> {path}")
    # OWLAPI requires one ontology header. Preserve source identity/version and
    # original header metadata in snapshots; only package headers are normalized.
    heads = set(combined.subjects(RDF.type, OWL.Ontology))
    header = URIRef("urn:ontology-tools:assembled")
    annotation_predicates = set(combined.subjects(RDF.type, OWL.AnnotationProperty)) | {
        RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy, OWL.versionInfo,
        OWL.priorVersion, OWL.backwardCompatibleWith, OWL.incompatibleWith, OWL.deprecated,
    }
    for subject in combined.subjects(OWL.versionIRI, None):
        versions = set(combined.objects(subject, OWL.versionIRI))
        if subject not in heads or not isinstance(subject, URIRef) or len(versions) != 1 or not all(isinstance(v, URIRef) for v in versions):
            raise ToolError("owl:versionIRI requires one IRI on a named ontology header")
    for head in heads:
        if (set(combined.objects(head, RDF.type)) != {OWL.Ontology}
                or any(p not in annotation_predicates for _, p, _ in combined.triples((None, None, head)))
                or any(p not in annotation_predicates | {RDF.type, OWL.versionIRI}
                       for _, p, _ in combined.triples((head, None, None)))):
            raise ToolError("An ontology header is also used as an entity; cannot safely assemble it")
    for head in heads:
        for _, predicate, value in list(combined.triples((head, None, None))):
            combined.remove((head, predicate, value))
            if predicate not in {RDF.type, OWL.versionIRI}:
                combined.add((header, predicate, value))
    combined.add((header, RDF.type, OWL.Ontology))
    # OWLAPI 4.5.29 strict RDF/XML loading requires an explicit class marker on
    # anonymous restrictions. OWL restrictions already denote class expressions;
    # this redundant declaration changes no OWL logical meaning.
    restrictions = [node for node in combined.subjects(RDF.type, OWL.Restriction)
                    if isinstance(node, BNode) and (node, RDF.type, OWL.Class) not in combined]
    for node in restrictions:
        combined.add((node, RDF.type, OWL.Class))
    evidence.add((RUN, OT.normalizedRestrictions, Literal(len(restrictions))))
    evidence.add((RUN, OT.normalization, Literal("assembly-v1: source headers replaced by one header; imports locally resolved; anonymous restrictions explicitly marked owl:Class for OWLAPI 4.5.29 strict parser")))
    return combined


def _runtime(output: Path, evidence: Graph):
    vendor = ROOT / "vendor" / "owl-dl"
    verify_manifest(vendor, required=True)
    verify_manifest(ROOT / "java", required=True)
    classes = ROOT / "java" / "classes"
    if not (classes / "OwlDlCheck.class").is_file():
        raise ToolError("Missing compiled OWL DL bridge; see java/README.md")
    jars = sorted((vendor / "lib").glob("*.jar"))
    if not jars:
        raise ToolError("Missing bundled offline OWL DL dependencies")
    runtime_files = dict(code_files())
    for path in sorted((ROOT / "java").rglob("*")):
        if path.is_file():
            runtime_files[path.relative_to(ROOT).as_posix()] = path
    for path in sorted(vendor.rglob("*")):
        if path.is_file():
            runtime_files[path.relative_to(ROOT).as_posix()] = path
    digests = []
    for relative, path in sorted(runtime_files.items()):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        digests.append(f"{digest}  {relative}\n")
        # Preserve the runner's small source files; bundled jars remain in the
        # distributable and are identified exactly by runtime.sha256.
        if path.suffix in {".py", ".java", ".class", ".txt"} and not relative.startswith("vendor/"):
            destination = output / "runtime" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
    payload = "".join(digests)
    (output / "runtime.sha256").write_text(payload, encoding="utf-8")
    evidence.add((RUN, OT.runtimeDigest, Literal(sha256(output / "runtime.sha256"))))
    evidence.add((RUN, OT.pythonVersion, Literal(__import__("platform").python_version())))
    evidence.add((RUN, OT.rdflibVersion, Literal(rdflib.__version__)))
    return os.pathsep.join([str(classes), *map(str, jars)])


def _protocol(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    if not lines or lines[0] != "PROTOCOL\towl-dl-v1" or lines[-1] != "END\towl-dl-v1":
        raise ToolError("Incomplete or invalid OWL DL bridge protocol; no consistency verdict")
    result = {}
    singles = {"PROTOCOL", "END", "PROFILE", "CONSISTENT", "REASONER", "VERSION", "OWLAPI",
               "AXIOMS", "LOGICAL_AXIOMS", "JAVA_VERSION", "JAVA_VENDOR", "HERMIT_ARTIFACT"}
    encoded = {"UNSAT", "VIOLATION", "ERROR"}
    for line in lines:
        key, sep, value = line.partition("\t")
        if not sep or key not in singles | encoded or (key in singles and key in result):
            raise ToolError("Malformed OWL DL bridge protocol")
        if key in encoded:
            try:
                value = base64.b64decode(value, validate=True).decode("utf-8")
            except Exception as exc:
                raise ToolError("Malformed encoded OWL DL bridge value") from exc
        result.setdefault(key, []).append(value)
    if "ERROR" in result:
        raise ToolError("; ".join(result["ERROR"]))
    if result.get("PROFILE") not in (["true"], ["false"]):
        raise ToolError("Missing OWL 2 DL profile result")
    for key in ("OWLAPI", "AXIOMS", "LOGICAL_AXIOMS"):
        if key not in result:
            raise ToolError(f"Missing bridge field: {key}")
    if result["PROFILE"] == ["false"]:
        if "CONSISTENT" in result or "UNSAT" in result or not result.get("VIOLATION"):
            raise ToolError("Invalid profile failure result")
    elif (result.get("CONSISTENT") not in (["true"], ["false"])
          or "REASONER" not in result or "VERSION" not in result or "VIOLATION" in result):
        raise ToolError("Missing or contradictory reasoner result")
    if result.get("CONSISTENT") == ["false"] and "UNSAT" in result:
        raise ToolError("An inconsistent ontology cannot have a usable classification result")
    return result


def check_consistency(ontology, output, *, facts=None, imports=None, java="java", timeout=60) -> Path:
    """Check explicit local OWL sources with HermiT; preserve evidence on failure.

    Return the new output directory for a completed semantic result. Operational
    and profile errors raise ToolError; only a completed reasoner execution may
    assert ot:consistent. Unsatisfiable named classes are separate from global
    inconsistency and make acceptance nonconformant even when consistent=true.
    """
    ontologies = _paths(ontology, required=True)
    fact_paths = _paths(facts)
    sources = ontologies + fact_paths + ([] if imports is None else [Path(imports).resolve()])
    # Protect imported packages before creating the output directory. The map
    # enumerates every permitted transitive import, so no network discovery or
    # traversal is needed. Map syntax errors are handled below with evidence.
    if imports is not None:
        mapping_path = Path(imports).resolve()
        try:
            mapping = _parse(mapping_path.read_bytes(), mapping_path)
            for item in mapping.subjects(RDF.type, OT.ImportMapping):
                for relative in mapping.objects(item, OT.path):
                    if isinstance(relative, Literal):
                        sources.append(safe_path(mapping_path.parent, str(relative)).resolve())
        except Exception:
            pass
    protected = [ROOT]
    for path in sources:
        protected.extend(_protected_roots(path))
    output = new_output(Path(output), *protected)
    evidence = Graph()
    report = Graph()
    evidence.add((RUN, RDF.type, OT.Execution))
    evidence.add((RUN, OT.profile, Literal(PROFILE)))
    from . import __version__
    evidence.add((RUN, OT.version, Literal(__version__)))
    evidence.add((RUN, OT.stage, Literal("owl-dl")))
    evidence.add((RUN, OT.javaExecutable, Literal(str(java))))
    evidence.add((RUN, OT.startedAt, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    report.add((RUN, RDF.type, OT.OWLConsistencyReport))
    report.add((RUN, OT.profile, Literal(PROFILE)))
    report.add((RUN, OT.ruleExecution, Literal("not_run")))
    report.add((RUN, OT.scope, Literal("Explicit OWL inputs and verified local import closure; SWRL excluded")))
    status, error, exit_code = "failed", None, 2
    try:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ToolError("timeout must be a finite positive number of seconds")
        combined = _load_inputs(ontologies, fact_paths, imports, output, evidence)
        assembled = output / "assembled.rdf"
        combined.serialize(destination=assembled, format="xml", encoding="utf-8")
        evidence.add((RUN, OT.assembledSHA256, Literal(sha256(assembled))))
        evidence.add((RUN, OT.inputTriples, Literal(len(combined))))
        classpath = _runtime(output, evidence)
        command = [str(java), "-Dfile.encoding=UTF-8", "-cp", classpath, "OwlDlCheck", str(assembled)]
        # Each row is an argument, not an executable shell command.
        if any("\n" in arg or "\r" in arg for arg in command):
            raise ToolError("Newline in Java command argument")
        (output / "command.txt").write_text("\n".join(command) + "\n", encoding="utf-8")
        evidence.add((RUN, OT.timeoutSeconds, Literal(timeout)))
        try:
            process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            for name, data in (("java-stdout.txt", exc.stdout), ("java-stderr.txt", exc.stderr)):
                (output / name).write_text(data.decode("utf-8", "replace") if isinstance(data, bytes) else data or "", encoding="utf-8")
            raise ToolError(f"OWL DL reasoner timed out after {timeout} seconds; result unknown") from exc
        (output / "java-stdout.txt").write_text(process.stdout, encoding="utf-8")
        (output / "java-stderr.txt").write_text(process.stderr, encoding="utf-8")
        evidence.add((RUN, OT.javaExitCode, Literal(process.returncode)))
        if process.returncode != 0:
            raise ToolError(f"OWL DL bridge failed (exit {process.returncode}); see java-stdout.txt and java-stderr.txt")
        result = _protocol(process.stdout)
        for key, predicate in (("OWLAPI", OT.owlapiVersion), ("REASONER", OT.reasoner),
                               ("VERSION", OT.reasonerVersion), ("JAVA_VERSION", OT.javaVersion),
                               ("JAVA_VENDOR", OT.javaVendor), ("HERMIT_ARTIFACT", OT.hermitArtifactVersion)):
            if key in result:
                evidence.add((RUN, predicate, Literal(result[key][0])))
        report.add((RUN, OT.profileConforms, Literal(result["PROFILE"] == ["true"])))
        for key, predicate in (("AXIOMS", OT.axiomCount), ("LOGICAL_AXIOMS", OT.logicalAxiomCount)):
            report.add((RUN, predicate, Literal(int(result[key][0]))))
        for violation in result.get("VIOLATION", []):
            report.add((RUN, OT.profileViolation, Literal(violation)))
        if result["PROFILE"] == ["false"]:
            raise ToolError("Input is outside OWL 2 DL; see profile violations in report.ttl")
        consistent = result["CONSISTENT"] == ["true"]
        unsatisfiable = sorted(set(result.get("UNSAT", [])))
        if str(OWL.Nothing) in unsatisfiable or any(not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", iri) for iri in unsatisfiable):
            raise ToolError("Invalid unsatisfiable-class list from reasoner")
        # Commit the semantic verdict only after validating the complete protocol.
        report.add((RUN, OT.consistent, Literal(consistent)))
        for iri in unsatisfiable:
            report.add((RUN, OT.unsatisfiableClass, URIRef(iri)))
        status = "passed" if consistent and not unsatisfiable else "nonconformant"
        exit_code = 0 if status == "passed" else 1
    except Exception as exc:
        error = str(exc)
        # Never retain a partial verdict on operational failure.
        report.remove((RUN, OT.consistent, None))
        report.remove((RUN, OT.unsatisfiableClass, None))
    evidence.add((RUN, OT.status, Literal(status)))
    evidence.add((RUN, OT.exitCode, Literal(exit_code)))
    evidence.add((RUN, OT.finishedAt, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    if error is not None:
        evidence.add((RUN, OT.error, Literal(error)))
    write_graph(report, output / "report.ttl")
    write_graph(evidence, output / "execution.ttl")
    consistent_value = report.value(RUN, OT.consistent)
    verdict = str(consistent_value) if consistent_value is not None else "unknown (not established)"
    names = sorted(map(str, report.objects(RUN, OT.unsatisfiableClass)))
    summary = (f"# OWL DL consistency check\n\nStatus: {status}\n\n"
               f"Profile: {PROFILE}\n\nGlobal consistency: {verdict}\n\n"
               f"Unsatisfiable named classes: {len(names) if consistent_value == Literal(True) else 'not classified'}\n\n"
               "SWRL execution: not_run. SHACL and business golden cases are separate checks.\n\n"
               "Scope: only the recorded inputs and verified local imports. Original files are unchanged.\n\n"
               "Reproduce with this tool bundle (runtime.sha256), the recorded Java version and assembled.rdf. "
               "Input snapshots and manifest.sha256 preserve the exact evidence.\n")
    if names:
        summary += "\n" + "\n".join(f"- `{name}`" for name in names) + "\n"
    if error is not None:
        summary += f"\nError: {error}\n"
    (output / "report.md").write_text(summary, encoding="utf-8")
    write_manifest(output)
    if error is not None:
        raise ToolError(error)
    return output


_CANDIDATES = {
    "CAND_INDIVIDUAL": OT.individual, "CAND_CLASS": OT["class"],
    "CAND_OBJECT": OT.objectProperty, "CAND_DATA": OT.dataProperty,
    "CAND_LITERAL": OT.literal,
}
_PROJECTION_COUNTS = {"CANDIDATE_COUNT", "CLASSIFICATION_COUNT", "FACT_COUNT", "PROJECTION_SHA256"}
_PROJECTION_ROWS = set(_CANDIDATES) | {"SUBCLASS", "EQUIVALENT", "TYPE", "SAME", "OBJECT", "DATA"}
DOMAIN = URIRef("urn:ontology-tools:candidates")


def _literal_parts(value: Literal) -> tuple[str, str, str]:
    return str(value), str(RDF.langString if value.language else value.datatype or XSD.string), value.language or ""


def _iri(value: str) -> URIRef:
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]*$", value):
        raise ToolError("Projection contains a malformed absolute IRI")
    return URIRef(value)


def _domain_values(graph: Graph) -> dict[str, set]:
    heads = set(graph.subjects(RDF.type, OT.CandidateDomain))
    if len(heads) != 1:
        raise ToolError("Candidate domain requires exactly one ot:CandidateDomain")
    head = next(iter(heads))
    permitted = set(_CANDIDATES.values())
    values = {key: set(graph.objects(head, predicate)) for key, predicate in _CANDIDATES.items()}
    for subject, predicate, value in graph:
        if subject != head or not (predicate in permitted or (predicate == RDF.type and value == OT.CandidateDomain)):
            raise ToolError("Unexpected candidate-domain triple; candidates are metadata, not OWL facts")
    for key, entries in values.items():
        for value in entries:
            if key == "CAND_LITERAL":
                if not isinstance(value, Literal):
                    raise ToolError("Candidate literal must be an RDF literal")
                if value.datatype is not None:
                    _iri(str(value.datatype))
            elif not isinstance(value, URIRef):
                raise ToolError("Candidate entity must be a named absolute IRI")
            else:
                _iri(str(value))
    return values


def _encoded(parts) -> str:
    return "\t".join(base64.b64encode(part.encode("utf-8")).decode("ascii") for part in parts)


def _domain_protocol(graph: Graph) -> str:
    values = _domain_values(graph)
    rows = []
    for kind, items in values.items():
        key = kind.removeprefix("CAND_")
        rows.extend(key + "\t" + _encoded(_literal_parts(v) if kind == "CAND_LITERAL" else (str(v),)) for v in items)
    # RDF 1.1 plain strings and explicit xsd:string are one candidate value.
    # A caller may merge both syntactic forms from rule and ontology files.
    return "DOMAIN\towl-projection-v1\n" + "".join(row + "\n" for row in sorted(set(rows))) + "END\towl-projection-v1\n"


def _decode_projection_literal(parts) -> Literal:
    lexical, datatype, lang = parts
    datatype = _iri(datatype)
    if lang:
        if datatype != RDF.langString or not re.fullmatch(r"[A-Za-z]+(?:-[A-Za-z0-9]+)*", lang):
            raise ToolError("Malformed language literal in projection")
        return Literal(lexical, lang=lang, normalize=False)
    if datatype == RDF.langString:
        raise ToolError("rdf:langString requires a language tag")
    return Literal(lexical, datatype=datatype, normalize=False)


def _projection_protocol(text: str, mode: str, frozen: Graph | None = None):
    """Reject truncated, extra, mis-typed or out-of-domain bridge output."""
    lines = text.splitlines()
    if (not lines or lines[0] != "PROTOCOL\towl-projection-v1"
            or lines[-1] != "END\towl-projection-v1" or lines.count(f"MODE\t{mode}") != 1):
        raise ToolError("Incomplete or invalid OWL projection bridge protocol")
    standard = []
    payload, counts = [], {}
    candidates, classification, facts = Graph(), Graph(), Graph()
    candidates.add((DOMAIN, RDF.type, OT.CandidateDomain))
    decoded = []
    for line in lines:
        key, sep, value = line.partition("\t")
        if not sep:
            raise ToolError("Malformed projection bridge protocol")
        if key in _PROJECTION_COUNTS:
            if key in counts:
                raise ToolError("Duplicate projection count or checksum")
            counts[key] = value
        elif key in _PROJECTION_ROWS:
            if line in payload:
                raise ToolError("Duplicate projection row")
            payload.append(line)
            try:
                parts = [base64.b64decode(item, validate=True).decode("utf-8") for item in value.split("\t")]
            except Exception as exc:
                raise ToolError("Malformed encoded projection value") from exc
            expected = 3 if key == "CAND_LITERAL" or key == "OBJECT" else 5 if key == "DATA" else 1 if key in _CANDIDATES else 2
            if len(parts) != expected:
                raise ToolError("Wrong projection row arity")
            decoded.append((key, parts))
        elif key == "MODE":
            if value != mode:
                raise ToolError("Wrong projection mode")
        elif key in {"PROTOCOL", "END"}:
            standard.append(key + "\towl-dl-v1")
        else:
            standard.append(line)
    # Candidate collection deliberately does not create a reasoner or a
    # consistency verdict. Reuse the strict v1 checker with synthetic structural
    # fields only for parsing; never persist those synthetic fields as a verdict.
    candidate_only = mode == "candidates"
    if candidate_only and any(line.startswith(("CONSISTENT\t", "REASONER\t", "VERSION\t", "UNSAT\t")) for line in standard):
        raise ToolError("Candidate extraction must not report a consistency verdict")
    if candidate_only and "PROFILE\ttrue" in standard:
        standard[-1:-1] = ["CONSISTENT\ttrue", "REASONER\tcandidate-domain-parser", "VERSION\t1"]
    result = _protocol("\n".join(standard))
    if candidate_only:
        for key in ("CONSISTENT", "REASONER", "VERSION"):
            result.pop(key, None)
    successful = result["PROFILE"] == ["true"] and (candidate_only or (
        result.get("CONSISTENT") == ["true"] and not result.get("UNSAT")))
    if not successful:
        if payload or counts:
            raise ToolError("Nonconformant OWL run cannot expose usable projection output")
        return result, None, None, None
    if set(counts) != _PROJECTION_COUNTS:
        raise ToolError("Missing projection counts or checksum")
    digest = hashlib.sha256("".join(row + "\n" for row in payload).encode("utf-8")).hexdigest()
    actual_counts = {
        "CANDIDATE_COUNT": sum(key in _CANDIDATES for key, _ in decoded),
        "CLASSIFICATION_COUNT": sum(key in {"SUBCLASS", "EQUIVALENT"} for key, _ in decoded),
        "FACT_COUNT": sum(key in {"TYPE", "SAME", "OBJECT", "DATA"} for key, _ in decoded),
    }
    if counts["PROJECTION_SHA256"] != digest or any(counts[key] != str(value) for key, value in actual_counts.items()):
        raise ToolError("Projection count/checksum mismatch")
    for key, parts in decoded:
        if key in _CANDIDATES:
            value = _decode_projection_literal(parts) if key == "CAND_LITERAL" else _iri(parts[0])
            candidates.add((DOMAIN, _CANDIDATES[key], value))
    domains = _domain_values(candidates)
    if frozen is not None:
        expected = _domain_values(frozen)
        for kind in expected:
            actual = domains[kind]
            # RDF 1.1 plain strings and explicit xsd:string denote the same
            # literal, but rdflib gives them distinct Python term identities.
            if kind == "CAND_LITERAL":
                actual = {_literal_parts(value) for value in actual}
                wanted = {_literal_parts(value) for value in expected[kind]}
            else:
                wanted = expected[kind]
            if actual != wanted:
                raise ToolError("The bridge expanded or altered the frozen candidate domain")
    def member(value, kind):
        if value not in domains[kind]:
            raise ToolError(f"Projection value outside frozen domain: {kind}")
        return value
    for key, parts in decoded:
        if key in _CANDIDATES:
            continue
        subject = _iri(parts[0])
        if key in {"SUBCLASS", "EQUIVALENT"}:
            member(subject, "CAND_CLASS")
            obj = member(_iri(parts[1]), "CAND_CLASS")
            if subject == obj:
                raise ToolError("Projection must omit reflexive class tautologies")
            classification.add((subject, RDFS.subClassOf if key == "SUBCLASS" else OWL.equivalentClass, obj))
            continue
        member(subject, "CAND_INDIVIDUAL")
        if key == "TYPE":
            triple = (subject, RDF.type, member(_iri(parts[1]), "CAND_CLASS"))
        elif key == "SAME":
            triple = (subject, OWL.sameAs, member(_iri(parts[1]), "CAND_INDIVIDUAL"))
            if triple[0] == triple[2]:
                raise ToolError("Projection must omit reflexive sameAs tautologies")
        elif key == "OBJECT":
            triple = (subject, member(_iri(parts[1]), "CAND_OBJECT"), member(_iri(parts[2]), "CAND_INDIVIDUAL"))
        else:
            triple = (subject, member(_iri(parts[1]), "CAND_DATA"), member(_decode_projection_literal(parts[2:]), "CAND_LITERAL"))
        facts.add(triple)
    if candidate_only and (classification or facts):
        raise ToolError("Candidate extraction cannot emit inferred facts")
    return result, candidates, classification, facts


def _projection_run(ontology, output, *, facts=None, imports=None, java="java", timeout=60,
                    candidates=None, mode="infer") -> Path:
    from . import __version__
    ontologies, fact_paths = _paths(ontology, required=True), _paths(facts)
    sources = ontologies + fact_paths
    if imports is not None:
        map_path = Path(imports).resolve()
        sources.append(map_path)
        try:
            mapping = _parse(map_path.read_bytes(), map_path)
            sources.extend(safe_path(map_path.parent, str(relative)).resolve()
                           for item in mapping.subjects(RDF.type, OT.ImportMapping)
                           for relative in mapping.objects(item, OT.path) if isinstance(relative, Literal))
        except Exception:
            pass  # Detailed, evidence-preserving validation follows below.
    if candidates is not None:
        sources.append(Path(candidates).resolve())
    protected = [ROOT]
    for source in sources:
        protected.extend(_protected_roots(source))
    output = new_output(Path(output), *protected)
    evidence, report = Graph(), Graph()
    stage = "owl-infer" if mode == "infer" else "candidates"
    evidence.add((RUN, RDF.type, OT.Execution))
    for predicate, value in ((OT.profile, INFER_PROFILE), (OT.stage, stage),
                             (OT.version, __version__), (OT.javaExecutable, str(java))):
        evidence.add((RUN, predicate, Literal(value)))
    evidence.add((RUN, OT.startedAt, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    report.add((RUN, RDF.type, OT.OWLProjectionReport if mode == "infer" else OT.CandidateDomainReport))
    report.add((RUN, OT.profile, Literal(INFER_PROFILE)))
    report.add((RUN, OT.scope, Literal("Finite named-entity and literal projection; no anonymous witnesses; not a complete OWL closure")))
    report.add((RUN, OT.ruleExecution, Literal("not_run")))
    status, error, exit_code = "failed", None, 2
    try:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ToolError("timeout must be a finite positive number of seconds")
        combined = _load_inputs(ontologies, fact_paths, imports, output, evidence)
        assembled = output / "assembled.rdf"
        combined.serialize(destination=assembled, format="xml", encoding="utf-8")
        write_graph(combined, output / "input.ttl")
        evidence.add((RUN, OT.assembledSHA256, Literal(sha256(assembled))))
        evidence.add((RUN, OT.inputTriples, Literal(len(combined))))
        classpath = _runtime(output, evidence)
        command = [str(java), "-Dfile.encoding=UTF-8", "-cp", classpath, "OwlDlCheck", str(assembled), mode]
        frozen = None
        if candidates is not None:
            index = len(set(evidence.objects(RUN, OT.input)))
            frozen, _ = _snapshot(Path(candidates).resolve(), "CandidateDomain", output, evidence, index)
            candidate_protocol = output / "candidate-domain.tsv"
            candidate_protocol.write_text(_domain_protocol(frozen), encoding="utf-8")
            command.append(str(candidate_protocol))
        if any("\n" in arg or "\r" in arg for arg in command):
            raise ToolError("Newline in Java command argument")
        (output / "command.txt").write_text("\n".join(command) + "\n", encoding="utf-8")
        evidence.add((RUN, OT.timeoutSeconds, Literal(timeout)))
        try:
            process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            for name, data in (("java-stdout.txt", exc.stdout), ("java-stderr.txt", exc.stderr)):
                (output / name).write_text(data.decode("utf-8", "replace") if isinstance(data, bytes) else data or "", encoding="utf-8")
            raise ToolError(f"OWL DL reasoner timed out after {timeout} seconds; result unknown") from exc
        (output / "java-stdout.txt").write_text(process.stdout, encoding="utf-8")
        (output / "java-stderr.txt").write_text(process.stderr, encoding="utf-8")
        evidence.add((RUN, OT.javaExitCode, Literal(process.returncode)))
        if process.returncode:
            raise ToolError(f"OWL DL bridge failed (exit {process.returncode}); see java-stdout.txt and java-stderr.txt")
        result, domain_graph, classification, projected_facts = _projection_protocol(process.stdout, mode, frozen)
        for key, predicate in (("OWLAPI", OT.owlapiVersion), ("REASONER", OT.reasoner),
                               ("VERSION", OT.reasonerVersion), ("JAVA_VERSION", OT.javaVersion),
                               ("JAVA_VENDOR", OT.javaVendor), ("HERMIT_ARTIFACT", OT.hermitArtifactVersion)):
            if key in result:
                evidence.add((RUN, predicate, Literal(result[key][0])))
        report.add((RUN, OT.profileConforms, Literal(result["PROFILE"] == ["true"])))
        for key, predicate in (("AXIOMS", OT.axiomCount), ("LOGICAL_AXIOMS", OT.logicalAxiomCount)):
            report.add((RUN, predicate, Literal(int(result[key][0]))))
        for violation in result.get("VIOLATION", []):
            report.add((RUN, OT.profileViolation, Literal(violation)))
        if result["PROFILE"] == ["false"]:
            raise ToolError("Input is outside OWL 2 DL; see profile violations in report.ttl")
        if mode == "infer":
            consistent = result["CONSISTENT"] == ["true"]
            unsatisfiable = sorted(set(result.get("UNSAT", [])))
            for value in unsatisfiable:
                if _iri(value) == OWL.Nothing:
                    raise ToolError("Invalid unsatisfiable-class list from reasoner")
            report.add((RUN, OT.consistent, Literal(consistent)))
            for value in unsatisfiable:
                report.add((RUN, OT.unsatisfiableClass, URIRef(value)))
            status = "passed" if consistent and not unsatisfiable else "nonconformant"
        else:
            status = "passed"
        exit_code = 0 if status == "passed" else 1
        if domain_graph is not None:
            write_graph(domain_graph, output / "candidates.ttl")
        if mode == "infer" and status == "passed":
            novel = (classification + projected_facts) - combined
            closure = combined + novel
            trace = Graph()
            trace.add((RUN, RDF.type, OT.EntailmentSnapshot))
            trace.add((RUN, OT.evidenceKind, Literal("HermiT entailment from recorded input snapshot; not an axiom-level proof")))
            trace.add((RUN, OT.inputSnapshot, Literal("input.ttl")))
            trace.add((RUN, OT.candidateSnapshot, Literal("candidates.ttl")))
            trace.add((RUN, OT.runtimeDigest, evidence.value(RUN, OT.runtimeDigest)))
            for number, (subject, predicate, obj) in enumerate(sorted(novel, key=lambda t: tuple(v.n3() for v in t))):
                node = URIRef(f"urn:ontology-tools:entailment:{number}")
                trace.add((RUN, OT.entailment, node))
                trace.add((node, RDF.subject, subject))
                trace.add((node, RDF.predicate, predicate))
                trace.add((node, RDF.object, obj))
                trace.add((node, OT.derivedBy, RUN))
            for graph, name in ((classification, "classification.ttl"), (projected_facts, "facts.ttl"),
                                (novel, "result.ttl"), (closure, "closure.ttl"), (trace, "trace.ttl")):
                write_graph(graph, output / name)
            evidence.add((RUN, OT.resultTriples, Literal(len(novel))))
            evidence.add((RUN, OT.classificationTriples, Literal(len(classification))))
            evidence.add((RUN, OT.factTriples, Literal(len(projected_facts))))
    except Exception as exc:
        error, status, exit_code = str(exc), "failed", 2
        report.remove((RUN, OT.consistent, None))
        report.remove((RUN, OT.unsatisfiableClass, None))
        # A filesystem write error must not leave an apparently accepted graph.
        for name in ("classification.ttl", "facts.ttl", "result.ttl", "closure.ttl", "trace.ttl"):
            (output / name).unlink(missing_ok=True)
    evidence.add((RUN, OT.status, Literal(status)))
    evidence.add((RUN, OT.exitCode, Literal(exit_code)))
    evidence.add((RUN, OT.finishedAt, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    if error:
        evidence.add((RUN, OT.error, Literal(error)))
    write_graph(report, output / "report.ttl")
    write_graph(evidence, output / "execution.ttl")
    summary = (f"# OWL DL {'projection' if mode == 'infer' else 'candidate collection'}\n\n"
               f"Status: {status}\n\nProfile: {INFER_PROFILE}\n\n"
               "Scope: finite recorded named-entity/literal domain. No anonymous witnesses, "
               "no SWRL execution and no claim of a complete OWL closure.\n\n"
               "Evidence identifies HermiT entailment from an exact input snapshot, not an axiom-level proof.\n")
    if mode == "candidates":
        summary += "\nCandidate extraction performs no consistency or satisfiability reasoning.\n"
    if error:
        summary += f"\nError: {error}\n"
    (output / "report.md").write_text(summary, encoding="utf-8")
    write_manifest(output)
    if error:
        raise ToolError(error)
    return output


def infer_owl(ontology, output, *, facts=None, imports=None, java="java", timeout=60, candidates=None) -> Path:
    """Export HermiT entailments over a finite named-entity/literal domain.

    A supplied CandidateDomain TTL freezes the exact projection scope. Its
    entities must occur with the stated roles in the OWL semantic signature.
    Only a completed, consistent and satisfiable run publishes usable graphs.
    """
    return _projection_run(ontology, output, facts=facts, imports=imports, java=java,
                           timeout=timeout, candidates=candidates)


def collect_candidates(ontology, output, *, facts=None, imports=None, java="java", timeout=60) -> Path:
    """Collect OWLAPI semantic signatures and non-annotation literal values.

    Return a new evidence directory containing candidates.ttl; this operation
    checks complete OWL loading and the DL profile but does not run a reasoner.
    """
    return _projection_run(ontology, output, facts=facts, imports=imports, java=java,
                           timeout=timeout, mode="candidates")
