"""
Chomper - Python Library for Document Parsing

Chomp through any document. A simple, powerful API for parsing 36+ file formats.

Basic Usage:
    >>> import chomper
    >>>
    >>> # Parse a document
    >>> result = chomper.parse("/path/to/document.pdf")
    >>> print(result.text)
    >>> print(result.metadata)
    >>>
    >>> # Parse from base64 (cloud storage, APIs, databases)
    >>> result = chomper.parse_bytes(base64_content, "document.pdf")
    >>>
    >>> # Chunk for RAG/embeddings
    >>> chunks = chomper.chunk("/path/to/document.pdf", strategy="semantic")
    >>> for chunk in chunks:
    ...     print(chunk.text, chunk.keywords)
    >>>
    >>> # Quick metadata extraction
    >>> meta = chomper.extract_metadata("/path/to/document.pdf")
    >>> print(meta.author, meta.page_count)

Supported Formats:
    - Documents: PDF, DOCX, PPTX, RTF
    - Spreadsheets: XLSX, CSV, TSV
    - Web: HTML, XML
    - Text: TXT, Markdown
    - Code: Python, JavaScript, TypeScript, Java, Go, Rust, C/C++, and more
    - Data: JSON, YAML
    - Email: EML, MSG
    - E-books: EPUB

For MCP server usage, see: https://github.com/IcHiGo-KuRoSaKiI/Chomper
"""

from __future__ import annotations

import base64
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__version__ = "1.0.0"
__all__ = [
    "parse",
    "parse_bytes",
    "chunk",
    "extract_metadata",
    "list_formats",
    "ParseResult",
    "ChunkResult",
    "MetadataResult",
    "ChomperError",
]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ParseResult:
    """Result from parsing a document."""

    text: str
    """Extracted text content."""

    metadata: dict[str, Any]
    """Document metadata (author, title, page_count, etc.)."""

    file_path: str
    """Path to the parsed file."""

    format: str
    """Detected file format (pdf, docx, etc.)."""

    word_count: int
    """Total word count."""

    char_count: int
    """Total character count."""

    images: list[dict[str, Any]] = field(default_factory=list)
    """List of image info (if extracted)."""

    def __repr__(self) -> str:
        return (
            f"ParseResult(format='{self.format}', "
            f"words={self.word_count}, chars={self.char_count})"
        )

    def summary(self, max_chars: int = 500) -> str:
        """Return a summary of the document content."""
        if len(self.text) <= max_chars:
            return self.text
        return self.text[:max_chars] + "..."


@dataclass
class ChunkResult:
    """A single chunk from document chunking."""

    text: str
    """Chunk text content."""

    chunk_id: int
    """Chunk index (0-based)."""

    start_char: int
    """Starting character position in original document."""

    end_char: int
    """Ending character position in original document."""

    word_count: int
    """Word count in this chunk."""

    keywords: list[str] = field(default_factory=list)
    """Extracted keywords for this chunk."""

    section_name: str | None = None
    """Detected section name (if any)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional chunk metadata."""

    def __repr__(self) -> str:
        return f"ChunkResult(id={self.chunk_id}, words={self.word_count})"


@dataclass
class MetadataResult:
    """Quick metadata extraction result."""

    file_path: str
    """Path to the file."""

    filename: str
    """Base filename."""

    format: str
    """File format (pdf, docx, etc.)."""

    file_size: int
    """File size in bytes."""

    # Document-specific metadata (may be None)
    author: str | None = None
    title: str | None = None
    subject: str | None = None
    creator: str | None = None
    producer: str | None = None
    page_count: int | None = None
    created: str | None = None
    modified: str | None = None

    # Computed info
    text_length: int | None = None
    word_count: int | None = None
    image_count: int | None = None

    def __repr__(self) -> str:
        return f"MetadataResult(filename='{self.filename}', format='{self.format}')"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            k: v for k, v in self.__dict__.items() if v is not None
        }


class ChomperError(Exception):
    """Base exception for Chomper errors."""

    pass


