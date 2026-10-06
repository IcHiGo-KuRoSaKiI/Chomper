"""
Check marks in table cells: symbol fonts, vector strokes, icons -- and no
false positives from borders and backgrounds.

Run: ``python -m pytest src/tests/test_cell_marks.py -q``
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF required")
from PIL import Image  # noqa: E402

from src.pdf_structure.cell_marks import recover_cell_marks  # noqa: E402

CELL_W, CELL_H, X0, Y0 = 90.0, 24.0, 72.0, 100.0


def _cell(row: int, col: int) -> tuple[float, float, float, float]:
    x = X0 + col * CELL_W
    y = Y0 + row * CELL_H
    return (x, y, x + CELL_W, y + CELL_H)


def _grid_lines(page, rows: int, cols: int) -> None:
    for r in range(rows + 1):
        page.draw_line((X0, Y0 + r * CELL_H), (X0 + cols * CELL_W, Y0 + r * CELL_H))
    for c in range(cols + 1):
        page.draw_line((X0 + c * CELL_W, Y0), (X0 + c * CELL_W, Y0 + rows * CELL_H))


def _tick(page, cell, color=(0, 0.5, 0)) -> None:
    x0, y0, x1, y1 = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    shape = page.new_shape()
    shape.draw_polyline([(cx - 5, cy), (cx - 1, cy + 5), (cx + 6, cy - 6)])
    shape.finish(color=color, width=1.5, closePath=False)
    shape.commit()


def _cross(page, cell, color=(0.8, 0, 0)) -> None:
    x0, y0, x1, y1 = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    page.draw_line((cx - 5, cy - 5), (cx + 5, cy + 5), color=color, width=1.5)
    page.draw_line((cx - 5, cy + 5), (cx + 5, cy - 5), color=color, width=1.5)


def _icon(color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def page():
    doc = fitz.open()
    yield doc.new_page()
    doc.close()


def _cells(rows: int, cols: int):
    return [[_cell(r, c) for c in range(cols)] for r in range(rows)]


def test_vector_tick_and_cross_fill_empty_cells(page):
    _grid_lines(page, 2, 3)
    _tick(page, _cell(1, 1))
    _cross(page, _cell(1, 2))
    grid = [["Feature", "Phone A", "Phone B"], ["Wireless charging", "", ""]]
    for r, row in enumerate(grid):
        for c, text in enumerate(row):
            if text:
                page.insert_text((_cell(r, c)[0] + 3, _cell(r, c)[1] + 16), text, fontsize=9)
    assert recover_cell_marks(page, _cells(2, 3), grid)[1] == ["Wireless charging", "✓", "✗"]


def test_borders_and_backgrounds_are_not_marks(page):
    """Empty cells whose own borders and fills are drawn inside them stay empty."""
    for c in range(3):
        x0, y0, x1, y1 = _cell(0, c)
        page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0, 0, 0), fill=(0.9, 0.95, 0.9))
        page.draw_line((x0 + 2, y1 - 2), (x1 - 2, y1 - 2), color=(0.2, 0.6, 0.2))  # underline rule
    assert recover_cell_marks(page, _cells(1, 3), [["", "", ""]]) == [["", "", ""]]


def test_cells_with_text_are_never_changed(page):
    _grid_lines(page, 1, 2)
    _tick(page, _cell(0, 1))
    page.insert_text((_cell(0, 1)[0] + 3, _cell(0, 1)[1] + 16), "128 GB", fontsize=9)
    assert recover_cell_marks(page, _cells(1, 2), [["Storage", "128 GB"]]) == [["Storage", "128 GB"]]


def test_zapf_dingbats_codes_become_marks(page):
    page.insert_text((_cell(0, 1)[0] + 3, _cell(0, 1)[1] + 16), "4", fontname="zadb", fontsize=10)
    page.insert_text((_cell(0, 2)[0] + 3, _cell(0, 2)[1] + 16), "8", fontname="zadb", fontsize=10)
    page.insert_text((_cell(0, 0)[0] + 3, _cell(0, 0)[1] + 16), "4K video", fontsize=9)
    grid = [["4K video", "4", "8"]]  # what extraction returns for ZapfDingbats
    assert recover_cell_marks(page, _cells(1, 3), grid) == [["4K video", "✓", "✗"]]


def test_icons_read_by_colour(page):
    for col, color in ((0, "green"), (1, "red"), (2, "blue")):
        x0, y0, _, _ = _cell(0, col)
        page.insert_image(fitz.Rect(x0 + 30, y0 + 4, x0 + 46, y0 + 20), stream=_icon(color))
    assert recover_cell_marks(page, _cells(1, 3), [["", "", ""]]) == [["✓", "✗", "[icon]"]]


def test_spanned_cells_are_left_alone(page):
    _grid_lines(page, 1, 2)
    cells = [[_cell(0, 0), None]]
    assert recover_cell_marks(page, cells, [["Merged", ""]]) == [["Merged", ""]]
