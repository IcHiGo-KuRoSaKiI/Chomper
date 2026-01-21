"""
PDF extractor using PyMuPDF.

Extracts text, images, and layout from PDF documents.
"""
import fitz
from typing import Dict, Any, List
from PIL import Image
import io
import base64
import logging
from .base import BaseExtractor
from ..models.document import RawDocument

logger = logging.getLogger(__name__)


class PDFExtractor(BaseExtractor):
    """
    Extract content from PDF files.

    Features:
    - Text extraction with position (X/Y coordinates)
    - Image extraction with position
    - Layout preservation (reading order)
    - Metadata extraction
    """

    SUPPORTED_EXTENSIONS = ['.pdf']

    def __init__(
        self,
        min_image_width: int = 100,
        min_image_height: int = 100,
        image_helper=None
    ):
        """
        Initialize PDF extractor.

        Args:
            min_image_width: Minimum image width to extract
            min_image_height: Minimum image height to extract
            image_helper: Optional image processing helper
        """
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.image_helper = image_helper

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

        # Extract pages
        pages = self._extract_pages(pdf_document)

        # Combine text from all pages
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

    def _extract_pages(self, pdf_document) -> List[Dict[str, Any]]:
        """
        Extract all pages from PDF.

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
            image_list = page.get_images(full=True)
            if image_list:
                logger.info(f"📸 [PDF-EXTRACTOR] Found {len(image_list)} images on page {page_num + 1}")

            for img_index, img in enumerate(image_list):
                try:
                    xref = img[0]
                    masks = page.get_image_rects(xref)

                    if not masks:
                        logger.debug(f"⚠️  [PDF-EXTRACTOR] Image {img_index + 1} on page {page_num + 1} has no position masks, skipping")
                        continue

                    # Extract image data
                    base_image = pdf_document.extract_image(xref)
                    image_bytes = base_image["image"]

                    # Check dimensions
                    image_pil = Image.open(io.BytesIO(image_bytes))
                    width, height = image_pil.size

                    # Skip small images
                    if width < self.min_image_width or height < self.min_image_height:
                        logger.debug(f"⚠️  [PDF-EXTRACTOR] Image {img_index + 1} on page {page_num + 1} too small ({width}x{height}), skipping (min: {self.min_image_width}x{self.min_image_height})")
                        continue

                    logger.info(f"✅ [PDF-EXTRACTOR] Extracted image {img_index + 1} from page {page_num + 1}: {width}x{height} pixels")

                    # Get position from first mask
                    mask = masks[0]

                    page_data["content"].append({
                        "type": "image",
                        "content": base64.b64encode(image_bytes).decode('utf-8'),
                        "width": width,
                        "height": height,
                        "position": {
                            "x0": mask.x0,
                            "y0": mask.y0,
                            "x1": mask.x1,
                            "y1": mask.y1
                        }
                    })

                except Exception as e:
                    logger.warning(f"❌ [PDF-EXTRACTOR] Failed to extract image {img_index + 1} from page {page_num + 1}: {e}")
                    # Skip problematic images
                    continue

            # Sort content by position (top to bottom, left to right)
            page_data["content"] = self._sort_content_by_position(page_data["content"])

            pages.append(page_data)

        return pages

    def _sort_content_by_position(self, content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort content by position (reading order).

        Args:
            content: List of content items

        Returns:
            Sorted content
        """
        def get_sort_key(item):
            pos = item["position"]
            content_type = item["type"]

            # Get y coordinate (vertical position)
            if content_type == "image":
                y = pos["y0"]
                x = pos["x0"]
            else:  # text
                y = pos["y1"]
                x = pos["x1"]

            return (y, x)

        return sorted(content, key=get_sort_key)

    def _combine_page_content(self, content: List[Dict[str, Any]]) -> str:
        """
        Combine page content into text.

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

    def _extract_pdf_metadata(self, pdf_document) -> Dict[str, Any]:
        """
        Extract PDF metadata.

        Args:
            pdf_document: fitz PDF document

        Returns:
            Metadata dictionary
        """
        metadata = pdf_document.metadata or {}

        return {
            "author": metadata.get("author", "Unknown"),
            "title": metadata.get("title", ""),
            "subject": metadata.get("subject", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "page_count": len(pdf_document),
            "format": "pdf"
        }
