"""
Base class for document chunkers.

All format-specific chunkers inherit from BaseChunker.
"""
from abc import ABC, abstractmethod

from ..models.document import Chunk, RawDocument


class BaseChunker(ABC):
    """
    Abstract base class for document chunkers.

    Chunkers are responsible for intelligently splitting documents
    into semantically meaningful pieces.
    """

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        preserve_context: bool = True
    ):
        """
        Initialize chunker with common parameters.

        Args:
            target_size: Target words per chunk
            overlap: Words to overlap between chunks (for context)
            preserve_context: Whether to maintain document structure
        """
        self.target_size = target_size
        self.overlap = overlap
        self.preserve_context = preserve_context

    @abstractmethod
    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Split document into chunks.

        Args:
            raw_doc: Raw document from extractor

        Returns:
            List of chunks

        Raises:
            ValueError: If document is invalid or empty
        """
        pass

    def _create_chunk(
        self,
        chunk_id: int,
        text: str,
        start_char: int = 0,
        end_char: int = 0,
        metadata: dict = None
    ) -> Chunk:
        """
        Helper to create a chunk with standard format.

        Args:
            chunk_id: Sequential chunk ID
            text: Chunk text content
            start_char: Start position in original document
            end_char: End position in original document
            metadata: Additional metadata

        Returns:
            Chunk object
        """
        return Chunk(
            chunk_id=chunk_id,
            text=text.strip(),
            start_char=start_char,
            end_char=end_char if end_char > 0 else start_char + len(text),
            metadata=metadata or {}
        )

    def _split_by_word_count(
        self,
        text: str,
        target_size: int = None,
        overlap: int = None
    ) -> list[str]:
        """
        Simple word-count-based splitting with overlap.

        Args:
            text: Text to split
            target_size: Target words per chunk (defaults to self.target_size)
            overlap: Overlap size (defaults to self.overlap)

        Returns:
            List of text chunks
        """
        target_size = target_size or self.target_size
        overlap = overlap or self.overlap

        words = text.split()
        chunks = []
        start = 0

        while start < len(words):
            end = start + target_size
            chunk_words = words[start:end]
            chunks.append(" ".join(chunk_words))

            # Move start forward, accounting for overlap
            start = end - overlap if end < len(words) else len(words)

        return chunks

    def _split_by_paragraphs(self, text: str) -> list[str]:
        """
        Split text by paragraph boundaries (double newlines).

        Args:
            text: Text to split

        Returns:
            List of paragraphs
        """
        paragraphs = text.split("\n\n")
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_by_sentences(self, text: str) -> list[str]:
        """
        Simple sentence splitting (can be improved with nltk).

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        import re
        # Simple regex for sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