# =============================================================================
# Internal Helpers
# =============================================================================


def _get_extractor(file_path: Path):
    """Get the appropriate extractor for a file."""
    from src.server.config import EXTRACTORS

    ext = file_path.suffix.lower()
    extractor_class = EXTRACTORS.get(ext)

    if extractor_class is None:
        raise ChomperError(
            f"Unsupported file format: {ext}. "
            f"Use chomper.list_formats() to see supported formats."
        )

    return extractor_class()


def _get_chunker(file_path: Path, strategy: str):
    """Get the appropriate chunker for a file and strategy."""
    from src.server.config import CHUNKERS

    ext = file_path.suffix.lower()

    if strategy == "semantic":
        from src.chunking.strategies import SemanticChunker
        return SemanticChunker()
    elif strategy == "fixed":
        from src.chunking.strategies import TextChunker
        return TextChunker()
    elif strategy == "auto":
        chunker_class = CHUNKERS.get(ext)
        if chunker_class:
            return chunker_class()
        from src.chunking.strategies import TextChunker
        return TextChunker()
    else:
        raise ChomperError(f"Unknown chunking strategy: {strategy}")


def _validate_path(file_path: str | Path) -> Path:
    """Validate and resolve a file path."""
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise ChomperError(f"File not found: {path}")

    if not path.is_file():
        raise ChomperError(f"Not a file: {path}")

    return path


# =============================================================================
# Public API
# =============================================================================


def parse(
    file_path: str | Path,
    *,
    include_images: bool = False,
    max_chars: int | None = None,
) -> ParseResult:
    """
    Parse a document and extract text, metadata, and optionally images.

    Args:
        file_path: Path to the document file.
        include_images: Whether to extract image information.
        max_chars: Maximum characters to return (None = all).

    Returns:
        ParseResult with text, metadata, and document info.

    Raises:
        ChomperError: If file not found or format not supported.

    Example:
        >>> result = chomper.parse("/path/to/report.pdf")
        >>> print(result.text[:500])
        >>> print(f"Author: {result.metadata.get('author')}")
        >>> print(f"Pages: {result.metadata.get('page_count')}")
    """
    path = _validate_path(file_path)
    extractor = _get_extractor(path)

    # Extract content
    raw_doc = extractor.extract(str(path))

    # Get text
    text = raw_doc.text if hasattr(raw_doc, 'text') else str(raw_doc)
    if isinstance(text, dict):
        text = text.get('text', str(text))

    # Apply max_chars limit
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]

    # Build metadata
    metadata = {}
    if hasattr(raw_doc, 'metadata') and raw_doc.metadata:
        metadata = dict(raw_doc.metadata)

    # Calculate counts
    word_count = len(text.split())
    char_count = len(text)

    # Extract images info if requested
    images = []
    if include_images and hasattr(raw_doc, 'structure'):
        structure = raw_doc.structure or {}
        if 'images' in structure:
            images = structure['images']

    return ParseResult(
        text=text,
        metadata=metadata,
        file_path=str(path),
        format=path.suffix.lower().lstrip('.'),
        word_count=word_count,
        char_count=char_count,
        images=images,
    )


