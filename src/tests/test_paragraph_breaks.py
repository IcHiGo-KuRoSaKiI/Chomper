"""Paragraphs split by a column or page break are joined again.

The layout model gives each column's part of a paragraph its own region and the
extractor wrote regions, and pages, as separate blocks: a sentence running from
the foot of one column (or page) to the top of the next became two paragraphs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")
pdf_layout = pytest.importorskip("src.extractors.pdf_layout")
if not pdf_layout.LAYOUT_AVAILABLE:  # pragma: no cover
    pytest.skip("pymupdf-layout not installed", allow_module_level=True)

from src.extractors.pdf_layout import _joiner, join_broken_paragraphs, join_pages  # noqa: E402

FILLER = (
    "Employers report wages and withheld taxes every quarter on the return for the "
    "period. The return lists each payment, and the totals must agree with the deposits "
    "made during the quarter. Differences are explained in a statement attached to the "
    "return. Records are kept for four years after the tax becomes due or is paid."
)


def _column(page: object, x: float, paragraphs: list[str]) -> None:
    page.insert_textbox(  # type: ignore[attr-defined]
        pymupdf.Rect(x, 72, x + 230, 720), "\n\n".join(paragraphs), fontsize=10
    )


def make_broken_pdf(path: Path) -> None:
    """Two pages, two columns; sentences break at the column and the page break."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    _column(page, 60, [FILLER, FILLER, f"{FILLER} An agricultural employer must file Form 943 with"])
    _column(page, 322, [
        "the agency by the last day of the month after the year ends. " + FILLER,
        FILLER,
        f"{FILLER} Deposits are made electronically unless the employer",
    ])
    page = doc.new_page(width=612, height=792)
    _column(page, 60, ["qualifies for an exception described in this chapter. " + FILLER, FILLER])
    doc.save(path)


def test_column_and_page_breaks_mid_sentence_are_joined(tmp_path: Path) -> None:
    from src.extractors.pdf_extractor import PDFExtractor

    pdf = tmp_path / "broken.pdf"
    make_broken_pdf(pdf)
    text = PDFExtractor(ocr="off").extract(str(pdf)).text
    flat = re.sub(r"[ \t]+", " ", text)
    assert "must file Form 943 with the agency by the last day" in flat
    assert "unless the employer qualifies for an exception" in flat


def test_page_texts_stay_verbatim_substrings(tmp_path: Path) -> None:
    from src.extractors.pdf_extractor import PDFExtractor

    pdf = tmp_path / "broken.pdf"
    make_broken_pdf(pdf)
    doc = PDFExtractor(ocr="off").extract(str(pdf))
    for page in doc.structure["pages"]:
        assert page["markdown_text"].strip("\n") in doc.text


# ------------------------------------------------------------------ the rule


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("A long sentence that the column break cuts off in the", "middle of its words.", " "),
        ("Employers in American Samoa, Guam, the", "CNMI, the USVI, and Puerto Rico should contact us.", " "),
        ("information for oversight as permitted by paragraph", "(d) of this section.", " "),
        ("the covered entity must maintain audit logs, ac-", "cess reports, and tracking reports.", ""),
        # Complete sentences, structure and enumerations stay apart.
        ("This paragraph ends with a full stop.", "next one starts lowercase oddly.", None),
        ("A lead-in that introduces a list of duties:", "the first duty is to file.", None),
        ("(2) Prosecute a criminal violation of the law; or", "(3) Conduct an inquiry into it.", None),
        ("The contract must provide that the business associate will—", "(A) Comply with the rules.", None),
        ("## A heading without punctuation", "continues nothing at all here.", None),
        ("| a | b |", "continues nothing at all here.", None),
        ("![chart](image:p1-1)", "continues nothing at all here.", None),
        ("Figure 3. Share of income from", "wages and salaries by group.", None),
        ("labour supply in lower-wage service industries during the", "_(continued)_", None),
        ("Employers whose principal place of business is in Samoa,", "Or, you can write to:", None),
        ("The rate of social security tax on taxable wages is 6.2% each for",
         "Publication 15 (2026) Catalog Number 10000W Department of the Treasury", None),
        ("Results for the year compared with", "Table 4 below shows the detail. More follows.", None),
    ],
)
def test_joiner(before: str, after: str, expected: str | None) -> None:
    assert _joiner(before, after) == expected


def test_join_broken_paragraphs_chains_and_respects_figures() -> None:
    text = (
        "First part of a sentence that runs\n\n"
        "into the next column and then\n\n"
        "onto a third block. Done.\n\n"
        "![figure](image:p1-1)\n\n"
        "after the figure a new block."
    )
    assert join_broken_paragraphs(text) == (
        "First part of a sentence that runs into the next column and then onto a third "
        "block. Done.\n\n![figure](image:p1-1)\n\nafter the figure a new block."
    )


def test_join_pages() -> None:
    pages = ["# Title\n\nThe sentence runs past the end of the", "page and finishes here.\n", "", "New page."]
    assert join_pages(pages) == (
        "# Title\n\nThe sentence runs past the end of the page and finishes here.\n\nNew page."
    )
    # A word hyphenated across pages keeps its hyphen: page texts stay substrings.
    assert join_pages(["covered enti-", "ties must comply."]) == "covered enti-ties must comply."
