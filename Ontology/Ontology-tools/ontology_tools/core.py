"""Six reusable operations. Project policy remains in OWL/SWRL/SHACL."""
from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from datetime import datetime, timezone
from pathlib import Path

from pyshacl import validate
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, SH, XSD
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue

from . import __version__
from .io import (OT, PROFILE, ToolError, ValidationError, code_digest, code_files,
                 enclosing_packages, environment, file_set, new_output, parse_rdf, safe_path, sha256,
                 verify_manifest, write_graph, write_manifest)

RUN = URIRef("urn:ontology-tools:run")
META = Namespace("https://example.org/ontology-template/meta#")
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
PROJECTION_PROFILE = "hermit-swrl-projection-v1"
CALCULATION_PROFILE = "hermit-swrl-calculation-v1"
FORMULA_PROFILE = "hermit-swrl-formula-v1"
EXCHANGE_PROFILES = {PROJECTION_PROFILE, CALCULATION_PROFILE, FORMULA_PROFILE}


def _selected_profile(package):
    """Select an explicit backend without weakening its own configuration checks."""
    path = Path(package).resolve() / "runtime.ttl"
    if not path.is_file():
        return PROFILE
    graph = parse_rdf(path)
    subjects = list(graph.subjects(RDF.type, OT.Runtime))
    if len(subjects) != 1:
        raise ToolError("runtime.ttl requires exactly one ot:Runtime")
    value = _one(graph, subjects[0], OT.profile, Literal(PROFILE))
    if not isinstance(value, Literal):
        raise ToolError("Runtime profile must be a literal")
    profile = str(value)
    if profile not in {PROFILE} | EXCHANGE_PROFILES:
        raise ToolError(f"Unsupported backend profile: {profile}")
    return profile


def _one(graph, subject, predicate, default=None):
    values = list(graph.objects(subject, predicate))
    if len(values) > 1:
        raise ToolError(f"Expected one {predicate} for {subject}")
    return values[0] if values else default


def _config(package):
    result = {"profile": PROFILE, "validationOrder": "pre-post", "maxIterations": 100}
    path = package / "runtime.ttl"
    if path.exists():
        graph = parse_rdf(path)
        subjects = list(graph.subjects(RDF.type, OT.Runtime))
        if len(subjects) != 1:
            raise ToolError("runtime.ttl requires exactly one ot:Runtime")
        subject = subjects[0]
        allowed = {RDF.type, RDFS.label, RDFS.comment, OT.profile, OT.validationOrder, OT.maxIterations}
        for _, predicate, _ in graph.triples((subject, None, None)):
            if predicate not in allowed:
                raise ToolError(f"Unsupported runtime option: {predicate}")
        for key in result:
            value = _one(graph, subject, OT[key])
            if value is not None:
                if not isinstance(value, Literal):
                    raise ToolError(f"Runtime option must be a literal: {key}")
                result[key] = str(value)
        try:
            result["maxIterations"] = int(result["maxIterations"])
        except ValueError as exc:
            raise ToolError("maxIterations must be a positive integer") from exc
    if result["profile"] != PROFILE:
        raise ToolError(f"Unsupported backend profile: {result['profile']}")
    if result["validationOrder"] not in {"pre", "post", "pre-post"}:
        raise ToolError("validationOrder must be pre, post or pre-post")
    if result["maxIterations"] <= 0:
        raise ToolError("maxIterations must be positive")
    return result


def _shape_check(shapes):
    # First version intentionally supports SHACL Core, without executable extensions.
    blocked = {SH.sparql, SH.rule, SH.js, SH.jsLibrary, SH.jsFunctionName,
               SH.target, SH.validator, SH.nodeValidator, SH.propertyValidator,
               SH.select, SH.ask, SH.construct}
    blocked_types = {SH.SPARQLConstraint, SH.SPARQLConstraintComponent,
                     SH.SPARQLFunction, SH.JSConstraint, SH.JSFunction,
                     SH.SPARQLRule, SH.TripleRule, SH.ConstraintComponent,
                     SH.SPARQLTarget, SH.SPARQLTargetType}
    core_predicates = {
        SH.targetClass, SH.targetNode, SH.targetObjectsOf, SH.targetSubjectsOf,
        SH.path, SH.inversePath, SH.alternativePath, SH.zeroOrMorePath,
        SH.oneOrMorePath, SH.zeroOrOnePath, SH.property, SH.node,
        SH["class"], SH.datatype, SH.nodeKind, SH.minCount, SH.maxCount,
        SH.minExclusive, SH.minInclusive, SH.maxExclusive, SH.maxInclusive,
        SH.minLength, SH.maxLength, SH.pattern, SH.flags, SH.languageIn,
        SH.uniqueLang, SH.equals, SH.disjoint, SH.lessThan, SH.lessThanOrEquals,
        SH["not"], SH["and"], SH["or"], SH.xone, SH.qualifiedValueShape,
        SH.qualifiedMinCount, SH.qualifiedMaxCount, SH.qualifiedValueShapesDisjoint,
        SH.closed, SH.ignoredProperties, SH.hasValue, SH["in"], SH.deactivated,
        SH.message, SH.severity, SH.name, SH.description, SH.order, SH.group,
        SH.defaultValue, SH.entailment,
    }
    for s, p, o in shapes:
        if p in blocked or (p == RDF.type and o in blocked_types):
            raise ToolError(f"SHACL executable/custom extension unsupported: {p} {o}")
        if str(p).startswith(str(SH)) and p not in core_predicates:
            raise ToolError(f"Unsupported SHACL predicate: {p}")
        if p == SH.entailment:
            raise ToolError("SHACL entailment declarations are unsupported; use an explicit runtime validation order")
        if p == RDF.type and str(o).startswith(str(SH)) and o not in {SH.NodeShape, SH.PropertyShape, SH.PropertyGroup}:
            raise ToolError(f"Unsupported SHACL shape type: {o}")


