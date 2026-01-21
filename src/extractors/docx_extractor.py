"""
DOCX extractor using python-docx.

Extracts text, headings, images, and tables from DOCX documents.
"""
import base64
import io
from typing import Dict, Any, List, Optional
from docx import Document
from docx.document import Document as _Document
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph
from PIL import Image

from .base import BaseExtractor
from ..models.document import RawDocument


class DOCXExtractor(BaseExtractor):
    """
    Extract content from DOCX files.

    Features:
    - Text extraction with heading hierarchy
    - Image extraction with position and dimensions
    - Table extraction
    - Structured document representation (sections by headings)
    """

    SUPPORTED_EXTENSIONS = ['.docx', '.doc']

    def __init__(
        self,
        min_image_width: int = 100,
        min_image_height: int = 100,
        image_helper=None
    ):
        """
        Initialize DOCX extractor.

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
        Extract content from DOCX.

        Args:
            file_path: Path to DOCX file

        Returns:
            RawDocument with extracted content
        """
        self.validate_file(file_path)

        # Open DOCX
        doc = Document(file_path)

        # Extract document structure
        sections = self._extract_sections(doc)

        # Combine text from all sections
        full_text = "\n\n".join(
            self._combine_section_content(section)
            for section in sections
        )

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_docx_metadata(doc))

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={"sections": sections}
        )

    def _extract_sections(self, doc: Document) -> List[Dict[str, Any]]:
        """
        Extract document sections based on heading hierarchy.

        Args:
            doc: python-docx Document

        Returns:
            List of section dictionaries
        """
        sections = []
        current_section = None

        for block in self._iter_block_items(doc):
            if isinstance(block, Paragraph):
                heading_level = self._get_heading_level(block)

                if heading_level is not None:
                    # Start new section on heading
                    if heading_level == 1 or current_section is None:
                        # Create new top-level section
                        if current_section:
                            sections.append(current_section)

                        current_section = {
                            "heading": block.text,
                            "level": heading_level,
                            "content": []
                        }
                    else:
                        # Add sub-heading as content
                        current_section["content"].append({
                            "type": "heading",
                            "level": heading_level,
                            "text": block.text
                        })
                else:
                    # Regular paragraph
                    if current_section is None:
                        current_section = {
                            "heading": "Introduction",
                            "level": 0,
                            "content": []
                        }

                    if block.text.strip():
                        current_section["content"].append({
                            "type": "text",
                            "text": block.text
                        })

                    # Extract images from paragraph
                    images = self._extract_images_from_paragraph(block, doc)
                    for img in images:
                        current_section["content"].append(img)

            elif isinstance(block, Table):
                # Extract table
                if current_section is None:
                    current_section = {
                        "heading": "Introduction",
                        "level": 0,
                        "content": []
                    }

                table_text = self._process_table(block)
                current_section["content"].append({
                    "type": "table",
                    "text": table_text
                })

        # Add final section
        if current_section:
            sections.append(current_section)

        return sections

    def _get_heading_level(self, paragraph: Paragraph) -> Optional[int]:
        """
        Get the heading level of a paragraph.

        Args:
            paragraph: Paragraph to check

        Returns:
            Heading level (1-9) or None if not a heading
        """
        if paragraph.style.name.startswith('Heading'):
            try:
                return int(paragraph.style.name.split()[-1])
            except (ValueError, IndexError):
                return None
        return None

    def _extract_images_from_paragraph(
        self,
        paragraph: Paragraph,
        doc: Document
    ) -> List[Dict[str, Any]]:
        """
        Extract images from a paragraph.

        Args:
            paragraph: Paragraph to extract from
            doc: Document object

        Returns:
            List of image dictionaries
        """
        images = []

        for run in paragraph.runs:
            # Handle images in drawings/shapes
            for drawing in run._element.findall(".//w:drawing", {
                'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            }):
                try:
                    inline_or_anchor = drawing.find(".//wp:inline", {
                        'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
                    })
                    if inline_or_anchor is None:
                        inline_or_anchor = drawing.find(".//wp:anchor", {
                            'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
                        })

                    if inline_or_anchor is not None:
                        graphic = inline_or_anchor.find(".//a:graphic", {
                            'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'
                        })
                        if graphic is not None:
                            graphicData = graphic.find(".//a:graphicData", {
                                'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'
                            })
                            if graphicData is not None:
                                pic = graphicData.find(".//pic:pic", {
                                    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'
                                })
                                if pic is not None:
                                    blip = pic.find(".//a:blip", {
                                        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'
                                    })
                                    if blip is not None:
                                        image_rid = blip.get(
                                            '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed'
                                        )
                                        if image_rid:
                                            image_part = doc.part.related_parts[image_rid]
                                            image_blob = image_part.blob

                                            # Check dimensions
                                            image_pil = Image.open(io.BytesIO(image_blob))
                                            width, height = image_pil.size

                                            if width >= self.min_image_width and height >= self.min_image_height:
                                                images.append({
                                                    "type": "image",
                                                    "content": base64.b64encode(image_blob).decode('utf-8'),
                                                    "width": width,
                                                    "height": height
                                                })
                except Exception:
                    # Skip problematic images
                    continue

            # Handle direct image elements
            for picture in run._element.findall(".//w:pict", {
                'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            }):
                try:
                    shape = picture.find(".//v:shape", {
                        'v': 'urn:schemas-microsoft-com:vml'
                    })
                    if shape is not None:
                        imagedata = shape.find(".//v:imagedata", {
                            'v': 'urn:schemas-microsoft-com:vml'
                        })
                        if imagedata is not None:
                            image_rid = imagedata.get(
                                '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}href'
                            )
                            if image_rid:
                                image_part = doc.part.related_parts[image_rid]
                                image_blob = image_part.blob

                                # Check dimensions
                                image_pil = Image.open(io.BytesIO(image_blob))
                                width, height = image_pil.size

                                if width >= self.min_image_width and height >= self.min_image_height:
                                    images.append({
                                        "type": "image",
                                        "content": base64.b64encode(image_blob).decode('utf-8'),
                                        "width": width,
                                        "height": height
                                    })
                except Exception:
                    # Skip problematic images
                    continue

        return images

    def _process_table(self, table: Table) -> str:
        """
        Convert table to text representation.

        Args:
            table: Table object

        Returns:
            Text representation of table
        """
        table_data = []
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                cell_text = " ".join(p.text for p in cell.paragraphs)
                row_data.append(cell_text)
            table_data.append(" | ".join(row_data))
        return "\n".join(table_data)

    def _iter_block_items(self, parent):
        """
        Yield paragraphs and tables in document order.

        Args:
            parent: Document or Cell

        Yields:
            Paragraph or Table objects
        """
        if isinstance(parent, _Document):
            parent_elm = parent.element.body
        elif isinstance(parent, _Cell):
            parent_elm = parent._tc
        else:
            raise ValueError("Parent must be Document or Cell")

        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _combine_section_content(self, section: Dict[str, Any]) -> str:
        """
        Combine section content into text.

        Args:
            section: Section dictionary

        Returns:
            Combined text
        """
        text_parts = []

        # Add heading
        level = section.get("level", 1)
        heading = section.get("heading", "")
        if heading:
            text_parts.append(f"{'#' * level} {heading}")

        # Add content
        for item in section.get("content", []):
            if item["type"] == "text":
                text_parts.append(item["text"])
            elif item["type"] == "heading":
                text_parts.append(f"{'#' * item['level']} {item['text']}")
            elif item["type"] == "image":
                text_parts.append(f"[Image: {item['width']}x{item['height']}]")
            elif item["type"] == "table":
                text_parts.append(item["text"])

        return "\n\n".join(text_parts)

    def _extract_docx_metadata(self, doc: Document) -> Dict[str, Any]:
        """
        Extract DOCX metadata.

        Args:
            doc: Document object

        Returns:
            Metadata dictionary
        """
        core_props = doc.core_properties

        return {
            "author": core_props.author or "Unknown",
            "title": core_props.title or "",
            "subject": core_props.subject or "",
            "created": str(core_props.created) if core_props.created else "",
            "modified": str(core_props.modified) if core_props.modified else "",
            "format": "docx"
        }
