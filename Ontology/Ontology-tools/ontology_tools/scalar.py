"""Deterministic scalar functions for hermit-swrl-calculation-v1.

This module supplies arithmetic, comparisons and timezone-aware instants. It
does not contain business rules, fetch the clock, modify a graph or generate
individuals. Fractions and integer milliseconds keep all operations independent
of Decimal context, floating point and the machine's timezone.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import re
from types import MappingProxyType

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

OTFN = Namespace("https://w3id.org/ontology-tools/functions#")
SWRLB = Namespace("http://www.w3.org/2003/11/swrlb#")
VERSION = "1"


class ScalarError(ValueError):
    """A deterministic function/type/representation failure, never a false filter."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class BuiltinSpec:
    predicate: URIRef
    arity: int
    input_positions: tuple[int, ...]
    output_position: int | None
    input_types: tuple[str, ...]
    output_type: str
    version: str = VERSION

    @property
    def is_comparison(self) -> bool:
        return self.output_position is None


_COMPARISONS = frozenset(SWRLB[name] for name in (
    "equal", "notEqual", "lessThan", "lessThanOrEqual", "greaterThan",
    "greaterThanOrEqual"))
_specs = [BuiltinSpec(p, 2, (0, 1), None, ("comparable", "comparable"), "boolean")
          for p in sorted(_COMPARISONS)]
_specs += [BuiltinSpec(SWRLB[name], 3, (1, 2), 0,
                      ("number", "number"), "number")
           for name in ("add", "subtract", "multiply", "divide")]
_specs += [
    BuiltinSpec(OTFN.divideRounded, 5, (1, 2, 3, 4), 0,
                ("number", "number", "nonnegative-integer", "rounding-mode"), "decimal"),
    BuiltinSpec(OTFN.secondsBetween, 3, (1, 2), 0,
                ("datetime", "datetime"), "decimal"),
    BuiltinSpec(OTFN.addSeconds, 3, (1, 2), 0,
                ("datetime", "number"), "datetime"),
]
REGISTRY = MappingProxyType({spec.predicate: spec for spec in _specs})
_INTEGER_TYPES = frozenset(XSD[name] for name in (
    "integer", "nonPositiveInteger", "negativeInteger", "long", "int", "short",
    "byte", "nonNegativeInteger", "unsignedLong", "unsignedInt", "unsignedShort",
    "unsignedByte", "positiveInteger"))
_INTEGER_BOUNDS = {
    XSD.nonPositiveInteger: (None, 0), XSD.negativeInteger: (None, -1),
    XSD.long: (-(2**63), 2**63 - 1), XSD.int: (-(2**31), 2**31 - 1),
    XSD.short: (-(2**15), 2**15 - 1), XSD.byte: (-128, 127),
    XSD.nonNegativeInteger: (0, None), XSD.positiveInteger: (1, None),
    XSD.unsignedLong: (0, 2**64 - 1), XSD.unsignedInt: (0, 2**32 - 1),
    XSD.unsignedShort: (0, 2**16 - 1), XSD.unsignedByte: (0, 255),
}
_TEMPORAL_TYPES = frozenset((XSD.dateTime, XSD.dateTimeStamp))
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
_INTEGER_RE = re.compile(r"[+-]?[0-9]+\Z")
_INSTANT_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]{1,3}))?(Z|[+-][0-9]{2}:[0-9]{2})\Z")
_DAY_MS = 86_400_000
_MAX_INSTANT = date(9999, 12, 31).toordinal() * _DAY_MS - 1
_ROUNDING = frozenset(("HALF_EVEN", "HALF_UP", "DOWN", "FLOOR", "CEILING"))


def get_spec(predicate: URIRef) -> BuiltinSpec:
    try:
        return REGISTRY[predicate]
    except (KeyError, TypeError):
        raise ScalarError("unknown-function", f"Unsupported builtin: {predicate}") from None


def _budget(max_numeric_digits: int) -> int:
    if type(max_numeric_digits) is not int or max_numeric_digits <= 0:
        raise ScalarError("invalid-budget", "max_numeric_digits must be a positive integer")
    return max_numeric_digits


def _literal(value) -> Literal:
    if not isinstance(value, Literal):
        raise ScalarError("invalid-argument", "Scalar arguments must be RDF literals")
    if value.language:
        raise ScalarError("unsupported-datatype", "Language-tagged literals are unsupported")
    return value


def _digit_int(digits: str) -> int:
    """Avoid Python's process-dependent decimal-string conversion limit."""
    result = 0
    for start in range(0, len(digits), 9):
        part = digits[start:start + 9]
        result = result * (10 ** len(part)) + int(part)
    return result