def _fact_role(data):
    # This is an execution-role boundary, not a general ban on TBox/ABox in
    # one RDF document: ontology.ttl may contain both frozen model and facts.
    annotations = {RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy}
    for _, predicate, obj in data:
        if str(predicate).startswith(str(SWRL)) or (predicate == RDF.type and str(obj).startswith(str(SWRL))):
            raise ToolError("Dynamic facts cannot define SWRL rules")
        if (str(predicate).startswith(str(OWL)) or
            (str(predicate).startswith(str(RDFS)) and predicate not in annotations) or
            (predicate == RDF.type and (obj in {RDF.Property, RDFS.Class, RDFS.Datatype} or
             (str(obj).startswith(str(OWL)) and obj != OWL.NamedIndividual)))):
            raise ToolError("Dynamic facts cannot modify TBox/schema; put reviewed schema in ontology.ttl")


def _load(package, facts=None):
    if _selected_profile(package) in EXCHANGE_PROFILES:
        from .projection import load_projection
        return load_projection(package, facts)
    from .backend import inspect_semantics
    package = Path(package).resolve()
    if not package.is_dir():
        raise ToolError(f"Missing package directory: {package}")
    if (package / "formulas.ttl").exists():
        raise ToolError("formulas.ttl requires the explicit hermit-swrl-formula-v1 profile")
    file_set(package)  # Reject escaping links even on un-frozen drafts.
    if (package / "modules").exists() and any((package / "modules").iterdir()):
        raise ToolError("modules/ loading is unsupported; provide an explicitly merged local model")
    frozen = verify_manifest(package)
    config = _config(package)
    ontology = parse_rdf(package / "ontology.ttl")
    rules = parse_rdf(package / "rules.swrl") if (package / "rules.swrl").exists() else Graph()
    shapes = parse_rdf(package / "shapes.ttl")
    _shape_check(shapes)
    facts_path = Path(facts).resolve() if facts is not None else package / "inputs/facts.ttl"
    if facts is not None:
        enclosing_packages(facts_path)
    data = parse_rdf(facts_path)
    _fact_role(data)
    for name in ("provenance.ttl", "mapping.ttl", "tests/cases.ttl"):
        if (package / name).exists():
            parse_rdf(package / name)
    issues = inspect_semantics(ontology + data, rules)
    if issues:
        raise ToolError("Unsupported/invalid model: " + "; ".join(issues))
    return package, config, ontology, rules, shapes, data, facts_path, frozen


def inspect_package(package, output=None):
    if _selected_profile(package) in EXCHANGE_PROFILES:
        from .projection import inspect_projection
        return inspect_projection(package, output=output)
    package, config, ontology, rules, shapes, facts, facts_path, frozen = _load(package)
    report = Graph()
    report.add((RUN, RDF.type, OT.PackageInspection))
    report.add((RUN, OT.status, Literal("passed")))
    report.add((RUN, OT.profile, Literal(config["profile"])))
    report.add((RUN, OT.frozen, Literal(frozen)))
    report.add((RUN, OT.validationOrder, Literal(config["validationOrder"])))
    report.add((RUN, OT.ontologyTriples, Literal(len(ontology))))
    report.add((RUN, OT.factTriples, Literal(len(facts))))
    report.add((RUN, OT.ruleCount, Literal(len(set(rules.subjects(RDF.type, SWRL.Imp))))))
    report.add((RUN, OT.fullOWLConsistency, Literal("not_run")))
    for rel, path in file_set(package).items():
        node = URIRef("urn:ontology-tools:file:" + hashlib.sha256(rel.encode()).hexdigest())
        report.add((RUN, OT.file, node))
        report.add((node, OT.path, Literal(rel)))
        report.add((node, OT.sha256, Literal(sha256(path))))
    if output is not None:
        out = new_output(output, package)
        write_graph(report, out / "inspection.ttl")
        (out / "report.md").write_text(f"Package inspection: passed\n\nProfile: `{PROFILE}`. Frozen manifest: {frozen}.\n\nThis is a supported-profile check, not a full OWL consistency proof.\n", encoding="utf-8")
        write_manifest(out)
    return report


