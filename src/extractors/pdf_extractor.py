"""
PDF extractor using PyMuPDF and PyMuPDF4LLM.

Extracts text (with proper Markdown formatting including tables),
images, and layout from PDF documents.
"""
import base64
import io
import logging
from typing import Any

import fitz
from PIL import Image

from ..models.document import RawDocument
from .base import BaseExtractor

# Try to import pymupdf4llm for better markdown output
try:
    import pymupdf4llm
    PYMUPDF4LLM_AVAILABLE = True
except ImportError:
    PYMUPDF4LLM_AVAILABLE = False

logger = logging.getLogger(__name__)


class PDFExtractor(BaseExtractor):
    """
    Extract content from PDF files.

    Features:
    - Markdown-formatted text extraction (with proper tables as | pipes |)
    - Image extraction with position
    - Layout preservation (reading order)
    - Table detection and Markdown formatting
    - Metadata extraction
    """

    SUPPORTED_EXTENSIONS = ['.pdf']

    def __init__(
        self,
        min_image_width: int = 100,
        min_image_height: int = 100,
        image_helper=None,
        use_markdown: bool = True,
        table_strategy: str = 'lines_strict'
    ):
        """
        Initialize PDF extractor.

        Args:
            min_image_width: Minimum image width to extract
            min_image_height: Minimum image height to extract
            image_helper: Optional image processing helper
            use_markdown: Use pymupdf4llm for Markdown output (recommended)
            table_strategy: Table detection strategy for pymupdf4llm
        """
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.image_helper = image_helper
        self.use_markdown = use_markdown and PYMUPDF4LLM_AVAILABLE
        self.table_strategy = table_strategy

        if use_markdown and not PYMUPDF4LLM_AVAILABLE:
            logger.warning(
                "pymupdf4llm not available. Install with: pip install pymupdf4llm. "
                "Falling back to basic text extraction."
            )

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from PDF.

        Args:
            file_path: Path to PDF file

        Returns:
            RawDocument with extracted content
        """
        self.validate_file(file_path)

        # Open PDF
        pdf_document = fitz.open(file_path)

        # Extract text using appropriate method
        if self.use_markdown:
            full_text, pages = self._extract_with_markdown(file_path, pdf_document)
        else:
            pages = self._extract_pages(pdf_document)
            full_text = "\n\n".join(
                self._combine_page_content(page["content"])
                for page in pages
            )

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_pdf_metadata(pdf_document))

        pdf_document.close()

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={"pages": pages}
        )

    def _extract_with_markdown(self, file_path: str, pdf_document) -> tuple:
        """
        Extract PDF content as Markdown with proper table formatting.

        Args:
            file_path: Path to PDF file
            pdf_document: fitz PDF document (for image extraction)

        Returns:
            Tuple of (full_text, pages_structure)
        """
        # Get markdown text with page chunks
        md_pages = pymupdf4llm.to_markdown(
            file_path,
            page_chunks=True,
            table_strategy=self.table_strategy,
            ignore_images=True,  # We extract images separately for better control
            force_text=True
        )

        pages = []
        text_parts = []

        for page_idx, md_page in enumerate(md_pages):
            page_text = md_page.get('text', '')
            text_parts.append(page_text)

            # Build page structure
            page_data = {
                "page_number": page_idx + 1,
                "content": [],
                "markdown_text": page_text
            }

            # Add text content
            if page_text.strip():
                page_data["content"].append({
                    "type": "text",
                    "content": page_text,
                    "format": "markdown"
                })

            # Extract images for this page
            if page_idx < len(pdf_document):
                page_images = self._extract_page_images(pdf_document, page_idx)
                page_data["content"].extend(page_images)

            pages.append(page_data)

        full_text = "\n\n".join(text_parts)
        return full_text, pages

    def _extract_page_images(self, pdf_document, page_idx: int) -> list[dict[str, Any]]:
        """
        Extract images from a specific page.

        Args:
            pdf_document: fitz PDF document
            page_idx: Page index (0-based)

        Returns:
            List of image content items
        """
        images = []
        page = pdf_document[page_idx]

        image_list = page.get_images(full=True)
        if image_list:
            logger.debug(f"Found {len(image_list)} images on page {page_idx + 1}")

        for img_index, img in enumerate(image_list):
            try:
                xref = img[0]
                masks = page.get_image_rects(xref)

                if not masks:
                    continue

                # Extract image data
                base_image = pdf_document.extract_image(xref)
                image_bytes = base_image["image"]

                # Check dimensions
                image_pil = Image.open(io.BytesIO(image_bytes))
                width, height = image_pil.size

                # Skip small images
                if width < self.min_image_width or height < self.min_image_height:
                    continue

                # Get position from first mask
                mask = masks[0]

                images.append({
                    "type": "image",
                    "content": base64.b64encode(image_bytes).decode('utf-8'),
                    "width": width,
                    "height": height,
                    "page": page_idx + 1,
                    "position": {
                        "x0": mask.x0,
                        "y0": mask.y0,
                        "x1": mask.x1,
                        "y1": mask.y1
                    }
                })

            except Exception as e:
                logger.warning(f"Failed to extract image {img_index + 1} from page {page_idx + 1}: {e}")
                continue

        return images

    def _extract_pages(self, pdf_document) -> list[dict[str, Any]]:
        """
        Extract all pages from PDF (fallback method without pymupdf4llm).

        Args:
            pdf_document: fitz PDF document

        Returns:
            List of page dictionaries
        """
        pages = []

        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            page_data = {
                "page_number": page_num + 1,
                "content": []
            }

            # Extract text blocks
            text_blocks = page.get_text("blocks")
            for block in text_blocks:
                text = block[4].strip()
                if text:
                    page_data["content"].append({
                        "type": "text",
                        "content": text,
                        "position": {
                            "x1": block[0],
                            "y1": block[1],
                            "x2": block[2],
                            "y2": block[3]
                        }
                    })

            # Extract images
            page_images = self._extract_page_images(pdf_document, page_num)
            page_data["content"].extend(page_images)

            # Sort content by position (top to bottom, left to right)
            page_data["content"] = self._sort_content_by_position(page_data["content"])

            pages.append(page_data)

        return pages

    def _sort_content_by_position(self, content: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Sort content by position (reading order).

        Args:
            content: List of content items

        Returns:
            Sorted content
        """
        def get_sort_key(item):
            pos = item.get("position", {})
            if not pos:
                return (0, 0)

            content_type = item["type"]

            # Get y coordinate (vertical position)
            if content_type == "image":
                y = pos.get("y0", 0)
                x = pos.get("x0", 0)
            else:  # text
                y = pos.get("y1", 0)
                x = pos.get("x1", 0)

            return (y, x)

        return sorted(content, key=get_sort_key)

    def _combine_page_content(self, content: list[dict[str, Any]]) -> str:
        """
        Combine page content into text (fallback method).

        Args:
            content: Page content items

        Returns:
            Combined text
        """
        text_parts = []

        for item in content:
            if item["type"] == "text":
                text_parts.append(item["content"])
            elif item["type"] == "image":
                text_parts.append(f"[Image: {item['width']}x{item['height']}]")

        return "\n".join(text_parts)

    def _extract_pdf_metadata(self, pdf_document) -> dict[str, Any]:
        """
        Extract PDF metadata.

        Args:
            pdf_document: fitz PDF document

        Returns:
            Metadata dictionary
        """
        metadata = pdf_document.metadata or {}

        return {
            "author": metadata.get("author", ""),
            "title": metadata.get("title", ""),
            "subject": metadata.get("subject", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "page_count": len(pdf_document),
            "format": "pdf",
            "extraction_method": "pymupdf4llm" if self.use_markdown else "pymupdf"
        }
