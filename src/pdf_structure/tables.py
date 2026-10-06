"""Table region detection.

Tables are not an edge case in long documents: on the reference document PyMuPDF found
341 tables across 252 of 438 pages, so 58% of pages contain one. They must survive as
unified atomic units with row and column alignment intact, which means chunk boundaries
must never fall inside one.

Two independent views, because each catches what the other misses:

* **geometric** -- ``page.find_tables()`` gives bounding boxes, which lets us mark the
  underlying :class:`~src.pdf_structure.lines.PageLine` records as belonging to a table.
* **markdown** -- runs of ``|`` pipe rows in the ``pymupdf4llm`` output, which is what
  actually gets emitted into chunk text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .lines import PageLine

logger = logging.getLogger(__name__)

_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR_ROW = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


@dataclass(frozen=True)
class TableRegion:
    """A table on one page, in both geometric and line-ordinal terms."""

    page: int
    bbox: tuple[float, float, float, float]
    rows: int
    cols: int
    ordinals: frozenset[int]
    """Ordinals of the lines that fall inside the table bbox."""
    header: tuple[str, ...] = ()
    data_rows: tuple[tuple[str, ...], ...] = ()
    header_external: bool = False
    page_height: float = 0.0

    @property
    def markdown(self) -> str:
        """The region's cell grid rendered as a constant-width pipe table."""
        return render_markdown_table(self.header, self.data_rows, self.cols)


def _page_words(page: Any) -> list[tuple]:
    """Words on a page, computed once per page object."""
    cached = getattr(page, "_chomper_words", None)
    if cached is None:
        cached = page.get_text("words", sort=True)
        try:
            page._chomper_words = cached
        except AttributeError:  # pragma: no cover - slotted page objects
            pass
    return cached


def _cell_text(words: list[tuple], bbox: Any) -> str:
    """Text of the words whose centre lies in ``bbox``, one line per text line."""
    x0, y0, x1, y1 = bbox
    lines: dict[tuple[int, int], list[tuple[float, str]]] = {}
    order: list[tuple[int, int]] = []
    for word in words:
        cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            key = (word[5], word[6])
            if key not in lines:
                lines[key] = []
                order.append(key)
            lines[key].append((word[0], word[4]))
    return "\n".join(" ".join(t for _, t in sorted(lines[key])) for key in order)


def _cells_from_words(table: Any, rows: Any) -> tuple[tuple[str, ...], ...] | None:
    """Cell text rebuilt from page words, or ``None`` if geometry is unavailable.

    ``Table.extract()`` depends on process-wide PyMuPDF state: once
    ``pymupdf.layout`` has been imported (``pymupdf4llm`` does it) it drops the
    spaces between words and splits ``1.42m`` into ``142m\\n.``. The cell
    boxes stay right, and plain word extraction is unaffected, so the text is
    taken from the words inside each cell box instead.
    """
    page = getattr(table, "page", None)
    if page is None or not rows:
        return None
    words = _page_words(page)
    out = []
    for row in rows:
        cells = getattr(row, "cells", None)
        if cells is None:
            return None
        out.append(tuple("" if cell is None else _cell_text(words, cell) for cell in cells))
    return tuple(out)


#: A cell that says yes/no/optional with a mark, maybe with a footnote number.
_MARK_CELL = re.compile(r"^[●○◐◑◒✓✔✗✘✕×+•■□☑☒✚–—-](?:\s*\d{1,2}(?:,\d{1,2})*)?$")

Grid = list[list[str]]
CellBoxes = list[list["tuple[float, float, float, float] | None"]]


def _is_mark_cell(text: str) -> bool:
    return bool(_MARK_CELL.match(text.strip()))


def is_mark_matrix(grid: Sequence[Sequence[str]], *, min_share: float = 0.6) -> bool:
    """True when the value cells of ``grid`` are mostly marks (●, ✓, ✗, +).

    Also true when the model merged mark columns: a cell holding several marks
    (``● ●``) counts as a mark cell.
    """
    values = [c.strip() for row in grid for c in row[1:] if c and c.strip()]
    if len(values) < 4:
        return False
    marks = sum(1 for c in values if all(_is_mark_cell(t) for t in c.split()))
    return marks >= min_share * len(values)


def _overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _area(r: Sequence[float]) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _intersection(a: Sequence[float], b: Sequence[float]) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


#: Marks counted to check none is lost; "+" and "•" also occur in prose.
_MARK_CHARS = frozenset("●○◐◑◒✓✔✗✘✕×■□☑☒✚")


