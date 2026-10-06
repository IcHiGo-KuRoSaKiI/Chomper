"""``ocr="auto"`` OCRs only pages without a text layer; ``force`` every page; ``off`` none.

pymupdf4llm's ``SELECT_KEEP_OLD`` heuristics, which ``auto`` used to map to, OCR'd
most pages of born-digital documents with icons and boxed notes: twice the time,
and garbled words added to the text.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from src.tests.test_stdout_clean import needs_ocr

pymupdf = pytest.importorskip("pymupdf")


def _words_image(text: str, width: float = 440, height: float = 160) -> Any:
    """A raster image of ``text`` (like a scanned page, or an icon with words)."""
    source = pymupdf.open()
    page = source.new_page(width=width, height=height)
    page.insert_textbox(pymupdf.Rect(10, 10, width - 10, height - 10), text, fontsize=16)
    return page.get_pixmap(dpi=200)


def make_mixed_pdf(path: Path) -> None:
    """Page 1: text plus a picture with words in it. Page 2: scanned. Page 3: text."""
    doc = pymupdf.open()
    prose = (
        "The ledger is reconciled to the bank statement at each month end, and any "
        "difference is investigated before the accounts are closed. "
    ) * 5
    first = doc.new_page()
    first.insert_textbox(pymupdf.Rect(72, 72, 520, 380), prose, fontsize=11)
    first.insert_image(
        pymupdf.Rect(72, 420, 512, 580),
        pixmap=_words_image("NOTES: remember the IFRS treatment of grants"),
    )
    scanned = doc.new_page()
    scanned.insert_image(
        scanned.rect,
        pixmap=_words_image(
            "Scanned appendix. The auditors reviewed the inventory counts and found "
            "no material differences between the ledger and the warehouse records.",
            width=595,
            height=842,
        ),
    )
    last = doc.new_page()
    last.insert_textbox(pymupdf.Rect(72, 72, 520, 700), prose, fontsize=11)
    doc.save(path)


@pytest.fixture
def ocr_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """0-based numbers of the pages the OCR engine actually ran on."""
    from pymupdf4llm.helpers import document_layout

    from src.extractors import pdf_layout

    real_select = document_layout.select_ocr_function
    calls: list[int] = []

    def recording(engine: Callable[..., Any]) -> Callable[..., Any]:
        def run(page: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append(page.number)
            return engine(page, *args, **kwargs)

        return run

    def select() -> Callable[..., Any] | None:
        engine = real_select()
        return recording(engine) if callable(engine) else engine

    monkeypatch.setattr(document_layout, "select_ocr_function", select)
    cached = getattr(pdf_layout, "_ocr_engine", None)
    if cached is not None and hasattr(cached, "cache_clear"):
        cached.cache_clear()
    yield calls
    if cached is not None and hasattr(cached, "cache_clear"):
        cached.cache_clear()


def _extract(path: Path, ocr: str) -> Any:
    from src.extractors.pdf_extractor import PDFExtractor

    return PDFExtractor(ocr=ocr).extract(str(path))


@needs_ocr
def test_auto_ocrs_only_the_page_without_a_text_layer(tmp_path: Path, ocr_calls: list[int]) -> None:
    pdf = tmp_path / "mixed.pdf"
    make_mixed_pdf(pdf)
    doc = _extract(pdf, "auto")
    assert ocr_calls == [1]
    assert doc.metadata["ocr_pages"] == [2]
    assert "auditors reviewed the inventory" in doc.text
    assert "pages_without_text_layer" not in doc.metadata


@needs_ocr
def test_auto_on_born_text_pages_runs_no_ocr_and_matches_off(
    tmp_path: Path, ocr_calls: list[int]
) -> None:
    pdf = tmp_path / "text_and_pictures.pdf"
    doc = pymupdf.open()
    for n in range(3):
        page = doc.new_page()
        page.insert_textbox(
            pymupdf.Rect(72, 72, 520, 380),
            f"Chapter {n + 1}. Accruals match income and expenses to the period in "
            "which they arise, not the period in which cash moves. " * 4,
            fontsize=11,
        )
        page.insert_image(
            pymupdf.Rect(72, 420, 512, 580), pixmap=_words_image("NOTES: IFRS 15 revenue")
        )
    doc.save(pdf)
    auto = _extract(pdf, "auto")
    assert ocr_calls == []
    assert "ocr_pages" not in auto.metadata
    assert auto.text == _extract(pdf, "off").text


@needs_ocr
def test_force_ocrs_every_page_and_off_none(tmp_path: Path, ocr_calls: list[int]) -> None:
    pdf = tmp_path / "mixed.pdf"
    make_mixed_pdf(pdf)
    off = _extract(pdf, "off")
    assert ocr_calls == []
    assert off.metadata["pages_without_text_layer"] == [2]
    _extract(pdf, "force")
    # pymupdf4llm's FORCE_KEEP_OLD skips pages that hold only text (nothing to read
    # off an image); every page with an image is OCR'd.
    assert set(ocr_calls) >= {0, 1}
