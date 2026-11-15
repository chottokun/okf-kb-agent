"""OKF v0.2 Markdown knowledge base (Pattern A/B, optional Pattern C)."""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import ContextBundle, ContextResolver
    from .embeddings import GemmaEmbedder, HttpEmbedder
    from .evolution import (
        FlowCluster,
        FlowRecord,
        analyse_flows,
        apply_cluster,
        load_history,
        propose_cluster,
        render_proposal,
        render_skill,
    )
    from .frontmatter import FrontmatterError, dump_document, parse_frontmatter
    from .graph import Edge, TraversalHit, WikiGraph, build_graph
    from .index import plan_indexes, stale_indexes, write_indexes
    from .model import (
        SCOPE_WEIGHTS,
        Concept,
        Link,
        Section,
        extract_links,
        extract_sections,
        find_wikilinks,
        iter_concepts,
        load_concept,
        scope_from_heading,
        scope_of,
        validate_meta,
        write_concept,
    )
    from .onnx_backend import MicroOnnxBackend
    from .qdrant_backend import QdrantBackend
    from .search import (
        BackendUnavailable,
        LocalSearchBackend,
        SearchHit,
        get_backend,
        pattern_for,
    )
    from .sqlite_backend import SQLiteSearchBackend
    from .synonyms import (
        ExpandedSearchBackend,
        SynonymIndex,
        evaluate_synonyms,
        load_eval_queries,
    )
    from .validate import ValidationReport, validate_wiki
    from .verify import (
        ClassifiedTarget,
        EvidenceRecord,
        SourceApiError,
        SourceMetadata,
        SourceOfflineError,
        SourceRateLimitError,
        SourceVerifier,
        SourceVerifyError,
        VerificationChecks,
        VerificationResult,
        classify_target,
    )

_EXPORTS: dict[str, tuple[str, str]] = {
    "BackendUnavailable": (".search", "BackendUnavailable"),
    "ClassifiedTarget": (".verify", "ClassifiedTarget"),
    "Concept": (".model", "Concept"),
    "ContextBundle": (".context", "ContextBundle"),
    "ContextResolver": (".context", "ContextResolver"),
    "Edge": (".graph", "Edge"),
    "EvidenceRecord": (".verify", "EvidenceRecord"),
    "ExpandedSearchBackend": (".synonyms", "ExpandedSearchBackend"),
    "FlowCluster": (".evolution", "FlowCluster"),
    "FlowRecord": (".evolution", "FlowRecord"),
    "FrontmatterError": (".frontmatter", "FrontmatterError"),
    "GemmaEmbedder": (".embeddings", "GemmaEmbedder"),
    "HttpEmbedder": (".embeddings", "HttpEmbedder"),
    "Link": (".model", "Link"),
    "LocalSearchBackend": (".search", "LocalSearchBackend"),
    "MicroOnnxBackend": (".onnx_backend", "MicroOnnxBackend"),
    "QdrantBackend": (".qdrant_backend", "QdrantBackend"),
    "SCOPE_WEIGHTS": (".model", "SCOPE_WEIGHTS"),
    "SQLiteSearchBackend": (".sqlite_backend", "SQLiteSearchBackend"),
    "SearchHit": (".search", "SearchHit"),
    "Section": (".model", "Section"),
    "SourceApiError": (".verify", "SourceApiError"),
    "SourceMetadata": (".verify", "SourceMetadata"),
    "SourceOfflineError": (".verify", "SourceOfflineError"),
    "SourceRateLimitError": (".verify", "SourceRateLimitError"),
    "SourceVerifier": (".verify", "SourceVerifier"),
    "SourceVerifyError": (".verify", "SourceVerifyError"),
    "SynonymIndex": (".synonyms", "SynonymIndex"),
    "TraversalHit": (".graph", "TraversalHit"),
    "ValidationReport": (".validate", "ValidationReport"),
    "VerificationChecks": (".verify", "VerificationChecks"),
    "VerificationResult": (".verify", "VerificationResult"),
    "WikiGraph": (".graph", "WikiGraph"),
    "analyse_flows": (".evolution", "analyse_flows"),
    "apply_cluster": (".evolution", "apply_cluster"),
    "build_graph": (".graph", "build_graph"),
    "classify_target": (".verify", "classify_target"),
    "dump_document": (".frontmatter", "dump_document"),
    "evaluate_synonyms": (".synonyms", "evaluate_synonyms"),
    "extract_links": (".model", "extract_links"),
    "extract_sections": (".model", "extract_sections"),
    "find_wikilinks": (".model", "find_wikilinks"),
    "get_backend": (".search", "get_backend"),
    "iter_concepts": (".model", "iter_concepts"),
    "load_concept": (".model", "load_concept"),
    "load_eval_queries": (".synonyms", "load_eval_queries"),
    "load_history": (".evolution", "load_history"),
    "parse_frontmatter": (".frontmatter", "parse_frontmatter"),
    "pattern_for": (".search", "pattern_for"),
    "plan_indexes": (".index", "plan_indexes"),
    "propose_cluster": (".evolution", "propose_cluster"),
    "render_proposal": (".evolution", "render_proposal"),
    "render_skill": (".evolution", "render_skill"),
    "scope_from_heading": (".model", "scope_from_heading"),
    "scope_of": (".model", "scope_of"),
    "stale_indexes": (".index", "stale_indexes"),
    "validate_meta": (".model", "validate_meta"),
    "validate_wiki": (".validate", "validate_wiki"),
    "write_concept": (".model", "write_concept"),
    "write_indexes": (".index", "write_indexes"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
