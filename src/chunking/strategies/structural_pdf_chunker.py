"""Structural PDF chunker.

Replaces the word-count slicing of :class:`~src.chunking.strategies.pdf_chunker.PDFChunker`
with heading-bounded, table-safe, sentence-safe chunking, and stamps the provenance
metadata required by the structural parsing work.

The difference in one line: ``PDFChunker`` asks "have I collected 400 words yet?",
whereas this asks "where does the document say a section ends?" and only falls back to
size when a section is genuinely too large.

Because :class:`~src.chunking.base.BaseChunker` receives an already-extracted
``RawDocument`` and the typographic signals needed for heading detection are not in it,
this chunker re-opens the source PDF when a path is available. It degrades to the
markdown text in ``RawDocument`` when it is not, so it never hard-fails.
"""

from __future__ import annotations

import logging
import re

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


class StructuralPDFChunker(BaseChunker):
    """Chunk PDFs on structural boundaries rather than word count.

    Args:
        target_size: soft ceiling in words before a section is subdivided.
        overlap: retained for interface compatibility. Defaults to 0 because
            duplicating content across assets is wrong for an authored knowledge
            model, even though it can help naive retrieval.
        preserve_context: keep the heading breadcrumb on every chunk.
        split_at_h3: break at H3 as well as H1/H2.
        soft_min_words: below this, a trailing chunk merges backwards.
        enable_noise_filter: strip running headers, footers and boilerplate.
        source_folder: provenance value, e.g. ``"manuals/reference"``.
        tier_gap: override the heading size-tier clustering gap, in points.
    """

    def __init__(
        self,
        target_size: int = 600,
        overlap: int = 0,
        preserve_context: bool = True,
        *,
        split_at_h3: bool = False,
        soft_min_words: int = 40,
        enable_noise_filter: bool = True,
        source_folder: str = "",
        tier_gap: float | None = None,
    ) -> None:
        super().__init__(target_size, overlap, preserve_context)
        self.split_at_h3 = split_at_h3
        self.soft_min_words = soft_min_words
        self.enable_noise_filter = enable_noise_filter
        self.source_folder = source_folder
        self.tier_gap = tier_gap
        #: Populated after :meth:`chunk` so callers can inspect diagnostics.
        self.last_result = None

    # ------------------------------------------------------------------ public
    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """Chunk a PDF document on structural boundaries."""
        source = self._source_path(raw_doc)

        if source:
            try:
                return self._chunk_from_pdf(source, raw_doc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Structural parse of %s failed (%s); "
                    "falling back to markdown chunking.", source, exc
                )

        return self._chunk_from_markdown(raw_doc)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _source_path(raw_doc: RawDocument) -> str | None:
        meta = raw_doc.metadata or {}
        for key in ("file_path", "source", "path"):
            value = meta.get(key)
            if value and str(value).lower().endswith(".pdf"):
                return str(value)
        return None

    def _chunk_from_pdf(self, source: str, raw_doc: RawDocument) -> list[Chunk]:
        from ...pdf_structure import parse_structure

        result = parse_structure(
            source,
            source_folder=self.source_folder,
            max_words=self.target_size,
            soft_min_words=self.soft_min_words,
            split_at_h3=self.split_at_h3,
            enable_noise_filter=self.enable_noise_filter,
            tier_gap=self.tier_gap,
        )
        self.last_result = result

        filename = (raw_doc.metadata or {}).get("filename") or result.source_pdf_filename

        chunks: list[Chunk] = []
        cursor = 0
        for block in result.blocks:
            text = block.text
            if self.preserve_context and block.heading_path:
                body = text
                if not body.lstrip().startswith("#"):
                    text = f"{block.heading_path}\n\n{body}"

            metadata = block.to_metadata(
                source_pdf_filename=filename,
                source_folder=self.source_folder,
            )
            metadata["source_hash"] = _hash_text(block.text)

            chunks.append(
                self._create_chunk(
                    chunk_id=block.sequence_index,
                    text=text,
                    start_char=cursor,
                    end_char=cursor + len(text),
                    metadata=metadata,
                )
            )
            cursor += len(text)

        return chunks

    def _chunk_from_markdown(self, raw_doc: RawDocument) -> list[Chunk]:
        """Fallback: split the extracted markdown on its ``#`` headings.

        Weaker than the full parse -- no noise filtering and no font evidence --
        but it still respects headings, keeps tables whole and never splits
        mid-sentence, so the requirements that matter most still hold.
        """
        from ...pdf_structure.sentences import split_paragraphs
        from ...pdf_structure.tables import markdown_table_blocks

        pages = (raw_doc.structure or {}).get("pages") or []
        page_of_line: list[int] = []
        all_lines: list[str] = []
        for page in pages:
            text = page.get("markdown_text") or ""
            for line in text.splitlines():
                all_lines.append(line)
                page_of_line.append(int(page.get("page_number", 1)))
        if not all_lines:
            all_lines = (raw_doc.text or "").splitlines()
            page_of_line = [1] * len(all_lines)

        protected: set[int] = set()
        for start, end in markdown_table_blocks("\n".join(all_lines)):
            protected.update(range(start, end + 1))

        # Split into heading-bounded sections.
        sections: list[tuple[str | None, int, list[int]]] = []
        current_heading: str | None = None
        current_level = 0
        current: list[int] = []

        for index, line in enumerate(all_lines):
            match = _HEADING_RE.match(line) if index not in protected else None
            if match and len(match.group(1)) <= 2:
                if current:
                    sections.append((current_heading, current_level, current))
                current_heading = match.group(2).strip()
                current_level = len(match.group(1))
                current = [index]
                continue
            current.append(index)

        if current:
            sections.append((current_heading, current_level, current))

        chunks: list[Chunk] = []
        cursor = 0
        breadcrumb: list[str] = []

        for heading, level, indices in sections:
            if heading:
                breadcrumb = breadcrumb[: max(0, level - 1)] + [heading]
            path = " > ".join(breadcrumb)

            body = "\n".join(all_lines[i] for i in indices).strip()
            if not body:
                continue

            pages_in = [page_of_line[i] for i in indices] or [1]
            has_table = any(i in protected for i in indices)

            pieces = (
                [body]
                if len(body.split()) <= self.target_size or has_table
                else _paragraph_pieces(body, self.target_size, split_paragraphs)
            )

            for piece in pieces:
                metadata = {
                    "source_folder": self.source_folder,
                    "source_pdf_filename": (raw_doc.metadata or {}).get("filename", ""),
                    "page_number": min(pages_in),
                    "page_span": [min(pages_in), max(pages_in)],
                    "sequence_index": len(chunks),
                    "parent_heading_id": None,
                    "heading_path": path,
                    "heading_level": level or None,
                    "section_name": heading or "Introduction",
                    "content_kind": "table" if has_table else "prose",
                    "atomic": has_table,
                    "has_images": False,
                    "section_type": "table" if has_table else "text",
                    "chunk_strategy": "structural-markdown-fallback",
                    "source_hash": _hash_text(piece),
                }
                chunks.append(
                    self._create_chunk(
                        chunk_id=len(chunks),
                        text=piece,
                        start_char=cursor,
                        end_char=cursor + len(piece),
                        metadata=metadata,
                    )
                )
                cursor += len(piece)

        return chunks


def _paragraph_pieces(body: str, max_words: int, splitter) -> list[str]:
    paragraphs = splitter(body) or [body]
    pieces: list[str] = []
    buffer: list[str] = []
    words = 0
    for paragraph in paragraphs:
        n = len(paragraph.split())
        if buffer and words + n > max_words:
            pieces.append("\n\n".join(buffer))
            buffer, words = [], 0
        buffer.append(paragraph)
        words += n
    if buffer:
        pieces.append("\n\n".join(buffer))
    return pieces


def _hash_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
