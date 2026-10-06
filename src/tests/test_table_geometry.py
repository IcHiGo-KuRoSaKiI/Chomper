"""
Geometry-based table reconstruction (``src.pdf_structure.table_geometry``),
from synthetic PDFs drawn with PyMuPDF.

Covers each generic feature on its own page layout:

* template statements: units header, indented stub with bold group rows,
  ``X`` placeholders, rules typed as ``––––`` (attributes, never cells);
* numeric statements with drawn rules, and the optional column-sum hint
  passing and failing (it never changes a number);
* two value columns under a years header (``2025  2024``);
* wrapped cell text and wrapped stub labels joined onto their row;
* spanning headers over the columns they overlap, never merged into values;
* dot leaders and ``====`` rules; ``--`` placeholders kept as values;
* unruled numeric tables (right-aligned columns) and row-ruled tables whose
  cells wrap;
* grid scoring: the geometric grid wins only over a model grid with defects;
* a plain grid that must stay as it is (no levels, no emphasis).

Run: ``python -m pytest src/tests/test_table_geometry.py -q``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF required")

from src.pdf_structure import table_geometry as tg  # noqa: E402
from src.pdf_structure.tables import render_markdown_table  # noqa: E402

SIZE = 10.0
LINE = 15.0


def _text(page: Any, x: float, y: float, text: str, *, bold: bool = False, right: bool = False, size: float = SIZE) -> None:
    """Write text with a TextWriter: ``insert_text`` with a base-14 name maps
    en dashes to other glyphs, a ``Font`` object keeps them."""
    font = fitz.Font("hebo" if bold else "helv")
    if right:
        x -= font.text_length(text, fontsize=size)
    writer = fitz.TextWriter(page.rect)
    writer.append((x, y), text, font=font, fontsize=size)
    writer.write_text(page)


def _rows_text(table: tg.GeoTable) -> list[list[str]]:
    return [[c.text for c in row.cells] for row in table.rows]


def _annotated(table: tg.GeoTable) -> tuple[list[tg.RowInfo], int]:
    infos = tg.rows_from_geometry(table)
    return infos, tg.annotate_rows(infos)


@pytest.fixture
def doc():
    document = fitz.open()
    yield document
    document.close()


# ---------------------------------------------------------------------------
# Statements: hierarchy, typed and drawn rules
# ---------------------------------------------------------------------------

# (indent level, label, bold, inner value, outer value); "RULE" in a value
# column types a rule of en dashes on its own line.
TEMPLATE = [
    (0, "Resources", True, "", ""),
    (1, "Long-lived resources", True, "", ""),
    (2, "Machinery and tools", False, "X", ""),
    (2, "Software licences", False, "X", ""),
    (None, "", False, "RULE", "X"),
    (1, "Short-lived resources", True, "", ""),
    (2, "Stock on hand", False, "X", ""),
    (2, "Money in the bank", False, "X", ""),
    (None, "", False, "RULE", "X"),
    (None, "", False, "", "RULE"),
    (0, "Total resources", True, "", "X"),
    (None, "", False, "", "RULE"),
]


def _statement(page: Any, rows: list[tuple[Any, ...]], *, top: float = 90.0) -> tuple[float, float, float, float]:
    """Draw a statement: units header, then rows; returns its bbox."""
    inner, outer = 420.0, 500.0
    _text(page, inner, top, "€m", right=True)
    _text(page, outer, top, "€m", right=True)
    y = top + LINE
    for level, label, bold, a, b in rows:
        if label:
            _text(page, 72 + 14 * (level or 0), y, label, bold=bold)
        for value, x in ((a, inner), (b, outer)):
            if value == "RULE":
                _text(page, x, y, "––––", right=True)
            elif value:
                _text(page, x, y, value, right=True)
        y += LINE
    return (70.0, top - 12, 505.0, y)


def test_template_statement_hierarchy_and_typed_rules(doc):
    page = doc.new_page()
    bbox = _statement(page, TEMPLATE)
    table = tg.reconstruct(page, bbox)
    assert table is not None
    grid = _rows_text(table)
    # Rules are attributes: no cell holds a dash run, and rule-only lines are no rows.
    assert not any("––" in cell for row in grid for cell in row)
    assert grid[0] == ["", "€m", "€m"]
    assert ["Machinery and tools", "X", ""] in grid
    assert ["", "", "X"] in grid  # an unlabelled value, kept as it is (no derived label)

    infos, header_rows = _annotated(table)
    assert header_rows == 1
    by_label = {i.cells[0]: i for i in infos if i.cells[0]}
    assert by_label["Resources"].emphasis == "group"
    assert by_label["Long-lived resources"].emphasis == "group"
    assert by_label["Long-lived resources"].level == 1
    assert by_label["Machinery and tools"].level == 2
    assert by_label["Machinery and tools"].path == ["Resources", "Long-lived resources"]
    assert by_label["Stock on hand"].path == ["Resources", "Short-lived resources"]
    total = by_label["Total resources"]
    assert total.emphasis == "total" and total.path == []
    assert total.rule_above != "none" and total.rule_below != "none"
    # The value under the inner column's rule closes that column.
    unlabelled = [i for i in infos if not i.cells[0] and i.cells[2] == "X"]
    assert unlabelled and all(i.rule_above == "single" and 1 in i.rule_above_cols for i in unlabelled)

    cells = tg.format_cells(infos)
    markdown = render_markdown_table(tuple(cells[0]), tuple(tuple(r) for r in cells[1:]), 3)
    assert "| **Resources** |" in markdown
    assert f"| {tg.EM_SPACE * 2}Machinery and tools | X |  |" in markdown
    assert f"| {tg.EM_SPACE}**Long-lived resources** |" in markdown
    assert "| **Total resources** |  | **X** |" in markdown


def _numeric_statement(page: Any, values: dict[str, str], top: float = 100.0) -> tuple[float, float, float, float]:
    """Income items, a drawn rule over the inner column, a subtotal, a total."""
    inner, outer = 400.0, 480.0
    _text(page, inner, top, "$", right=True)
    _text(page, outer, top, "$", right=True)
    y = top + LINE
    _text(page, 72, y, "Revenue")
    _text(page, outer, y, values["revenue"], right=True)
    y += LINE
    _text(page, 72, y, "Operating costs", bold=True)
    y += LINE
    for label, key in (("Wages", "wages"), ("Rent", "rent"), ("Power", "power")):
        _text(page, 86, y, label)
        _text(page, inner, y, values[key], right=True)
        y += LINE
    page.draw_line((inner - 40, y - LINE + 4), (inner, y - LINE + 4), width=0.6)
    _text(page, outer, y, values["costs"], right=True)
    y += LINE
    page.draw_line((outer - 40, y - LINE + 4), (outer, y - LINE + 4), width=0.6)
    _text(page, 72, y, "Profit", bold=True)
    _text(page, outer, y, values["profit"], right=True)
    page.draw_line((outer - 40, y + 4), (outer, y + 4), width=0.6)
    page.draw_line((outer - 40, y + 6), (outer, y + 6), width=0.6)
    return (70.0, top - 12, 485.0, y + 10)


@pytest.mark.parametrize(("costs", "ok"), [("2,100", True), ("2,000", False)])
def test_numeric_statement_drawn_rules_and_sum_hint(doc, costs, ok):
    page = doc.new_page()
    values = {"revenue": "5,000", "wages": "1,500", "rent": "400", "power": "200",
              "costs": costs, "profit": "2,900"}
    bbox = _numeric_statement(page, values)
    table = tg.reconstruct(page, bbox)
    assert table is not None
    infos, header_rows = _annotated(table)
    assert header_rows == 1
    rows = {i.cells[0]: i for i in infos if i.cells[0]}
    subtotal = next(i for i in infos if not i.cells[0] and i.cells[2] == costs)
    assert subtotal.rule_above == "single" and subtotal.rule_above_cols == [1]
    assert subtotal.emphasis == "total"
    assert rows["Wages"].path == ["Operating costs"]
    assert rows["Profit"].emphasis == "total"
    assert rows["Profit"].rule_below == "double"
    # The hint compares the items above the rule with the value under it.
    hint = next(h for h in tg.column_sum_hints(infos) if h["row"] == infos.index(subtotal))
    assert hint["from_column"] == 1 and hint["sum"] == 2100.0
    assert hint["ok"] is ok
    # It never edits: the printed number stays.
    assert subtotal.cells[2] == costs


def test_years_header_two_value_columns(doc):
    page = doc.new_page()
    top = 100.0
    _text(page, 72, top, "Summary of results", bold=True)
    _text(page, 400, top + LINE, "2025", right=True, bold=True)
    _text(page, 480, top + LINE, "2024", right=True, bold=True)
    data = [("Sales", "12,400", "11,050"), ("Cost of sales", "(7,300)", "(6,900)"), ("Gross profit", "5,100", "4,150")]
    y = top + 2 * LINE
    for label, a, b in data:
        _text(page, 72, y, label)
        _text(page, 400, y, a, right=True)
        _text(page, 480, y, b, right=True)
        y += LINE
    table = tg.reconstruct(page, (70, top - 12, 485, y))
    assert table is not None
    grid = _rows_text(table)
    # A short title inside the first column is a header row, kept as text.
    assert grid[0] == ["Summary of results", "", ""]
    assert grid[1] == ["", "2025", "2024"]
    assert grid[2] == ["Sales", "12,400", "11,050"]
    infos, header_rows = _annotated(table)
    assert header_rows == 2  # years are column headings, not data
    assert [c.align for c in table.columns[1:]] == ["right", "right"]


# ---------------------------------------------------------------------------
# Generic structure
# ---------------------------------------------------------------------------


def test_wrapped_cells_join_their_row(doc):
    page = doc.new_page()
    _text(page, 72, 100, "Item", bold=True)
    _text(page, 180, 100, "Description", bold=True)
    _text(page, 450, 100, "Qty", bold=True, right=True)
    rows = [
        ("Bolt", ["Hex head bolt, zinc plated, sold in", "boxes of one hundred"], "4"),
        ("Washer", ["Flat washer"], "12"),
        ("Bracket for wall", None, "2"),
    ]
    y = 100 + LINE
    for item, desc, qty in rows:
        _text(page, 72, y, item)
        if desc:
            for k, line in enumerate(desc):
                _text(page, 180, y + k * 11, line)
        _text(page, 450, y, qty, right=True)
        y += LINE + 11 * (len(desc or [""]) - 1)
    # A stub label wrapped onto a second line, values on the first.
    _text(page, 72, y - LINE + 11, "mounting")
    table = tg.reconstruct(page, (70, 88, 455, y + 4))
    assert table is not None
    grid = _rows_text(table)
    assert grid[1] == ["Bolt", "Hex head bolt, zinc plated, sold in boxes of one hundred", "4"]
    assert grid[2] == ["Washer", "Flat washer", "12"]
    assert grid[3][0] == "Bracket for wall mounting" and grid[3][2] == "2"
    assert len(grid) == 4


def test_spanning_header_stays_over_its_columns(doc):
    page = doc.new_page()
    xs = [260.0, 320.0, 380.0, 440.0]
    _text(page, 300, 100, "Sample size by effect")  # spans the four value columns
    _text(page, 72, 100 + LINE, "Rate")
    for x, v in zip(xs, ("1.0", "1.5", "2.0", "2.5"), strict=True):
        _text(page, x, 100 + LINE, v, right=True)
    y = 100 + 2 * LINE
    for rate in ("0.90", "0.80", "0.70", "0.60"):
        _text(page, 72, y, rate)
        for k, x in enumerate(xs):
            _text(page, x, y, str(80 + 10 * k + int(float(rate) * 10)), right=True)
        y += LINE
    table = tg.reconstruct(page, (70, 88, 445, y))
    assert table is not None
    grid = _rows_text(table)
    assert len(grid[0]) == 5
    header = table.rows[0]
    spanning = [c for c in header.cells if c.text]
    assert [c.text for c in spanning] == ["Sample size by effect"] and spanning[0].span >= 2
    # Never merged into the values or the sub-header below it.
    assert grid[1] == ["Rate", "1.0", "1.5", "2.0", "2.5"]
    assert all("Sample" not in cell for row in grid[1:] for cell in row)


def test_leaders_and_double_rules_are_not_cells(doc):
    page = doc.new_page()
    y = 100.0
    for label, value in (("Opening balance", "300"), ("Receipts", "--"), ("Payments", "120")):
        _text(page, 72, y, label + " " + "." * 30)
        _text(page, 400, y, value, right=True)
        y += LINE
    _text(page, 400, y, "========", right=True)
    _text(page, 72, y + LINE, "Closing balance")
    _text(page, 400, y + LINE, "180", right=True)
    table = tg.reconstruct(page, (70, 88, 405, y + LINE + 4))
    assert table is not None
    grid = _rows_text(table)
    assert grid[0] == ["Opening balance", "300"]
    assert grid[1] == ["Receipts", "--"]  # a "--" placeholder is a value, not a rule
    assert grid[-1] == ["Closing balance", "180"]
    assert table.rows[-1].rule_above == "double"
    assert not any("." * 4 in cell or "==" in cell for row in grid for cell in row)


def test_unruled_numeric_table_columns_from_alignment(doc):
    page = doc.new_page()
    y = 100.0
    _text(page, 72, y, "Country", bold=True)
    _text(page, 300, y, "Index", bold=True, right=True)
    _text(page, 380, y, "Change", bold=True, right=True)
    for name, a, b in (("Austria", "93.14", "+1.2"), ("Czech Republic", "32.62", "-0.4"), ("Japan", "153.36", "+12.0"), ("United Kingdom", "100.5", "0.0")):
        y += LINE
        _text(page, 72, y, name)
        _text(page, 300, y, a, right=True)
        _text(page, 380, y, b, right=True)
    table = tg.reconstruct(page, (70, 88, 385, y + 4))
    assert table is not None
    assert _rows_text(table) == [
        ["Country", "Index", "Change"],
        ["Austria", "93.14", "+1.2"],
        ["Czech Republic", "32.62", "-0.4"],
        ["Japan", "153.36", "+12.0"],
        ["United Kingdom", "100.5", "0.0"],
    ]
    infos, header_rows = _annotated(table)
    # Bold header row is not a group or total; all stubs flush left: no levels.
    assert header_rows == 1
    assert all(i.level == 0 and i.emphasis is None for i in infos)


def test_row_ruled_table_wrapped_cells_and_centred_neighbours(doc):
    """Each band between drawn row rules is one row, however its cells wrap,
    and a one-line cell centred in a two-line row does not fuse lines."""
    page = doc.new_page()
    x0, x1 = 70.0, 470.0
    rows = [
        (["Project"], ["Agency"], ["Place"]),
        (["Ethics of new materials in", "food production (pilot)"], ["Board"], ["North State", "University"]),
        (["Public views on sensors"], ["Office"], ["City College"]),
        (["Water reuse and its", "public acceptance"], ["Board"], ["West Institute"]),
    ]
    y = 100.0
    page.draw_line((x0, y), (x1, y), width=0.5)
    for cells in rows:
        height = 6 + 11 * max(len(c) for c in cells)
        for x, lines in zip((74.0, 280.0, 360.0), cells, strict=True):
            offset = (height - 11 * len(lines)) / 2  # vertically centred
            for k, line in enumerate(lines):
                _text(page, x, y + offset + 9 + 11 * k, line)
        y += height
        page.draw_line((x0, y), (x1, y), width=0.5)
    for x in (x0, 276.0, 356.0, x1):
        page.draw_line((x, 100), (x, y), width=0.5)
    table = tg.reconstruct(page, (x0, 99, x1, y + 1))
    assert table is not None
    assert table.ruled
    assert _rows_text(table) == [
        ["Project", "Agency", "Place"],
        ["Ethics of new materials in food production (pilot)", "Board", "North State University"],
        ["Public views on sensors", "Office", "City College"],
        ["Water reuse and its public acceptance", "Board", "West Institute"],
    ]


# ---------------------------------------------------------------------------
# Choosing between grids
# ---------------------------------------------------------------------------


def _merged_column_page(page: Any) -> tuple[tuple[float, float, float, float], list[list[Any]], list[list[str]]]:
    """A 4-column numeric table and a model-like grid that merged columns 2-4."""
    xs = [250.0, 310.0, 370.0]
    y = 100.0
    _text(page, 72, y, "Group")
    for x, h in zip(xs, ("A", "B", "C"), strict=True):
        _text(page, x, y, h, right=True)
    names = ["North", "South", "East", "West", "Centre"]
    for n, name in enumerate(names):
        y += LINE
        _text(page, 72, y, name)
        for k, x in enumerate(xs):
            _text(page, x, y, str(10 * (n + 1) + k), right=True)
    bbox = (70.0, 88.0, 375.0, y + 4)
    cells, grid = [], []
    for r in range(len(names) + 1):
        top = 88.0 + r * LINE
        cells.append([(70.0, top, 200.0, top + LINE), (200.0, top, 375.0, top + LINE)])
    words = tg.page_words(page, bbox)
    for row in cells:
        grid.append([
            " ".join(w.text for w in words if b[0] <= w.xc <= b[2] and b[1] <= w.yc <= b[3]) for b in row
        ])
    return bbox, cells, grid


def test_geometry_wins_over_merged_columns_only(doc):
    page = doc.new_page()
    bbox, cells, grid = _merged_column_page(page)
    words = tg.page_words(page, bbox)
    geo = tg.reconstruct(page, bbox, words=words)
    assert geo is not None and len(geo.columns) == 4
    model_score = tg.grid_quality(words, cells, geo)
    geo_score = tg.grid_quality(words, geo.cell_boxes, geo)
    assert model_score.merged_cells >= 5 and geo_score.defects == 0
    assert tg.prefer_geometry(model_score, geo_score)
    # The geometric grid against itself: no defects, so nothing to fix.
    assert not tg.prefer_geometry(geo_score, geo_score)


def test_snap_to_words_keeps_lattice_and_whole_words(doc):
    """A model lattice whose edge cuts through a word: the text is re-read
    from whole words (each in the cell holding its centre), and the scorer
    counts the cut."""
    page = doc.new_page()
    _text(page, 72, 100, "Pesticide")
    _text(page, 150, 100, "1979")
    _text(page, 200, 100, "1980")
    _text(page, 72, 115, "Herbicides")
    _text(page, 150, 115, "610")
    _text(page, 200, 115, "622")
    words = tg.page_words(page, (60, 85, 260, 125))
    # The second edge (185) falls inside "1979"'s neighbour column; the first
    # (158) cuts "1979" itself.
    cells = [[(60, 88, 140, 104), (140, 88, 158, 104), (158, 88, 260, 104)],
             [(60, 104, 140, 120), (140, 104, 158, 120), (158, 104, 260, 120)]]
    score = tg.grid_quality(words, cells, None)
    assert score.split_words >= 1
    grid = tg.snap_to_words(words, cells)
    # "1979" (centre right of 158) lands whole in the last cell, not "19" | "79".
    assert grid == [["Pesticide", "", "1979 1980"], ["Herbicides", "", "610 622"]]


def test_model_grid_rule_glyphs_become_attributes():
    infos = tg.rows_from_grid(
        [],
        [[None, None, None]] * 4,
        [["Cash", "15", ""], ["", "––––", ""], ["", "", "15"], ["", "––––", "––––"]],
    )
    assert [i.cells for i in infos] == [["Cash", "15", ""], ["", "", "15"]]
    assert infos[1].rule_above == "single" and infos[1].rule_above_cols == [1]
    assert infos[1].rule_below == "single"


def test_plain_grid_is_left_alone(doc):
    """A plain table: no indent levels, no bold rows, nothing reordered."""
    page = doc.new_page()
    header = ["Name", "Role", "City"]
    body = [["Ana Lima", "Engineer", "Porto"], ["Bo Chen", "Designer", "Leeds"], ["Cy Dube", "Analyst", "Accra"]]
    xs = [72.0, 200.0, 330.0]
    y = 100.0
    for row in [header, *body]:
        for x, text in zip(xs, row, strict=True):
            _text(page, x, y, text)
        y += LINE
    table = tg.reconstruct(page, (70, 88, 400, y))
    assert table is not None
    assert _rows_text(table) == [header, *body]
    infos, header_rows = _annotated(table)
    assert header_rows == 1
    assert all(i.level == 0 and i.emphasis is None and i.rule_above == "none" for i in infos)
    cells = tg.format_cells(infos)
    assert cells == [header, *body]


def test_oversized_invisible_word_does_not_fuse_lines(doc):
    """An OCR pass can leave an invisible word whose box covers a whole block;
    it must not pull the lines it overlaps into one."""
    page = doc.new_page()
    y = 100.0
    for label, a, b in (("Opening", "10", "20"), ("Added", "5", "6"), ("Closing", "15", "26")):
        _text(page, 72, y, label)
        _text(page, 300, y, a, right=True)
        _text(page, 380, y, b, right=True)
        y += LINE
    writer = fitz.TextWriter(page.rect)
    writer.append((80, y - 4), "——", font=fitz.Font("helv"), fontsize=60)
    writer.write_text(page, render_mode=3)  # invisible, like OCR text
    table = tg.reconstruct(page, (70, 88, 400, y))
    assert table is not None
    assert _rows_text(table) == [["Opening", "10", "20"], ["Added", "5", "6"], ["Closing", "15", "26"]]


def test_rule_text_versus_placeholders():
    assert tg.is_rule_text("––––", 24, 11)
    assert tg.is_rule_text("________", 40, 11)
    assert not tg.is_rule_text("--", 7, 11)
    assert not tg.is_rule_text("—", 10, 11)
    assert not tg.is_rule_text("–", 6, 11)
    assert tg.is_leader_text("..........") and not tg.is_leader_text("...")
    assert tg.is_numeric("(1,234)") and tg.is_numeric("X") and tg.is_numeric("–")
    assert not tg.is_numeric("(000)") and tg.is_unit("€m") and tg.is_unit("(mn ecu)")


def test_markdown_keeps_indent_em_spaces():
    md = render_markdown_table(("", "€m"), ((tg.EM_SPACE * 2 + "Item  one", "X"),), 2)
    assert f"| {tg.EM_SPACE * 2}Item one | X |" in md


# ---------------------------------------------------------------------------
# Borderless tables left as text
# ---------------------------------------------------------------------------


def test_text_run_table_is_strict(doc):
    from src.extractors.pdf_layout import _text_run_table

    page = doc.new_page()
    # A small numeric grid.
    y = 100.0
    for row in (("method", "P", "R", "F1"), ("base", "0.71", "0.65", "0.68"), ("ours", "0.79", "0.74", "0.76"), ("oracle", "0.91", "0.90", "0.90")):
        for x, text in zip((72.0, 200.0, 260.0, 320.0), row, strict=True):
            _text(page, x, y, text)
        y += LINE
    grid_box = {"bbox": (70, 88, 340, y)}
    geo = _text_run_table(page, grid_box)
    assert geo is not None and _rows_text(geo)[1] == ["base", "0.71", "0.65", "0.68"]

    # Prose, and a list of answer options, are not tables.
    y = 300.0
    for line in ("The committee met twice in the year and reviewed the", "accounts, the budget and the plans for next year."):
        _text(page, 72, y, line)
        y += LINE
    assert _text_run_table(page, {"bbox": (70, 288, 400, y)}) is None
    y = 400.0
    for letter, amount in (("A", "£2,500"), ("B", "£2,700"), ("C", "£4,200"), ("D", "£2,750")):
        _text(page, 90, y, letter)
        _text(page, 110, y, amount)
        y += LINE
    assert _text_run_table(page, {"bbox": (70, 388, 300, y)}) is None


# ---------------------------------------------------------------------------
# End to end through the PDF extractor
# ---------------------------------------------------------------------------


def _layout_available() -> bool:
    try:
        from src.extractors.pdf_layout import LAYOUT_AVAILABLE
    except Exception:
        return False
    return bool(LAYOUT_AVAILABLE)


@pytest.mark.skipif(not _layout_available(), reason="pymupdf-layout not installed")
def test_extractor_renders_statement_and_records_structure(tmp_path):
    from src.extractors.pdf_extractor import PDFExtractor

    path = tmp_path / "statement.pdf"
    document = fitz.open()
    page = document.new_page()
    _text(page, 72, 60, "Statement of resources at year end", bold=True, size=12)
    _statement(page, TEMPLATE)
    _text(page, 72, 400, "The statement above is an illustrative template with placeholder values only.")
    document.save(path)
    document.close()

    raw = PDFExtractor().extract(str(path))
    assert "––" not in raw.text
    assert f"{tg.EM_SPACE * 2}Machinery and tools" in raw.text
    assert "**Resources**" in raw.text
    tables = raw.structure["tables"]
    assert len(tables) == 1
    record = tables[0]
    assert record["page"] == 1 and record["source"] in ("model", "geometry")
    assert record["header_rows"] == 1
    machinery = next(r for r in record["rows"] if r["cells"][0] == "Machinery and tools")
    assert machinery["level"] == 2 and machinery["path"] == ["Resources", "Long-lived resources"]
    assert any(r["emphasis"] == "total" and r["rule_above"] != "none" for r in record["rows"])
    assert set(record["scores"]) <= {"model", "geometry"}


@pytest.mark.skipif(not _layout_available(), reason="pymupdf-layout not installed")
def test_extractor_plain_table_unchanged(tmp_path):
    from src.extractors.pdf_extractor import PDFExtractor

    path = tmp_path / "plain.pdf"
    document = fitz.open()
    page = document.new_page()
    _text(page, 72, 70, "Staff list for the regional office, as at the start of the year.")
    rows = [["Name", "Role", "City"]] + [[f"Person {k}", ["Engineer", "Designer", "Analyst"][k % 3], ["Porto", "Leeds", "Accra"][k % 3]] for k in range(1, 7)]
    y = 110.0
    for row in rows:
        page.draw_line((70, y - 11), (420, y - 11), width=0.5)
        for x, text in zip((74.0, 200.0, 320.0), row, strict=True):
            _text(page, x, y, text)
        y += 18
    page.draw_line((70, y - 11), (420, y - 11), width=0.5)
    for x in (70.0, 196.0, 316.0, 420.0):
        page.draw_line((x, 99), (x, y - 11), width=0.5)
    document.save(path)
    document.close()

    raw = PDFExtractor().extract(str(path))
    assert "| Name | Role | City |" in raw.text
    assert "| Person 1 | Designer | Leeds |" in raw.text
    assert "**" not in raw.text.split("| Name")[1]
    assert tg.EM_SPACE not in raw.text
    record = raw.structure["tables"][0]
    assert record["source"] == "model"
    assert all(r["emphasis"] is None and r["level"] == 0 for r in record["rows"])
