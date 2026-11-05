"""Optional RDF authoring helpers. No project policy or automatic source overwrite."""
from rdflib import BNode, Literal, RDF, RDFS
from rdflib.namespace import OWL, XSD


def rdf_list(graph, values):
    head = RDF.nil
    for value in reversed(list(values)):
        cell = BNode()
        graph.add((cell, RDF.first, value))
        graph.add((cell, RDF.rest, head))
        head = cell
    return head


def named_class(graph, iri, label, parent=None, comment=None):
    graph.add((iri, RDF.type, OWL.Class))
    graph.add((iri, RDFS.label, Literal(label, lang="zh")))
    if parent is not None:
        graph.add((iri, RDFS.subClassOf, parent))
    if comment:
        graph.add((iri, RDFS.comment, Literal(comment, lang="zh")))
    return iri


def property_(graph, iri, label, domain, range_, *, datatype=False,
              inverse=None, functional=False, transitive=False, comment=None):
    graph.add((iri, RDF.type, OWL.DatatypeProperty if datatype else OWL.ObjectProperty))
    graph.add((iri, RDFS.label, Literal(label, lang="zh")))
    if comment:
        graph.add((iri, RDFS.comment, Literal(comment, lang="zh")))
    if domain is not None:
        graph.add((iri, RDFS.domain, domain))
    if range_ is not None:
        graph.add((iri, RDFS.range, range_))
    if inverse is not None:
        if datatype:
            raise ValueError("Data properties have no inverse object property")
        graph.add((inverse, RDF.type, OWL.ObjectProperty))
        graph.add((iri, OWL.inverseOf, inverse))
        graph.add((inverse, OWL.inverseOf, iri))
    if functional:
        graph.add((iri, RDF.type, OWL.FunctionalProperty))
    if transitive:
        if datatype:
            raise ValueError("Data properties cannot be transitive")
        graph.add((iri, RDF.type, OWL.TransitiveProperty))
    return iri


def restriction(graph, prop, facet, value):
    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    graph.add((node, facet, value))
    return node


def enum_restriction(graph, prop, values):
    datatype = BNode()
    graph.add((datatype, RDF.type, RDFS.Datatype))
    graph.add((datatype, OWL.oneOf, rdf_list(graph, [Literal(v, datatype=XSD.string) for v in values])))
    return restriction(graph, prop, OWL.allValuesFrom, datatype)


def some_values(graph, prop, cls):
    return restriction(graph, prop, OWL.someValuesFrom, cls)


def min_cardinality(graph, prop, count):
    if type(count) is not int or count < 0:
        raise ValueError("Cardinality must be a non-negative integer")
    return restriction(graph, prop, OWL.minCardinality, Literal(count, datatype=XSD.nonNegativeInteger))


def union_domain(graph, prop, classes):
    node = BNode()
    graph.add((node, RDF.type, OWL.Class))
    graph.add((node, OWL.unionOf, rdf_list(graph, classes)))
    graph.remove((prop, RDFS.domain, None))
    graph.add((prop, RDFS.domain, node))
    return node


def has_key(graph, cls, properties):
    graph.add((cls, OWL.hasKey, rdf_list(graph, properties)))


def individual(graph, iri, cls, label=None):
    graph.add((iri, RDF.type, OWL.NamedIndividual))
    graph.add((iri, RDF.type, cls))
    if label:
        graph.add((iri, RDFS.label, Literal(label, lang="zh")))
    return iri
