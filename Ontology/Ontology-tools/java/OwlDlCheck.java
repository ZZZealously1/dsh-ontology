import java.io.ByteArrayInputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.security.MessageDigest;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import org.semanticweb.HermiT.Reasoner;
import org.semanticweb.owlapi.formats.RDFXMLDocumentFormat;
import org.semanticweb.owlapi.io.RDFParserMetaData;
import org.semanticweb.owlapi.model.*;
import org.semanticweb.owlapi.profiles.OWL2DLProfile;
import org.semanticweb.owlapi.profiles.OWLProfileReport;
import org.semanticweb.owlapi.profiles.OWLProfileViolation;
import org.semanticweb.owlapi.rdf.rdfxml.parser.RDFXMLParserFactory;
import org.semanticweb.owlapi.rdf.rdfxml.parser.IRIProvider;
import org.semanticweb.owlapi.rdf.rdfxml.parser.OWLRDFConsumer;
import org.semanticweb.owlapi.rdf.rdfxml.parser.RDFParser;
import org.semanticweb.owlapi.reasoner.OWLReasoner;
import org.semanticweb.owlapi.vocab.OWLRDFVocabulary;
import org.semanticweb.owlapi.util.OWLObjectWalker;
import org.semanticweb.owlapi.util.OWLObjectVisitorAdapter;
import org.semanticweb.owlapi.util.StructureWalker;
import uk.ac.manchester.cs.owl.owlapi.OWLDataFactoryImpl;
import uk.ac.manchester.cs.owl.owlapi.OWLOntologyFactoryImpl;
import uk.ac.manchester.cs.owl.owlapi.OWLOntologyImpl;
import uk.ac.manchester.cs.owl.owlapi.OWLOntologyManagerImpl;
import org.w3c.dom.Document;
import org.xml.sax.InputSource;

/** Offline OWL 2 DL checker. Input is one fully assembled RDF/XML ontology. */
public final class OwlDlCheck {
    private static final String PROTOCOL = "owl-dl-v1";
    private static final String PROJECTION_PROTOCOL = "owl-projection-v1";

    /**
     * OWLAPI 4.5.29 consumes list edges during streaming, then its strict
     * translators try to read those edges again. Retain read-only resource
     * list lookups, and present the original declarations before other edges.
     * No triples or entity declarations are invented and strict remains true.
     */
    private static final class StrictListConsumer extends OWLRDFConsumer {
        private final Map<IRI, IRI> first = new HashMap<>();
        private final Map<IRI, IRI> rest = new HashMap<>();
        private final Map<IRI, List<String>> literalFirst = new HashMap<>();
        private final IRIProvider provider;
        private final List<String[]> resources = new ArrayList<>();
        private final List<String[]> literals = new ArrayList<>();
        private static final IRI FIRST = OWLRDFVocabulary.RDF_FIRST.getIRI();
        private static final IRI REST = OWLRDFVocabulary.RDF_REST.getIRI();
        private static final IRI NIL = OWLRDFVocabulary.RDF_NIL.getIRI();

        StrictListConsumer(OWLOntology ontology, OWLOntologyLoaderConfiguration config,
                           IRIProvider parser) {
            super(ontology, config);
            provider = parser;
            setIRIProvider(parser);
        }

        private IRI iri(String value) {
            IRI result = provider.getIRI(value);
            return result == null ? IRI.create(value) : result;
        }

        private void remember(IRI subject, IRI predicate, IRI object) {
            Map<IRI, IRI> map = FIRST.equals(predicate) ? first : REST.equals(predicate) ? rest : null;
            if (map != null) {
                IRI old = map.putIfAbsent(subject, object);
                if ((old != null && !old.equals(object)) || NIL.equals(subject)
                        || (FIRST.equals(predicate) && literalFirst.containsKey(subject))) {
                    throw new IllegalArgumentException("Ambiguous RDF list: " + subject);
                }
            }
        }

        @Override public void statementWithResourceValue(String s, String p, String o) {
            remember(iri(s), iri(p), iri(o));
            resources.add(new String[]{s, p, o});
        }

