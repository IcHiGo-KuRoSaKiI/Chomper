"""
Excel extractor using openpyxl.

Turns each worksheet into reader-friendly Markdown:

- Output is bounded to the cells that hold data. Formatting-only cells (a fill
  or border painted down to row 5000) no longer produce pages of ``|||``.
- Blocks of rows separated by fully empty rows become separate GFM tables.
- A leading row holding a single text cell (typically a title merged across
  the table, ``A1:D1``) becomes a ``### Title`` line above the table, and the
  next row is used as the header. A first row with numbers or dates in it is
  not promoted to a header; the table gets an empty header row instead.
- Merged cells keep their value in the top-left cell only; spanned cells stay
  empty rather than repeating the value.
- Values follow their number format where that is cheap: dates as ISO
  ``2024-03-01`` (``2024-03-02 14:30`` when there is a time part, seconds only
  when non-zero), percentages (``0.0%`` -> ``12.5%``), thousands separators
  (``#,##0`` -> ``1,234,567``), fixed decimals (``0.00``) and currency symbols.
  General numbers drop float noise (``0.30000000000000004`` -> ``0.3``).
- Formulas without a cached value (files written by scripts, never opened in
  Excel) fall back to the formula text, e.g. ``=SUM(B2:B3)``, instead of blank.
- Hidden sheets are marked ``(hidden)`` in their heading and listed in
  ``metadata["hidden_sheets"]``.

``structure["sheets"][i]["markdown"]`` holds that Markdown (``RawDocument.text``
is built from it). ``structure["sheets"][i]["text"]`` keeps a row-aligned pipe
grid -- one row per worksheet row from row 1, columns from A, same value
formatting, bounded the same way -- because ``ExcelChunker`` slices it by
worksheet row and column index.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    import openpyxl

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from ..models.document import RawDocument
from ..models.excel_models import ExcelMetadata, SheetInfo, TableRange
from .base import BaseExtractor
from .markdown_utils import MarkdownBuilder, heading, render_table

logger = logging.getLogger(__name__)

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_RE = re.compile(rb"<(?:\w+:)?c\s[^>]*?(?:/>|>(.*?)</(?:\w+:)?c>)", re.S)
_FORMULA_RE = re.compile(rb"<(?:\w+:)?f[\s>/]")
_CACHED_RE = re.compile(rb"<(?:\w+:)?v>[^<]")
# Number format pieces that never print digits: quoted literals, [colour] /
# [$locale] tags, escaped characters, padding and fill directives.
_FORMAT_NOISE_RE = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.')
_CURRENCY_RE = re.compile(r'\[\$([^\]\-]+)|"([^"]*[$€£¥][^"]*)"|([$€£¥])')

#: Maximum leading single-cell rows treated as titles above one table.
_MAX_TITLE_ROWS = 3


@dataclass
class _SheetGrid:
    """The non-empty cells of one sheet, already formatted for output."""

    values: dict[tuple[int, int], str] = field(default_factory=dict)
    kinds: dict[tuple[int, int], str] = field(default_factory=dict)
    bold: set[tuple[int, int]] = field(default_factory=set)
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)
    has_formulas: bool = False

    @property
    def max_row(self) -> int:
        return max((r for r, _ in self.values), default=0)

    @property
    def max_col(self) -> int:
        return max((c for _, c in self.values), default=0)


@dataclass
class _Region:
    """A block of consecutive non-empty rows (one table, maybe with titles)."""

    start_row: int
    end_row: int
    start_col: int
    end_col: int
    title_rows: list[int] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    header_row: int | None = None


class ExcelExtractor(BaseExtractor):
    """
    Extract content from Excel files (.xlsx, .xlsm, .xltx, .xltm).

    See the module docstring for the output format.
    """

    SUPPORTED_EXTENSIONS = [".xlsx", ".xlsm", ".xltx", ".xltm"]

    def __init__(
        self,
        data_only: bool = True,
        detect_tables: bool = True,
        min_table_rows: int = 2,
        min_table_cols: int = 2,
        fill_merged_cells: bool = False,
    ):
        """
        Initialize Excel extractor.

        Args:
            data_only: Use cached values (falling back to the formula text when
                a formula has none) instead of always showing formulas.
            detect_tables: Record detected table ranges in ``SheetInfo.tables``.
            min_table_rows: Minimum rows for a recorded table range.
            min_table_cols: Minimum columns for a recorded table range.
            fill_merged_cells: Repeat a merged value in every spanned cell.
                Off by default: duplicated values mislead readers and inflate
                token counts.
        """
        if not OPENPYXL_AVAILABLE:
            raise ImportError(
                "openpyxl is required for Excel extraction. Install with: pip install openpyxl"
            )

        self.data_only = data_only
        self.detect_tables = detect_tables
        self.min_table_rows = min_table_rows
        self.min_table_cols = min_table_cols
        self.fill_merged_cells = fill_merged_cells

    # ------------------------------------------------------------------ extract

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from an Excel file.

        Args:
            file_path: Path to Excel file

        Returns:
            RawDocument with Markdown text and per-sheet structure
        """
        self.validate_file(file_path)

        workbook = openpyxl.load_workbook(file_path, data_only=self.data_only)
        formula_scan = _scan_formulas(file_path)
        formula_book: Any = None

        sheets_data: list[dict[str, Any]] = []
        hidden_sheets: list[str] = []
        excel_metadata = ExcelMetadata(
            filename=Path(file_path).name, total_sheets=len(workbook.sheetnames)
        )

        try:
            for sheet_idx, sheet_name in enumerate(workbook.sheetnames):
                sheet = workbook[sheet_name]
                hidden = getattr(sheet, "sheet_state", "visible") != "visible"
                if hidden:
                    hidden_sheets.append(sheet_name)
                if not hasattr(sheet, "iter_rows"):  # chartsheet: no cells
                    excel_metadata.sheets.append(
                        SheetInfo(name=sheet_name, index=sheet_idx, max_row=0, max_column=0, has_data=False)
                    )
                    continue

                has_formulas, uncached = formula_scan.get(sheet_name, (False, False))
                formula_sheet = None
                if self.data_only and uncached:
                    if formula_book is None:
                        formula_book = openpyxl.load_workbook(file_path, data_only=False)
                    formula_sheet = formula_book[sheet_name]

                grid = self._read_grid(sheet, formula_sheet)
                grid.has_formulas = grid.has_formulas or has_formulas
                regions = self._find_regions(grid)
                sheet_info = self._sheet_info(sheet_name, sheet_idx, grid, regions)
                excel_metadata.sheets.append(sheet_info)

                if sheet_info.is_empty:
                    continue
                markdown = self._sheet_markdown(sheet_name, hidden, grid, regions)
                sheets_data.append(
                    {
                        "sheet_name": sheet_name,
                        "sheet_index": sheet_idx,
                        "hidden": hidden,
                        "text": self._grid_text(grid),
                        "markdown": markdown,
                        "info": sheet_info,
                    }
                )
        finally:
            workbook.close()
            if formula_book is not None:
                formula_book.close()

        full_text = "\n\n".join(sheet["markdown"] for sheet in sheets_data)

        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_workbook_metadata(workbook, excel_metadata))
        metadata["hidden_sheets"] = hidden_sheets

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={"sheets": sheets_data, "excel_metadata": excel_metadata},
        )

    # --------------------------------------------------------------- reading

    def _read_grid(self, sheet: Any, formula_sheet: Any) -> _SheetGrid:
        """Collect every non-empty cell, formatted, plus merges and bold flags."""
        grid = _SheetGrid()
        cells = getattr(sheet, "_cells", None)
        items = (
            cells.items()
            if isinstance(cells, dict)
            else (((c.row, c.column), c) for row in sheet.iter_rows() for c in row)
        )
        for coord, cell in items:
            value = cell.value
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            text, kind = _format_value(value, cell.number_format)
            grid.values[coord] = text
            grid.kinds[coord] = kind
            if kind == "formula":
                grid.has_formulas = True
            font = cell.font
            if font is not None and font.bold:
                grid.bold.add(coord)

        if formula_sheet is not None:
            # Formulas Excel never calculated: show the formula, not a blank.
            for coord, cell in getattr(formula_sheet, "_cells", {}).items():
                if coord in grid.values:
                    continue
                formula = _formula_text(cell.value)
                if formula:
                    grid.values[coord] = formula
                    grid.kinds[coord] = "formula"
                    grid.has_formulas = True

        max_row, max_col = grid.max_row, grid.max_col
        for merged in sheet.merged_cells.ranges:
            if merged.min_row > max_row or merged.min_col > max_col:
                continue  # formatting-only merge outside the data
            grid.merges.append(
                (merged.min_row, merged.min_col, min(merged.max_row, max_row), min(merged.max_col, max_col))
            )
            if self.fill_merged_cells:
                anchor = grid.values.get((merged.min_row, merged.min_col))
                if anchor is None:
                    continue
                for r in range(merged.min_row, min(merged.max_row, max_row) + 1):
                    for c in range(merged.min_col, min(merged.max_col, max_col) + 1):
                        grid.values.setdefault((r, c), anchor)
                        grid.kinds.setdefault((r, c), grid.kinds[(merged.min_row, merged.min_col)])
        return grid

    # --------------------------------------------------------------- layout

    def _find_regions(self, grid: _SheetGrid) -> list[_Region]:
        """Split the sheet into blocks of rows separated by empty rows."""
        by_row: dict[int, list[int]] = {}
        for r, c in grid.values:
            by_row.setdefault(r, []).append(c)

        regions: list[_Region] = []
        for row in sorted(by_row):
            if regions and regions[-1].end_row == row - 1:
                region = regions[-1]
                region.end_row = row
                region.start_col = min(region.start_col, *by_row[row])
                region.end_col = max(region.end_col, *by_row[row])
            else:
                regions.append(_Region(row, row, min(by_row[row]), max(by_row[row])))

        horizontal_merges = {(r, c) for r, c, _, c2 in grid.merges if c2 > c}
        for region in regions:
            first = region.start_row
            # Leading rows with one text cell, above rows with several, are titles.
            while (
                len(region.title_rows) < _MAX_TITLE_ROWS
                and first < region.end_row
                and len(by_row[first]) == 1
                and grid.kinds.get((first, by_row[first][0])) == "text"
                and any(len(by_row.get(r, [])) > 1 for r in range(first + 1, region.end_row + 1))
            ):
                region.title_rows.append(first)
                region.titles.append(grid.values[(first, by_row[first][0])])
                first += 1
            if first == region.start_row and region.start_row == region.end_row:
                # A lone row: a title only when merged across columns.
                cols = by_row[first]
                if len(cols) == 1 and (first, cols[0]) in horizontal_merges:
                    region.title_rows.append(first)
                    region.titles.append(grid.values[(first, cols[0])])
                    continue
            body_cols = [c for r in range(first, region.end_row + 1) for c in by_row.get(r, [])]
            if body_cols:
                region.start_col = min(body_cols)
                region.end_col = max(body_cols)
            if self._is_header_row(grid, first, by_row[first], region.end_row > first):
                region.header_row = first
        return regions

    @staticmethod
    def _is_header_row(grid: _SheetGrid, row: int, cols: list[int], has_body: bool) -> bool:
        """A header is mostly bold, or all text sitting above more rows."""
        coords = [(row, c) for c in cols]
        if sum(coord in grid.bold for coord in coords) * 2 > len(coords):
            return True
        return has_body and all(grid.kinds.get(coord) == "text" for coord in coords)

    def _sheet_markdown(
        self, name: str, hidden: bool, grid: _SheetGrid, regions: list[_Region]
    ) -> str:
        builder = MarkdownBuilder()
        builder.add_block(heading(f"Sheet: {name}" + (" (hidden)" if hidden else ""), 2))
        for region in regions:
            for title in region.titles:
                builder.add_block(heading(title, 3))
            first = region.title_rows[-1] + 1 if region.title_rows else region.start_row
            if first > region.end_row:
                continue
            rows = [
                [grid.values.get((r, c), "") for c in range(region.start_col, region.end_col + 1)]
                for r in range(first, region.end_row + 1)
            ]
            if len(rows) == 1 and len(rows[0]) == 1:
                builder.add_block(rows[0][0])
                continue
            builder.add_block(render_table(rows, header_rows=1 if region.header_row else 0))
        return builder.build()

    @staticmethod
    def _grid_text(grid: _SheetGrid) -> str:
        """Row-aligned pipe grid from A1 to the last data cell (for the chunker)."""
        rows = [
            [grid.values.get((r, c), "") for c in range(1, grid.max_col + 1)]
            for r in range(1, grid.max_row + 1)
        ]
        return render_table(rows)

    def _sheet_info(
        self, name: str, index: int, grid: _SheetGrid, regions: list[_Region]
    ) -> SheetInfo:
        max_row, max_col = grid.max_row, grid.max_col
        tables: list[TableRange] = []
        if self.detect_tables:
            for region in regions:
                rows = region.end_row - region.start_row + 1
                cols = region.end_col - region.start_col + 1
                if rows >= self.min_table_rows and cols >= self.min_table_cols:
                    tables.append(
                        TableRange(
                            sheet_name=name,
                            start_row=region.start_row,
                            start_col=region.start_col,
                            end_row=region.end_row,
                            end_col=region.end_col,
                            header_row=region.header_row,
                            has_headers=region.header_row is not None,
                        )
                    )
        return SheetInfo(
            name=name,
            index=index,
            max_row=max_row,
            max_column=max_col,
            has_data=bool(grid.values),
            tables=tables,
            merged_cells=grid.merges,
            has_formulas=grid.has_formulas,
            has_merged_cells=bool(grid.merges),
            column_types=self._infer_column_types(grid, max_col),
        )

    @staticmethod
    def _infer_column_types(grid: _SheetGrid, max_column: int) -> dict[int, str]:
        """Predominant value type per column over the first 20 rows."""
        column_types: dict[int, str] = {}
        for col in range(1, max_column + 1):
            seen = {grid.kinds[(r, col)] for r in range(1, 21) if (r, col) in grid.kinds}
            if "number" in seen and "text" in seen:
                column_types[col] = "mixed"
            elif "number" in seen:
                column_types[col] = "number"
            elif "date" in seen:
                column_types[col] = "date"
            elif "boolean" in seen:
                column_types[col] = "boolean"
            else:
                column_types[col] = "text"
        return column_types

    def _extract_workbook_metadata(self, workbook: Any, excel_metadata: ExcelMetadata) -> dict[str, Any]:
        """Workbook-level metadata."""
        metadata: dict[str, Any] = {
            "format": "excel",
            "total_sheets": excel_metadata.total_sheets,
            "num_sheets": excel_metadata.total_sheets,
            "active_sheets": len(excel_metadata.active_sheets),
            "total_tables": excel_metadata.total_tables,
            "has_multiple_sheets": excel_metadata.has_multiple_sheets,
            "sheet_names": [sheet.name for sheet in excel_metadata.sheets],
        }
        props = getattr(workbook, "properties", None)
        if props is not None:
            if props.creator:
                metadata["author"] = props.creator
            if props.created:
                metadata["created"] = str(props.created)
            if props.modified:
                metadata["modified"] = str(props.modified)
            if props.title:
                metadata["title"] = props.title
        return metadata


