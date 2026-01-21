"""
Document processing pipeline.

Orchestrates the full document processing workflow:
Extraction → Chunking → Enrichment → Formatting
"""
from typing import Optional, List, Any
from pathlib import Path

from .models.document import RawDocument, Chunk, EnrichedChunk, ProcessedDocument
from .extractors import (
    PDFExtractor,
    DOCXExtractor,
    PPTXExtractor,
    CodeExtractor,
    TextExtractor,
    MarkdownExtractor,
    ExcelExtractor,
    CSVExtractor,
    HTMLExtractor
)
from .chunking.strategies import (
    PDFChunker,
    DOCXChunker,
    PPTXChunker,
    CodeChunker,
    TextChunker,
    MarkdownChunker,
    ExcelChunker,
    HTMLChunker
)
from .enrichment import (
    KeywordExtractor,
    SectionDetector,
    TitleGenerator,
    MetadataEnricher
)
from .formatters import (
    SimpleFormatter,
    WeaviateFormatter,
    Neo4jFormatter
)


class DocumentPipeline:
    """
    Main document processing pipeline.

    Orchestrates the complete workflow from file to formatted output.

    Usage:
        pipeline = DocumentPipeline()
        result = pipeline.process("document.pdf")

        # With custom configuration
        pipeline = DocumentPipeline(
            enrichers=[KeywordExtractor(), TitleGenerator()],
            formatter=WeaviateFormatter()
        )
    """

    # Build format mappings dynamically (only include available extractors)
    @staticmethod
    def _build_extractors():
        """Build extractor mapping with only available extractors."""
        extractors = {}

        # Always available (no heavy dependencies)
        extractors.update({
            '.py': CodeExtractor,
            '.js': CodeExtractor,
            '.jsx': CodeExtractor,
            '.ts': CodeExtractor,
            '.tsx': CodeExtractor,
            '.java': CodeExtractor,
            '.cpp': CodeExtractor,
            '.c': CodeExtractor,
            '.go': CodeExtractor,
            '.rs': CodeExtractor,
            '.txt': TextExtractor,
            '.text': TextExtractor,
            '.log': TextExtractor,
            '.md': MarkdownExtractor,
            '.markdown': MarkdownExtractor
        })

        # Optional (require heavy dependencies)
        if PDFExtractor is not None:
            extractors['.pdf'] = PDFExtractor
        if DOCXExtractor is not None:
            extractors['.docx'] = DOCXExtractor
            extractors['.doc'] = DOCXExtractor
        if PPTXExtractor is not None:
            extractors['.pptx'] = PPTXExtractor
            extractors['.ppt'] = PPTXExtractor
        if ExcelExtractor is not None:
            extractors['.xlsx'] = ExcelExtractor
            extractors['.xlsm'] = ExcelExtractor
            extractors['.xltx'] = ExcelExtractor
            extractors['.xltm'] = ExcelExtractor
        if CSVExtractor is not None:
            extractors['.csv'] = CSVExtractor
            extractors['.tsv'] = CSVExtractor
        if HTMLExtractor is not None:
            extractors['.html'] = HTMLExtractor
            extractors['.htm'] = HTMLExtractor

        return extractors

    @staticmethod
    def _build_chunkers():
        """Build chunker mapping with only available chunkers."""
        chunkers = {}

        # Always available
        chunkers.update({
            '.py': CodeChunker,
            '.js': CodeChunker,
            '.jsx': CodeChunker,
            '.ts': CodeChunker,
            '.tsx': CodeChunker,
            '.java': CodeChunker,
            '.cpp': CodeChunker,
            '.c': CodeChunker,
            '.go': CodeChunker,
            '.rs': CodeChunker,
            '.txt': TextChunker,
            '.text': TextChunker,
            '.log': TextChunker,
            '.md': MarkdownChunker,
            '.markdown': MarkdownChunker
        })

        # Optional
        if PDFExtractor is not None:
            chunkers['.pdf'] = PDFChunker
        if DOCXExtractor is not None:
            chunkers['.docx'] = DOCXChunker
            chunkers['.doc'] = DOCXChunker
        if PPTXExtractor is not None:
            chunkers['.pptx'] = PPTXChunker
            chunkers['.ppt'] = PPTXChunker
        if ExcelExtractor is not None:
            chunkers['.xlsx'] = ExcelChunker
            chunkers['.xlsm'] = ExcelChunker
            chunkers['.xltx'] = ExcelChunker
            chunkers['.xltm'] = ExcelChunker
        if CSVExtractor is not None:
            chunkers['.csv'] = ExcelChunker  # Use ExcelChunker for CSV too
            chunkers['.tsv'] = ExcelChunker
        if HTMLExtractor is not None:
            chunkers['.html'] = HTMLChunker
            chunkers['.htm'] = HTMLChunker

        return chunkers

    EXTRACTORS = None  # Will be built on first use
    CHUNKERS = None  # Will be built on first use

    def __init__(
        self,
        enrichers: Optional[List[Any]] = None,
        formatter: Optional[Any] = None,
        skip_enrichment_for_code: bool = True
    ):
        """
        Initialize pipeline.

        Args:
            enrichers: List of enricher instances (default: all enrichers)
            formatter: Formatter instance (default: SimpleFormatter)
            skip_enrichment_for_code: Skip enrichment for code files (default: True)
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

        # Build extractors/chunkers on first use
        if DocumentPipeline.EXTRACTORS is None:
            DocumentPipeline.EXTRACTORS = DocumentPipeline._build_extractors()
        if DocumentPipeline.CHUNKERS is None:
            DocumentPipeline.CHUNKERS = DocumentPipeline._build_chunkers()

    def process(self, file_path: str, doc_id: Optional[str] = None) -> Any:
        """
        Process a document through the full pipeline.

        Args:
            file_path: Path to document
            doc_id: Optional document ID

        Returns:
            Formatted output (depends on formatter)
        """
        # Detect format
        extension = Path(file_path).suffix.lower()

        if extension not in self.EXTRACTORS:
            raise ValueError(f"Unsupported file format: {extension}")

        # Step 1: Extract
        extractor_class = self.EXTRACTORS[extension]
        extractor = extractor_class()
        raw_doc = extractor.extract(file_path)

        # Step 2: Chunk
        chunker_class = self.CHUNKERS[extension]
        chunker = chunker_class()
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

    def _enrich_chunks(self, chunks: List[Chunk]) -> List[EnrichedChunk]:
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

    def get_supported_formats(self) -> List[str]:
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
