"""
Text chunker with structure-aware ("recursive") splitting.

Chunks plain text while preserving:
- Paragraph, line, list and table boundaries (chunk text is an exact substring)
- Sentence boundaries when a single line is too long
- Topic shifts (optional TextTiling-style valleys used as preferred cut points)
"""

from __future__ import annotations

import dataclasses

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker
from ..text_splitter import BLOCK, HEADING, Unit


class TextChunker(BaseChunker):
    """
    Chunk plain text with context awareness.

    Strategy (the ``recursive`` strategy everywhere in Chomper):
    - Cut at headings, then blank lines, then lines, then sentences; word windows
      only for a single sentence longer than the target
    - Never cut inside a fenced code block or a Markdown table row
    - ``target_size`` is a hard ceiling in words (an atomic code block or table row
      larger than it is kept whole)
    - With ``use_semantic``, paragraph boundaries where the vocabulary shifts are
      promoted to preferred cut points (TextTiling), still within the size limit
    """

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        preserve_context: bool = True,
        use_semantic: bool = True,
        prefer_structure: bool = True,
    ):
        """
        Initialize text chunker.

        Args:
            target_size: Maximum words per chunk
            overlap: Words repeated from the previous chunk (whole lines/sentences)
            preserve_context: Maintain context
            use_semantic: Prefer cutting at topic shifts between paragraphs
            prefer_structure: Cut at the strongest nearby boundary. False gives plain
                fixed-size windows that still only break between lines (``fixed``)
        """
        super().__init__(target_size, overlap, preserve_context)
        self.use_semantic = use_semantic
        self.prefer_structure = prefer_structure

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk text document.

        Args:
            raw_doc: Raw text document

        Returns:
            List of chunks; ``chunk.text == raw_doc.text[chunk.start_char:chunk.end_char]``
        """
        text = raw_doc.text or ""
        if not text.strip():
            return []
        if not self.prefer_structure:
            return self._chunks_from_text(
                text, strategy="fixed", prefer_structure=False, section_level=0
            )
        return self._chunks_from_text(
            text,
            section_level=0,
            strategy="semantic" if self.use_semantic else "recursive",
            adjust_units=self._promote_topic_shifts if self.use_semantic else None,
        )

    # ------------------------------------------------------------ TextTiling
    def _promote_topic_shifts(self, text: str, units: list[Unit]) -> list[Unit]:
        """Mark paragraph starts that follow a vocabulary valley as strong boundaries."""
        para_starts = [i for i, u in enumerate(units) if i == 0 or u.strength >= BLOCK]
        if len(para_starts) < 4:
            return units
        bounds = para_starts + [len(units)]
        paragraphs = [
            {"text": text[units[a].start:units[b - 1].end]}
            for a, b in zip(bounds, bounds[1:], strict=False)
        ]
        similarities = self._calculate_similarities(paragraphs)
        promoted = list(units)
        for boundary in self._find_boundaries(similarities):
            idx = para_starts[boundary]
            if promoted[idx].strength < HEADING:
                promoted[idx] = dataclasses.replace(promoted[idx], strength=HEADING)
        return promoted

    def _calculate_similarities(self, paragraphs: list[dict]) -> list[float]:
        """
        Calculate lexical (Jaccard) similarity between adjacent paragraphs.

        Args:
            paragraphs: List of paragraph dictionaries

        Returns:
            List of similarity scores
        """
        word_sets = [set(p["text"].lower().split()) for p in paragraphs]
        similarities = []
        for a, b in zip(word_sets, word_sets[1:], strict=False):
            union = len(a | b)
            similarities.append(len(a & b) / union if union else 0.0)
        return similarities

    def _find_boundaries(self, similarities: list[float]) -> list[int]:
        """
        Find topic boundaries (valleys in similarity scores).

        Args:
            similarities: Similarity scores

        Returns:
            Indices of paragraphs that start a new topic
        """
        if len(similarities) < 3:
            return []

        avg = sum(similarities) / len(similarities)  # computed once, not per valley
        threshold = avg * 0.7
        return [
            i + 1
            for i in range(1, len(similarities) - 1)
            if similarities[i] < similarities[i - 1]
            and similarities[i] < similarities[i + 1]
            and similarities[i] < threshold
        ]
