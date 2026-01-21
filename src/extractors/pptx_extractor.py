"""
PPTX extractor using python-pptx.

Extracts text, images, and slide structure from PowerPoint presentations.
"""
import base64
import io
from typing import Dict, Any, List
from pptx import Presentation
from PIL import Image

from .base import BaseExtractor
from ..models.document import RawDocument


class PPTXExtractor(BaseExtractor):
    """
    Extract content from PPTX files.

    Features:
    - Slide-by-slide extraction
    - Text extraction (titles, body text, notes)
    - Image extraction from slides
    - Table extraction
    - Slide metadata (layout, position)
    """

    SUPPORTED_EXTENSIONS = ['.pptx', '.ppt']

    def __init__(
        self,
        min_image_width: int = 100,
        min_image_height: int = 100,
        extract_notes: bool = True,
        image_helper=None
    ):
        """
        Initialize PPTX extractor.

        Args:
            min_image_width: Minimum image width to extract
            min_image_height: Minimum image height to extract
            extract_notes: Extract speaker notes
            image_helper: Optional image processing helper
        """
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.extract_notes = extract_notes
        self.image_helper = image_helper

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from PPTX.

        Args:
            file_path: Path to PPTX file

        Returns:
            RawDocument with extracted content
        """
        self.validate_file(file_path)

        # Open PPTX
        prs = Presentation(file_path)

        # Extract slides
        slides = self._extract_slides(prs)

        # Combine text from all slides
        full_text = "\n\n".join(
            self._combine_slide_content(slide)
            for slide in slides
        )

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_pptx_metadata(prs))

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={"slides": slides}
        )

    def _extract_slides(self, prs: Presentation) -> List[Dict[str, Any]]:
        """
        Extract all slides from presentation.

        Args:
            prs: python-pptx Presentation

        Returns:
            List of slide dictionaries
        """
        slides = []

        for slide_num, slide in enumerate(prs.slides, start=1):
            slide_data = {
                "slide_number": slide_num,
                "layout": slide.slide_layout.name,
                "content": []
            }

            # Extract text from shapes
            for shape in slide.shapes:
                # Text boxes and placeholders
                if hasattr(shape, "text") and shape.text.strip():
                    # Detect if this is a title
                    is_title = hasattr(shape, "placeholder_format") and \
                               shape.placeholder_format.type == 1  # Title placeholder

                    slide_data["content"].append({
                        "type": "title" if is_title else "text",
                        "text": shape.text
                    })

                # Tables
                if shape.has_table:
                    table_text = self._process_table(shape.table)
                    slide_data["content"].append({
                        "type": "table",
                        "text": table_text
                    })

                # Images
                if shape.shape_type == 13:  # Picture
                    try:
                        image = shape.image
                        image_bytes = image.blob

                        # Check dimensions
                        image_pil = Image.open(io.BytesIO(image_bytes))
                        width, height = image_pil.size

                        if width >= self.min_image_width and height >= self.min_image_height:
                            slide_data["content"].append({
                                "type": "image",
                                "content": base64.b64encode(image_bytes).decode('utf-8'),
                                "width": width,
                                "height": height
                            })
                    except Exception:
                        # Skip problematic images
                        continue

            # Extract notes
            if self.extract_notes and slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    slide_data["content"].append({
                        "type": "notes",
                        "text": notes_text
                    })

            slides.append(slide_data)

        return slides

    def _process_table(self, table) -> str:
        """
        Convert table to text representation.

        Args:
            table: Table object

        Returns:
            Text representation
        """
        table_data = []
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                row_data.append(cell.text)
            table_data.append(" | ".join(row_data))
        return "\n".join(table_data)

    def _combine_slide_content(self, slide: Dict[str, Any]) -> str:
        """
        Combine slide content into text.

        Args:
            slide: Slide dictionary

        Returns:
            Combined text
        """
        text_parts = []

        # Add slide header
        text_parts.append(f"--- Slide {slide['slide_number']} ---")

        # Add content
        for item in slide.get("content", []):
            if item["type"] == "title":
                text_parts.append(f"# {item['text']}")
            elif item["type"] == "text":
                text_parts.append(item["text"])
            elif item["type"] == "table":
                text_parts.append(item["text"])
            elif item["type"] == "image":
                text_parts.append(f"[Image: {item['width']}x{item['height']}]")
            elif item["type"] == "notes":
                text_parts.append(f"Notes: {item['text']}")

        return "\n\n".join(text_parts)

    def _extract_pptx_metadata(self, prs: Presentation) -> Dict[str, Any]:
        """
        Extract PPTX metadata.

        Args:
            prs: Presentation object

        Returns:
            Metadata dictionary
        """
        core_props = prs.core_properties

        return {
            "author": core_props.author or "Unknown",
            "title": core_props.title or "",
            "subject": core_props.subject or "",
            "created": str(core_props.created) if core_props.created else "",
            "modified": str(core_props.modified) if core_props.modified else "",
            "slide_count": len(prs.slides),
            "format": "pptx"
        }
