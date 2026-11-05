"""Restricted RDF expression evaluation for hermit-swrl-formula-v1.

Formula semantics live in RDF.  This module is a generic interpreter: it does
not contain semiconductor equations, evaluate Python source, invent individuals,
or turn absent conditions into true conditions.  All arithmetic uses the pure
Python decimal implementation, whose fingerprint is included in every run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
from pathlib import Path
import re
import sys
from types import MappingProxyType
import _pydecimal as dec

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

F = Namespace("https://w3id.org/ontology-tools/formula#")
VERSION = "1"
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_DIMENSION = re.compile(r"([a-z][a-z0-9_]*):([+-]?[0-9]+(?:/[1-9][0-9]*)?)\Z")
_NUMERIC_TYPES = frozenset(XSD[name] for name in (
    "decimal", "integer", "nonPositiveInteger",
    "negativeInteger", "long", "int", "short", "byte", "nonNegativeInteger",
    "unsignedLong", "unsignedInt", "unsignedShort", "unsignedByte", "positiveInteger"))
_INTEGER_BOUNDS = {
    XSD.nonPositiveInteger: (None, 0), XSD.negativeInteger: (None, -1),
    XSD.long: (-(2**63), 2**63 - 1), XSD.int: (-(2**31), 2**31 - 1),
    XSD.short: (-(2**15), 2**15 - 1), XSD.byte: (-128, 127),
    XSD.nonNegativeInteger: (0, None), XSD.unsignedLong: (0, 2**64 - 1),
    XSD.unsignedInt: (0, 2**32 - 1), XSD.unsignedShort: (0, 2**16 - 1),
    XSD.unsignedByte: (0, 255), XSD.positiveInteger: (1, None),
}


class FormulaError(ValueError):
    """An explicit data, domain, or resource failure; never a numeric result."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Unit:
    scale: str
    dimensions: tuple[tuple[str, Fraction], ...] = ()


def _dims(**values):
    return tuple(sorted((key, Fraction(value)) for key, value in values.items() if value))


def _unit_table():
    # Exact, documented definitions.  Unknown strings are never parsed or guessed.
    length, time = _dims(length=1), _dims(time=1)
    table = {
        "1": Unit("1"), "dimensionless": Unit("1"),
        "m": Unit("1", length), "cm": Unit("0.01", length),
        "mm": Unit("0.001", length), "um": Unit("0.000001", length),
        "µm": Unit("0.000001", length), "μm": Unit("0.000001", length),
        "nm": Unit("0.000000001", length),
        "s": Unit("1", time), "ms": Unit("0.001", time),
        "us": Unit("0.000001", time), "ns": Unit("0.000000001", time),
        "K": Unit("1", _dims(temperature=1)),
        "kg": Unit("1", _dims(mass=1)), "A": Unit("1", _dims(current=1)),
        "C": Unit("1", _dims(current=1, time=1)),
        "V": Unit("1", _dims(mass=1, length=2, time=-3, current=-1)),
        "mV": Unit("0.001", _dims(mass=1, length=2, time=-3, current=-1)),
        "W": Unit("1", _dims(mass=1, length=2, time=-3)),
        "J": Unit("1", _dims(mass=1, length=2, time=-2)),
        "eV": Unit("0.0000000000000000001602176634", _dims(mass=1, length=2, time=-2)),
        "Hz": Unit("1", _dims(time=-1)), "kHz": Unit("1000", _dims(time=-1)),
        "MHz": Unit("1000000", _dims(time=-1)),
        "ohm": Unit("1", _dims(mass=1, length=2, time=-3, current=-2)),
        "ohm*m": Unit("1", _dims(mass=1, length=3, time=-3, current=-2)),
        "ohm*cm": Unit("0.01", _dims(mass=1, length=3, time=-3, current=-2)),
        "F": Unit("1", _dims(mass=-1, length=-2, time=4, current=2)),
        "F/m": Unit("1", _dims(mass=-1, length=-3, time=4, current=2)),
        "F/cm": Unit("100", _dims(mass=-1, length=-3, time=4, current=2)),
        "J/K": Unit("1", _dims(mass=1, length=2, time=-2, temperature=-1)),
        "K/W": Unit("1", _dims(temperature=1, mass=-1, length=-2, time=3)),
        "V/m": Unit("1", _dims(mass=1, length=1, time=-3, current=-1)),
        "V/cm": Unit("100", _dims(mass=1, length=1, time=-3, current=-1)),
        "A/m2": Unit("1", _dims(current=1, length=-2)),
        "A/cm2": Unit("10000", _dims(current=1, length=-2)),
        "m2/s": Unit("1", _dims(length=2, time=-1)),
        "cm2/s": Unit("0.0001", _dims(length=2, time=-1)),
        "m2/(V*s)": Unit("1", _dims(mass=-1, time=2, current=1)),
        "cm2/(V*s)": Unit("0.0001", _dims(mass=-1, time=2, current=1)),
        "F/m^2": Unit("1", _dims(mass=-1, length=-4, time=4, current=2)),
        "C/m^2": Unit("1", _dims(current=1, time=1, length=-2)),
        "W/m^2": Unit("1", _dims(mass=1, time=-3)),
        "V/s": Unit("1", _dims(mass=1, length=2, time=-4, current=-1)),
    }
    for spelling, exponent, scale in (
        ("m2", 2, "1"), ("cm2", 2, "0.0001"),
        ("m3", 3, "1"), ("cm3", 3, "0.000001"),
        ("m-3", -3, "1"), ("cm-3", -3, "1000000"),
        ("1/m3", -3, "1"), ("1/cm3", -3, "1000000"),
    ):
        table[spelling] = Unit(scale, _dims(length=exponent))
    for alias, canonical in {
        "m^2": "m2", "cm^2": "cm2", "m^3": "m3", "cm^3": "cm3",
        "m^-3": "m-3", "cm^-3": "cm-3", "m^2/s": "m2/s", "cm^2/s": "cm2/s",
        "m^2/(V*s)": "m2/(V*s)", "cm^2/(V*s)": "cm2/(V*s)",
        "A/m^2": "A/m2", "A/cm^2": "A/cm2",
    }.items():
        table[alias] = table[canonical]
    return table


