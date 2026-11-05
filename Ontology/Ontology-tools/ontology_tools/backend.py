"""Deterministic, deliberately limited local-rules-v1 materialisation.

This is a finite named-term rule engine, not an OWL DL reasoner or an OWL
consistency checker. No imports, equality replacement, existential creation,
negation, priorities, arithmetic, or external calls are implemented. See PROFILE.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import re
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import OWL, RDF, RDFS, XSD
from rdflib.term import Identifier

PROFILE = "local-rules-v1"
OT = Namespace("https://w3id.org/ontology-tools#")
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
SWRLB = Namespace("http://www.w3.org/2003/11/swrlb#")
Triple = tuple[Identifier, Identifier, Identifier]


class UnsupportedSemantics(ValueError):
    """Input uses a construct or value outside the declared execution profile."""


class InferenceLimitError(ValueError):
    """The configured iteration budget ended before a verified fixed point."""


@dataclass(frozen=True)
class InferenceResult:
    closure: Graph
    inferred: Graph
    trace: Graph
    iterations: int


@dataclass(frozen=True)
class _Atom:
    kind: Identifier
    predicate: Identifier
    arguments: tuple[Identifier, ...]
    node: Identifier


@dataclass(frozen=True)
class _Rule:
    identifier: URIRef
    body: tuple[_Atom, ...]
    head: tuple[_Atom, ...]
    variables: frozenset[Identifier]


_ATOMS = {SWRL.ClassAtom, SWRL.IndividualPropertyAtom,
          SWRL.DatavaluedPropertyAtom, SWRL.BuiltinAtom}
_SWRL_TERMS = _ATOMS | {SWRL.Imp, SWRL.Variable, SWRL.body, SWRL.head,
    SWRL.classPredicate, SWRL.propertyPredicate, SWRL.argument1, SWRL.argument2,
    SWRL.builtin, SWRL.arguments}
_COMPARISONS = {SWRLB[name] for name in (
    "equal", "notEqual", "lessThan", "lessThanOrEqual", "greaterThan",
    "greaterThanOrEqual")}
_OWL_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
    OWL.AnnotationProperty, OWL.Ontology, OWL.NamedIndividual,
    OWL.TransitiveProperty, OWL.SymmetricProperty}
_OWL_PREDICATES = {OWL.inverseOf, OWL.versionIRI, OWL.versionInfo, OWL.deprecated}
_RDFS_PREDICATES = {RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range,
    RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy}
_RDF_PREDICATES = {RDF.type, RDF.subject, RDF.predicate, RDF.object, RDF.first,
                   RDF.rest, RDF.value}
_SCHEMA_PREDICATES = {RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain,
                      RDFS.range, OWL.inverseOf}
_DECLARATIONS = _OWL_TYPES | {RDFS.Class, RDFS.Datatype, RDF.Property}
_RULE_ENABLED = URIRef("http://swrl.stanford.edu/ontologies/3.3/swrla.owl#isRuleEnabled")
_RESERVED = tuple(map(str, (RDF, RDFS, OWL, SWRL, SWRLB, XSD)))
_INTEGER_TYPES = {XSD[name] for name in (
    "integer", "nonPositiveInteger", "negativeInteger", "long", "int", "short",
    "byte", "nonNegativeInteger", "unsignedLong", "unsignedInt", "unsignedShort",
    "unsignedByte", "positiveInteger")}
_INTEGER_BOUNDS = {
    XSD.nonPositiveInteger: (None, 0), XSD.negativeInteger: (None, -1),
    XSD.long: (-(2**63), 2**63 - 1), XSD.int: (-(2**31), 2**31 - 1),
    XSD.short: (-(2**15), 2**15 - 1), XSD.byte: (-128, 127),
    XSD.nonNegativeInteger: (0, None), XSD.positiveInteger: (1, None),
    XSD.unsignedLong: (0, 2**64 - 1), XSD.unsignedInt: (0, 2**32 - 1),
    XSD.unsignedShort: (0, 2**16 - 1), XSD.unsignedByte: (0, 255),
}


def _key(term: Identifier) -> str:
    return term.n3()


def _triple_key(triple: Triple) -> str:
    return " ".join(_key(term) for term in triple) + " ."


def _id(kind: str, text: str) -> URIRef:
    return URIRef(str(OT) + kind + "-" + sha256(text.encode("utf-8")).hexdigest())


def _copy(graph: Graph) -> Graph:
    result = Graph()
    for prefix, namespace in graph.namespaces():
        result.bind(prefix, namespace)
    for triple in graph:
        result.add(triple)
    return result


def _canonical_scope(graph: Graph, scope: str) -> Graph:
    """Canonical, independently scoped blank nodes; never confound two files."""
    result = Graph()
    for prefix, namespace in graph.namespaces():
        result.bind(prefix, namespace)
    for triple in to_canonical_graph(graph):
        result.add(tuple(BNode(scope + "-" + str(t)) if isinstance(t, BNode)
                         else t for t in triple))
    return result


def _one(graph: Graph, subject: Identifier, predicate: Identifier) -> Identifier:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise UnsupportedSemantics(
            f"{subject.n3()} requires exactly one {predicate.n3()} (found {len(values)})")
    return values[0]


def _list(graph: Graph, root: Identifier) -> tuple[Identifier, ...]:
    values, visited = [], set()
    while root != RDF.nil:
        if root in visited or isinstance(root, Literal):
            raise UnsupportedSemantics("Malformed or cyclic RDF list in SWRL rule")
        visited.add(root)
        values.append(_one(graph, root, RDF.first))
        root = _one(graph, root, RDF.rest)
    return tuple(values)


def _value(literal: Identifier) -> tuple[str, object]:
    if not isinstance(literal, Literal):
        raise UnsupportedSemantics("SWRL comparison arguments must be literal values")
    if literal.language:
        raise UnsupportedSemantics("Language-tagged comparison values are not supported")
    if getattr(literal, "ill_typed", False):
        raise UnsupportedSemantics(f"Ill-typed literal: {literal.n3()}")
    datatype, value = literal.datatype, literal.toPython()
    if datatype in _INTEGER_TYPES:
        if type(value) is not int or not re.fullmatch(r"[+-]?[0-9]+", str(literal).strip()):
            raise UnsupportedSemantics(f"Invalid integer literal: {literal.n3()}")
        lower, upper = _INTEGER_BOUNDS.get(datatype, (None, None))
        if (lower is not None and value < lower) or (upper is not None and value > upper):
            raise UnsupportedSemantics(f"Out-of-range integer literal: {literal.n3()}")
        return "number", Decimal(value)
    if datatype == XSD.decimal:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise UnsupportedSemantics(f"Invalid finite decimal: {literal.n3()}")
        # Python Decimal accepts exponent notation although xsd:decimal does not.
        lexical = str(literal).strip()
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", lexical):
            raise UnsupportedSemantics(f"Invalid xsd:decimal lexical form: {literal.n3()}")
        return "number", value
    if datatype in (None, XSD.string):
        return "string", str(literal)
    if datatype == XSD.boolean:
        if type(value) is not bool or str(literal) not in {"true", "false", "1", "0"}:
            raise UnsupportedSemantics(f"Invalid boolean: {literal.n3()}")
        return "boolean", value
    raise UnsupportedSemantics(f"Unsupported comparison datatype: {datatype}")


def _same_term(left: Identifier, right: Identifier) -> bool:
    if left == right:
        return True
    if isinstance(left, Literal) and isinstance(right, Literal):
        try:
            return _value(left) == _value(right)
        except UnsupportedSemantics:
            return False
    return False


def _compare(operator: Identifier, arguments: tuple[Identifier, ...]) -> bool:
    left_type, left = _value(arguments[0])
    right_type, right = _value(arguments[1])
    if left_type != right_type:
        raise UnsupportedSemantics("Comparison values have incompatible datatypes")
    if operator == SWRLB.equal:
        return left == right
    if operator == SWRLB.notEqual:
        return left != right
    if left_type == "boolean":
        raise UnsupportedSemantics("Boolean values support only equal/notEqual")
    if operator == SWRLB.lessThan:
        return left < right
    if operator == SWRLB.lessThanOrEqual:
        return left <= right
    if operator == SWRLB.greaterThan:
        return left > right
    if operator == SWRLB.greaterThanOrEqual:
        return left >= right
    raise UnsupportedSemantics(f"Unsupported SWRL builtin {operator}")


def _parse_atom(graph: Graph, node: Identifier,
                variables: frozenset[Identifier], head: bool, parse_builtin=None) -> _Atom:
    kinds = set(graph.objects(node, RDF.type)) & _ATOMS
    if len(kinds) != 1:
        raise UnsupportedSemantics(f"SWRL atom {node.n3()} needs one supported atom type")
    kind = kinds.pop()
    if kind == SWRL.BuiltinAtom:
        if head:
            raise UnsupportedSemantics("Builtin atoms in rule heads are unsupported")
        predicate = _one(graph, node, SWRL.builtin)
        arguments = _list(graph, _one(graph, node, SWRL.arguments))
        if parse_builtin is not None:
            parse_builtin(predicate, arguments, variables)
        else:
            if predicate not in _COMPARISONS or len(arguments) != 2:
                raise UnsupportedSemantics("Only six binary SWRL comparison builtins are supported")
            for arg in arguments:
                if arg not in variables:
                    kind_of_value, _ = _value(arg)
                    if kind_of_value == "boolean" and predicate not in {SWRLB.equal, SWRLB.notEqual}:
                        raise UnsupportedSemantics("Boolean values support only equal/notEqual")
            if not any(arg in variables for arg in arguments):
                _compare(predicate, arguments)
    else:
        predicate = _one(graph, node, SWRL.classPredicate if kind == SWRL.ClassAtom
                         else SWRL.propertyPredicate)
        if (not isinstance(predicate, URIRef) or str(predicate).startswith(_RESERVED)
                or predicate in variables):
            raise UnsupportedSemantics("SWRL class/property predicates must be non-reserved named IRIs")
        arguments = (_one(graph, node, SWRL.argument1),)
        if kind != SWRL.ClassAtom:
            arguments += (_one(graph, node, SWRL.argument2),)
        if arguments[0] not in variables and not isinstance(arguments[0], URIRef):
            raise UnsupportedSemantics("SWRL individual constants must be named IRIs")
        if kind == SWRL.IndividualPropertyAtom:
            if arguments[1] not in variables and not isinstance(arguments[1], URIRef):
                raise UnsupportedSemantics("Object property atoms require named individual constants")
        if kind == SWRL.DatavaluedPropertyAtom:
            if arguments[1] not in variables and not isinstance(arguments[1], Literal):
                raise UnsupportedSemantics("Data property atoms require literal values")
    allowed = {RDF.type, SWRL.builtin, SWRL.arguments} if kind == SWRL.BuiltinAtom else {
        RDF.type, SWRL.classPredicate if kind == SWRL.ClassAtom else SWRL.propertyPredicate,
        SWRL.argument1}
    if kind in {SWRL.IndividualPropertyAtom, SWRL.DatavaluedPropertyAtom}:
        allowed.add(SWRL.argument2)
    for predicate2 in graph.predicates(node):
        if str(predicate2).startswith(str(SWRL)) and predicate2 not in allowed:
            raise UnsupportedSemantics(f"Unexpected atom field {predicate2.n3()}")
    return _Atom(kind, predicate, arguments, node)


def _compile_rules(graph: Graph, *, parse_builtin=None, schedule=None) -> tuple[_Rule, ...]:
    variables = frozenset(graph.subjects(RDF.type, SWRL.Variable))
    if any(not isinstance(v, URIRef) for v in variables):
        raise UnsupportedSemantics("SWRL variables must use named IRIs")
    rules, used = [], set()
    for identifier in sorted(set(graph.subjects(RDF.type, SWRL.Imp)), key=_key):
        if not isinstance(identifier, URIRef):
            raise UnsupportedSemantics("SWRL rules require stable named IRIs")
        body_nodes = _list(graph, _one(graph, identifier, SWRL.body))
        head_nodes = _list(graph, _one(graph, identifier, SWRL.head))
        if not body_nodes or not head_nodes:
            raise UnsupportedSemantics("SWRL body and head must be nonempty")
        body = tuple(_parse_atom(graph, node, variables, False, parse_builtin) for node in body_nodes)
        head = tuple(_parse_atom(graph, node, variables, True, parse_builtin) for node in head_nodes)
        bound = {v for atom in body if atom.kind != SWRL.BuiltinAtom
                 for v in atom.arguments if v in variables}
        required = {v for atom in (*body, *head)
                    for v in atom.arguments if v in variables}
        if schedule is None and required - bound:
            raise UnsupportedSemantics("All head/builtin variables must be bound by body class/property atoms")
        if not any(atom.kind != SWRL.BuiltinAtom for atom in body):
            raise UnsupportedSemantics("A SWRL body needs at least one class/property atom")
        individuals, data_values = set(), set()
        for atom in (*body, *head):
            if atom.kind == SWRL.BuiltinAtom:
                data_values.update(v for v in atom.arguments if v in variables)
            else:
                if atom.arguments[0] in variables:
                    individuals.add(atom.arguments[0])
                if atom.kind == SWRL.IndividualPropertyAtom and atom.arguments[1] in variables:
                    individuals.add(atom.arguments[1])
                if atom.kind == SWRL.DatavaluedPropertyAtom and atom.arguments[1] in variables:
                    data_values.add(atom.arguments[1])
        if individuals & data_values:
            raise UnsupportedSemantics("A rule variable cannot be both an individual and a literal value")
        # Join class/property atoms before filters: body order is not procedural.
        ordered = tuple(a for a in body if a.kind != SWRL.BuiltinAtom) + tuple(
            a for a in body if a.kind == SWRL.BuiltinAtom)
        if schedule is not None:
            ordered = schedule(body, head, variables)
        rules.append(_Rule(identifier, ordered, head, variables))
        used.update(body_nodes + head_nodes)
    orphan_atoms = {s for kind in _ATOMS for s in graph.subjects(RDF.type, kind)} - used
    if orphan_atoms:
        raise UnsupportedSemantics("Orphan SWRL atoms are not attached to any rule")
    typed = set(graph.subjects(RDF.type, SWRL.Imp))
    for predicate in (SWRL.body, SWRL.head):
        if set(graph.subjects(predicate, None)) - typed:
            raise UnsupportedSemantics("Rule body/head found without swrl:Imp declaration")
    atom_fields = {SWRL.classPredicate, SWRL.propertyPredicate, SWRL.argument1,
                   SWRL.argument2, SWRL.builtin, SWRL.arguments}
    typed_atoms = {s for kind in _ATOMS for s in graph.subjects(RDF.type, kind)}
    if any(s not in typed_atoms for s, p, _ in graph if p in atom_fields):
        raise UnsupportedSemantics("SWRL atom field found without a supported atom declaration")
    return tuple(rules)


def _rule_schema(rules: Graph) -> Graph:
    """Extract schema declarations while rejecting misplaced business assertions."""
    result = Graph()
    structural = {s for kind in (_ATOMS | {SWRL.Imp, SWRL.Variable})
                  for s in rules.subjects(RDF.type, kind)}
    for predicate in (SWRL.body, SWRL.head, SWRL.arguments):
        for root in rules.objects(None, predicate):
            visited = set()
            while root != RDF.nil:
                if root in visited:
                    raise UnsupportedSemantics("Cyclic SWRL list")
                visited.add(root)
                structural.add(root)
                root = _one(rules, root, RDF.rest)
    annotation_properties = set(rules.subjects(RDF.type, OWL.AnnotationProperty))
    annotations = {RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy,
                   OWL.versionIRI, OWL.versionInfo, OWL.deprecated, _RULE_ENABLED}
    schema_subjects = {s for s, p, o in rules if p in _SCHEMA_PREDICATES or (
                       p == RDF.type and o in _DECLARATIONS)}
    for triple in rules:
        subject, predicate, obj = triple
        if predicate in _SCHEMA_PREDICATES or (predicate == RDF.type and obj in _DECLARATIONS):
            result.add(triple)
        elif subject in structural:
            # Rule/atom/variable annotations stay in the rule artifact; unlike
            # domain data, they are not available as SWRL body facts.
            continue
        elif predicate in annotations or predicate in annotation_properties or str(predicate).startswith((
                "http://purl.org/dc/terms/", "http://purl.org/dc/elements/1.1/")):
            if subject in schema_subjects:
                result.add(triple)
        else:
            raise UnsupportedSemantics(
                f"Business assertions belong in facts, not the rules graph: {_triple_key(triple)}")
    return result


def _check_property_values(graph: Graph, compiled: tuple[_Rule, ...]) -> None:
    """Check the resource/literal boundary used by this execution profile."""
    object_properties = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    data_properties = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    for kind in (OWL.TransitiveProperty, OWL.SymmetricProperty):
        object_properties.update(graph.subjects(RDF.type, kind))
    for subject, _, obj in graph.triples((None, OWL.inverseOf, None)):
        object_properties.update((subject, obj))
    for rule in compiled:
        for atom in (*rule.body, *rule.head):
            if atom.kind == SWRL.IndividualPropertyAtom:
                object_properties.add(atom.predicate)
            elif atom.kind == SWRL.DatavaluedPropertyAtom:
                data_properties.add(atom.predicate)
    overlap = object_properties & data_properties
    if overlap:
        raise UnsupportedSemantics("Properties cannot have both object and data roles: " +
                                   ", ".join(map(str, sorted(overlap, key=_key))))
    for prop in sorted(object_properties, key=_key):
        if any(isinstance(obj, Literal) for obj in graph.objects(None, prop)):
            raise UnsupportedSemantics(f"Object property has a literal-valued assertion: {prop}")
    for prop in sorted(data_properties, key=_key):
        if any(not isinstance(obj, Literal) for obj in graph.objects(None, prop)):
            raise UnsupportedSemantics(f"Data property has a resource-valued assertion: {prop}")


def inspect_semantics(ontology: Graph, rules: Graph) -> list[str]:
    """Return deterministic diagnostics; no reasoning or network access occurs."""
    ontology = _canonical_scope(ontology, "inspection-data")
    rules = _canonical_scope(rules, "inspection-rules")
    graph = _copy(ontology)
    for triple in rules:
        graph.add(triple)
    issues = set()
    if any(str(p).startswith(str(SWRL)) or (p == RDF.type and str(o).startswith(str(SWRL)))
           for _, p, o in ontology):
        issues.add("SWRL definitions must be in the explicit rules graph")
    for subject, predicate, obj in graph:
        if not isinstance(predicate, URIRef) or isinstance(subject, Literal):
            issues.add("Only standard RDF triples (resource subject, IRI predicate) are supported")
        if str(predicate).startswith(str(OWL)) and predicate not in _OWL_PREDICATES:
            issues.add(f"Unsupported OWL predicate: {predicate}")
        if predicate == RDF.type and str(obj).startswith(str(OWL)) and obj not in _OWL_TYPES:
            issues.add(f"Unsupported OWL type: {obj}")
        if predicate == RDF.type and str(obj).startswith(str(RDFS)) and obj not in {RDFS.Class, RDFS.Datatype}:
            issues.add(f"Unsupported RDFS type: {obj}")
        if predicate == RDF.type and str(obj).startswith(str(RDF)) and obj not in {RDF.Property, RDF.Statement, RDF.List}:
            issues.add(f"Unsupported RDF type: {obj}")
        if predicate == RDF.type and obj in _DECLARATIONS and not isinstance(subject, URIRef):
            issues.add("Class/property/ontology declarations require named IRIs")
        if str(predicate).startswith(str(RDFS)) and predicate not in _RDFS_PREDICATES:
            issues.add(f"Unsupported RDFS predicate: {predicate}")
        if str(predicate).startswith(str(RDF)) and predicate not in _RDF_PREDICATES:
            issues.add(f"Unsupported RDF predicate: {predicate}")
        if predicate in _SCHEMA_PREDICATES:
            if not isinstance(subject, URIRef) or not isinstance(obj, URIRef):
                issues.add("Schema axioms require named IRIs; anonymous class expressions are unsupported")
            elif str(subject).startswith(_RESERVED) or (
                str(obj).startswith(_RESERVED) and not (
                    predicate == RDFS.range and str(obj).startswith(str(XSD)))):
                issues.add("Schema axioms involving reserved vocabulary are unsupported except XSD datatype range")
        for term in (subject, predicate, obj):
            if isinstance(term, URIRef) and str(term).startswith(str(SWRL)) and term not in _SWRL_TERMS:
                issues.add(f"Unsupported SWRL vocabulary: {term}")
        if predicate == SWRL.builtin and obj not in _COMPARISONS:
            issues.add(f"Unsupported SWRL builtin: {obj}")
        if predicate == _RULE_ENABLED and obj != Literal(True):
            issues.add("Disabled or non-boolean SWRL activation flags are unsupported; remove inactive rules explicitly")
        if isinstance(obj, Literal) and (obj.datatype in _INTEGER_TYPES or
                                        obj.datatype in {XSD.decimal, XSD.boolean}):
            try:
                _value(obj)
            except UnsupportedSemantics as exc:
                issues.add(str(exc))
    for prop in set(graph.subjects(RDF.type, OWL.DatatypeProperty)):
        if (prop, RDF.type, OWL.ObjectProperty) in graph or any(
            (prop, RDF.type, t) in graph for t in (OWL.TransitiveProperty, OWL.SymmetricProperty)):
            issues.add(f"Property has incompatible object/data declarations: {prop}")
        if any(graph.triples((prop, OWL.inverseOf, None))) or any(graph.triples((None, OWL.inverseOf, prop))):
            issues.add(f"inverseOf cannot apply to a declared datatype property: {prop}")
    try:
        compiled = _compile_rules(graph)
        _rule_schema(rules)
        _check_property_values(graph, compiled)
        for rule in compiled:
            for atom in (*rule.body, *rule.head):
                if atom.kind == SWRL.IndividualPropertyAtom and (atom.predicate, RDF.type, OWL.DatatypeProperty) in graph:
                    issues.add(f"Object atom refers to declared datatype property: {atom.predicate}")
                if atom.kind == SWRL.DatavaluedPropertyAtom and (atom.predicate, RDF.type, OWL.ObjectProperty) in graph:
                    issues.add(f"Data atom refers to declared object property: {atom.predicate}")
    except UnsupportedSemantics as exc:
        issues.add(str(exc))
    return sorted(issues)


def _bind(pattern: Identifier, value: Identifier, bindings: dict,
          variables: frozenset[Identifier], same_term=_same_term) -> bool:
    if pattern in variables:
        if pattern in bindings:
            return same_term(bindings[pattern], value)
        bindings[pattern] = value
        return True
    return same_term(pattern, value)


def _matches(graph: Graph, atom: _Atom, bindings: dict,
             variables: frozenset[Identifier], *, same_term=_same_term, on_candidate=None):
    subject_arg = atom.arguments[0]
    subject = bindings.get(subject_arg) if subject_arg in variables else subject_arg
    predicate = RDF.type if atom.kind == SWRL.ClassAtom else atom.predicate
    obj = atom.predicate if atom.kind == SWRL.ClassAtom else None
    for triple in sorted(graph.triples((subject, predicate, obj)), key=_triple_key):
        if on_candidate is not None:
            on_candidate()
        if not isinstance(triple[0], (URIRef, BNode)):
            continue
        if atom.kind == SWRL.IndividualPropertyAtom and not isinstance(triple[2], (URIRef, BNode)):
            continue
        if atom.kind == SWRL.DatavaluedPropertyAtom and not isinstance(triple[2], Literal):
            continue
        new_bindings = dict(bindings)
        if not _bind(subject_arg, triple[0], new_bindings, variables, same_term):
            continue
        if atom.kind != SWRL.ClassAtom and not _bind(atom.arguments[1], triple[2], new_bindings, variables, same_term):
            continue
        yield new_bindings, triple


def _rule_candidates(graph: Graph, rule: _Rule):
    states = [({}, ())]
    for atom in rule.body:
        next_states = []
        for bindings, premises in states:
            if atom.kind == SWRL.BuiltinAtom:
                values = tuple(bindings[a] if a in rule.variables else a for a in atom.arguments)
                if _compare(atom.predicate, values):
                    next_states.append((bindings, premises))
            else:
                for new_bindings, triple in _matches(graph, atom, bindings, rule.variables):
                    next_states.append((new_bindings, premises + (triple,)))
        states = next_states
        if not states:
            return
    for bindings, premises in states:
        for atom in rule.head:
            values = tuple(bindings[a] if a in rule.variables else a for a in atom.arguments)
            if not isinstance(values[0], (URIRef, BNode)):
                raise UnsupportedSemantics("Rule heads require individual subjects")
            if atom.kind == SWRL.ClassAtom:
                triple = (values[0], RDF.type, atom.predicate)
            else:
                expected = Literal if atom.kind == SWRL.DatavaluedPropertyAtom else (URIRef, BNode)
                if not isinstance(values[1], expected):
                    raise UnsupportedSemantics("Rule head value does not match its object/data atom kind")
                triple = (values[0], atom.predicate, values[1])
            yield triple, OT.rule, rule.identifier, tuple(sorted(set(premises), key=_triple_key))


def _axiom_candidates(graph: Graph):
    def result(triple, axiom, *premises):
        return triple, OT.axiom, axiom, tuple(sorted(set((axiom,) + premises), key=_triple_key))

    for child, _, parent in sorted(graph.triples((None, RDFS.subClassOf, None)), key=_triple_key):
        axiom = (child, RDFS.subClassOf, parent)
        for item, _, _ in sorted(graph.triples((None, RDF.type, child)), key=_triple_key):
            yield result((item, RDF.type, parent), axiom, (item, RDF.type, child))
        for _, _, ancestor in sorted(graph.triples((parent, RDFS.subClassOf, None)), key=_triple_key):
            yield result((child, RDFS.subClassOf, ancestor), axiom, (parent, RDFS.subClassOf, ancestor))
    for child, _, parent in sorted(graph.triples((None, RDFS.subPropertyOf, None)), key=_triple_key):
        axiom = (child, RDFS.subPropertyOf, parent)
        for subject, _, obj in sorted(graph.triples((None, child, None)), key=_triple_key):
            yield result((subject, parent, obj), axiom, (subject, child, obj))
        for _, _, ancestor in sorted(graph.triples((parent, RDFS.subPropertyOf, None)), key=_triple_key):
            yield result((child, RDFS.subPropertyOf, ancestor), axiom, (parent, RDFS.subPropertyOf, ancestor))
    for schema_predicate in (RDFS.domain, RDFS.range):
        for prop, _, cls in sorted(graph.triples((None, schema_predicate, None)), key=_triple_key):
            axiom = (prop, schema_predicate, cls)
            for subject, _, obj in sorted(graph.triples((None, prop, None)), key=_triple_key):
                item = subject if schema_predicate == RDFS.domain else obj
                # Standard RDF cannot encode literal subjects. Datatype range is
                # a declaration here, not literal validation (use SHACL).
                if isinstance(item, Literal) or str(cls).startswith(str(XSD)):
                    continue
                yield result((item, RDF.type, cls), axiom, (subject, prop, obj))
    for prop, _, inverse in sorted(graph.triples((None, OWL.inverseOf, None)), key=_triple_key):
        axiom = (prop, OWL.inverseOf, inverse)
        for source, target in ((prop, inverse), (inverse, prop)):
            for subject, _, obj in sorted(graph.triples((None, source, None)), key=_triple_key):
                if isinstance(obj, Literal):
                    raise UnsupportedSemantics("inverseOf cannot be applied to literal-valued assertions")
                yield result((obj, target, subject), axiom, (subject, source, obj))
    for kind in (OWL.SymmetricProperty, OWL.TransitiveProperty):
        for prop in sorted(set(graph.subjects(RDF.type, kind)), key=_key):
            axiom = (prop, RDF.type, kind)
            for subject, _, obj in sorted(graph.triples((None, prop, None)), key=_triple_key):
                if isinstance(obj, Literal):
                    raise UnsupportedSemantics("Symmetric/transitive properties require resource values")
                if kind == OWL.SymmetricProperty:
                    yield result((obj, prop, subject), axiom, (subject, prop, obj))
                else:
                    for _, _, other in sorted(graph.triples((obj, prop, None)), key=_triple_key):
                        if isinstance(other, Literal):
                            raise UnsupportedSemantics("Transitive properties require resource values")
                        yield result((subject, prop, other), axiom, (subject, prop, obj), (obj, prop, other))


def _statement(trace: Graph, triple: Triple) -> URIRef:
    identifier = _id("statement", _triple_key(triple))
    trace.add((identifier, RDF.type, RDF.Statement))
    for predicate, obj in zip((RDF.subject, RDF.predicate, RDF.object), triple):
        trace.add((identifier, predicate, obj))
    return identifier


def compile_swrl_rules(rules: Graph) -> tuple[_Rule, ...]:
    """Compile only the supported SWRL language, without inspecting OWL axioms.

    The existing local profile deliberately keeps its own OWL guard. The
    projection profile calls this separate rule layer after an OWL DL check.
    """
    for _, predicate, obj in rules:
        for term in (predicate, obj):
            if isinstance(term, URIRef) and str(term).startswith(str(SWRL)) and term not in _SWRL_TERMS:
                raise UnsupportedSemantics(f"Unsupported SWRL vocabulary: {term}")
        if predicate == _RULE_ENABLED and obj != Literal(True):
            raise UnsupportedSemantics("Disabled or non-boolean SWRL activation flags are unsupported")
    compiled = _compile_rules(rules)
    _rule_schema(rules)
    _check_property_values(rules, compiled)
    return compiled


def swrl_seed(rules: Graph) -> tuple[Graph, frozenset[Literal]]:
    """Return reviewed rule declarations, named constants and literal constants."""
    compiled = compile_swrl_rules(rules)
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


def normalize_projection_literals(graph: Graph) -> Graph:
    """Use the RDF 1.1 spelling for plain strings in the projection profile.

    This is not applied to local-rules-v1 and does not alter literal values or
    numerics. HermiT serializes an untagged RDF string as xsd:string; normalizing
    that spelling avoids counting the same value as a new fact on every round.
    """
    result = Graph()
    for triple in graph:
        result.add(tuple(Literal(str(t), datatype=XSD.string, normalize=False)
                         if isinstance(t, Literal) and t.datatype is None and not t.language
                         else t for t in triple))
    return result


def _named_candidate_view(facts: Graph, candidates: Graph, iteration: int, *, on_expansion=None):
    """Shared frozen entity domain, sameAs expansion and direct evidence."""
    roots = list(candidates.subjects(RDF.type, OT.CandidateDomain))
    if len(roots) != 1:
        raise UnsupportedSemantics("Exactly one frozen CandidateDomain is required")
    root = roots[0]
    individuals = set(candidates.objects(root, OT.individual))
    classes = set(candidates.objects(root, OT["class"]))
    objects = set(candidates.objects(root, OT.objectProperty))
    data = set(candidates.objects(root, OT.dataProperty))
    literals = set(candidates.objects(root, OT.literal))
    if any(not isinstance(v, URIRef) for v in individuals | classes | objects | data):
        raise UnsupportedSemantics("Frozen entity candidates must be named IRIs")
    if any(not isinstance(v, Literal) for v in literals):
        raise UnsupportedSemantics("Frozen literal candidates must be RDF literals")
    view, trace = Graph(), Graph()
    for s, p, o in facts:
        if s not in individuals:
            continue
        if ((p == RDF.type and o in classes) or
            (p in objects and o in individuals) or
            (p in data and o in literals) or
            (p == OWL.sameAs and o in individuals)):
            view.add((s, p, o))
    original = _copy(view)
    aliases = {v: {v} for v in individuals}
    for s, _, o in view.triples((None, OWL.sameAs, None)):
        merged = aliases[s] | aliases[o]
        for member in merged:
            aliases[member] = merged

    def record(triple, kind, source, premises):
        conclusion = _statement(trace, triple)
        premise_ids = tuple(_statement(trace, premise) for premise in sorted(set(premises), key=_triple_key))
        derivation = _id("derivation", "\n".join((str(conclusion), str(kind), str(source),
                                                   *(str(v) for v in premise_ids))))
        trace.add((derivation, RDF.type, OT.Derivation))
        trace.add((derivation, OT.conclusion, conclusion))
        trace.add((derivation, kind, source))
        trace.add((derivation, OT.iteration, Literal(iteration)))
        for premise in premise_ids:
            trace.add((derivation, OT.premise, premise))

    # HermiT normally supplies these aliases already; this closure also makes
    # this independently usable rule layer correct on a sparse equality graph.
    equalities = tuple(view.triples((None, OWL.sameAs, None)))
    for s, p, o in sorted(original, key=_triple_key):
        targets = aliases[o] if p in objects or p == OWL.sameAs else {o}
        for subject in sorted(aliases[s], key=_key):
            for obj in sorted(targets, key=_key):
                triple = (subject, p, obj)
                # Count attempted identity substitutions before allocating any
                # additional facts or their evidence. Ordinary unchanged
                # triples remain free; the legacy profile supplies no hook.
                if on_expansion is not None and (subject != s or obj != o):
                    on_expansion(trace)
                if p == OWL.sameAs and subject == obj:
                    continue
                if triple not in view:
                    view.add(triple)
                    record(triple, OT.axiom, OWL.sameAs, ( (s, p, o), *equalities ))
    return view, original, trace, record, (individuals, classes, objects, data, literals)


def apply_swrl_rules(rules: Graph, facts: Graph, candidates: Graph,
                     iteration: int = 1) -> InferenceResult:
    """Perform one named-domain SWRL step; never interpret complex OWL here.

    Equality expands individual positions only. Class/property IRIs are never
    renamed, including when an IRI is punned as both an individual and a class.
    Every new conclusion retains its actual direct premises.
    """
    rules = normalize_projection_literals(rules)
    facts = normalize_projection_literals(facts)
    candidates = normalize_projection_literals(candidates)
    compiled = compile_swrl_rules(rules)
    view, original, trace, record, domain = _named_candidate_view(facts, candidates, iteration)
    individuals, classes, objects, data, literals = domain
    additions = Graph()
    for triple in view:
        if triple not in original:
            additions.add(triple)
    pending = {}
    for rule in compiled:
        for triple, kind, source, premises in _rule_candidates(view, rule):
            s, p, o = triple
            if (s not in individuals or
                (p == RDF.type and o not in classes) or
                (p in objects and o not in individuals) or
                (p in data and o not in literals) or
                p not in {RDF.type} | objects | data):
                raise UnsupportedSemantics("SWRL conclusion escapes the frozen named candidate domain")
            if triple not in view:
                pending.setdefault(triple, (kind, source, premises))
    for triple in sorted(pending, key=_triple_key):
        kind, source, premises = pending[triple]
        view.add(triple)
        additions.add(triple)
        record(triple, kind, source, premises)
    return InferenceResult(view, additions, trace, int(bool(additions)))


def infer(ontology: Graph, rules: Graph, facts: Graph,
          max_iterations: int = 100) -> InferenceResult:
    """Materialise to a verified fixed point, retaining one actual proof per fact.

    A round uses only the previous round's graph; results and first proofs are
    deterministic under RDF graph isomorphism. The budget counts rounds that
    add facts. A separate no-change probe verifies completion at the limit.
    """
    if type(max_iterations) is not int or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    ontology = _canonical_scope(ontology, "ontology")
    rules = _canonical_scope(rules, "rules")
    facts = _canonical_scope(facts, "facts")
    combined = _copy(ontology)
    for triple in facts:
        combined.add(triple)
    diagnostics = inspect_semantics(combined, rules)
    if diagnostics:
        raise UnsupportedSemantics("; ".join(diagnostics))
    # All executable rule definitions must be supplied in the rules graph.
    if any(str(p).startswith(str(SWRL)) or (p == RDF.type and str(o).startswith(str(SWRL)))
           for _, p, o in combined):
        raise UnsupportedSemantics("SWRL definitions must be in the explicit rules graph")
    compiled = _compile_rules(rules)
    for triple in _rule_schema(rules):
        combined.add(triple)
    closure, inferred, trace = _copy(combined), Graph(), Graph()
    for graph in (closure, inferred, trace):
        graph.bind("ot", OT)
    iterations = 0
    while True:
        _check_property_values(closure, compiled)
        candidates = list(_axiom_candidates(closure))
        for rule in compiled:
            candidates.extend(_rule_candidates(closure, rule))
        pending = {}
        def candidate_key(item):
            triple, kind, source, premises = item
            source_key = _triple_key(source) if isinstance(source, tuple) else _key(source)
            return (_triple_key(triple), _key(kind), source_key,
                    tuple(map(_triple_key, premises)))
        for candidate in sorted(candidates, key=candidate_key):
            if candidate[0] not in closure:
                pending.setdefault(candidate[0], candidate)
        if not pending:
            return InferenceResult(closure, inferred, trace, iterations)
        if iterations >= max_iterations:
            raise InferenceLimitError(f"No fixed point within {max_iterations} inference rounds")
        iterations += 1
        for triple, kind, source, premises in pending.values():
            closure.add(triple)
            inferred.add(triple)
            conclusion_id = _statement(trace, triple)
            source_id = _statement(trace, source) if isinstance(source, tuple) else source
            premise_ids = tuple(_statement(trace, premise) for premise in premises)
            derivation_id = _id("derivation", "\n".join((str(conclusion_id), str(kind),
                str(source_id), *(str(p) for p in premise_ids))))
            trace.add((derivation_id, RDF.type, OT.Derivation))
            trace.add((derivation_id, OT.conclusion, conclusion_id))
            trace.add((derivation_id, kind, source_id))
            trace.add((derivation_id, OT.iteration, Literal(iterations, datatype=XSD.integer)))
            for premise_id in premise_ids:
                trace.add((derivation_id, OT.premise, premise_id))