def _int_digits(value: int) -> str:
    value = abs(value)
    if not value:
        return "0"
    parts = []
    while value:
        value, chunk = divmod(value, 1_000_000_000)
        parts.append(chunk)
    return str(parts[-1]) + "".join(f"{part:09d}" for part in reversed(parts[:-1]))


def _number(value: Literal, budget: int) -> tuple[Fraction, bool]:
    value = _literal(value)
    datatype, lexical = value.datatype, str(value).strip(" \t\r\n")
    integer = datatype in _INTEGER_TYPES
    if not integer and datatype != XSD.decimal:
        raise ScalarError("unsupported-datatype", f"Expected integer or decimal, received {datatype}")
    pattern = _INTEGER_RE if integer else _NUMBER_RE
    if not pattern.fullmatch(lexical):
        raise ScalarError("invalid-number", f"Invalid numeric lexical form: {value.n3()}")
    unsigned = lexical.lstrip("+-")
    # Discard redundant fractional zeroes before counting/constructing a
    # coefficient. Canonical integral decimals spell '.0', whose zero is not
    # another value digit; accepting our own output is budget-stable.
    if not integer and "." in unsigned:
        whole, fractional = unsigned.split(".", 1)
        fractional = fractional.rstrip("0")
        digits = (whole or "0") + fractional
        scale = len(fractional)
    else:
        digits, scale = unsigned, 0
    if len(digits) > budget:
        raise ScalarError("numeric-budget", "Input number exceeds max_numeric_digits")
    coefficient = _digit_int(digits)
    if lexical.startswith("-"):
        coefficient = -coefficient
    if integer:
        lower, upper = _INTEGER_BOUNDS.get(datatype, (None, None))
        if ((lower is not None and coefficient < lower)
                or (upper is not None and coefficient > upper)):
            raise ScalarError("integer-range", f"Literal is outside {datatype}: {value.n3()}")
        return Fraction(coefficient), True
    return Fraction(coefficient, 10 ** scale), False


def _integer_literal(number: int, budget: int) -> Literal:
    digits = _int_digits(number)
    if len(digits) > budget:
        raise ScalarError("numeric-budget", "Computed integer exceeds max_numeric_digits")
    lexical = ("-" if number < 0 else "") + digits
    return Literal(lexical, datatype=XSD.integer, normalize=False)


def _decimal_coefficient(coefficient: int, scale: int, budget: int) -> Literal:
    if not coefficient:
        return Literal("0.0", datatype=XSD.decimal, normalize=False)
    while scale and coefficient % 10 == 0:
        coefficient //= 10
        scale -= 1
    digits = _int_digits(coefficient)
    # Count value digits, including leading fractional zeroes, but excluding
    # the purely syntactic '.0' used to spell integral decimal values.
    if max(len(digits), scale + 1 if scale else 1) > budget:
        raise ScalarError("numeric-budget", "Computed decimal exceeds max_numeric_digits")
    if scale:
        padded = digits.zfill(scale + 1)
        lexical = padded[:-scale] + "." + padded[-scale:]
    else:
        lexical = digits + ".0"
    if coefficient < 0:
        lexical = "-" + lexical
    return Literal(lexical, datatype=XSD.decimal, normalize=False)


def _decimal_literal(number: Fraction, budget: int) -> Literal:
    denominator, twos, fives = number.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ScalarError("non-terminating-decimal", "Exact result has no finite decimal representation")
    scale = max(twos, fives)
    if scale > budget:
        raise ScalarError("numeric-budget", "Computed decimal scale exceeds max_numeric_digits")
    coefficient = number.numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    return _decimal_coefficient(coefficient, scale, budget)


def _instant(value: Literal) -> int:
    value = _literal(value)
    if value.datatype not in _TEMPORAL_TYPES:
        raise ScalarError("unsupported-datatype", "Expected xsd:dateTime or xsd:dateTimeStamp")
    match = _INSTANT_RE.fullmatch(str(value).strip(" \t\r\n"))
    if match is None:
        raise ScalarError("invalid-datetime", "Time requires year 0001..9999, timezone and at most milliseconds")
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    fraction, zone = match.group(7), match.group(8)
    if hour > 23 or minute > 59 or second > 59:
        raise ScalarError("invalid-datetime", "Hours must be 00..23; minutes and seconds 00..59")
    try:
        ordinal = date(year, month, day).toordinal()
    except ValueError as exc:
        raise ScalarError("invalid-datetime", str(exc)) from exc
    offset = 0
    if zone != "Z":
        offset_hour, offset_minute = int(zone[1:3]), int(zone[4:6])
        if offset_hour > 14 or offset_minute > 59 or (offset_hour == 14 and offset_minute):
            raise ScalarError("invalid-datetime", "Timezone offset must be within -14:00..+14:00")
        offset = (offset_hour * 60 + offset_minute) * (1 if zone[0] == "+" else -1)
    millis = ((ordinal - 1) * _DAY_MS + hour * 3_600_000 + minute * 60_000
              + second * 1000 + int((fraction or "0").ljust(3, "0")) - offset * 60_000)
    if not 0 <= millis <= _MAX_INSTANT:
        raise ScalarError("datetime-range", "UTC instant is outside years 0001..9999")
    return millis


