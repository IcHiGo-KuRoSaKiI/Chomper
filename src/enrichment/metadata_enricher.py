"""
Metadata enrichment.

Computes additional metadata for chunks:
- Word count, character count
- Reading time estimation
- Complexity scores
"""
from typing import List
import re
from .base import BaseEnricher
from ..models.document import Chunk, EnrichedChunk


class MetadataEnricher(BaseEnricher):
    """
    Compute additional metadata for chunks.

    Adds:
    - word_count: Number of words
    - char_count: Number of characters
    - reading_time: Estimated reading time in minutes
    - sentence_count: Number of sentences
    - avg_word_length: Average word length
    - complexity_score: Simple readability score
    """

    def __init__(self, reading_speed: int = 200):
        """
        Initialize metadata enricher.

        Args:
            reading_speed: Words per minute (default 200 WPM)
        """
        self.reading_speed = reading_speed

    def enrich(self, chunks: List[Chunk]) -> List[EnrichedChunk]:
        """
        Compute metadata for all chunks.

        Args:
            chunks: List of chunks to enrich

        Returns:
            List of enriched chunks with computed metadata
        """
        enriched_chunks = []

        for chunk in chunks:
            enriched = self._chunk_to_enriched(chunk)

            # Compute metadata
            metadata = {
                "word_count": self._count_words(chunk.text),
                "char_count": len(chunk.text),
                "reading_time": self._estimate_reading_time(chunk.text),
                "sentence_count": self._count_sentences(chunk.text),
                "avg_word_length": self._avg_word_length(chunk.text),
                "complexity_score": self._complexity_score(chunk.text)
            }

            enriched.computed_metadata.update(metadata)
            enriched_chunks.append(enriched)

        return enriched_chunks

    def _count_words(self, text: str) -> int:
        """Count words in text."""
        return len(text.split())

    def _count_sentences(self, text: str) -> int:
        """Count sentences in text."""
        # Simple sentence boundary detection
        sentences = re.split(r'[.!?]+', text)
        return len([s for s in sentences if s.strip()])

    def _avg_word_length(self, text: str) -> float:
        """Calculate average word length."""
        words = text.split()
        if not words:
            return 0.0

        total_length = sum(len(word.strip('.,!?;:')) for word in words)
        return round(total_length / len(words), 2)

    def _estimate_reading_time(self, text: str) -> str:
        """
        Estimate reading time.

        Args:
            text: Text to estimate

        Returns:
            Reading time as string (e.g., "2 min", "30 sec")
        """
        word_count = self._count_words(text)
        minutes = word_count / self.reading_speed

        if minutes < 1:
            seconds = int(minutes * 60)
            return f"{seconds} sec"
        else:
            return f"{int(minutes)} min"

    def _complexity_score(self, text: str) -> float:
        """
        Calculate simple complexity/readability score.

        Uses a simplified version of Flesch Reading Ease:
        - Lower score = more complex
        - Higher score = easier to read

        Args:
            text: Text to analyze

        Returns:
            Complexity score (0-100, higher = easier)
        """
        words = self._count_words(text)
        sentences = self._count_sentences(text)

        if words == 0 or sentences == 0:
            return 50.0  # Neutral

        # Average words per sentence
        avg_sentence_length = words / sentences

        # Average syllables per word (simplified)
        avg_syllables = self._estimate_avg_syllables(text)

        # Simplified Flesch Reading Ease
        # Score = 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
        score = 206.835 - (1.015 * avg_sentence_length) - (84.6 * avg_syllables)

        # Clamp to 0-100
        score = max(0, min(100, score))

        return round(score, 2)

    def _estimate_avg_syllables(self, text: str) -> float:
        """
        Estimate average syllables per word (simplified).

        Uses vowel counting as proxy (not perfect but fast).

        Args:
            text: Text to analyze

        Returns:
            Average syllables per word
        """
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())

        if not words:
            return 1.0

        total_syllables = 0
        for word in words:
            # Count vowel groups as syllables
            syllables = len(re.findall(r'[aeiouy]+', word))
            # Minimum 1 syllable per word
            total_syllables += max(1, syllables)

        return round(total_syllables / len(words), 2)
