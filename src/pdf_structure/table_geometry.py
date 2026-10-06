"""Table reconstruction from page geometry: rows, columns, header rows, stub
hierarchy and rules, for any table.

The layout model gives each table a lattice of row and column lines and cuts
the cell text out by character position. Where its lines are off, words are
split between cells (``Absolute val | ue of``), several columns share one cell
(``880 960 1,040``), a units row lands inside the first value (``$000 880``) and
rule glyphs (``––––``) are glued onto values. Here the same table is rebuilt
from the page itself:

- **rows** from word baselines, wrapped cell text joined back onto its row
  only when the evidence is clear (:func:`_merge_continuations`);
- **columns** from the whitespace that runs down the table body between
  phrases, which handles ruled, partly ruled and unruled tables, right-aligned
  numbers and centred marks alike (:func:`_find_columns`); a few overflowing
  labels or spanning headers may cross a gap, a body of rows may not;
- **header rows** above the first data row, spanning headers placed over the
  columns they overlap (never merged into a value);
- **stub hierarchy**: indent levels from the first column's left edges, group
  rows from emphasis (bold or larger text) with no values
  (:func:`annotate_rows`, which works on any grid);
- **rules**: runs of ``–— _ =`` and short drawn lines become ``rule_above`` /
  ``rule_below`` attributes of the rows next to them, never cells.

:func:`grid_quality` scores a grid (the model's or this one) on the defects
above, so callers can keep the model's grid unless this one is clearly better.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

Box = tuple[float, float, float, float]

EM_SPACE = " "

#: Characters a drawn-with-text rule is made of (``––––``, ``____``, ``====``).
_RULE_CHARS = frozenset("-‐‑‒–—―─━_=~═")
_DOUBLE_RULE_CHARS = frozenset("=═")
#: Dot leaders between a label and its value (``Proportion ....... 0.99``).
_LEADER = re.compile(r"^(?:[.·]{4,}|…{2,}|(?:[.·] ){3,}[.·]?)$")
_NUMERIC = re.compile(
    r"^[(\[]?[-−–+±]?[£$€¥%]?\s?(?:\d{1,3}(?:[,.\s]\d{3})+|\d+)(?:[.,]\d+)?\s?[%‰]?[)\]]?[*†‡§#a-z]?$"
)
_PLACEHOLDER = re.compile(r"^(?:[(]?[Xx][)]?|[-–—]|nil|n/?a|N/?A|\.{3}|…)$")
_YEAR = re.compile(r"^(?:19|20)[\dX]\d$")
#: A unit a column header carries: ``€m``, ``$000``, ``(000)``, ``(mn ecu)``, ``%``, ``Dr``.
_UNIT = re.compile(
    r"^\(?(?:[£$€¥]\s?(?:m|bn|k|000|'000)?|'?000s?|%|mn|bn|m|k|dr|cr|units?|pts?)"
    r"(?:\s?[a-z]{1,5})?\)?$",
    re.I,
)


def is_unit(text: str) -> bool:
    token = " ".join(text.split())
    return bool(token) and bool(_UNIT.match(token))
_CONNECTOR_END = re.compile(r"(?:[,;:\-‐–&/(]|\b(?:and|or|of|for|the|to|in|on|at|by|with|from|a|an))$", re.I)
_TOTAL_LABEL = re.compile(r"^\W*total\b", re.I)
_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi|[-,]b$|bd$", re.I)


# ---------------------------------------------------------------------------
# Page primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Word:
    """A word on the page with the style of the span it came from."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    bold: bool = False
    size: float = 0.0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class HRule:
    """A horizontal rule: drawn, or typed as a run of dashes."""

    x0: float
    x1: float
    y: float
    double: bool = False
    drawn: bool = True


def is_rule_text(text: str, width: float = 0.0, height: float = 0.0) -> bool:
    """True for a run of rule glyphs wide enough to be a rule, not a ``--`` value.

    Placeholders for "nil" or "not available" (``–``, ``—``, ``--``) are short;
    typed rules are three or more glyphs at least 1.4 line heights wide.
    """
    token = text.strip()
    if len(token) < 2 or any(ch not in _RULE_CHARS for ch in token):
        return False
    if height <= 0:
        return len(token) >= 3
    ratio = width / height
    return (len(token) >= 3 and ratio >= 1.4) or ratio >= 3.0


def is_leader_text(text: str) -> bool:
    return bool(_LEADER.match(text.strip()))


def is_numeric(text: str) -> bool:
    """A number, amount, percentage, or a placeholder (``X``, ``–``, ``nil``);
    units such as ``(000)`` are not."""
    token = " ".join(text.replace("**", "").split())
    if not token or is_unit(token):
        return False
    return bool(_NUMERIC.match(token) or _PLACEHOLDER.match(token))


def _span_bold(span: dict[str, Any]) -> bool:
    return bool(int(span.get("flags", 0)) & 16) or bool(_BOLD_FONT.search(str(span.get("font", ""))))


def _page_spans(page: Any) -> list[tuple[Box, bool, float]]:
    """Text spans of a page with bold flag and size, computed once per page."""
    cached = getattr(page, "_chomper_spans", None)
    if cached is not None:
        return list(cached)
    flags = 0
    try:
        import pymupdf

        flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    except (ImportError, AttributeError):  # pragma: no cover - old PyMuPDF
        flags = 0
    spans: list[tuple[Box, bool, float]] = []
    for block in page.get_text("dict", flags=flags).get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if not str(span.get("text", "")).strip():
                    continue
                x0, y0, x1, y1 = span["bbox"]
                spans.append(((float(x0), float(y0), float(x1), float(y1)), _span_bold(span), float(span.get("size", 0.0))))
    try:
        page._chomper_spans = spans
    except AttributeError:  # pragma: no cover - slotted page objects
        pass
    return spans


def _raw_words(page: Any) -> list[tuple[Any, ...]]:
    from .tables import _page_words

    return list(_page_words(page))


