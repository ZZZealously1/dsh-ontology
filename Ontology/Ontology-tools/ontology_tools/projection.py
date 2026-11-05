"""Finite named-fact exchange between HermiT and the supported SWRL layer.

This is not a complete OWL DL + SWRL reasoner. In particular, consequences
requiring rules to be evaluated inside alternative OWL models can be missed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextvars import ContextVar
import hashlib
from pathlib import Path
import shutil

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .backend import (SWRL, _canonical_scope, _check_property_values,
                      apply_swrl_rules, compile_swrl_rules, normalize_projection_literals, swrl_seed)
from .io import (OT, ToolError, ValidationError, code_files, enclosing_packages,
                 file_set, new_output, safe_path, sha256, verify_manifest,
                 write_graph, write_manifest)

PROFILE = "hermit-swrl-projection-v1"
CALCULATION_PROFILE = "hermit-swrl-calculation-v1"
FORMULA_PROFILE = "hermit-swrl-formula-v1"
PROFILES = {PROFILE, CALCULATION_PROFILE, FORMULA_PROFILE}
CALCULATION_DEFAULTS = {"maxMatches": 100000, "maxEvaluations": 100000,
                        "maxGeneratedLiterals": 10000, "maxNumericDigits": 1000}
RUN = URIRef("urn:ontology-tools:run")
_SOURCE_BYTES = ContextVar("projection_source_bytes", default=None)


class ProjectionSemanticError(ToolError):
    """A completed OWL semantic check rejected this run."""
    exit_code = 1


def _read(path):
    from .owl_dl import _parse
    path = Path(path).resolve()
    if not path.is_file():
        raise ToolError(f"Missing local RDF file: {path}")
    cache = _SOURCE_BYTES.get()
    if cache is None:
        raw = path.read_bytes()
    else:
        if path not in cache:
            cache[path] = path.read_bytes()
        raw = cache[path]
    return _parse(raw, path)


def _config(package):
    result = {"profile": PROFILE, "validationOrder": "pre-post",
              "maxIterations": 100, "javaExecutable": "java", "javaTimeout": 60}
    path = package / "runtime.ttl"
    if not path.is_file():
        raise ToolError("Projection execution requires an explicit runtime.ttl profile")
    graph = _read(path)
    roots = list(graph.subjects(RDF.type, OT.Runtime))
    if len(roots) != 1:
        raise ToolError("runtime.ttl requires exactly one ot:Runtime")
    root = roots[0]
    profiles = list(graph.objects(root, OT.profile))
    if len(profiles) == 1 and str(profiles[0]) in {CALCULATION_PROFILE, FORMULA_PROFILE}:
        result.update(CALCULATION_DEFAULTS)
        if str(profiles[0]) == FORMULA_PROFILE:
            result["formulaPrecision"] = 50
    allowed = {RDF.type, RDFS.label, RDFS.comment} | {OT[k] for k in result}
    for _, predicate, _ in graph.triples((root, None, None)):
        if predicate not in allowed:
            raise ToolError(f"Unsupported runtime option: {predicate}")
    for name in result:
        values = list(graph.objects(root, OT[name]))
        if len(values) > 1 or any(not isinstance(v, Literal) for v in values):
            raise ToolError(f"Runtime option requires one literal: {name}")
        if values:
            result[name] = str(values[0])
    if result["profile"] not in PROFILES:
        raise ToolError(f"Exchange requires one of profiles {sorted(PROFILES)}")
    if result["validationOrder"] not in {"pre", "post", "pre-post"}:
        raise ToolError("validationOrder must be pre, post or pre-post")
    for name in ("maxIterations", "javaTimeout", *(k for k in CALCULATION_DEFAULTS if k in result),
                 *(k for k in ("formulaPrecision",) if k in result)):
        try:
            result[name] = int(result[name])
        except (ValueError, TypeError) as exc:
            raise ToolError(f"{name} must be a positive integer") from exc
        if result[name] < 1:
            raise ToolError(f"{name} must be a positive integer")
    if not result["javaExecutable"]:
        raise ToolError("javaExecutable must not be empty")
    if result["profile"] == FORMULA_PROFILE and not 2 <= result["formulaPrecision"] <= result["maxNumericDigits"]:
        raise ToolError("formulaPrecision must be between 2 and maxNumericDigits")
    return result


def _fact_role(data):
    annotations = {RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy}
    for s, predicate, obj in data:
        if str(predicate).startswith(str(SWRL)) or (
                predicate == RDF.type and str(obj).startswith(str(SWRL))):
            raise ToolError("Dynamic facts cannot define SWRL rules")
        if predicate in {OWL.sameAs, OWL.differentFrom}:
            if not isinstance(s, URIRef) or not isinstance(obj, URIRef):
                raise ToolError("Dynamic identity assertions require named individuals")
            continue
        if (str(predicate).startswith(str(OWL)) or
            (str(predicate).startswith(str(RDFS)) and predicate not in annotations) or
            (predicate == RDF.type and (obj in {RDF.Property, RDFS.Class, RDFS.Datatype} or
             (str(obj).startswith(str(OWL)) and obj != OWL.NamedIndividual)))):
            raise ToolError("Dynamic facts cannot modify TBox/schema; put reviewed schema in ontology.ttl")


def _ontology(package):
    """Resolve only explicitly mapped imports inside this package, without I/O elsewhere."""
    mappings = {}
    mapping = package / "imports-map.ttl"
    if mapping.exists():
        graph = _read(mapping)
        for node in graph.subjects(RDF.type, OT.ImportMapping):
            iris, paths = list(graph.objects(node, OT.ontologyIRI)), list(graph.objects(node, OT.path))
            if (len(iris) != 1 or not isinstance(iris[0], URIRef) or len(paths) != 1
                    or not isinstance(paths[0], Literal) or iris[0] in mappings):
                raise ToolError("ImportMapping requires one unique ontologyIRI and one local path")
            mappings[iris[0]] = safe_path(package, str(paths[0])).resolve()
    pending, seen, combined = [(package / "ontology.ttl", None)], {}, Graph()
    while pending:
        path, imported = pending.pop(0)
        if path in seen:
            graph = seen[path]
        else:
            graph = _read(path)
            seen[path] = graph
            if any(isinstance(term, URIRef) and str(term).startswith(str(SWRL))
                   for triple in graph for term in triple):
                raise ToolError("SWRL must be in the separate rules.swrl graph")
            for source, _, target in graph.triples((None, OWL.imports, None)):
                if (source, RDF.type, OWL.Ontology) not in graph:
                    raise ToolError("owl:imports requires an explicitly declared ontology header")
                if not isinstance(target, URIRef) or target not in mappings:
                    raise ToolError(f"Unmapped owl:imports; network resolution is disabled: {target}")
                pending.append((mappings[target], target))
            semantic = Graph()
            for triple in graph:
                if triple[1] != OWL.imports:
                    semantic.add(triple)
            scoped = _canonical_scope(semantic, "model-" + str(len(seen)))
            for triple in scoped:
                combined.add(triple)
        if imported is not None:
            heads = set(graph.subjects(RDF.type, OWL.Ontology))
            identities = heads | {v for h in heads for v in graph.objects(h, OWL.versionIRI)}
            if imported not in identities:
                raise ToolError(f"Import mapping IRI does not match source ontology/version IRI: {imported}")
    return combined


def load_projection(package, facts=None):
    """Read a flat execution package; return the same tuple shape as core._load."""
    from .core import _shape_check
    package = Path(package).resolve()
    if not package.is_dir():
        raise ToolError(f"Missing package directory: {package}")
    file_set(package)
    frozen = verify_manifest(package)
    config, ontology = _config(package), _ontology(package)
    if config["profile"] != FORMULA_PROFILE and (package / "formulas.ttl").exists():
        raise ToolError("formulas.ttl requires the explicit hermit-swrl-formula-v1 profile; legacy profiles do not execute RDF ASTs")
    rules = _read(package / "rules.swrl") if (package / "rules.swrl").exists() else Graph()
    shapes = _read(package / "shapes.ttl")
    _shape_check(shapes)
    facts_path = Path(facts).resolve() if facts is not None else package / "inputs/facts.ttl"
    enclosing_packages(facts_path)
    data = _canonical_scope(_read(facts_path), "input-data")
    _fact_role(data)
    if config["profile"] in {CALCULATION_PROFILE, FORMULA_PROFILE}:
        from .calculation_rules import compile_calculation_rules, calculation_seed
        from .scalar import validate_temporal_literals
        compiled = compile_calculation_rules(rules, ontology)
        seed, _ = calculation_seed(rules)
        validate_temporal_literals(ontology + seed + data + rules)
        if config["profile"] == FORMULA_PROFILE:
            from .formula_exchange import check_catalog, check_requests, check_rule_boundaries, seed_graph
            catalog = check_catalog(_read(package / "formulas.ttl"))
            check_requests(data)
            ontology += seed_graph(catalog, data)
            check_rule_boundaries(compiled, ontology)
    else:
        compiled = compile_swrl_rules(rules)
        seed, _ = swrl_seed(rules)
    _check_property_values(ontology + seed + data, compiled)
    for path in ("provenance.ttl", "mapping.ttl", "tests/cases.ttl"):
        if (package / path).exists():
            _read(package / path)
    return package, config, ontology, rules, shapes, data, facts_path, frozen


def inspect_projection(package, output=None):
    package, config, ontology, rules, shapes, data, _, frozen = load_projection(package)
    report = Graph()
    report.add((RUN, RDF.type, OT.PackageInspection))
    for predicate, value in {OT.status: "passed", OT.profile: config["profile"],
                             OT.frozen: frozen, OT.validationOrder: config["validationOrder"],
                             OT.ontologyTriples: len(ontology), OT.factTriples: len(data),
                             OT.ruleCount: len(set(rules.subjects(RDF.type, SWRL.Imp))),
                             OT.fullOWLConsistency: "not_run"}.items():
        report.add((RUN, predicate, Literal(value)))
    for rel, path in file_set(package).items():
        node = URIRef("urn:ontology-tools:file:" + hashlib.sha256(rel.encode()).hexdigest())
        report.add((RUN, OT.file, node))
        report.add((node, OT.path, Literal(rel)))
        report.add((node, OT.sha256, Literal(sha256(path))))
    if output is not None:
        out = new_output(output, package)
        write_graph(report, out / "inspection.ttl")
        (out / "report.md").write_text(
            f"Package inspection: passed. Profile: `{config['profile']}`.\n\n"
            "This checks local loading, supported SWRL and input roles. OWL DL checking is not run.\n",
            encoding="utf-8")
        write_manifest(out)
    return report


def validate_projection(package, facts=None, output=None):
    from .core import _validate
    package, _, ontology, _, shapes, data, path, _ = load_projection(package, facts)
    conforms, report = _validate(data, ontology, shapes)
    if output is not None:
        out = new_output(output, package, *enclosing_packages(path))
        write_graph(report, out / "shacl-report.ttl")
        (out / "report.md").write_text(
            f"Input SHACL: {'passed' if conforms else 'failed'}.\n\n"
            "Only explicit model and facts were checked; no DL or rule inference ran.\n", encoding="utf-8")
        write_manifest(out)
    return report


def _snapshot(out, package, facts_path, config, ontology, rules, shapes, data, raw_sources):
    for rel, path in file_set(package).items():
        target = out / "snapshot/package" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw_sources.get(path.resolve(), path.read_bytes()))
    for rel, path in code_files().items():
        target = out / "snapshot/tool" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (out / ("facts-source" + facts_path.suffix)).write_bytes(raw_sources[facts_path.resolve()])
    # A source package with a manifest must remain byte-exact in the snapshot.
    # Parsed source bytes above are the ones captured by _read, not a later read.
    verify_manifest(out / "snapshot/package")
    # The separately captured, parsed graphs keep the original document bases.
    # Replay never reparses relative IRIs against a relocated source directory.
    replay = out / "snapshot/semantic-package"
    replay.mkdir(parents=True)
    write_graph(ontology, replay / "ontology.ttl")
    rules.serialize(destination=str(replay / "rules.swrl"), format="xml", encoding="utf-8")
    write_graph(shapes, replay / "shapes.ttl")
    write_graph(data, replay / "inputs/facts.ttl")
    if config["profile"] == FORMULA_PROFILE:
        from .owl_dl import _parse
        formula_path = package / "formulas.ttl"
        formula_graph = _parse(raw_sources[formula_path.resolve()], formula_path)
        write_graph(formula_graph, replay / "formulas.ttl")
        write_graph(formula_graph, out / "formulas.ttl")
    runtime = Graph()
    runtime.add((RUN, RDF.type, OT.Runtime))
    for name, value in config.items():
        runtime.add((RUN, OT[name], Literal(value)))
    write_graph(runtime, replay / "runtime.ttl")
    write_manifest(replay)
    write_graph(data, out / "input.ttl")
    return replay


def _scope_owl_trace(source, round_number):
    """Preserve snapshot evidence, without mixing the local node IDs of rounds."""
    round_node = URIRef(f"urn:ontology-tools:projection-round:{round_number}")
    nodes = {RUN} | set(source.objects(RUN, OT.entailment))
    remap = {node: URIRef(f"urn:ontology-tools:round:{round_number}:" +
                         hashlib.sha256(str(node).encode()).hexdigest()) for node in nodes}
    result = Graph()
    prefix = f"rounds/round-{round_number:04d}/owl/"
    for subject, predicate, obj in source:
        subject = remap.get(subject, subject)
        if predicate in {OT.inputSnapshot, OT.candidateSnapshot} and isinstance(obj, Literal):
            obj = Literal(prefix + str(obj))
        elif predicate not in {RDF.subject, RDF.predicate, RDF.object}:
            obj = remap.get(obj, obj)
        result.add((subject, predicate, obj))
    result.add((round_node, RDF.type, OT.ProjectionRound))
    result.add((round_node, OT.iteration, Literal(round_number)))
    result.add((round_node, OT.executionPath, Literal(prefix + "execution.ttl")))
    result.add((remap[RUN], OT.round, round_node))
    return result


def _calculation_contract(config):
    """Versioned function and execution semantics, included in replay comparison."""
    from .scalar import REGISTRY
    graph = Graph()
    graph.add((RUN, RDF.type, OT.CalculationContract))
    graph.add((RUN, OT.contractVersion, Literal("scalar-v1")))
    graph.add((RUN, OT.candidatePolicy, Literal("successful-head-literals-only")))
    graph.add((RUN, OT.temporalPolicy, Literal("explicit-timezone; 0001-9999; milliseconds; generated UTC xsd:dateTime")))
    graph.add((RUN, OT.numericPolicy, Literal("exact-integer-decimal; finite-exact-divide; explicit-rounded-divide")))
    graph.add((RUN, OT.errorPolicy, Literal("comparison-false-unmatches; undefined-computation-fails")))
    for name, value in config.items():
        graph.add((RUN, OT[name], Literal(value)))
    for iri, spec in sorted(REGISTRY.items(), key=lambda item: str(item[0])):
        graph.add((RUN, OT.function, iri))
        graph.add((iri, OT.functionVersion, Literal(spec.version)))
        graph.add((iri, OT.arity, Literal(spec.arity)))
        for position in spec.input_positions:
            graph.add((iri, OT.inputPosition, Literal(position)))
        if spec.output_position is not None:
            graph.add((iri, OT.outputPosition, Literal(spec.output_position)))
    return graph


def _budget_evidence(budget):
    graph = Graph()
    graph.add((RUN, RDF.type, OT.CalculationBudget))
    for name, value in (("maxMatches", budget.max_matches),
                        ("maxEvaluations", budget.max_evaluations),
                        ("maxGeneratedLiterals", budget.max_generated_literals),
                        ("maxNumericDigits", budget.max_numeric_digits),
                        ("matches", budget.matches), ("evaluations", budget.evaluations),
                        ("generatedLiteralCount", len(budget.generated_literals))):
        graph.add((RUN, OT[name], Literal(value)))
    return graph


def _temporal_working_graphs(model, rules, data, shapes):
    """Value-preserving UTC adapter for the selected calculation profile only.

    The bundled HermiT compares nonzero-offset lexical representations
    incorrectly. Keep raw snapshots and input.ttl untouched, and use one
    explicitly documented UTC view for DL, rules and post-validation.
    """
    from .scalar import annotation_literal_positions, canonical_temporal_literal
    from rdflib.namespace import XSD
    combined = model + rules + data + shapes
    annotations = annotation_literal_positions(combined)
    mapping, converted = Graph(), []
    mapping.add((RUN, RDF.type, OT.TemporalNormalization))
    mapping.add((RUN, OT.normalization, Literal("calculation-utc-v1: semantic instants use UTC Z; datatype retained; annotations and source bytes retained")))
    for role, source in (("ontology", model), ("rules", rules), ("facts", data), ("shapes", shapes)):
        target = Graph()
        for s, p, o in source:
            value = o
            if ((s, p) not in annotations and isinstance(o, Literal)
                    and o.datatype in {XSD.dateTime, XSD.dateTimeStamp}):
                value = canonical_temporal_literal(o)
                if value != o:
                    payload = role + "\n" + o.n3() + "\n" + value.n3()
                    change = URIRef("urn:ontology-tools:time-normalization:" + hashlib.sha256(payload.encode()).hexdigest())
                    mapping.add((RUN, OT.transformation, change))
                    mapping.add((change, OT.role, Literal(role)))
                    mapping.add((change, OT.originalValue, o))
                    mapping.add((change, OT.normalizedValue, value))
            target.add((s, p, value))
        converted.append(target)
    return (*converted, mapping)


def infer_projection(package, facts=None, output=None):
    """Run the finite projection to a fixed point, saving every rejected round."""
    from .core import _finish, _record, _validate, _selected_profile
    from .owl_dl import _runtime, collect_candidates, infer_owl
    if output is None:
        raise ToolError("An explicit new output directory is required")
    package = Path(package).resolve()
    out = new_output(output, package, *(enclosing_packages(Path(facts)) if facts is not None else []))
    started, stage = datetime.now(timezone.utc).isoformat(), "inspect"
    config, evidence, semantic_state = {}, Graph(), "not_run"
    profile, calculation, formula_mode, budget = PROFILE, False, False, None
    computations = Graph()
    formula_computations = Graph()
    formula_diagnostics = Graph()
    rounds = 0
    try:
        profile = _selected_profile(package)
        formula_mode = profile == FORMULA_PROFILE
        calculation = profile in {CALCULATION_PROFILE, FORMULA_PROFILE}
        raw_sources = {}
        token = _SOURCE_BYTES.set(raw_sources)
        try:
            package, config, model, rules, shapes, data, facts_path, frozen = load_projection(package, facts)
            if formula_mode:
                from .formula import evaluate_catalog, normalize_numeric_facts
                from .formula_exchange import check_catalog, contract_graph, evidence_graph, validate_result
                catalog_graph = _read(package / "formulas.ttl")
                catalog = check_catalog(catalog_graph)
        finally:
            _SOURCE_BYTES.reset(token)
        # RDF 1.1 plain strings and xsd:string denote the same term. Keep exact
        # raw bytes separately, while giving both engines the same spelling.
        model, rules, shapes, data = [normalize_projection_literals(g) for g in (model, rules, shapes, data)]
        _snapshot(out, package, facts_path, config, model, rules, shapes, data, raw_sources)
        if formula_mode:
            # HermiT can project decimal/integer spellings of the same exact
            # value. Canonicalize formula numeric fields only in working graphs;
            # _snapshot above retains every original input literal unchanged.
            model, data = [normalize_numeric_facts(graph, max_numeric_digits=config["maxNumericDigits"])
                           for graph in (model, data)]
            evidence.add((RUN, OT.numericNormalization, Literal(
                "formula-exact-numeric-v1: legal integer/decimal f:value and f:result "
                "use one exact decimal spelling; conflicting/invalid values remain rejected")))
        evidence.add((RUN, OT.normalization, Literal(
            "projection-rdf11-v1: untagged plain strings use xsd:string; reflexive "
            "identity tautologies are not reasserted as OWLAPI feedback axioms")))
        evidence.add((RUN, OT.replayPackage, Literal("snapshot/semantic-package")))
        evidence.add((RUN, OT.replayFacts, Literal("input.ttl")))
        evidence.add((RUN, OT.sourcePackage, Literal(str(package))))
        evidence.add((RUN, OT.factSourcePath, Literal(str(facts_path))))
        evidence.add((RUN, OT.frozen, Literal(frozen)))
        if calculation:
            from .calculation_rules import (CalculationBudget, CalculationExecutionError,
                                             apply_calculation_rules, calculation_seed)
            from .scalar import validate_temporal_literals
            seed, rule_literals = calculation_seed(rules)
            budget = CalculationBudget(max_matches=config["maxMatches"],
                max_evaluations=config["maxEvaluations"],
                max_generated_literals=config["maxGeneratedLiterals"],
                max_numeric_digits=config["maxNumericDigits"])
            write_graph(_calculation_contract(config), out / "calculation-contract.ttl")
            evidence.add((RUN, OT.calculationContract, Literal("calculation-contract.ttl")))
            if formula_mode:
                write_graph(contract_graph(config), out / "formula-contract.ttl")
                evidence.add((RUN, OT.formulaContract, Literal("formula-contract.ttl")))
        else:
            seed, rule_literals = swrl_seed(rules)
        ontology = model + seed
        prepared = out / "prepared"
        write_graph(ontology, prepared / "ontology.ttl")
        write_graph(data, prepared / "facts.ttl")
        stage = "runtime"
        _runtime(out, evidence)
        if config["validationOrder"] in {"pre", "pre-post"}:
            stage = "pre-validation"
            conforms, report = _validate(data, ontology, shapes)
            write_graph(report, out / "shacl-report.ttl")
            if not conforms:
                semantic_state = "shacl-invalid"
                raise ValidationError("Input SHACL failed; projection inference was not run")
        if calculation:
            stage = "temporal-normalization"
            model, rules, data, shapes, time_mapping = _temporal_working_graphs(model, rules, data, shapes)
            seed, rule_literals = calculation_seed(rules)
            ontology = model + seed
            write_graph(ontology, prepared / "ontology.ttl")
            write_graph(data, prepared / "facts.ttl")
            write_graph(rules, prepared / "rules.ttl")
            write_graph(shapes, prepared / "shapes.ttl")
            write_graph(time_mapping, out / "temporal-normalization.ttl")
            evidence.add((RUN, OT.temporalNormalization, Literal("temporal-normalization.ttl")))
        stage = "candidate-collection"
        collected = collect_candidates(
            prepared / "ontology.ttl", out / "candidate-collection",
            facts=prepared / "facts.ttl", java=config["javaExecutable"], timeout=config["javaTimeout"])
        candidates = _read(collected / "candidates.ttl")
        roots = list(candidates.subjects(RDF.type, OT.CandidateDomain))
        if len(roots) != 1:
            raise ToolError("Candidate collector did not return exactly one frozen domain")
        known_individuals = set(candidates.objects(roots[0], OT.individual))
        for literal in rule_literals:
            candidates.add((roots[0], OT.literal, literal))
        write_graph(candidates, out / "candidates.ttl")
        if calculation:
            write_graph(candidates, out / "initial-candidates.ttl")
        accumulated, trace, initial = Graph(), Graph(), ontology + data
        for triple in data:
            accumulated.add(triple)
        classification, final_facts = Graph(), Graph()
        while True:
            rounds += 1
            round_dir = out / "rounds" / f"round-{rounds:04d}"
            write_graph(accumulated, round_dir / "input.ttl")
            candidate_path = out / "candidates.ttl"
            if calculation:
                candidate_path = round_dir / "candidates.ttl"
                write_graph(candidates, candidate_path)
                validate_temporal_literals(ontology + accumulated + candidates)
            stage = "owl-inference"
            owl_out = infer_owl(
                prepared / "ontology.ttl", round_dir / "owl",
                facts=round_dir / "input.ttl", candidates=candidate_path,
                java=config["javaExecutable"], timeout=config["javaTimeout"])
            owl_execution = _read(owl_out / "execution.ttl")
            owl_report_path = owl_out / "owl-report.ttl"
            if not owl_report_path.exists():
                owl_report_path = owl_out / "report.ttl"
            if owl_report_path.exists():
                owl_report = _read(owl_report_path)
                write_graph(owl_report, out / "owl-report.ttl")
                evidence.set((RUN, OT.owlReport, Literal("owl-report.ttl")))
                for predicate in (OT.consistent, OT.unsatisfiableClass, OT.profileConforms):
                    evidence.remove((RUN, predicate, None))
                    for value in owl_report.objects(RUN, predicate):
                        evidence.add((RUN, predicate, value))
            else:
                owl_report = Graph()
            for predicate in (OT.javaVersion, OT.javaVendor, OT.reasoner, OT.reasonerVersion):
                for value in owl_execution.objects(RUN, predicate):
                    evidence.set((RUN, predicate, value))
            status = str(owl_execution.value(RUN, OT.status))
            if status != "passed":
                if status == "nonconformant":
                    semantic_state = ("inconsistent" if owl_report.value(RUN, OT.consistent) == Literal(False)
                                      else "unsatisfiable" if any(owl_report.objects(RUN, OT.unsatisfiableClass))
                                      else "profile-violation")
                    raise ProjectionSemanticError(f"OWL DL rejected round {rounds}: {semantic_state}")
                raise ToolError(f"OWL inference did not complete successfully in round {rounds}")
            semantic_state = "conformant"
            final_facts = _read(owl_out / "facts.ttl")
            if formula_mode:
                final_facts = normalize_numeric_facts(final_facts, max_numeric_digits=config["maxNumericDigits"])
            classification = _read(owl_out / "classification.ttl")
            owl_trace = _read(owl_out / "trace.ttl")
            # Preserve bridge evidence without pretending it is an axiom proof.
            for triple in _scope_owl_trace(owl_trace, rounds):
                trace.add(triple)
            stage = "swrl-inference"
            if calculation:
                try:
                    rule_result = apply_calculation_rules(rules, final_facts, candidates,
                        iteration=rounds, budget=budget, model=ontology)
                except CalculationExecutionError as exc:
                    write_graph(exc.trace, round_dir / "swrl-trace.ttl")
                    write_graph(exc.computations, round_dir / "computations.ttl")
                    for triple in exc.computations:
                        computations.add(triple)
                    write_graph(computations, out / "computations.ttl")
                    raise
                write_graph(rule_result.computations, round_dir / "computations.ttl")
                for triple in rule_result.computations:
                    computations.add(triple)
                write_graph(computations, out / "computations.ttl")
                write_graph(_budget_evidence(budget), round_dir / "budget.ttl")
            else:
                rule_result = apply_swrl_rules(rules, final_facts, candidates, iteration=rounds)
            write_graph(rule_result.inferred, round_dir / "swrl-result.ttl")
            write_graph(rule_result.trace, round_dir / "swrl-trace.ttl")
            for triple in rule_result.trace:
                trace.add(triple)
            # All DL facts must be visible to the next rule step. Only a new
            # rule conclusion can require another DL call: its projection is
            # already complete over the fixed candidates for the current model.
            new = set(rule_result.inferred) - set(final_facts)
            formula_rule_facts = rule_result.inferred
            if formula_mode:
                formula_rule_facts = normalize_numeric_facts(rule_result.inferred,
                    max_numeric_digits=config["maxNumericDigits"])
                new = set(formula_rule_facts) - set(final_facts)
            new_literals = set()
            formula_literals = set()
            if formula_mode:
                stage = "formula-evaluation"
                formula_result = evaluate_catalog(catalog, final_facts + formula_rule_facts,
                    precision=config["formulaPrecision"], max_evaluations=config["maxEvaluations"],
                    max_numeric_digits=config["maxNumericDigits"], iteration=rounds)
                formula_trace = evidence_graph(formula_result, rounds)
                write_graph(formula_trace, round_dir / "formula-computations.ttl")
                formula_computations += formula_trace
                write_graph(formula_computations, out / "formula-computations.ttl")
                formula_diagnostics = evidence_graph(type(formula_result)(diagnostics=formula_result.diagnostics), rounds)
                write_graph(formula_diagnostics, out / "formula-diagnostics.ttl")
                used = validate_result(formula_result, known_individuals,
                    config["maxGeneratedLiterals"], config["maxEvaluations"] - budget.evaluations)
                budget.evaluations += used
                formula_delta = normalize_projection_literals(formula_result.facts)
                new |= set(formula_delta) - set(final_facts)
                formula_literals = {o for _, _, o in formula_delta if isinstance(o, Literal)}
                for literal in formula_literals:
                    budget.generate(literal)
                write_graph(formula_delta, round_dir / "formula-result.ttl")
            if calculation:
                new_literals = (set(rule_result.generated_literals) | formula_literals) - set(candidates.objects(roots[0], OT.literal))
                for literal in new_literals:
                    candidates.add((roots[0], OT.literal, literal))
                write_graph(candidates, out / "candidates.ttl")
            if not new and not new_literals:
                break
            if rounds >= config["maxIterations"]:
                raise ToolError(f"No fixed point within {config['maxIterations']} projection rounds")
            for triple in final_facts:
                # RDF a sameAs a is tautologically true, but the OWLAPI RDF
                # mapper turns it into unary SameIndividual(a), outside the
                # structural OWL 2 DL syntax. Never feed this generated
                # tautology back as a new axiom.
                if not (triple[1] == OWL.sameAs and triple[0] == triple[2]):
                    accumulated.add(triple)
            for triple in new:
                accumulated.add(triple)
        closure = initial + final_facts + classification
        if formula_mode:
            closure = normalize_numeric_facts(closure, max_numeric_digits=config["maxNumericDigits"])
        if config["validationOrder"] in {"post", "pre-post"}:
            stage = "post-validation"
            conforms, report = _validate(closure, Graph(), shapes)
            write_graph(report, out / "post-shacl-report.ttl")
            if not conforms:
                semantic_state = "shacl-invalid"
                raise ValidationError("Output SHACL failed; projection result is not accepted")
        result = Graph()
        for triple in final_facts:
            if triple not in initial:
                result.add(triple)
        write_graph(result, out / "result.ttl")
        write_graph(closure, out / "closure.ttl")
        write_graph(classification, out / "classification.ttl")
        write_graph(trace, out / "trace.ttl")
        record = _record("complete", "passed", started, profile=profile)
        for triple in evidence:
            record.add(triple)
        record.set((RUN, OT.fullOWLConsistency, Literal("checked-each-round")))
        record.add((RUN, OT.semanticState, Literal("conformant")))
        record.add((RUN, OT.iterations, Literal(rounds)))
        record.add((RUN, OT.inferredTriples, Literal(len(result))))
        for name in ("validationOrder", "maxIterations", "javaExecutable", *(CALCULATION_DEFAULTS if calculation else ())):
            record.add((RUN, OT[name], Literal(config[name])))
        record.add((RUN, OT.timeoutSeconds, Literal(config["javaTimeout"])))
        if formula_mode:
            record.add((RUN, OT.formulaPrecision, Literal(config["formulaPrecision"])))
            record.add((RUN, OT.formulaCount, Literal(len(catalog.formulas))))
            record.add((RUN, OT.pendingFormulaCount, Literal(len(formula_result.diagnostics))))
        if calculation:
            write_graph(_budget_evidence(budget), out / "budget.ttl")
        scope = (("Named evaluations were frozen; verified RDF formula ASTs were evaluated separately from OWL/SWRL. "
                  "Only complete successful formula results and rule-head values expanded candidates. "
                  "Missing parameters/conditions remain pending; formula-computations.ttl records calculations. ")
                 if formula_mode else
                 ("Named entities were frozen; only successful rule-head literal values expanded each round's candidates. "
                 "Calculation arguments, results and effective policies are saved in computations.ttl and calculation-contract.ttl. "
                 if calculation else
                 "Candidates were frozen before inference. No anonymous witnesses or new literal values were created. "))
        _finish(out, record,
                f"# Finite OWL DL / SWRL projection\n\nStatus: passed. Profile: `{profile}`.\n\n"
                f"OWL/rule rounds: {rounds}. New ABox facts: {len(result)}.\n\n"
                + scope +
                "This fixed point is not complete OWL DL + SWRL reasoning; conclusions requiring reasoning "
                "across alternative OWL models can be missing. OWL evidence identifies the reasoner call, "
                "not a per-axiom proof. External systems: not_run.\n")
        return out
    except Exception as exc:
        # A write or final validation failure must never leave a top-level
        # graph that a caller could mistake for an accepted result.
        for name in ("result.ttl", "closure.ttl", "classification.ttl", "trace.ttl"):
            (out / name).unlink(missing_ok=True)
        code = getattr(exc, "exit_code", 2)
        if code == 2:
            semantic_state = "unknown"
            for predicate in (OT.consistent, OT.unsatisfiableClass, OT.profileConforms):
                evidence.remove((RUN, predicate, None))
        status = "nonconformant" if code == 1 else "failed"
        record = _record(stage, status, started, code, exc, profile=profile)
        for triple in evidence:
            record.add(triple)
        record.add((RUN, OT.semanticState, Literal(semantic_state)))
        record.add((RUN, OT.iterations, Literal(rounds)))
        for name in ("validationOrder", "maxIterations", "javaExecutable", *CALCULATION_DEFAULTS):
            if name in config:
                record.add((RUN, OT[name], Literal(config[name])))
        if "javaTimeout" in config:
            record.add((RUN, OT.timeoutSeconds, Literal(config["javaTimeout"])))
        if budget is not None:
            write_graph(_budget_evidence(budget), out / "budget.ttl")
        _finish(out, record,
                f"# Finite OWL DL / SWRL projection\n\nStatus: {status}. Stage: {stage}. Exit: {code}.\n\n"
                f"{exc}\n\nOnly diagnostics and rejected round artifacts are retained. "
                "No top-level result or closure is accepted. External systems: not_run.\n")
        if isinstance(exc, ToolError):
            raise
        raise ToolError(str(exc)) from exc
