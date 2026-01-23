"""
Semantic chunker using sentence embeddings.

This chunker uses sentence-transformers to create embeddings and finds
semantic boundaries based on cosine similarity between adjacent text units.
"""
import numpy as np

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker

# Lazy loading for sentence-transformers
_model_cache = {}


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

        Args:
            raw_doc: Raw document from extractor

        Returns:
            List of chunks with semantic boundaries
        """
        text = raw_doc.text
        if not text or not text.strip():
            return []

        # Step 1: Split into sentences/paragraphs (small units)
        units = self._split_into_units(text)
        if len(units) <= 1:
            # Document too small, return as single chunk
            return [self._create_chunk(
                chunk_id=0,
                text=text,
                start_char=0,
                end_char=len(text),
                metadata={"chunk_strategy": "semantic", "reason": "document_too_small"}
            )]

        # Step 2: Compute embeddings for all units
        embeddings = self._compute_embeddings(units)

        # Step 3: Calculate distances between adjacent units
        distances = self._calculate_distances(embeddings)

        # Step 4: Find semantic breakpoints
        breakpoints = self._find_breakpoints(distances)

        # Step 5: Create chunks from breakpoints
        chunks = self._create_chunks_from_breakpoints(
            text=text,
            units=units,
            breakpoints=breakpoints
        )

        return chunks

    def _split_into_units(self, text: str) -> list[tuple[str, int, int]]:
        """
        Split text into small units (sentences or paragraphs).

        Returns list of (text, start_char, end_char) tuples.
        """
        units = []

        # Try splitting by paragraphs first
        paragraphs = text.split("\n\n")

        current_pos = 0
        for para in paragraphs:
            para = para.strip()
            if not para:
                current_pos += 2  # Skip the \n\n
                continue

            # Find actual position in original text
            start = text.find(para, current_pos)
            if start == -1:
                start = current_pos
            end = start + len(para)

            # If paragraph is very long, split into sentences
            if len(para.split()) > self.target_size:
                sentences = self._split_by_sentences(para)
                sent_pos = start
                for sent in sentences:
                    sent_start = text.find(sent, sent_pos)
                    if sent_start == -1:
                        sent_start = sent_pos
                    sent_end = sent_start + len(sent)
                    if sent.strip():
                        units.append((sent.strip(), sent_start, sent_end))
                    sent_pos = sent_end
            else:
                units.append((para, start, end))

            current_pos = end

        return units

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

    def _create_chunks_from_breakpoints(
        self,
        text: str,
        units: list[tuple[str, int, int]],
        breakpoints: list[int]
    ) -> list[Chunk]:
        """
        Create chunks using the detected breakpoints.

        Args:
            text: Original document text
            units: List of (text, start, end) tuples
            breakpoints: Indices where to break

        Returns:
            List of Chunk objects
        """
        chunks = []

        # Add start and end boundaries
        all_breaks = [0] + [b + 1 for b in breakpoints] + [len(units)]

        chunk_id = 0
        for i in range(len(all_breaks) - 1):
            start_idx = all_breaks[i]
            end_idx = all_breaks[i + 1]

            # Get units for this chunk
            chunk_units = units[start_idx:end_idx]
            if not chunk_units:
                continue

            # Combine unit texts
            chunk_text = " ".join([u[0] for u in chunk_units])

            # Check if chunk is too small, merge with next if possible
            word_count = len(chunk_text.split())
            if word_count < self.min_chunk_size and i < len(all_breaks) - 2:
                # Skip this chunk, it will be merged with the next one
                continue

            # Get character positions
            start_char = chunk_units[0][1]
            end_char = chunk_units[-1][2]

            chunks.append(self._create_chunk(
                chunk_id=chunk_id,
                text=chunk_text,
                start_char=start_char,
                end_char=end_char,
                metadata={
                    "chunk_strategy": "semantic",
                    "model": self.model_key,
                    "breakpoint_strategy": self.breakpoint_strategy,
                    "unit_count": len(chunk_units),
                    "section_type": "text"
                }
            ))
            chunk_id += 1

        # Handle edge case: no chunks created
        if not chunks:
            chunks.append(self._create_chunk(
                chunk_id=0,
                text=text,
                start_char=0,
                end_char=len(text),
                metadata={"chunk_strategy": "semantic", "reason": "no_breakpoints_found"}
            ))

        return chunks