def _targets(data, shapes):
    targets = set()
    for _, _, node in shapes.triples((None, SH.targetNode, None)):
        targets.add(node)
    for _, _, predicate in shapes.triples((None, SH.targetSubjectsOf, None)):
        targets.update(data.subjects(predicate, None))
    for _, _, predicate in shapes.triples((None, SH.targetObjectsOf, None)):
        targets.update(data.objects(None, predicate))
    for _, _, cls in shapes.triples((None, SH.targetClass, None)):
        subclasses = {cls}
        while True:
            more = {s for s, _, o in data.triples((None, RDFS.subClassOf, None)) if o in subclasses}
            if more <= subclasses:
                break
            subclasses |= more
        for actual in subclasses:
            targets.update(data.subjects(RDF.type, actual))
    return len(targets)


def _validate(data, ontology, shapes):
    combined = ontology + data
    conforms, report, _ = validate(
        data_graph=combined, shacl_graph=shapes, inference="none", advanced=False,
        js=False, do_owl_imports=False, meta_shacl=True, inplace=False,
        abort_on_first=False, allow_infos=False, allow_warnings=False,
    )
    if not isinstance(report, Graph):
        raise ToolError(f"SHACL validation failed to execute: {report}")
    root = next(report.subjects(RDF.type, SH.ValidationReport))
    report.add((root, OT.focusNodeCount, Literal(_targets(combined, shapes))))
    return bool(conforms), report


def validate_graph(package, facts=None, output=None):
    if _selected_profile(package) in EXCHANGE_PROFILES:
        from .projection import validate_projection
        return validate_projection(package, facts=facts, output=output)
    package, config, ontology, rules, shapes, data, path, frozen = _load(package, facts)
    conforms, report = _validate(data, ontology, shapes)
    if output is not None:
        out = new_output(output, package, *enclosing_packages(path))
        write_graph(report, out / "shacl-report.ttl")
        (out / "report.md").write_text(f"Input SHACL: {'passed' if conforms else 'failed'}\n\nChecked explicit facts plus the ontology; no rule inference executed.\n", encoding="utf-8")
        write_manifest(out)
    return report


def _record(stage, status, started, exit_code=0, error=None, *, profile=PROFILE):
    report = Graph()
    report.add((RUN, RDF.type, OT.Execution))
    for predicate, value in {
        OT.stage: stage, OT.status: status, OT.startedAt: started,
        OT.finishedAt: datetime.now(timezone.utc).isoformat(),
        OT.exitCode: exit_code, OT.profile: profile, OT.version: __version__,
        OT.engineDigest: code_digest(), OT.workingDirectory: str(Path.cwd()),
        OT.pythonExecutable: sys.executable,
        OT.externalSystems: "not_run", OT.fullOWLConsistency: "not_run",
    }.items():
        report.add((RUN, predicate, Literal(value)))
    if error:
        report.add((RUN, OT.error, Literal(str(error))))
    invocation = getattr(sys, "orig_argv", sys.argv)
    report.add((RUN, OT.command, Literal(subprocess.list2cmdline(invocation))))
    for index, arg in enumerate(invocation):
        node = URIRef(f"urn:ontology-tools:argument:{index}")
        report.add((RUN, OT.argument, node))
        report.add((node, OT["index"], Literal(index)))
        report.add((node, RDF.value, Literal(arg)))
    for name, version in environment().items():
        node = URIRef("urn:ontology-tools:dependency:" + name)
        report.add((RUN, OT.dependency, node))
        report.add((node, OT.name, Literal(name)))
        report.add((node, OT.version, Literal(version)))
    return report


def _finish(out, record, message):
    # The outer manifest protects execution.ttl too; it is not a digital signature.
    for rel, path in file_set(out).items():
        node = URIRef("urn:ontology-tools:artifact:" + hashlib.sha256(rel.encode()).hexdigest())
        record.add((RUN, OT.artifact, node))
        record.add((node, OT.path, Literal(rel)))
        record.add((node, OT.sha256, Literal(sha256(path))))
    write_graph(record, out / "execution.ttl")
    (out / "report.md").write_text(message, encoding="utf-8")
    write_manifest(out)