def page_words(page: Any, region: Sequence[float]) -> list[Word]:
    """Words whose centre lies in ``region``, with bold and size from their span."""
    x0, y0, x1, y1 = region
    raw = [
        w for w in _raw_words(page)
        if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1 and str(w[4]).strip()
    ]
    spans = [
        s for s in _page_spans(page)
        if s[0][2] >= x0 - 2 and s[0][0] <= x1 + 2 and s[0][3] >= y0 - 2 and s[0][1] <= y1 + 2
    ]
    words: list[Word] = []
    for w in raw:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        bold, size = False, float(w[3] - w[1]) / 1.2
        best = -1.0
        for box, span_bold, span_size in spans:
            if box[0] - 0.5 <= cx <= box[2] + 0.5 and box[1] - 0.5 <= cy <= box[3] + 0.5:
                area = (box[2] - box[0]) * (box[3] - box[1])
                score = 1.0 / (1.0 + area)  # the tightest span containing the word
                if score > best:
                    best, bold, size = score, span_bold, span_size
        words.append(Word(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]), bold, size))
    # Words far taller than the text around them are not text lines: an OCR
    # pass can leave an invisible word whose box covers a whole block, and
    # vertical text has a tall box. They would fuse every line they touch.
    if words:
        heights = sorted(w.h for w in words)
        typical = heights[len(heights) // 2]
        words = [w for w in words if w.h <= 3.0 * typical]
    return words


def _page_drawings(page: Any) -> list[dict[str, Any]]:
    cached = getattr(page, "_chomper_drawings", None)
    if cached is None:
        try:
            cached = page.get_drawings()
        except Exception:  # pragma: no cover - damaged content streams
            cached = []
        try:
            page._chomper_drawings = cached
        except AttributeError:  # pragma: no cover
            pass
    return list(cached)


def drawn_rules(page: Any, region: Sequence[float]) -> tuple[list[HRule], list[tuple[float, float, float]]]:
    """Horizontal and vertical lines drawn in ``region`` (thin rectangles count).

    Returns ``(horizontal rules, vertical rules as (x, y0, y1))``.
    """
    rx0, ry0, rx1, ry1 = region
    hrules: list[HRule] = []
    vrules: list[tuple[float, float, float]] = []
    for drawing in _page_drawings(page):
        for item in drawing.get("items", []):
            if item[0] == "l":
                p, q = item[1], item[2]
                x0, x1 = sorted((float(p.x), float(q.x)))
                y0, y1 = sorted((float(p.y), float(q.y)))
            elif item[0] == "re":
                r = item[1]
                x0, y0, x1, y1 = float(r.x0), float(r.y0), float(r.x1), float(r.y1)
            else:
                continue
            w, h = x1 - x0, y1 - y0
            if x1 < rx0 - 1 or x0 > rx1 + 1 or y1 < ry0 - 3 or y0 > ry1 + 3:
                continue
            if h <= 2.0 and w >= 4.0:
                hrules.append(HRule(max(x0, rx0), min(x1, rx1), (y0 + y1) / 2))
            elif w <= 2.0 and h >= 4.0:
                vrules.append(((x0 + x1) / 2, max(y0, ry0), min(y1, ry1)))
    # Merge collinear pieces (one rule drawn as several strokes) and pairs that
    # form a double rule.
    hrules.sort(key=lambda r: (round(r.y, 1), r.x0))
    merged: list[HRule] = []
    for rule in hrules:
        last = merged[-1] if merged else None
        if last is not None and abs(last.y - rule.y) <= 0.6 and rule.x0 <= last.x1 + 1.5:
            merged[-1] = HRule(last.x0, max(last.x1, rule.x1), last.y, last.double)
        else:
            merged.append(rule)
    return merged, vrules


# ---------------------------------------------------------------------------
# Lines and phrases
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    """A phrase on one line: words close together, or one rule glyph run."""

    words: list[Word]
    kind: str = "text"  # text | rule

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def y0(self) -> float:
        return min(w.y0 for w in self.words)

    @property
    def y1(self) -> float:
        return max(w.y1 for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bold(self) -> bool:
        return all(w.bold for w in self.words)

    @property
    def size(self) -> float:
        return max(w.size for w in self.words)


def group_lines(words: Sequence[Word]) -> list[list[Word]]:
    """Words grouped into text lines, top to bottom.

    A word joins a line when its vertical centre is within 0.3 heights of the
    line's centre, or when it is smaller (a superscript, a footnote mark) and
    sits inside the line's band. Bands do not grow: a cell centred between
    two lines of its neighbour (a one-line cell in a two-line row) is a line
    of its own, not a bridge that fuses both.
    """
    lines: list[list[Word]] = []
    bands: list[tuple[float, float]] = []
    for word in sorted(words, key=lambda w: (w.yc, w.x0)):
        placed = False
        for index in range(len(lines) - 1, max(-1, len(lines) - 4), -1):
            y0, y1 = bands[index]
            h = y1 - y0
            centre = (y0 + y1) / 2
            same = abs(word.yc - centre) <= 0.3 * min(h, word.h)
            small = word.h < 0.85 * h and word.y0 >= y0 - 1.0 and word.y1 <= y1 + 1.0
            if same or small:
                lines[index].append(word)
                if h * 1.15 < word.h <= h * 2.0 and same:  # the line's main text is the taller one
                    bands[index] = (word.y0, word.y1)
                placed = True
                break
        if not placed:
            lines.append([word])
            bands.append((word.y0, word.y1))
    for line in lines:
        line.sort(key=lambda w: w.x0)
    lines.sort(key=lambda line: min(w.yc for w in line))
    return lines


def _gap_threshold(line: Sequence[Word]) -> float:
    heights = sorted(w.h for w in line if not is_rule_text(w.text, w.x1 - w.x0, w.h))
    h = heights[len(heights) // 2] if heights else line[0].h
    return max(0.45 * h, 2.5)


def split_segments(line: Sequence[Word], vrules: Sequence[tuple[float, float, float]] = ()) -> list[Segment]:
    """Split a text line into phrases at wide gaps, vertical rules and leaders.

    Dot leaders are dropped (they only bridge a gap); rule glyph runs become
    ``rule`` segments.
    """
    threshold = _gap_threshold(line)
    segments: list[Segment] = []
    current: list[Word] = []
    current_kind = "text"
    dots: list[Word] = []

    def flush() -> None:
        nonlocal current
        if current:
            segments.append(Segment(current, current_kind))
        current = []

    for word in line:
        if word.text in (".", "·"):
            dots.append(word)
            continue
        if len(dots) >= 3:  # spaced leader ". . . ." between phrases
            flush()
        elif dots:
            current.extend(dots)
        dots = []
        if is_leader_text(word.text):
            flush()
            continue
        kind = "rule" if is_rule_text(word.text, word.x1 - word.x0, word.h) else "text"
        if current:
            prev = current[-1]
            gap = word.x0 - prev.x1
            ruled = any(prev.x1 - 0.5 <= x <= word.x0 + 0.5 and y0 <= word.yc <= y1 for x, y0, y1 in vrules)
            if gap > threshold or ruled or kind != current_kind or kind == "rule":
                flush()
        current_kind = kind
        current.append(word)
    if dots and len(dots) < 3 and current:
        current.extend(dots)
    flush()
    return _attach_currency(segments)


_CURRENCY = frozenset("$£€¥")


def _attach_currency(segments: list[Segment]) -> list[Segment]:
    """A lone currency sign set apart from its amount (``$    131,182``) is
    part of the amount, not a column of its own."""
    out: list[Segment] = []
    for seg in segments:
        prev = out[-1] if out else None
        if (
            prev is not None and prev.kind == "text" and seg.kind == "text"
            and prev.text in _CURRENCY and is_numeric(seg.text)
            and seg.x0 - prev.x1 <= 80.0
        ):
            out[-1] = Segment(prev.words + seg.words)
        else:
            out.append(seg)
    return out


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


def _find_gaps(lines: Sequence[Sequence[Segment]], width: float) -> list[tuple[float, float]]:
    """Whitespace gaps that run down the body of the table, left to right.

    A gap is an x interval that, in the body lines, few phrases cross
    (``crossing <= 10%`` of the lines that have phrases on both sides of it,
    and none when fewer than ten lines witness it). Lines above the body (the
    header zone) and lines holding a single phrase (section labels spanning
    the columns, titles, notes) are left out, so spanning text does not hide
    the columns under it.
    """
    texts = [[s for s in line if s.kind == "text"] for line in lines]
    counts = [len(t) for t in texts]
    if not counts or max(counts) < 2:
        return []
    most = max(counts)
    need = max(2, -(-most * 6 // 10))
    start = next(i for i, n in enumerate(counts) if n >= need)
    body = [t for t in texts[start:] if len(t) >= 2]
    segs = [s for t in body for s in t]
    edges = sorted({round(s.x0, 2) for s in segs} | {round(s.x1, 2) for s in segs})
    gaps: list[tuple[float, float]] = []
    run: tuple[float, float] | None = None
    for a, b in zip(edges, edges[1:], strict=False):
        if b - a < 0.3:
            continue
        crossing = sum(1 for s in segs if s.x0 <= a + 0.01 and s.x1 >= b - 0.01)
        witness = sum(
            1 for t in body
            if any(s.x1 <= a + 0.01 for s in t) and any(s.x0 >= b - 0.01 for s in t)
        )
        valid = witness >= 1 and crossing <= (witness // 10 if witness >= 10 else 0)
        if valid:
            run = (run[0], b) if run is not None and abs(run[1] - a) < 0.02 else (a, b)
            if gaps and run[0] == gaps[-1][0]:
                gaps[-1] = run
            else:
                gaps.append(run)
        else:
            run = None
    return gaps


@dataclass
class Column:
    x0: float  # boundary to the left (gap middle), -inf for the first
    x1: float  # boundary to the right, +inf for the last
    left: float = 0.0  # leftmost content edge
    right: float = 0.0  # rightmost content edge
    align: str = "left"


def _columns_from_gaps(gaps: Sequence[tuple[float, float]], x0: float, x1: float) -> list[Column]:
    bounds = [x0] + [(a + b) / 2 for a, b in gaps] + [x1]
    return [Column(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _place(seg: Segment, columns: Sequence[Column]) -> tuple[int, int]:
    """Columns a phrase covers: ``(first, last)``; one column unless it spans."""
    width = max(seg.x1 - seg.x0, 0.1)
    overlaps = [_overlap(seg.x0, seg.x1, c.x0, c.x1) for c in columns]
    best = max(range(len(columns)), key=lambda i: overlaps[i])
    if overlaps[best] <= 0:  # a zero-width word: nearest column
        best = min(range(len(columns)), key=lambda i: abs((columns[i].x0 + columns[i].x1) / 2 - seg.x0))
        return best, best
    covered = [i for i, o in enumerate(overlaps) if o >= max(3.0, 0.2 * width)]
    if len(covered) >= 2:
        return covered[0], covered[-1]
    return best, best


# ---------------------------------------------------------------------------
# The reconstructed table
# ---------------------------------------------------------------------------


@dataclass
class GeoCell:
    text: str = ""
    span: int = 1
    words: list[Word] = field(default_factory=list)

    @property
    def bold(self) -> bool:
        return bool(self.words) and all(w.bold for w in self.words)


@dataclass
class GeoRow:
    cells: list[GeoCell]
    y0: float
    y1: float
    rule_above: str = "none"
    rule_above_cols: list[int] = field(default_factory=list)
    rule_below: str = "none"
    rule_below_cols: list[int] = field(default_factory=list)
    lines: int = 1

    def filled(self) -> list[int]:
        return [i for i, c in enumerate(self.cells) if c.text]


@dataclass
class GeoTable:
    """A table rebuilt from page geometry."""

    bbox: Box
    columns: list[Column]
    rows: list[GeoRow]
    title: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ruled: bool = False

    @property
    def grid(self) -> list[list[str]]:
        return [[c.text for c in row.cells] for row in self.rows]

    @property
    def cell_boxes(self) -> list[list[Box | None]]:
        """Cell rectangles; a spanning cell covers its columns, which get ``None``."""
        boxes: list[list[Box | None]] = []
        lo, hi = self.bbox[0], self.bbox[2]
        for row in self.rows:
            out: list[Box | None] = []
            covered = 0
            for i, cell in enumerate(row.cells):
                if covered:
                    out.append(None)
                    covered -= 1
                    continue
                last = min(len(self.columns) - 1, i + max(1, cell.span) - 1)
                out.append((max(self.columns[i].x0, lo), row.y0, min(self.columns[last].x1, hi), row.y1))
                covered = last - i
            boxes.append(out)
        return boxes

    def is_clean_grid(self) -> bool:
        """High-confidence borderless table, for text the layout model did not
        call a table: 3+ rows; 3+ columns, or 2 with a text header over a
        numeric column; no spanning cell below the header; cells filled (60%+),
        short (6 words at most) and 40%+ numeric outside the first column."""
        rows = self.rows
        cols = len(self.columns)
        if len(rows) < 3 or cols < 2:
            return False
        cells = [c for r in rows for c in r.cells]
        filled = [c for c in cells if c.text]
        if len(filled) < 0.6 * len(cells):
            return False
        if any(len(c.text.split()) > 6 for c in filled):
            return False
        if any(c.span > 1 for r in rows[1:] for c in r.cells):
            return False
        values = [c.text for r in rows[1:] for c in r.cells[1:] if c.text]
        if not values or sum(is_numeric(v) for v in values) < 0.4 * len(values):
            return False
        if cols == 2:
            head = rows[0].cells[1].text
            return bool(head) and not is_numeric(head) and len(rows) >= 4
        return True


def _rule_kind(seg_or_rule: Segment | HRule) -> str:
    if isinstance(seg_or_rule, HRule):
        return "double" if seg_or_rule.double else "single"
    return "double" if any(ch in _DOUBLE_RULE_CHARS for ch in seg_or_rule.text) else "single"


def _stronger(a: str, b: str) -> str:
    order = {"none": 0, "single": 1, "double": 2}
    return a if order[a] >= order[b] else b


def reconstruct(page: Any, bbox: Sequence[float], *, words: Sequence[Word] | None = None) -> GeoTable | None:
    """Rebuild the table in ``bbox`` from the page's words and drawings.

    Returns ``None`` when no column structure is found (fewer than two
    columns or two rows).
    """
    region: Box = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    if words is None:
        words = page_words(page, (region[0] - 1, region[1] - 1, region[2] + 1, region[3] + 1))
    if len(words) < 4:
        return None
    hrules, vrules = drawn_rules(page, region)
    tall = [v for v in vrules if v[2] - v[1] >= 0.5 * (region[3] - region[1])]
    lines = [split_segments(line, vrules) for line in group_lines(words)]
    lines = [line for line in lines if line]
    width = max(s.x1 for line in lines for s in line) - min(s.x0 for line in lines for s in line)
    gaps = _find_gaps(lines, width)
    # Tall vertical rules separate columns even where no line shows a gap
    # (sparse columns): add them where no body phrase crosses.
    for x, _, _ in tall:
        if any(a - 1 <= x <= b + 1 for a, b in gaps):
            continue
        crossing = sum(1 for line in lines for s in line if s.kind == "text" and s.x0 < x - 1 < x + 1 < s.x1)
        has_left = any(s.x1 <= x for line in lines for s in line)
        has_right = any(s.x0 >= x for line in lines for s in line)
        if crossing == 0 and has_left and has_right:
            gaps.append((x - 0.5, x + 0.5))
    gaps.sort()
    if not gaps:
        return None
    columns = _columns_from_gaps(gaps, region[0], region[2])

    # Rows: one per line that holds text; rule-only lines become rules.
    rows: list[GeoRow] = []
    rules: list[tuple[float, float, float, str]] = []  # x0, x1, y, kind
    for line in lines:
        texts = [s for s in line if s.kind == "text"]
        for seg in line:
            if seg.kind == "rule":
                rules.append((seg.x0, seg.x1, (seg.y0 + seg.y1) / 2, _rule_kind(seg)))
        if not texts:
            continue
        cells = [GeoCell() for _ in columns]
        placed: tuple[int, int] | None = None  # columns of the previous phrase
        previous: Segment | None = None
        for seg in texts:
            first, last = _place(seg, columns)
            if (
                placed is not None and previous is not None and first <= placed[1]
                and seg.x0 - previous.x1 <= 1.5 * max(w.h for w in seg.words)
            ):
                # Shares a column with the phrase just before it (a widely
                # spaced spanning header): one cell.
                first, last = placed[0], max(last, placed[1])
            previous = seg
            cell = cells[first]
            cell.text = f"{cell.text} {seg.text}".strip()
            cell.words.extend(seg.words)
            cell.span = max(cell.span, last - first + 1)
            placed = (first, last)
        rows.append(GeoRow(cells, min(s.y0 for s in texts), max(s.y1 for s in texts)))
    if len(rows) < 2:
        return None

    table_width = region[2] - region[0]
    full_width = [r for r in hrules if r.x1 - r.x0 >= 0.8 * table_width]
    rows, ruled = _rows_from_rule_bands(rows, sorted(r.y for r in full_width))
    for rule in hrules:
        if ruled and rule in full_width:
            continue
        rules.append((rule.x0, rule.x1, rule.y, _rule_kind(rule)))
    _attach_rules(rows, columns, rules)
    if not ruled:
        rows = _merge_header_lines(rows)
        rows = _merge_continuations(rows, columns)
    table = GeoTable(region, columns, rows, ruled=ruled)
    _split_title_and_notes(table)
    if len(table.rows) < 2 or len([c for c in range(len(columns)) if any(r.cells[c].text for r in table.rows)]) < 2:
        return None
    _drop_empty_columns(table)
    _measure_columns(table)
    return table


def _attach_rules(rows: list[GeoRow], columns: Sequence[Column], rules: Sequence[tuple[float, float, float, str]]) -> None:
    """Give each rule to the row next to it: ``rule_above`` of the row below,
    or ``rule_below`` of the row above when it sits closer to that one (an
    underline) or there is no row below."""
    for x0, x1, y, kind in rules:
        cols = [
            i for i, c in enumerate(columns)
            if _overlap(x0, x1, c.x0, c.x1) >= 0.4 * min(x1 - x0, c.x1 - c.x0)
        ] or [max(range(len(columns)), key=lambda i: _overlap(x0, x1, columns[i].x0, columns[i].x1))]
        below = next((r for r in rows if r.y1 > y and (r.y0 + r.y1) / 2 >= y - 0.5), None)
        above = next((r for r in reversed(rows) if (r.y0 + r.y1) / 2 < y - 0.5), None)
        if below is None and above is None:
            continue
        on_line = below is not None and below.y0 <= y <= below.y1
        # A rule separates values in its columns: under the last value above
        # it (an underline) when nothing follows in those columns, else over
        # the next value. Otherwise the nearer row takes it.
        above_has = above is not None and any(above.cells[c].text for c in cols)
        below_has = below is not None and any(below.cells[c].text for c in cols)
        below_values = below is not None and any(c.text for c in below.cells[1:])
        if on_line or above is None:
            use_above_row = False
        elif below is None:
            use_above_row = True
        elif above_has and not below_has:
            # Under the last value of a column: the next row's rule when it
            # brings a value elsewhere (the subtotal), else an underline.
            use_above_row = not below_values
        elif below_has and not above_has:
            use_above_row = False
        else:
            use_above_row = (y - above.y1) < 0.6 * (below.y0 - y)
        if use_above_row and above is not None:
            above.rule_below, above.rule_below_cols = _add_rule(above.rule_below, above.rule_below_cols, kind, cols)
        elif below is not None:
            below.rule_above, below.rule_above_cols = _add_rule(below.rule_above, below.rule_above_cols, kind, cols)


def _add_rule(current: str, current_cols: Sequence[int], kind: str, cols: Sequence[int]) -> tuple[str, list[int]]:
    """Combine a rule with the ones already on a row edge; two single rules
    over the same column make a double rule."""
    union = sorted(set(current_cols) | set(cols))
    if current == "single" and kind == "single" and set(current_cols) & set(cols):
        return "double", union
    return _stronger(current, kind), union


def _join_rows(group: Sequence[GeoRow]) -> GeoRow:
    """Several lines of one row as one row: each column's text in line order."""
    first = group[0]
    if len(group) == 1:
        return first
    cells = [GeoCell() for _ in first.cells]
    for row in group:
        for i, cell in enumerate(row.cells):
            if cell.text:
                cells[i].text = f"{cells[i].text} {cell.text}".strip()
                cells[i].words.extend(cell.words)
                cells[i].span = max(cells[i].span, cell.span)
    return GeoRow(cells, min(r.y0 for r in group), max(r.y1 for r in group), lines=sum(r.lines for r in group))


def _rows_from_rule_bands(rows: list[GeoRow], rule_ys: Sequence[float]) -> tuple[list[GeoRow], bool]:
    """In a table with a drawn rule between its rows, each band between two
    rules is one row, however many lines its cells wrap to (and wherever a
    one-line cell sits vertically in it).

    A table counts as row-ruled when 3+ bands hold text and 80% of them hold
    at most three lines; a booktabs table (rules only around the header and
    at the bottom) does not. Returns the rows and whether the table is row-ruled.
    """
    ys: list[float] = []
    for y in rule_ys:
        if not ys or y - ys[-1] > 2.0:
            ys.append(y)
    if len(ys) < 3:
        return rows, False
    bands: list[list[GeoRow]] = [[] for _ in range(len(ys) - 1)]
    outside: list[tuple[float, GeoRow]] = []
    for row in rows:
        yc = (row.y0 + row.y1) / 2
        index = next((i for i in range(len(ys) - 1) if ys[i] <= yc < ys[i + 1]), None)
        if index is None:
            outside.append((yc, row))
        else:
            bands[index].append(row)
    filled = [b for b in bands if b]
    if len(filled) < 3 or sum(1 for b in filled if len(b) <= 3) < 0.8 * len(filled):
        return rows, False
    joined: list[tuple[float, GeoRow]] = [(r.y0, r) for _, r in outside]
    for band in filled:
        if _stacks_numbers(band):
            # Numbers above numbers in one column: separate rows that share
            # a band (a group the rules enclose), not one wrapped row. A line
            # only in columns the value rows leave empty is a label spanning
            # them (centred vertically): it goes on the band's first row.
            numeric_lines = [r for r in band if any(is_numeric(c.text) for c in r.cells)]
            used = {i for r in numeric_lines for i in r.filled()}
            spanning = [r for r in band if r not in numeric_lines and not set(r.filled()) & used]
            kept = [r for r in band if r not in spanning]
            if spanning and kept:
                kept[0] = _join_rows([kept[0], *spanning])
            joined.extend((r.y0, r) for r in kept)
        else:
            joined.append((min(r.y0 for r in band), _join_rows(band)))
    return [row for _, row in sorted(joined, key=lambda item: item[0])], True


def _stacks_numbers(band: Sequence[GeoRow]) -> bool:
    """Lines in a band that are rows of their own: numbers above numbers in
    one column, or two lines each with a label and a value holding digits
    (``Civil Sciences  40 (26.0%)`` over ``Total  154``)."""
    count = max((len(r.cells) for r in band), default=0)
    for c in range(count):
        if sum(1 for r in band if c < len(r.cells) and is_numeric(r.cells[c].text)) >= 2:
            return True
    labelled_values = sum(
        1 for r in band
        if r.cells and r.cells[0].text and any(any(ch.isdigit() for ch in c.text) for c in r.cells[1:])
    )
    return labelled_values >= 2


def _numeric_columns(rows: Sequence[GeoRow]) -> set[int]:
    count = max((len(r.cells) for r in rows), default=0)
    out: set[int] = set()
    for c in range(1, count):
        values = [r.cells[c].text for r in rows if c < len(r.cells) and r.cells[c].text]
        if values and sum(is_numeric(v) for v in values) >= 0.5 * len(values):
            out.add(c)
    return out


def _merge_header_lines(rows: list[GeoRow]) -> list[GeoRow]:
    """Join the lines of multi-line column headers above the first data row.

    Two tight header lines, both with text beyond the first column and no
    number in either, are one header row, unless the lower one is a units row
    (``€m  €m``) or a row of years, or the upper one spans several of its cells
    (a spanning header stays over its columns).
    """
    numeric = _numeric_columns(rows)
    first_data = next(
        (
            i for i, r in enumerate(rows)
            if any(c in numeric and is_numeric(cell.text) and not _YEAR.match(cell.text) for c, cell in enumerate(r.cells))
        ),
        len(rows),
    )
    # Without a data row the header's extent is unknown: merge nothing.
    if first_data < 2 or first_data >= len(rows):
        return rows
    merged: list[GeoRow] = [rows[0]]
    for row in rows[1:first_data]:
        prev = merged[-1]
        texts = [c.text for c in row.cells if c.text]
        prev_texts = [c.text for c in prev.cells if c.text]
        beyond_stub = any(c.text for c in row.cells[1:]) and any(c.text for c in prev.cells[1:])
        no_numbers = not any(is_numeric(t) and not is_unit(t) for t in texts + prev_texts)
        units_row = all(is_unit(t) or _YEAR.match(t) for t in texts)
        spans_over = any(
            cell.span > 1 and sum(1 for k in range(i, i + cell.span) if k < len(row.cells) and row.cells[k].text) >= 2
            for i, cell in enumerate(prev.cells)
        )
        if beyond_stub and no_numbers and not units_row and not spans_over and _tight(prev, row):
            joined = _join_rows([prev, row])
            joined.rule_above, joined.rule_above_cols = prev.rule_above, prev.rule_above_cols
            joined.rule_below, joined.rule_below_cols = row.rule_below, row.rule_below_cols
            merged[-1] = joined
        else:
            merged.append(row)
    return merged + rows[first_data:]


def _alpha_start(text: str) -> bool:
    return bool(text) and (text[0].isalpha() or text[0] in "(\"'‘“[")


def _merge_continuations(rows: list[GeoRow], columns: Sequence[Column]) -> list[GeoRow]:
    """Join wrapped cell text back onto its row.

    A line continues the row above when all of these hold: no rule between
    them, the gap between them is tight (under 0.5 line heights), it has text
    only in columns where the row above has text, each such piece starts at
    the same x as the text above (wrapped text is left-aligned under itself),
    starts with a letter, has the same weight, and either the new line starts
    in lower case, the text above ends with a connector (``,``, ``and``,
    ``of``...), or the text above fills its column (it wrapped because it was
    full) and the gap is tighter than the table's usual gap between rows.

    Also the reverse: a stub-only line whose wrapped label ends on the next
    line, where the values are.
    """
    if not rows:
        return rows
    right_edge = [
        max((c.words[-1].x1 for r in rows if (c := r.cells[i]).words), default=0.0)
        for i in range(len(columns))
    ]
    gaps = sorted(b.y0 - a.y1 for a, b in zip(rows, rows[1:], strict=False))
    usual_gap = gaps[len(gaps) // 2] if gaps else 0.0
    merged: list[GeoRow] = [rows[0]]
    for row in rows[1:]:
        prev = merged[-1]
        if _continues(prev, row, columns, right_edge, usual_gap):
            for i, cell in enumerate(row.cells):
                if cell.text:
                    target = prev.cells[i]
                    target.text = f"{target.text} {cell.text}".strip()
                    target.words.extend(cell.words)
            prev.y1 = max(prev.y1, row.y1)
            prev.lines += row.lines
            prev.rule_below, prev.rule_below_cols = row.rule_below, row.rule_below_cols
            continue
        if _label_continues_on(prev, row, columns):
            stub = row.cells[0]
            stub.text = f"{prev.cells[0].text} {stub.text}".strip()
            stub.words = prev.cells[0].words + stub.words
            row.y0 = prev.y0
            row.lines += prev.lines
            row.rule_above, row.rule_above_cols = prev.rule_above, prev.rule_above_cols
            merged[-1] = row
            continue
        merged.append(row)
    return merged


def _line_height(row: GeoRow) -> float:
    heights = [w.h for c in row.cells for w in c.words]
    return statistics.median(heights) if heights else 10.0


def _tight(prev: GeoRow, row: GeoRow) -> bool:
    lh = min(_line_height(prev), _line_height(row))
    last_line_bottom = prev.y1
    return row.y0 - last_line_bottom <= 0.5 * lh and row.rule_above == "none" and prev.rule_below == "none"


def _continues(
    prev: GeoRow, row: GeoRow, columns: Sequence[Column], right_edge: Sequence[float], usual_gap: float
) -> bool:
    filled = row.filled()
    if not filled or not _tight(prev, row):
        return False
    closer = row.y0 - prev.y1 < usual_gap - 0.1 * _line_height(row)
    for i in filled:
        above, cell = prev.cells[i], row.cells[i]
        if not above.text or above.span > 1 or cell.span > 1:
            return False
        if not _alpha_start(cell.text) or is_numeric(cell.text) or is_numeric(above.text):
            return False
        if above.bold != cell.bold:
            return False
        last_line = [w for w in above.words if w.y0 >= max(x.y0 for x in above.words) - 0.5 * w.h]
        start_above = min(w.x0 for w in last_line)
        start_here = min(w.x0 for w in cell.words)
        if abs(start_here - start_above) > 3.0 and abs(start_here - min(w.x0 for w in above.words)) > 3.0:
            return False
        col_width = max(1.0, right_edge[i] - min(w.x0 for w in above.words))
        full = max(w.x1 for w in last_line) >= right_edge[i] - 0.2 * col_width
        lower = cell.text[0].islower()
        if not ((full and closer) or lower or _CONNECTOR_END.search(above.text)):
            return False
    return True


def _label_continues_on(prev: GeoRow, row: GeoRow, columns: Sequence[Column]) -> bool:
    """``prev`` is the first line of a wrapped stub label whose values are on ``row``."""
    if prev.filled() != [0] or 0 not in row.filled() or len(row.filled()) < 2:
        return False
    if not _tight(prev, row):
        return False
    above, cell = prev.cells[0], row.cells[0]
    if above.bold != cell.bold or above.span > 1 or not _alpha_start(cell.text):
        return False
    if min(w.x0 for w in cell.words) < min(w.x0 for w in above.words) - 1.0:
        return False
    return cell.text[0].islower() or bool(_CONNECTOR_END.search(above.text))


def _split_title_and_notes(table: GeoTable) -> None:
    """Lone lines that span the columns above or below the body: a title or notes."""
    def lone_wide(row: GeoRow) -> bool:
        filled = row.filled()
        return len(filled) == 1 and filled[0] == 0 and row.cells[0].span >= 2
    while len(table.rows) > 2 and lone_wide(table.rows[0]):
        table.title.append(table.rows.pop(0).cells[0].text)
    while len(table.rows) > 2 and lone_wide(table.rows[-1]):
        table.notes.insert(0, table.rows.pop().cells[0].text)


def _drop_empty_columns(table: GeoTable) -> None:
    keep = [i for i in range(len(table.columns)) if any(r.cells[i].text for r in table.rows)]
    if len(keep) == len(table.columns):
        return
    remap = {old: new for new, old in enumerate(keep)}
    for row in table.rows:
        cells: list[GeoCell] = []
        for old in keep:
            cell = row.cells[old]
            if cell.span > 1:
                last = old + cell.span - 1
                cell.span = max(1, sum(1 for k in keep if old <= k <= last))
            cells.append(cell)
        row.cells = cells
        row.rule_above_cols = sorted({remap[c] for c in row.rule_above_cols if c in remap})
        row.rule_below_cols = sorted({remap[c] for c in row.rule_below_cols if c in remap})
    # Widen neighbours over the dropped columns.
    columns = [table.columns[i] for i in keep]
    for i in range(len(columns) - 1):
        mid = (columns[i].x1 + columns[i + 1].x0) / 2
        columns[i].x1 = columns[i + 1].x0 = mid
    columns[0].x0 = table.columns[0].x0
    columns[-1].x1 = table.columns[-1].x1
    table.columns = columns


def _alignment_of(extents: Sequence[tuple[float, float]], tol: float = 2.5) -> tuple[str, float]:
    """Best of left/right/centre alignment and the share of cells that fit it."""
    if not extents:
        return "left", 1.0
    best = ("left", 0.0)
    for name, values in (
        ("left", [a for a, _ in extents]),
        ("right", [b for _, b in extents]),
        ("center", [(a + b) / 2 for a, b in extents]),
    ):
        median = statistics.median(values)
        share = sum(1 for v in values if abs(v - median) <= tol) / len(values)
        if share > best[1]:
            best = (name, share)
    return best


def _measure_columns(table: GeoTable) -> None:
    for i, column in enumerate(table.columns):
        extents = [
            (min(w.x0 for w in c.words), max(w.x1 for w in c.words))
            for r in table.rows if (c := r.cells[i]).words and c.span == 1
        ]
        if extents:
            column.left = min(a for a, _ in extents)
            column.right = max(b for _, b in extents)
        column.align = _alignment_of(extents)[0]


# ---------------------------------------------------------------------------
# Grid quality
# ---------------------------------------------------------------------------


@dataclass
class GridScore:
    """Defects of a grid against the words on the page.

    - ``assigned``: share of the table's words that land whole in exactly one cell;
    - ``split_words``: words cut between two cells;
    - ``merged_cells``: cells holding two or more phrases side by side on one
      line, in a column where that happens at least twice (merged columns);
    - ``stacked_cells``: cells holding text from two or more of the page's
      rows (a header line merged into a value, two rows in one);
    - ``glued_rules``: cells holding a typed rule (``––––``) and a value;
    - ``alignment``: mean share of a column's cells that share its alignment;
    - ``empty``: share of empty cells.
    """

    words: int = 0
    assigned: float = 1.0
    split_words: int = 0
    merged_cells: int = 0
    stacked_cells: int = 0
    glued_rules: int = 0
    alignment: float = 1.0
    empty: float = 0.0
    cells: int = 0

    @property
    def defects(self) -> int:
        return self.split_words + self.merged_cells + self.stacked_cells + self.glued_rules

    def as_dict(self) -> dict[str, float | int]:
        return {
            "words": self.words,
            "assigned": round(self.assigned, 3),
            "split_words": self.split_words,
            "merged_cells": self.merged_cells,
            "stacked_cells": self.stacked_cells,
            "glued_rules": self.glued_rules,
            "alignment": round(self.alignment, 3),
            "empty": round(self.empty, 3),
        }


def _row_index(rows: Sequence[GeoRow]) -> list[tuple[float, float, int]]:
    """Every source line's vertical band, keyed to the reconstructed row it belongs to."""
    bands: list[tuple[float, float, int]] = []
    for index, row in enumerate(rows):
        for line in group_lines([w for c in row.cells for w in c.words]):
            bands.append((min(w.y0 for w in line), max(w.y1 for w in line), index))
    return bands


def _fuses_rows(by_row: dict[int, list[Word]], rows: Sequence[GeoRow]) -> bool:
    """A cell holding a value from one row and text from another row that is
    a row of its own: two labelled rows (``(35) (2,265)``), or a header or
    units row on a value (``$000 880``). A value written on two lines (``270``
    over ``(100%)``) is not a defect."""
    def text(ws: list[Word]) -> str:
        return " ".join(w.text for w in sorted(ws, key=lambda w: (w.yc, w.x0)))

    valued = [i for i, ws in by_row.items() if is_numeric(text(ws))]
    if not valued:
        return False
    labelled = [i for i in by_row if rows[i].cells and rows[i].cells[0].text]
    if len(labelled) >= 2:
        return True
    heading = [
        i for i in by_row
        if i not in valued and not any(is_numeric(c.text) for c in rows[i].cells)
        and not (rows[i].cells and rows[i].cells[0].text)
    ]
    return bool(heading)


def grid_quality(
    words: Sequence[Word],
    cells: Sequence[Sequence[Sequence[float] | None]],
    reference: GeoTable | None,
) -> GridScore:
    """Score a grid of cell boxes against the page's words.

    ``reference`` (the geometric reconstruction) supplies the page's rows for
    ``stacked_cells``; without it that count is 0.
    """
    rules = [w for w in words if is_rule_text(w.text, w.x1 - w.x0, w.h)]
    content = [w for w in words if w not in rules and not is_leader_text(w.text) and w.text not in (".", "·")]
    score = GridScore(words=len(content))
    flat = [(r, c, box) for r, row in enumerate(cells) for c, box in enumerate(row) if box is not None]
    score.cells = len(flat)
    if not flat or not content:
        return score
    ruled_cells = {
        (r, c) for word in rules for r, c, b in flat
        if b[0] - 0.5 <= word.xc <= b[2] + 0.5 and b[1] - 0.5 <= word.yc <= b[3] + 0.5
    }
    holders: dict[tuple[int, int], list[Word]] = {}
    once = 0
    for word in content:
        hits = [(r, c) for r, c, b in flat if b[0] - 0.5 <= word.xc <= b[2] + 0.5 and b[1] - 0.5 <= word.yc <= b[3] + 0.5]
        if len(hits) >= 1:
            r, c = hits[0]
            holders.setdefault((r, c), []).append(word)
        # Cut between two cells of its row: a character or more (2pt) on
        # each side of a cell edge (``(5,581)`` read as ``(5581)`` and ``,``).
        width = word.x1 - word.x0
        cut = False
        if len(word.text) >= 2 and width > 0 and hits:
            r = hits[0][0]
            for _, _c, b in (h for h in flat if h[0] == r):
                inside = _overlap(word.x0, word.x1, b[0], b[2])
                if 2.0 <= inside <= width - 2.0 and inside < width:
                    cut = True
                    break
        score.split_words += cut
        once += len(hits) == 1 and not cut
    score.assigned = once / len(content)

    # Phrases side by side in one cell, per column.
    merged_by_col: dict[int, int] = {}
    for (_, c), held in holders.items():
        if any(len([s for s in split_segments(line) if s.kind == "text"]) >= 2 for line in group_lines(held)):
            merged_by_col[c] = merged_by_col.get(c, 0) + 1
    score.merged_cells = sum(n for n in merged_by_col.values() if n >= 2)

    if reference is not None:
        bands = _row_index(reference.rows)
        for held in holders.values():
            by_row: dict[int, list[Word]] = {}
            for word in held:
                for y0, y1, index in bands:
                    if y0 - 0.5 <= word.yc <= y1 + 0.5:
                        by_row.setdefault(index, []).append(word)
                        break
            if len(by_row) >= 2 and _fuses_rows(by_row, reference.rows):
                score.stacked_cells += 1

    score.glued_rules = sum(1 for key in ruled_cells if key in holders)

    columns = max((len(row) for row in cells), default=0)
    shares: list[float] = []
    for c in range(1, columns):
        extents = [
            (min(w.x0 for w in held), max(w.x1 for w in held))
            for (r, cc), held in holders.items() if cc == c
        ]
        if len(extents) >= 3:
            shares.append(_alignment_of(extents)[1])
    score.alignment = sum(shares) / len(shares) if shares else 1.0
    score.empty = 1.0 - len(holders) / len(flat)
    return score


def snap_to_words(
    words: Sequence[Word], cells: Sequence[Sequence[Sequence[float] | None]]
) -> list[list[str]]:
    """Cell text read from whole words, each in the cell holding its centre.

    The layout model cuts cell text out by character, so a word across a
    cell edge is split (``1979 1 | 980``). Its lattice is kept; only the
    text is re-read."""
    grid: list[list[str]] = []
    for row in cells:
        out: list[str] = []
        for box in row:
            if box is None:
                out.append("")
                continue
            held = [w for w in words if box[0] <= w.xc <= box[2] and box[1] <= w.yc <= box[3]]
            out.append("\n".join(" ".join(w.text for w in line) for line in group_lines(held)))
        grid.append(out)
    return grid


def prefer_geometry(model: GridScore, geo: GridScore) -> bool:
    """Use the geometric grid only when it is clearly better than the model's.

    The model's grid must show at least two defects (and at least 5% of its
    filled cells, unless the geometric grid has none), the geometric grid
    must fix most of them, keep every word,
    and not lose column alignment or fill. A single word cut between two cells
    is enough when the geometric grid has no defect and is otherwise as good.
    """
    filled = max(1, round(model.cells * (1 - model.empty)))
    if model.split_words >= 1 and geo.defects == 0 and geo.assigned >= model.assigned:
        # A word cut in two is always wrong: fix it when nothing else changes
        # for the worse.
        return geo.alignment >= model.alignment - 0.02 and geo.empty <= model.empty + 0.05
    if model.defects < 2 or (model.defects < 0.05 * filled and geo.defects > 0):
        return False
    if geo.defects > 0.34 * model.defects:
        return False
    if geo.assigned < model.assigned - 0.01:
        return False
    if geo.alignment < model.alignment - 0.1:
        return False
    return geo.empty <= model.empty + 0.25


# ---------------------------------------------------------------------------
# Rows, hierarchy and emphasis (any grid)
# ---------------------------------------------------------------------------


@dataclass
class RowInfo:
    """What a row is, independent of where its grid came from."""

    cells: list[str]
    stub_x0: float | None = None
    stub_bold: bool = False
    stub_size: float = 0.0
    values_bold: bool = False
    rule_above: str = "none"
    rule_above_cols: list[int] = field(default_factory=list)
    rule_below: str = "none"
    rule_below_cols: list[int] = field(default_factory=list)
    spans: dict[int, int] = field(default_factory=dict)
    level: int = 0
    path: list[str] = field(default_factory=list)
    emphasis: str | None = None
    header: bool = False


def rows_from_geometry(table: GeoTable) -> list[RowInfo]:
    infos: list[RowInfo] = []
    for row in table.rows:
        stub = row.cells[0]
        values = [c for c in row.cells[1:] if c.words]
        infos.append(RowInfo(
            cells=[c.text for c in row.cells],
            stub_x0=min((w.x0 for w in stub.words), default=None),
            stub_bold=stub.bold,
            stub_size=max((w.size for w in stub.words), default=0.0),
            values_bold=bool(values) and all(c.bold for c in values),
            rule_above=row.rule_above,
            rule_above_cols=list(row.rule_above_cols),
            rule_below=row.rule_below,
            rule_below_cols=list(row.rule_below_cols),
            spans={i: c.span for i, c in enumerate(row.cells) if c.span > 1},
        ))
    return infos


def _strip_rule_tokens(text: str) -> tuple[str, str]:
    """Cell text without rule glyph runs and leaders, and the rule kind removed."""
    kind = "none"
    kept_lines = []
    for line in text.split("\n"):
        kept = []
        for token in line.split():
            if is_rule_text(token) or is_leader_text(token):
                if is_rule_text(token):
                    kind = _stronger(kind, "double" if any(ch in _DOUBLE_RULE_CHARS for ch in token) else "single")
                continue
            kept.append(token)
        if kept:
            kept_lines.append(" ".join(kept))
    return "\n".join(kept_lines), kind


def rows_from_grid(words: Sequence[Word], cells: Sequence[Sequence[Sequence[float] | None]], grid: Sequence[Sequence[str]]) -> list[RowInfo]:
    """Row records for any grid (the model's): text, stub style, typed rules.

    Rule glyph runs in a cell are taken out of the text; a row left empty by
    that becomes a ``rule_above`` of the next row (``rule_below`` of the last).
    """
    infos: list[RowInfo] = []
    pending: tuple[str, list[int]] | None = None
    for r, row in enumerate(grid):
        texts: list[str] = []
        ruled_cols: list[int] = []
        kind = "none"
        for c, value in enumerate(row):
            text, rule = _strip_rule_tokens(value or "")
            texts.append(text)
            if rule != "none":
                ruled_cols.append(c)
                kind = _stronger(kind, rule)
        if not any(t.strip() for t in texts):
            if kind != "none":
                if pending is not None:
                    pending = ("double", sorted(set(pending[1]) | set(ruled_cols)))
                else:
                    pending = (kind, ruled_cols)
            elif any((v or "").strip() for v in row):
                pending = pending  # only leaders: nothing to keep
            else:
                infos.append(RowInfo(cells=texts))
            continue
        boxes = cells[r] if r < len(cells) else []
        stub_box = boxes[0] if boxes else None
        stub_words = [w for w in words if stub_box is not None and stub_box[0] - 0.5 <= w.xc <= stub_box[2] + 0.5 and stub_box[1] - 0.5 <= w.yc <= stub_box[3] + 0.5 and not is_rule_text(w.text, w.x1 - w.x0, w.h)] if texts[0] else []
        value_words = [
            w for b in boxes[1:] if b is not None for w in words
            if b[0] - 0.5 <= w.xc <= b[2] + 0.5 and b[1] - 0.5 <= w.yc <= b[3] + 0.5 and not is_rule_text(w.text, w.x1 - w.x0, w.h)
        ]
        info = RowInfo(
            cells=texts,
            stub_x0=min((w.x0 for w in stub_words), default=None),
            stub_bold=bool(stub_words) and all(w.bold for w in stub_words),
            stub_size=max((w.size for w in stub_words), default=0.0),
            values_bold=bool(value_words) and all(w.bold for w in value_words),
        )
        if kind != "none":  # a rule typed in the same cell as text: under the value
            info.rule_below, info.rule_below_cols = kind, ruled_cols
        if pending is not None:
            info.rule_above, info.rule_above_cols = pending
            pending = None
        infos.append(info)
    if pending is not None and infos:
        infos[-1].rule_below = _stronger(infos[-1].rule_below, pending[0])
        infos[-1].rule_below_cols = sorted(set(infos[-1].rule_below_cols) | set(pending[1]))
    return infos


def _indent_levels(infos: Sequence[RowInfo]) -> dict[float, int] | None:
    """Map stub left edges to indent levels, or ``None`` when the stub is not
    a left-aligned, indented column (centred or ragged stubs get no levels)."""
    xs = sorted(i.stub_x0 for i in infos if i.stub_x0 is not None and i.cells and i.cells[0])
    if len(xs) < 3:
        return None
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 2.5:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    if len(clusters) < 2 or len(clusters) > 6:
        return None
    # Mostly flush-left: the shallowest level must hold a real share of rows,
    # and singletons spread across many positions read as ragged text.
    if len(clusters[0]) < 2 or sum(1 for c in clusters if len(c) == 1) > max(1, len(clusters) // 2):
        return None
    # A lone row at its own indent (a header word, a centred label) is not a
    # level: it joins the level to its left.
    kept: list[list[float]] = []
    for cluster in clusters:
        if len(cluster) == 1 and kept:
            kept[-1].append(cluster[0])
        else:
            kept.append(cluster)
    if len(kept) < 2:
        return None
    centres = [statistics.mean(c) for c in kept]
    steps = [b - a for a, b in zip(centres, centres[1:], strict=False)]
    if min(steps) < 4.0 or centres[-1] - centres[0] > 90.0:
        return None
    mapping: dict[float, int] = {}
    for level, cluster in enumerate(kept):
        for x in cluster:
            mapping[x] = level
    return mapping


def annotate_rows(infos: list[RowInfo]) -> int:
    """Set ``level``, ``path``, ``emphasis`` and ``header`` on every row.

    Returns the number of header rows: the rows above the first data row (a
    row with a number in a column that is mostly numbers). Years and units
    (``2025``, ``€m``) do not make a row a data row.
    """
    if not infos:
        return 0
    columns = max(len(i.cells) for i in infos)
    numeric_cols = set()
    for c in range(1, columns):
        values = [i.cells[c] for i in infos if c < len(i.cells) and i.cells[c].strip()]
        if values and sum(is_numeric(v) for v in values) >= 0.5 * len(values):
            numeric_cols.add(c)
    header_rows = 0
    for index, info in enumerate(infos):
        data = any(
            c in numeric_cols and is_numeric(v) and not _YEAR.match(v.strip())
            for c, v in enumerate(info.cells) if v.strip()
        )
        if data:
            header_rows = index
            break
    else:
        header_rows = 1 if len(infos) > 1 else 0
    # Rows with text only in the first column just above the data are group
    # labels ("Revenue", "Operating segments"), not column headers.
    while header_rows > 1 and _stub_only(infos[header_rows - 1]):
        header_rows -= 1
    # A data row cannot be a header.
    header_rows = min(header_rows, max(1, len(infos) // 2))
    for info in infos[:header_rows]:
        info.header = True

    body = infos[header_rows:]
    levels = _indent_levels(body) or {}
    sizes = [i.stub_size for i in body if i.stub_size > 0]
    body_size = statistics.median(sizes) if sizes else 0.0
    labelled = [i for i in body if i.cells and i.cells[0].strip()]
    # Bold marks emphasis only where most stubs are not bold.
    bold_is_style = bool(labelled) and sum(i.stub_bold for i in labelled) > 0.5 * len(labelled)
    for k, info in enumerate(body):
        has_label = bool(info.cells and info.cells[0].strip())
        numbers = any(is_numeric(v) for v in info.cells[1:] if v.strip())
        has_values = any(v.strip() for v in info.cells[1:])
        info.level = levels.get(info.stub_x0, 0) if info.stub_x0 is not None else 0
        emphasised = (info.stub_bold and not bold_is_style) or (
            body_size > 0 and info.stub_size >= 1.15 * body_size
        )
        following = body[k + 1] if k + 1 < len(body) else None
        next_deeper = (
            following is not None and following.stub_x0 is not None and info.stub_x0 is not None
            and levels.get(following.stub_x0, 0) > info.level
        )
        previous = body[k - 1] if k > 0 else None
        closes_column = (
            info.rule_above != "none" and bool(info.rule_above_cols) and 0 not in info.rule_above_cols
            and previous is not None and any(v.strip() for v in previous.cells[1:])
        )
        if has_label and not numbers and (emphasised or (next_deeper and not has_values)):
            info.emphasis = "group"
        elif numbers and (
            (info.stub_bold and not bold_is_style) or (info.values_bold and not bold_is_style)
            or (has_label and bool(_TOTAL_LABEL.match(info.cells[0])))
            or closes_column
        ):
            info.emphasis = "total"
    # Paths: the labels of the open groups above each row. A group whose
    # children were indented closes at the next row back at its own indent.
    stack: list[list[Any]] = []  # [level, is_group_rank, label, saw_deeper]
    for info in body:
        label = info.cells[0].strip() if info.cells else ""
        if not label:
            info.path = [entry[2] for entry in stack]
            continue
        group = info.emphasis == "group"
        while stack:
            level, _, _, saw_deeper = stack[-1]
            if level > info.level or (level == info.level and (group or saw_deeper)):
                stack.pop()
            else:
                break
        info.path = [entry[2] for entry in stack]
        if stack and info.level > stack[-1][0]:
            stack[-1][3] = True
        if group:
            stack.append([info.level, True, label, False])
    return header_rows


def _stub_only(info: RowInfo) -> bool:
    return bool(info.cells and info.cells[0].strip()) and not any(v.strip() for v in info.cells[1:])


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _bold(text: str) -> str:
    text = text.strip()
    if not text or text.startswith("**"):
        return text
    return f"**{text}**"


def format_cells(infos: Sequence[RowInfo]) -> list[list[str]]:
    """Cell strings for Markdown: em-space indents, bold group and total rows."""
    out: list[list[str]] = []
    for info in infos:
        cells = [" ".join(c.split()) for c in info.cells]
        if not info.header and cells:
            if info.emphasis in ("group", "total"):
                cells = [_bold(c) if c else c for c in cells]
            if cells[0] and info.level:
                cells[0] = EM_SPACE * info.level + cells[0]
        out.append(cells)
    return out


def _number(text: str) -> float | None:
    token = text.replace("**", "").strip()
    if token in ("-", "–", "—", "nil"):
        return 0.0
    match = re.fullmatch(r"([(\-−–])?\s?[£$€¥]?\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s?\)?", token)
    if not match:
        return None
    value = float(match.group(2).replace(",", ""))
    return -value if match.group(1) else value


def column_sum_hints(infos: Sequence[RowInfo]) -> list[dict[str, Any]]:
    """Optional confidence hint: rows under a typed or drawn rule whose value
    equals the sum of the numbers above it in its column (or the column to its
    left) since the previous rule. Informational only; nothing depends on it."""
    hints: list[dict[str, Any]] = []
    columns = max((len(i.cells) for i in infos), default=0)
    for c in range(1, columns):
        for r, info in enumerate(infos):
            if c >= len(info.cells) or info.rule_above == "none" or not info.rule_above_cols:
                continue
            found = _number(info.cells[c])
            if found is None:
                continue
            for source in (c, c - 1):
                if source < 1:
                    continue
                total, n = 0.0, 0
                for k in range(r - 1, -1, -1):
                    above = infos[k]
                    value = _number(above.cells[source]) if source < len(above.cells) else None
                    if value is not None:
                        total += value
                        n += 1
                    if above.header or (above.rule_above != "none" and source in above.rule_above_cols):
                        break
                if n >= 2:
                    hints.append({"row": r, "column": c, "from_column": source, "sum": round(total, 2), "value": found, "ok": abs(total - found) < 0.005 + 1e-9 * abs(found)})
                    if abs(total - found) < 0.005:
                        break
    return hints


def table_record(
    *,
    page: int,
    bbox: Sequence[float],
    infos: Sequence[RowInfo],
    header_rows: int,
    source: str,
    scores: dict[str, dict[str, float | int]],
    columns: Sequence[Column] | None = None,
    title: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    """The structured record of a table for ``structure["tables"]``."""
    count = max((len(i.cells) for i in infos), default=0)
    headers = [
        " ".join(i.cells[c].strip() for i in infos[:header_rows] if c < len(i.cells) and i.cells[c].strip())
        for c in range(count)
    ]
    column_records: list[dict[str, Any]] = []
    for c in range(count):
        record: dict[str, Any] = {"index": c, "header": headers[c]}
        if columns is not None and c < len(columns):
            record.update({"x0": round(columns[c].left, 1), "x1": round(columns[c].right, 1), "align": columns[c].align})
        column_records.append(record)
    rows = []
    for i in infos:
        row: dict[str, Any] = {
            "cells": [" ".join(c.split()) for c in i.cells],
            "header": i.header,
            "level": i.level,
            "path": list(i.path),
            "emphasis": i.emphasis,
            "rule_above": i.rule_above,
            "rule_below": i.rule_below,
        }
        if i.rule_above_cols:
            row["rule_above_cols"] = list(i.rule_above_cols)
        if i.rule_below_cols:
            row["rule_below_cols"] = list(i.rule_below_cols)
        if i.spans:
            row["spans"] = {str(k): v for k, v in i.spans.items()}
        rows.append(row)
    record_out: dict[str, Any] = {
        "page": page,
        "bbox": [round(float(v), 1) for v in bbox],
        "source": source,
        "scores": scores,
        "title": " ".join(title) or None,
        "notes": list(notes),
        "header_rows": header_rows,
        "columns": column_records,
        "rows": rows,
    }
    hints = column_sum_hints(infos)
    if hints:
        record_out["column_sum_hints"] = hints
    return record_out
