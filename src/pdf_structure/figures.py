"""Figures on a PDF page: find them, caption them, and mark them in the text.

A PDF figure is either an embedded raster image or a cluster of vector drawing
commands (most charts and diagrams). Text extraction drops both silently, so a
reader of the Markdown never learns a figure was there, what its caption said,
or where it sat relative to the prose. This module recovers all three:

- :func:`find_vector_figures` clusters drawings into figure regions, skipping
  tables, page frames, rules and shaded text boxes.
- :func:`find_caption` links a "Figure 3: ..." style caption just above or below.
- :func:`insert_markers` writes ``![caption](image:<id>)`` into the page's
  Markdown at the figure's reading position, anchored on the caption or on the
  text line just above the figure.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

#: Caption openers. "Table 2" is included: a table rendered as a picture is a figure.
CAPTION_RE = re.compile(
    r"^(fig(?:ure)?s?|chart|exhibit|graph|diagram|image|photo(?:graph)?|illustration|"
    r"plate|map|scheme|table|source|abbildung|figura)\.?\s*[\dIVXivx]+[a-z]?\b",
    re.IGNORECASE,
)
_CAPTION_GAP = 40.0  # points between figure edge and caption line
_MD_NOISE = re.compile(r"[*_`#>|\\]")


class _Line(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def bbox(self) -> tuple[float, float, float, float]: ...


@dataclass
class Caption:
    text: str
    first_line: str
    below: bool
    """True when the caption sits under the figure."""


def _area(r: Sequence[float]) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _overlap(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection area of two boxes."""
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _significant(box: Any, paths: list[dict[str, Any]]) -> bool:
    """True when the cluster holds real drawing, not just same-size rules or boxes.

    Same idea as ``pymupdf4llm``: a cluster whose paths are all horizontal or
    vertical lines and rectangles of one width or height is decoration (a frame,
    an underline, a shaded panel behind text).
    """
    inner = [p for p in paths if p["rect"] in box and p["rect"] != box]
    if not inner:
        return False
    widths = {round(p["rect"].width) for p in inner} | {round(box.width)}
    heights = {round(p["rect"].height) for p in inner} | {round(box.height)}
    if len(widths) == 1 or len(heights) == 1:
        return False
    curves = any(item[0] in ("c", "qu") for p in inner for item in p.get("items", []))
    return curves or len(inner) >= 3


def find_vector_figures(
    page: Any,
    exclude: Sequence[Sequence[float]] = (),
    lines: Sequence[_Line] = (),
    min_edge_fraction: float = 0.05,
    max_paths: int = 20000,
) -> list[tuple[float, float, float, float]]:
    """
    Regions of a page that hold vector-drawn figures (charts, diagrams).

    Args:
        page: ``fitz.Page``.
        exclude: Boxes already accounted for: tables and raster images.
        lines: Text lines on the page, to reject shaded text boxes.
        min_edge_fraction: Both edges must be at least this share of the page.
        max_paths: Above this many drawings (maps, CAD), give up rather than stall.
    """
    page_rect = page.rect
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    if not drawings or len(drawings) > max_paths:
        return []

    paths = [
        p
        for p in drawings
        if (p["rect"].width > 3 or p["rect"].height > 3)
        and p["rect"].width < page_rect.width * 0.98
        and p["rect"].height < page_rect.height * 0.98
        and not any(_overlap(p["rect"], box) > 0.5 * max(_area(p["rect"]), 1.0) for box in exclude)
    ]
    if not paths:
        return []

    figures: list[tuple[float, float, float, float]] = []
    for box in page.cluster_drawings(drawings=paths):
        if (
            box.width < page_rect.width * min_edge_fraction
            or box.height < page_rect.height * min_edge_fraction
            or box.width > page_rect.width * 0.95 and box.height > page_rect.height * 0.9
        ):
            continue
        rect = (box.x0, box.y0, box.x1, box.y1)
        if any(_overlap(rect, other) > 0.5 * _area(rect) for other in exclude):
            continue
        if not _significant(box, paths):
            continue
        # A panel whose interior is mostly text is a styled text box, not a figure.
        text_area = sum(_overlap(rect, line.bbox) for line in lines)
        if text_area > 0.45 * _area(rect):
            continue
        figures.append(_with_labels(rect, lines))
    return figures