def infer_graph(package, facts=None, output=None):
    """Execute with immutable snapshots; failures are saved then raised."""
    if _selected_profile(package) in EXCHANGE_PROFILES:
        from .projection import infer_projection
        return infer_projection(package, facts=facts, output=output)
    from .backend import infer
    if output is None:
        raise ToolError("An explicit new output directory is required")
    package = Path(package).resolve()
    out = new_output(output, package, *(enclosing_packages(Path(facts)) if facts is not None else []))
    started = datetime.now(timezone.utc).isoformat()
    stage = "inspect"
    try:
        package, config, ontology, rules, shapes, data, facts_path, frozen = _load(package, facts)
        # Capture original bytes before any execution. Replay uses only this copy.
        snapshot = out / "snapshot/package"
        snapshot.mkdir(parents=True)
        for rel, path in file_set(package).items():
            target = snapshot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        for rel, path in code_files().items():
            target = out / "snapshot/tool" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        shutil.copyfile(facts_path, out / ("facts-source" + facts_path.suffix))
        # Reload the actual snapshot: no changed source can affect this run.
        facts_snapshot = out / ("facts-source" + facts_path.suffix)
        _, config, ontology, rules, shapes, data, _, _ = _load(snapshot, facts_snapshot)
        write_graph(data, out / "input.ttl")
        if config["validationOrder"] in {"pre", "pre-post"}:
            stage = "pre-validation"
            conforms, report = _validate(data, ontology, shapes)
            write_graph(report, out / "shacl-report.ttl")
            if not conforms:
                raise ValidationError("Input SHACL failed; rule inference was not run")
        stage = "inference"
        result = infer(ontology, rules, data, max_iterations=config["maxIterations"])
        write_graph(result.inferred, out / "result.ttl")
        write_graph(result.closure, out / "closure.ttl")
        write_graph(result.trace, out / "trace.ttl")
        if config["validationOrder"] in {"post", "pre-post"}:
            stage = "post-validation"
            # Closure already includes the model. Re-adding the parsed source
            # would duplicate its independently scoped blank-node individuals.
            conforms, report = _validate(result.closure, Graph(), shapes)
            write_graph(report, out / "post-shacl-report.ttl")
            if not conforms:
                raise ValidationError("Output SHACL failed; inferred result is not accepted")
        record = _record("complete", "passed", started)
        record.add((RUN, OT.validationOrder, Literal(config["validationOrder"])))
        record.add((RUN, OT.inferredTriples, Literal(len(result.inferred))))
        record.add((RUN, OT.iterations, Literal(result.iterations)))
        record.add((RUN, OT.frozen, Literal(frozen)))
        record.add((RUN, OT.sourcePackage, Literal(str(package))))
        record.add((RUN, OT.factSourcePath, Literal(str(facts_path))))
        _finish(out, record, f"# Local ontology execution\n\nStatus: passed. Profile: `{PROFILE}`.\n\nNew triples: {len(result.inferred)}. Iterations: {result.iterations}. Validation: {config['validationOrder']}.\n\n`result.ttl` contains only newly inferred facts; query `closure.ttl` for the combined graph. `trace.ttl` contains the backend's recorded derivations. Zero new facts is reported as zero, not evidence that a business objective was met.\n\nFull OWL consistency, external systems and business actions: not_run.\n")
        return out
    except Exception as exc:
        code = getattr(exc, "exit_code", 2)
        _finish(out, _record(stage, "failed", started, code, exc), f"# Local ontology execution\n\nStatus: failed. Stage: {stage}. Exit: {code}.\n\n{exc}\n\nAny intermediate graph is unaccepted. External systems: not_run.\n")
        if isinstance(exc, ToolError):
            raise
        raise ToolError(str(exc)) from exc


def _safe_query(text):
    parsed = parseQuery(text)  # Also rejects SPARQL UPDATE.
    def visit(value):
        if isinstance(value, CompValue):
            if value.name in {"ServiceGraphPattern", "DatasetClause"}:
                raise ToolError("Remote SERVICE and FROM/dataset loading are disabled")
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)) or hasattr(value, "asList"):
            for child in value:
                visit(child)
    visit(parsed)


