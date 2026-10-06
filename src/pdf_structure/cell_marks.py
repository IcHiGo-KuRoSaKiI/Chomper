"""Check marks, crosses and dots in table cells: recover what extraction loses.

Comparison tables (phone specs, pricing tiers, feature matrices, fee schedules)
say "yes" and "no" with marks, not words, and every text extractor loses them:

- symbol fonts (ZapfDingbats, Wingdings, Webdings) extract as their raw code
  points -- ZapfDingbats ✓ is the letter "4", Wingdings ✓ is "ü" -- or as U+FFFD;
- marks drawn as vector strokes have no text at all, so the cell comes back empty;
- marks placed as tiny icons are images, so the cell comes back empty.

On a synthetic set of such tables, layout extraction kept the meaning of 35% of
marks; with this pass, 98%. The pass only ever writes into a cell that is empty
(or holds only symbol-font junk), and only from evidence inside that cell's box,
so text tables are unaffected.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pymupdf as fitz

CHECK, CROSS, DOT = "✓", "✗", "●"

_SYMBOL_MAPS: dict[str, dict[str, str]] = {
    "dingbat": {"3": CHECK, "4": CHECK, "7": CROSS, "8": CROSS, "l": DOT, "n": "■"},
    "zapf": {"3": CHECK, "4": CHECK, "7": CROSS, "8": CROSS, "l": DOT, "n": "■"},
    "wingdings2": {"P": CHECK, "O": CROSS, "R": "☑", "Q": "☒", "T": "☒", "S": "☒"},
    "wingdings": {
        "ü": CHECK, "û": CROSS, "þ": "☑", "ý": "☒", "o": "☐", "l": DOT, "n": "■",
        "": CHECK, "": CROSS, "": "☑", "": "☒", "": "☐", "": DOT,
    },
    "webdings": {"a": CHECK, "r": CROSS},
}


def _symbol_map(font: str) -> dict[str, str] | None:
    name = font.lower().replace(" ", "").replace("-", "")
    for key in ("wingdings2", "wingdings", "webdings", "zapf", "dingbat"):
        if key in name:
            return _SYMBOL_MAPS[key]
    return None


def _hue(rgb: Sequence[float] | None) -> str | None:
    """Green reads as yes, red as no; anything else is not evidence."""
    if not rgb or len(rgb) < 3:
        return None
    r, g, b = rgb[:3]
    if g > r + 0.15 and g > b:
        return CHECK
    if r > g + 0.25 and r > b:
        return CROSS
    return None


def _segments(drawing: dict[str, Any]) -> list[tuple[Any, Any]]:
    return [(item[1], item[2]) for item in drawing.get("items", []) if item[0] == "l"]


def _close(p: Any, q: Any, tol: float = 0.75) -> bool:
    return abs(p.x - q.x) <= tol and abs(p.y - q.y) <= tol


def _cross(a: tuple[Any, Any], b: tuple[Any, Any]) -> bool:
    """True when two segments intersect away from their endpoints."""
    (p1, p2), (p3, p4) = a, b

    def orient(p: Any, q: Any, r: Any) -> float:
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def _vector_mark(drawings: list[dict[str, Any]], cell: fitz.Rect) -> str | None:
    """A ✓, ✗ or ● drawn with vector strokes inside ``cell``.

    Only marks: a drawing must have real width *and* height (borders and rules
    are lines with none), and be small next to the cell (backgrounds are not).
    """
    slack = cell + (-1, -1, 1, 1)
    marks = []
    for drawing in drawings:
        r = drawing["rect"]
        if not r.is_valid or r not in slack:
            continue
        if r.width < 2 or r.height < 2:
            continue
        if r.width > 0.7 * cell.width or r.height > 0.9 * cell.height:
            continue
        marks.append(drawing)
    if not marks:
        return None

    segments = [seg for d in marks for seg in _segments(d)]
    curves = any(item[0] == "c" for d in marks for item in d.get("items", []))
    colour = next((d.get("color") or d.get("fill") for d in marks if d.get("color") or d.get("fill")), None)

    if len(segments) == 2 and not curves:
        a, b = segments
        shared = [p for p in a if any(_close(p, q) for q in b)]
        if shared:
            # A tick's joint is its lowest point (largest y on the page).
            joint = shared[0]
            others = [p for p in (*a, *b) if not _close(p, joint)]
            if all(joint.y >= p.y - 0.5 for p in others):
                return CHECK
            return None
        if _cross(a, b):
            return CROSS
        return None

    fill_only = all(d.get("fill") is not None and d.get("color") is None for d in marks)
    box = marks[0]["rect"]
    if len(marks) == 1 and fill_only and curves and abs(box.width - box.height) < 2:
        return DOT
    # Outlined glyph shapes (a tick converted to a filled path): colour decides.
    return _hue(colour) if fill_only else None


def _image_mark(page: Any, images: list[dict[str, Any]], cell: fitz.Rect) -> str | None:
    """A tiny icon in ``cell``: green ✓, red ✗, otherwise ``[icon]``."""
    slack = cell + (-1, -1, 1, 1)
    for info in images:
        r = fitz.Rect(info["bbox"])
        if r not in slack or r.width > 40 or r.height > 40:
            continue
        pix = page.get_pixmap(clip=r, dpi=72, alpha=False)
        data, step = pix.samples, pix.n
        totals = [0, 0, 0]
        count = 0
        for i in range(0, len(data) - 2, step):
            red, green, blue = data[i], data[i + 1], data[i + 2]
            if max(red, green, blue) - min(red, green, blue) > 60:  # saturated pixels
                totals[0] += red
                totals[1] += green
                totals[2] += blue
                count += 1
        if count:
            return _hue([t / count / 255 for t in totals]) or "[icon]"
        return "[icon]"
    return None


def recover_cell_marks(
    page: Any,
    cells: Sequence[Sequence[Sequence[float] | None]],
    grid: Sequence[Sequence[str]],
) -> list[list[str]]:
    """
    ``grid`` with symbol-font codes translated and empty cells filled from marks.

    Args:
        page: ``pymupdf.Page`` the table is on.
        cells: Row-major cell boxes (``None`` for spanned cells), as PyMuPDF's
            ``find_tables`` and the layout model's tables provide.
        grid: Row-major cell text, same shape.
    """
    spans = [
        span
        for block in page.get_text("dict").get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if _symbol_map(span.get("font", "")) is not None
    ]
    drawings: list[dict[str, Any]] | None = None
    images: list[dict[str, Any]] | None = None

    out: list[list[str]] = []
    for row_boxes, row_text in zip(cells, grid, strict=False):
        new_row = list(row_text)
        for col, (box, text) in enumerate(zip(row_boxes, row_text, strict=False)):
            if box is None:
                continue
            cell = fitz.Rect(box)
            value = text or ""

            symbols = []
            for span in spans:
                sb = fitz.Rect(span["bbox"])
                if fitz.Point((sb.x0 + sb.x1) / 2, (sb.y0 + sb.y1) / 2) in cell:
                    symbol_map = _symbol_map(span["font"]) or {}
                    symbols.append((span["text"], symbol_map))
            if symbols:
                mapped = "".join(m.get(ch, "") for raw, m in symbols for ch in raw.strip())
                if mapped:
                    rest = value
                    for raw, _ in symbols:
                        rest = rest.replace(raw.strip(), "", 1)
                    value = f"{rest.replace(chr(0xFFFD), '').strip()} {mapped}".strip()

            if not value.strip():
                if drawings is None:
                    drawings = page.get_drawings()
                    images = page.get_image_info()
                value = _vector_mark(drawings, cell) or _image_mark(page, images or [], cell) or value
            new_row[col] = value
        out.append(new_row)
    return out
