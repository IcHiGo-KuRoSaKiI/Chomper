"""
PPTX chunker with slide-based structure.

Chunks PPTX documents by slides, preserving:
- Slide boundaries
- Title and content relationship
- Speaker notes
- Images and tables in context
"""
from typing import List
from ..base import BaseChunker
from ...models.document import RawDocument, Chunk


class PPTXChunker(BaseChunker):
    """
    Chunk PPTX documents by slides.

    Strategy:
    - One chunk per slide (natural boundary)
    - Preserves slide title and content
    - Includes speaker notes
    - Maintains images and tables with surrounding text
    """

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 0,  # No overlap for slides
        preserve_context: bool = True
    ):
        """
        Initialize PPTX chunker.

        Args:
            target_size: Not used for slide-based chunking
            overlap: Not used for slide-based chunking
            preserve_context: Maintain slide context
        """
        super().__init__(target_size, overlap, preserve_context)

    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        """
        Chunk PPTX document by slides.

        Args:
            raw_doc: Raw PPTX document

        Returns:
            List of chunks (one per slide)
        """
        if not raw_doc.structure or "slides" not in raw_doc.structure:
            # Fallback to simple chunking if no structure
            return self._simple_chunk(raw_doc)

        slides = raw_doc.structure["slides"]
        chunks = []

        for idx, slide in enumerate(slides):
            chunk = self._create_slide_chunk(idx, slide)
            chunks.append(chunk)

        return chunks

    def _create_slide_chunk(self, chunk_id: int, slide: dict) -> Chunk:
        """
        Create chunk from a slide.

        Args:
            chunk_id: Chunk ID
            slide: Slide dictionary

        Returns:
            Chunk
        """
        text_parts = []

        # Add slide number
        slide_num = slide.get("slide_number", chunk_id + 1)
        text_parts.append(f"--- Slide {slide_num} ---")

        # Extract title (if present)
        title = None
        has_images = False
        has_tables = False
        has_notes = False

        for item in slide.get("content", []):
            if item["type"] == "title":
                title = item["text"]
                text_parts.append(f"# {item['text']}")
            elif item["type"] == "text":
                text_parts.append(item["text"])
            elif item["type"] == "table":
                text_parts.append(item["text"])
                has_tables = True
            elif item["type"] == "image":
                text_parts.append(f"[Image: {item['width']}x{item['height']}]")
                has_images = True
            elif item["type"] == "notes":
                text_parts.append(f"Notes: {item['text']}")
                has_notes = True

        text = "\n\n".join(text_parts)

        return self._create_chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "slide_number": slide_num,
                "slide_title": title or f"Slide {slide_num}",
                "slide_layout": slide.get("layout", "Unknown"),
                "has_images": has_images,
                "has_tables": has_tables,
                "has_notes": has_notes,
                "section_type": "slide",
                "chunk_strategy": "slide"
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
            text = " ".join(chunk_words)

            chunk = self._create_chunk(
                chunk_id=chunk_id,
                text=text,
                metadata={
                    "slide_number": chunk_id + 1,
                    "section_type": "text",
                    "chunk_strategy": "simple"
                }
            )
            chunks.append(chunk)

            chunk_id += 1
            start = end

        return chunks