def _mark_count(texts: Any) -> int:
    """Mark glyphs in a grid (or any nesting of strings)."""
    if isinstance(texts, str):
        return sum(ch in _MARK_CHARS for ch in texts)
    return sum(_mark_count(t) for t in texts if t)


def _has_merged_marks(grid: Sequence[Sequence[str]]) -> bool:
    """A cell holding several separate marks (``● ●``): two columns merged into one."""
    return any(
        len(tokens) >= 2 and all(_is_mark_cell(t) for t in tokens)
        for row in grid
        for tokens in ((c or "").split() for c in row[1:])
    )


def _centre_in(word: Sequence[Any], box: Sequence[float]) -> bool:
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


MarkRecovery = Callable[[Any, CellBoxes, Grid], Grid]


@dataclass(frozen=True)
class RuledPiece:
    """One piece of a layout table rebuilt from ruled grids: a grid, or a line of text."""

    y: float
    cells: CellBoxes | None = None
    grid: Grid | None = None
    text: str = ""
    block: int = -1


def ruled_grids_for_sparse_matrix(
    page: Any,
    bbox: Sequence[float],
    grid: Sequence[Sequence[str]],
    recover: MarkRecovery | None = None,
) -> list[RuledPiece] | None:
    """The ruled ``find_tables`` grids to use instead of a layout-model grid, or ``None``.

    The layout model places columns from where text is. In a sparse feature
    matrix (Microsoft 365 plan grids: 21 plan columns, most cells empty or one
    ●) whole columns hold no text, so the model merges them: a plan's dot lands
    in its neighbour's column, or two dots share a cell (``● ●``). The ruled
    grids that ``find_tables`` reads from the drawn lines keep every column.
    One layout table often spans several ruled sections, with section titles,
    legends and footnotes between them.

    Preferring ``find_tables`` wherever it overlaps a layout table costs table
    adjacency F1 on ICDAR-2013 + SciTSR, so the ruled grids are used only when
    all of these hold:

    - the layout grid is a mark matrix (:func:`is_mark_matrix`);
    - line-based grids (not guided by the layout model) lie inside the layout
      table's box and hold at least half of its words;
    - each has 3+ columns and sparse value cells (>= 90% empty or one mark);
    - the layout grid shows merged columns: a ruled grid has more columns, or
      a layout cell holds several marks;
    - no mark is lost or gained: the ruled grids plus the text between them
      hold exactly as many mark glyphs as the layout grid;
    - the ruled cells pull in almost nothing from outside the box (<= 5% of
      their words).

    Returns the grids and the lines of text between them (words in the box that
    no ruled cell holds), in reading order from the top. Cell text comes from
    the page's words (``Table.extract()`` is corrupted once ``pymupdf.layout``
    is imported); ``recover`` (mark recovery) runs on each ruled grid first.
    """
    if not is_mark_matrix(grid):
        return None
    try:
        found = page.find_tables(strategy="lines", use_layout=False).tables
    except Exception:  # pragma: no cover - PyMuPDF version differences
        return None
    # Ruled grids in the layout table's rows; they may be wider (empty columns
    # carry no text for the model's box to hug).
    tables = [
        t for t in found
        if _overlap_1d(bbox[1], bbox[3], t.bbox[1], t.bbox[3]) >= 0.8 * (t.bbox[3] - t.bbox[1])
        and _overlap_1d(bbox[0], bbox[2], t.bbox[0], t.bbox[2]) >= 0.5 * (t.bbox[2] - t.bbox[0])
        and t.col_count >= 3
    ]
    if not tables:
        logger.debug("sparse matrix p%s: no ruled grid in %s", page.number + 1, bbox)
        return None
    layout_cols = max((len(row) for row in grid), default=0)
    if max(t.col_count for t in tables) <= layout_cols and not _has_merged_marks(grid):
        logger.debug("sparse matrix p%s: no merged columns", page.number + 1)
        return None

    words = _page_words(page)
    in_box = [w for w in words if _centre_in(w, bbox)]
    pieces: list[RuledPiece] = []
    held: set[int] = set()
    pulled_in = total = 0
    for table in tables:
        texts = _cells_from_words(table, table.rows)
        if texts is None:
            return None
        values = [cell for row in texts for cell in row[1:]]
        if sum(1 for c in values if not c.strip() or _is_mark_cell(c)) < 0.9 * len(values):
            logger.debug("sparse matrix p%s: ruled grid %s not sparse", page.number + 1, table.bbox)
            return None
        boxes: CellBoxes = [
            [None if c is None else (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
             for c in row.cells]
            for row in table.rows
        ]
        ruled = [list(row) for row in texts]
        if recover is not None:
            ruled = [["" if c is None else str(c) for c in row] for row in recover(page, boxes, ruled)]
        flat = [b for row in boxes for b in row if b is not None]
        for index, word in enumerate(words):
            if any(_centre_in(word, b) for b in flat):
                held.add(index)
                total += 1
                pulled_in += not _centre_in(word, bbox)
        pieces.append(RuledPiece(y=float(table.bbox[1]), cells=boxes, grid=ruled))
    if total < 0.5 * len(in_box) or pulled_in > 0.05 * max(1, total):
        logger.debug(
            "sparse matrix p%s: ruled cells hold %d of %d words, %d from outside",
            page.number + 1, total, len(in_box), pulled_in,
        )
        return None

    # Words in the box no ruled cell holds: section titles, legends, footnotes.
    lines: dict[tuple[int, int], list[tuple[Any, ...]]] = {}
    for index, word in enumerate(words):
        if index not in held and _centre_in(word, bbox):
            lines.setdefault((word[5], word[6]), []).append(word)
    leftover = [
        RuledPiece(
            y=min(w[1] for w in ws),
            text=" ".join(w[4] for w in sorted(ws, key=lambda w: w[0])),
            block=int(key[0]),
        )
        for key, ws in lines.items()
    ]
    marks = sum(_mark_count(p.grid) for p in pieces) + _mark_count([p.text for p in leftover])
    if marks != _mark_count(grid):
        logger.debug("sparse matrix p%s: %d marks vs %d", page.number + 1, marks, _mark_count(grid))
        return None
    return sorted(pieces + leftover, key=lambda p: p.y)


def render_ruled_pieces(pieces: Sequence[RuledPiece]) -> str:
    """Markdown for :func:`ruled_grids_for_sparse_matrix` output: tables and the
    text between them, consecutive lines of one text block joined."""
    parts: list[str] = []
    last_block: int | None = None
    for piece in pieces:
        if piece.grid is None:
            if last_block == piece.block and parts:
                parts[-1] += " " + piece.text
            else:
                parts.append(piece.text)
            last_block = piece.block
            continue
        last_block = None
        rows = [tuple(row) for row in piece.grid]
        columns = max((len(row) for row in rows), default=0)
        parts.append(render_markdown_table(rows[0], tuple(rows[1:]), columns))
    return "\n\n".join(parts)


def extract_table_data(
    table: Any,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], int, bool]:
    """Extract a PyMuPDF table into header, body, width and header provenance."""
    extracted = _cells_from_words(table, getattr(table, "rows", None))
    if extracted is None:
        extracted = tuple(
            tuple("" if cell is None else str(cell) for cell in row)
            for row in (table.extract() or ())
        )
    header_object = getattr(table, "header", None)
    header_cells = getattr(header_object, "cells", None)
    page = getattr(table, "page", None)
    if header_cells and page is not None and getattr(header_object, "external", False):
        words = _page_words(page)
        header_names = tuple("" if c is None else _cell_text(words, c) for c in header_cells)
    else:
        header_names = tuple(
            "" if cell is None else str(cell)
            for cell in (getattr(header_object, "names", None) or ())
        )
        if header_names and not getattr(header_object, "external", False) and extracted:
            # An internal header is the first row; use its rebuilt text.
            header_names = extracted[0]
    header_external = bool(getattr(header_object, "external", False))
    columns = max(
        int(getattr(table, "col_count", 0) or 0),
        len(header_names),
        max((len(row) for row in extracted), default=0),
    )

    if header_names:
        header = header_names
        # Internal headers are the first extracted row. External headers are not
        # part of ``extract()`` and therefore must not consume the first data row.
        data_rows = extracted if header_external else extracted[1:]
    elif extracted:
        header, data_rows = extracted[0], extracted[1:]
    else:
        header, data_rows = tuple("" for _ in range(columns)), ()

    return header, data_rows, columns, header_external


