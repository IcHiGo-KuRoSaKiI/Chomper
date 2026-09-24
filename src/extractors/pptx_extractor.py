"""
PPTX extractor using python-pptx.

Extracts text, images, and slide structure from PowerPoint presentations.
"""
import logging
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.shapes.picture import Picture

from ..models.document import RawDocument
from .base import BaseExtractor
from .image_utils import image_record

logger = logging.getLogger(__name__)

EMU_PER_POINT = 12700


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
        if file_path.lower().endswith(".ppt"):
            raise ValueError(
                "Legacy binary .ppt files can't be read; save the deck as .pptx first."
            )
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

    def _extract_slides(self, prs: Presentation) -> list[dict[str, Any]]:
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

            for shape, in_group in self._iter_shapes(slide.shapes):
                # One odd shape (linked picture, OLE object, broken XML) must
                # not take the rest of the slide -- or the deck -- down with it.
                try:
                    item = self._shape_content(shape, in_group, slide_num)
                except Exception as e:
                    logger.warning(f"Skipping shape {shape.shape_id} on slide {slide_num}: {e}")
                    continue
                if item:
                    slide_data["content"].append(item)

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

    def _iter_shapes(self, shapes, in_group: bool = False):
        """Yield ``(shape, in_group)`` for every shape, descending into groups."""
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from self._iter_shapes(shape.shapes, in_group=True)
            else:
                yield shape, in_group

    def _shape_content(self, shape, in_group: bool, slide_num: int) -> dict[str, Any] | None:
        """Turn one shape into a content item, or ``None`` if it carries nothing."""
        # Pictures, including pictures dropped into a layout's picture
        # placeholder (PlaceholderPicture subclasses Picture, but its
        # shape_type is PLACEHOLDER, not PICTURE -- so check the class).
        if isinstance(shape, Picture):
            extra: dict[str, Any] = {"page": slide_num, "slide": slide_num}
            # Group children use the group's own coordinate space, so only
            # top-level shapes get a slide position (in points, like PDF).
            if not in_group and shape.left is not None and shape.top is not None:
                extra["position"] = {
                    "x0": shape.left / EMU_PER_POINT,
                    "y0": shape.top / EMU_PER_POINT,
                    "x1": (shape.left + shape.width) / EMU_PER_POINT,
                    "y1": (shape.top + shape.height) / EMU_PER_POINT,
                }
            return image_record(
                shape.image.blob, self.min_image_width, self.min_image_height, **extra
            )

        if getattr(shape, "has_table", False) and shape.has_table:
            return {"type": "table", "text": self._process_table(shape.table)}

        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text = shape.text_frame.text
            if text.strip():
                # ``placeholder_format`` raises ValueError (not AttributeError)
                # on ordinary shapes, so ``hasattr`` is not a safe probe.
                is_title = shape.is_placeholder and shape.placeholder_format.type in (
                    PP_PLACEHOLDER.TITLE,
                    PP_PLACEHOLDER.CENTER_TITLE,
                )
                return {"type": "title" if is_title else "text", "text": text}

        return None

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

    def _combine_slide_content(self, slide: dict[str, Any]) -> str:
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

    def _extract_pptx_metadata(self, prs: Presentation) -> dict[str, Any]:
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