def _instant_literal(millis: int) -> Literal:
    if not 0 <= millis <= _MAX_INSTANT:
        raise ScalarError("datetime-range", "Computed UTC instant is outside years 0001..9999")
    days, remaining = divmod(millis, _DAY_MS)
    actual_date = date.fromordinal(days + 1)
    hour, remaining = divmod(remaining, 3_600_000)
    minute, remaining = divmod(remaining, 60_000)
    second, fraction = divmod(remaining, 1000)
    suffix = (f".{fraction:03d}".rstrip("0")) if fraction else ""
    lexical = (f"{actual_date.year:04d}-{actual_date.month:02d}-{actual_date.day:02d}"
               f"T{hour:02d}:{minute:02d}:{second:02d}{suffix}Z")
    return Literal(lexical, datatype=XSD.dateTime, normalize=False)


def canonical_temporal_literal(value: Literal, *, preserve_datatype: bool = True) -> Literal:
    """Return the same supported instant in millisecond-exact UTC notation.

    A bridge using this helper must retain the original semantic input and
    record the value-preserving normalization; this function does not mutate it.
    """
    canonical = _instant_literal(_instant(value))
    if preserve_datatype:
        return Literal(str(canonical), datatype=value.datatype, normalize=False)
    return canonical


def _value(value: Literal, budget: int) -> tuple[str, object]:
    value = _literal(value)
    if value.datatype in _INTEGER_TYPES or value.datatype == XSD.decimal:
        return "number", _number(value, budget)[0]
    if value.datatype in _TEMPORAL_TYPES:
        return "datetime", _instant(value)
    if value.datatype in (None, XSD.string):
        return "string", str(value)
    if value.datatype == XSD.boolean:
        if str(value) not in {"true", "false", "0", "1"}:
            raise ScalarError("invalid-boolean", f"Invalid boolean: {value.n3()}")
        return "boolean", str(value) in {"true", "1"}
    raise ScalarError("unsupported-datatype", f"Unsupported comparison datatype: {value.datatype}")


def same_value(left, right, *, max_numeric_digits: int = 1000) -> bool:
    """Supported literal value equality; other RDF terms use exact term equality.

    Invalid lexical forms of supported datatypes are errors even when their RDF
    terms happen to be identical. Unknown datatypes are not silently coerced.
    """
    budget = _budget(max_numeric_digits)
    if not isinstance(left, Literal) or not isinstance(right, Literal):
        return left == right
    supported = _INTEGER_TYPES | _TEMPORAL_TYPES | {None, XSD.decimal, XSD.string, XSD.boolean}
    a = _value(left, budget) if left.datatype in supported and not left.language else None
    b = _value(right, budget) if right.datatype in supported and not right.language else None
    return a == b if a is not None and b is not None else left == right


def compare(predicate: URIRef, left: Literal, right: Literal, *, max_numeric_digits: int = 1000) -> bool:
    if predicate not in _COMPARISONS:
        raise ScalarError("unknown-comparison", f"Unsupported comparison: {predicate}")
    budget = _budget(max_numeric_digits)
    a_kind, a = _value(left, budget)
    b_kind, b = _value(right, budget)
    if a_kind != b_kind:
        raise ScalarError("incompatible-datatypes", "Comparison requires compatible input datatypes")
    if predicate == SWRLB.equal:
        return a == b
    if predicate == SWRLB.notEqual:
        return a != b
    if a_kind == "boolean":
        raise ScalarError("unsupported-comparison", "Booleans support only equal and notEqual")
    if predicate == SWRLB.lessThan:
        return a < b
    if predicate == SWRLB.lessThanOrEqual:
        return a <= b
    if predicate == SWRLB.greaterThan:
        return a > b
    return a >= b