def _with_labels(
    rect: tuple[float, float, float, float],
    lines: Sequence[_Line],
    margin: float = 14.0,
    max_words: int = 6,
) -> tuple[float, float, float, float]:
    """Grow a drawing's box to take in its axis labels, tick values and legend.

    Those are text, so the drawing cluster stops short of them and a crop
    would cut them off. Only short lines hugging the box are taken; captions
    and body text stay out.
    """
    x0, y0, x1, y1 = rect
    for _ in range(2):  # a second pass catches labels next to labels
        for line in lines:
            lx0, ly0, lx1, ly1 = line.bbox
            text = line.text.strip()
            if not text or len(text.split()) > max_words or CAPTION_RE.match(text):
                continue
            near_x = lx1 >= x0 - margin and lx0 <= x1 + margin
            near_y = ly1 >= y0 - margin and ly0 <= y1 + margin
            if near_x and near_y:
                x0, y0, x1, y1 = min(x0, lx0), min(y0, ly0), max(x1, lx1), max(y1, ly1)
    return (x0, y0, x1, y1)


def _inside(line: _Line, rect: Sequence[float]) -> bool:
    cx = (line.bbox[0] + line.bbox[2]) / 2
    cy = (line.bbox[1] + line.bbox[3]) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def find_caption(
    rect: Sequence[float],
    lines: Sequence[_Line],
    others: Sequence[Sequence[float]] = (),
) -> Caption | None:
    """
    The "Figure N ..." caption belonging to the figure at ``rect``.

    Preference: a caption printed inside the figure's own frame near its top or
    bottom edge (report-style boxes with a title bar), then the nearest caption
    just below, then just above. A caption inside a *different* figure (``others``)
    is never taken.
    """
    x0, y0, x1, y1 = rect
    edge = max(30.0, 0.2 * (y1 - y0))
    best: tuple[int, float, int, bool] | None = None  # (rank, gap, index, below)
    for index, line in enumerate(lines):
        lx0, ly0, lx1, ly1 = line.bbox
        if lx1 <= x0 or lx0 >= x1:
            continue
        if not CAPTION_RE.match(line.text.strip()):
            continue
        if any(_inside(line, other) for other in others):
            continue
        if _inside(line, rect):
            if ly0 - y0 <= edge:
                candidate = (0, ly0 - y0, index, False)
            elif y1 - ly1 <= edge:
                candidate = (0, y1 - ly1, index, True)
            else:
                continue
        elif y1 - 2 <= ly0 <= y1 + _CAPTION_GAP:
            candidate = (1, ly0 - y1, index, True)
        elif y0 - _CAPTION_GAP <= ly1 <= y0 + 2:
            candidate = (1, y0 - ly1 + 0.5, index, False)  # ties go to the caption below
        else:
            continue
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None

    _, _, index, below = best
    first = lines[index]
    parts = [first.text.strip()]
    previous = first
    for line in lines[index + 1 : index + 4]:
        height = previous.bbox[3] - previous.bbox[1]
        if line.bbox[1] - previous.bbox[3] > max(4.0, 0.6 * height):
            break
        if abs(line.bbox[0] - first.bbox[0]) > 30 or parts[-1].endswith("."):
            break
        parts.append(line.text.strip())
        previous = line
    return Caption(text=" ".join(parts), first_line=first.text.strip(), below=below)


