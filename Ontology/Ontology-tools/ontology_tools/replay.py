"""Replay completed OWL checks and finite projections from saved local evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess

from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic

from .io import (OT, ToolError, code_digest, environment, new_output, parse_rdf,
                 safe_path, verify_manifest, write_graph)

RUN = URIRef("urn:ontology-tools:run")
PROJECTION = "hermit-swrl-projection-v1"
CALCULATION = "hermit-swrl-calculation-v1"
FORMULA = "hermit-swrl-formula-v1"
OWL_PROFILES = {"owl-dl-hermit-v1", "owl-dl-projection-v1"}


def _check_environment(original):
    digest = original.value(RUN, OT.engineDigest)
    if digest is not None and str(digest) != code_digest():
        raise ToolError("Runtime source fingerprint changed; use the recorded runtime version")
    expected = {str(original.value(n, OT.name)): str(original.value(n, OT.version))
                for n in original.objects(RUN, OT.dependency)}
    actual = environment()
    if expected and expected != actual:
        raise ToolError("Dependency/Python versions differ from the recorded run")
    for predicate, key in ((OT.pythonVersion, "python"), (OT.rdflibVersion, "rdflib")):
        saved = original.value(RUN, predicate)
        if saved is not None and str(saved) != actual[key]:
            raise ToolError(f"Recorded {key} version differs from the current runtime")


def _check_java(original, java, out):
    try:
        result = subprocess.run(
            [java, "-XshowSettings:properties", "-version"], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"Cannot verify the recorded Java runtime: {exc}") from exc
    text = result.stdout + result.stderr
    (out / "java-preflight.txt").write_text(text, encoding="utf-8")
    if result.returncode:
        raise ToolError("Java runtime verification failed")
    for predicate, property_name in ((OT.javaVersion, "java.version"), (OT.javaVendor, "java.vendor")):
        saved = original.value(RUN, predicate)
        match = re.search(r"^\s*" + re.escape(property_name) + r"\s*=\s*(.+?)\s*$", text, re.M)
        if saved is None or match is None or str(saved) != match.group(1):
            raise ToolError(f"Java {property_name} differs from, or is missing in, the recorded run")


def _semantic_graphs(root):
    """Execution timestamps, physical file bases and process logs are not results."""
    names = {"report.ttl", "owl-report.ttl", "input.ttl", "classification.ttl",
             "facts.ttl", "result.ttl", "closure.ttl", "trace.ttl", "candidates.ttl",
             "shacl-report.ttl", "post-shacl-report.ttl",
             "rule-input.ttl", "rule-result.ttl", "rule-trace.ttl",
             "swrl-result.ttl", "swrl-trace.ttl", "initial-candidates.ttl",
             "computations.ttl", "calculation-contract.ttl", "budget.ttl",
             "temporal-normalization.ttl", "ontology.ttl", "rules.ttl", "shapes.ttl",
             "formulas.ttl", "formula-computations.ttl", "formula-contract.ttl",
             "formula-diagnostics.ttl", "formula-budget.ttl"}
    names.add("formula-result.ttl")
    files = {}
    for path in root.rglob("*.ttl"):
        relative = path.relative_to(root)
        if any(part in {"snapshot", "runtime", "inputs"} for part in relative.parts):
            continue
        if path.name in names:
            files[relative.as_posix()] = path
    return files


def replay_reasoning(run_dir, output, original=None):
    """Verify hashes/runtime, rerun frozen inputs, compare semantic graph outputs."""
    from .core import _finish, _record, infer_graph
    from .owl_dl import ROOT, _runtime, check_consistency, infer_owl

    run_dir = Path(run_dir).resolve()
    verify_manifest(run_dir, required=True)
    original = parse_rdf(run_dir / "execution.ttl") if original is None else original
    profile = str(original.value(RUN, OT.profile))
    status = str(original.value(RUN, OT.status))
    stage = str(original.value(RUN, OT.stage))
    if profile not in OWL_PROFILES | {PROJECTION, CALCULATION, FORMULA}:
        raise ToolError(f"Unsupported replay profile: {profile}")
    if status not in {"passed", "nonconformant"} or stage in {"replay", "golden-cases", "query", "inspect", "validate", "candidates"}:
        raise ToolError("Replay needs a completed inference or semantic check, not a technical failure or utility run")
    if not (run_dir / "runtime.sha256").is_file():
        raise ToolError("Missing complete OWL runtime fingerprint")
    _check_environment(original)
    out = new_output(output, run_dir, ROOT.parent)
    started = datetime.now(timezone.utc).isoformat()
    try:
        record = _record("replay", "failed", started, profile=profile)
        _runtime(out, record)
        if (run_dir / "runtime.sha256").read_bytes() != (out / "runtime.sha256").read_bytes():
            raise ToolError("OWL runtime/dependency fingerprint changed; use the recorded runtime")
        java = str(original.value(RUN, OT.javaExecutable) or "java")
        _check_java(original, java, out)
        timeout = float(original.value(RUN, OT.timeoutSeconds) or 60)
        rerun = out / "replayed"
        if profile in OWL_PROFILES:
            assembled = run_dir / "assembled.rdf"
            if not assembled.is_file():
                raise ToolError("Missing assembled OWL input snapshot")
            operation = check_consistency if profile == "owl-dl-hermit-v1" else infer_owl
            extra = {} if profile == "owl-dl-hermit-v1" else {
                "candidates": run_dir / "candidates.ttl" if (run_dir / "candidates.ttl").is_file() else None}
            operation(assembled, rerun, java=java, timeout=timeout, **extra)
        else:
            replay_package = original.value(RUN, OT.replayPackage)
            replay_facts = original.value(RUN, OT.replayFacts)
            if replay_package is None or replay_facts is None:
                raise ToolError("Missing semantic replay package/facts references")
            package = safe_path(run_dir, str(replay_package))
            facts = safe_path(run_dir, str(replay_facts))
            try:
                infer_graph(package, facts=facts, output=rerun)
            except ToolError as exc:
                if getattr(exc, "exit_code", 2) != 1:
                    raise
        repeated = parse_rdf(rerun / "execution.ttl")
        compared = Graph()
        checks = []
        for predicate in (OT.status, OT.exitCode, OT.semanticState, OT.stage):
            equal = original.value(RUN, predicate) == repeated.value(RUN, predicate)
            checks.append(equal)
            item = URIRef("urn:ontology-tools:comparison:state:" + str(predicate).split("#")[-1])
            compared.add((RUN, OT.comparison, item))
            compared.add((item, OT.field, predicate))
            compared.add((item, OT.matches, Literal(equal)))
        before = _semantic_graphs(run_dir)
        after = _semantic_graphs(rerun)
        for relative in sorted(set(before) | set(after)):
            equal = (relative in before and relative in after and
                     isomorphic(parse_rdf(before[relative]), parse_rdf(after[relative])))
            checks.append(equal)
            item = URIRef("urn:ontology-tools:comparison:graph:" + relative)
            compared.add((RUN, OT.comparison, item))
            compared.add((item, OT.path, Literal(relative)))
            compared.add((item, OT.isomorphic, Literal(equal)))
        equal = bool(before) and all(checks)
        compared.add((RUN, OT.status, Literal("passed" if equal else "failed")))
        write_graph(compared, out / "replay-report.ttl")
        record = _record("replay", "passed" if equal else "failed", started,
                         0 if equal else 1, profile=profile)
        record.add((RUN, OT.replayedStatus, Literal(status)))
        _finish(out, record, f"# Reasoning replay\n\nStatus: {'passed' if equal else 'failed'}. "
                f"Profile: `{profile}`. Original semantic status: `{status}`.\n\n"
                f"Compared {len(set(before) | set(after))} RDF graphs and execution outcome. "
                "Input/runtime fingerprints and Python/Java/dependency versions were verified. "
                "Graph isomorphism excludes serialization, timestamps and logs. "
                "A reproduced nonconformant ontology remains nonconformant.\n")
        return out
    except Exception as exc:
        _finish(out, _record("replay", "failed", started, 2, exc, profile=profile),
                f"Reasoning replay failed: {exc}\n")
        if isinstance(exc, ToolError):
            raise
        raise ToolError(str(exc)) from exc
