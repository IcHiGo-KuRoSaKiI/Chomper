"""Nothing but the caller's own output may reach stdout.

Under the MCP stdio transport stdout is the JSON-RPC channel: one stray line
("=== Document parser messages ===", "Using Tesseract for OCR processing.",
"OCR on page.number=1/2.") corrupts the protocol. pymupdf4llm sends those through
``pymupdf.message``, whose stream is bound to the real ``sys.stdout`` when PyMuPDF
is imported, so ``contextlib.redirect_stdout`` around the call did not catch them.

These tests run a real child process and read its file descriptor 1, so writes
from C code or from streams captured at import time are caught too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _ocr_engine() -> bool:
    try:
        from src.extractors.pdf_layout import LAYOUT_AVAILABLE
    except Exception:  # pragma: no cover
        return False
    if not LAYOUT_AVAILABLE:  # pragma: no cover
        return False
    import pymupdf

    try:
        return bool(pymupdf.get_tessdata()) and shutil.which("tesseract") is not None
    except Exception:  # pragma: no cover - no tessdata
        return False


needs_ocr = pytest.mark.skipif(not _ocr_engine(), reason="needs pymupdf-layout and Tesseract")


def make_scanned_pdf(path: Path) -> None:
    """Page 1 has a text layer; page 2 is only an image of text."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(
        pymupdf.Rect(72, 72, 520, 700),
        "Quarterly report. Revenue grew in every region during the quarter, and the "
        "board approved a dividend. " * 6,
        fontsize=12,
    )
    source = pymupdf.open()
    scanned = source.new_page()
    scanned.insert_textbox(
        pymupdf.Rect(72, 72, 520, 700),
        "Scanned appendix. The auditors reviewed the inventory counts and found no "
        "material differences between the ledger and the warehouse records. " * 4,
        fontsize=14,
    )
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=scanned.get_pixmap(dpi=200))
    doc.save(path)


CHILD = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, sys.argv[2])
    import chomper

    path = sys.argv[1]
    result = chomper.parse(path)
    layout = chomper.chunk(path, strategy="layout")
    structural = chomper.chunk(path, strategy="structural")
    default = chomper.chunk(path)
    # A second, uncached extraction must not replay earlier messages either.
    chomper.clear_cache()
    chomper.parse(path, ocr="force")
    sys.stderr.write(
        f"RESULT ocr_pages={result.metadata.get('ocr_pages')} "
        f"chunks={len(layout)},{len(structural)},{len(default)}\\n"
    )
    """
)


@needs_ocr
def test_parse_and_chunk_with_ocr_write_nothing_to_stdout(tmp_path: Path) -> None:
    pdf = tmp_path / "scanned.pdf"
    make_scanned_pdf(pdf)
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    done = subprocess.run(
        [sys.executable, str(script), str(pdf), str(ROOT)],
        cwd=tmp_path,
        capture_output=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-2000:]
    assert b"RESULT ocr_pages=[2]" in done.stderr  # OCR really ran
    assert done.stdout == b"", done.stdout.decode(errors="replace")


def test_pymupdf_messages_go_to_stderr() -> None:
    """Importing the layout extractor routes PyMuPDF's user messages to stderr."""
    code = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, sys.argv[1])
        import src.extractors.pdf_layout  # noqa: F401
        import pymupdf
        pymupdf.message("hello from pymupdf")
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(ROOT)], capture_output=True, timeout=120
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert done.stdout == b""
    assert b"hello from pymupdf" in done.stderr


def test_explicit_pymupdf_message_setting_is_respected() -> None:
    """PYMUPDF_MESSAGE chosen by the user is left alone."""
    code = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, sys.argv[1])
        import src.extractors.pdf_layout  # noqa: F401
        import pymupdf
        pymupdf.message("to fd 1 on purpose")
        """
    )
    import os

    env = {**os.environ, "PYMUPDF_MESSAGE": "fd:1"}
    done = subprocess.run(
        [sys.executable, "-c", code, str(ROOT)], capture_output=True, timeout=120, env=env
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert b"to fd 1 on purpose" in done.stdout