BUILTIN_UNITS = MappingProxyType(_unit_table())


@dataclass(frozen=True)
class Parameter:
    iri: URIRef
    key: str
    symbol: str
    unit: str
    bounds: tuple[tuple[str, str], ...] = ()
    relations: tuple[tuple[str, URIRef], ...] = ()


@dataclass(frozen=True)
class Expression:
    kind: str
    value: object = None
    arguments: tuple["Expression", ...] = ()
    unit: str = "1"


@dataclass(frozen=True)
class Formula:
    iri: URIRef
    expression: Expression
    parameters: tuple[Parameter, ...]
    output_symbol: str
    output_unit: str
    latex: str
    conditions: frozenset[URIRef]


@dataclass(frozen=True)
class Catalog:
    formulas: object
    units: object
    issues: tuple[dict, ...] = ()
    inactive: tuple[str, ...] = ()


@dataclass
class EvaluationResult:
    facts: Graph = field(default_factory=Graph)
    trace: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    generated_literals: set[Literal] = field(default_factory=set)
    metadata: dict = field(default_factory=dict)


def scientific_metadata():
    return {
        "version": VERSION, "implementation": "python._pydecimal",
        "python": sys.version.split()[0],
        "implementation_sha256": hashlib.sha256(Path(dec.__file__).read_bytes()).hexdigest(),
        "rounding": "HALF_EVEN",
        "unit_contract": "explicit-dimensions-and-exact-SI-scales-v1",
        "numeric_input_contract": "xsd:decimal-and-integer-subtypes-v1",
        "numeric_value_policy": "exact-integer-decimal-canonical-decimal-v1",
    }


def _one(graph, subject, predicate, *, optional=False):
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        if optional and not values:
            return None
        raise FormulaError("cardinality", f"{subject} {predicate} requires exactly one value")
    return values[0]


def _string(term, label):
    if not isinstance(term, Literal) or term.language or term.datatype not in (None, XSD.string):
        raise FormulaError("invalid-string", f"{label} requires a plain/xsd:string literal")
    return str(term)


def _boolean(term, label):
    if not isinstance(term, Literal) or term.datatype != XSD.boolean or str(term) not in ("true", "false", "1", "0"):
        raise FormulaError("invalid-boolean", f"{label} requires an xsd:boolean")
    return str(term) in ("true", "1")


