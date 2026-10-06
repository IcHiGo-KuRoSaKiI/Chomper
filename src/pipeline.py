"""
Document processing pipeline.

Orchestrates the full document processing workflow:
Extraction → Chunking → Enrichment → Formatting
"""
from pathlib import Path
from typing import Any

from .enrichment import KeywordExtractor, MetadataEnricher, SectionDetector, TitleGenerator
from .formatters import SimpleFormatter
from .models.document import Chunk, EnrichedChunk, ProcessedDocument
from .server.config import (
    CHUNKERS,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_STRATEGY,
    EXTRACTORS,
)
from .server.documents import build_chunker, load_document, validate_path


class DocumentPipeline:
    """
    Main document processing pipeline.

    Orchestrates the complete workflow from file to formatted output. Extraction
    and chunking go through the same registry, document cache and chunker
    factory as ``chomper.chunk()``, the CLI and the MCP server, so the pipeline
    cannot drift from them; only enrichment and formatting are its own.

    Usage:
        pipeline = DocumentPipeline()
        result = pipeline.process("document.pdf")

        # With custom configuration
        pipeline = DocumentPipeline(
            enrichers=[KeywordExtractor(), TitleGenerator()],
            formatter=WeaviateFormatter()
        )
    """

    #: Shared, lazily resolved registries (see ``src.server.config``).
    EXTRACTORS = EXTRACTORS
    CHUNKERS = CHUNKERS

    def __init__(
        self,
        enrichers: list[Any] | None = None,
        formatter: Any | None = None,
        skip_enrichment_for_code: bool = True,
        *,
        strategy: str = DEFAULT_CHUNK_STRATEGY,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        """
        Initialize pipeline.

        Args:
            enrichers: List of enricher instances (default: all enrichers)
            formatter: Formatter instance (default: SimpleFormatter)
            skip_enrichment_for_code: Skip enrichment for code files (default: True)
            strategy: Chunking strategy, as in ``chomper.chunk`` (default: auto)
            chunk_size: Maximum words per chunk (default: 1000)
            overlap: Words to overlap between chunks (default: 100)
        """
        # Default enrichers
        if enrichers is None:
            enrichers = [
                KeywordExtractor(method="rake", top_k=5),
                SectionDetector(method="heuristic"),
                TitleGenerator(method="keywords"),
                MetadataEnricher()
            ]

        # Default formatter
        if formatter is None:
            formatter = SimpleFormatter()

        self.enrichers = enrichers
        self.formatter = formatter
        self.skip_enrichment_for_code = skip_enrichment_for_code
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.overlap = overlap

    def process(self, file_path: str, doc_id: str | None = None) -> Any:
        """
        Process a document through the full pipeline.

        Args:
            file_path: Path to document
            doc_id: Optional document ID

        Returns:
            Formatted output (depends on formatter)
        """
        path = validate_path(file_path)
        extension = path.suffix.lower()

        # Step 1: Extract (shared cache; raises ValueError for unsupported formats)
        raw_doc = load_document(path)

        # Step 2: Chunk (shared factory and defaults)
        chunker = build_chunker(extension, self.strategy, self.chunk_size, self.overlap)
        chunks = chunker.chunk(raw_doc)

        # Step 3: Enrich (skip for code, structured data, and HTML if configured)
        is_code = extension in ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.cpp', '.c', '.go', '.rs']
        is_structured_data = extension in ['.xlsx', '.xlsm', '.xltx', '.xltm', '.csv', '.tsv']
        is_html = extension in ['.html', '.htm']

        if self.skip_enrichment_for_code and (is_code or is_structured_data or is_html):
            # Convert to EnrichedChunk without enrichment
            enriched_chunks = [
                EnrichedChunk(
                    chunk_id=c.chunk_id,
                    text=c.text,
                    start_char=c.start_char,
                    end_char=c.end_char,
                    metadata=c.metadata,
                    keywords=[],
                    section_name=c.metadata.get("section_name", "table" if is_structured_data else ("html" if is_html else "code")),
                    section_type=c.metadata.get("section_type", "table" if is_structured_data else ("html" if is_html else "code"))
                )
                for c in chunks
            ]
        else:
            # Apply enrichment
            enriched_chunks = self._enrich_chunks(chunks)

        # Step 4: Format
        processed_doc = ProcessedDocument(
            document_id=doc_id or Path(file_path).stem,
            source=file_path,
            doc_type=extension[1:],  # Remove leading dot
            chunks=enriched_chunks,
            metadata=raw_doc.metadata
        )

        return self.formatter.format(processed_doc)

    def _enrich_chunks(self, chunks: list[Chunk]) -> list[EnrichedChunk]:
        """
        Apply enrichment to chunks.

        Args:
            chunks: List of chunks

        Returns:
            List of enriched chunks
        """
        enriched = chunks

        for enricher in self.enrichers:
            enriched = enricher.enrich(enriched)

        return enriched

    def get_supported_formats(self) -> list[str]:
        """
        Get list of supported file formats.

        Returns:
            List of file extensions
        """
        return list(self.EXTRACTORS.keys())

    def is_supported(self, file_path: str) -> bool:
        """
        Check if file format is supported.

        Args:
            file_path: Path to file

        Returns:
            True if supported
        """
        extension = Path(file_path).suffix.lower()
        return extension in self.EXTRACTORS