        @Override public void statementWithResourceValue(IRI s, IRI p, IRI o) {
            remember(s, p, o);
            super.statementWithResourceValue(s, p, o);
        }

        @Override public void statementWithLiteralValue(String s, String p, String value,
                                                        String lang, String datatype) {
            IRI subject = iri(s), predicate = iri(p);
            if (REST.equals(predicate)) throw new IllegalArgumentException("Literal rdf:rest: " + s);
            if (FIRST.equals(predicate)) {
                List<String> item = Arrays.asList(value, lang, datatype);
                List<String> old = literalFirst.putIfAbsent(subject, item);
                if (NIL.equals(subject) || first.containsKey(subject) || (old != null && !old.equals(item))) {
                    throw new IllegalArgumentException("Ambiguous RDF list: " + s);
                }
            }
            literals.add(new String[]{s, p, value, lang, datatype});
        }

        private void validateLists() {
            Set<IRI> nodes = new HashSet<>(first.keySet());
            nodes.addAll(literalFirst.keySet());
            nodes.addAll(rest.keySet());
            Map<IRI, Boolean> done = new HashMap<>();
            for (IRI start : nodes) {
                Set<IRI> chain = new HashSet<>();
                IRI node = start;
                Boolean literalKind = null;
                while (!NIL.equals(node) && !done.containsKey(node)) {
                    if (!chain.add(node)) throw new IllegalArgumentException("Cyclic RDF list: " + start);
                    if ((!first.containsKey(node) && !literalFirst.containsKey(node)) || !rest.containsKey(node)) {
                        throw new IllegalArgumentException("Incomplete RDF list: " + node);
                    }
                    boolean isLiteral = literalFirst.containsKey(node);
                    if (literalKind != null && literalKind != isLiteral) {
                        throw new IllegalArgumentException("Mixed resource/literal OWL list: " + start);
                    }
                    literalKind = isLiteral;
                    node = rest.get(node);
                }
                if (literalKind != null && !NIL.equals(node) && !literalKind.equals(done.get(node))) {
                    throw new IllegalArgumentException("Mixed resource/literal OWL list: " + start);
                }
                for (IRI member : chain) done.put(member, literalKind);
            }
        }

        @Override public void endModel() {
            validateLists();
            String type = OWLRDFVocabulary.RDF_TYPE.getIRI().toString();
            for (String[] t : resources) if (type.equals(t[1])) super.statementWithResourceValue(t[0], t[1], t[2]);
            for (String[] t : resources) if (!type.equals(t[1])) super.statementWithResourceValue(t[0], t[1], t[2]);
            for (String[] t : literals) super.statementWithLiteralValue(t[0], t[1], t[2], t[3], t[4]);
            super.endModel();
        }

        @Override protected IRI getResourceObject(IRI s, IRI p, boolean consume) {
            if (!consume && FIRST.equals(p)) return first.get(s);
            if (!consume && REST.equals(p)) return rest.get(s);
            return super.getResourceObject(s, p, consume);
        }

        @Override protected IRI getFirstResource(IRI node, boolean consume) {
            IRI original = super.getFirstResource(node, consume);
            // List tails can be shared by several OWL expressions. A first
            // translation must not remove members from subsequent expressions.
            return first.containsKey(node) ? first.get(node) : original;
        }

        @Override protected IRI getRest(IRI node, boolean consume) {
            IRI original = super.getRest(node, consume);
            IRI value = rest.containsKey(node) ? rest.get(node) : original;
            // OWLAPI's translator expects null, not rdf:nil, as its terminator.
            return NIL.equals(value) ? null : value;
        }
    }

    private static void row(String key, Object value) {
        System.out.println(key + "\t" + value);
    }

    private static String b64(String text) {
        return Base64.getEncoder().encodeToString(text.getBytes(StandardCharsets.UTF_8));
    }

