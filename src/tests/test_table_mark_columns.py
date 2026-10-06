"""
Regression cover for mark recovery and mark-matrix tables, from generated PDFs.

* marks a model cell box does not fully contain (last row, short last column);
* legend lookup for marks colour cannot decide ("Partially supported");
* cell padding rectangles are neither marks nor legend symbols (an ICDAR-2013
  table got "Net Financial Condition" copied into five columns before);
* unruled tables whose mark-only columns the layout model dropped;
* ruled sparse feature matrices whose empty columns the layout model merged.

Run: ``python -m pytest src/tests/test_table_mark_columns.py -q``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF required")

from src.pdf_structure.cell_marks import (  # noqa: E402
    recover_cell_marks,
    recover_mark_columns,
)
from src.pdf_structure.tables import ruled_grids_for_sparse_matrix  # noqa: E402

GREEN, GREY = (0.0, 0.82, 0.37), (0.31, 0.34, 0.38)
DOT_FONT = "china-s"  # built-in Droid Sans Fallback: has ● (base-14 fonts do not)


def _filled_tick(page, cx: float, cy: float, colour) -> None:
    """A tick drawn as a filled outline (six straight edges), as design tools export it."""
    shape = page.new_shape()
    shape.draw_polyline([
        (cx - 6, cy), (cx - 4, cy - 2), (cx - 1.5, cy + 0.5),
        (cx + 4, cy - 5), (cx + 6, cy - 3), (cx - 1.5, cy + 4.5),
    ])
    shape.finish(color=None, fill=colour, closePath=True)
    shape.commit()


def _stroke_tick(page, cx: float, cy: float) -> None:
    shape = page.new_shape()
    shape.draw_polyline([(cx - 5, cy), (cx - 1.5, cy + 4.5), (cx + 6, cy - 5)])
    shape.finish(color=(0, 0.5, 0), width=1.5, closePath=False)
    shape.commit()


@pytest.fixture
def page():
    doc = fitz.open()
    yield doc.new_page(width=842, height=595)
    doc.close()


# ---------------------------------------------------------------------------
# recover_cell_marks
# ---------------------------------------------------------------------------


def test_last_row_mark_below_text_hugging_box(page):
    """The model's last-row box ends at the label's baseline; the tick reaches below it."""
    page.insert_text((60, 112), "eSIM", fontsize=9)
    _stroke_tick(page, 175, 110)
    cells = [[(55, 102, 150, 113.5), (150, 102, 200, 113.5)]]
    assert recover_cell_marks(page, cells, [["eSIM", ""]]) == [["eSIM", "✓"]]


def test_short_last_column_is_widened_for_marks(page):
    """A last column whose header is a short left-aligned word ("E3") gets a box
    narrower than the column, and the centred marks fall outside it."""
    rows = 5
    cells, grid = [], []
    for r in range(rows):
        y0 = 100 + 22 * r
        row = [(55, y0, 150, y0 + 22), (150, y0, 200, y0 + 22), (200, y0, 250, y0 + 22),
               (250, y0, 300, y0 + 22), (300, y0, 318, y0 + 22)]
        cells.append(row)
        grid.append([f"Feature {r}", "x", "x", "x", ""])
        _stroke_tick(page, 326, y0 + 11)  # centred in the real 52pt column (300-352)
    out = recover_cell_marks(page, cells, grid)
    assert [row[-1] for row in out] == ["✓"] * rows


def test_grey_tick_takes_its_meaning_from_the_legend(page):
    _filled_tick(page, 40, 40, GREEN)
    page.insert_text((50, 43), "Fully supported", fontsize=7)
    _filled_tick(page, 140, 40, GREY)
    page.insert_text((150, 43), "Partially supported", fontsize=7)
    _filled_tick(page, 230, 111, GREEN)
    _filled_tick(page, 280, 111, GREY)
    cells = [[(55, 100, 200, 122), (200, 100, 255, 122), (255, 100, 305, 122)]]
    out = recover_cell_marks(page, cells, [["Malware detection", "", ""]])
    assert out == [["Malware detection", "✓", "Partially supported"]]


def test_grey_tick_without_a_legend_stays_empty(page):
    _filled_tick(page, 280, 111, GREY)
    cells = [[(55, 100, 255, 122), (255, 100, 305, 122)]]
    assert recover_cell_marks(page, cells, [["Malware detection", ""]]) == [["Malware detection", ""]]


def test_padding_rectangles_are_not_marks_or_legend_symbols(page):
    """Header cells padded with small filled rectangles next to their text."""
    navy = (0.13, 0.05, 0.45)
    for x in (110, 204, 278):
        page.draw_rect(fitz.Rect(x, 632, x + 5.4, 642.2), color=None, fill=navy)
    page.insert_text((116, 640), "Net Financial Condition", fontsize=8)
    page.draw_rect(fitz.Rect(270, 660, 278, 668), color=None, fill=(0.1, 0.7, 0.2))  # green swatch
    cells = [[(100, 650, 255, 672), (255, 650, 300, 672)]]
    assert recover_cell_marks(page, cells, [["Assets", ""]]) == [["Assets", ""]]


# ---------------------------------------------------------------------------
# recover_mark_columns (unruled: the model dropped the mark columns)
# ---------------------------------------------------------------------------

PLANS = ["Community", "Foundation", "Advanced", "Premium"]
PLAN_X = [215.0, 270.0, 325.0, 380.0]


def _unruled_matrix(page, rows):
    """Label | 4 plan columns of filled ticks | description, header above, legend at top."""
    _filled_tick(page, 40, 40, GREEN)
    page.insert_text((50, 43), "Fully supported", fontsize=7)
    _filled_tick(page, 140, 40, GREY)
    page.insert_text((150, 43), "Partially supported", fontsize=7)
    for name, x in zip(PLANS, PLAN_X, strict=True):
        width = fitz.get_text_length(name, fontsize=7)
        page.insert_text((x - width / 2, 95), name, fontsize=7)
    page.insert_text((420, 95), "Description", fontsize=7)
    cells, grid = [], []
    for r, (label, marks) in enumerate(rows):
        y0 = 110 + 30 * r
        page.draw_line((50, y0), (790, y0), color=(0.8, 0.8, 0.8), width=0.5)
        page.insert_text((55, y0 + 14), label, fontsize=8)
        description = f"What {label.lower()} does, in a sentence long enough to wrap."
        page.insert_text((420, y0 + 14), description, fontsize=8)
        for mark, x in zip(marks, PLAN_X, strict=True):
            if mark:
                _filled_tick(page, x, y0 + 12, GREEN if mark == "✓" else GREY)
        # What the layout model returns: two columns, the description box
        # stretching back over the mark columns.
        cells.append([(52, y0 + 2, 190, y0 + 24), (190, y0 + 2, 788, y0 + 24)])
        grid.append([label, description])
    return cells, grid


def test_dropped_mark_columns_are_rebuilt_under_their_header(page):
    rows = [
        ("Malware detection", ["", "P", "✓", "✓"]),
        ("Recon", ["", "", "✓", "✓"]),
        ("SAML support", ["", "✓", "✓", "✓"]),
        ("Updater", ["", "✓", "✓", "✓"]),
    ]
    cells, grid = _unruled_matrix(page, rows)
    rebuilt = recover_mark_columns(page, cells, grid)
    assert rebuilt is not None
    _, out = rebuilt
    # Community has no tick in this table but keeps its column, under its header.
    assert out[0] == ["", *PLANS, ""]
    assert out[1][:5] == ["Malware detection", "", "Partially supported", "✓", "✓"]
    assert out[2][:5] == ["Recon", "", "", "✓", "✓"]
    assert out[4][:5] == ["Updater", "", "✓", "✓", "✓"]
    assert out[1][5].startswith("What malware detection does")


def test_text_tables_are_not_rebuilt(page):
    cells, grid = [], []
    for r in range(4):
        y0 = 110 + 22 * r
        page.insert_text((55, y0 + 14), f"Item {r}", fontsize=8)
        page.insert_text((215, y0 + 14), f"{r * 12.5:.1f}", fontsize=8)
        cells.append([(52, y0, 190, y0 + 22), (190, y0, 300, y0 + 22)])
        grid.append([f"Item {r}", f"{r * 12.5:.1f}"])
    assert recover_mark_columns(page, cells, grid) is None


def test_correctly_placed_marks_are_left_to_the_model(page):
    """Each mark already in its own cell, no header line over the marks: no rebuild."""
    cells, grid = [], []
    for r in range(4):
        y0 = 110 + 22 * r
        page.insert_text((55, y0 + 14), f"Feature {r}", fontsize=8)
        _stroke_tick(page, 225, y0 + 11)
        _stroke_tick(page, 275, y0 + 11)
        cells.append([(52, y0, 200, y0 + 22), (200, y0, 250, y0 + 22), (250, y0, 300, y0 + 22)])
        grid.append([f"Feature {r}", "", ""])
    assert recover_mark_columns(page, cells, grid) is None


# ---------------------------------------------------------------------------
# ruled_grids_for_sparse_matrix (ruled: the model merged empty columns)
# ---------------------------------------------------------------------------

N_PLANS, LABEL_W, COL_W, ROW_H, X0 = 10, 160.0, 40.0, 16.0, 40.0


def _ruled_section(page, top: float, rows: list[tuple[str, list[str]]]) -> None:
    for r, (label, marks) in enumerate(rows):
        y = top + ROW_H * r
        page.insert_text((X0 + 4, y + 11), label, fontsize=7)
        for c, mark in enumerate(marks):
            if mark:
                x = X0 + LABEL_W + COL_W * c + COL_W / 2 - 3
                page.insert_text((x, y + 11), mark, fontsize=7, fontname=DOT_FONT)
    bottom = top + ROW_H * len(rows)
    for r in range(len(rows) + 1):
        page.draw_line((X0, top + ROW_H * r), (X0 + LABEL_W + COL_W * N_PLANS, top + ROW_H * r),
                       color=(0.8, 0.8, 0.8), width=0.5)
    for c in range(N_PLANS + 2):
        x = X0 if c == 0 else X0 + LABEL_W + COL_W * (c - 1)
        page.draw_line((x, top), (x, bottom), color=(0.8, 0.8, 0.8), width=0.5)


SECTION_A = [
    ("Copilot Chat", ["●", "●", "●", "", "", "●", "●", "", "", ""]),
    ("Copilot Analytics", ["●", "●", "", "", "", "●", "", "", "", "●"]),
    ("Security Copilot", ["", "●", "●", "", "", "", "", "", "", "●"]),
]
SECTION_B = [
    ("Agent Identity", ["●", "●", "●", "●", "", "●", "●", "", "●", "●"]),
    ("Agent map", ["", "", "●", "", "", "", "", "", "", "●"]),
    ("Graph API", ["", "", "●", "", "", "", "", "", "", "●"]),
]


def test_ruled_sparse_matrix_keeps_every_column(page):
    _ruled_section(page, 100, SECTION_A)
    # What the layout model returns for it: the three empty columns gone and
    # two dots sharing a cell.
    merged = [
        ["Copilot Chat", "● ●", "●", "●", "●", ""],
        ["Copilot Analytics", "● ●", "", "●", "", "●"],
        ["Security Copilot", "●", "●", "", "", "●"],
    ]
    pieces = ruled_grids_for_sparse_matrix(page, (X0 + 2, 100, X0 + LABEL_W + COL_W * N_PLANS - 5, 148), merged)
    assert pieces is not None and len(pieces) == 1
    assert pieces[0].grid == [[label, *marks] for label, marks in SECTION_A]


def test_ruled_sections_and_the_text_between_them(page):
    _ruled_section(page, 100, SECTION_A)
    page.insert_text((X0, 165), "1 Footnote for the first section.", fontsize=6)
    page.insert_text((X0, 182), "Agent Observability", fontsize=9)
    _ruled_section(page, 190, SECTION_B)
    layout = [
        ["Copilot Chat", "● ●", "●", "●", "●"],
        ["Copilot Analytics", "● ●", "", "●", "●"],
        ["Security Copilot", "●", "●", "", "●"],
        ["1 Footnote for the first section. Agent Observability", "", "", "", ""],
        ["Agent Identity", "● ●", "● ●", "● ●", "● ●"],
        ["Agent map", "", "●", "", "●"],
        ["Graph API", "", "●", "", "●"],
    ]
    bbox = (X0, 100, X0 + LABEL_W + COL_W * N_PLANS, 238)
    pieces = ruled_grids_for_sparse_matrix(page, bbox, layout)
    assert pieces is not None
    assert [p.grid if p.grid else p.text for p in pieces] == [
        [[label, *marks] for label, marks in SECTION_A],
        "1 Footnote for the first section.",
        "Agent Observability",
        [[label, *marks] for label, marks in SECTION_B],
    ]


def test_ruled_grid_is_not_used_when_a_mark_would_be_lost(page):
    _ruled_section(page, 100, SECTION_A)
    layout = [
        ["Copilot Chat", "● ●", "●", "●", "● ●"],  # one more ● than the page holds
        ["Copilot Analytics", "● ●", "", "●", "●"],
        ["Security Copilot", "●", "●", "", "●"],
    ]
    bbox = (X0, 100, X0 + LABEL_W + COL_W * N_PLANS, 148)
    assert ruled_grids_for_sparse_matrix(page, bbox, layout) is None


def test_ruled_text_tables_are_left_to_the_model(page):
    rows = [("Assets", ["12,584", "12,804"]), ("Liabilities", ["581", "596"]), ("Net", ["12,003", "12,208"])]
    for r, (label, values) in enumerate(rows):
        y = 100 + ROW_H * r
        page.insert_text((X0 + 4, y + 11), label, fontsize=7)
        for c, v in enumerate(values):
            page.insert_text((X0 + LABEL_W + COL_W * c + 4, y + 11), v, fontsize=7)
    for r in range(4):
        page.draw_line((X0, 100 + ROW_H * r), (X0 + LABEL_W + COL_W * 4, 100 + ROW_H * r))
    for c in range(6):
        x = X0 if c == 0 else X0 + LABEL_W + COL_W * (c - 1)
        page.draw_line((x, 100), (x, 148))
    grid = [[label, *values] for label, values in rows]
    assert ruled_grids_for_sparse_matrix(page, (X0, 100, X0 + LABEL_W + COL_W * 2, 148), grid) is None


# ---------------------------------------------------------------------------
# End to end through the layout model
# ---------------------------------------------------------------------------


def _matrix_rows(markdown: str) -> dict[str, list[str]]:
    rows = {}
    for line in markdown.splitlines():
        if line.startswith("| ") and "---" not in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.setdefault(cells[0], cells[1:])
    return rows


def _licence_grid(path: Path, ruled_columns: bool) -> dict[str, list[str]]:
    """A Microsoft 365-style plan grid: 21 narrow plan columns, the plan names in
    a block above the first section only, right-aligned feature names, mostly
    empty cells, sections separated by titles and footnotes."""
    n_plans, label_w, col_w, row_h, x0 = 21, 190.0, 36.0, 14.0, 30.0
    density = [0.95, 0.85, 0.9, 0.1, 0.6, 0.05, 0.9, 0.85, 0.1, 0.6, 0.05, 0.85,
               0.6, 0.05, 0.9, 0.1, 0.85, 0.6, 0.1, 0.05, 0.9]
    features = ["Exchange Online", "Teams meetings", "SharePoint", "OneDrive storage",
                "Defender for Office", "Purview DLP", "Intune", "Entra ID P1", "Entra ID P2",
                "Audit (Premium)", "eDiscovery", "Bookings"]
    doc = fitz.open()
    page = doc.new_page(width=1008, height=612)
    for i in range(n_plans):
        page.insert_text((x0 + label_w + col_w * i + col_w / 2 - 5, 50), f"P{i + 1}", fontsize=7)
    truth: dict[str, list[str]] = {}
    y, k = 66.0, 0
    for section in range(3):
        page.insert_text((x0, y + 10), f"Section {section + 1}", fontsize=9, color=(0, 0.4, 0.8))
        y += 16
        top = y
        for _ in range(4):
            name = features[k]
            # deterministic "random" pattern: plan i is ticked when its density
            # beats a per-row hash
            marks = ["●" if ((k * 7 + i * 13) % 20) / 20 < density[i] else "" for i in range(n_plans)]
            truth[name] = marks
            k += 1
            width = fitz.get_text_length(name, fontsize=7)
            page.insert_text((x0 + label_w - 4 - width, y + 10), name, fontsize=7)
            for i, mark in enumerate(marks):
                if mark:
                    page.insert_text((x0 + label_w + col_w * i + col_w / 2 - 3, y + 10), mark,
                                     fontsize=6, fontname=DOT_FONT)
            y += row_h
        right = x0 + label_w + col_w * n_plans
        for r in range(5):
            page.draw_line((x0, top + r * row_h), (right, top + r * row_h), color=(0.8, 0.8, 0.8), width=0.5)
        if ruled_columns:
            for c in range(n_plans + 2):
                lx = x0 if c == 0 else x0 + label_w + col_w * (c - 1)
                page.draw_line((lx, top), (lx, y), color=(0.8, 0.8, 0.8), width=0.5)
        page.insert_text((x0, y + 8), f"{section + 1} Availability varies by region.", fontsize=5.5)
        y += 22
    doc.save(path)
    doc.close()
    return truth


@pytest.mark.parametrize("ruled_columns", [True, False], ids=["ruled", "unruled"])
def test_extractor_keeps_every_plan_column(tmp_path, ruled_columns):
    """Before the fix the layout model merged the empty plan columns: on this grid
    no row came out right, and only 48% (ruled) / 34% (unruled) of the dots sat
    under their plan."""
    from src.extractors.pdf_extractor import PDFExtractor

    path = tmp_path / "plans.pdf"
    truth = _licence_grid(path, ruled_columns)
    raw = PDFExtractor(ocr="off").extract(str(path))
    rows = _matrix_rows(raw.text)
    for label, marks in truth.items():
        assert rows.get(label) == marks, label