def evaluate(predicate: URIRef, arguments, *, max_numeric_digits: int = 1000) -> Literal | bool:
    """Evaluate already-bound inputs; the rule output position is not passed in."""
    spec = get_spec(predicate)
    budget = _budget(max_numeric_digits)
    arguments = tuple(arguments)
    if len(arguments) != len(spec.input_positions):
        raise ScalarError("arity", f"{predicate} requires {len(spec.input_positions)} input arguments")
    for argument in arguments:
        _literal(argument)
    if spec.is_comparison:
        return compare(predicate, *arguments, max_numeric_digits=budget)
    if predicate == OTFN.secondsBetween:
        return _decimal_literal(Fraction(_instant(arguments[0]) - _instant(arguments[1]), 1000), budget)
    if predicate == OTFN.addSeconds:
        instant = _instant(arguments[0])
        seconds, _ = _number(arguments[1], budget)
        delta = seconds * 1000
        if delta.denominator != 1:
            raise ScalarError("datetime-precision", "Offset must be an exact number of milliseconds")
        return _instant_literal(instant + delta.numerator)
    left, left_integer = _number(arguments[0], budget)
    right, right_integer = _number(arguments[1], budget)
    if predicate == OTFN.divideRounded:
        if not right:
            raise ScalarError("division-by-zero", "The divisor is zero")
        scale_value, is_integer = _number(arguments[2], budget)
        if not is_integer or scale_value < 0:
            raise ScalarError("invalid-scale", "Rounding scale must be a nonnegative integer literal")
        scale = scale_value.numerator
        if scale > budget:
            raise ScalarError("numeric-budget", "Rounding scale exceeds max_numeric_digits")
        mode_literal = arguments[3]
        if mode_literal.datatype not in (None, XSD.string) or str(mode_literal) not in _ROUNDING:
            raise ScalarError("invalid-rounding", "An explicit supported rounding mode is required")
        mode = str(mode_literal)
        scaled = (left / right) * (10 ** scale)
        sign = -1 if scaled < 0 else 1
        quotient, remainder = divmod(abs(scaled.numerator), scaled.denominator)
        if (mode == "HALF_EVEN" and (2 * remainder > scaled.denominator
                or (2 * remainder == scaled.denominator and quotient % 2))
                or mode == "HALF_UP" and 2 * remainder >= scaled.denominator
                or mode == "FLOOR" and sign < 0 and remainder
                or mode == "CEILING" and sign > 0 and remainder):
            quotient += 1
        return _decimal_coefficient(sign * quotient, scale, budget)
    if predicate == SWRLB.add:
        result = left + right
    elif predicate == SWRLB.subtract:
        result = left - right
    elif predicate == SWRLB.multiply:
        result = left * right
    else:
        if not right:
            raise ScalarError("division-by-zero", "The divisor is zero")
        result = left / right
    if predicate != SWRLB.divide and left_integer and right_integer:
        return _integer_literal(result.numerator, budget)
    return _decimal_literal(result, budget)


def annotation_literal_positions(graph: Graph) -> frozenset:
    """Annotation object positions, including OWL reified annotation targets.

    An annotatedTarget repeats the object of its annotatedProperty assertion.
    It must follow that property's role so an annotation and its reification
    retain the same literal. Ambiguous or untyped reifications are not exempt.
    """
    annotations = set(graph.subjects(RDF.type, OWL.AnnotationProperty)) | {
        RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy,
        OWL.versionInfo, OWL.deprecated, OWL.priorVersion,
        OWL.backwardCompatibleWith, OWL.incompatibleWith,
    }
    positions = {(subject, predicate) for subject, predicate, _ in graph if predicate in annotations}
    for kind in (OWL.Axiom, OWL.Annotation):
        for subject in graph.subjects(RDF.type, kind):
            properties = set(graph.objects(subject, OWL.annotatedProperty))
            if len(properties) == 1 and next(iter(properties)) in annotations:
                positions.add((subject, OWL.annotatedTarget))
    return frozenset(positions)


def validate_temporal_literals(graph: Graph) -> None:
    """Check semantic datetime literals without interpreting annotation values.

    The caller must parse source literals with normalization disabled, since a
    graph cannot recover precision already discarded by a parser. Rule constants
    and OWL restriction/list literals are semantic and are checked as well.
    """
    annotations = annotation_literal_positions(graph)
    seen = set()
    for subject, predicate, obj in graph:
        if (subject, predicate) in annotations:
            continue
        if isinstance(obj, Literal) and obj.datatype in _TEMPORAL_TYPES and obj not in seen:
            _instant(obj)
            seen.add(obj)
