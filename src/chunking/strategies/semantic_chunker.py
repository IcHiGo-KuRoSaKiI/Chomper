"""
Semantic chunker using sentence embeddings.

This chunker uses sentence-transformers to create embeddings and finds
semantic boundaries based on cosine similarity between adjacent text units.
"""
from __future__ import annotations

import numpy as np

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker
from ..text_splitter import BLOCK, Unit, pack, segment

# Lazy loading for sentence-transformers
_model_cache: dict[str, object] = {}


def _get_embedding_model(model_name: str):
    """
    Lazy load embedding model to avoid startup cost.

    Args:
        model_name: Model identifier

    Returns:
        SentenceTransformer model instance
    """
    global _model_cache

    if model_name in _model_cache:
        return _model_cache[model_name]

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        _model_cache[model_name] = model
        return model
    except ImportError as e:
        raise ImportError(
            "sentence-transformers is required for semantic chunking. "
            "Install with: pip install sentence-transformers"
        ) from e


class SemanticChunker(BaseChunker):
    """
    Embedding-based semantic chunker for RAG applications.

    Uses sentence embeddings to find semantic boundaries in text,
    grouping semantically similar content together.
    """

    # Available models with trade-offs
    MODELS = {
        "fast": "all-MiniLM-L6-v2",      # ~80MB, fastest, good quality
        "balanced": "all-mpnet-base-v2",  # ~420MB, best quality/speed ratio
    }

    # Breakpoint detection strategies
    STRATEGIES = ["percentile", "standard_deviation", "interquartile"]

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        model: str = "fast",
        breakpoint_strategy: str = "percentile",
        breakpoint_threshold: float = 0.5,
        min_chunk_size: int = 50,
        preserve_context: bool = True
    ):
        """
        Initialize semantic chunker.

        Args:
            target_size: Target words per chunk (soft limit)
            overlap: Words to overlap between chunks
            model: Embedding model - 'fast' or 'balanced'
            breakpoint_strategy: How to detect semantic boundaries:
                - 'percentile': Break at distances > Nth percentile
                - 'standard_deviation': Break at distances > N std devs from mean
                - 'interquartile': Break at distances outside IQR
            breakpoint_threshold: Threshold for breakpoint detection:
                - For 'percentile': Percentile cutoff (0.5 = 50th percentile)
                - For 'standard_deviation': Number of std devs (e.g., 1.0)
                - For 'interquartile': IQR multiplier (e.g., 1.5)
            min_chunk_size: Minimum words per chunk
            preserve_context: Whether to maintain document structure
        """
        super().__init__(target_size, overlap, preserve_context)

        if model not in self.MODELS:
            raise ValueError(f"Unknown model: {model}. Available: {list(self.MODELS.keys())}")
        if breakpoint_strategy not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy: {breakpoint_strategy}. Available: {self.STRATEGIES}")

        self.model_name = self.MODELS[model]
        self.model_key = model
        self.breakpoint_strategy = breakpoint_strategy
        self.breakpoint_threshold = breakpoint_threshold
        self.min_chunk_size = min_chunk_size

        # Model loaded lazily on first use
        self._model = None

    @property
    def model(self):
        """Lazy load the embedding model."""
        if self._model is None:
            self._model = _get_embedding_model(self.model_name)
        return self._model

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Split document into semantically coherent chunks.

        Every word of the document lands in a chunk (merging small groups never drops
        text), no chunk exceeds ``target_size`` words unless a single code block or
        table row does, and ``overlap`` words of whole lines/sentences are repeated.

        Args:
            raw_doc: Raw document from extractor

        Returns:
            List of chunks; ``chunk.text == raw_doc.text[chunk.start_char:chunk.end_char]``
        """
        text = raw_doc.text
        if not text or not text.strip():
            return []

        base = segment(text, self.target_size)
        if not base:
            return []

        # Step 1: embedding units = paragraphs, each cut to at most target_size words.
        unit_ranges = self._paragraph_ranges(base)
        if len(unit_ranges) <= 1:
            groups = [(0, len(base))]
            reason: str | None = "document_too_small"
        else:
            units = [
                (text[base[a].start:base[b - 1].end], base[a].start, base[b - 1].end)
                for a, b in unit_ranges
            ]
            # Steps 2-4: embed, measure adjacent distances, pick breakpoints.
            embeddings = self._compute_embeddings(units)
            distances = self._calculate_distances(embeddings)
            breakpoints = self._find_breakpoints(distances)
            groups = self._groups_from_breakpoints(base, unit_ranges, breakpoints)
            reason = None

        # Step 5: enforce the size limit, then add overlap, then build chunks.
        pieces: list[tuple[int, int]] = []
        for a, b in groups:
            sub = base[a:b]
            pieces.extend((a + x, a + y) for x, y in pack(sub, self.target_size, 0))
        return self._build_chunks(text, base, pieces, reason)

    def _paragraph_ranges(self, base: list[Unit]) -> list[tuple[int, int]]:
        """Index ranges of paragraphs (blank-line blocks), oversized ones subdivided."""
        starts = [i for i, u in enumerate(base) if i == 0 or u.strength >= BLOCK]
        bounds = starts + [len(base)]
        ranges: list[tuple[int, int]] = []
        for a, b in zip(bounds, bounds[1:], strict=False):
            ranges.extend((a + x, a + y) for x, y in pack(base[a:b], self.target_size, 0))
        return ranges

    def _groups_from_breakpoints(
        self,
        base: list[Unit],
        unit_ranges: list[tuple[int, int]],
        breakpoints: list[int],
    ) -> list[tuple[int, int]]:
        """Group embedding units between breakpoints; merge undersized groups.

        A group below ``min_chunk_size`` words is merged into the next group (the
        last one into the previous), so nothing is ever discarded.
        """
        cuts = sorted({b + 1 for b in breakpoints if 0 <= b < len(unit_ranges) - 1})
        bounds = [0] + cuts + [len(unit_ranges)]
        groups = [
            (unit_ranges[a][0], unit_ranges[b - 1][1])
            for a, b in zip(bounds, bounds[1:], strict=False)
            if b > a
        ]

        def words(group: tuple[int, int]) -> int:
            return sum(u.words for u in base[group[0]:group[1]])

        merged: list[tuple[int, int]] = []
        pending: tuple[int, int] | None = None
        for group in groups:
            if pending is not None:
                group = (pending[0], group[1])
                pending = None
            if words(group) < self.min_chunk_size:
                pending = group
                continue
            merged.append(group)
        if pending is not None:
            if merged:
                merged[-1] = (merged[-1][0], pending[1])
            else:
                merged.append(pending)
        return merged

    def _build_chunks(
        self,
        text: str,
        base: list[Unit],
        pieces: list[tuple[int, int]],
        reason: str | None,
    ) -> list[Chunk]:
        """Turn unit ranges into chunks, prepending up to ``overlap`` words."""
        chunks: list[Chunk] = []
        prev_start = -1
        for a, b in pieces:
            start_idx = a
            if self.overlap and chunks:
                carried = 0
                room = self.target_size - sum(u.words for u in base[a:b])
                budget = min(self.overlap, room)
                while start_idx - 1 > prev_start:
                    unit = base[start_idx - 1]
                    if unit.kind == "code" or carried + unit.words > budget:
                        break
                    carried += unit.words
                    start_idx -= 1
            prev_start = a
            start_char, end_char = base[start_idx].start, base[b - 1].end
            metadata: dict = {
                "chunk_strategy": "semantic",
                "model": self.model_key,
                "breakpoint_strategy": self.breakpoint_strategy,
                "unit_count": b - start_idx,
                "section_type": "text",
            }
            if reason:
                metadata["reason"] = reason
            chunks.append(
                Chunk(
                    chunk_id=len(chunks),
                    text=text[start_char:end_char],
                    start_char=start_char,
                    end_char=end_char,
                    metadata=metadata,
                )
            )
        return chunks

    def _split_into_units(self, text: str) -> list[tuple[str, int, int]]:
        """
        Split text into embedding units: paragraphs no larger than ``target_size``.

        Returns list of (text, start_char, end_char) tuples.
        """
        base = segment(text, self.target_size)
        return [
            (text[base[a].start:base[b - 1].end], base[a].start, base[b - 1].end)
            for a, b in self._paragraph_ranges(base)
        ]

    def _compute_embeddings(self, units: list[tuple[str, int, int]]) -> np.ndarray:
        """
        Compute embeddings for all text units.

        Args:
            units: List of (text, start, end) tuples

        Returns:
            numpy array of embeddings
        """
        texts = [u[0] for u in units]
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings

    def _calculate_distances(self, embeddings: np.ndarray) -> list[float]:
        """
        Calculate cosine distances between adjacent embeddings.

        Args:
            embeddings: numpy array of embeddings

        Returns:
            List of distances (1 - cosine_similarity)
        """
        distances = []
        for i in range(len(embeddings) - 1):
            # Cosine similarity
            a = embeddings[i]
            b = embeddings[i + 1]
            similarity = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
            # Convert to distance (higher = more different)
            distance = 1 - similarity
            distances.append(distance)
        return distances

    def _find_breakpoints(self, distances: list[float]) -> list[int]:
        """
        Find indices where semantic breaks should occur.

        Args:
            distances: List of distances between adjacent units

        Returns:
            List of indices where breaks should occur
        """
        if not distances:
            return []

        distances_arr = np.array(distances)

        if self.breakpoint_strategy == "percentile":
            # Break at distances above the Nth percentile
            threshold = np.percentile(distances_arr, self.breakpoint_threshold * 100)
            breakpoints = [i for i, d in enumerate(distances) if d > threshold]

        elif self.breakpoint_strategy == "standard_deviation":
            # Break at distances N standard deviations above mean
            mean = np.mean(distances_arr)
            std = np.std(distances_arr)
            threshold = mean + (self.breakpoint_threshold * std)
            breakpoints = [i for i, d in enumerate(distances) if d > threshold]

        elif self.breakpoint_strategy == "interquartile":
            # Break at distances outside IQR
            q1 = np.percentile(distances_arr, 25)
            q3 = np.percentile(distances_arr, 75)
            iqr = q3 - q1
            threshold = q3 + (self.breakpoint_threshold * iqr)
            breakpoints = [i for i, d in enumerate(distances) if d > threshold]

        else:
            breakpoints = []

        return breakpoints