def share_captions(
    rects: Sequence[Sequence[float]],
    captions: list[Caption | None],
) -> list[Caption | None]:
    """
    Give uncaptioned panels the caption of a captioned figure beside them.

    "Figure 2: (left) ... (right) ..." sits under one of two side-by-side
    images; the other one is part of the same figure.
    """
    shared = list(captions)
    for i, rect in enumerate(rects):
        if shared[i] is not None:
            continue
        for j, other in enumerate(rects):
            if captions[j] is None or i == j:
                continue
            overlap = min(rect[3], other[3]) - max(rect[1], other[1])
            smaller = min(rect[3] - rect[1], other[3] - other[1])
            if smaller > 0 and overlap >= 0.5 * smaller:
                shared[i] = captions[j]
                break
    return shared


def _norm(text: str) -> str:
    return " ".join(_MD_NOISE.sub(" ", text).split()).casefold()


def _find_line(md_lines: list[str], text: str, start: int) -> int | None:
    key = _norm(text)[:50]
    if len(key) < 4:
        return None
    for index in range(start, len(md_lines)):
        if key in _norm(md_lines[index]):
            return index
    for index in range(0, start):
        if key in _norm(md_lines[index]):
            return index
    return None


def _block_end(md_lines: list[str], index: int) -> int:
    """Index just past the paragraph, list or table containing ``index``."""
    end = index + 1
    while end < len(md_lines) and md_lines[end].strip():
        end += 1
    return end


def _block_start(md_lines: list[str], index: int) -> int:
    start = index
    while start > 0 and md_lines[start - 1].strip():
        start -= 1
    return start


@dataclass
class PlacedFigure:
    """What :func:`insert_markers` needs to know about one figure."""

    marker: str
    rect: tuple[float, float, float, float]
    caption: Caption | None = None


def insert_markers(markdown: str, figures: Sequence[PlacedFigure], lines: Sequence[_Line]) -> str:
    """
    Insert each figure's marker into ``markdown`` at its reading position.

    Anchors, in order of preference: the figure's caption line (marker goes
    right before a caption below, or after a caption above); the last text
    line above the figure (marker goes after that paragraph); the first text
    line below it (marker goes before that paragraph). Unanchored figures are
    appended to the page so none is lost.
    """
    if not figures:
        return markdown
    md_lines = markdown.split("\n")
    # Insertions are collected first so earlier ones do not shift later anchors.
    inserts: list[tuple[int, int, str]] = []  # (line index, order, marker)
    unanchored: list[str] = []
    for order, figure in enumerate(sorted(figures, key=lambda f: (f.rect[1], f.rect[0]))):
        position = _anchor(md_lines, figure, lines)
        if position is None:
            unanchored.append(figure.marker)
        else:
            inserts.append((position, order, figure.marker))

    for position, _, marker in sorted(inserts, reverse=True):
        md_lines[position:position] = ["", marker, ""]
    text = "\n".join(md_lines)
    if unanchored:
        text = text.rstrip("\n") + "\n\n" + "\n\n".join(unanchored) + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


def _anchor(md_lines: list[str], figure: PlacedFigure, lines: Sequence[_Line]) -> int | None:
    x0, y0, x1, y1 = figure.rect
    caption = figure.caption
    if caption is not None:
        index = _find_line(md_lines, caption.first_line, 0)
        if index is not None:
            return _block_start(md_lines, index) if caption.below else _block_end(md_lines, index)

    def overlaps(line: _Line) -> bool:
        return line.bbox[0] < x1 and line.bbox[2] > x0

    above = [line for line in lines if line.bbox[3] <= y0 + 2 and overlaps(line)]
    if above:
        line = max(above, key=lambda item: (item.bbox[3], item.bbox[0]))
        index = _find_line(md_lines, line.text, 0)
        if index is not None:
            return _block_end(md_lines, index)

    below = [line for line in lines if line.bbox[1] >= y1 - 2 and overlaps(line)]
    if below:
        line = min(below, key=lambda item: (item.bbox[1], item.bbox[0]))
        index = _find_line(md_lines, line.text, 0)
        if index is not None:
            return _block_start(md_lines, index)
    return None