def _number(term, max_digits):
    if not isinstance(term, Literal) or term.datatype not in _NUMERIC_TYPES or not _NUMBER.fullmatch(str(term)):
        raise FormulaError("invalid-number", "Expected a finite typed RDF numeric literal")
    text = str(term)
    if len(text) > max_digits * 3 + 32:
        raise FormulaError("numeric-budget", "Numeric literal exceeds its lexical budget")
    try:
        value = dec.Decimal(text)
    except dec.DecimalException as exc:
        raise FormulaError("invalid-number", str(exc)) from exc
    _check_size(value, max_digits)
    if term.datatype != XSD.decimal:
        if not re.fullmatch(r"[+-]?[0-9]+", text):
            raise FormulaError("invalid-number", "Integer datatype requires an integer lexical form")
        lower, upper = _INTEGER_BOUNDS.get(term.datatype, (None, None))
        if (lower is not None and value < lower) or (upper is not None and value > upper):
            raise FormulaError("invalid-number", "Value violates its integer subtype bounds")
    if term.datatype == XSD.decimal and ("e" in text.lower()):
        raise FormulaError("invalid-number", "xsd:decimal lexical form cannot use an exponent")
    return value


def _check_size(value, max_digits):
    if not value.is_finite():
        raise FormulaError("non-finite", "Numeric result must be finite")
    tup = value.as_tuple()
    if len(tup.digits) > max_digits or abs(tup.exponent) > max_digits or abs(value.adjusted()) > max_digits:
        raise FormulaError("numeric-budget", "Numeric magnitude or precision exceeds max_numeric_digits")