def parse_bytes(
    content: bytes | str,
    filename: str,
    *,
    include_images: bool = False,
    max_chars: int | None = None,
) -> ParseResult:
    """
    Parse a document from bytes or base64-encoded content.

    Perfect for documents from:
    - Cloud storage (S3, Azure Blob, GCS)
    - API responses
    - Database BLOBs
    - In-memory documents

    Args:
        content: Raw bytes or base64-encoded string.
        filename: Filename with extension (e.g., "report.pdf").
        include_images: Whether to extract image information.
        max_chars: Maximum characters to return (None = all).

    Returns:
        ParseResult with text, metadata, and document info.

    Raises:
        ChomperError: If format not supported or content invalid.

    Example:
        >>> # From base64 string
        >>> result = chomper.parse_bytes(base64_content, "document.pdf")
        >>>
        >>> # From raw bytes
        >>> with open("doc.pdf", "rb") as f:
        ...     result = chomper.parse_bytes(f.read(), "doc.pdf")
        >>>
        >>> # From S3
        >>> import boto3
        >>> s3 = boto3.client('s3')
        >>> obj = s3.get_object(Bucket='bucket', Key='doc.pdf')
        >>> result = chomper.parse_bytes(obj['Body'].read(), "doc.pdf")
    """
    # Decode if base64
    if isinstance(content, str):
        try:
            content_bytes = base64.b64decode(content)
        except Exception as e:
            raise ChomperError(f"Invalid base64 content: {e}") from e
    else:
        content_bytes = content

    # Get extension
    ext = Path(filename).suffix.lower()
    if not ext:
        raise ChomperError(f"Filename must have an extension: {filename}")

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = Path(tmp.name)

    try:
        result = parse(tmp_path, include_images=include_images, max_chars=max_chars)
        # Update file_path to show original filename
        result.file_path = filename
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


def chunk(
    file_path: str | Path,
    *,
    strategy: Literal["auto", "semantic", "fixed"] = "auto",
    chunk_size: int = 1000,
    overlap: int = 100,
    embedding_model: Literal["fast", "balanced"] = "fast",
) -> list[ChunkResult]:
    """
    Split a document into chunks for RAG/embedding systems.

    Args:
        file_path: Path to the document file.
        strategy: Chunking strategy:
            - "auto": Format-aware (PDF by page, code by function)
            - "semantic": Embedding-based breakpoints (best for RAG)
            - "fixed": Fixed word count
        chunk_size: Target words per chunk (default: 1000).
        overlap: Words to overlap between chunks (default: 100).
        embedding_model: For semantic strategy:
            - "fast": all-MiniLM-L6-v2 (~80MB, faster)
            - "balanced": all-mpnet-base-v2 (~420MB, better quality)

    Returns:
        List of ChunkResult objects.

    Raises:
        ChomperError: If file not found or format not supported.

    Example:
        >>> # Auto-detect best strategy for format
        >>> chunks = chomper.chunk("/path/to/report.pdf")
        >>>
        >>> # Semantic chunking for RAG
        >>> chunks = chomper.chunk(
        ...     "/path/to/report.pdf",
        ...     strategy="semantic",
        ...     chunk_size=500,
        ...     overlap=50
        ... )
        >>>
        >>> # Process chunks
        >>> for chunk in chunks:
        ...     embedding = embed(chunk.text)
        ...     store(embedding, chunk.keywords, chunk.section_name)
    """
    path = _validate_path(file_path)
    extractor = _get_extractor(path)

    # Extract content
    raw_doc = extractor.extract(str(path))
    text = raw_doc.text if hasattr(raw_doc, 'text') else str(raw_doc)
    if isinstance(text, dict):
        text = text.get('text', str(text))

    # Get chunker
    if strategy == "semantic":
        from src.chunking.strategies import SemanticChunker
        chunker = SemanticChunker(
            target_size=chunk_size,
            overlap=overlap,
            model=embedding_model,
        )
    else:
        chunker = _get_chunker(path, strategy)
        if hasattr(chunker, 'target_size'):
            chunker.target_size = chunk_size
        if hasattr(chunker, 'overlap'):
            chunker.overlap = overlap

    # Chunk the document
    chunks = chunker.chunk(raw_doc)

    # Convert to ChunkResult objects
    results = []
    for i, c in enumerate(chunks):
        # Try 'text' first (src/models/document.py Chunk), then 'content' for compatibility
        if hasattr(c, 'text') and isinstance(c.text, str):
            chunk_text = c.text
        elif hasattr(c, 'content') and isinstance(c.content, str):
            chunk_text = c.content
        else:
            chunk_text = str(c)

        results.append(ChunkResult(
            text=chunk_text,
            chunk_id=i,
            start_char=getattr(c, 'start_char', 0),
            end_char=getattr(c, 'end_char', len(chunk_text)),
            word_count=len(chunk_text.split()),
            keywords=getattr(c, 'keywords', []),
            section_name=getattr(c, 'section_name', None),
            metadata=getattr(c, 'metadata', {}),
        ))

    return results


