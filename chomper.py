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
import binascii
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
    "is_supported",
    "get_format",
    "clear_cache",
]

#: Whether ``chunk()`` attaches TF-IDF keywords unless told otherwise.
KEYWORDS_BY_DEFAULT = False


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


def _validate_path(file_path: str | Path) -> Path:
    """Validate and resolve a file path."""
    from src.server.documents import validate_path

    try:
        return validate_path(file_path)
    except ValueError as e:
        raise ChomperError(str(e)) from e


def _load(path: Path, *, use_cache: bool = True) -> Any:
    """Extract ``path`` through the shared document cache."""
    from src.server.cache import cached_extract
    from src.server.documents import extractor_class_for

    try:
        extractor_cls = extractor_class_for(path)
    except ValueError as e:
        raise ChomperError(str(e)) from e
    # Extraction errors propagate unchanged, as they always have.
    return cached_extract(path, extractor_cls, use_cache=use_cache)


def _collect_images(raw_doc: Any) -> list[dict[str, Any]]:
    """Gather image records from a RawDocument, however the extractor nested them.

    Extractors are inconsistent: some advertise a top-level ``structure["images"]``,
    others (PDF, PPTX, DOCX) nest image items inside per-page, per-slide or
    per-section ``content`` lists. This delegates to the one shared walker every
    entry point uses. Identical images are returned once, with ``pages`` listing
    where they appear.
    """
    from src.extractors.image_utils import collect_images

    return collect_images(getattr(raw_doc, "structure", None))


def _decode_content(content: bytes | str) -> bytes:
    """Raw bytes from bytes or base64 text, enforcing the input size cap."""
    from src.server.config import MAX_BYTES_INPUT

    if isinstance(content, str):
        if len(content) > MAX_BYTES_INPUT * 4 // 3 + 4:
            raise ChomperError(
                f"Content is larger than the {MAX_BYTES_INPUT // (1024 * 1024)} MB limit. "
                "Save it to a file and call chomper.parse(path) instead."
            )
        try:
            content_bytes = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ChomperError(
                f"Invalid base64 content: {e}. Pass raw bytes, or standard base64 text."
            ) from e
    else:
        content_bytes = content
    if len(content_bytes) > MAX_BYTES_INPUT:
        raise ChomperError(
            f"Content is {len(content_bytes)} bytes, over the "
            f"{MAX_BYTES_INPUT // (1024 * 1024)} MB limit. "
            "Save it to a file and call chomper.parse(path) instead."
        )
    return content_bytes


