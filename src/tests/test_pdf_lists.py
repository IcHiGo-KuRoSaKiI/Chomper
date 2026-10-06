"""
PDF lists: bullet glyphs, nesting from indentation, wrapped items, legal labels.

PDFs carry no list structure, only glyphs and indentation. These tests build
real PDFs and check both entry points -- ``chomper.parse`` (pymupdf4llm path)
and ``chomper.chunk`` (structural path) -- keep every item on its own line,
nested by depth, with its label intact.

Run: ``python -m pytest src/tests/test_pdf_lists.py -q``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

fitz = pytest.importorskip("fitz", reason="PyMuPDF required")

import chomper  # noqa: E402
from src.pdf_structure.lists import normalize_markdown_lists, parse_marker  # noqa: E402

HTML = """<h1>Quarterly Report</h1>
<p>This report covers the following points:</p>
<ul><li>Revenue increased across all regions
  <ul><li>APAC up 30%</li><li>EMEA up 12%</li></ul></li>
<li>Costs were flat</li></ul>
<ol><li>First step: collect data</li><li>Second step: analyse it</li></ol>
<p>Closing paragraph.</p>"""


@pytest.fixture
def html_list_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    doc.new_page().insert_htmlbox(fitz.Rect(50, 40, 550, 500), HTML)
    path = tmp_path / "lists.pdf"
    doc.save(path)
    return path


@pytest.fixture
def legal_pdf(tmp_path: Path) -> Path:
    """Hand-placed lines: labels at increasing indents, one wrapped item."""
    doc = fitz.open()
    page = doc.new_page()
    rows = [
        (72, "Section 4. Obligations of the parties are as follows."),
        (90, "(a) The supplier shall deliver the goods on time and in full,"),
        (110, "including all accessories listed in Schedule 2."),
        (110, "(1) Delivery is to the buyer's registered address."),
        (130, "(i) Partial deliveries require written consent."),
        (130, "(ii) Consent may be given by email."),
        (90, "(b) The buyer shall pay within 30 days."),
        (72, "Nothing in this section limits liability for fraud."),
    ]
    y = 80
    for x, text in rows:
        page.insert_text((x, y), text, fontsize=10)
        y += 16
    path = tmp_path / "legal.pdf"
    doc.save(path)
    return path


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def test_parse_keeps_nested_bullets_and_numbers(html_list_pdf: Path):
    lines = _lines(chomper.parse(str(html_list_pdf)).text)
    assert "- Revenue increased across all regions" in lines
    assert "  - APAC up 30%" in lines
    assert "  - EMEA up 12%" in lines
    assert "- Costs were flat" in lines
    assert "1. First step: collect data" in lines
    assert "2. Second step: analyse it" in lines


def test_chunks_keep_list_items_on_their_own_lines(html_list_pdf: Path):
    text = "\n".join(chunk.text for chunk in chomper.chunk(str(html_list_pdf)))
    lines = _lines(text)
    assert "- Revenue increased across all regions" in lines
    assert "  - APAC up 30%" in lines
    assert "  - EMEA up 12%" in lines
    assert "- Costs were flat" in lines
    assert "1. First step: collect data" in lines
    assert "•" not in text and "○" not in text, "raw bullet glyphs leaked into chunks"


def test_chunks_expand_ligatures(html_list_pdf: Path):
    text = "\n".join(chunk.text for chunk in chomper.chunk(str(html_list_pdf)))
    assert "flat" in text and "ﬂ" not in text


def test_legal_labels_nest_and_wrapped_items_join(legal_pdf: Path):
    lines = _lines("\n".join(chunk.text for chunk in chomper.chunk(str(legal_pdf))))
    assert (
        "- (a) The supplier shall deliver the goods on time and in full, "
        "including all accessories listed in Schedule 2."
    ) in lines
    assert "  - (1) Delivery is to the buyer's registered address." in lines
    assert "    - (i) Partial deliveries require written consent." in lines
    assert "    - (ii) Consent may be given by email." in lines
    assert "- (b) The buyer shall pay within 30 days." in lines
    assert any(line.startswith("Nothing in this section") for line in lines)


@pytest.mark.parametrize(
    "text, label, ordered",
    [
        ("• Item", "•", False),
        (" Wingdings bullet", "", False),
        ("▪ Square", "▪", False),
        ("- dash item", "-", False),
        ("(a) sub-clause", "(a)", True),
        ("iv) roman", "iv)", True),
        ("12) twelve", "12)", True),
    ],
)
def test_markers_recognised(text: str, label: str, ordered: bool):
    marker = parse_marker(text)
    assert marker is not None and marker.label == label and marker.ordered is ordered


@pytest.mark.parametrize("text", ["1.2 Scope", "A. Smith wrote this", "-5% drop", "I. Introduction"])
def test_non_list_lines_rejected(text: str):
    assert parse_marker(text) is None


def test_markdown_list_levels_normalised():
    md = "Intro:\n\n  - item\n\n    - child\n\n   - child two\n\n  - item two\n\n1. one\n2. two\n"
    assert normalize_markdown_lists(md) == (
        "Intro:\n\n- item\n  - child\n  - child two\n- item two\n\n1. one\n2. two\n"
    )


def test_code_fences_untouched():
    md = "```\n    - not a list\n\n  * nor this\n```"
    assert normalize_markdown_lists(md) == md


def test_list_continuing_in_next_column_is_not_nested():
    md = "- Jan\n- Feb\n  - Jul\n  - Aug\n"
    hints = {"jan": (50.0, 600.0), "feb": (50.0, 612.0), "jul": (320.0, 80.0), "aug": (320.0, 92.0)}
    assert normalize_markdown_lists(md, hints) == "- Jan\n- Feb\n- Jul\n- Aug\n"


def test_nesting_from_positions_beats_space_counts():
    md = "  - parent\n   - child\n   - child two\n  - next\n"
    hints = {
        "parent": (70.4, 100.0),
        "child": (93.2, 112.0),
        "child two": (93.2, 124.0),
        "next": (70.4, 136.0),
    }
    assert normalize_markdown_lists(md, hints) == "- parent\n  - child\n  - child two\n- next\n"


def test_wrapped_item_text_is_joined():
    md = "- October 12—Indigenous Peoples’ Day (Columbus\nDay)\n- November 11—Veterans Day\n\nNext paragraph."
    assert normalize_markdown_lists(md) == (
        "- October 12—Indigenous Peoples’ Day (Columbus Day)\n- November 11—Veterans Day\n\nNext paragraph."
    )
