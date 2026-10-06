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
import os
import re
import sys
import threading
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..pdf_structure.cell_marks import recover_cell_marks, recover_mark_columns
from ..pdf_structure.figures import CAPTION_RE, Caption, find_caption, share_captions
from ..pdf_structure.lists import list_indent_hints, normalize_markdown_lists
from ..pdf_structure.sentences import ends_mid_sentence
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


class _StderrStream:
    """Write-through to whatever ``sys.stderr`` is at the time of each write."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def _route_pymupdf_messages_to_stderr() -> None:
    """Send PyMuPDF's user messages to stderr unless the user chose a destination.

    ``pymupdf.message`` prints to the ``sys.stdout`` object captured when PyMuPDF
    was imported, so ``contextlib.redirect_stdout`` does not catch it. pymupdf4llm
    flushes "=== Document parser messages ===", the OCR engine and every OCR'd
    page through it after each parse. Under the MCP stdio transport stdout is the
    JSON-RPC channel, so those lines corrupted the protocol. A ``PYMUPDF_MESSAGE``
    setting, or a stream set with ``pymupdf.set_messages``, is left alone.
    """
    if os.environ.get("PYMUPDF_MESSAGE"):
        return
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - PyMuPDF is a core dependency
        return
    current = getattr(pymupdf, "_g_out_message", None)
    if current is None or current is sys.stdout or current is sys.__stdout__:
        pymupdf.set_messages(stream=_StderrStream())


_route_pymupdf_messages_to_stderr()

_STDOUT_LOCK = threading.Lock()
_stdout_depth = 0
_saved_stdout: Any = None


@contextlib.contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Send Python-level ``print`` output to stderr while third-party code runs.

    ``contextlib.redirect_stdout`` is not safe across threads: two overlapping
    calls (the MCP server extracts in worker threads) restore in the wrong order
    and can leave ``sys.stdout`` pointing at stderr for good. This one counts
    nested and concurrent users and restores the real stdout when the last
    one leaves.
    """
    global _stdout_depth, _saved_stdout
    with _STDOUT_LOCK:
        if _stdout_depth == 0:
            _saved_stdout = sys.stdout
            sys.stdout = _StderrStream()  # type: ignore[assignment]
        _stdout_depth += 1
    try:
        yield
    finally:
        with _STDOUT_LOCK:
            _stdout_depth -= 1
            if _stdout_depth == 0:
                sys.stdout = _saved_stdout
                _saved_stdout = None


def _clear_parser_messages() -> None:
    """Empty pymupdf4llm's message buffer.

    It is flushed through ``pymupdf.message`` at the end of every
    ``parse_document`` and then "emptied" with ``truncate()`` at the end
    position, which empties nothing: every later parse replayed the old lines.
    """
    buffer = getattr(_layout, "INFO_MESSAGES", None)
    if buffer is not None:
        buffer.seek(0)
        buffer.truncate()


@functools.cache
def _ocr_engine() -> Callable[..., Any] | None:
    """The installed OCR engine (Tesseract, RapidOCR...), looked up once."""
    assert _layout is not None
    with stdout_to_stderr():
        engine = _layout.select_ocr_function()
    return engine if callable(engine) else None


def _only_pages(engine: Callable[..., Any], wanted: frozenset[int]) -> Callable[..., Any]:
    """``engine`` restricted to the 0-based page numbers in ``wanted``."""

    def run(page: Any, *args: Any, **kwargs: Any) -> Any:
        if page.number in wanted:
            return engine(page, *args, **kwargs)
        return None

    return run


def _ocr_plan(ocr: str, without_text: Sequence[int]) -> tuple[Any, Callable[..., Any] | None]:
    """``(use_ocr, ocr_function)`` for ``parse_document``.

    * ``off``: never.
    * ``force``: every page, through pymupdf4llm's ``FORCE_KEEP_OLD`` (text that
      is already extractable is masked out of the image before OCR).
    * ``auto``: only the pages in ``without_text`` (no text layer before parsing).
      pymupdf4llm's own ``SELECT_KEEP_OLD`` heuristics OCR'd most pages of
      born-digital documents with icons and boxed notes, doubling the time and
      adding garbled words to the text. Here every page is offered to OCR
      (``FORCE_KEEP_OLD``) but the engine runs only on pages without a text
      layer; a document where every page has one skips OCR entirely.
    """
    assert _layout is not None
    never = (_layout.OCRMode.NEVER, None)
    if ocr == "off" or (ocr == "auto" and not without_text):
        return never
    engine = _ocr_engine()
    if engine is None:
        return never
    if ocr == "force":
        return _layout.OCRMode.FORCE_KEEP_OLD, engine
    return _layout.OCRMode.FORCE_KEEP_OLD, _only_pages(engine, frozenset(without_text))


