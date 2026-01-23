"""
Title generation enricher.

Generates smart section titles from content using:
- Keywords method (from extracted keywords)
- First sentence method (using first sentence as title)
"""
import re

from ..models.document import Chunk, EnrichedChunk
from .base import BaseEnricher


class TitleGenerator(BaseEnricher):
    """
    Generate smart section titles.

    Replaces generic "Section 1, 2, 3" with meaningful names
    based on content.

    Supports two methods:
    - keywords: Use extracted keywords to generate title
    - first_sentence: Use first sentence as title
    """

    def __init__(self, method: str = "first_sentence", max_length: int = 80):
        """
        Initialize title generator.

        Args:
            method: "keywords" or "first_sentence"
            max_length: Maximum title length (chars)
        """
        self.method = method.lower()
        self.max_length = max_length

        if self.method not in ["keywords", "first_sentence"]:
            raise ValueError(f"Unknown method: {method}. Use 'keywords' or 'first_sentence'")

    def enrich(self, chunks: list[Chunk]) -> list[EnrichedChunk]:
        """
        Generate smart titles for chunks/sections.

        Args:
            chunks: List of chunks to enrich

        Returns:
            List of enriched chunks with smart section names
        """
        enriched_chunks = [self._chunk_to_enriched(chunk) for chunk in chunks]

        for chunk in enriched_chunks:
            # Skip code chunks
            if self._should_skip_chunk(chunk):
                continue

            # Only generate title if section name is generic or missing
            if self._needs_better_title(chunk.section_name):
                if self.method == "keywords":
                    chunk.section_name = self._generate_from_keywords(chunk)
                else:  # first_sentence
                    chunk.section_name = self._generate_from_first_sentence(chunk)

        return enriched_chunks

    def _needs_better_title(self, section_name: str) -> bool:
        """
        Check if section name needs improvement.

        Args:
            section_name: Current section name

        Returns:
            True if needs better title
        """
        if not section_name:
            return True

        # Generic patterns to replace
        generic_patterns = [
            r'^Section \d+$',           # "Section 1"
            r'^Section_\d+$',           # "Section_1"
            r'^Untitled',               # "Untitled Section"
            r'^Part \d+$',              # "Part 1"
            r'^Chapter \d+$'            # "Chapter 1"
        ]

        for pattern in generic_patterns:
            if re.match(pattern, section_name):
                return True

        return False

    def _generate_from_keywords(self, chunk: EnrichedChunk) -> str:
        """
        Generate title from extracted keywords.

        Args:
            chunk: Chunk with keywords

        Returns:
            Generated title
        """
        # Check if chunk has keywords
        if not chunk.keywords or not chunk.has_keywords:
            # Fallback to first sentence
            return self._generate_from_first_sentence(chunk)

        # Use top 2-3 keywords
        top_keywords = chunk.keywords[:3]

        # Capitalize and join
        title = ", ".join(word.title() for word in top_keywords)

        # Add "Section: " prefix
        title = f"Section: {title}"

        # Truncate if too long
        if len(title) > self.max_length:
            title = title[:self.max_length - 3] + "..."

        return title

    def _generate_from_first_sentence(self, chunk: Chunk) -> str:
        """
        Generate title from first sentence.

        Args:
            chunk: Chunk to generate title from

        Returns:
            Generated title
        """
        text = chunk.text.strip()

        if not text:
            return "Untitled Section"

        # Extract first sentence
        first_sentence = self._extract_first_sentence(text)

        if not first_sentence:
            # Use first 50 chars
            first_sentence = text[:50]

        # Clean up
        title = first_sentence.strip()

        # Remove trailing punctuation
        title = re.sub(r'[.!?:;,]+$', '', title)

        # Truncate if too long
        if len(title) > self.max_length:
            title = title[:self.max_length - 3] + "..."

        return title

    def _extract_first_sentence(self, text: str) -> str:
        """
        Extract first sentence from text.

        Args:
            text: Text to extract from

        Returns:
            First sentence
        """
        # Simple sentence boundary detection
        # Splits on: . ! ? followed by space and capital letter or end of string
        sentence_pattern = r'([^.!?]+[.!?]+)'
        matches = re.findall(sentence_pattern, text)

        if matches:
            return matches[0].strip()

        # If no sentence boundary, use first line
        first_line = text.split('\n')[0].strip()
        return first_line if first_line else text[:100]