def extract_metadata(file_path: str | Path) -> MetadataResult:
    """
    Quick metadata extraction without full document parsing.

    Useful for:
    - File indexing
    - Quick document previews
    - Filtering before full parsing

    Args:
        file_path: Path to the document file.

    Returns:
        MetadataResult with file and document metadata.

    Raises:
        ChomperError: If file not found or format not supported.

    Example:
        >>> meta = chomper.extract_metadata("/path/to/report.pdf")
        >>> print(f"Title: {meta.title}")
        >>> print(f"Author: {meta.author}")
        >>> print(f"Pages: {meta.page_count}")
        >>> print(f"Size: {meta.file_size} bytes")
    """
    path = _validate_path(file_path)
    extractor = _get_extractor(path)

    # Extract content for metadata
    raw_doc = extractor.extract(str(path))

    # Get metadata
    metadata = {}
    if hasattr(raw_doc, 'metadata') and raw_doc.metadata:
        metadata = dict(raw_doc.metadata)

    # Get text info
    text = raw_doc.text if hasattr(raw_doc, 'text') else str(raw_doc)
    if isinstance(text, dict):
        text = text.get('text', str(text))

    # Count images
    image_count = 0
    if hasattr(raw_doc, 'structure') and raw_doc.structure:
        images = raw_doc.structure.get('images', [])
        image_count = len(images) if isinstance(images, list) else 0

    return MetadataResult(
        file_path=str(path),
        filename=path.name,
        format=path.suffix.lower().lstrip('.'),
        file_size=path.stat().st_size,
        author=metadata.get('author'),
        title=metadata.get('title'),
        subject=metadata.get('subject'),
        creator=metadata.get('creator'),
        producer=metadata.get('producer'),
        page_count=metadata.get('page_count'),
        created=metadata.get('created'),
        modified=metadata.get('modified'),
        text_length=len(text),
        word_count=len(text.split()),
        image_count=image_count,
    )


def list_formats() -> dict[str, dict[str, Any]]:
    """
    List all supported file formats.

    Returns:
        Dictionary of format extension to info dict containing:
        - description: Human-readable description
        - available: Whether dependencies are installed
        - reason: Why unavailable (if applicable)

    Example:
        >>> formats = chomper.list_formats()
        >>> for ext, info in formats.items():
        ...     if info['available']:
        ...         print(f"{ext}: {info['description']}")
    """
    from src.server.config import EXTRACTORS, FORMAT_DESCRIPTIONS

    result = {}
    for ext, description in FORMAT_DESCRIPTIONS.items():
        available = ext in EXTRACTORS
        result[ext] = {
            "description": description,
            "available": available,
            "reason": None if available else "Missing optional dependency",
        }

    return result


# =============================================================================
# Convenience Functions
# =============================================================================


def is_supported(file_path: str | Path) -> bool:
    """
    Check if a file format is supported.

    Args:
        file_path: Path to file or just a filename with extension.

    Returns:
        True if the format is supported, False otherwise.

    Example:
        >>> chomper.is_supported("document.pdf")
        True
        >>> chomper.is_supported("unknown.xyz")
        False
    """
    ext = Path(file_path).suffix.lower()
    from src.server.config import EXTRACTORS
    return ext in EXTRACTORS


def get_format(file_path: str | Path) -> str | None:
    """
    Get the format name for a file.

    Args:
        file_path: Path to file.

    Returns:
        Format name (e.g., "pdf", "docx") or None if unsupported.

    Example:
        >>> chomper.get_format("report.pdf")
        'pdf'
        >>> chomper.get_format("document.docx")
        'docx'
    """
    ext = Path(file_path).suffix.lower()
    if is_supported(file_path):
        return ext.lstrip('.')
    return None