    private static void preflight(byte[] content) throws Exception {
        // Perform a secure XML parse before OWLAPI can resolve imports or entities.
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
        factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        factory.setXIncludeAware(false);
        factory.setExpandEntityReferences(false);
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        Document document = factory.newDocumentBuilder().parse(new ByteArrayInputStream(content));
        if (document.getElementsByTagNameNS("http://www.w3.org/2002/07/owl#", "imports").getLength() != 0) {
            throw new IllegalArgumentException("owl:imports is prohibited; supply a locally assembled closure");
        }
        if (!"http://www.w3.org/1999/02/22-rdf-syntax-ns#".equals(document.getDocumentElement().getNamespaceURI())
                || !"RDF".equals(document.getDocumentElement().getLocalName())) {
            throw new IllegalArgumentException("The bridge accepts RDF/XML with an rdf:RDF root only");
        }
    }

    private static final class Domain {
        final Set<String> individuals = new TreeSet<>();
        final Set<String> classes = new TreeSet<>();
        final Set<String> objects = new TreeSet<>();
        final Set<String> data = new TreeSet<>();
        final Map<String, OWLLiteral> literals = new HashMap<>();
    }

    private static String decode(String text) {
        return new String(Base64.getDecoder().decode(text), StandardCharsets.UTF_8);
    }

    private static String literalRow(OWLLiteral value) {
        // OWLAPI 4 represents RDF plain/language literals with the OWL 2
        // rdf:PlainLiteral datatype. The external RDF 1.1 graph must use
        // xsd:string / rdf:langString, never invent an rdf:PlainLiteral value.
        String datatype = value.hasLang() ? "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
                : value.isRDFPlainLiteral() ? "http://www.w3.org/2001/XMLSchema#string"
                : value.getDatatype().getIRI().toString();
        return b64(value.getLiteral()) + "\t" + b64(datatype)
                + "\t" + b64(value.getLang());
    }

    private static Domain domain(OWLOntology ontology, Path candidateFile) throws Exception {
        Domain domain = new Domain();
        OWLDataFactory factory = ontology.getOWLOntologyManager().getOWLDataFactory();
        if (candidateFile == null) {
            ontology.getIndividualsInSignature().forEach(v -> domain.individuals.add(v.getIRI().toString()));
            ontology.getClassesInSignature().forEach(v -> domain.classes.add(v.getIRI().toString()));
            ontology.getObjectPropertiesInSignature().forEach(v -> domain.objects.add(v.getIRI().toString()));
            ontology.getDataPropertiesInSignature().forEach(v -> domain.data.add(v.getIRI().toString()));
            // Walk logical axioms only, with annotations explicitly excluded.
            // Thus labels, ontology metadata and axiom-annotation literals do not
            // silently become candidate business values.
            OWLObjectWalker<OWLLogicalAxiom> walker = new OWLObjectWalker<>(
                    ontology.getLogicalAxioms(), StructureWalker.AnnotationWalkingControl.DONT_WALK_ANNOTATIONS);
            walker.walkStructure(new OWLObjectVisitorAdapter() {
                @Override public void visit(OWLLiteral value) { domain.literals.put(literalRow(value), value); }
            });
        } else {
            List<String> lines = Files.readAllLines(candidateFile, StandardCharsets.UTF_8);
            if (lines.size() < 2 || !"DOMAIN\towl-projection-v1".equals(lines.get(0))
                    || !"END\towl-projection-v1".equals(lines.get(lines.size() - 1))) {
                throw new IllegalArgumentException("Incomplete frozen candidate domain");
            }
            Set<String> seen = new HashSet<>();
            for (String line : lines.subList(1, lines.size() - 1)) {
                if (!seen.add(line)) throw new IllegalArgumentException("Duplicate frozen candidate");
                String[] fields = line.split("\t", -1);
                if (fields.length == 4 && "LITERAL".equals(fields[0])) {
                    String lexical = decode(fields[1]), datatype = decode(fields[2]), lang = decode(fields[3]);
                    OWLLiteral literal = lang.isEmpty()
                            ? factory.getOWLLiteral(lexical, factory.getOWLDatatype(IRI.create(datatype)))
                            : factory.getOWLLiteral(lexical, lang);
                    if (!lang.isEmpty() && !"http://www.w3.org/1999/02/22-rdf-syntax-ns#langString".equals(datatype)) {
                        throw new IllegalArgumentException("Invalid language-literal datatype");
                    }
                    domain.literals.put(fields[1] + "\t" + fields[2] + "\t" + fields[3], literal);
                    continue;
                }
                if (fields.length != 2) throw new IllegalArgumentException("Malformed frozen candidate");
                String value = decode(fields[1]);
                IRI iri = IRI.create(value);
                OWLEntity entity;
                switch (fields[0]) {
                    case "INDIVIDUAL": entity = factory.getOWLNamedIndividual(iri); domain.individuals.add(value); break;
                    case "CLASS": entity = factory.getOWLClass(iri); domain.classes.add(value); break;
                    case "OBJECT": entity = factory.getOWLObjectProperty(iri); domain.objects.add(value); break;
                    case "DATA": entity = factory.getOWLDataProperty(iri); domain.data.add(value); break;
                    default: throw new IllegalArgumentException("Unknown frozen candidate kind");
                }
                if (!entity.isBuiltIn() && !ontology.containsEntityInSignature(entity)) {
                    throw new IllegalArgumentException("Frozen candidate is outside the semantic signature: " + fields[0] + " " + value);
                }
            }
        }
        return domain;
    }

