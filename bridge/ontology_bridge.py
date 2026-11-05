"""DSH transport adapter; business semantics remain in the unchanged native engine.

JSON is used only on stdout as the host tool protocol. Engine artifacts remain
RDF/Turtle/Markdown. This module is deliberately outside ontology_tools so its
addition does not change the engine's replay identity.
"""
from __future__ import annotations
import contextlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'Ontology' / 'Ontology-tools'
sys.path.insert(0, str(ENGINE))


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


def environment(java):
    dependencies = {}
    for name in ('rdflib', 'pyshacl', 'packaging'):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    java_path = shutil.which(java)
    java_info, java_ready = '', False
    if java_path:
        try:
            result = subprocess.run([java_path, '-version'], capture_output=True,
                text=True, encoding='utf-8', errors='replace', timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            java_info = (result.stdout + result.stderr).strip()[:3000]
            java_ready = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            java_info = str(exc)
    engine_version, native_ready, detail = None, False, ''
    try:
        import ontology_tools
        from ontology_tools import inspect_package
        engine_version = ontology_tools.__version__
        # Runtime fingerprints can be verified without writing any report.
        from ontology_tools.io import verify_manifest
        verify_manifest(ENGINE / 'java', required=True)
        verify_manifest(ENGINE / 'vendor' / 'owl-dl', required=True)
        native_ready = all(dependencies.values())
        if not native_ready:
            detail = 'Missing required Python dependencies'
    except Exception as exc:
        detail = str(exc)
    return dict(status='ready' if native_ready and java_ready else 'incomplete',
        pythonExecutable=sys.executable, pythonVersion=platform.python_version(),
        engineVersion=engine_version, dependencies=dependencies, javaExecutable=java_path,
        javaReady=java_ready, javaVersion=java_info, nativeRuntimeReady=native_ready,
        detail=detail, capabilities={'nativeRules': native_ready,
            'owlDL': native_ready and java_ready, 'calculation': native_ready and java_ready,
            'formula': native_ready and java_ready},
        documentExtraction='Host parsers/OCR must be available separately; not tested by this probe.')


def check_java_selection(arguments, java):
    # Package RDF must not choose an arbitrary executable through javaExecutable.
    from ontology_tools.io import OT, parse_rdf, file_set
    configs = []
    for flag in ('--package', '--run'):
        if flag in arguments:
            root = Path(arguments[arguments.index(flag) + 1])
            files = file_set(root)  # Reject links before reading metadata.
            configs.extend(file for file in files.values() if file.name == 'runtime.ttl')
            if flag == '--run' and 'execution.ttl' in files:
                configs.append(files['execution.ttl'])
    allowed = {'java', java}
    resolved = shutil.which(java)
    if resolved:
        allowed.add(resolved)
    for config in configs:
        selected = parse_rdf(config).objects(None, OT.javaExecutable)
        if any(str(item) not in allowed for item in selected):
            raise ValueError('Package/replay javaExecutable differs from the trusted plugin configuration')


def run(arguments, java):
    from ontology_tools.__main__ import main
    from ontology_tools.io import OT, parse_rdf
    from rdflib import URIRef, Literal
    from rdflib.namespace import SH
    check_java_selection(arguments, java)
    output = (Path(arguments[arguments.index('--output') + 1])
              if '--output' in arguments else None)
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            exit_code = main(arguments)
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    report = dict(status='passed' if exit_code == 0 else 'failed', exitCode=exit_code,
        stage=arguments[0], semanticState=None, outputPath=str(output) if output else None,
        artifacts=[], summary=(stdout.getvalue() + stderr.getvalue())[-16000:])
    if output and output.is_dir():
        artifacts = sorted(p.name for p in output.iterdir() if p.is_file())
        report['artifacts'] = artifacts
        if (output / 'execution.ttl').is_file():
            graph = parse_rdf(output / 'execution.ttl')
            node = URIRef('urn:ontology-tools:run')
            for key, predicate in [('status', OT.status), ('stage', OT.stage),
                                   ('semanticState', OT.semanticState)]:
                value = graph.value(node, predicate)
                if value is not None:
                    report[key] = str(value)
            saved = graph.value(node, OT.exitCode)
            if saved is not None and int(saved) != exit_code:
                raise ValueError('Engine CLI and saved execution exit codes disagree')
        # Standalone OWL checks store semantic findings in report.ttl, not
        # execution.ttl. Surface those explicit findings without altering them.
        if report['semanticState'] is None and arguments[0] in {'owl-dl', 'owl-infer'}:
            finding = output / 'report.ttl'
            if finding.is_file():
                graph = parse_rdf(finding)
                node = URIRef('urn:ontology-tools:run')
                consistent = graph.value(node, OT.consistent)
                if consistent == Literal(False):
                    report['semanticState'] = 'inconsistent'
                elif consistent == Literal(True):
                    report['semanticState'] = ('unsatisfiable'
                        if any(graph.objects(node, OT.unsatisfiableClass)) else 'consistent')
        if report['semanticState'] is None and arguments[0] == 'validate':
            finding = output / 'shacl-report.ttl'
            if finding.is_file():
                graph = parse_rdf(finding)
                if (None, SH.conforms, Literal(False)) in graph:
                    report['semanticState'] = 'shacl-nonconformant'
                elif (None, SH.conforms, Literal(True)) in graph:
                    report['semanticState'] = 'shacl-conformant'
    return report


def main():
    if len(sys.argv) < 3:
        raise ValueError('Expected doctor|run and a trusted Java executable')
    operation, java, *arguments = sys.argv[1:]
    if java != 'java':
        resolved = shutil.which(java)
        if resolved:
            os.environ['PATH'] = str(Path(resolved).parent) + os.pathsep + os.environ.get('PATH', '')
    if operation == 'doctor':
        emit(environment(java))
    elif operation == 'run':
        emit(run(arguments, java))
    else:
        raise ValueError('Unknown bridge action')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit(dict(status='failed', exitCode=2, stage='bridge', semanticState='unknown',
                  outputPath=None, artifacts=[], summary=f'{type(exc).__name__}: {exc}'))
        sys.exit(2)
