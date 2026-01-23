"""
Section detection enricher.

Detects topic boundaries and section transitions using:
- Heuristic detection (pattern matching)
- TextTiling algorithm (topic shift detection)
"""
import re

from ..models.document import Chunk, EnrichedChunk
from .base import BaseEnricher


class SectionDetector(BaseEnricher):
    """
    Detect section boundaries in chunks.

    Supports two methods:
    - heuristic: Pattern-based detection (ALL CAPS, colons, etc.)
    - texttiling: Topic shift detection using lexical cohesion
    """

    def __init__(self, method: str = "heuristic"):
        """
        Initialize section detector.

        Args:
            method: "heuristic" or "texttiling"
        """
        self.method = method.lower()

        if self.method not in ["heuristic", "texttiling"]:
            raise ValueError(f"Unknown method: {method}. Use 'heuristic' or 'texttiling'")

    def enrich(self, chunks: list[Chunk]) -> list[EnrichedChunk]:
        """
        Detect sections and assign section names.

        Args:
            chunks: List of chunks to enrich

        Returns:
            List of enriched chunks with section names
        """
        enriched_chunks = [self._chunk_to_enriched(chunk) for chunk in chunks]

        if self.method == "heuristic":
            return self._heuristic_detection(enriched_chunks)
        else:  # texttiling
            return self._texttiling_detection(enriched_chunks)

    def _heuristic_detection(self, chunks: list[EnrichedChunk]) -> list[EnrichedChunk]:
        """
        Detect sections using pattern matching.

        Patterns:
        - ALL CAPS text (< 10 words) = section header
        - Text ending with colon (< 8 words) = section header
        - **Bold text** or _italic text_ (< 10 words) = section header
        - Numbered sections (1., 2., etc.) = section header

        Args:
            chunks: List of enriched chunks

        Returns:
            Chunks with section names assigned
        """
        current_section = None
        section_counter = 1

        for chunk in chunks:
            # Skip code chunks
            if self._should_skip_chunk(chunk):
                continue

            # Check if this chunk starts with a section header
            header = self._detect_header(chunk.text)

            if header:
                # This is a new section
                current_section = header
                chunk.section_name = header
            elif current_section:
                # Continuation of previous section
                chunk.section_name = current_section
            else:
                # No section detected yet, use numbered fallback
                chunk.section_name = f"Section {section_counter}"

        return chunks

    def _detect_header(self, text: str) -> str:
        """
        Detect if text starts with a section header.

        Args:
            text: Text to check

        Returns:
            Header text if detected, None otherwise
        """
        # Get first line
        first_line = text.split('\n')[0].strip()

        if not first_line or len(first_line.split()) > 15:
            return None

        # Pattern 1: ALL CAPS (< 10 words)
        if first_line.isupper() and len(first_line.split()) <= 10:
            return first_line.title()  # Convert to Title Case

        # Pattern 2: Ends with colon (< 8 words)
        if first_line.endswith(':') and len(first_line.split()) <= 8:
            return first_line[:-1]  # Remove colon

        # Pattern 3: Numbered section (1., 2., 1.1, etc.)
        numbered_match = re.match(r'^(\d+\.)+\s+(.+)', first_line)
        if numbered_match:
            return numbered_match.group(2)

        # Pattern 4: Markdown bold/italic (simplified)
        bold_match = re.match(r'^\*\*(.+?)\*\*', first_line)
        if bold_match and len(bold_match.group(1).split()) <= 10:
            return bold_match.group(1)

        italic_match = re.match(r'^_(.+?)_', first_line)
        if italic_match and len(italic_match.group(1).split()) <= 10:
            return italic_match.group(1)

        return None

    def _texttiling_detection(self, chunks: list[EnrichedChunk]) -> list[EnrichedChunk]:
        """
        Detect sections using TextTiling algorithm.

        Algorithm:
        1. Calculate lexical similarity between adjacent chunks
        2. Find valleys (low similarity) = section boundaries
        3. Group chunks between boundaries into sections

        Args:
            chunks: List of enriched chunks

        Returns:
            Chunks with section names assigned
        """
        if len(chunks) < 3:
            # Too few chunks, just assign one section
            for chunk in chunks:
                chunk.section_name = "Section 1"
            return chunks

        # Calculate similarities between adjacent chunks
        similarities = []
        for i in range(len(chunks) - 1):
            sim = self._calculate_similarity(chunks[i].text, chunks[i + 1].text)
            similarities.append(sim)

        # Find valleys (local minima) as boundaries
        boundaries = [0]  # Start is always a boundary
        for i in range(1, len(similarities) - 1):
            if similarities[i] < similarities[i - 1] and similarities[i] < similarities[i + 1]:
                # Local minimum = topic shift
                boundaries.append(i + 1)
        boundaries.append(len(chunks))  # End is always a boundary

        # Assign section names
        for section_num, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=False), 1):
            for i in range(start, end):
                chunks[i].section_name = f"Section {section_num}"

        return chunks

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate lexical similarity between two texts.

        Uses simple word overlap (Jaccard similarity).

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score (0-1, higher = more similar)
        """
        # Convert to lowercase and split into words
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        # Remove very short words
        words1 = {w for w in words1 if len(w) > 2}
        words2 = {w for w in words2 if len(w) > 2}

        if not words1 or not words2:
            return 0.0

        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0