    private static void projection(OWLOntology ontology, OWLReasoner reasoner, Domain domain) throws Exception {
        Set<String> candidates = new TreeSet<>(), classification = new TreeSet<>(), facts = new TreeSet<>();
        for (String iri : domain.individuals) candidates.add("CAND_INDIVIDUAL\t" + b64(iri));
        for (String iri : domain.classes) candidates.add("CAND_CLASS\t" + b64(iri));
        for (String iri : domain.objects) candidates.add("CAND_OBJECT\t" + b64(iri));
        for (String iri : domain.data) candidates.add("CAND_DATA\t" + b64(iri));
        for (String literal : domain.literals.keySet()) candidates.add("CAND_LITERAL\t" + literal);
        OWLDataFactory factory = ontology.getOWLOntologyManager().getOWLDataFactory();
        if (reasoner != null) {
            for (String iri : domain.classes) {
                OWLClass cls = factory.getOWLClass(IRI.create(iri));
                Set<OWLClass> supers = new HashSet<>(reasoner.getSuperClasses(cls, false).getFlattened());
                Set<OWLClass> equivalents = reasoner.getEquivalentClasses(cls).getEntities();
                supers.addAll(equivalents);
                for (OWLClass value : supers) if (!iri.equals(value.getIRI().toString()) && domain.classes.contains(value.getIRI().toString())) {
                    classification.add("SUBCLASS\t" + b64(iri) + "\t" + b64(value.getIRI().toString()));
                }
                for (OWLClass value : equivalents) if (!iri.equals(value.getIRI().toString()) && domain.classes.contains(value.getIRI().toString())) {
                    classification.add("EQUIVALENT\t" + b64(iri) + "\t" + b64(value.getIRI().toString()));
                }
            }
            for (String iri : domain.individuals) {
                OWLNamedIndividual individual = factory.getOWLNamedIndividual(IRI.create(iri));
                for (OWLClass cls : reasoner.getTypes(individual, false).getFlattened()) {
                    if (domain.classes.contains(cls.getIRI().toString())) {
                        facts.add("TYPE\t" + b64(iri) + "\t" + b64(cls.getIRI().toString()));
                    }
                }
                for (OWLNamedIndividual other : reasoner.getSameIndividuals(individual).getEntities()) {
                    // Self SameIndividual/EquivalentClasses RDF statements can
                    // collapse to unary OWLAPI axioms and violate OWL 2 DL.
                    // Omit these tautologies from reusable exported graphs.
                    if (!iri.equals(other.getIRI().toString()) && domain.individuals.contains(other.getIRI().toString())) {
                        facts.add("SAME\t" + b64(iri) + "\t" + b64(other.getIRI().toString()));
                    }
                }
                for (String property : domain.objects) {
                    OWLObjectProperty prop = factory.getOWLObjectProperty(IRI.create(property));
                    for (OWLNamedIndividual value : reasoner.getObjectPropertyValues(individual, prop).getFlattened()) {
                        if (domain.individuals.contains(value.getIRI().toString())) {
                            facts.add("OBJECT\t" + b64(iri) + "\t" + b64(property) + "\t" + b64(value.getIRI().toString()));
                        }
                    }
                }
                for (String property : domain.data) {
                    OWLDataProperty prop = factory.getOWLDataProperty(IRI.create(property));
                    for (Map.Entry<String, OWLLiteral> value : domain.literals.entrySet()) {
                        // getDataPropertyValues is not a complete entailment
                        // interface for values implied by arbitrary OWL axioms.
                        if (reasoner.isEntailed(factory.getOWLDataPropertyAssertionAxiom(prop, individual, value.getValue()))) {
                            facts.add("DATA\t" + b64(iri) + "\t" + b64(property) + "\t" + value.getKey());
                        }
                    }
                }
            }
        }
        List<String> payload = new ArrayList<>();
        payload.addAll(candidates);
        payload.addAll(classification);
        payload.addAll(facts);
        for (String line : payload) System.out.println(line);
        row("CANDIDATE_COUNT", candidates.size());
        row("CLASSIFICATION_COUNT", classification.size());
        row("FACT_COUNT", facts.size());
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(
                (String.join("\n", payload) + (payload.isEmpty() ? "" : "\n")).getBytes(StandardCharsets.UTF_8));
        StringBuilder hex = new StringBuilder();
        for (byte part : hash) hex.append(String.format("%02x", part & 255));
        row("PROJECTION_SHA256", hex);
    }

