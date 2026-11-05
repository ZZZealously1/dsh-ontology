"""Formula-role loading, evidence and fixed-domain guards for the formula profile.

This module is generic. Domain formula expressions stay in formulas.ttl; domain
applicability and diagnostic policy stay in the loaded OWL/SWRL graphs.
"""
from __future__ import annotations

from hashlib import sha256

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from .backend import SWRL
from .formula import F, compile_catalog, scientific_metadata
from .io import OT, ToolError

PROFILE = "hermit-swrl-formula-v1"
RUN = URIRef("urn:ontology-tools:run")
OWNED_OUTPUTS = frozenset({F.result, F.resultUnit, F.calculationStatus})
PENDING_CODES = frozenset({"missing-condition", "missing-input", "dependency-failed"})


def check_catalog(graph):
    catalog = compile_catalog(graph)
    if catalog.issues:
        raise ToolError("Enabled formula catalog is invalid: " + "; ".join(
            str(item) for item in catalog.issues))
    return catalog


def check_requests(data):
    for predicate in OWNED_OUTPUTS | {F.satisfiedCondition}:
        if any(data.triples((None, predicate, None))):
            raise ToolError("Dynamic inputs cannot prewrite calculator outputs or derived applicability: " + str(predicate))
    # No formula graph supplied by --facts can alter the immutable catalog role.
    for predicate in (F.enabled, F.verified, F.expression, F.parameters, F.arguments,
                      F.operator, F.requiredCondition, F.unconditional):
        if any(data.triples((None, predicate, None))):
            raise ToolError("Dynamic inputs cannot modify the formula catalog: " + str(predicate))
    for evaluation in data.subjects(RDF.type, F.Evaluation):
        if not isinstance(evaluation, URIRef):
            raise ToolError("Formula evaluations must be pre-existing named individuals")


def seed_graph(catalog, data):
    """Expose only identities/required output terms; never load the AST into DL."""
    graph = Graph()
    for cls in (F.Formula, F.Evaluation, F.Binding, F.Condition, F.CalculationState):
        graph.add((cls, RDF.type, OWL.Class))
    for prop in (F.formula, F.context, F.binding, F.parameter, F.fromEvaluation,
                 F.satisfiedCondition, F.calculationStatus):
        graph.add((prop, RDF.type, OWL.ObjectProperty))
    for prop in (F.value, F.unit, F.result, F.resultUnit):
        graph.add((prop, RDF.type, OWL.DatatypeProperty))
    graph.add((F.Computed, RDF.type, F.CalculationState))
    requested = set(data.objects(None, F.formula))
    for iri in sorted(requested, key=str):
        if iri not in catalog.formulas:
            raise ToolError("Requested formula is unavailable: " + str(iri))
        formula = catalog.formulas[iri]
        graph.add((iri, RDF.type, F.Formula))
        # Output unit strings and status identities must be in the frozen terms.
        graph.add((F.frozenOutputUnit, RDF.type, OWL.DatatypeProperty))
        graph.add((iri, F.frozenOutputUnit, Literal(formula.output_unit)))
        for condition in formula.conditions:
            graph.add((condition, RDF.type, F.Condition))
        for parameter in formula.parameters:
            graph.add((parameter.iri, RDF.type, OWL.NamedIndividual))
    return graph


def check_rule_boundaries(compiled, model):
    """Reject result feedback into eligibility; calculations use an acyclic request DAG.

    Formula-v1 allows numerical results to refine diagnoses and flow through
    fromEvaluation dependencies. Eligibility itself must be established from
    observations/semantic conditions, not circular numerical self-permission.
    """
    edges = {}
    for rule in compiled:
        for head in rule.head:
            if head.predicate in OWNED_OUTPUTS:
                raise ToolError("Only the formula evaluator may write " + str(head.predicate))
            for body in rule.body:
                if body.kind != SWRL.BuiltinAtom:
                    edges.setdefault(body.predicate, set()).add(head.predicate)
    for predicate in (RDFS.subPropertyOf, OWL.equivalentProperty):
        for left, _, right in model.triples((None, predicate, None)):
            edges.setdefault(left, set()).add(right)
            if predicate == OWL.equivalentProperty:
                edges.setdefault(right, set()).add(left)
    pending, seen = list(OWNED_OUTPUTS), set()
    while pending:
        node = pending.pop()
        if node == F.satisfiedCondition:
            raise ToolError("Formula-result feedback into applicability is unsupported; declare an acyclic input dependency instead")
        if node not in seen:
            seen.add(node)
            pending.extend(edges.get(node, ()))


