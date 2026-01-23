"""
Modular Document Parsing System.

A flexible, SOLID-principles-based document parsing framework with
pluggable components for extraction, chunking, enrichment, and formatting.

Example Usage:
    >>> from parsers import DocumentPipeline
    >>> pipeline = DocumentPipeline()
    >>> result = pipeline.process("document.pdf")

Components:
    - Extractors: Raw content extraction (PDF, DOCX, PPTX, MD, TXT, Code)
    - Chunkers: Intelligent splitting (format-specific strategies)
    - Enrichers: Content analysis (keywords, sections, metadata)
    - Formatters: Output transformation (JSON, Weaviate, Neo4j)
"""

# Data models
# Enrichers
from .enrichment import KeywordExtractor, MetadataEnricher, SectionDetector, TitleGenerator

# Formatters
from .formatters import Neo4jFormatter, SimpleFormatter, WeaviateFormatter
from .models import Chunk, EnrichedChunk, ProcessedDocument, RawDocument

# Pipeline
from .pipeline import DocumentPipeline

__version__ = "1.0.0"

__all__ = [
    # Models
    "RawDocument",
    "Chunk",
    "EnrichedChunk",
    "ProcessedDocument",

    # Pipeline
    "DocumentPipeline",

    # Enrichers
    "KeywordExtractor",
    "SectionDetector",
    "TitleGenerator",
    "MetadataEnricher",

    # Formatters
    "SimpleFormatter",
    "WeaviateFormatter",
    "Neo4jFormatter",
]