    private static void check(Path input, String mode, Path candidateFile) throws Exception {
        byte[] content = Files.readAllBytes(input);
        preflight(content);
        System.setProperty("javax.xml.accessExternalDTD", "");
        System.setProperty("javax.xml.accessExternalSchema", "");
        OWLOntologyLoaderConfiguration configuration = new OWLOntologyLoaderConfiguration()
                .setStrict(true).setRepairIllegalPunnings(false)
                .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.THROW_EXCEPTION)
                .setConnectionTimeout(1).setRetriesToAttempt(0).setFollowRedirects(false);
        // Construct only the required parser/factory. Do not discover network-capable parsers.
        OWLOntologyManager manager = new OWLOntologyManagerImpl(
                new OWLDataFactoryImpl(configuration), new ReentrantReadWriteLock());
        manager.setOntologyLoaderConfiguration(configuration);
        manager.setOntologyFactories(Collections.singleton(new OWLOntologyFactoryImpl(OWLOntologyImpl::new)));
        manager.setOntologyParsers(Collections.singleton(new RDFXMLParserFactory()));
        manager.setIRIMappers(Collections.singleton(iri -> {
            throw new IllegalArgumentException("Import resolution is prohibited: " + iri);
        }));
        OWLOntology ontology = manager.createOntology();
        RDFParser parser = new RDFParser();
        StrictListConsumer consumer = new StrictListConsumer(ontology, configuration, parser);
        RDFXMLDocumentFormat documentFormat = new RDFXMLDocumentFormat();
        consumer.setOntologyFormat(documentFormat);
        InputSource source = new InputSource(new ByteArrayInputStream(content));
        source.setSystemId(input.toUri().toString());
        parser.parse(source, consumer);
        manager.setOntologyFormat(ontology, documentFormat);
        if (!ontology.getImportsDeclarations().isEmpty()) {
            throw new IllegalArgumentException("The assembled ontology still contains imports");
        }
        if (ontology.getAxiomCount(AxiomType.SWRL_RULE) != 0) {
            throw new IllegalArgumentException("SWRL rules are outside this OWL 2 DL check; use separate rule validation");
        }
        org.semanticweb.owlapi.model.OWLDocumentFormat format = manager.getOntologyFormat(ontology);
        if (format.getOntologyLoaderMetaData() instanceof RDFParserMetaData) {
            RDFParserMetaData metadata = (RDFParserMetaData) format.getOntologyLoaderMetaData();
            if (!metadata.getUnparsedTriples().isEmpty()) {
                List<String> triples = new ArrayList<>();
                metadata.getUnparsedTriples().forEach(t -> triples.add(t.toString()));
                Collections.sort(triples);
                throw new IllegalArgumentException("Unparsed RDF triples: " + String.join("; ", triples));
            }
        } else {
            throw new IllegalStateException("RDF parser metadata is unavailable; cannot verify complete loading");
        }
        row("AXIOMS", ontology.getAxiomCount());
        row("LOGICAL_AXIOMS", ontology.getLogicalAxiomCount());
        OWLProfileReport profile = new OWL2DLProfile().checkOntology(ontology);
        row("PROFILE", profile.isInProfile());
        if (!profile.isInProfile()) {
            List<String> violations = new ArrayList<>();
            for (OWLProfileViolation violation : profile.getViolations()) {
                violations.add(violation.toString());
            }
            Collections.sort(violations);
            for (String violation : violations) row("VIOLATION", b64(violation));
            return;
        }
        Domain candidateDomain = !"check".equals(mode) ? domain(ontology, candidateFile) : null;
        if ("candidates".equals(mode)) {
            projection(ontology, null, candidateDomain);
            return;
        }
        OWLReasoner reasoner = new Reasoner.ReasonerFactory().createReasoner(ontology);
        try {
            row("REASONER", reasoner.getReasonerName());
            row("VERSION", reasoner.getReasonerVersion());
            boolean consistent = reasoner.isConsistent();
            row("CONSISTENT", consistent);
            // On an inconsistent ontology class satisfiability is not reported as a usable classification.
            if (consistent) {
                List<String> unsatisfiable = new ArrayList<>();
                reasoner.getUnsatisfiableClasses().getEntitiesMinusBottom().forEach(
                        c -> unsatisfiable.add(c.getIRI().toString()));
                Collections.sort(unsatisfiable);
                for (String iri : unsatisfiable) row("UNSAT", b64(iri));
                if ("infer".equals(mode) && unsatisfiable.isEmpty()) {
                    projection(ontology, reasoner, candidateDomain);
                }
            }
        } finally {
            reasoner.dispose();
        }
    }

    public static void main(String[] args) {
        try {
            System.setOut(new PrintStream(System.out, true, "UTF-8"));
            System.setErr(new PrintStream(System.err, true, "UTF-8"));
        } catch (java.io.UnsupportedEncodingException impossible) {
            throw new AssertionError(impossible);
        }
        String mode = args.length > 1 ? args[1] : "check";
        String protocol = "check".equals(mode) ? PROTOCOL : PROJECTION_PROTOCOL;
        row("PROTOCOL", protocol);
        if (!"check".equals(mode)) row("MODE", mode);
        row("OWLAPI", "4.5.29");
        row("HERMIT_ARTIFACT", "1.4.3.456");
        row("JAVA_VERSION", System.getProperty("java.version").replace('\t', ' ').replace('\n', ' '));
        row("JAVA_VENDOR", System.getProperty("java.vendor").replace('\t', ' ').replace('\n', ' '));
        if (args.length < 1 || args.length > 3 || !Arrays.asList("check", "infer", "candidates").contains(mode)) {
            row("ERROR", b64("Usage: OwlDlCheck <assembled-local-rdfxml-file> [check|infer|candidates] [candidate-domain.tsv]"));
            System.exit(2);
        }
        try {
            check(Paths.get(args[0]).toRealPath(), mode, args.length == 3 ? Paths.get(args[2]).toRealPath() : null);
            row("END", protocol);
        } catch (Throwable failure) {
            row("ERROR", b64(failure.getClass().getName() + ": " + failure.getMessage()));
            System.err.println(failure.getClass().getName() + ": " + failure.getMessage());
            System.exit(2);
        }
    }
}
