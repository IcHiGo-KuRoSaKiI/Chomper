"""
Markdown chunker with heading-aware structure preservation.

Chunks Markdown while preserving:
- Heading hierarchy (every heading starts a new chunk)
- Code fences (never split) and table rows (never split)
- Lists and line breaks (chunk text is an exact substring of the document)
"""

from __future__ import annotations

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker
from ..text_splitter import HeadingIndex, section_spans


class MarkdownChunker(BaseChunker):
    """
    Chunk Markdown documents preserving structure.

    Strategy:
    - Every heading starts a new chunk; a heading stays with the text under it
    - Sections larger than ``target_size`` words are split at blank lines, then
      lines, then sentences, never inside a code fence or table row
    - ``section_name`` / ``heading_path`` metadata name the enclosing section
    """

    def __init__(
        self,
        target_size: int = 400,
        overlap: int = 50,
        preserve_context: bool = True,
        chunk_by_section: bool = False,
        section_level: int = 6,
    ):
        """
        Initialize Markdown chunker.

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
        Chunk Markdown document.

        Args:
            raw_doc: Raw Markdown document

        Returns:
            List of chunks; ``chunk.text == raw_doc.text[chunk.start_char:chunk.end_char]``
        """
        text = raw_doc.text or ""
        if not text.strip():
            return []
        if self.chunk_by_section:
            return self._section_chunks(text)
        return self._chunks_from_text(
            text, section_level=self.section_level, strategy="markdown"
        )

    def _section_chunks(self, text: str) -> list[Chunk]:
        """One chunk per heading-bounded section."""
        index = HeadingIndex(text)
        chunks: list[Chunk] = []
        for start, end, _heading in section_spans(text, self.section_level):
            heading, path = index.for_span(text, start, end)
            body = text[start:end]
            chunks.append(
                Chunk(
                    chunk_id=len(chunks),
                    text=body,
                    start_char=start,
                    end_char=end,
                    metadata={
                        "section_name": heading.title if heading else None,
                        "heading_path": " > ".join(path),
                        "heading_level": heading.level if heading else 0,
                        "has_code": "```" in body or "~~~" in body,
                        "has_images": "](image:" in body,
                        "section_type": "text",
                        "chunk_strategy": "section",
                    },
                )
            )
        return chunks
