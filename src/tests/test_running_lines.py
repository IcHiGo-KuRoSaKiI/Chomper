"""Running heads, running feet and folios the layout model did not label as such.

The layout model labels a running head ``page-header`` on some pages and
``section-header`` or ``text`` on others, so dropping only repeated
``page-header`` boxes left 45 CFR's alternating heads, section locators and
folios in the text (and Berkshire's "Notes to Consolidated Financial
Statements"). ``cfr45_164_layout_pages.json`` is the model's real output for six
pages of 45 CFR part 164, replayed through :func:`extract_with_layout`.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Any

import pytest

pymupdf = pytest.importorskip("pymupdf")
pdf_layout = pytest.importorskip("src.extractors.pdf_layout")
if not pdf_layout.LAYOUT_AVAILABLE:  # pragma: no cover
    pytest.skip("pymupdf-layout not installed", allow_module_level=True)

FIXTURE = Path(__file__).parent / "fixtures" / "cfr45_164_layout_pages.json"


class _Parsed:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.pages: list[Any] = []

    def to_markdown(self, **_: Any) -> list[dict[str, Any]]:
        return [
            {"text": p["text"], "page_boxes": [dict(b, pos=tuple(b["pos"])) for b in p["boxes"]]}
            for p in self._pages
        ]


def extract_recorded(monkeypatch: pytest.MonkeyPatch, pages: list[dict[str, Any]]) -> list[str]:
    """Run extract_with_layout on recorded model output; page texts out."""
    doc = pymupdf.open()
    for page in pages:
        doc.new_page(width=page["width"], height=page["height"])
    monkeypatch.setattr(pdf_layout._layout, "parse_document", lambda *a, **k: _Parsed(pages))
    result = pdf_layout.extract_with_layout(
        doc,
        "recorded.pdf",
        rasters=[[] for _ in pages],
        page_lines=lambda page: [],
        render_loader=lambda *a: b"",
        ocr="off",
        table_format="html",  # no table re-rendering from the (absent) cell grids
    )
    return [page.text for page in result.pages]


def plain_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = " ".join(re.sub(r"[*_`#>|]", "", line).split())
        if line:
            out.append(line)
    return out


RUNNING = [
    re.compile(r"Dept\. of Health and Human Services"),
    re.compile(r"45 CFR Subtitle A \(10–1–23 Edition\)"),
    re.compile(r"§ 164\.\d+"),
    re.compile(r"6\d\d"),
]


def test_cfr_running_heads_and_folios_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = json.loads(FIXTURE.read_text())["pages"]
    texts = extract_recorded(monkeypatch, pages)
    left = [
        line for text in texts for line in plain_lines(text)
        if any(p.fullmatch(line) for p in RUNNING)
    ]
    assert left == []


def test_cfr_body_text_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = json.loads(FIXTURE.read_text())["pages"]
    texts = extract_recorded(monkeypatch, pages)
    kept = [
        line for page in pages for line in plain_lines(page["text"])
        if not any(p.fullmatch(line) for p in RUNNING) and not line.startswith("VerDate")
    ]
    # Same letters and digits in the same order (paragraphs split by a column break
    # are rejoined, so lines may merge; nothing else moves or goes missing).
    def stream(lines: list[str]) -> str:
        return "".join(c for line in lines for c in line if c.isalnum())

    assert stream([line for text in texts for line in plain_lines(text)]) == stream(kept)
    # Real section headings that carry a title are not running heads.
    assert "§ 164.102 Statutory basis." in collections.Counter(
        line for text in texts for line in plain_lines(text)
    )


# ------------------------------------------------------------- rules, synthetic


def page(lines: list[tuple[float, str, str]], height: float = 800.0) -> dict[str, Any]:
    """A page chunk from ``(y, class, text)`` boxes, one per line, in that order."""
    text, boxes = "", []
    for y, cls, body in lines:
        start = len(text)
        text += body + "\n\n"
        boxes.append({"class": cls, "bbox": (72.0, y, 500.0, y + 10.0), "pos": (start, start + len(body))})
    return {"text": text, "page_boxes": boxes, "height": height}


BODY = "Body text of the page that runs for many words and is clearly not a running head at all."


def dropped(chunks: list[dict[str, Any]]) -> list[list[str]]:
    found = pdf_layout.running_lines(chunks, [c["height"] for c in chunks])
    return [
        sorted(chunk["text"][s:e] for s, e in found.get(i, ()))
        for i, chunk in enumerate(chunks)
    ]


def test_alternating_heads_and_tracking_folios_are_running() -> None:
    chunks = [
        page([
            (40, "section-header", "## Dept. of Health" if n % 2 else "## Title 45 Edition"),
            (80, "text", BODY),
            (700, "text", BODY),
            (740, "text", str(629 + n)),
        ])
        for n in range(6)
    ]
    result = dropped(chunks)
    for n, lines in enumerate(result):
        head = "## Dept. of Health" if n % 2 else "## Title 45 Edition"
        assert lines == sorted([head, str(629 + n)])


def test_one_off_top_line_is_kept() -> None:
    chunks = [page([(40, "section-header", "## Running"), (80, "text", BODY)]) for _ in range(4)]
    chunks[0] = page([(40, "text", "Pt. 164"), (60, "section-header", "## Running"), (80, "text", BODY)])
    result = dropped(chunks)
    assert "Pt. 164" not in result[0]


def test_second_row_headings_that_start_pages_are_kept() -> None:
    chunks = [
        page([
            (40, "page-header", f"Chapter {1 + n // 4}"),
            (80, "section-header", f"## Exercise {n}"),
            (120, "text", BODY),
        ])
        for n in range(8)
    ]
    result = dropped(chunks)
    assert all(not any("Exercise" in line for line in lines) for lines in result)
    assert all(lines == [f"Chapter {1 + n // 4}"] for n, lines in enumerate(result))


def test_numbered_headings_once_per_page_are_kept() -> None:
    chunks = [page([(40, "section-header", f"## Question {n * 3 + 1}"), (80, "text", BODY)]) for n in range(6)]
    assert dropped(chunks) == [[] for _ in range(6)]


def test_section_locators_that_repeat_are_running() -> None:
    sections = [502, 502, 504, 506, 506, 508]
    chunks = [page([(40, "text", f"§ 164.{s}"), (80, "text", BODY)]) for s in sections]
    assert dropped(chunks) == [[f"§ 164.{s}"] for s in sections]


def test_a_chapter_opening_title_lower_on_the_page_is_kept() -> None:
    chunks = [page([(40, "page-header", "Inventory"), (80, "text", BODY)]) for _ in range(5)]
    chunks[0] = page([(200, "section-header", "# Inventory"), (300, "text", BODY)])
    result = dropped(chunks)
    assert result[0] == []
    assert all(lines == ["Inventory"] for lines in result[1:])


def test_bare_numbers_that_do_not_track_the_page_are_kept() -> None:
    # A chart's year label in the last row of three pages is not a folio.
    chunks = [page([(40, "text", BODY), (740, "text", "2024")]) for _ in range(3)]
    assert dropped(chunks) == [[], [], []]


def test_front_matter_roman_folios_and_heads_are_running() -> None:
    # Fed MPR front matter: "iv Monetary Policy Report" heads, the same head with
    # arabic folios later, and bare roman folios at the foot.
    heads = [
        "iv Monetary Policy Report",
        "vi Monetary Policy Report",
        "2 Monetary Policy Report",
        "3 Monetary Policy Report",
    ]
    folios = ["iii", "iv", "v", "vi"]
    chunks = [
        page([(40, "text", head), (80, "text", BODY), (740, "text", folio)])
        for head, folio in zip(heads, folios, strict=True)
    ]
    assert dropped(chunks) == [sorted([h, f]) for h, f in zip(heads, folios, strict=True)]
