"""
HTML chunking strategies.

Provides 4 chunking strategies for HTML documents:
1. semantic: Chunk by semantic sections (article, section, nav, etc.)
2. structural: Chunk by heading hierarchy (h1-h6)
3. fixed_size: Size-bounded chunks (words) on paragraph/line boundaries
4. auto: Intelligent selection based on document structure
"""
from __future__ import annotations

import logging
from typing import Any

from ...models.document import Chunk, RawDocument
from ...models.html_models import HTMLDocument, HTMLTable
from ..base import BaseChunker
from ..text_splitter import split_spans

logger = logging.getLogger(__name__)


class HTMLChunker(BaseChunker):
    """
    Chunk HTML documents using intelligent strategies.

    Strategies:
    - semantic: one chunk per semantic HTML5 section (article, section, nav, ...),
      oversized sections split on structure
    - structural: heading-bounded chunks of the extracted text
    - fixed_size: size-bounded chunks of the extracted text on paragraph/line breaks
    - auto: pick one of the above from the document structure

    Sizes are in words, like every other chunker. Text chunks of the
    ``structural``/``fixed_size`` strategies are exact substrings of ``raw_doc.text``
    with true offsets; ``semantic`` chunks point into it when the section text is
    found there (``metadata["offsets"] == "text"``).
    """

    STRATEGIES = ("semantic", "structural", "fixed_size", "auto")

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        preserve_context: bool = True,
        *,
        strategy: str = "auto",
        include_tables_separately: bool = True,
        preserve_headings: bool = True,
        chunk_size: int | None = None,
        overlap_size: int | None = None,
    ):
        """
        Initialize HTML chunker.

        Args:
            target_size: Maximum words per chunk
            overlap: Words repeated from the previous chunk
            preserve_context: Maintain heading context
            strategy: "semantic", "structural", "fixed_size" or "auto"
            include_tables_separately: Also emit each table as its own HTML chunk
            preserve_headings: Prefix semantic-section chunks with their heading
            chunk_size: Deprecated character budget; converted to words (/6)
            overlap_size: Deprecated character overlap; converted to words (/6)
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}. Use one of {self.STRATEGIES}")
        if chunk_size is not None:
            target_size = max(1, chunk_size // 6)
        if overlap_size is not None:
            overlap = max(0, overlap_size // 6)
        super().__init__(target_size, overlap, preserve_context)
        self.strategy = strategy
        self.include_tables_separately = include_tables_separately
        self.preserve_headings = preserve_headings

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk HTML document using selected strategy.

        Args:
            raw_doc: RawDocument with HTML structure

        Returns:
            List of chunks
        """
        html_doc = (raw_doc.structure or {}).get('html_document')

        if not html_doc:
            logger.info("No HTML structure found, using structure-aware text chunking")
            return self._chunk_fixed_size(raw_doc.text, raw_doc.metadata)

        if self.strategy == "auto":
            selected_strategy = self._auto_select_strategy(html_doc)
            logger.debug(f"Auto-selected strategy: {selected_strategy}")
        else:
            selected_strategy = self.strategy

        if selected_strategy == "semantic":
            chunks = self._chunk_semantic(html_doc, raw_doc.metadata, raw_doc.text)
        elif selected_strategy == "structural":
            chunks = self._chunk_structural(raw_doc.text, html_doc, raw_doc.metadata)
        else:  # fixed_size
            chunks = self._chunk_fixed_size(raw_doc.text, raw_doc.metadata)

        if self.include_tables_separately and html_doc.tables:
            chunks.extend(self._chunk_tables(html_doc.tables, raw_doc.metadata, len(chunks)))

        return chunks

    def _auto_select_strategy(self, html_doc: HTMLDocument) -> str:
        """
        Automatically select best chunking strategy.

        Logic:
        - Has semantic sections (article, section) -> semantic
        - Has clear heading structure (5+ headings) -> structural
        - Otherwise -> fixed_size

        Args:
            html_doc: HTMLDocument object

        Returns:
            Selected strategy name
        """
        if html_doc.num_sections >= 3:
            semantic_tags = {'article', 'section', 'aside'}
            if any(section.tag in semantic_tags for section in html_doc.sections):
                return "semantic"

        if html_doc.num_headings >= 5:
            return "structural"

        return "fixed_size"

    def _chunk_semantic(
        self,
        html_doc: HTMLDocument,
        metadata: dict[str, Any],
        full_text: str = "",
    ) -> list[Chunk]:
        """
        Chunk by semantic HTML sections; oversized sections are split on structure.

        Args:
            html_doc: HTMLDocument object
            metadata: Document metadata
            full_text: Extracted document text, used to locate true offsets

        Returns:
            List of chunks
        """
        chunks: list[Chunk] = []
        cursor = 0

        for section in html_doc.sections:
            if section.is_empty:
                continue

            body = section.text
            if section.heading and self.preserve_headings and not body.lstrip().startswith(
                section.heading
            ):
                body = f"{section.heading}\n\n{body}"

            for s, e in split_spans(body, self.target_size, self.overlap):
                piece = body[s:e]
                found = full_text.find(piece, cursor) if full_text else -1
                if found == -1 and full_text:
                    found = full_text.find(piece)
                if found >= 0:
                    start_char, end_char, offsets = found, found + len(piece), "text"
                    cursor = found
                else:
                    start_char = section.start_char + s
                    end_char = start_char + len(piece)
                    offsets = "section"
                chunks.append(Chunk(
                    chunk_id=len(chunks),
                    text=piece,
                    start_char=start_char,
                    end_char=end_char,
                    metadata={
                        "chunk_strategy": "semantic",
                        "section_name": section.heading,
                        "section_tag": section.tag,
                        "section_heading": section.heading,
                        "heading_level": section.heading_level,
                        "section_index": section.section_index,
                        "has_subsections": section.has_subsections,
                        "section_type": "text",
                        "offsets": offsets,
                    }
                ))

        return chunks

    def _chunk_structural(
        self,
        full_text: str,
        html_doc: HTMLDocument,
        metadata: dict[str, Any]
    ) -> list[Chunk]:
        """
        Chunk by heading hierarchy: every Markdown-style heading starts a chunk.

        Args:
            full_text: Full document text (``raw_doc.text``)
            html_doc: HTMLDocument object
            metadata: Document metadata

        Returns:
            List of chunks (exact substrings of ``full_text``)
        """
        return self._chunks_from_text(full_text, section_level=6, strategy="structural")

    def _chunk_fixed_size(
        self,
        text: str,
        metadata: dict[str, Any]
    ) -> list[Chunk]:
        """
        Size-bounded chunks on paragraph, line and sentence boundaries.

        Args:
            text: Document text
            metadata: Document metadata

        Returns:
            List of chunks (exact substrings of ``text``)
        """
        if not (text or "").strip():
            return []
        return self._chunks_from_text(text, section_level=0, strategy="fixed_size")

    def _chunk_tables(
        self,
        tables: list[HTMLTable],
        metadata: dict[str, Any],
        start_id: int = 0,
    ) -> list[Chunk]:
        """
        Extract tables as separate chunks.

        Converts tables to HTML format for better LLM understanding.

        Args:
            tables: List of HTMLTable objects
            metadata: Document metadata

        Returns:
            List of table chunks
        """
        chunks: list[Chunk] = []

        for table in tables:
            # Convert table to HTML
            table_html = table.to_html()

            chunk = Chunk(
                chunk_id=start_id + len(chunks),
                text=table_html,
                start_char=0,
                end_char=len(table_html),
                metadata={
                    "chunk_strategy": "table",
                    "section_type": "table",
                    "offsets": "none",
                    "chunk_type": "table",
                    "table_index": table.table_index,
                    "table_caption": table.caption,
                    "num_rows": table.num_rows,
                    "num_cols": table.num_cols,
                    "has_headers": table.has_headers
                }
            )
            chunks.append(chunk)

        return chunks
