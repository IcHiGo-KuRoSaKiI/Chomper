"""
Base class for enrichers.

All enrichers inherit from BaseEnricher.
"""
from abc import ABC, abstractmethod
from typing import List
from ..models.document import Chunk, EnrichedChunk


class BaseEnricher(ABC):
    """
    Abstract base class for chunk enrichers.

    Enrichers add metadata and analysis to chunks
    (keywords, sections, summaries, etc.)
    """

    @abstractmethod
    def enrich(self, chunks: List[Chunk]) -> List[EnrichedChunk]:
        """
        Enrich chunks with additional metadata.

        Args:
            chunks: List of chunks to enrich

        Returns:
            List of enriched chunks

        Raises:
            ValueError: If chunks are invalid
        """
        pass

    def _chunk_to_enriched(self, chunk: Chunk) -> EnrichedChunk:
        """
        Convert a regular Chunk to EnrichedChunk.

        Args:
            chunk: Chunk to convert

        Returns:
            EnrichedChunk with same base data
        """
        if isinstance(chunk, EnrichedChunk):
            return chunk

        return EnrichedChunk(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            metadata=chunk.metadata.copy(),
            keywords=[],
            section_name=None,
            section_type=chunk.metadata.get("section_type", "text"),
            computed_metadata={}
        )

    def _should_skip_chunk(self, chunk: Chunk) -> bool:
        """
        Determine if chunk should be skipped (e.g., code chunks).

        Args:
            chunk: Chunk to check

        Returns:
            True if should skip enrichment
        """
        # Skip very short chunks
        if chunk.word_count < 5:
            return True

        # Skip code chunks (AST provides enough structure)
        if chunk.metadata.get("section_type") == "code":
            return True

        return False
