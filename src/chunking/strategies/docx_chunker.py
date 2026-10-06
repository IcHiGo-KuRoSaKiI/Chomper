"""
DOCX chunker with heading-aware structure preservation.

Chunks DOCX documents while preserving:
- Heading hierarchy (a top-level heading always starts a new chunk)
- Tables, lists and image markers in place (chunk text is an exact substring)
"""

from __future__ import annotations

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker
from .markdown_chunker import MarkdownChunker


class DOCXChunker(BaseChunker):
    """
    Chunk DOCX documents preserving heading structure.

    The DOCX extractor renders headings as Markdown (``# Title``) and tables as
    Markdown tables, so this chunks that text: top-level headings (``level <=
    section_level``) always start a new chunk, sub-headings are preferred cut points,
    and tables are only ever cut between rows.
    """

    def __init__(
        self,
        target_size: int = 500,
        overlap: int = 50,
        preserve_context: bool = True,
        chunk_by_section: bool = False,
        section_level: int = 1,
    ):
        """
        Initialize DOCX chunker.

        Args:
            target_size: Maximum words per chunk
            overlap: Words repeated from the previous chunk within a section
            preserve_context: Maintain heading context
            chunk_by_section: One chunk per section regardless of size
            section_level: Deepest heading level that forces a new chunk
        """
        super().__init__(target_size, overlap, preserve_context)
        self.chunk_by_section = chunk_by_section
        self.section_level = section_level

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk DOCX document.

        Args:
            raw_doc: Raw DOCX document

        Returns:
            List of chunks; ``chunk.text == raw_doc.text[chunk.start_char:chunk.end_char]``
        """
        text = raw_doc.text or ""
        if not text.strip():
            return []
        if self.chunk_by_section:
            md = MarkdownChunker(
                self.target_size, self.overlap, self.preserve_context,
                chunk_by_section=True, section_level=self.section_level,
            )
            return md.chunk(raw_doc)
        return self._chunks_from_text(
            text, section_level=self.section_level, strategy="docx"
        )
