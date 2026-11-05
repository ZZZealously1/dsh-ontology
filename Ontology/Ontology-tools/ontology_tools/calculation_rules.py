"""Deterministic ABox-only SWRL calculations for the explicit calculation profile.

This layer shares the existing SWRL syntax, named-domain matching and identity
handling. It does not interpret OWL restrictions or prove general termination.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from . import scalar
from .backend import (OT, SWRL, UnsupportedSemantics, _RULE_ENABLED, _SWRL_TERMS,
                      _check_property_values, _compile_rules, _copy, _id, _key,
                      _matches, _named_candidate_view, _rule_schema, _statement,
                      _triple_key, normalize_projection_literals)

PROFILE = "hermit-swrl-calculation-v1"


class CalculationExecutionError(ValueError):
    """A failed computation or budget, with the evidence collected so far."""

    def __init__(self, message, *, trace=None, computations=None, rule=None,
                 predicate=None, arguments=()):
        super().__init__(message)
        self.trace = trace if trace is not None else Graph()
        self.computations = computations if computations is not None else Graph()
        self.rule, self.predicate, self.arguments = rule, predicate, tuple(arguments)


@dataclass
class CalculationBudget:
    """One cumulative budget shared across all SWRL rounds in a run."""

    max_matches: int = 100000
    max_evaluations: int = 100000
    max_generated_literals: int = 10000
    max_numeric_digits: int = 1000
    matches: int = field(default=0, init=False)
    evaluations: int = field(default=0, init=False)
    generated_literals: set = field(default_factory=set, init=False)

    def __post_init__(self):
        for name in ("max_matches", "max_evaluations", "max_generated_literals",
                     "max_numeric_digits"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")

    def match(self):
        self.matches += 1
        if self.matches > self.max_matches:
            raise CalculationExecutionError("Calculation match budget exhausted")

    def evaluate(self):
        self.evaluations += 1
        if self.evaluations > self.max_evaluations:
            raise CalculationExecutionError("Calculation function evaluation budget exhausted")

    def generate(self, literal):
        self.generated_literals.add(literal)
        if len(self.generated_literals) > self.max_generated_literals:
            raise CalculationExecutionError("Calculation generated literal budget exhausted")


@dataclass(frozen=True)
class CalculationResult:
    closure: Graph
    inferred: Graph
    trace: Graph
    iterations: int
    computations: Graph
    generated_literals: frozenset[Literal]


def _parse_builtin(predicate, arguments, variables):
    try:
        spec = scalar.get_spec(predicate)
    except ValueError as exc:
        raise UnsupportedSemantics(str(exc)) from exc
    if len(arguments) != spec.arity:
        raise UnsupportedSemantics(f"{predicate} requires {spec.arity} arguments")
    if any(a not in variables and not isinstance(a, Literal) for a in arguments):
        raise UnsupportedSemantics("Calculation builtin constants must be RDF literals")


def _atom_key(atom):
    return (str(atom.kind), str(atom.predicate), tuple(map(_key, atom.arguments)))


def _schedule(body, head, variables):
    """Stable dependency scheduling; source list order is never procedural."""
    facts = sorted((a for a in body if a.kind != SWRL.BuiltinAtom), key=_atom_key)
    bound = {v for a in facts for v in a.arguments if v in variables}
    pending = sorted((a for a in body if a.kind == SWRL.BuiltinAtom), key=_atom_key)
    ordered = list(facts)
    while pending:
        ready = [a for a in pending if all(a.arguments[i] not in variables or
                 a.arguments[i] in bound for i in scalar.get_spec(a.predicate).input_positions)]
        if not ready:
            remaining = ", ".join(str(a.predicate) for a in pending)
            raise UnsupportedSemantics("Unbound calculation inputs or cyclic bindings: " + remaining)
        # A ready filter can remove a branch before an otherwise undefined
        # calculation (for example a nonzero-divisor guard). This priority is
        # independent of the source RDF-list order.
        atom = min(ready, key=lambda a: (scalar.get_spec(a.predicate).output_position is not None,
                                         _atom_key(a)))
        ordered.append(atom)
        pending.remove(atom)
        position = scalar.get_spec(atom.predicate).output_position
        if position is not None and atom.arguments[position] in variables:
            bound.add(atom.arguments[position])
    if any(v in variables and v not in bound for a in head for v in a.arguments):
        raise UnsupportedSemantics("All rule head variables must be bound by facts or calculations")
    return tuple(ordered)


def _reject_generation_cycles(compiled, model):
    """Conservative data-value dependency check, not an OWL termination proof."""
    edges = {}  # (source property, target property) -> rule/axiom descriptions
    generated_edges = set()

    def edge(source, target, description, generating=False):
        edges.setdefault((source, target), set()).add(description)
        if generating:
            generated_edges.add((source, target))

    for rule in compiled:
        body_data = [a for a in rule.body if a.kind == SWRL.DatavaluedPropertyAtom]
        origins = {}
        fact_bound = {v for a in rule.body if a.kind != SWRL.BuiltinAtom
                      for v in a.arguments if v in rule.variables}
        generated = set()
        for atom in body_data:
            if atom.arguments[1] in rule.variables:
                origins.setdefault(atom.arguments[1], set()).add(atom.predicate)
        for atom in rule.body:
            if atom.kind != SWRL.BuiltinAtom:
                continue
            spec = scalar.get_spec(atom.predicate)
            if spec.output_position is None:
                continue
            output = atom.arguments[spec.output_position]
            if output not in rule.variables or output in fact_bound:
                continue
            generated.add(output)
            sources = set().union(*(origins.get(atom.arguments[i], set())
                                    for i in spec.input_positions))
            origins.setdefault(output, set()).update(sources)
        for atom in rule.head:
            if atom.kind != SWRL.DatavaluedPropertyAtom:
                continue
            value = atom.arguments[1]
            sources = origins.get(value, set())
            # Guards also influence when generated values become available.
            if value in generated:
                sources = sources | {a.predicate for a in body_data}
            for source in sources:
                edge(source, atom.predicate, str(rule.identifier), value in generated)
    if model is not None:
        for source, _, target in model.triples((None, RDFS.subPropertyOf, None)):
            if isinstance(source, URIRef) and isinstance(target, URIRef):
                edge(source, target, "rdfs:subPropertyOf")
        for source, _, target in model.triples((None, OWL.equivalentProperty, None)):
            if isinstance(source, URIRef) and isinstance(target, URIRef):
                edge(source, target, "owl:equivalentProperty")
                edge(target, source, "owl:equivalentProperty")
    adjacency = {}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
    for source, target in sorted(generated_edges, key=lambda pair: tuple(map(str, pair))):
        pending, seen = [(target, [source, target])], set()
        while pending:
            node, path = pending.pop(0)
            if node == source:
                descriptions = sorted(set().union(*(edges[(a, b)] for a, b in zip(path, path[1:]))))
                raise UnsupportedSemantics("Unsupported calculation generation dependency cycle: " +
                    " -> ".join(map(str, path)) + "; rules/axioms: " + ", ".join(descriptions))
            if node in seen:
                continue
            seen.add(node)
            pending.extend((n, path + [n]) for n in sorted(adjacency.get(node, ()), key=str))


def compile_calculation_rules(rules: Graph, model: Graph | None = None):
    for _, predicate, obj in rules:
        for term in (predicate, obj):
            if isinstance(term, URIRef) and str(term).startswith(str(SWRL)) and term not in _SWRL_TERMS:
                raise UnsupportedSemantics(f"Unsupported SWRL vocabulary: {term}")
        if predicate == _RULE_ENABLED and obj != Literal(True):
            raise UnsupportedSemantics("Disabled or non-boolean SWRL activation flags are unsupported")
    compiled = _compile_rules(rules, parse_builtin=_parse_builtin, schedule=_schedule)
    schema = _rule_schema(rules)
    _check_property_values(rules + (model if model is not None else Graph()), compiled)
    _reject_generation_cycles(compiled, schema + (model if model is not None else Graph()))
    return compiled


def calculation_seed(rules: Graph):
    compiled = compile_calculation_rules(rules)
    seed, literals = _rule_schema(rules), set()
    for rule in compiled:
        for atom in (*rule.body, *rule.head):
            if atom.kind == SWRL.BuiltinAtom:
                literals.update(a for a in atom.arguments if isinstance(a, Literal))
                continue
            declaration = {SWRL.ClassAtom: OWL.Class,
                           SWRL.IndividualPropertyAtom: OWL.ObjectProperty,
                           SWRL.DatavaluedPropertyAtom: OWL.DatatypeProperty}[atom.kind]
            seed.add((atom.predicate, RDF.type, declaration))
            for argument in atom.arguments:
                if argument in rule.variables:
                    continue
                if isinstance(argument, Literal):
                    literals.add(argument)
                else:
                    seed.add((argument, RDF.type, OWL.NamedIndividual))
    return seed, frozenset(literals)


def _calculation_record(graph, rule, atom, arguments, output, status, premises,
                        previous, iteration, *, error=None):
    """Stable RDF evidence with ordered inputs, explicit output and error state."""
    spec = scalar.get_spec(atom.predicate)
    content = [str(rule.identifier), str(atom.predicate), str(spec.version), str(iteration), status,
               *(f"{i}:{_key(v)}" for i, v in arguments),
               "output:" + (_key(output) if output is not None else ""),
               *(_triple_key(t) for t in sorted(set(premises), key=_triple_key)),
               *(str(v) for v in previous), error or ""]
    identifier = _id("computation", "\n".join(content))
    for predicate, value in ((RDF.type, OT.Computation), (OT.rule, rule.identifier),
                             (OT.function, atom.predicate), (OT.functionVersion, Literal(spec.version)),
                             (OT.iteration, Literal(iteration)), (OT.status, Literal(status))):
        graph.add((identifier, predicate, value))
    for index, value in arguments:
        arg = _id("argument", str(identifier) + ":" + str(index))
        graph.add((identifier, OT.argument, arg))
        graph.add((arg, OT.position, Literal(index)))
        graph.add((arg, RDF.value, value))
    if output is not None:
        graph.add((identifier, OT.output, output))
    if spec.output_position is not None:
        graph.add((identifier, OT.outputPosition, Literal(spec.output_position)))
    if str(atom.predicate).endswith("divideRounded"):
        values = dict(arguments)
        if 3 in values:
            graph.add((identifier, OT.decimalPlaces, values[3]))
        if 4 in values:
            graph.add((identifier, OT.roundingMode, values[4]))
    if str(atom.predicate).endswith(("secondsBetween", "addSeconds")):
        graph.add((identifier, OT.timeConvention, Literal("UTC; milliseconds; seconds")))
    for premise in sorted(set(premises), key=_triple_key):
        graph.add((identifier, OT.premise, _statement(graph, premise)))
    for step in previous:
        graph.add((identifier, OT.priorComputation, step))
    if error:
        graph.add((identifier, OT.error, Literal(error)))
    return identifier


def apply_calculation_rules(rules: Graph, facts: Graph, candidates: Graph,
                            iteration: int = 1, budget: CalculationBudget | None = None,
                            model: Graph | None = None) -> CalculationResult:
    """One synchronous SWRL step, allowing new head literals but no new entities."""
    budget = budget if budget is not None else CalculationBudget()
    rules, facts, candidates = map(normalize_projection_literals, (rules, facts, candidates))
    compiled = compile_calculation_rules(rules, model)
    def consume_expansion(partial_trace):
        try:
            budget.match()
        except CalculationExecutionError as exc:
            raise CalculationExecutionError("Calculation match budget exhausted during sameAs expansion",
                                            trace=partial_trace) from exc

    view, original, trace, record, domain = _named_candidate_view(
        facts, candidates, iteration, on_expansion=consume_expansion)
    individuals, classes, objects, data, literals = domain
    computations, additions = Graph(), Graph()
    equal = partial(scalar.same_value, max_numeric_digits=budget.max_numeric_digits)
    pending, generated = {}, set()
    rule = atom = None
    current_arguments = ()
    try:
        for triple in view:
            if triple not in original:
                additions.add(triple)
        for rule in compiled:
            states = [({}, (), ())]
            for atom in rule.body:
                next_states = []
                for bindings, premises, steps in states:
                    if atom.kind != SWRL.BuiltinAtom:
                        for new_bindings, triple in _matches(view, atom, bindings, rule.variables,
                                                            same_term=equal, on_candidate=budget.match):
                            next_states.append((new_bindings, premises + (triple,), steps))
                        continue
                    spec = scalar.get_spec(atom.predicate)
                    arguments = tuple((i, bindings[a] if a in rule.variables else a)
                                      for i in spec.input_positions for a in (atom.arguments[i],))
                    current_arguments = tuple(v for _, v in arguments)
                    recorded_arguments = arguments
                    if spec.output_position is not None:
                        target = atom.arguments[spec.output_position]
                        existing = bindings.get(target) if target in rule.variables else target
                        if existing is not None:
                            recorded_arguments = ((spec.output_position, existing), *arguments)
                    try:
                        budget.evaluate()
                        output = scalar.evaluate(atom.predicate, current_arguments,
                                                 max_numeric_digits=budget.max_numeric_digits)
                        new_bindings = dict(bindings)
                        if spec.output_position is None:
                            matched = bool(output)
                            output = Literal(bool(output))
                        else:
                            target = atom.arguments[spec.output_position]
                            existing = bindings.get(target) if target in rule.variables else target
                            matched = existing is None or equal(existing, output)
                            if matched and target in rule.variables:
                                new_bindings[target] = output if existing is None else existing
                        step = _calculation_record(computations, rule, atom, recorded_arguments, output,
                                                   "matched" if matched else "unmatched",
                                                   premises, steps, iteration)
                    except ValueError as exc:
                        _calculation_record(computations, rule, atom, recorded_arguments, None, "failed",
                                            premises, steps, iteration, error=str(exc))
                        raise CalculationExecutionError(
                            f"Rule {rule.identifier}; function {atom.predicate}; inputs " +
                            ", ".join(_key(v) for _, v in arguments) + f": {exc}",
                            trace=trace, computations=computations, rule=rule.identifier,
                            predicate=atom.predicate, arguments=current_arguments) from exc
                    if matched:
                        next_states.append((new_bindings, premises, steps + (step,)))
                states = next_states
                if not states:
                    break
            for bindings, premises, steps in states:
                premises = tuple(sorted(set(premises), key=_triple_key))
                for atom in rule.head:
                    values = tuple(bindings[a] if a in rule.variables else a for a in atom.arguments)
                    triple = ((values[0], RDF.type, atom.predicate) if atom.kind == SWRL.ClassAtom
                              else (values[0], atom.predicate, values[1]))
                    s, p, o = triple
                    if (s not in individuals or (p == RDF.type and o not in classes) or
                        (p in objects and o not in individuals) or
                        (p in data and not isinstance(o, Literal)) or
                        p not in {RDF.type} | objects | data):
                        raise CalculationExecutionError("SWRL conclusion escapes the frozen named entity domain")
                    # Count only new data values of completed rule heads, never
                    # intermediate values or values from a failed body branch.
                    if p in data and o not in literals:
                        budget.generate(o)
                        generated.add(o)
                    # OWL may serialize an equivalent numeric/time spelling.
                    # Do not make that spelling a fresh fact every iteration.
                    exists = triple in view or (p in data and any(equal(o, v) for v in view.objects(s, p)))
                    if not exists:
                        pending.setdefault(triple, (rule.identifier, premises, steps))
        for triple in sorted(pending, key=_triple_key):
            identifier, premises, steps = pending[triple]
            view.add(triple)
            additions.add(triple)
            record(triple, OT.rule, identifier, premises)
            conclusion = _statement(trace, triple)
            for step in steps:
                trace.add((conclusion, OT.computation, step))
                computations.add((step, OT.conclusion, conclusion))
    except ValueError as exc:
        if isinstance(exc, CalculationExecutionError):
            exc.trace, exc.computations = trace, computations
            if exc.rule is None and rule is not None:
                exc.rule = rule.identifier
            raise
        raise CalculationExecutionError(str(exc), trace=trace, computations=computations,
                                        rule=rule.identifier if rule else None,
                                        predicate=atom.predicate if atom else None,
                                        arguments=current_arguments) from exc
    return CalculationResult(view, additions, trace, int(bool(additions)), computations,
                             frozenset(generated))
