"""
Text chunker with context-aware semantic chunking.

Chunks plain text while preserving:
- Paragraph boundaries
- Sentence boundaries
- Semantic coherence (via TextTiling algorithm)
"""

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker


class TextChunker(BaseChunker):
    """
    Chunk plain text with context awareness.

    Strategy:
    - Respect paragraph boundaries
    - Use TextTiling for semantic chunking (optional)
    - Split at sentence boundaries when needed
    - Maintain reading flow
    """

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        preserve_context: bool = True,
        use_semantic: bool = True
    ):
        """
        Initialize text chunker.

        Args:
            target_size: Target words per chunk
            overlap: Words to overlap
            preserve_context: Maintain context
            use_semantic: Use semantic chunking (TextTiling)
        """
        super().__init__(target_size, overlap, preserve_context)
        self.use_semantic = use_semantic

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk text document.

        Args:
            raw_doc: Raw text document

        Returns:
            List of chunks
        """
        if self.use_semantic and raw_doc.structure:
            # Use semantic chunking with paragraph structure
            return self._semantic_chunk(raw_doc)
        else:
            # Simple paragraph-based chunking
            return self._paragraph_chunk(raw_doc)

    def _paragraph_chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk by paragraphs.

        Args:
            raw_doc: Raw document

        Returns:
            List of chunks
        """
        chunks = []
        chunk_id = 0

        if raw_doc.structure and "paragraphs" in raw_doc.structure:
            paragraphs = raw_doc.structure["paragraphs"]

            current_chunk_text = []
            current_word_count = 0

            for para in paragraphs:
                para_text = para["text"]
                para_words = para_text.split()

                # If adding this paragraph would exceed target, finalize current chunk
                if current_word_count + len(para_words) > self.target_size and current_chunk_text:
                    chunk = self._create_chunk(
                        chunk_id=chunk_id,
                        text=' '.join(current_chunk_text),
                        metadata={
                            "section_type": "text",
                            "chunk_strategy": "paragraph"
                        }
                    )
                    chunks.append(chunk)
                    chunk_id += 1

                    # Start new chunk with overlap
                    if self.overlap > 0 and current_word_count >= self.overlap:
                        current_chunk_text = current_chunk_text[-self.overlap:]
                        current_word_count = len(current_chunk_text)
                    else:
                        current_chunk_text = []
                        current_word_count = 0

                # Add paragraph to current chunk
                current_chunk_text.extend(para_words)
                current_word_count += len(para_words)

            # Add final chunk
            if current_chunk_text:
                chunk = self._create_chunk(
                    chunk_id=chunk_id,
                    text=' '.join(current_chunk_text),
                    metadata={
                        "section_type": "text",
                        "chunk_strategy": "paragraph"
                    }
                )
                chunks.append(chunk)

        else:
            # No paragraph structure, use simple word-based chunking
            words = raw_doc.text.split()
            start = 0

            while start < len(words):
                end = min(start + self.target_size, len(words))
                chunk_words = words[start:end]
                text = ' '.join(chunk_words)

                chunk = self._create_chunk(
                    chunk_id=chunk_id,
                    text=text,
                    metadata={
                        "section_type": "text",
                        "chunk_strategy": "simple"
                    }
                )
                chunks.append(chunk)

                chunk_id += 1
                start = end - self.overlap if self.overlap > 0 else end

        return chunks

    def _semantic_chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Semantic chunking using TextTiling algorithm.

        Detects topic shifts and chunks accordingly.

        Args:
            raw_doc: Raw document

        Returns:
            List of chunks
        """
        if not raw_doc.structure or "paragraphs" not in raw_doc.structure:
            return self._paragraph_chunk(raw_doc)

        paragraphs = raw_doc.structure["paragraphs"]

        if len(paragraphs) < 3:
            # Too few paragraphs for semantic analysis
            return self._paragraph_chunk(raw_doc)

        # Calculate lexical similarity between adjacent paragraphs
        similarities = self._calculate_similarities(paragraphs)

        # Find valleys (topic boundaries) - low similarity points
        boundaries = self._find_boundaries(similarities)

        # Chunk at boundaries
        chunks = []
        chunk_id = 0
        current_chunk_paras = []

        for i, para in enumerate(paragraphs):
            current_chunk_paras.append(para)

            # Check if this is a boundary
            if i in boundaries or i == len(paragraphs) - 1:
                # Combine paragraphs into chunk
                chunk_text = '\n\n'.join(p["text"] for p in current_chunk_paras)

                chunk = self._create_chunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    metadata={
                        "section_type": "text",
                        "paragraph_count": len(current_chunk_paras),
                        "chunk_strategy": "semantic"
                    }
                )
                chunks.append(chunk)

                chunk_id += 1
                current_chunk_paras = []

        return chunks

    def _calculate_similarities(self, paragraphs: list[dict]) -> list[float]:
        """
        Calculate lexical similarity between adjacent paragraphs.

        Args:
            paragraphs: List of paragraph dictionaries

        Returns:
            List of similarity scores
        """
        similarities = []

        for i in range(len(paragraphs) - 1):
            para1_words = set(paragraphs[i]["text"].lower().split())
            para2_words = set(paragraphs[i + 1]["text"].lower().split())

            # Jaccard similarity
            intersection = len(para1_words & para2_words)
            union = len(para1_words | para2_words)

            similarity = intersection / union if union > 0 else 0
            similarities.append(similarity)

        return similarities

    def _find_boundaries(self, similarities: list[float]) -> list[int]:
        """
        Find topic boundaries (valleys in similarity scores).

        Args:
            similarities: Similarity scores

        Returns:
            List of boundary indices
        """
        if len(similarities) < 3:
            return []

        boundaries = []

        # Find local minima (valleys)
        for i in range(1, len(similarities) - 1):
            # Check if this is a valley
            if similarities[i] < similarities[i - 1] and similarities[i] < similarities[i + 1]:
                # And significantly lower than average
                avg = sum(similarities) / len(similarities)
                if similarities[i] < avg * 0.7:  # Threshold: 70% of average
                    boundaries.append(i + 1)  # Boundary is after the low-similarity pair

        return boundaries
