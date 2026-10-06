"""
PDF extractor using PyMuPDF and PyMuPDF4LLM.

Extracts text (with proper Markdown formatting including tables),
images, and layout from PDF documents.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import logging
import sys
from typing import Any

import pymupdf as fitz

from ..models.document import RawDocument
from .base import BaseExtractor
from .image_utils import IMAGE_MARKER_RE, image_marker, image_record
from .pymupdf_lock import PYMUPDF_LOCK

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
        table_strategy: str = 'lines_strict',
        extract_vector_figures: bool = True,
        backend: str = "auto",
        ocr: str = "auto",
        table_format: str = "markdown",
    ):
        """
        Initialize PDF extractor.

        Args:
            min_image_width: Minimum image width to extract
            min_image_height: Minimum image height to extract
            image_helper: Optional image processing helper
            use_markdown: Use pymupdf4llm for Markdown output (recommended)
            table_strategy: Table detection strategy for pymupdf4llm
            extract_vector_figures: Treat vector-drawn charts and diagrams as
                figures (rendered on request) and mark them in the text
            backend: ``layout`` (pymupdf-layout model; the default when
                installed), or ``legacy`` (pymupdf4llm without the model plus a
                second find_tables pass; much weaker tables, kept as fallback)
            ocr: ``auto`` OCRs pages that have no text layer when an OCR engine
                (Tesseract, RapidOCR) is installed; ``off``; ``force`` every page.
                Layout backend only.
            table_format: ``markdown`` pipe tables or ``html`` (keeps merged
                cells). Layout backend only.
        """
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.image_helper = image_helper
        self.use_markdown = use_markdown and PYMUPDF4LLM_AVAILABLE
        self.table_strategy = table_strategy
        self.extract_vector_figures = extract_vector_figures
        from .pdf_layout import LAYOUT_AVAILABLE, OCR_MODES

        if backend not in ("auto", "layout", "legacy"):
            raise ValueError(f"backend must be 'auto', 'layout' or 'legacy', not {backend!r}")
        if ocr not in OCR_MODES:
            raise ValueError(f"ocr must be one of {', '.join(OCR_MODES)}, not {ocr!r}")
        if table_format not in ("markdown", "html"):
            raise ValueError(f"table_format must be 'markdown' or 'html', not {table_format!r}")
        if backend == "layout" and not LAYOUT_AVAILABLE:
            raise ValueError("backend='layout' needs pymupdf-layout: pip install pymupdf-layout")
        self.backend = "layout" if backend != "legacy" and LAYOUT_AVAILABLE else "legacy"
        self.ocr = ocr
        self.table_format = table_format
        self._pages_without_text: list[int] = []
        self._ocr_pages: list[int] = []

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
        self._pages_without_text, self._ocr_pages = [], []
        if self.use_markdown and self.backend == "layout":
            full_text, pages = self._extract_with_layout(file_path, pdf_document)
        elif self.use_markdown:
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
        without_text = list(self._pages_without_text) if self.use_markdown else []
        if not IMAGE_MARKER_RE.sub("", full_text).strip():
            warning = (
                "No text layer detected; use OCR to extract text from this PDF. "
                "Scanned pages are marked in the text; fetch them with get_document_images."
            )
            metadata.update({"no_text_layer": True, "warning": warning})
            logger.warning("%s: %s", file_path, warning)
        elif without_text:
            label = "Page" if len(without_text) == 1 else "Pages"
            verb = "is a scanned image" if len(without_text) == 1 else "are scanned images"
            warning = (
                f"{label} {', '.join(map(str, without_text))} {verb} with no text layer; "
                "that text is missing. Fetch the page images with get_document_images or use OCR."
            )
            metadata["warning"] = warning
            logger.warning("%s: %s", file_path, warning)
        if without_text:
            metadata["pages_without_text_layer"] = without_text
        if self._ocr_pages:
            metadata["ocr_pages"] = list(self._ocr_pages)

        pdf_document.close()

        # Images are nested inside each page's ``content``, but callers look for a
        # top-level ``structure["images"]`` list (see ``chomper.parse`` and
        # ``chomper.extract_metadata``). Without this aggregate the images were
        # extracted and then silently dropped -- reported as issue #1.
        # ``pages`` is still present, so nothing that already walked pages breaks.
        images = [
            {**item, "page": item.get("page", page["page_number"])}
            for page in pages
            for item in page["content"]
            if item.get("type") == "image"
        ]

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={"pages": pages, "images": images}
        )

    def _extract_with_layout(self, file_path: str, pdf_document) -> tuple:
        """Markdown, figures and scanned-page handling from the layout model."""
        from .pdf_layout import extract_with_layout, join_pages

        rasters = [self._extract_page_images(pdf_document, i) for i in range(len(pdf_document))]
        result = extract_with_layout(
            pdf_document,
            file_path,
            rasters=rasters,
            page_lines=_page_lines,
            render_loader=_render_pdf_region,
            ocr=self.ocr,
            table_format=self.table_format,
            vector_figures=self.extract_vector_figures,
        )
        self._pages_without_text = result.pages_without_text
        self._ocr_pages = result.ocr_pages

        pages = []
        for index, layout_page in enumerate(result.pages):
            rect = pdf_document[index].rect
            content: list[dict[str, Any]] = []
            if layout_page.text.strip():
                content.append({
                    "type": "text",
                    "content": layout_page.text,
                    "format": "markdown",
                    "position": {"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1},
                })
            content.extend(layout_page.figures)
            pages.append({
                "page_number": index + 1,
                "content": content,
                "markdown_text": layout_page.text,
            })
        full_text = join_pages([page.text for page in result.pages])
        return full_text, pages

    def _extract_with_markdown(self, file_path: str, pdf_document) -> tuple:
        """
        Extract PDF content as Markdown with proper table formatting.

        Args:
            file_path: Path to PDF file
            pdf_document: fitz PDF document (for image extraction)

        Returns:
            Tuple of (full_text, pages_structure)
        """
        from ..pdf_structure.lists import list_indent_hints, normalize_markdown_lists
        from ..pdf_structure.tables import (
            TableRegion,
            extract_table_data,
            inherit_continuation_headers,
            replace_markdown_tables,
        )

        # Convert first: pymupdf4llm configures PyMuPDF's layout analysis, so cell
        # extraction must happen afterwards to stay deterministic with structural chunks.
        with contextlib.redirect_stdout(sys.stderr):  # keep stdout for MCP JSON-RPC
            md_pages = pymupdf4llm.to_markdown(
                file_path,
                page_chunks=True,
                table_strategy=self.table_strategy,
                ignore_images=True,  # We extract images separately for better control
                force_text=True
            )

        # Extract the same cell grids used by structural chunks. Doing this for the
        # document at once lets headerless page continuations inherit their header.
        table_regions = []
        for page_idx in range(len(pdf_document)):
            page = pdf_document[page_idx]
            try:
                found = page.find_tables()
                for table in found.tables:
                    header, rows, columns, external = extract_table_data(table)
                    table_regions.append(
                        TableRegion(
                            page=page_idx + 1,
                            bbox=tuple(float(value) for value in table.bbox),
                            rows=int(getattr(table, "row_count", 0) or 0),
                            cols=columns,
                            ordinals=frozenset(),
                            header=header,
                            data_rows=rows,
                            header_external=external,
                            page_height=float(page.rect.height),
                        )
                    )
            except Exception as exc:  # pragma: no cover - version differences
                logger.debug("Could not extract tables on page %s: %s", page_idx + 1, exc)

        replacements_by_page = {}
        ordered_regions = sorted(
            table_regions,
            key=lambda region: (region.page, region.bbox[1], region.bbox[0]),
        )
        for region in inherit_continuation_headers(ordered_regions):
            replacements_by_page.setdefault(region.page, []).append(region.markdown)

        pages = []
        text_parts = []

        # Raster images first, for every page: a logo repeated on most pages is
        # still returned by get_document_images but gets no marker in the text.
        rasters = [
            self._extract_page_images(pdf_document, idx) if idx < len(pdf_document) else []
            for idx in range(len(md_pages))
        ]
        pages_per_key: dict[str, set[int]] = {}
        for idx, records in enumerate(rasters):
            for record in records:
                pages_per_key.setdefault(record["_key"], set()).add(idx)
        repeated = {
            key for key, on in pages_per_key.items()
            if len(on) >= 3 and len(on) > 0.5 * len(md_pages)
        }
        tables_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for region in table_regions:
            tables_by_page.setdefault(region.page, []).append(region.bbox)
        self._pages_without_text = []

        for page_idx, md_page in enumerate(md_pages):
            page_text = md_page.get('text', '')
            replacements = replacements_by_page.get(page_idx + 1, [])
            page_text = replace_markdown_tables(page_text, replacements)
            if page_idx < len(pdf_document):
                page = pdf_document[page_idx]
                lines = _page_lines(page)
            else:  # pragma: no cover - defensive
                page, lines = None, []
            page_text = normalize_markdown_lists(page_text, list_indent_hints(lines))

            figures: list[dict[str, Any]] = []
            if page is not None:
                figures = self._page_figures(
                    page, file_path, rasters[page_idx], tables_by_page.get(page_idx + 1, []), lines,
                )
                page_text = self._place_figures(page, page_text, figures, lines, repeated)
            text_parts.append(page_text)

            # Build page structure
            page_data = {
                "page_number": page_idx + 1,
                "content": [],
                "markdown_text": page_text
            }

            # Add text content.
            #
            # ``position`` is always present, even in markdown mode. Downstream
            # chunkers index ``item["position"]`` unconditionally, so omitting it
            # raised ``KeyError: 'position'`` and broke the default PDF chunking
            # path entirely. Markdown text spans the whole page, so the page
            # rectangle is the honest bounding box for it.
            if page_text.strip():
                if page is not None:
                    rect = page.rect
                    position = {
                        "x0": rect.x0, "y0": rect.y0,
                        "x1": rect.x1, "y1": rect.y1,
                    }
                else:  # pragma: no cover - defensive
                    position = {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}
                page_data["content"].append({
                    "type": "text",
                    "content": page_text,
                    "format": "markdown",
                    "position": position,
                })

            page_data["content"].extend(figures)
            pages.append(page_data)

        full_text = "\n\n".join(text_parts)
        return full_text, pages

    def _page_figures(
        self,
        page,
        file_path: str,
        rasters: list[dict[str, Any]],
        table_boxes: list[tuple[float, float, float, float]],
        lines: list[_TextLine],
    ) -> list[dict[str, Any]]:
        """
        Raster images plus vector-drawn figures on one page, captioned, in
        reading order, with ids ``p<page>-<n>``.
        """
        from ..pdf_structure.figures import find_caption, find_vector_figures, share_captions

        page_no = page.number + 1
        raster_boxes = [
            (r["position"]["x0"], r["position"]["y0"], r["position"]["x1"], r["position"]["y1"])
            for r in rasters
        ]
        vectors = []
        if self.extract_vector_figures:
            for rect in find_vector_figures(page, exclude=table_boxes + raster_boxes, lines=lines):
                width_pt, height_pt = rect[2] - rect[0], rect[3] - rect[1]
                dpi = max(72.0, min(200.0, 1568 * 72 / max(width_pt, height_pt, 1.0)))
                record = image_record(
                    loader=functools.partial(_render_pdf_region, file_path, page.number, rect, dpi),
                    width=max(1, round(width_pt * dpi / 72)),
                    height=max(1, round(height_pt * dpi / 72)),
                    key=f"vector-{page_no}-{rect}",
                    page=page_no,
                    position={"x0": rect[0], "y0": rect[1], "x1": rect[2], "y1": rect[3]},
                    kind="vector",
                )
                if record:
                    vectors.append(record)

        figures = sorted(
            rasters + vectors, key=lambda r: (round(r["position"]["y0"]), r["position"]["x0"])
        )
        rects = [
            (f["position"]["x0"], f["position"]["y0"], f["position"]["x1"], f["position"]["y1"])
            for f in figures
        ]
        captions = share_captions(
            rects,
            [
                find_caption(rect, lines, others=rects[:i] + rects[i + 1:])
                for i, rect in enumerate(rects)
            ],
        )
        for n, (figure, caption) in enumerate(zip(figures, captions, strict=True), start=1):
            figure["id"] = f"p{page_no}-{n}"
            figure.setdefault("kind", "raster")
            if caption is not None:
                figure["alt"] = caption.text
                figure["_caption"] = caption
        return figures

    def _place_figures(
        self,
        page,
        page_text: str,
        figures: list[dict[str, Any]],
        lines: list[_TextLine],
        repeated: set[str],
    ) -> str:
        """Write each figure's ``![caption](image:id)`` marker into the page text."""
        from ..pdf_structure.figures import PlacedFigure, insert_markers

        page_area = abs(page.rect)
        if not page_text.strip():
            scans = [
                f for f in figures
                if f["kind"] == "raster" and _box_area(f["position"]) >= 0.5 * page_area
            ]
            if scans:
                self._pages_without_text.append(page.number + 1)
                for scan in scans:
                    scan["alt"] = (
                        f"Page {page.number + 1} is a scanned image with no text layer; "
                        "fetch this image to read it"
                    )
        placed = [
            PlacedFigure(
                marker=image_marker(f["id"], f.get("alt", "")),
                rect=(f["position"]["x0"], f["position"]["y0"], f["position"]["x1"], f["position"]["y1"]),
                caption=f.get("_caption"),
            )
            for f in figures
            if f["_key"] not in repeated
        ]
        if not page_text.strip():
            return "\n\n".join(p.marker for p in placed)
        return insert_markers(page_text, placed, lines)

    def _extract_page_images(self, pdf_document, page_idx: int) -> list[dict[str, Any]]:
        """
        Lazy image records for one page, in reading order (top to bottom).

        Nothing is decoded here: width and height come from the image table,
        and the bytes are loaded from the file only if the image is requested.
        Ids are ``p<page>-<n>``; the same id appears in the text marker.

        Args:
            pdf_document: fitz PDF document
            page_idx: Page index (0-based)

        Returns:
            List of image content items
        """
        page = pdf_document[page_idx]
        file_path = pdf_document.name
        placed = []

        for img in page.get_images(full=True):
            xref, width, height = img[0], img[2], img[3]
            if width < self.min_image_width or height < self.min_image_height:
                continue
            try:
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                try:
                    key = hashlib.sha1(pdf_document.xref_stream_raw(xref) or b"").hexdigest()
                except Exception:
                    key = f"xref-{xref}"
                for rect in rects:
                    if rect.is_empty or rect.is_infinite:
                        continue
                    placed.append((rect, xref, width, height, key))
            except Exception as e:
                logger.warning(f"Failed to read image xref {xref} on page {page_idx + 1}: {e}")

        placed.sort(key=lambda item: (round(item[0].y0), item[0].x0))
        images = []
        for n, (rect, xref, width, height, key) in enumerate(placed, start=1):
            record = image_record(
                loader=functools.partial(_load_pdf_image, file_path, xref),
                width=width,
                height=height,
                key=key,
                id=f"p{page_idx + 1}-{n}",
                page=page_idx + 1,
                position={"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1},
            )
            if record:
                images.append(record)
        return images

    @staticmethod
    def _image_bytes(pdf_document, xref: int, base_image: dict[str, Any]) -> bytes:
        """
        Bytes for one embedded image, rendered through MuPDF when the raw stream
        would come out wrong.

        ``extract_image`` returns the raw stream only. Transparency lives in a
        separate soft-mask object, so dropping it paints transparent areas
        black; JPEG 2000, JBIG2, CCITT and CMYK streams are ones clients cannot
        show. MuPDF decodes all of them, so render those to PNG instead.
        """
        smask = base_image.get("smask") or 0
        if not smask and base_image.get("ext") in ("png", "jpeg", "jpg"):
            return base_image["image"]
        try:
            pix = fitz.Pixmap(pdf_document, xref)
            if pix.colorspace and pix.colorspace.n > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if smask:
                pix = fitz.Pixmap(pix, fitz.Pixmap(pdf_document, smask))
            return pix.tobytes("png")
        except Exception as e:
            logger.debug(f"Pixmap render failed for xref {xref}, using raw stream: {e}")
            return base_image["image"]

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
                text_parts.append(image_marker(item["id"]))

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
            "extraction_method": (
                ("pymupdf-layout" if self.backend == "layout" else "pymupdf4llm")
                if self.use_markdown else "pymupdf"
            ),
        }