def _decimal_text(value):
    if value.is_zero():
        return "0.0"
    value = format(value, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value if "." in value else value + ".0"


def normalize_numeric_facts(graph, *, max_numeric_digits=1000):
    """Canonicalize exact numeric values only on formula-owned numeric fields.

    Preserve malformed/unsupported terms for explicit rejection, never repair
    their lexical form. The formula profile calls this on working graphs only;
    its original source and input snapshots remain unchanged.
    """
    normalized = Graph()
    for subject, predicate, value in graph:
        if predicate in {F.value, F.result}:
            try:
                number = _number(value, max_numeric_digits)
            except FormulaError:
                pass
            else:
                value = Literal(_decimal_text(number), datatype=XSD.decimal, normalize=False)
        normalized.add((subject, predicate, value))
    return normalized


def _numeric_one(graph, subject, predicate, *, max_numeric_digits, optional=False):
    terms = set(graph.objects(subject, predicate))
    if not terms:
        if optional:
            return None
        raise FormulaError("cardinality", f"{subject} {predicate} requires exactly one numeric value")
    numbers = {_number(term, max_numeric_digits) for term in terms}
    if len(numbers) != 1:
        raise FormulaError("cardinality", f"{subject} {predicate} has conflicting numeric values")
    return Literal(_decimal_text(next(iter(numbers))), datatype=XSD.decimal, normalize=False)


def _list(graph, head, limit=10000):
    result, seen = [], set()
    while head != RDF.nil:
        if head in seen:
            raise FormulaError("list-cycle", "RDF list is cyclic")
        if len(result) >= limit:
            raise FormulaError("structure-budget", "RDF list exceeds structural budget")
        seen.add(head)
        result.append(_one(graph, head, RDF.first))
        head = _one(graph, head, RDF.rest)
    return result


def _dimensions(text):
    if not text or text == "1":
        return ()
    dimensions = {}
    for item in text.split(";"):
        match = _DIMENSION.fullmatch(item.strip())
        if not match or match[1] in dimensions:
            raise FormulaError("invalid-unit", f"Invalid or duplicate dimension: {item}")
        dimensions[match[1]] = Fraction(match[2])
    return tuple(sorted((key, value) for key, value in dimensions.items() if value))


def _read_units(graph):
    units = dict(BUILTIN_UNITS)
    for node in sorted(set(graph.subjects(RDF.type, F.Unit)), key=str):
        key = _string(_one(graph, node, F.key), "Unit key")
        scale = _number(_one(graph, node, F.scale), 1000)
        if scale <= 0:
            raise FormulaError("invalid-unit", "Unit scale must be positive")
        unit = Unit(_decimal_text(scale), _dimensions(_string(_one(graph, node, F.dimensions), "Unit dimensions")))
        if key in units and (dec.Decimal(units[key].scale) != scale or units[key].dimensions != unit.dimensions):
            raise FormulaError("unit-redefinition", f"Conflicting definition for unit {key}")
        units[key] = unit
    return units


def _compile_formula(graph, iri, units):
    if not isinstance(iri, URIRef):
        raise FormulaError("unnamed-formula", "Enabled formulas require a stable named IRI")
    if not _boolean(_one(graph, iri, F.verified), "verified"):
        raise FormulaError("unverified-formula", "Only verified formulas can be executable")
    parameters, keys = [], set()
    for node in _list(graph, _one(graph, iri, F.parameters)):
        if not isinstance(node, URIRef) or (node, RDF.type, F.Parameter) not in graph:
            raise FormulaError("invalid-parameter", "Parameters must be named, typed f:Parameter resources")
        key = _string(_one(graph, node, F.key), "Parameter key")
        symbol = _string(_one(graph, node, F.symbol), "Parameter symbol")
        unit = _string(_one(graph, node, F.unit), "Parameter unit")
        if not key or key in keys or any(p.iri == node for p in parameters):
            raise FormulaError("duplicate-parameter", "Parameter identities and keys must be unique")
        if unit not in units:
            raise FormulaError("unknown-unit", f"Undeclared parameter unit: {unit}")
        bounds = []
        for bound in ("minInclusive", "minExclusive", "maxInclusive", "maxExclusive"):
            value = _one(graph, node, F[bound], optional=True)
            if value is not None:
                bounds.append((bound, _decimal_text(_number(value, 1000))))
        relations = tuple((name, target) for name in (
            "lessThanParameter", "lessThanOrEqualParameter", "greaterThanParameter",
            "greaterThanOrEqualParameter")
            for target in sorted(set(graph.objects(node, F[name])), key=str))
        parameters.append(Parameter(node, key, symbol, unit, tuple(bounds), relations))
        keys.add(key)
    parameter_ids = {p.iri for p in parameters}
    parameter_map = {p.iri: p for p in parameters}
    for parameter in parameters:
        for relation, target in parameter.relations:
            if target not in parameter_ids:
                raise FormulaError("unknown-parameter", f"{relation} target must be a parameter of the same formula")
            if units[parameter.unit].dimensions != units[parameter_map[target].unit].dimensions:
                raise FormulaError("dimension-mismatch", f"{relation} requires dimensionally compatible parameters")
    used, active, count = set(), set(), [0]

    def expression(node, depth=0):
        count[0] += 1
        if depth > 128 or count[0] > 10000:
            raise FormulaError("structure-budget", "Expression exceeds depth/node budget")
        if node in active:
            raise FormulaError("expression-cycle", "Expression graph is cyclic")
        active.add(node)
        kinds = set(graph.objects(node, RDF.type)) & {F.Constant, F.ParameterRef, F.Operation}
        if len(kinds) != 1:
            raise FormulaError("invalid-expression", "Expression requires exactly one supported node type")
        kind = next(iter(kinds))
        if kind == F.Constant:
            value = _decimal_text(_number(_one(graph, node, F.value), 1000))
            unit_term = _one(graph, node, F.unit, optional=True)
            unit = "1" if unit_term is None else _string(unit_term, "Constant unit")
            if unit not in units:
                raise FormulaError("unknown-unit", f"Undeclared constant unit: {unit}")
            result = Expression("constant", value, unit=unit)
        elif kind == F.ParameterRef:
            parameter = _one(graph, node, F.parameter)
            if parameter not in parameter_ids:
                raise FormulaError("unknown-parameter", "ParameterRef must reference a declared formula parameter")
            used.add(parameter)
            result = Expression("parameter", parameter)
        else:
            operator = _one(graph, node, F.operator)
            operators = {F[name]: name for name in ("Add", "Subtract", "Multiply", "Divide", "Negate", "Sqrt", "Exp", "Ln", "Pow")}
            if operator not in operators:
                raise FormulaError("unknown-operator", f"Unsupported operation: {operator}")
            arguments = _list(graph, _one(graph, node, F.arguments))
            name = operators[operator]
            expected = 1 if name in {"Negate", "Sqrt", "Exp", "Ln"} else 2
            if len(arguments) != expected:
                raise FormulaError("arity", f"{name} requires exactly {expected} arguments")
            result = Expression(name, arguments=tuple(expression(arg, depth + 1) for arg in arguments))
        active.remove(node)
        return result

    root = expression(_one(graph, iri, F.expression))
    if used != parameter_ids:
        raise FormulaError("unused-parameter", "Every declared input must occur in the executable expression")
    conditions = frozenset(graph.objects(iri, F.requiredCondition))
    if any(not isinstance(condition, URIRef) for condition in conditions):
        raise FormulaError("invalid-condition", "Required conditions must be named IRIs")
    unconditional = _one(graph, iri, F.unconditional, optional=True)
    unconditional = False if unconditional is None else _boolean(unconditional, "unconditional")
    if bool(conditions) == unconditional:
        raise FormulaError("missing-applicability", "Declare requiredCondition or explicit unconditional=true")
    output_unit = _string(_one(graph, iri, F.outputUnit), "Output unit")
    if output_unit not in units:
        raise FormulaError("unknown-unit", f"Undeclared output unit: {output_unit}")
    return Formula(iri, root, tuple(parameters),
        _string(_one(graph, iri, F.outputSymbol), "Output symbol"), output_unit,
        _string(_one(graph, iri, F.latex), "LaTeX"), conditions)


def compile_catalog(graph):
    """Compile only enabled verified entries; retain other candidates for search.

    An invalid enabled entry appears in ``issues`` and cannot execute.  Other
    valid entries remain usable.  Invalid global unit declarations raise because
    they could otherwise change the meaning of every formula in the catalog.
    """
    units = _read_units(graph)
    formulas, issues, inactive = {}, [], []
    for iri in sorted(set(graph.subjects(RDF.type, F.Formula)), key=str):
        try:
            enabled = _one(graph, iri, F.enabled, optional=True)
            if enabled is None or not _boolean(enabled, "enabled"):
                inactive.append(str(iri))
                continue
            formulas[iri] = _compile_formula(graph, iri, units)
        except FormulaError as exc:
            issues.append({"formula": str(iri), "code": exc.code, "message": str(exc)})
    return Catalog(MappingProxyType(formulas), MappingProxyType(units), tuple(issues), tuple(inactive))


def render_expression(catalog, formula):
    """Generate canonical LaTeX from the executable AST for independent review."""
    spec = catalog.formulas[URIRef(formula)]
    parameters = {p.iri: p for p in spec.parameters}

    def render(node):
        if node.kind == "constant":
            return node.value
        if node.kind == "parameter":
            return parameters[node.value].symbol
        args = [render(arg) for arg in node.arguments]
        if node.kind == "Sqrt":
            return r"\sqrt{" + args[0] + "}"
        if node.kind in {"Exp", "Ln"}:
            return (r"\exp" if node.kind == "Exp" else r"\ln") + r"\left(" + args[0] + r"\right)"
        if node.kind == "Negate":
            return r"-\left(" + args[0] + r"\right)"
        if node.kind == "Divide":
            return r"\frac{" + args[0] + "}{" + args[1] + "}"
        if node.kind == "Pow":
            return r"\left(" + args[0] + r"\right)^{" + args[1] + "}"
        separator = {"Add": "+", "Subtract": "-", "Multiply": r"\cdot "}[node.kind]
        return r"\left(" + separator.join(args) + r"\right)"

    return spec.output_symbol + "=" + render(spec.expression)


def render_formula(catalog, formula):
    """Return the preserved source LaTeX (never reconstructed by the agent)."""
    return catalog.formulas[URIRef(formula)].latex


def _combine(left, right, multiplier=1):
    values = dict(left)
    for key, value in right:
        values[key] = values.get(key, Fraction(0)) + value * multiplier
    return tuple(sorted((key, value) for key, value in values.items() if value))


def _dimension_text(dimensions):
    return ";".join(f"{key}:{value}" for key, value in dimensions) or "1"


def evaluate_catalog(catalog, facts, *, precision=50, max_evaluations=100000,
                     max_numeric_digits=1000, iteration=1):
    """Evaluate named pre-existing requests and return only complete result deltas.

    Missing conditions/inputs and invalid requests are diagnostics, never result
    triples. Dependency edges are checked across the entire request graph before
    numerical evaluation. Existing results must match recomputation exactly.
    """
    for name, value, minimum in (("precision", precision, 2), ("max_evaluations", max_evaluations, 1),
                                  ("max_numeric_digits", max_numeric_digits, 2), ("iteration", iteration, 1)):
        if type(value) is not int or value < minimum:
            raise FormulaError("invalid-budget", f"{name} must be an integer >= {minimum}")
    if precision > max_numeric_digits:
        raise FormulaError("invalid-budget", "precision cannot exceed max_numeric_digits")
    output = EvaluationResult(metadata={**scientific_metadata(), "precision": precision,
        "max_numeric_digits": max_numeric_digits, "max_evaluations": max_evaluations,
        "iteration": iteration})
    output.facts.bind("f", F)
    evaluations = sorted(set(facts.subjects(RDF.type, F.Evaluation)), key=str)
    if len(evaluations) > max_evaluations:
        output.diagnostics.append({"code": "evaluation-budget", "message": "Number of requests exceeds max_evaluations"})
        return output
    evaluation_set, dependencies, invalid = set(evaluations), {}, {}
    for request in evaluations:
        try:
            if not isinstance(request, URIRef):
                raise FormulaError("unnamed-evaluation", "Evaluation requires a pre-existing named IRI")
            targets = set()
            for binding in facts.objects(request, F.binding):
                target = _one(facts, binding, F.fromEvaluation, optional=True)
                if target is not None:
                    if target not in evaluation_set:
                        raise FormulaError("missing-dependency", "Dependency must be a typed pre-existing Evaluation")
                    targets.add(target)
            dependencies[request] = sorted(targets, key=str)
        except FormulaError as exc:
            invalid[request] = exc
    # Iterative DFS avoids a Python recursion failure for malicious long chains.
    colors, cycles = {}, set()
    for start in evaluations:
        if colors.get(start):
            continue
        stack, path, offsets = [(start, False)], [], {}
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colors[node] = 2
                offsets.pop(node, None)
                path.pop()
                continue
            if colors.get(node) == 1:
                cycles.update(path[offsets[node]:])
                continue
            if colors.get(node) == 2:
                continue
            colors[node], offsets[node] = 1, len(path)
            path.append(node)
            stack.append((node, True))
            for target in reversed(dependencies.get(node, [])):
                stack.append((target, False))
    for request in cycles:
        invalid[request] = FormulaError("dependency-cycle", "Evaluation dependency graph is cyclic")
    completed, failed, visiting = {}, set(), set()
    evaluations_used = [0]

    def charge():
        evaluations_used[0] += 1
        if evaluations_used[0] > max_evaluations:
            raise FormulaError("evaluation-budget", "Binding/operation count exceeds max_evaluations")

    def calculate(request, depth=0):
        if request in completed:
            return completed[request]
        if request in failed:
            raise FormulaError("dependency-failed", "Upstream evaluation did not produce a complete result")
        if depth > 128:
            raise FormulaError("structure-budget", "Dependency chain exceeds depth budget")
        if request in visiting:
            raise FormulaError("dependency-cycle", "Evaluation dependency graph is cyclic")
        visiting.add(request)
        event = {"evaluation": str(request), "iteration": iteration, "precision": precision,
                 "rounding": "HALF_EVEN", "operations": [], "bindings": [], "constants": [],
                 "parameter_relations": []}
        try:
            if request in invalid:
                raise invalid[request]
            formula_iri = _one(facts, request, F.formula)
            if formula_iri not in catalog.formulas:
                raise FormulaError("unavailable-formula", "Formula is disabled, invalid, or absent from this catalog")
            spec = catalog.formulas[formula_iri]
            context = _one(facts, request, F.context)
            if not isinstance(context, URIRef):
                raise FormulaError("invalid-context", "Evaluation context requires a named IRI")
            missing_conditions = spec.conditions - set(facts.objects(request, F.satisfiedCondition))
            if missing_conditions:
                raise FormulaError("missing-condition", "Unconfirmed conditions: " + ", ".join(sorted(map(str, missing_conditions))))
            event.update(formula=str(formula_iri), context=str(context), latex=spec.latex,
                         rendered_latex=render_expression(catalog, formula_iri))
            parameter_map, bound = {p.iri: p for p in spec.parameters}, {}
            for binding in sorted(set(facts.objects(request, F.binding)), key=str):
                charge()
                if (binding, RDF.type, F.Binding) not in facts:
                    raise FormulaError("invalid-binding", "Binding must have explicit f:Binding type")
                parameter = _one(facts, binding, F.parameter)
                if parameter not in parameter_map:
                    raise FormulaError("unknown-parameter", "Binding references a parameter outside this formula")
                if parameter in bound:
                    raise FormulaError("multiple-values", "Multiple bindings for one parameter require user resolution")
                if _one(facts, binding, F.context) != context:
                    raise FormulaError("context-mismatch", "Binding and evaluation contexts differ")
                target = _one(facts, binding, F.fromEvaluation, optional=True)
                value_term = _numeric_one(facts, binding, F.value,
                    max_numeric_digits=max_numeric_digits, optional=True)
                unit_term = _one(facts, binding, F.unit, optional=True)
                if target is not None:
                    if value_term is not None or unit_term is not None:
                        raise FormulaError("ambiguous-binding", "A dependency binding cannot also supply direct value/unit")
                    if _one(facts, target, F.context) != context:
                        raise FormulaError("context-mismatch", "Dependency evaluation contexts differ")
                    value, unit_name = calculate(target, depth + 1)
                else:
                    if value_term is None or unit_term is None:
                        raise FormulaError("missing-input", "Direct binding requires value and unit")
                    value, unit_name = _number(value_term, max_numeric_digits), _string(unit_term, "Binding unit")
                if unit_name not in catalog.units:
                    raise FormulaError("unknown-unit", f"Undeclared input unit: {unit_name}")
                expected = catalog.units[parameter_map[parameter].unit]
                unit = catalog.units[unit_name]
                if expected.dimensions != unit.dimensions:
                    raise FormulaError("unit-mismatch", "Binding unit is incompatible with declared parameter unit")
                normalized = value * dec.Decimal(unit.scale) / dec.Decimal(expected.scale)
                for bound_name, bound_value in parameter_map[parameter].bounds:
                    threshold = dec.Decimal(bound_value)
                    valid = {"minInclusive": normalized >= threshold, "minExclusive": normalized > threshold,
                             "maxInclusive": normalized <= threshold, "maxExclusive": normalized < threshold}[bound_name]
                    if not valid:
                        raise FormulaError("parameter-domain", f"{parameter_map[parameter].key} violates {bound_name}")
                si_value = value * dec.Decimal(unit.scale)
                _check_size(si_value, max_numeric_digits)
                bound[parameter] = (si_value, unit.dimensions)
                event["bindings"].append({"parameter": str(parameter), "key": parameter_map[parameter].key,
                    "input": _decimal_text(value), "input_unit": unit_name,
                    "declared_value": _decimal_text(normalized), "declared_unit": parameter_map[parameter].unit,
                    "si_value": _decimal_text(si_value), "dimensions": _dimension_text(unit.dimensions),
                    "source_numeric_literals": [{"lexical": str(term), "datatype": str(term.datatype)}
                        for term in sorted(set(facts.objects(binding, F.value)), key=lambda term: (str(term.datatype), str(term)))],
                    **({"from_evaluation": str(target)} if target is not None else {})})
            missing_parameters = set(parameter_map) - set(bound)
            if missing_parameters:
                raise FormulaError("missing-input", "Missing parameters: " + ", ".join(sorted(map(str, missing_parameters))))
            for parameter in spec.parameters:
                for relation, target in parameter.relations:
                    left, right = bound[parameter.iri][0], bound[target][0]
                    valid = {"lessThanParameter": left < right,
                             "lessThanOrEqualParameter": left <= right,
                             "greaterThanParameter": left > right,
                             "greaterThanOrEqualParameter": left >= right}[relation]
                    event["parameter_relations"].append({"parameter": str(parameter.iri),
                        "relation": str(F[relation]), "target_parameter": str(target),
                        "left_si": _decimal_text(left), "right_si": _decimal_text(right),
                        "satisfied": valid})
                    if not valid:
                        raise FormulaError("parameter-domain", f"{parameter.key} violates {relation} {parameter_map[target].key}")

            def run(node, path="root"):
                if node.kind == "parameter":
                    return bound[node.value]
                if node.kind == "constant":
                    unit = catalog.units[node.unit]
                    result = dec.Decimal(node.value) * dec.Decimal(unit.scale)
                    _check_size(result, max_numeric_digits)
                    event["constants"].append({"path": path, "value": node.value,
                        "unit": node.unit, "si_value": _decimal_text(result),
                        "dimensions": _dimension_text(unit.dimensions)})
                    return result, unit.dimensions
                args = [run(arg, f"{path}.{index}") for index, arg in enumerate(node.arguments)]
                charge()
                values, dimensions = [arg[0] for arg in args], [arg[1] for arg in args]
                a, da = values[0], dimensions[0]
                name = node.kind
                numeric_context = dec.getcontext()
                prior_flags = numeric_context.flags.copy()
                numeric_context.clear_flags()
                if name in {"Add", "Subtract"}:
                    if da != dimensions[1]:
                        raise FormulaError("dimension-mismatch", "Addition/subtraction require identical dimensions")
                    value, dimension = (a + values[1] if name == "Add" else a - values[1]), da
                elif name == "Multiply":
                    value, dimension = a * values[1], _combine(da, dimensions[1])
                elif name == "Divide":
                    if values[1].is_zero():
                        raise FormulaError("division-by-zero", "Division by zero")
                    value, dimension = a / values[1], _combine(da, dimensions[1], -1)
                elif name == "Negate":
                    value, dimension = -a, da
                elif name == "Sqrt":
                    if a < 0:
                        raise FormulaError("invalid-domain", "Square root requires a nonnegative argument")
                    value, dimension = a.sqrt(), tuple((key, power / 2) for key, power in da)
                elif name in {"Exp", "Ln"}:
                    if da:
                        raise FormulaError("dimension-mismatch", "Exp/Ln require dimensionless arguments")
                    if name == "Ln" and a <= 0:
                        raise FormulaError("invalid-domain", "Natural logarithm requires a positive argument")
                    if name == "Exp" and abs(a) > max_numeric_digits * 3:
                        raise FormulaError("numeric-budget", "Exponential argument exceeds magnitude budget")
                    value, dimension = (a.exp() if name == "Exp" else a.ln()), ()
                elif name == "Pow":
                    exponent = values[1]
                    if dimensions[1]:
                        raise FormulaError("dimension-mismatch", "Power exponent must be dimensionless")
                    if (a.is_zero() and exponent <= 0) or (a < 0 and exponent != exponent.to_integral_value()):
                        raise FormulaError("invalid-domain", "Power is outside the supported real domain")
                    if abs(exponent) > max_numeric_digits * 4:
                        raise FormulaError("numeric-budget", "Power exponent exceeds resource budget")
                    rational = Fraction(str(exponent))
                    if da and rational.denominator > 1000000:
                        raise FormulaError("dimension-budget", "Dimensional exponent requires a manageable exact rational")
                    value = a ** exponent
                    dimension = tuple((key, power * rational) for key, power in da if power * rational)
                else:
                    raise FormulaError("unknown-operator", "Unsupported compiled operation")
                _check_size(value, max_numeric_digits)
                operation_inexact = bool(numeric_context.flags[dec.Inexact])
                operation_rounded = bool(numeric_context.flags[dec.Rounded])
                for signal, prior in prior_flags.items():
                    numeric_context.flags[signal] = prior or numeric_context.flags[signal]
                event["operations"].append({"path": path, "operator": str(F[name]),
                    "inputs": [_decimal_text(item) for item in values],
                    "input_dimensions": [_dimension_text(item) for item in dimensions],
                    "output": _decimal_text(value), "output_dimensions": _dimension_text(dimension),
                    "precision": precision, "rounding": "HALF_EVEN",
                    "inexact": operation_inexact, "rounded": operation_rounded})
                return value, dimension

            value, dimension = run(spec.expression)
            output_unit = catalog.units[spec.output_unit]
            if dimension != output_unit.dimensions:
                raise FormulaError("dimension-mismatch", "Expression dimension does not match declared output unit")
            value = +(value / dec.Decimal(output_unit.scale))
            _check_size(value, max_numeric_digits)
            literal = Literal(_decimal_text(value), datatype=XSD.decimal, normalize=False)
            triples = ((request, F.result, literal), (request, F.resultUnit, Literal(spec.output_unit)),
                       (request, F.calculationStatus, F.Computed))
            # Existing output is trusted only after independent recomputation.
            for _, predicate, expected in triples:
                existing = set(facts.objects(request, predicate))
                if existing:
                    if predicate == F.result:
                        matches = all(_number(previous, max_numeric_digits) == value for previous in existing)
                    elif len(existing) != 1:
                        raise FormulaError("output-conflict", "Existing output has multiple values")
                    elif predicate == F.resultUnit:
                        matches = _string(next(iter(existing)), "Result unit") == spec.output_unit
                    else:
                        matches = next(iter(existing)) == expected
                    if not matches:
                        raise FormulaError("output-conflict", "Existing result/status differs from recomputation")
            for triple in triples:
                if not any(facts.objects(request, triple[1])):
                    output.facts.add(triple)
                    if isinstance(triple[2], Literal):
                        output.generated_literals.add(triple[2])
            event.update(status="computed", result=str(literal), result_unit=spec.output_unit,
                         inexact=bool(dec.getcontext().flags[dec.Inexact]),
                         rounded=bool(dec.getcontext().flags[dec.Rounded]))
            output.trace.append(event)
            completed[request] = (value, spec.output_unit)
            return completed[request]
        except FormulaError as exc:
            failed.add(request)
            event.update(status="not-computed", code=exc.code, message=str(exc))
            output.trace.append(event)
            output.diagnostics.append({"evaluation": str(request), "code": exc.code, "message": str(exc)})
            raise
        except dec.DecimalException as exc:
            error = FormulaError("numeric-error", f"{type(exc).__name__}: {exc}")
            failed.add(request)
            event.update(status="not-computed", code=error.code, message=str(error))
            output.trace.append(event)
            output.diagnostics.append({"evaluation": str(request), "code": error.code, "message": str(error)})
            raise error from exc
        finally:
            visiting.discard(request)

    context = dec.Context(prec=precision, rounding=dec.ROUND_HALF_EVEN,
                          Emin=-max_numeric_digits, Emax=max_numeric_digits,
                          traps=[dec.InvalidOperation, dec.DivisionByZero, dec.Overflow, dec.Underflow])
    with dec.localcontext(context) as numeric_context:
        for request in evaluations:
            if request in completed or request in failed:
                continue
            numeric_context.clear_flags()
            try:
                calculate(request)
            except FormulaError:
                pass
    return output