def _parse_path(
    path: Path,
    *,
    include_images: bool,
    max_chars: int | None,
    use_cache: bool,
) -> ParseResult:
    raw_doc = _load(path, use_cache=use_cache)
    text = raw_doc.text or ""

    if max_chars is not None and max_chars >= 0 and len(text) > max_chars:
        text = text[:max_chars]

    metadata = dict(raw_doc.metadata) if raw_doc.metadata else {}

    return ParseResult(
        text=text,
        metadata=metadata,
        file_path=str(path),
        format=path.suffix.lower().lstrip('.'),
        word_count=len(text.split()),
        char_count=len(text),
        images=_collect_images(raw_doc) if include_images else [],
    )


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

    Repeated calls on an unchanged file reuse a cached extraction (see
    ``CHOMPER_CACHE_SIZE`` / ``CHOMPER_DISABLE_CACHE``).

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
    return _parse_path(path, include_images=include_images, max_chars=max_chars, use_cache=True)


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

    Content is capped at 100 MB; the temporary file is never cached.

    Args:
        content: Raw bytes or base64-encoded string.
        filename: Filename with extension (e.g., "report.pdf").
        include_images: Whether to extract image information.
        max_chars: Maximum characters to return (None = all).

    Returns:
        ParseResult with text, metadata, and document info.

    Raises:
        ChomperError: If format not supported, content invalid or too large.

    Example:
        >>> result = chomper.parse_bytes(base64_content, "document.pdf")
        >>> with open("doc.pdf", "rb") as f:
        ...     result = chomper.parse_bytes(f.read(), "doc.pdf")
    """
    ext = Path(filename).suffix.lower()
    if not ext:
        raise ChomperError(
            f"Filename must have an extension for format detection: {filename!r} "
            "(e.g. 'report.pdf')."
        )
    if not is_supported(filename):
        from src.server.config import EXTRACTORS

        raise ChomperError(EXTRACTORS.unavailable_reason(ext) or f"Unsupported format: {ext}")

    content_bytes = _decode_content(content)

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = Path(tmp.name)

    try:
        result = _parse_path(
            tmp_path.resolve(), include_images=include_images, max_chars=max_chars,
            use_cache=False,
        )
        result.file_path = filename
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


def chunk(
    file_path: str | Path,
    *,
    strategy: Literal["auto", "semantic", "fixed", "recursive"] = "auto",
    chunk_size: int = 1000,
    overlap: int = 100,
    embedding_model: Literal["fast", "balanced"] = "fast",
    keywords: bool = KEYWORDS_BY_DEFAULT,
) -> list[ChunkResult]:
    """
    Split a document into chunks for RAG/embedding systems.

    Chunk text keeps the document's line breaks, lists, tables and code blocks.
    Uses the same chunkers, defaults and strategy names as the CLI and the MCP
    ``parse_document_chunked`` tool.

    Args:
        file_path: Path to the document file.
        strategy: Chunking strategy:
            - "auto": Format-aware (PDF structure, headings, code by function)
            - "recursive": Structure-aware text (headings > paragraphs > lines >
              sentences; never inside a code fence or table row)
            - "fixed": Fixed word windows that only break between lines
            - "semantic": Embedding-based breakpoints (best for RAG)
        chunk_size: Maximum words per chunk (default: 1000).
        overlap: Words to overlap between chunks (default: 100).
        embedding_model: For semantic strategy:
            - "fast": all-MiniLM-L6-v2 (~80MB, faster)
            - "balanced": all-mpnet-base-v2 (~420MB, better quality)
        keywords: Attach TF-IDF keywords to each chunk.

    Returns:
        List of ChunkResult objects.

    Raises:
        ChomperError: If file not found, format not supported or options invalid.

    Example:
        >>> chunks = chomper.chunk("/path/to/report.pdf")
        >>> for c in chunks:
        ...     store(embed(c.text), c.keywords, c.section_name)
    """
    from src.server.documents import chunk_document, keywords_of, section_name_of

    path = _validate_path(file_path)
    try:
        outcome = chunk_document(
            path,
            strategy=strategy,
            chunk_size=chunk_size,
            overlap=overlap,
            embedding_model=embedding_model,
            keywords=keywords,
        )
    except ValueError as e:
        raise ChomperError(str(e)) from e

    results = []
    for i, c in enumerate(outcome.chunks):
        chunk_text = c.text if isinstance(getattr(c, "text", None), str) else str(c)
        metadata = dict(getattr(c, "metadata", None) or {})
        results.append(ChunkResult(
            text=chunk_text,
            chunk_id=i,
            start_char=getattr(c, 'start_char', 0),
            end_char=getattr(c, 'end_char', len(chunk_text)),
            word_count=len(chunk_text.split()),
            keywords=keywords_of(c),
            section_name=section_name_of(c),
            metadata=metadata,
        ))

    return results


def extract_metadata(file_path: str | Path) -> MetadataResult:
    """
    Quick metadata extraction.

    Reuses a cached extraction when the same unchanged file was parsed before.

    Args:
        file_path: Path to the document file.

    Returns:
        MetadataResult with file and document metadata.

    Raises:
        ChomperError: If file not found or format not supported.

    Example:
        >>> meta = chomper.extract_metadata("/path/to/report.pdf")
        >>> print(meta.title, meta.author, meta.page_count, meta.file_size)
    """
    from src.extractors.image_utils import count_images

    path = _validate_path(file_path)
    raw_doc = _load(path)

    metadata = dict(raw_doc.metadata) if raw_doc.metadata else {}
    text = raw_doc.text or ""

    page_count = metadata.get('page_count')
    if page_count is None and raw_doc.structure and isinstance(
        raw_doc.structure.get("pages"), list
    ):
        page_count = len(raw_doc.structure["pages"])

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
        page_count=page_count,
        created=metadata.get('created'),
        modified=metadata.get('modified'),
        text_length=len(text),
        word_count=len(text.split()),
        image_count=count_images(getattr(raw_doc, "structure", None)),
    )


def list_formats() -> dict[str, dict[str, Any]]:
    """
    List all supported file formats.

    Returns:
        Dictionary of format extension to info dict containing:
        - description: Human-readable description
        - available: Whether dependencies are installed
        - reason: Why unavailable (if applicable), with the install command

    Example:
        >>> formats = chomper.list_formats()
        >>> [ext for ext, info in formats.items() if info['available']]
    """
    from src.server.config import describe_formats

    return {
        f["extension"]: {
            "description": f["description"],
            "available": f["available"],
            "reason": f["reason"],
        }
        for f in describe_formats()
    }


def clear_cache() -> None:
    """Drop every cached extraction (e.g. after rewriting many files in place)."""
    from src.server.cache import clear_caches

    clear_caches()


# =============================================================================
# Convenience Functions
# =============================================================================


def is_supported(file_path: str | Path) -> bool:
    """
    Check if a file format is supported (and its dependencies are installed).

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
    from src.server.config import EXTRACTORS

    return Path(file_path).suffix.lower() in EXTRACTORS


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
    """
    ext = Path(file_path).suffix.lower()
    if is_supported(file_path):
        return ext.lstrip('.')
    return None