def render_markdown_table(
    header: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    column_count: int,
) -> str:
    """Render cells as GitHub-flavoured markdown without changing their order."""
    columns = max(column_count, len(header), max((len(row) for row in rows), default=0))
    if columns <= 0:
        return ""

    def render_cell(cell: str) -> str:
        # Leading em spaces are a row's indent level (Markdown collapses spaces).
        indent = re.match(r" *", cell.lstrip(" \t\n")).group(0)  # type: ignore[union-attr]
        body = re.sub(r"\s+", " ", cell).strip().replace("|", r"\|")
        return indent + body

    def render_row(row: tuple[str, ...]) -> str:
        cells = list(row[:columns]) + [""] * max(0, columns - len(row))
        return "| " + " | ".join(render_cell(cell) for cell in cells) + " |"

    return "\n".join(
        [render_row(header), render_row(tuple("---" for _ in range(columns)))]
        + [render_row(row) for row in rows]
    )


def table_to_markdown(table: Any) -> str:
    """Render one PyMuPDF table using the same formatter as structural chunks."""
    header, rows, columns, _ = extract_table_data(table)
    return render_markdown_table(header, rows, columns)


def find_table_regions(pdf_document, lines: list[PageLine]) -> list[TableRegion]:
    """Locate tables geometrically and map them onto the line model.

    Args:
        pdf_document: an open ``fitz.Document``.
        lines: the document line model.

    Returns:
        One :class:`TableRegion` per detected table.
    """
    by_page: dict[int, list[PageLine]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    regions: list[TableRegion] = []

    for page_index in range(len(pdf_document)):
        page = pdf_document[page_index]
        page_no = page_index + 1
        try:
            found = page.find_tables()
            tables = list(found.tables)
        except Exception:  # pragma: no cover - PyMuPDF version differences
            continue

        for table in tables:
            try:
                bbox = tuple(float(v) for v in table.bbox)
                n_rows = int(getattr(table, "row_count", 0) or 0)
                n_cols = int(getattr(table, "col_count", 0) or 0)
            except Exception:  # pragma: no cover
                continue
            header, data_rows, n_cols, header_external = extract_table_data(table)

            inside = frozenset(
                line.ordinal
                for line in by_page.get(page_no, [])
                if _contains(bbox, line.bbox)
            )
            if not inside:
                continue

            # Close the span. A table is a contiguous visual block, so its lines
            # are contiguous in reading order; filling any gap guarantees the
            # region becomes a single indivisible unit downstream. Without this,
            # a stray gap let 5 of 198 tables on the real document be split
            # across chunk boundaries.
            page_ordinals = {line.ordinal for line in by_page.get(page_no, [])}
            span = frozenset(
                o for o in range(min(inside), max(inside) + 1) if o in page_ordinals
            )

            regions.append(
                TableRegion(
                    page=page_no,
                    bbox=bbox,  # type: ignore[arg-type]
                    rows=n_rows,
                    cols=n_cols,
                    ordinals=span,
                    header=header,
                    data_rows=data_rows,
                    header_external=header_external,
                    page_height=float(page.rect.height),
                )
            )

    return inherit_continuation_headers(_merge_overlapping(regions))


def _merge_overlapping(regions: list[TableRegion]) -> list[TableRegion]:
    """Union table regions on the same page whose line spans intersect.

    ``find_tables()`` regularly reports several overlapping bounding boxes for one
    visual table -- on page 285 of the real document a table reported as 2 rows
    claimed 63 lines, overlapping its neighbours. Left separate, the overlapping
    regions each claim the shared ordinals and fragment one another, which is how
    5 of 198 tables ended up split across chunk boundaries. Merging first makes
    each visual table exactly one indivisible unit.
    """
    if not regions:
        return []

    by_page: dict[int, list[TableRegion]] = {}
    for region in regions:
        by_page.setdefault(region.page, []).append(region)

    merged: list[TableRegion] = []

    for page in sorted(by_page):
        ordered = sorted(by_page[page], key=lambda r: min(r.ordinals))
        current = ordered[0]

        for candidate in ordered[1:]:
            overlaps = (
                min(candidate.ordinals) <= max(current.ordinals) + 1
            )
            if overlaps:
                richer = max(
                    (current, candidate),
                    key=lambda region: (1 + len(region.data_rows)) * region.cols,
                )
                # Both operands are contiguous within this page's ordinals, and
                # they overlap or abut, so their union is contiguous too.
                current = TableRegion(
                    page=page,
                    bbox=(
                        min(current.bbox[0], candidate.bbox[0]),
                        min(current.bbox[1], candidate.bbox[1]),
                        max(current.bbox[2], candidate.bbox[2]),
                        max(current.bbox[3], candidate.bbox[3]),
                    ),
                    rows=max(current.rows, candidate.rows),
                    cols=max(current.cols, candidate.cols),
                    ordinals=current.ordinals | candidate.ordinals,
                    header=richer.header,
                    data_rows=richer.data_rows,
                    header_external=richer.header_external,
                    page_height=current.page_height,
                )
            else:
                merged.append(current)
                current = candidate

        merged.append(current)

    return merged


def _row_signature(row: tuple[str, ...], columns: int) -> tuple[str, ...]:
    """Classify cells coarsely enough to distinguish headers from body rows."""
    padded = list(row[:columns]) + [""] * max(0, columns - len(row))
    signature = []
    for cell in padded:
        value = re.sub(r"\s+", " ", cell).strip()
        has_alpha = any(character.isalpha() for character in value)
        has_digit = any(character.isdigit() for character in value)
        if not value:
            signature.append("empty")
        elif has_alpha and has_digit:
            signature.append("mixed")
        elif has_digit:
            signature.append("numeric")
        else:
            signature.append("text")
    return tuple(signature)


def _looks_like_body_row(row: tuple[str, ...], previous: TableRegion) -> bool:
    """True when an inferred header has the prior table's body shape, not its header."""
    candidate = _row_signature(row, previous.cols)
    header = _row_signature(previous.header, previous.cols)
    body = {_row_signature(data_row, previous.cols) for data_row in previous.data_rows}
    return candidate != header and candidate in body


def inherit_continuation_headers(regions: list[TableRegion]) -> list[TableRegion]:
    """Restore the header on a table that flows onto the following page.

    PyMuPDF labels the first data row on a headerless continuation as an internal
    header. A continuation must match both page-edge geometry and the prior table's
    body-row shape; this avoids relabeling an unrelated next-page table that happens
    to have the same width and column count.
    """
    restored: list[TableRegion] = []
    for region in regions:
        previous = restored[-1] if restored else None
        continues = bool(
            previous
            and region.page == previous.page + 1
            and region.cols == previous.cols
            and not region.header_external
            and region.header != previous.header
            and _looks_like_body_row(region.header, previous)
            and abs(region.bbox[0] - previous.bbox[0]) <= 12
            and abs(region.bbox[2] - previous.bbox[2]) <= 12
            and previous.page_height > 0
            and region.page_height > 0
            and previous.bbox[3] >= previous.page_height * 0.75
            and region.bbox[1] <= region.page_height * 0.25
        )
        if continues and previous is not None:
            # The inferred "header" is really the continuation's first data row.
            region = replace(
                region,
                header=previous.header,
                data_rows=(region.header,) + region.data_rows,
            )
        restored.append(region)
    return restored


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float = 2.0,
) -> bool:
    """True when ``inner``'s centre sits within ``outer`` on both axes.

    Testing the vertical axis alone over-claims: any line sharing a horizontal
    band with the table -- a marginal note, a second column -- was being absorbed
    into the table region, which fragmented the region's ordinal set.
    """
    cy = (inner[1] + inner[3]) / 2.0
    cx = (inner[0] + inner[2]) / 2.0
    return (
        (outer[1] - tolerance) <= cy <= (outer[3] + tolerance)
        and (outer[0] - tolerance) <= cx <= (outer[2] + tolerance)
    )