# ------------------------------------------------------------------- formulas


def _scan_formulas(file_path: str) -> dict[str, tuple[bool, bool]]:
    """
    Per sheet name: ``(has_formulas, has_formula_without_cached_value)``.

    Read straight from the worksheet XML: with ``data_only=True`` openpyxl hides
    formulas entirely, and loading the workbook a second time just to find out
    is expensive. The second load only happens for sheets that need it.
    """
    result: dict[str, tuple[bool, bool]] = {}
    try:
        with zipfile.ZipFile(file_path) as archive:
            book = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{_NS_PKG_REL}Relationship")}
            for sheet in book.iter(f"{_NS_MAIN}sheet"):
                target = targets.get(sheet.get(f"{_NS_REL}id"), "")
                part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                if part not in archive.namelist():
                    continue
                data = archive.read(part)
                if not _FORMULA_RE.search(data):
                    result[sheet.get("name", "")] = (False, False)
                    continue
                uncached = any(
                    inner and _FORMULA_RE.search(inner) and not _CACHED_RE.search(inner)
                    for inner in (m.group(1) for m in _CELL_RE.finditer(data))
                )
                result[sheet.get("name", "")] = (True, uncached)
    except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as e:
        logger.warning(f"Could not scan formulas in {file_path}: {e}")
    return result


