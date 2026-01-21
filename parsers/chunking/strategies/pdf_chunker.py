"""
PDF chunker with layout preservation.

Chunks PDF documents while preserving:
- Page boundaries
- X/Y coordinates (reading order)
- Text → Image → Text order
"""
from typing import List
from ..base import BaseChunker
from ...models.document import RawDocument, Chunk


class PDFChunker(BaseChunker):
    """
    Chunk PDF documents preserving layout structure.

    Strategy:
    - Respects page boundaries
    - Maintains X/Y position information
    - Preserves text → image → text order
    - Groups content by pages or sections
    """

    def __init__(
        self,
        target_size: int = 400,
        overlap: int = 50,
        preserve_context: bool = True,
        chunk_by_page: bool = False
    ):
        """
        Initialize PDF chunker.

        Args:
            target_size: Target words per chunk
            overlap: Words to overlap
            preserve_context: Maintain document structure
            chunk_by_page: Chunk by page (one chunk per page) vs semantic chunking
        """
        super().__init__(target_size, overlap, preserve_context)
        self.chunk_by_page = chunk_by_page

    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        """
        Chunk PDF document.

        Args:
            raw_doc: Raw PDF document

        Returns:
            List of chunks with layout preserved
        """
        if not raw_doc.structure or "pages" not in raw_doc.structure:
            raise ValueError("PDF document must have page structure")

        pages = raw_doc.structure["pages"]
        chunks = []
        chunk_id = 0

        if self.chunk_by_page:
            # Simple: one chunk per page
            for page in pages:
                chunk = self._create_page_chunk(chunk_id, page)
                chunks.append(chunk)
                chunk_id += 1
        else:
            # Smart: chunk by content size while preserving layout
            for page in pages:
                page_chunks = self._chunk_page_content(chunk_id, page)
                chunks.extend(page_chunks)
                chunk_id += len(page_chunks)

        return chunks

    def _create_page_chunk(self, chunk_id: int, page: dict) -> Chunk:
        """
        Create chunk from entire page.

        Args:
            chunk_id: Chunk ID
            page: Page dictionary

        Returns:
            Chunk
        """
        # Combine all content
        text_parts = []
        has_images = False

        for item in page["content"]:
            if item["type"] == "text":
                text_parts.append(item["content"])
            elif item["type"] == "image":
                text_parts.append(f"[Image: {item.get('width', 0)}x{item.get('height', 0)}]")
                has_images = True

        text = "\n".join(text_parts)

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "page_number": page["page_number"],
                "has_images": has_images,
                "section_type": "text",
                "chunk_strategy": "page"
            }
        )

    def _chunk_page_content(self, start_chunk_id: int, page: dict) -> List[Chunk]:
        """
        Chunk page content by size while preserving order.

        Args:
            start_chunk_id: Starting chunk ID
            page: Page dictionary

        Returns:
            List of chunks for this page
        """
        chunks = []
        current_chunk_text = []
        current_chunk_items = []
        chunk_id = start_chunk_id

        for item in page["content"]:
            if item["type"] == "text":
                words = item["content"].split()
                current_chunk_text.extend(words)
                current_chunk_items.append(item)

                # Check if chunk is full
                if len(current_chunk_text) >= self.target_size:
                    # Create chunk
                    chunk = self._finalize_chunk(
                        chunk_id,
                        current_chunk_text,
                        current_chunk_items,
                        page["page_number"]
                    )
                    chunks.append(chunk)

                    # Start new chunk with overlap
                    overlap_words = current_chunk_text[-self.overlap:] if self.overlap > 0 else []
                    current_chunk_text = overlap_words
                    current_chunk_items = []
                    chunk_id += 1

            elif item["type"] == "image":
                # Add image to current chunk
                current_chunk_text.append(f"[Image: {item.get('width', 0)}x{item.get('height', 0)}]")
                current_chunk_items.append(item)

        # Add remaining content as final chunk
        if current_chunk_text:
            chunk = self._finalize_chunk(
                chunk_id,
                current_chunk_text,
                current_chunk_items,
                page["page_number"]
            )
            chunks.append(chunk)

        return chunks

    def _finalize_chunk(
        self,
        chunk_id: int,
        words: List[str],
        items: List[dict],
        page_number: int
    ) -> Chunk:
        """
        Create chunk from accumulated words and items.

        Args:
            chunk_id: Chunk ID
            words: List of words
            items: List of content items
            page_number: Page number

        Returns:
            Chunk
        """
        text = " ".join(words)

        # Check if chunk has images
        has_images = any(item["type"] == "image" for item in items)

        # Get position range
        positions = [item["position"] for item in items]
        if positions:
            min_y = min(pos.get("y0", pos.get("y1", 0)) for pos in positions)
            max_y = max(pos.get("y1", pos.get("y0", 0)) for pos in positions)
        else:
            min_y = max_y = 0

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "page_number": page_number,
                "has_images": has_images,
                "section_type": "text",
                "position_range": {"min_y": min_y, "max_y": max_y},
                "chunk_strategy": "semantic"
            }
        )