def _plain(markdown: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markdown)
    text = re.sub(r"[*_`#>|]", "", text)
    return " ".join(text.split())


#: A lowercase roman numeral at the start or end of a line: a front-matter folio
#: ("vi Monetary Policy Report", "iii").
_EDGE_ROMAN = re.compile(r"^[ivxl]{1,7}(?=\s|$)|(?<=\s)[ivxl]{1,7}$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50}


def _roman(token: str) -> int | None:
    """Value of a lowercase roman numeral, or None when ``token`` is not one."""
    if not token or any(c not in _ROMAN_VALUES for c in token):
        return None
    total = 0
    for i, c in enumerate(token):
        value = _ROMAN_VALUES[c]
        total += -value if i + 1 < len(token) and _ROMAN_VALUES[token[i + 1]] > value else value
    return total


def _running_key(text: str) -> str:
    return _EDGE_ROMAN.sub("#", re.sub(r"\d+", "#", _plain(text))).casefold()


# ----------------------------------------------------------------- running lines
#: A running head or foot is a short line: at most this many words.
_RUNNING_MAX_WORDS = 12
#: Hits of one running line sit at the same height: within this share of the page.
_RUNNING_Y_TOLERANCE = 0.01
#: A recurring line counts as running on at least this many pages...
_RUNNING_MIN_PAGES = 3
#: ...or on at least this share of the pages (and never on fewer than two).
_RUNNING_MIN_SHARE = 0.3
#: A bare folio: ``639``, ``K-12``, ``P.2``, ``Page 4``, ``4 of 20``.
_FOLIO = re.compile(
    r"^(?:page\s*)?([a-z]{1,3}\s?[-.–]?\s?)?(\d{1,4})(?:\s*(?:of|/)\s*\d{1,4})?$",
    re.IGNORECASE,
)
_LAST_NUMBER = re.compile(r"(\d+)\D*$")


def _folio_number(text: str) -> tuple[str, int] | None:
    """``(series, number)`` of a bare folio (``("k", 12)`` for ``K-12``), else None.

    Lowercase roman numerals (front matter: ``iii``) are their own series.
    """
    folio = _FOLIO.match(text)
    if folio:
        prefix = re.sub(r"[\s.\-–]", "", folio.group(1) or "").casefold()
        return prefix, int(folio.group(2))
    value = _roman(text)
    return ("roman", value) if value is not None else None


@dataclass(frozen=True)
class _EdgeLine:
    """A short text box in one of the two outermost rows at the top or bottom of a page."""

    page: int  # 0-based
    start: int
    end: int
    y: float  # top edge as a share of the page height
    depth: int  # 0: outermost row, 1: next row in
    text: str  # plain text


def _edge_lines(chunk: dict[str, Any], height: float) -> list[_EdgeLine]:
    """Short boxes in the top two and bottom two rows of a page.

    Rows are boxes that overlap vertically, ordered by height on the page (reading
    order can put a running head anywhere in the page text). Pictures, tables and
    empty boxes are not lines.
    """
    text: str = chunk["text"]
    items: list[tuple[float, float, int, int, str]] = []
    for box in chunk.get("page_boxes", []):
        if box["class"] in ("picture", "table"):
            continue
        start, end = box["pos"]
        plain = _plain(text[start:end])
        if plain:
            items.append((float(box["bbox"][1]), float(box["bbox"][3]), start, end, plain))
    items.sort()
    rows: list[list[tuple[float, float, int, int, str]]] = []
    bottom = -1.0
    for item in items:
        if rows and item[0] < bottom - 1:
            rows[-1].append(item)
            bottom = max(bottom, item[1])
        else:
            rows.append([item])
            bottom = item[1]
    depth_of: dict[int, int] = {}
    for depth in (1, 0):  # outermost wins when a page has fewer than four rows
        for row_index in (depth, len(rows) - 1 - depth):
            if 0 <= row_index < len(rows):
                depth_of[row_index] = depth
    height = height or 1.0
    return [
        _EdgeLine(page=-1, start=s, end=e, y=y0 / height, depth=depth, text=plain)
        for row_index, depth in depth_of.items()
        for y0, _, s, e, plain in rows[row_index]
        if len(plain.split()) <= _RUNNING_MAX_WORDS
    ]


def _often(pages: set[int], page_count: int) -> bool:
    count = len(pages)
    return count >= 2 and (count >= _RUNNING_MIN_PAGES or count >= _RUNNING_MIN_SHARE * page_count)


def _same_height(hits: list[_EdgeLine]) -> list[_EdgeLine]:
    """The hits at the line's usual height (a chapter-opening title sits lower)."""
    ys = sorted(hit.y for hit in hits)
    usual = ys[len(ys) // 2]
    return [hit for hit in hits if abs(hit.y - usual) <= _RUNNING_Y_TOLERANCE]


def running_lines(chunks: list[dict[str, Any]], heights: list[float]) -> dict[int, set[tuple[int, int]]]:
    """Running heads, running feet and folios the layout model did not label as such.

    The model labels a running head ``page-header`` on some pages and
    ``section-header`` or ``text`` on others, and alternating odd/even heads are
    two different lines, so repetition among ``page-header`` boxes alone missed
    45 CFR's "Dept. of Health and Human Services" / "45 CFR Subtitle A (10-1-23
    Edition)", its section locators ("§ 164.512") and folios ("639"), and
    Berkshire's "Notes to Consolidated Financial Statements".

    * A recurring line: a short box in the outermost row at the top or bottom of
      the page whose text, digits ignored, recurs at the same height on at least
      three pages or 30% of pages (never fewer than two, so a one-off top line is
      kept). Only the outermost row: in long training manuals the second row holds
      real headings that start many pages ("Exercise 3", "Chapter summary",
      "Illustration 2"). When the digits differ on every page
      the line must also track the page number (a folio inside the head) or
      repeat exactly somewhere, so "Question 1", "Question 2"... heading one page
      each are kept.
    * A bare folio (``639``, ``K-12``, ``Page 4``) in the two outermost rows whose
      number minus the page index is shared by enough pages, by the same rule.

    Returns:
        ``{page index: {(start, end) of each box to drop}}``, positions into the
        page chunk's text.
    """
    page_count = len(chunks)
    found: dict[int, set[tuple[int, int]]] = {}
    if page_count < 2:
        return found
    by_key: dict[str, list[_EdgeLine]] = {}
    folios: dict[tuple[str, int], list[_EdgeLine]] = {}
    for index, chunk in enumerate(chunks):
        height = heights[index] if index < len(heights) else 0.0
        for line in _edge_lines(chunk, height):
            line = _EdgeLine(index, line.start, line.end, line.y, line.depth, line.text)
            number = _folio_number(line.text)
            if number is not None:
                folios.setdefault((number[0], number[1] - index), []).append(line)
            if line.depth == 0:
                by_key.setdefault(_running_key(line.text), []).append(line)

    drop: list[_EdgeLine] = []
    for key, hits in by_key.items():
        if all(_folio_number(hit.text) is not None for hit in hits):
            continue  # bare numbers: only as folios that track the page (below)
        hits = _same_height(hits)
        if not _often({hit.page for hit in hits}, page_count):
            continue
        if "#" in key:
            texts = [hit.text for hit in hits]
            offsets = [
                int(match.group(1)) - hit.page
                for hit in hits
                if (match := _LAST_NUMBER.search(hit.text))
            ]
            repeats = len(set(texts)) < len(texts)
            tracks_page = len(set(offsets)) < len(offsets)
            if not (repeats or tracks_page):
                continue
        drop.extend(hits)
    for hits in folios.values():
        if _often({hit.page for hit in hits}, page_count):
            drop.extend(hits)
    for hit in drop:
        found.setdefault(hit.page, set()).add((hit.start, hit.end))
    return found


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
    use_ocr, ocr_function = _ocr_plan(
        ocr, [index for index, has_text in enumerate(text_layer) if not has_text]
    )
    # pymupdf4llm prints warnings with print() and flushes its parser messages
    # through pymupdf.message (routed to stderr at import, above). Under the MCP
    # stdio transport stdout is the JSON-RPC channel, so nothing may reach it.
    with stdout_to_stderr():
        _clear_parser_messages()
        parsed = _layout.parse_document(
            pdf_document,
            use_ocr=use_ocr,
            ocr_function=ocr_function,
            force_text=True,
            render_html_tables=table_format == "html",
            show_progress=False,
        )
        chunks = parsed.to_markdown(page_chunks=True, header=True, footer=True)
        _clear_parser_messages()
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
    running = running_lines(chunks, [float(page.rect.height) for page in pdf_document])

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

        dropped = set(running.get(index, ()))
        for box in boxes:
            if box["class"] not in ("page-header", "page-footer"):
                continue
            start, end = box["pos"]
            body = text[start:end]
            if not body.strip():
                continue
            key = _running_key(body)
            if _PAGE_NUMBER.match(_plain(body)) or (page_count > 1 and seen[key] >= 2):
                dropped.add((start, end))
        replacements.extend((start, end, "") for start, end in sorted(dropped))

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
        text = join_broken_paragraphs(text)
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

    Feature matrices whose mark-only columns the model merged or dropped are
    rebuilt: from the ruled grid when the columns are drawn
    (:func:`~src.pdf_structure.tables.ruled_grids_for_sparse_matrix`), else
    from the marks' own positions
    (:func:`~src.pdf_structure.cell_marks.recover_mark_columns`).
    """
    from ..pdf_structure.tables import (
        TableRegion,
        inherit_continuation_headers,
        render_ruled_pieces,
        ruled_grids_for_sparse_matrix,
    )

    regions: list[tuple[tuple[int, int], TableRegion]] = []
    direct: dict[tuple[int, int], str] = {}
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
            page = pdf_document[page_index]
            if recover_marks and len(cells) == len(grid):
                grid = recover_cell_marks(page, cells, grid)
            # Sparse feature matrices: the model merges columns that hold no text.
            pieces = ruled_grids_for_sparse_matrix(
                page,
                _box(box),
                [["" if c is None else str(c) for c in row] for row in grid],
                recover_cell_marks if recover_marks else None,
            )
            if pieces is not None and len(pieces) == 1 and pieces[0].grid is not None:
                cells, grid = pieces[0].cells or [], pieces[0].grid
            elif pieces is not None:
                direct[(page_index, box_index)] = render_ruled_pieces(pieces)
                continue
            elif recover_marks and len(cells) == len(grid):
                # Unruled: mark-only columns the model dropped altogether.
                rebuilt = recover_mark_columns(page, cells, grid)
                if rebuilt is not None:
                    cells, grid = rebuilt
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
    rendered = {key: region.markdown for (key, _), region in zip(ordered, restored, strict=True)}
    return {**rendered, **direct}


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


# ------------------------------------------------------- paragraphs across breaks
#: Words that cannot end an English sentence: a block ending in one runs on.
_RUN_ON_WORDS = frozenset(
    "a an the of to in for with on at by from into onto upon under over between among "
    "about after before during without within per via and or but nor as than that which "
    "who whom whose where when while if because although though whether is are was were "
    "be been being has have had will would shall should may might must can could not no "
    "this these those its their our your his her my such any each every both either "
    "neither other another see".split()
)
#: Cross-reference words: "paragraph" / "(d) of this section" is one sentence.
_REFERENCE_WORDS = frozenset({"paragraph", "paragraphs"})
#: First line of a block that is structure, not running prose.
_NOT_PROSE = re.compile(
    r"^\s*(?:#|\||<|!\[|[-*+•]\s|\d{1,3}[.)]\s|>|```|~~~|\$\$|\*Text in figure)"
)
#: An enumeration label that starts a new item: "(3)", "(ii)", "(A)", "a)", "iv.".
_ITEM_START = re.compile(r"^\s*(?:\((?:\d{1,3}|[ivxlc]{1,6}|[A-Za-z])\)|(?:\d{1,3}|[a-z]|[ivxlc]{1,6})[.)]\s)")
#: "...; and" / "...; or": the block closes one item of an enumeration.
_ITEM_END = re.compile(r";\s*(?:and|or)$")
_SENTENCE_END = re.compile(r"[.!?][\"'”’)]*(?:\s|$)")
#: A continuation label, not text: "(continued)", "Continued…".
_CONTINUED = re.compile(r"^\W*continued\W*$", re.IGNORECASE)


def _joiner(before: str, after: str) -> str | None:
    """How to join two blank-line separated blocks, or None to keep them apart.

    ``" "`` when ``before`` is prose that stops mid-sentence and ``after`` is the
    rest of that sentence: ``after`` starts lowercase, or ``before`` ends in a
    comma or a word no sentence ends with ("the", "with", "and") and ``after``
    starts a word. ``""`` for a word hyphenated across the break
    (``enti-`` / ``ty``). Never across headings, tables, lists, figures,
    captions or enumerated items (``...; and`` / ``(3) That ...``).
    """
    before, after = before.rstrip(), after.lstrip()
    first_before = before.split("\n", 1)[0]
    last_before = before.rsplit("\n", 1)[-1]
    first_after = after.split("\n", 1)[0]
    if not before or not after:
        return None
    if any(_NOT_PROSE.match(line) for line in (first_before, last_before, first_after)):
        return None
    if CAPTION_RE.match(_plain(first_before)) or CAPTION_RE.match(_plain(first_after)):
        return None
    tail, head = _plain(last_before), _plain(first_after)
    if not tail or not head or _ITEM_END.search(tail) or _CONTINUED.match(head):
        return None
    last_word = tail.split()[-1].casefold()
    if _ITEM_START.match(first_after):
        # A new enumerated item, unless it is a cross-reference: "paragraph" / "(d)".
        return " " if last_word in _REFERENCE_WORDS else None
    if head[0].islower():
        if re.search(r"[A-Za-z]-$", before):
            return ""
        return " " if ends_mid_sentence(tail) else None
    if not (head[0].isalnum() or head[0] in "(“\"'‘$"):
        return None
    run_on = (
        tail.endswith(",")
        or last_word in _RUN_ON_WORDS
        or last_word.endswith(("’s", "'s"))
    )
    if not (run_on and ends_mid_sentence(tail)):
        return None
    # Without the lowercase signal, ``after`` must read as the rest of a sentence:
    # running prose with a sentence end, not a label ("Or, you can write to:"),
    # a cover line or a "(continued)" marker.
    rest = _plain(after.split("\n\n", 1)[0])
    if len(rest.split()) < 6 or rest.endswith(":") or not _SENTENCE_END.search(rest):
        return None
    return " "


def join_broken_paragraphs(markdown: str) -> str:
    """Rejoin paragraphs a column break split in two (see :func:`_joiner`).

    The layout model gives each column's part of a paragraph its own region, and
    regions are written as separate blocks, so a sentence running from the foot
    of one column to the top of the next came out as two paragraphs.
    """
    blocks = markdown.split("\n\n")
    out: list[str] = []
    fenced = False
    for block in blocks:
        joined = False
        if out and not fenced and block.strip():
            how = _joiner(out[-1], block)
            if how is not None:
                head = out[-1].rstrip()
                if how == "":
                    head = head[:-1]  # the hyphen of the split word
                out[-1] = head + how + block.lstrip()
                joined = True
        if not joined:
            out.append(block)
        if block.count("```") % 2:
            fenced = not fenced
    return "\n\n".join(out)


def join_pages(texts: Sequence[str]) -> str:
    """The document text: page texts joined with a blank line, or a space where a
    sentence runs on from one page to the next (see :func:`_joiner`).

    Each page's text stays a verbatim substring, so per-page offsets still work;
    a word hyphenated across the page break keeps its hyphen for that reason.
    """
    out = ""
    for raw in texts:
        text = raw.strip("\n")
        if not text.strip():
            continue
        if not out:
            out = text
            continue
        last_block = out.rsplit("\n\n", 1)[-1]
        first_block = text.split("\n\n", 1)[0]
        how = _joiner(last_block, first_block)
        out += "\n\n" + text if how is None else how + text
    return out