def _formula_text(value: Any) -> str | None:
    """``=SUM(A1:A3)`` from a formula cell value (plain or array formula)."""
    if isinstance(value, str) and value.startswith("="):
        return value
    text = getattr(value, "text", None)  # openpyxl ArrayFormula / DataTableFormula
    if isinstance(text, str) and text:
        return text if text.startswith("=") else f"={text}"
    return None


# ------------------------------------------------------------------ formatting


def _format_value(value: Any, number_format: str | None) -> tuple[str, str]:
    """Display text and kind (text/number/date/boolean/formula) for one cell."""
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), "boolean"
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.date().isoformat(), "date"
        fmt = "%Y-%m-%d %H:%M" if not value.second and not value.microsecond else "%Y-%m-%d %H:%M:%S"
        return value.strftime(fmt), "date"
    if isinstance(value, date):
        return value.isoformat(), "date"
    if isinstance(value, time):
        return value.strftime("%H:%M" if not value.second else "%H:%M:%S"), "date"
    if isinstance(value, timedelta):
        return str(value), "date"
    if isinstance(value, (int, float)):
        return _format_number(value, number_format or "General"), "number"
    formula = _formula_text(value)
    if formula:
        return formula, "formula"
    return str(value).strip(), "text"


def _general(value: float) -> str:
    if isinstance(value, int):
        return str(value)
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.15g}"


def _format_number(value: float, number_format: str) -> str:
    """Apply the cheap, common parts of an Excel number format."""
    section = number_format.split(";")[0]
    clean = _FORMAT_NOISE_RE.sub("", section)
    if section in ("General", "@", "") or not re.search(r"[0#?]", clean):
        return _general(value)
    match = re.search(r"\.([0#?]+)", clean)
    decimals = len(match.group(1)) if match else 0
    if "%" in clean:
        return f"{value * 100:.{decimals}f}%"
    if re.search(r"E[+-]", clean, re.I):
        return f"{value:.{decimals}E}"
    integer_part = clean.split(".")[0]
    text = f"{value:,.{decimals}f}" if "," in integer_part else f"{value:.{decimals}f}"

    symbol_match = _CURRENCY_RE.search(section)
    if symbol_match:
        symbol = next(g for g in symbol_match.groups() if g)
        digits_at = re.search(r"[0#?]", section)
        if digits_at and symbol_match.start() < digits_at.start():
            sign = "-" if text.startswith("-") else ""
            return f"{sign}{symbol}{text.lstrip('-')}"
        return f"{text}{symbol}"
    return text