def table_ordinals(regions: list[TableRegion]) -> frozenset[int]:
    """Union of every line ordinal inside any table."""
    out: set[int] = set()
    for region in regions:
        out |= region.ordinals
    return frozenset(out)


def markdown_table_blocks(text: str) -> list[tuple[int, int]]:
    """Find pipe-table runs in markdown as ``(start_line, end_line)`` index pairs.

    Inclusive of both ends, indexing ``text.splitlines()``.
    """
    lines = text.splitlines()
    spans: list[tuple[int, int]] = []
    start: int | None = None

    for index, line in enumerate(lines):
        if _PIPE_ROW.match(line):
            if start is None:
                start = index
        else:
            if start is not None:
                spans.append((start, index - 1))
                start = None

    if start is not None:
        spans.append((start, len(lines) - 1))

    # A single pipe line is not a table.
    return [(a, b) for a, b in spans if b > a]


def replace_markdown_tables(text: str, replacements: list[str]) -> str:
    """Replace detected pipe tables when they map one-to-one to extracted grids."""
    spans = markdown_table_blocks(text)
    if not spans or len(spans) != len(replacements):
        return text

    lines = text.splitlines()
    for (start, end), replacement in reversed(list(zip(spans, replacements, strict=True))):
        lines[start : end + 1] = replacement.splitlines()

    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def count_markdown_tables(text: str) -> int:
    """Number of distinct pipe-tables in ``text``."""
    return len(markdown_table_blocks(text))


def is_table_line(line: str) -> bool:
    return bool(_PIPE_ROW.match(line))


def is_separator_line(line: str) -> bool:
    return bool(_SEPARATOR_ROW.match(line))


def table_row_count(text: str) -> int:
    """Total pipe rows in ``text``, excluding separator rows."""
    return sum(
        1
        for line in text.splitlines()
        if is_table_line(line) and not is_separator_line(line)
    )
