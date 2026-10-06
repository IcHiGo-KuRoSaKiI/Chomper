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
    EXTRACTORS,
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


def load_document(path: Path, *, use_cache: bool = True) -> Any:
    """Extract ``path`` into a RawDocument, reusing a cached extraction when the file
    is unchanged. The result is shared: treat it as read-only.
    """
    return cached_extract(path, extractor_class_for(path), use_cache=use_cache)


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
    """
    validate_chunk_options(strategy, chunk_size, overlap, embedding_model)
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
) -> ChunkingOutcome:
    """Chunk ``path`` with the shared factory.

    PDFs on the ``auto`` strategy are chunked straight from the file by the
    structural chunker, skipping the Markdown extraction pass it does not need
    (the extractor runs only if the structural parse fails).
    """
    ext = path.suffix.lower()
    extractor_class_for(path)  # fail fast on unsupported formats
    chunker = build_chunker(ext, strategy, chunk_size, overlap, embedding_model)

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
        raw_doc = peek_document(path, extractor_class_for(path)) if use_cache else None
    if chunks is None:
        raw_doc = load_document(path, use_cache=use_cache)
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
