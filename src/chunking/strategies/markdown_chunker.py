"""
Markdown chunker with heading-aware structure preservation.

Chunks Markdown while preserving:
- Heading hierarchy
- Section boundaries
- Code blocks
- Lists
"""
from typing import List
from ..base import BaseChunker
from ...models.document import RawDocument, Chunk


class MarkdownChunker(BaseChunker):
    """
    Chunk Markdown documents preserving structure.

    Strategy:
    - Respect heading hierarchy (H1 always starts new chunk)
    - Maintain section context
    - Keep code blocks together
    - Group by sections or size
    """

    def __init__(
        self,
        target_size: int = 400,
        overlap: int = 50,
        preserve_context: bool = True,
        chunk_by_section: bool = False
    ):
        """
        Initialize Markdown chunker.

        Args:
            target_size: Target words per chunk
            overlap: Words to overlap
            preserve_context: Maintain heading context
            chunk_by_section: Chunk by sections vs semantic chunking
        """
        super().__init__(target_size, overlap, preserve_context)
        self.chunk_by_section = chunk_by_section

    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        """
        Chunk Markdown document.

        Args:
            raw_doc: Raw Markdown document

        Returns:
            List of chunks with heading context preserved
        """
        if not raw_doc.structure or "sections" not in raw_doc.structure:
            # Fallback to simple chunking
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
        heading = section.get("heading")
        level = section.get("level", 0)

        if heading:
            text_parts.append(f"{'#' * level} {heading}")

        # Add content
        has_code = False
        has_images = False

        for item in section.get("content", []):
            text = item.get("text", "")
            item_type = item.get("type", "text")

            text_parts.append(text)

            if item_type == "code_fence":
                has_code = True
            elif item_type == "image":
                has_images = True

        text = '\n'.join(text_parts)

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "section_name": heading or "Introduction",
                "heading_level": level,
                "has_code": has_code,
                "has_images": has_images,
                "section_type": "text",
                "chunk_strategy": "section"
            }
        )

    def _chunk_section_content(self, start_chunk_id: int, section: dict) -> List[Chunk]:
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
        chunk_id = start_chunk_id

        heading = section.get("heading")
        level = section.get("level", 0)

        # Add heading to first chunk
        if heading:
            current_chunk_text.append(f"{'#' * level} {heading}")

        has_code = False
        has_images = False
        in_code_block = False
        code_block_lines = []

        for item in section.get("content", []):
            text = item.get("text", "")
            item_type = item.get("type", "text")

            # Handle code blocks specially (keep together)
            if item_type == "code_fence":
                if not in_code_block:
                    in_code_block = True
                    code_block_lines = [text]
                    has_code = True
                else:
                    # End of code block
                    code_block_lines.append(text)
                    code_block_text = '\n'.join(code_block_lines)
                    current_chunk_text.append(code_block_text)
                    in_code_block = False
                    code_block_lines = []
                continue

            if in_code_block:
                code_block_lines.append(text)
                continue

            # Track images
            if item_type == "image":
                has_images = True

            # Add line
            words = text.split()
            current_chunk_text.extend(words)

            # Check if chunk is full
            if len(current_chunk_text) >= self.target_size:
                # Create chunk
                chunk = self._finalize_chunk(
                    chunk_id,
                    current_chunk_text,
                    heading,
                    level,
                    has_code,
                    has_images
                )
                chunks.append(chunk)

                # Start new chunk with overlap
                overlap_words = current_chunk_text[-self.overlap:] if self.overlap > 0 else []
                current_chunk_text = overlap_words

                # Preserve heading context in new chunk
                if self.preserve_context and heading:
                    current_chunk_text.insert(0, f"{'#' * level} {heading}")

                chunk_id += 1
                has_code = False
                has_images = False

        # Add remaining content as final chunk
        if current_chunk_text:
            chunk = self._finalize_chunk(
                chunk_id,
                current_chunk_text,
                heading,
                level,
                has_code,
                has_images
            )
            chunks.append(chunk)

        return chunks

    def _finalize_chunk(
        self,
        chunk_id: int,
        words: List[str],
        section_heading: str,
        heading_level: int,
        has_code: bool,
        has_images: bool
    ) -> Chunk:
        """
        Create chunk from accumulated words.

        Args:
            chunk_id: Chunk ID
            words: List of words
            section_heading: Section heading
            heading_level: Heading level
            has_code: Has code blocks
            has_images: Has images

        Returns:
            Chunk
        """
        text = ' '.join(words)

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "section_name": section_heading or "Introduction",
                "heading_level": heading_level,
                "has_code": has_code,
                "has_images": has_images,
                "section_type": "text",
                "chunk_strategy": "semantic"
            }
        )

    def _simple_chunk(self, raw_doc: RawDocument) -> List[Chunk]:
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
            text = ' '.join(chunk_words)

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
