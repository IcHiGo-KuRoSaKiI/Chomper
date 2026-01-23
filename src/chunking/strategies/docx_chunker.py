"""
DOCX chunker with heading-aware structure preservation.

Chunks DOCX documents while preserving:
- Heading hierarchy
- Section boundaries
- Tables and images in context
"""

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker


class DOCXChunker(BaseChunker):
    """
    Chunk DOCX documents preserving heading structure.

    Strategy:
    - Respects heading hierarchy (H1 always starts new chunk)
    - Maintains section context
    - Groups content by sections or size
    - Preserves tables and images with surrounding text
    """

    def __init__(
        self,
        target_size: int = 500,
        overlap: int = 50,
        preserve_context: bool = True,
        chunk_by_section: bool = False
    ):
        """
        Initialize DOCX chunker.

        Args:
            target_size: Target words per chunk
            overlap: Words to overlap
            preserve_context: Maintain heading context
            chunk_by_section: Chunk by sections (one chunk per section) vs semantic chunking
        """
        super().__init__(target_size, overlap, preserve_context)
        self.chunk_by_section = chunk_by_section

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk DOCX document.

        Args:
            raw_doc: Raw DOCX document

        Returns:
            List of chunks with heading context preserved
        """
        if not raw_doc.structure or "sections" not in raw_doc.structure:
            # Fallback to simple chunking if no structure
            return self._simple_chunk(raw_doc)

        sections = raw_doc.structure["sections"]
        chunks = []
        chunk_id = 0

        if self.chunk_by_section:
            # Simple: one chunk per section
            for section in sections:
                chunk = self._create_section_chunk(chunk_id, section)
                chunks.append(chunk)
                chunk_id += 1
        else:
            # Smart: chunk by content size while preserving structure
            for section in sections:
                section_chunks = self._chunk_section_content(chunk_id, section)
                chunks.extend(section_chunks)
                chunk_id += len(section_chunks)

        return chunks

    def _create_section_chunk(self, chunk_id: int, section: dict) -> Chunk:
        """
        Create chunk from entire section.

        Args:
            chunk_id: Chunk ID
            section: Section dictionary

        Returns:
            Chunk
        """
        text_parts = []

        # Add heading
        heading = section.get("heading", "")
        level = section.get("level", 1)
        if heading:
            text_parts.append(f"{'#' * level} {heading}")

        # Add content
        has_images = False
        has_tables = False

        for item in section.get("content", []):
            if item["type"] == "text":
                text_parts.append(item["text"])
            elif item["type"] == "heading":
                text_parts.append(f"{'#' * item['level']} {item['text']}")
            elif item["type"] == "image":
                text_parts.append(f"[Image: {item['width']}x{item['height']}]")
                has_images = True
            elif item["type"] == "table":
                text_parts.append(item["text"])
                has_tables = True

        text = "\n\n".join(text_parts)

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "section_name": heading,
                "heading_level": level,
                "has_images": has_images,
                "has_tables": has_tables,
                "section_type": "text",
                "chunk_strategy": "section"
            }
        )

    def _chunk_section_content(self, start_chunk_id: int, section: dict) -> list[Chunk]:
        """
        Chunk section content by size while preserving structure.

        Args:
            start_chunk_id: Starting chunk ID
            section: Section dictionary

        Returns:
            List of chunks for this section
        """
        chunks = []
        current_chunk_text = []
        current_chunk_items = []
        chunk_id = start_chunk_id

        heading = section.get("heading", "")
        level = section.get("level", 1)

        # Add heading to first chunk
        if heading:
            current_chunk_text.append(f"{'#' * level} {heading}")

        for item in section.get("content", []):
            if item["type"] == "text":
                words = item["text"].split()
                current_chunk_text.extend(words)
                current_chunk_items.append(item)

                # Check if chunk is full
                if len(current_chunk_text) >= self.target_size:
                    # Create chunk
                    chunk = self._finalize_chunk(
                        chunk_id,
                        current_chunk_text,
                        current_chunk_items,
                        heading,
                        level
                    )
                    chunks.append(chunk)

                    # Start new chunk with overlap
                    overlap_words = current_chunk_text[-self.overlap:] if self.overlap > 0 else []
                    current_chunk_text = overlap_words

                    # Preserve heading context in new chunk
                    if self.preserve_context and heading:
                        current_chunk_text.insert(0, f"{'#' * level} {heading}")

                    current_chunk_items = []
                    chunk_id += 1

            elif item["type"] == "heading":
                # Add sub-heading
                sub_level = item["level"]
                current_chunk_text.append(f"{'#' * sub_level} {item['text']}")
                current_chunk_items.append(item)

            elif item["type"] == "image":
                # Add image to current chunk
                current_chunk_text.append(f"[Image: {item['width']}x{item['height']}]")
                current_chunk_items.append(item)

            elif item["type"] == "table":
                # Add table to current chunk
                table_words = item["text"].split()
                current_chunk_text.extend(table_words)
                current_chunk_items.append(item)

        # Add remaining content as final chunk
        if current_chunk_text:
            chunk = self._finalize_chunk(
                chunk_id,
                current_chunk_text,
                current_chunk_items,
                heading,
                level
            )
            chunks.append(chunk)

        return chunks

    def _finalize_chunk(
        self,
        chunk_id: int,
        words: list[str],
        items: list[dict],
        section_heading: str,
        heading_level: int
    ) -> Chunk:
        """
        Create chunk from accumulated words and items.

        Args:
            chunk_id: Chunk ID
            words: List of words
            items: List of content items
            section_heading: Section heading
            heading_level: Heading level

        Returns:
            Chunk
        """
        text = " ".join(words)

        # Check what types of content we have
        has_images = any(item.get("type") == "image" for item in items)
        has_tables = any(item.get("type") == "table" for item in items)

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "section_name": section_heading,
                "heading_level": heading_level,
                "has_images": has_images,
                "has_tables": has_tables,
                "section_type": "text",
                "chunk_strategy": "semantic"
            }
        )

    def _simple_chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Fallback to simple chunking if no structure available.

        Args:
            raw_doc: Raw document

        Returns:
            List of chunks
        """
        chunks = []
        words = raw_doc.text.split()

        chunk_id = 0
        start = 0

        while start < len(words):
            end = min(start + self.target_size, len(words))
            chunk_words = words[start:end]
            text = " ".join(chunk_words)

            chunk = self._create_chunk(
                chunk_id=chunk_id,
                text=text,
                metadata={
                    "section_name": "Unknown",
                    "heading_level": 0,
                    "section_type": "text",
                    "chunk_strategy": "simple"
                }
            )
            chunks.append(chunk)

            chunk_id += 1
            start = end - self.overlap if self.overlap > 0 else end

        return chunks