def _load_pdf_image(file_path: str, xref: int) -> bytes:
    """Bytes for one image, read from the file when a caller asks for it."""
    with PYMUPDF_LOCK, fitz.open(file_path) as pdf_document:
        base_image = pdf_document.extract_image(xref)
        return PDFExtractor._image_bytes(pdf_document, xref, base_image)


class _TextLine:
    """Minimal positional line for list-indent hints."""

    __slots__ = ("text", "bbox")

    def __init__(self, text: str, bbox: tuple[float, float, float, float]):
        self.text = text
        self.bbox = bbox


def _page_lines(page) -> list[_TextLine]:
    """Text lines with their boxes, ligatures expanded."""
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES
    lines = []
    for block in page.get_text("dict", flags=flags).get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if text:
                lines.append(_TextLine(text, tuple(line["bbox"])))
    return lines


def _box_area(position: dict[str, float]) -> float:
    return max(0.0, position["x1"] - position["x0"]) * max(0.0, position["y1"] - position["y0"])


def _render_pdf_region(file_path: str, page_index: int, rect: tuple[float, ...], dpi: float) -> bytes:
    """Render one page region (a vector figure) to PNG when a caller asks for it."""
    with PYMUPDF_LOCK, fitz.open(file_path) as pdf_document:
        pix = pdf_document[page_index].get_pixmap(clip=fitz.Rect(rect), dpi=round(dpi))
        return pix.tobytes("png")
