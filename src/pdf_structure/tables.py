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

import re
from dataclasses import dataclass, replace
from typing import Any

from .lines import PageLine

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


def extract_table_data(
    table: Any,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], int, bool]:
    """Extract a PyMuPDF table into header, body, width and header provenance."""
    extracted = tuple(
        tuple("" if cell is None else str(cell) for cell in row)
        for row in (table.extract() or ())
    )
    header_object = getattr(table, "header", None)
    header_names = tuple(
        "" if cell is None else str(cell)
        for cell in (getattr(header_object, "names", None) or ())
    )
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

    def render_row(row: tuple[str, ...]) -> str:
        cells = list(row[:columns]) + [""] * max(0, columns - len(row))
        clean = [re.sub(r"\s+", " ", cell).strip().replace("|", r"\|") for cell in cells]
        return "| " + " | ".join(clean) + " |"

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