def query_graph(graph_path, query_path, output):
    graph_path, query_path = Path(graph_path).resolve(), Path(query_path).resolve()
    # Reading a saved run also verifies that it has not been changed.
    protected = [graph_path.parent, *enclosing_packages(graph_path), *enclosing_packages(query_path)]
    out = new_output(output, *protected)
    started = datetime.now(timezone.utc).isoformat()
    try:
        graph = parse_rdf(graph_path)
        shutil.copyfile(graph_path, out / ("graph-source" + graph_path.suffix))
        query = query_path.read_text(encoding="utf-8-sig")
        _safe_query(query)
        write_graph(graph, out / "query-input.ttl")
        (out / "query.rq").write_text(query, encoding="utf-8")
        result = graph.query(query)
        count = 0
        if result.type in {"CONSTRUCT", "DESCRIBE"}:
            count = len(result.graph)
            write_graph(result.graph, out / "query-result.ttl")
        elif result.type == "ASK":
            report = Graph()
            report.add((RUN, OT.askResult, Literal(bool(result.askAnswer))))
            write_graph(report, out / "query-result.ttl")
            count = int(bool(result.askAnswer))
        else:
            with (out / "query-result.tsv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                writer.writerow([str(var) for var in result.vars])
                for row in result:
                    writer.writerow([term.n3() if term is not None else "" for term in row])
                    count += 1
        record = _record("query", "passed", started)
        record.add((RUN, OT.rowCount, Literal(count)))
        _finish(out, record, f"Query: passed. Type: {result.type}. Rows/triples: {count}.\n\nInput is the saved graph. No additional inference or remote data loading was performed.\n")
        return out
    except Exception as exc:
        _finish(out, _record("query", "failed", started, 2, exc), f"Query failed: {exc}\n")
        if isinstance(exc, ToolError):
            raise
        raise ToolError(str(exc)) from exc


def _case_values(graph, case, name):
    return list(graph.objects(case, OT[name])) + list(graph.objects(case, META[name]))


def _case_one(graph, case, name, default=None):
    values = _case_values(graph, case, name)
    if len(values) > 1:
        raise ToolError(f"Duplicate case field {name}: {case}")
    return values[0] if values else default


def _expected(graph, node):
    values = tuple(_one(graph, node, p) for p in (RDF.subject, RDF.predicate, RDF.object))
    if any(v is None for v in values) or not isinstance(values[1], URIRef):
        raise ToolError("Expected triple must have exactly one RDF subject/predicate/object")
    if any(isinstance(v, BNode) for v in values):
        raise ToolError("Golden triple values must use stable IRIs/literals, not blank node identity")
    return values


def _outcome_case(cases, case, package, input_path, case_dir):
    """Check a declared semantic/technical outcome independently of SHACL."""
    outcome = str(_case_one(cases, case, "expectedOutcome"))
    allowed = {"passed", "shacl-invalid", "owl-inconsistent", "owl-unsatisfiable", "failed"}
    if outcome not in allowed:
        raise ToolError(f"Unknown expectedOutcome: {outcome}")
    if _case_values(cases, case, "validationExpectation") or _case_values(cases, case, "reasoningMustStop"):
        raise ToolError("Use either expectedOutcome or the legacy validation expectation, not both")
    expected = [_expected(cases, n) for n in _case_values(cases, case, "expectedTriple")]
    forbidden = [_expected(cases, n) for n in _case_values(cases, case, "notExpectedInferredTriple")]
    closure_expected = [_expected(cases, n) for n in _case_values(cases, case, "expectedClosureTriple")]
    numeric_nodes = _case_values(cases, case, "expectedNumeric")
    if outcome != "passed" and (expected or forbidden or closure_expected or numeric_nodes):
        raise ToolError("Non-passed cases cannot require successful inference outputs")
    if outcome == "passed" and not (expected or forbidden or closure_expected or numeric_nodes):
        raise ToolError("A passed case requires independent triple expectations")
    failure_stage = _case_one(cases, case, "expectedFailureStage")
    error_contains = _case_one(cases, case, "expectedErrorContains")
    classes = set(_case_values(cases, case, "expectedUnsatisfiableClass"))
    if outcome == "failed" and (not isinstance(failure_stage, Literal) or not str(failure_stage)):
        raise ToolError("A technical-failure case requires expectedFailureStage")
    if outcome != "failed" and (failure_stage is not None or error_contains is not None):
        raise ToolError("Failure-stage/error expectations apply only to technical failure")
    if error_contains is not None and (not isinstance(error_contains, Literal) or not str(error_contains)):
        raise ToolError("expectedErrorContains must be a nonempty literal")
    if outcome == "owl-unsatisfiable" and (not classes or any(not isinstance(c, URIRef) for c in classes)):
        raise ToolError("An unsatisfiable case requires named expectedUnsatisfiableClass values")
    if outcome != "owl-unsatisfiable" and classes:
        raise ToolError("expectedUnsatisfiableClass applies only to owl-unsatisfiable")
    error = None
    try:
        infer_graph(package, facts=input_path, output=case_dir)
    except ToolError as exc:
        error = exc
    if not (case_dir / "execution.ttl").is_file():
        return False, f"No saved execution evidence: {error}", set()
    execution = parse_rdf(case_dir / "execution.ttl")
    status = str(execution.value(RUN, OT.status))
    code = int(execution.value(RUN, OT.exitCode) or 0)
    semantic = str(execution.value(RUN, OT.semanticState))
    checks = []
    covered = set()
    if outcome == "passed":
        checks.append(status == "passed" and code == 0 and error is None)
        if all(checks):
            result = parse_rdf(case_dir / "result.ttl")
            closure = parse_rdf(case_dir / "closure.ttl")
            trace = parse_rdf(case_dir / "trace.ttl")
            covered.update(trace.objects(None, OT.rule))
            checks.extend(t in result for t in expected)
            checks.extend(t not in result for t in forbidden)
            checks.extend(t in closure for t in closure_expected)
            numeric_checks, _ = _check_numeric_expectations(cases, case, result)
            checks.extend(numeric_checks)
    elif outcome == "shacl-invalid":
        checks.append(code == 3 and isinstance(error, ValidationError))
    elif outcome in {"owl-inconsistent", "owl-unsatisfiable"}:
        wanted = "inconsistent" if outcome == "owl-inconsistent" else "unsatisfiable"
        checks.append(status == "nonconformant" and code == 1 and semantic == wanted)
        owl_report = case_dir / "owl-report.ttl"
        if not owl_report.is_file():
            checks.append(False)
        else:
            report = parse_rdf(owl_report)
            checks.append(report.value(RUN, OT.consistent) == Literal(outcome == "owl-unsatisfiable"))
            if outcome == "owl-unsatisfiable":
                checks.append(set(report.objects(RUN, OT.unsatisfiableClass)) == classes)
    else:
        checks.append(status == "failed" and code == 2 and error is not None)
        checks.append(str(execution.value(RUN, OT.stage)) == str(failure_stage))
        if error_contains is not None:
            checks.append(str(error_contains) in str(execution.value(RUN, OT.error)))
    if outcome != "passed":
        checks.append(not (case_dir / "closure.ttl").exists())
    ok = all(checks)
    return ok, f"Expected {outcome}; actual {status}/{semantic}; exit={code}; checks={sum(checks)}/{len(checks)}", covered if ok else set()


def _golden_semantic_snapshot(snapshot, source, destination):
    """Freeze original document bases without relocating authored entity IRIs."""
    from .owl_dl import _parse
    files = file_set(snapshot)
    manifests = {Path(".")}
    for relative, path in files.items():
        if path.name == "manifest.sha256":
            verify_manifest(path.parent, required=True)
            manifests.add(Path(relative).parent)
    for relative, path in files.items():
        if path.name == "manifest.sha256":
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes()
        if path.suffix.lower() in {".ttl", ".nt", ".owl", ".rdf", ".swrl"}:
            try:
                graph = _parse(raw, source / relative)
            except Exception:
                # An intentionally malformed case must fail in the actual
                # execution stage, not abort the entire golden-case suite.
                target.write_bytes(raw)
            else:
                if path.suffix.lower() in {".ttl", ".nt"}:
                    write_graph(graph, target)
                else:
                    graph.serialize(destination=target, format="xml", encoding="utf-8")
        else:
            target.write_bytes(raw)
    # Rebuild nested manifests before their containing package manifest.
    for relative in sorted(manifests, key=lambda p: (-len(p.parts), p.as_posix())):
        write_manifest(destination / relative)
    return destination


def _check_numeric_expectations(cases, case, result):
    """Compare a full singleton result set with an independently authored bound."""
    checks, details = [], []
    numeric_types = {XSD.decimal, XSD.integer, XSD.int, XSD.long, XSD.nonNegativeInteger,
                     XSD.positiveInteger, XSD.short, XSD.byte}

    def number(value, label):
        if not isinstance(value, Literal) or value.datatype not in numeric_types:
            raise ToolError(f"{label} must be an integer/decimal literal")
        try:
            parsed = Decimal(str(value))
        except InvalidOperation as exc:
            raise ToolError(f"Invalid {label}") from exc
        if not parsed.is_finite():
            raise ToolError(f"{label} must be finite")
        return parsed

    for node in _case_values(cases, case, "expectedNumeric"):
        subject, predicate = _one(cases, node, RDF.subject), _one(cases, node, RDF.predicate)
        expected = number(_one(cases, node, RDF.value), "Numeric reference")
        absolute_term = _one(cases, node, OT.absoluteTolerance)
        relative_term = _one(cases, node, OT.relativeTolerance)
        if absolute_term is None and relative_term is None:
            raise ToolError("Numeric expectations require an explicit tolerance (zero is permitted)")
        absolute = number(absolute_term, "Absolute tolerance") if absolute_term is not None else Decimal(0)
        relative = number(relative_term, "Relative tolerance") if relative_term is not None else Decimal(0)
        if absolute < 0 or relative < 0:
            raise ToolError("Numeric tolerance must be nonnegative")
        actual = set(result.objects(subject, predicate))
        bound = max(Fraction(absolute), Fraction(relative) * abs(Fraction(expected)))
        ok = len(actual) == 1 and abs(Fraction(number(next(iter(actual)), "Actual numeric result")) - Fraction(expected)) <= bound
        unit = _one(cases, node, OT.unit)
        unit_predicate = _one(cases, node, OT.unitPredicate)
        if (unit is None) != (unit_predicate is None):
            raise ToolError("Numeric unit requires both ot:unit and ot:unitPredicate")
        if unit is not None:
            ok = ok and {str(value) for value in result.objects(subject, unit_predicate)} == {str(unit)}
        checks.append(ok)
        details.append(f"{subject}: numeric={'passed' if ok else 'failed'}; actual={sorted(map(str, actual))}; reference={expected}; tolerance={bound}")
    return checks, details


def run_cases(package, output):
    package = Path(package).resolve()
    out = new_output(output, package)
    started = datetime.now(timezone.utc).isoformat()
    try:
        snapshot = out / "snapshot/package"
        snapshot.mkdir(parents=True)
        for rel, path in file_set(package).items():
            target = snapshot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        verify_manifest(snapshot)
        package = (_golden_semantic_snapshot(snapshot, package, out / "snapshot/semantic-package")
                   if _selected_profile(snapshot) in EXCHANGE_PROFILES else snapshot)
        _, config, *_ = _load(package)
        cases_path = package / "tests/cases.ttl"
        cases = parse_rdf(cases_path)
        if config["profile"] in EXCHANGE_PROFILES:
            from .backend import normalize_projection_literals
            cases = normalize_projection_literals(cases)
        identifiers = set(cases.subjects(RDF.type, OT.Case)) | set(cases.subjects(RDF.type, META.Case))
        if not identifiers:
            raise ToolError("No independent golden cases found")
        report = Graph()
        passed = 0
        covered = set()
        for index, case in enumerate(sorted(identifiers, key=str), 1):
            case_dir = out / f"case-{index:04d}"
            ok = False
            details = []
            try:
                relative = _case_one(cases, case, "input")
                if relative is None or not isinstance(relative, Literal):
                    raise ToolError("Case requires one literal input path")
                input_path = safe_path(cases_path.parent, str(relative))
                if _case_one(cases, case, "expectedOutcome") is not None:
                    ok, detail, case_covered = _outcome_case(cases, case, package, input_path, case_dir)
                    covered.update(case_covered)
                    passed += int(ok)
                    report.add((case, RDF.type, OT.CaseResult))
                    report.add((case, OT.status, Literal("passed" if ok else "failed")))
                    report.add((case, OT.detail, Literal(detail)))
                    report.add((case, OT.output, Literal(case_dir.name)))
                    # Keep the authored expectations with the report; the whole
                    # exact cases file is also preserved in the package snapshot.
                    for name in ("expectedOutcome", "expectedFailureStage", "expectedErrorContains",
                                 "expectedUnsatisfiableClass"):
                        for value in _case_values(cases, case, name):
                            report.add((case, OT[name], value))
                    continue
                expectation = str(_case_one(cases, case, "validationExpectation", Literal("conforms")))
                if expectation not in {"conforms", "invalid"}:
                    raise ToolError("Unknown validationExpectation")
                must_stop = _case_one(cases, case, "reasoningMustStop", Literal(False))
                if not isinstance(must_stop, Literal) or type(must_stop.toPython()) is not bool:
                    raise ToolError("reasoningMustStop must be an RDF boolean")
                if expectation == "conforms" and must_stop.toPython():
                    raise ToolError("Conforming case cannot require reasoningMustStop; declare an invalid-input case")
                expected = [_expected(cases, node) for node in _case_values(cases, case, "expectedTriple")]
                forbidden = [_expected(cases, node) for node in _case_values(cases, case, "notExpectedInferredTriple")]
                in_closure = [_expected(cases, node) for node in _case_values(cases, case, "expectedClosureTriple")]
                numeric_nodes = _case_values(cases, case, "expectedNumeric")
                if expectation == "invalid" and (expected or forbidden or in_closure or numeric_nodes):
                    raise ToolError("Invalid-input cases cannot also require successful inference outputs")
                if expectation == "conforms" and not (expected or forbidden or in_closure or numeric_nodes):
                    raise ToolError("A conforming case requires an independent result expectation")
                try:
                    infer_graph(package, facts=input_path, output=case_dir)
                    validation_failed = False
                except ValidationError:
                    validation_failed = True
                if expectation == "invalid":
                    ok = validation_failed and (not must_stop.toPython() or not (case_dir / "result.ttl").exists())
                    details.append(f"validation_failed={validation_failed}; reasoning_stopped={not (case_dir / 'result.ttl').exists()}")
                elif validation_failed:
                    details.append("Unexpected SHACL failure")
                else:
                    result = parse_rdf(case_dir / "result.ttl")
                    closure = parse_rdf(case_dir / "closure.ttl")
                    trace = parse_rdf(case_dir / "trace.ttl")
                    checks = [t in result for t in expected] + [t not in result for t in forbidden] + [t in closure for t in in_closure]
                    numeric_checks, numeric_details = _check_numeric_expectations(cases, case, result)
                    checks += numeric_checks
                    details += numeric_details
                    ok = all(checks)
                    if ok:
                        covered.update(trace.objects(None, OT.rule))
                    details.append(f"Expected result checks: {sum(checks)}/{len(checks)}")
                for predicate, triples in ((OT.expectedTriple, expected), (OT.notExpectedInferredTriple, forbidden), (OT.expectedClosureTriple, in_closure)):
                    for triple in triples:
                        node = BNode()
                        report.add((case, predicate, node))
                        for p, value in zip((RDF.subject, RDF.predicate, RDF.object), triple):
                            report.add((node, p, value))
            except Exception as exc:
                details.append(str(exc))
            passed += int(ok)
            report.add((case, RDF.type, OT.CaseResult))
            report.add((case, OT.status, Literal("passed" if ok else "failed")))
            report.add((case, OT.detail, Literal("; ".join(details))))
            report.add((case, OT.output, Literal(case_dir.name)))
        report.add((RUN, OT.total, Literal(len(identifiers))))
        report.add((RUN, OT.passed, Literal(passed)))
        report.add((RUN, OT.failed, Literal(len(identifiers) - passed)))
        report.add((RUN, OT.status, Literal("passed" if passed == len(identifiers) else "failed")))
        rules = parse_rdf(package / "rules.swrl") if (package / "rules.swrl").exists() else Graph()
        all_rules = set(rules.subjects(RDF.type, SWRL.Imp))
        for rule in covered:
            report.add((RUN, OT.coveredRule, rule))
        for rule in all_rules - covered:
            report.add((RUN, OT.uncoveredRule, rule))
        write_graph(report, out / "test-report.ttl")
        summary = f"Golden cases: {passed}/{len(identifiers)} passed.\n\nRules producing a recorded new fact: {len(covered & all_rules)}/{len(all_rules)}. This is derivation coverage, not all possible matches.\n\n" + "\n".join(f"- {case}: {report.value(case, OT.status)} — {report.value(case, OT.detail)}" for case in sorted(identifiers, key=str)) + "\n"
        (out / "test-report.md").write_text(summary, encoding="utf-8")
        _finish(out, _record("golden-cases", "passed" if passed == len(identifiers) else "failed", started,
                            0 if passed == len(identifiers) else 1, profile=config["profile"]), summary)
        return out
    except Exception as exc:
        _finish(out, _record("golden-cases", "failed", started, 2, exc), f"Golden cases could not execute: {exc}\n")
        if isinstance(exc, ToolError):
            raise
        raise ToolError(str(exc)) from exc


def replay_run(run_dir, output):
    run_dir = Path(run_dir).resolve()
    verify_manifest(run_dir, required=True)
    original = parse_rdf(run_dir / "execution.ttl")
    if str(original.value(RUN, OT.profile)) in {
        PROJECTION_PROFILE, CALCULATION_PROFILE, FORMULA_PROFILE, "owl-dl-hermit-v1", "owl-dl-projection-v1"
    }:
        from .replay import replay_reasoning
        return replay_reasoning(run_dir, output, original)
    if str(original.value(RUN, OT.status)) != "passed" or str(original.value(RUN, OT.stage)) != "complete":
        raise ToolError("Replay requires a successful inference run; failed/query/test runs are not replayable")
    if str(original.value(RUN, OT.engineDigest)) != code_digest():
        raise ToolError("Runtime source fingerprint changed; use the recorded runtime version")
    expected_environment = {str(original.value(node, OT.name)): str(original.value(node, OT.version)) for node in original.objects(RUN, OT.dependency)}
    if expected_environment != environment():
        raise ToolError("Dependency/Python versions differ from the recorded run")
    output = Path(output).resolve()
    if output.is_relative_to(run_dir):
        raise ToolError("Replay output must be outside the original run")
    source_files = list(run_dir.glob("facts-source.*"))
    if len(source_files) != 1:
        raise ToolError("Run snapshot needs exactly one original fact file")
    out = new_output(output, run_dir)
    started = datetime.now(timezone.utc).isoformat()
    try:
        rerun = infer_graph(run_dir / "snapshot/package", facts=source_files[0], output=out / "replayed")
        compared = Graph()
        matches = []
        for name in ("input.ttl", "result.ttl", "closure.ttl", "trace.ttl", "shacl-report.ttl", "post-shacl-report.ttl"):
            before, after = run_dir / name, rerun / name
            if not before.exists() and not after.exists():
                continue
            equal = before.exists() and after.exists() and isomorphic(parse_rdf(before), parse_rdf(after))
            matches.append(equal)
            node = URIRef("urn:ontology-tools:comparison:" + name)
            compared.add((RUN, OT.comparison, node))
            compared.add((node, OT.path, Literal(name)))
            compared.add((node, OT.isomorphic, Literal(equal)))
        equal = all(matches) and bool(matches)
        compared.add((RUN, OT.status, Literal("passed" if equal else "failed")))
        write_graph(compared, out / "replay-report.ttl")
        _finish(out, _record("replay", "passed" if equal else "failed", started, 0 if equal else 1), f"Replay: {'passed' if equal else 'failed'}.\n\nCompared {len(matches)} RDF graphs by isomorphism. Input/model snapshot, source fingerprints and dependency versions were checked. Timestamps are expected to differ; they are not compared as graph outputs.\n")
        return out
    except Exception as exc:
        _finish(out, _record("replay", "failed", started, 2, exc), f"Replay failed: {exc}\n")
        if isinstance(exc, ToolError):
            raise
        raise ToolError(str(exc)) from exc
