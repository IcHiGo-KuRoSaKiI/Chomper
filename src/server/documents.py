"""One way to load and chunk documents, shared by the library, the CLI and MCP.

``chomper.parse``/``chunk``/``extract_metadata`` and every MCP handler go through
:func:`load_document` (cached extraction) and :func:`chunk_document` (one chunker
factory, one set of defaults and strategy names). Nothing here imports the MCP
SDK, so the library stays light.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cache import cached_extract, peek_document
from .config import (
    CHUNK_STRATEGIES,
    CHUNKERS,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_STRATEGY,
    DEFAULT_PDF_OCR,
    DEFAULT_PDF_TABLE_FORMAT,
    EXTRACTORS,
    PDF_OCR_MODES,
    PDF_TABLE_FORMATS,
    supported_extensions_hint,
)

logger = logging.getLogger("chomper")

EMBEDDING_MODELS: tuple[str, ...] = ("fast", "balanced")


def validate_path(file_path: str | Path | None) -> Path:
    """Resolve ``file_path`` and check it is an existing regular file.

    Raises:
        ValueError: with what was wrong and what to pass instead.
    """
    if not file_path:
        raise ValueError("file_path is required: pass an absolute path to a document file.")
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"File not found: {path}. Check the path and pass an absolute path.")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}. Pass the path of a single document, not a directory.")
    return path


def extractor_class_for(path: Path) -> type:
    """Extractor class for ``path``'s extension.

    Raises:
        ValueError: unsupported extension, or its optional dependency is missing.
    """
    ext = path.suffix.lower()
    if ext in EXTRACTORS:
        return EXTRACTORS[ext]
    reason = EXTRACTORS.unavailable_reason(ext)
    if ext in EXTRACTORS.known():
        raise ValueError(reason)
    raise ValueError(
        f"Unsupported file format: {ext or '(no extension)'}. "
        f"Supported formats: {supported_extensions_hint()}"
    )


#: Extractor options as passed to the extractor and stored in the cache key.
ExtractorOptions = tuple[tuple[str, Any], ...]


def validate_extract_options(ocr: str, table_format: str) -> None:
    """Raise ValueError with the accepted values for a bad ``ocr``/``table_format``."""
    if ocr not in PDF_OCR_MODES:
        raise ValueError(
            f"Unknown ocr mode: {ocr!r}. Use one of: {', '.join(PDF_OCR_MODES)} "
            "('auto' OCRs only pages without a text layer)."
        )
    if table_format not in PDF_TABLE_FORMATS:
        raise ValueError(
            f"Unknown table_format: {table_format!r}. Use one of: {', '.join(PDF_TABLE_FORMATS)}."
        )


def extractor_options(
    path: Path,
    *,
    ocr: str = DEFAULT_PDF_OCR,
    table_format: str = DEFAULT_PDF_TABLE_FORMAT,
) -> ExtractorOptions:
    """Validated extractor keyword arguments for ``path``, in cache-key form.

    Only PDFs take these options; other formats ignore them. Default values are
    left out, so an explicit ``ocr="auto"`` shares the cache entry of a call that
    did not pass it, while ``ocr="off"`` or ``table_format="html"`` get their own.

    Raises:
        ValueError: unknown ``ocr`` or ``table_format`` value.
    """
    validate_extract_options(ocr, table_format)
    if path.suffix.lower() != ".pdf":
        return ()
    options: list[tuple[str, Any]] = []
    if ocr != DEFAULT_PDF_OCR:
        options.append(("ocr", ocr))
    if table_format != DEFAULT_PDF_TABLE_FORMAT:
        options.append(("table_format", table_format))
    return tuple(options)


def load_document(
    path: Path,
    *,
    use_cache: bool = True,
    ocr: str = DEFAULT_PDF_OCR,
    table_format: str = DEFAULT_PDF_TABLE_FORMAT,
) -> Any:
    """Extract ``path`` into a RawDocument, reusing a cached extraction when the file
    is unchanged and the options match. The result is shared: treat it as read-only.

    Args:
        path: document to extract.
        use_cache: read and fill the shared document cache.
        ocr: PDFs only -- ``auto`` OCRs pages without a text layer (needs Tesseract
            or RapidOCR), ``off`` never OCRs, ``force`` OCRs every page.
        table_format: PDFs only -- ``markdown`` pipe tables or ``html`` tables.

    Raises:
        ValueError: unsupported format or invalid option.
    """
    options = extractor_options(path, ocr=ocr, table_format=table_format)
    return cached_extract(path, extractor_class_for(path), options, use_cache=use_cache)


def validate_chunk_options(
    strategy: str, chunk_size: int, overlap: int, embedding_model: str = "fast"
) -> None:
    """Raise ValueError with an actionable message for bad chunking options."""
    if strategy not in CHUNK_STRATEGIES:
        raise ValueError(
            f"Unknown chunking strategy: {strategy!r}. Use one of: {', '.join(CHUNK_STRATEGIES)}."
        )
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
        raise ValueError(f"chunk_size must be a positive integer (words), got {chunk_size!r}.")
    if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 0:
        raise ValueError(f"overlap must be 0 or a positive integer (words), got {overlap!r}.")
    if embedding_model not in EMBEDDING_MODELS:
        raise ValueError(
            f"Unknown embedding_model: {embedding_model!r}. Use one of: {', '.join(EMBEDDING_MODELS)}."
        )


def build_chunker(
    ext: str,
    strategy: str = DEFAULT_CHUNK_STRATEGY,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    embedding_model: str = "fast",
) -> Any:
    """The chunker for ``ext`` and ``strategy``, configured through its constructor.

    Strategies (identical in the library, the CLI and MCP):
        auto: format-aware chunker (PDF structure, DOCX/Markdown headings, code
            functions, spreadsheet sheets/tables), structure-aware text otherwise.
        recursive: structure-aware text splitting -- headings, then blank lines,
            then lines, then sentences; never inside a code fence or table row.
        fixed: fixed-size windows of ``chunk_size`` words that only break between
            lines (a single over-long line is split on sentences/words).
        semantic: embedding-based topic boundaries, ``chunk_size`` as a maximum.
        layout: PDFs only -- the layout-model Markdown that ``parse()`` returns, split
            on headings (hard cuts at levels 1-2), never inside a table or figure
            line, with page numbers; other formats get their ``auto`` chunker.
    """
    validate_chunk_options(strategy, chunk_size, overlap, embedding_model)
    if strategy == "layout" and ext == ".pdf":
        from ..chunking.strategies.layout_pdf_chunker import LayoutPDFChunker

        return LayoutPDFChunker(target_size=chunk_size, overlap=overlap)
    if strategy == "semantic":
        from ..chunking.strategies import SemanticChunker

        if SemanticChunker is None:
            raise ValueError(
                "Semantic chunking requires numpy and sentence-transformers. "
                "Install with: pip install 'chomper[semantic]'"
            )
        return SemanticChunker(target_size=chunk_size, overlap=overlap, model=embedding_model)

    from ..chunking.strategies.text_chunker import TextChunker

    if strategy == "fixed":
        return TextChunker(
            target_size=chunk_size, overlap=overlap, use_semantic=False, prefer_structure=False
        )
    if strategy == "recursive":
        return TextChunker(target_size=chunk_size, overlap=overlap, use_semantic=False)

    chunker_cls = CHUNKERS.get(ext)
    if chunker_cls is None:
        return TextChunker(target_size=chunk_size, overlap=overlap, use_semantic=False)
    return chunker_cls(target_size=chunk_size, overlap=overlap)


@dataclass
class ChunkingOutcome:
    """Chunks plus the RawDocument they came from (None when extraction was skipped)."""

    chunks: list[Any]
    raw_doc: Any | None
    #: Facts about the source when extraction was skipped (e.g. ``page_count``).
    document_info: dict[str, Any] = field(default_factory=dict)


def chunk_document(
    path: Path,
    *,
    strategy: str = DEFAULT_CHUNK_STRATEGY,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    embedding_model: str = "fast",
    keywords: bool = False,
    use_cache: bool = True,
    ocr: str = DEFAULT_PDF_OCR,
    table_format: str = DEFAULT_PDF_TABLE_FORMAT,
) -> ChunkingOutcome:
    """Chunk ``path`` with the shared factory.

    PDFs on the ``auto`` strategy are chunked straight from the file by the
    structural chunker, skipping the Markdown extraction pass it does not need
    (the extractor runs only if the structural parse fails). Every other strategy
    chunks the extracted text, so ``ocr`` and ``table_format`` apply to it, and it
    shares the cached extraction with ``parse()``.

    Raises:
        ValueError: unsupported format, bad option, or ``ocr``/``table_format``
            set for a PDF on the ``auto`` strategy (which does not extract text).
    """
    ext = path.suffix.lower()
    extractor_class_for(path)  # fail fast on unsupported formats
    options = extractor_options(path, ocr=ocr, table_format=table_format)
    chunker = build_chunker(ext, strategy, chunk_size, overlap, embedding_model)
    if options and hasattr(chunker, "chunk_path"):
        raise ValueError(
            "ocr and table_format apply to extracted PDF text, but the 'auto' strategy "
            "chunks PDFs with the structural chunker, which reads the file directly "
            "(no OCR, Markdown tables). Use strategy 'layout' to chunk the extracted text "
            f"with these options (got {dict(options)})."
        )

    chunks: list[Any] | None = None
    raw_doc: Any | None = None
    info: dict[str, Any] = {}
    if hasattr(chunker, "chunk_path"):
        try:
            chunks = chunker.chunk_path(str(path), path.name)
            result = getattr(chunker, "last_result", None)
            if result is not None:
                info["page_count"] = getattr(result, "page_count", None)
        except Exception as exc:  # any structural-parse failure falls back to extraction
            logger.warning("Structural parse of %s failed (%s); extracting instead.", path, exc)
        raw_doc = peek_document(path, extractor_class_for(path), options) if use_cache else None
    if chunks is None:
        raw_doc = load_document(path, use_cache=use_cache, ocr=ocr, table_format=table_format)
        chunks = chunker.chunk(raw_doc)

    if keywords:
        add_keywords(chunks)
    return ChunkingOutcome(chunks=chunks, raw_doc=raw_doc, document_info=info)


def section_name_of(chunk: Any) -> str | None:
    """Section name of a chunk, wherever the chunker recorded it."""
    name = getattr(chunk, "section_name", None)
    if name:
        return str(name)
    meta = getattr(chunk, "metadata", None) or {}
    for key in ("section_name", "section_heading", "slide_title", "heading", "sheet_name"):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def keywords_of(chunk: Any) -> list[str]:
    """Keywords attached to a chunk, if any."""
    value = getattr(chunk, "keywords", None)
    if value:
        return list(value)
    return list((getattr(chunk, "metadata", None) or {}).get("keywords", []))


def add_keywords(chunks: list[Any], top_k: int = 8) -> None:
    """Attach TF-IDF keywords (fitted across the document's chunks) to each chunk.

    Stored in ``chunk.metadata["keywords"]``.
    """
    from ..enrichment.keyword_extractor import KeywordExtractor

    texts = [getattr(c, "text", "") or "" for c in chunks]
    for chunk, words in zip(
        chunks, KeywordExtractor(method="tfidf", top_k=top_k).keywords_for_texts(texts),
        strict=True,
    ):
        chunk.metadata["keywords"] = words
