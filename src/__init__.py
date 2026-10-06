"""
Modular Document Parsing System.

A flexible, SOLID-principles-based document parsing framework with
pluggable components for extraction, chunking, enrichment, and formatting.

Components:
    - Extractors: Raw content extraction (PDF, DOCX, PPTX, MD, TXT, Code)
    - Chunkers: Intelligent splitting (format-specific strategies)
    - Enrichers: Content analysis (keywords, sections, metadata)
    - Formatters: Output transformation (JSON, Weaviate, Neo4j)

Names are imported on first access (PEP 562): importing any ``src.*`` module no
longer drags in every extractor and its heavy dependencies.
"""
from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.0.0"

_EXPORTS: dict[str, str] = {
    "RawDocument": "models",
    "Chunk": "models",
    "EnrichedChunk": "models",
    "ProcessedDocument": "models",
    "DocumentPipeline": "pipeline",
    "KeywordExtractor": "enrichment",
    "SectionDetector": "enrichment",
    "TitleGenerator": "enrichment",
    "MetadataEnricher": "enrichment",
    "SimpleFormatter": "formatters",
    "WeaviateFormatter": "formatters",
    "Neo4jFormatter": "formatters",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
