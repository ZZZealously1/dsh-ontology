"""CLI for the public local reasoning, validation and replay operations."""
import argparse
import sys
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import SH

from . import __version__
from .core import (RUN, infer_graph, inspect_package, query_graph, replay_run,
                   run_cases, validate_graph)
from .io import OT, ToolError, parse_rdf, write_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline native OWL/SWRL/SHACL tools; no JSON or external services")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="operation", required=True)
    for name in ("inspect", "validate", "infer", "test", "freeze"):
        child = subs.add_parser(name)
        child.add_argument("--package", required=True, type=Path)
        if name != "freeze":
            child.add_argument("--output", required=True, type=Path)
        if name in {"validate", "infer"}:
            child.add_argument("--facts", type=Path)
    child = subs.add_parser("query")
    child.add_argument("--graph", required=True, type=Path)
    child.add_argument("--query", required=True, type=Path)
    child.add_argument("--output", required=True, type=Path)
    child = subs.add_parser("replay")
    child.add_argument("--run", required=True, type=Path)
    child.add_argument("--output", required=True, type=Path)
    for operation in ("owl-dl", "owl-infer"):
        child = subs.add_parser(operation)
        child.add_argument("--ontology", required=True, action="append", type=Path)
        child.add_argument("--facts", action="append", type=Path)
        child.add_argument("--imports-map", type=Path)
        child.add_argument("--output", required=True, type=Path)
        child.add_argument("--java", default="java")
        child.add_argument("--timeout", default=60, type=float)
        if operation == "owl-infer":
            child.add_argument("--candidates", type=Path,
                               help="Optional frozen candidate-domain Turtle file")
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.operation == "inspect":
            inspect_package(args.package, output=args.output)
        elif args.operation == "validate":
            report = validate_graph(args.package, facts=args.facts, output=args.output)
            code = 0 if (None, SH.conforms, Literal(True)) in report else 3
        elif args.operation == "infer":
            out = infer_graph(args.package, facts=args.facts, output=args.output)
            record = parse_rdf(out / "execution.ttl")
            code = int(record.value(RUN, OT.exitCode) or 0)
        elif args.operation == "query":
            query_graph(args.graph, args.query, args.output)
        elif args.operation == "test":
            out = run_cases(args.package, args.output)
            code = 0 if str(parse_rdf(out / "test-report.ttl").value(RUN, OT.status)) == "passed" else 1
        elif args.operation == "replay":
            out = replay_run(args.run, args.output)
            code = 0 if str(parse_rdf(out / "replay-report.ttl").value(RUN, OT.status)) == "passed" else 1
        elif args.operation in {"owl-dl", "owl-infer"}:
            from .owl_dl import check_consistency, infer_owl
            operation = check_consistency if args.operation == "owl-dl" else infer_owl
            extra = {} if args.operation == "owl-dl" else {"candidates": args.candidates}
            out = operation(args.ontology, args.output, facts=args.facts,
                            imports=args.imports_map, java=args.java, timeout=args.timeout, **extra)
            code = 0 if str(parse_rdf(out / "execution.ttl").value(RUN, OT.status)) == "passed" else 1
        else:
            inspect_package(args.package)
            print(write_manifest(args.package.resolve()))
            return 0
        print(f"{args.operation}: {'passed' if code == 0 else 'failed'}; output={args.output.resolve()}")
        return code
    except Exception as exc:
        print(f"{args.operation}: failed: {exc}", file=sys.stderr)
        return getattr(exc, "exit_code", 2)


if __name__ == "__main__":
    raise SystemExit(main())
