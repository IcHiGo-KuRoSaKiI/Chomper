"""
Data models for document parsing pipeline.

These models represent documents at different stages:
- RawDocument: After extraction
- Chunk: After chunking
- EnrichedChunk: After enrichment
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawDocument:
    """
    Raw document after extraction.

    Represents the complete document with all extracted content
    before chunking and enrichment.
    """
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] | None = None  # Pages, sections, etc.

    def __post_init__(self):
        """Validate raw document."""
        if not self.text:
            raise ValueError("RawDocument must have text content")


@dataclass
class Chunk:
    """
    Document chunk after intelligent splitting.

    Represents a semantically meaningful piece of the document.
    """
    chunk_id: int
    text: str
    start_char: int = 0
    end_char: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate and compute defaults."""
        if not self.text:
            raise ValueError("Chunk must have text content")

        # Auto-compute char positions if not set
        if self.end_char == 0:
            self.end_char = self.start_char + len(self.text)

    @property
    def word_count(self) -> int:
        """Count words in chunk."""
        return len(self.text.split())

    @property
    def char_count(self) -> int:
        """Count characters in chunk."""
        return len(self.text)


@dataclass
class EnrichedChunk(Chunk):
    """
    Chunk with added enrichment metadata.

    Extends Chunk with computed metadata like keywords,
    section names, and other analysis results.
    """
    keywords: list[str] = field(default_factory=list)
    section_name: str | None = None
    section_type: str = "text"  # "text", "code", "image", "table"
    computed_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_keywords(self) -> bool:
        """Check if keywords were extracted."""
        return len(self.keywords) > 0

    @property
    def has_section_name(self) -> bool:
        """Check if section name was generated."""
        return self.section_name is not None


@dataclass
class ProcessedDocument:
    """
    Final processed document with all chunks and metadata.

    This is the output of the full pipeline.
    """
    document_id: str
    source: str
    doc_type: str
    chunks: list[EnrichedChunk]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_chunks(self) -> int:
        """Total number of chunks."""
        return len(self.chunks)

    @property
    def total_words(self) -> int:
        """Total word count across all chunks."""
        return sum(chunk.word_count for chunk in self.chunks)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "document_id": self.document_id,
            "source": self.source,
            "doc_type": self.doc_type,
            "total_chunks": self.total_chunks,
            "total_words": self.total_words,
            "metadata": self.metadata,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "keywords": chunk.keywords,
                    "section_name": chunk.section_name,
                    "section_type": chunk.section_type,
                    "metadata": chunk.metadata,
                    "computed_metadata": chunk.computed_metadata
                }
                for chunk in self.chunks
            ]
        }
