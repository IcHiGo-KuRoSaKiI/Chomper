"""
PDF to Markdown on the ``pymupdf-layout`` model: one pass for text, headings,
lists, tables, figures and reading order.

Measured against Chomper's previous ``pymupdf4llm`` 0.2 + second ``find_tables``
pass on 378 ground-truth tables (ICDAR-2013 corrected + SciTSR), this lifts table
adjacency F1 from 0.42 to 0.89 and detection F1 from 0.78 to 0.96, while taking
less time per page. It also joins wrapped lines into paragraphs and finds far more
headings.

The layout model labels every region on a page (``text``, ``section-header``,
``list-item``, ``table``, ``picture``, ``caption``, ``page-header``...) and the
Markdown comes with each region's character span. This module uses those spans
to:

- replace each picture's region with an ``![caption](image:<id>)`` marker, the
  caption taken from the adjacent caption region;
- drop page headers and footers only when they really are running heads (they
  repeat across pages, or are bare page numbers). The model labels any lone line
  near the top of a page a header, and dropping those loses content;
- report scanned pages, and OCR them when an OCR engine is installed.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..pdf_structure.cell_marks import recover_cell_marks
from ..pdf_structure.figures import CAPTION_RE, Caption, find_caption, share_captions
from ..pdf_structure.lists import list_indent_hints, normalize_markdown_lists
from .image_utils import image_marker, image_record

logger = logging.getLogger(__name__)

try:
    from pymupdf4llm.helpers import document_layout as _layout

    LAYOUT_AVAILABLE = hasattr(_layout, "parse_document")
except Exception:  # pragma: no cover - pymupdf-layout not installed
    _layout = None
    LAYOUT_AVAILABLE = False

#: OCR settings accepted by :class:`~src.extractors.pdf_extractor.PDFExtractor`.
OCR_MODES = ("auto", "off", "force")

_PAGE_NUMBER = re.compile(r"^\W*(?:page\s*)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\W*$", re.IGNORECASE)
_PICTURE_TEXT = re.compile(r"<!--\s*Start of picture text\s*-->(.*?)<!--\s*End of picture text\s*-->", re.S)
_BOLD_HEADING = re.compile(r"^(#{1,6})[ \t]+\*\*(.+?)\*\*[ \t]*$", re.M)
# OCR reads bullet glyphs as stray characters after the list marker.
_OCR_JUNK_HEADING = re.compile(r"^#{1,6}[ \t]+\W*\w?\W*[ \t]*$\n?", re.M)
_OCR_BULLET = re.compile(r"^(\s*-\s)[+oO°*•·©¢e»>]\s+(?=\S)", re.M)


@dataclass
class LayoutPage:
    text: str
    figures: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LayoutResult:
    pages: list[LayoutPage]
    pages_without_text: list[int] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)


def _ocr_mode(ocr: str) -> Any:
    assert _layout is not None
    if ocr == "off":
        return _layout.OCRMode.NEVER
    if _layout.select_ocr_function() is None:
        return _layout.OCRMode.NEVER
    return _layout.OCRMode.FORCE_KEEP_OLD if ocr == "force" else _layout.OCRMode.SELECT_KEEP_OLD


def _plain(markdown: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markdown)
    text = re.sub(r"[*_`#>|]", "", text)
    return " ".join(text.split())


def _running_key(text: str) -> str:
    return re.sub(r"\d+", "#", _plain(text)).casefold()


def _box(box: dict[str, Any]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box["bbox"]
    return (float(x0), float(y0), float(x1), float(y1))


def _overlap(a: Sequence[float], b: Sequence[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _area(r: Sequence[float]) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _figure_text(slice_text: str) -> str:
    """Words the model read inside a picture, kept only when they are words.

    Chart regions yield axis ticks and legend fragments (``75<br>60<br>45``),
    which are noise; diagrams yield labels worth keeping.
    """
    match = _PICTURE_TEXT.search(slice_text)
    if not match:
        return ""
    parts = [p.strip() for p in re.split(r"<br\s*/?>|\n", match.group(1)) if p.strip()]
    tokens = " ".join(parts).split()
    if not tokens:
        return ""
    wordy = sum(1 for t in tokens if sum(c.isalpha() for c in t) >= max(2, len(t) // 2))
    if wordy < 0.6 * len(tokens) or wordy < 3:
        return ""
    return " · ".join(parts)


def _assign_captions(
    boxes: list[dict[str, Any]], text: str, pictures: list[int]
) -> dict[int, Caption]:
    """
    Pair picture regions with the caption region next to them.

    A caption belongs to the nearest picture it sits directly above or below and
    overlaps horizontally; each caption goes to one picture. "Figure N" captions
    win over notes and sources.
    """
    pairs: list[tuple[int, float, int, int, bool]] = []  # rank, gap, picture, caption, below
    for picture in pictures:
        rect = _box(boxes[picture])
        for caption in range(len(boxes)):
            if boxes[caption]["class"] != "caption" or abs(caption - picture) > 2:
                continue
            cap = _box(boxes[caption])
            shared = min(rect[2], cap[2]) - max(rect[0], cap[0])
            if shared < 0.3 * min(rect[2] - rect[0], cap[2] - cap[0]):
                continue
            below = cap[1] >= rect[1]
            gap = cap[1] - rect[3] if below else rect[1] - cap[3]
            if gap > 60:
                continue
            body = _plain(text[slice(*boxes[caption]["pos"])])
            if not body:
                continue
            rank = 0 if CAPTION_RE.match(body) else 1
            pairs.append((rank, max(gap, 0.0), picture, caption, below))

    assigned: dict[int, Caption] = {}
    used: set[int] = set()
    for _, _, picture, caption, below in sorted(pairs):
        if picture in assigned or caption in used:
            continue
        body = _plain(text[slice(*boxes[caption]["pos"])])
        assigned[picture] = Caption(body[:400], body, below=below)
        used.add(caption)
    return assigned


def extract_with_layout(
    pdf_document: Any,
    file_path: str,
    *,
    rasters: list[list[dict[str, Any]]],
    page_lines: Callable[[Any], list[Any]],
    render_loader: Callable[[str, int, tuple[float, float, float, float], float], bytes],
    ocr: str = "auto",
    table_format: str = "markdown",
    figure_text: bool = True,
    vector_figures: bool = True,
    recover_marks: bool = True,
) -> LayoutResult:
    """
    Run the layout model over ``pdf_document`` and build per-page Markdown and
    figure records.

    Args:
        rasters: Lazy raster image records per page (from the extractor).
        page_lines: Positional text lines for a page (list nesting, captions).
        render_loader: ``(path, page_index, rect, dpi) -> png bytes`` for figures
            that are not a single embedded image (vector charts, composites).
        ocr: ``auto`` OCRs pages without a text layer when an engine is installed;
            ``off`` never; ``force`` every page.
        table_format: ``markdown`` pipe tables, or ``html`` (keeps merged cells).
        figure_text: Keep word-like text read inside figures (diagram labels).
        vector_figures: Treat picture regions with no embedded image behind them
            (vector charts, diagrams) as figures.
        recover_marks: Restore ✓/✗/● in table cells from symbol fonts, vector
            strokes and tiny icons (Markdown tables only).
    """
    assert _layout is not None, "pymupdf-layout is not installed"
    # Before parsing: OCR writes recognised text into the page objects, after
    # which a scanned page looks like it always had a text layer.
    text_layer = [bool(page.get_text("text").strip()) for page in pdf_document]
    # pymupdf4llm prints progress and "Using Tesseract for OCR processing." to
    # stdout. Under the MCP stdio transport stdout is the JSON-RPC channel, so
    # every library message goes to stderr instead.
    with contextlib.redirect_stdout(sys.stderr):
        parsed = _layout.parse_document(
            pdf_document,
            use_ocr=_ocr_mode(ocr),
            force_text=True,
            render_html_tables=table_format == "html",
            show_progress=False,
        )
        chunks = parsed.to_markdown(page_chunks=True, header=True, footer=True)
    page_count = len(chunks)

    # Running heads: header/footer text that repeats on other pages (numbers ignored).
    seen: Counter[str] = Counter()
    for chunk in chunks:
        keys = {
            _running_key(chunk["text"][slice(*b["pos"])])
            for b in chunk.get("page_boxes", [])
            if b["class"] in ("page-header", "page-footer")
        }
        seen.update(k for k in keys if k)

    # Logos repeated on most pages get no marker (still returned as images).
    pages_per_key: dict[str, set[int]] = {}
    for index, records in enumerate(rasters):
        for record in records:
            pages_per_key.setdefault(record["_key"], set()).add(index)
    repeated = {k for k, on in pages_per_key.items() if len(on) >= 3 and len(on) > 0.5 * page_count}

    table_markdown = (
        _render_tables(parsed, chunks, pdf_document, recover_marks)
        if table_format == "markdown"
        else {}
    )

    result = LayoutResult(pages=[])
    for index, chunk in enumerate(chunks):
        page = pdf_document[index]
        text: str = chunk["text"]
        boxes: list[dict[str, Any]] = chunk.get("page_boxes", [])
        page_rect = (page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)
        lines = page_lines(page)
        page_rasters = rasters[index] if index < len(rasters) else []
        had_text_layer = text_layer[index]
        replacements: list[tuple[int, int, str]] = []

        for box in boxes:
            if box["class"] not in ("page-header", "page-footer"):
                continue
            start, end = box["pos"]
            body = text[start:end]
            if not body.strip():
                continue
            key = _running_key(body)
            if _PAGE_NUMBER.match(_plain(body)) or (page_count > 1 and seen[key] >= 2):
                replacements.append((start, end, ""))

        for box in boxes:
            rendered = table_markdown.get((index, box.get("index")))
            if box["class"] == "table" and rendered is not None:
                start, end = box["pos"]
                replacements.append((start, end, f"\n\n{rendered}\n\n"))

        # Figures: picture regions, backed by the embedded image when one fills the region.
        figures: list[dict[str, Any]] = []
        picture_slots: list[tuple[int, int, int]] = []  # (figure index, start, end)
        claimed: set[int] = set()
        layout_captions = _assign_captions(
            boxes, text, [i for i, b in enumerate(boxes) if b["class"] == "picture"]
        )
        for box_index, box in enumerate(boxes):
            if box["class"] != "picture":
                continue
            rect = _box(box)
            record = None
            for raster_index, raster in enumerate(page_rasters):
                pos = raster["position"]
                raster_rect = (pos["x0"], pos["y0"], pos["x1"], pos["y1"])
                inter = _overlap(rect, raster_rect)
                if inter >= 0.8 * _area(raster_rect) and _area(raster_rect) >= 0.6 * _area(rect):
                    record = dict(raster)
                    claimed.add(raster_index)
                    break
            if record is None and not vector_figures:
                continue
            if record is None:
                width_pt, height_pt = rect[2] - rect[0], rect[3] - rect[1]
                if (
                    width_pt < 0.05 * (page_rect[2] - page_rect[0])
                    or height_pt < 0.05 * (page_rect[3] - page_rect[1])
                ):
                    continue  # icon-sized: not a figure
                dpi = max(72.0, min(200.0, 1568 * 72 / max(width_pt, height_pt, 1.0)))
                record = image_record(
                    loader=functools.partial(render_loader, file_path, index, rect, dpi),
                    width=max(1, round(width_pt * dpi / 72)),
                    height=max(1, round(height_pt * dpi / 72)),
                    key=f"region-{index + 1}-{rect}",
                    page=index + 1,
                    position={"x0": rect[0], "y0": rect[1], "x1": rect[2], "y1": rect[3]},
                    kind="vector",
                )
                if record is None:
                    continue
            caption = layout_captions.get(box_index)
            if caption is not None:
                record["_caption"] = caption
            figures.append(record)
            start, end = box["pos"]
            picture_slots.append((len(figures) - 1, start, end))

        # Embedded images no picture region covers (inside tables, misread regions).
        for raster_index, raster in enumerate(page_rasters):
            if raster_index not in claimed:
                figures.append(dict(raster))

        # Ids in reading position; captions for figures the model left uncaptioned.
        order = sorted(range(len(figures)), key=lambda i: (round(figures[i]["position"]["y0"]), figures[i]["position"]["x0"]))
        rects = [
            (f["position"]["x0"], f["position"]["y0"], f["position"]["x1"], f["position"]["y1"])
            for f in figures
        ]
        captions: list[Caption | None] = []
        for i, figure in enumerate(figures):
            caption = figure.get("_caption") or find_caption(rects[i], lines, others=rects[:i] + rects[i + 1:])
            captions.append(caption)
        captions = share_captions(rects, captions)
        for n, i in enumerate(order, start=1):
            figures[i]["id"] = f"p{index + 1}-{n}"
            figures[i].setdefault("kind", "raster")
            if captions[i] is not None:
                figures[i]["alt"] = captions[i].text
            figures[i].pop("_caption", None)

        for figure_index, start, end in picture_slots:
            figure = figures[figure_index]
            if figure["_key"] in repeated:
                replacements.append((start, end, "\n\n"))
                continue
            block = image_marker(figure["id"], figure.get("alt", ""))
            label_text = _figure_text(text[start:end]) if figure_text else ""
            if label_text:
                block += f"\n\n*Text in figure:* {label_text}"
            replacements.append((start, end, f"\n\n{block}\n\n"))

        for start, end, new in sorted(replacements, key=lambda r: r[0], reverse=True):
            text = text[:start] + new + text[end:]

        # Scanned pages: a page-sized image and no text layer.
        if not had_text_layer:
            page_area = _area(page_rect)
            scans = [
                f for f, r in zip(figures, rects, strict=True)
                if f.get("kind") == "raster" and _area(r) >= 0.5 * page_area
            ]
            ocr_text = _plain(text)
            for scan in scans:
                if ocr_text:
                    scan["alt"] = f"Scanned page {index + 1}; its text below was read by OCR"
                else:
                    scan["alt"] = (
                        f"Page {index + 1} is a scanned image with no text layer; "
                        "fetch this image to read it"
                    )
            if scans:
                markers = "\n\n".join(image_marker(s["id"], s["alt"]) for s in scans)
                text = f"{markers}\n\n{text}" if ocr_text else markers
                (result.ocr_pages if ocr_text else result.pages_without_text).append(index + 1)
            if ocr_text:
                text = _OCR_BULLET.sub(r"\1", text)
                # Logos and stamps OCR into one-letter "headings" ("# a").
                text = _OCR_JUNK_HEADING.sub("", text)

        text = normalize_markdown_lists(_tidy(text), list_indent_hints(lines))
        result.pages.append(LayoutPage(text=text.strip("\n") + "\n", figures=figures))
    return result


def _column_span(table: dict[str, Any], box: dict[str, Any]) -> tuple[float, float, float, float]:
    """Table box whose left/right edges are its first and last column starts.

    The continuation check compares table edges across a page break. The
    model's boxes hug the text, so they change with the widest cell on each
    page; where the columns start does not.
    """
    y0, y1 = float(box["bbox"][1]), float(box["bbox"][3])
    starts = [float(cell[0]) for row in table.get("cells") or [] for cell in row if cell]
    if not starts:
        return _box(box)
    return (min(starts), y0, max(starts), y1)


def _render_tables(
    parsed: Any,
    chunks: list[dict[str, Any]],
    pdf_document: Any,
    recover_marks: bool = True,
) -> dict[tuple[int, int], str]:
    """
    Markdown for every table region, keyed by ``(page index, box index)``.

    Rendered from the model's cell grid rather than taken from its Markdown,
    which leaves ``|`` inside cells unescaped (splitting the column) and reads
    cell borders as strikethrough. A table continuing on the next page gets its
    header row back, as the structural chunker does. With ``recover_marks``,
    check marks and crosses that extract as symbol-font junk or not at all are
    restored (see :mod:`src.pdf_structure.cell_marks`).
    """
    from ..pdf_structure.tables import TableRegion, inherit_continuation_headers

    regions: list[tuple[tuple[int, int], TableRegion]] = []
    for page_index, chunk in enumerate(chunks):
        layout_boxes = parsed.pages[page_index].boxes if page_index < len(parsed.pages) else []
        page_height = float(pdf_document[page_index].rect.height)
        for box in chunk.get("page_boxes", []):
            box_index = box.get("index")
            if box["class"] != "table" or box_index is None or box_index >= len(layout_boxes):
                continue
            table = getattr(layout_boxes[box_index], "table", None) or {}
            grid = table.get("extract") or []
            if not grid:
                continue
            cells = table.get("cells") or []
            if recover_marks and len(cells) == len(grid):
                grid = recover_cell_marks(pdf_document[page_index], cells, grid)
            rows = tuple(tuple("" if c is None else str(c) for c in row) for row in grid)
            columns = max(len(row) for row in rows)
            regions.append((
                (page_index, box_index),
                TableRegion(
                    page=page_index + 1,
                    bbox=_column_span(table, box),
                    rows=len(rows),
                    cols=columns,
                    ordinals=frozenset(),
                    header=rows[0],
                    data_rows=rows[1:],
                    page_height=page_height,
                ),
            ))
    ordered = sorted(regions, key=lambda item: (item[1].page, item[1].bbox[1], item[1].bbox[0]))
    restored = inherit_continuation_headers([region for _, region in ordered])
    return {key: region.markdown for (key, _), region in zip(ordered, restored, strict=True)}


def _tidy(markdown: str) -> str:
    """Trailing spaces off, ``# **Title**`` to ``# Title``, at most one blank line."""
    lines = []
    in_fence = False
    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        lines.append(line if in_fence else line.rstrip())
    text = _BOLD_HEADING.sub(r"\1 \2", "\n".join(lines))
    return re.sub(r"\n{3,}", "\n\n", text)
