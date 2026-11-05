"""Local-only RDF I/O, fingerprints and exact package manifests."""
from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import re
import threading
from pathlib import Path, PurePosixPath
from decimal import Decimal

import rdflib
from rdflib import Graph, Namespace, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import OWL, XSD

OT = Namespace("https://w3id.org/ontology-tools#")
PROFILE = "local-rules-v1"
_PARSE_LOCK = threading.RLock()


class ToolError(ValueError):
    exit_code = 2


class ValidationError(ToolError):
    exit_code = 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    """Paths in data are relative POSIX paths, never drives, URLs or traversal."""
    pure = PurePosixPath(relative)
    if not relative or "\\" in relative or ":" in relative or pure.is_absolute() or ".." in pure.parts:
        raise ToolError(f"Unsafe relative path: {relative}")
    candidate = root.joinpath(*pure.parts)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ToolError(f"Path escapes package: {relative}")
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ToolError(f"Links are not allowed in package paths: {relative}")
        cursor = cursor.parent
    return candidate


def file_set(root: Path) -> dict[str, Path]:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        safe_path(root, relative)
        if path.is_file():
            result[relative] = path
    return result


def write_manifest(root: Path) -> Path:
    target = root / "manifest.sha256"
    if target.exists():
        raise ToolError(f"Manifest already exists; create a new package/run version: {target}")
    lines = [f"{sha256(path)}  {rel}\n" for rel, path in file_set(root).items() if rel != "manifest.sha256"]
    target.write_text("".join(lines), encoding="utf-8")
    return target


def verify_manifest(root: Path, required=False) -> bool:
    manifest = root / "manifest.sha256"
    if not manifest.exists():
        if required:
            raise ToolError(f"Missing manifest: {manifest}")
        return False
    expected = {}
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        if not match:
            raise ToolError("Malformed manifest entry")
        digest, relative = match.groups()
        path = safe_path(root, relative)
        if relative in expected or relative == "manifest.sha256":
            raise ToolError(f"Duplicate/self manifest entry: {relative}")
        expected[relative] = digest.lower()
        if not path.is_file() or sha256(path) != digest.lower():
            raise ToolError(f"Manifest mismatch: {relative}")
    actual = set(file_set(root)) - {"manifest.sha256"}
    if actual != set(expected):
        raise ToolError(f"Manifest file set mismatch: {sorted(actual ^ set(expected))}")
    return True


def enclosing_packages(path: Path) -> list[Path]:
    """Protect and verify each declared package/run containing an input file."""
    protected = []
    for ancestor in Path(path).resolve().parents:
        if (ancestor / "manifest.sha256").exists():
            verify_manifest(ancestor, required=True)
            protected.append(ancestor)
        elif (ancestor / "ontology.ttl").is_file():
            protected.append(ancestor)
    return protected


def parse_graph_lexically(graph, text, fmt, public_id):
    """Preserve explicit lexical errors and valid Turtle decimal shorthand.

    RDFLib 7.1.4 converts bare Turtle decimals through Python Decimal and str(),
    which spells sufficiently small values with E notation. With normalization
    disabled (needed to retain malformed explicit typed literals), that creates
    invalid xsd:decimal lexical forms from valid input. A local sink fixes only
    Python Decimal tokens; quoted typed literals still retain their exact bytes.
    No third-party module or global parser registry is changed.
    """
    if fmt != "turtle":
        graph.parse(data=text, format=fmt, publicID=public_id)
        return graph
    from rdflib import Literal
    from rdflib.plugins.parsers.notation3 import RDFSink, SinkParser

    class DecimalSink(RDFSink):
        def normalise(self, formula, node):
            if isinstance(node, Decimal):
                return Literal(format(node, "f"), datatype=XSD.decimal, normalize=False)
            return super().normalise(formula, node)

    parser = SinkParser(DecimalSink(graph), baseURI=graph.absolutize(public_id), turtle=True)
    parser.loadBuf(text)
    for prefix, namespace in parser._bindings.items():
        graph.bind(prefix, namespace)
    return graph


def parse_rdf(path: Path) -> Graph:
    path = Path(path).resolve()
    if not path.is_file():
        raise ToolError(f"Missing local RDF file: {path}")
    if path.suffix.lower() not in {".ttl", ".swrl", ".rdf", ".owl", ".nt"}:
        raise ToolError(f"Unsupported RDF file format: {path.suffix}")
    text = path.read_text(encoding="utf-8-sig")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.I):
        raise ToolError("RDF/XML DTD and entities are disabled")
    fmt = "turtle" if path.suffix.lower() == ".ttl" else "nt" if path.suffix.lower() == ".nt" else "xml"
    # Fixed base avoids path-dependent relative IRIs when replaying a snapshot.
    graph = Graph()
    # Preserve lexical evidence, including malformed literals that a Python
    # numeric constructor might otherwise normalize into apparently valid data.
    # All tool parses share a lock; restore the caller's RDFLib setting.
    with _PARSE_LOCK:
        normalize = rdflib.NORMALIZE_LITERALS
        try:
            rdflib.NORMALIZE_LITERALS = False
            parse_graph_lexically(graph, text, fmt, "urn:ontology-tools:local:")
        finally:
            rdflib.NORMALIZE_LITERALS = normalize
    if any(graph.triples((None, OWL.imports, None))):
        raise ToolError("owl:imports is unsupported by this offline profile; provide a merged local model")
    return graph


def stable_graph(graph: Graph) -> Graph:
    result = Graph()
    for triple in to_canonical_graph(graph):
        result.add(triple)
    return result


def write_graph(graph: Graph, path: Path) -> Path:
    """Sorted N-Triples is also valid Turtle; never serialize JSON."""
    canonical = stable_graph(graph)
    lines = sorted(f"{s.n3()} {p.n3()} {o.n3()} .\n" for s, p, o in canonical)
    path.parent.mkdir(parents=True, exist_ok=True)
    # n3() escapes literal CR characters but may retain LF inside long strings.
    # Windows text translation would turn each LF into CRLF and silently change
    # the RDF literal each time a snapshot is written and reparsed.
    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return path


def code_files() -> dict[str, Path]:
    root = Path(__file__).resolve().parent.parent
    files = {p.relative_to(root).as_posix(): p for p in sorted((root / "ontology_tools").glob("*.py"))}
    files["requirements.txt"] = root / "requirements.txt"
    files["requirements.lock.txt"] = root / "requirements.lock.txt"
    return files


def code_digest() -> str:
    payload = "".join(f"{rel} {sha256(path)}\n" for rel, path in sorted(code_files().items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def environment() -> dict[str, str]:
    # Include the transitive installed dependencies actually used by this tool.
    from packaging.requirements import Requirement
    pending = ["rdflib", "pyshacl", "packaging"]
    result = {"python": platform.python_version(), "implementation": platform.python_implementation()}
    while pending:
        name = pending.pop().lower().replace("_", "-")
        if name in result:
            continue
        result[name] = importlib.metadata.version(name)
        for raw in importlib.metadata.requires(name) or []:
            dependency = Requirement(raw)
            if dependency.marker is None or dependency.marker.evaluate({"extra": ""}):
                pending.append(dependency.name)
    return result


def new_output(output: Path, *protected: Path) -> Path:
    output = Path(output).resolve()
    for root in protected:
        root = Path(root).resolve()
        if output == root or output.is_relative_to(root):
            raise ToolError(f"Output must be outside the input package/run: {output}")
    if output.exists():
        raise ToolError(f"Output already exists; use a new directory: {output}")
    output.mkdir(parents=True)
    return output
