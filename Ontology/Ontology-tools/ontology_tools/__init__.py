"""Local, evidence-producing tools for native ontology packages."""

__version__ = "0.4.0"


def __getattr__(name):
    if name in {"check_consistency", "infer_owl"}:
        from . import owl_dl
        return getattr(owl_dl, name)
    if name in {"inspect_package", "validate_graph", "infer_graph", "query_graph", "run_cases", "replay_run"}:
        from . import core
        return getattr(core, name)
    raise AttributeError(name)