def contract_graph(config):
    graph = Graph()
    graph.add((RUN, RDF.type, F.CalculationContract))
    graph.add((RUN, OT.contractVersion, Literal("rdf-formula-ast-v1")))
    graph.add((RUN, OT.profile, Literal(PROFILE)))
    for key, value in scientific_metadata().items():
        graph.add((RUN, F[key], Literal(value)))
    graph.add((RUN, F.precision, Literal(config["formulaPrecision"])))
    graph.add((RUN, F.candidatePolicy, Literal("frozen-named-evaluations; successful-complete-formula-results-only")))
    graph.add((RUN, F.applicabilityPolicy, Literal("all-required-conditions-supported; no-result-feedback-into-eligibility")))
    graph.add((RUN, F.catalogPath, Literal("formulas.ttl")))
    return graph


def evidence_graph(result, iteration):
    """Convert generic computation records to RDF, without embedding JSON."""
    graph = Graph()

    def value_graph(subject, key, value):
        predicate = F[key]
        if isinstance(value, dict):
            child = URIRef(str(subject) + ":" + key)
            graph.add((subject, predicate, child))
            for subkey, subvalue in sorted(value.items()):
                value_graph(child, subkey, subvalue)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                child = URIRef(str(subject) + ":" + key + ":" + str(index))
                graph.add((subject, predicate, child))
                graph.add((child, F.position, Literal(index)))
                if isinstance(item, dict):
                    for subkey, subvalue in sorted(item.items()):
                        value_graph(child, subkey, subvalue)
                else:
                    graph.add((child, RDF.value, Literal(item)))
        else:
            term = (URIRef(value) if key in {"evaluation", "formula", "context", "operator", "parameter", "from_evaluation"}
                    and isinstance(value, str) else Literal(value))
            graph.add((subject, predicate, term))

    for kind, records in (("computation", result.trace), ("diagnostic", result.diagnostics)):
        for index, record in enumerate(records):
            identity = f"{iteration}:{kind}:{index}:" + str(record.get("evaluation", ""))
            node = URIRef("urn:ontology-tools:formula-" + kind + ":" + sha256(identity.encode()).hexdigest())
            graph.add((RUN, F[kind], node))
            graph.add((node, RDF.type, F.Computation if kind == "computation" else F.Diagnostic))
            graph.add((node, OT.iteration, Literal(iteration)))
            for key, value in sorted(record.items()):
                value_graph(node, key, value)
    for key, value in sorted(result.metadata.items()):
        value_graph(RUN, key, value)
    return graph


def validate_result(result, known, candidate_budget, evaluations_used):
    fatal = [item for item in result.diagnostics if item["code"] not in PENDING_CODES]
    if fatal:
        raise ToolError("Formula evaluation failed: " + "; ".join(
            item["code"] + ": " + item["message"] for item in fatal))
    generated = set(result.generated_literals)
    if len(generated) > candidate_budget:
        raise ToolError("Formula generated literal budget exhausted")
    for subject, _, obj in result.facts:
        if subject not in known or (isinstance(obj, URIRef) and obj not in known):
            raise ToolError("Formula evaluation attempted to create an unfrozen individual")
    used = sum(len(record.get("operations", ())) + len(record.get("bindings", ()))
               for record in result.trace)
    if used > evaluations_used:
        raise ToolError("Formula cumulative evaluation budget exhausted")
    return used
