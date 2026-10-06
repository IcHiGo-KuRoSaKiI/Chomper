"""
PDF figures: vector charts are found, captions are linked, markers are placed.

Built from generated PDFs so every case has an exact expected answer.

Run: ``python -m pytest src/tests/test_pdf_figures.py -q``
"""

from __future__ import annotations

import base64
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF required")
from PIL import Image  # noqa: E402

import chomper  # noqa: E402

MARKER = re.compile(r"!\[([^\]]*)\]\(image:([\w.-]+)\)")


def _png(w: int, h: int, color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "PNG")
    return out.getvalue()


def _bar_chart(page, ox: float, oy: float) -> None:
    page.draw_line((ox, oy), (ox + 300, oy))
    page.draw_line((ox, oy), (ox, oy - 200))
    for i, (name, h) in enumerate([("APAC", 150), ("EMEA", 90), ("NA", 170), ("LATAM", 60)]):
        x = ox + 20 + i * 70
        page.draw_rect(fitz.Rect(x, oy - h, x + 40, oy), color=(0, 0, 0), fill=(0.9, 0.4, 0.1))
        page.insert_text((x + 2, oy + 12), name, fontsize=8)
    for v in range(0, 201, 50):
        page.insert_text((ox - 24, oy - v + 3), str(v), fontsize=8)


@pytest.fixture
def chart_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Annual revenue grew strongly across all four regions.", fontsize=11)
    _bar_chart(page, 110, 300)
    page.insert_text((72, 330), "Figure 3: Revenue by region, 2026", fontsize=9)
    page.insert_text((72, 360), "The chart above shows NA leading, followed by APAC.", fontsize=11)
    # A shaded call-out box with text: decoration, not a figure.
    page.draw_rect(fitz.Rect(72, 400, 520, 470), color=None, fill=(0.9, 0.9, 0.95))
    page.insert_text((84, 425), "Key takeaway: growth was broad-based across regions", fontsize=11)
    page.insert_text((84, 445), "and was led by stronger demand in North America.", fontsize=11)
    path = tmp_path / "chart.pdf"
    doc.save(path)
    return path


@pytest.fixture
def framed_pdf(tmp_path: Path) -> Path:
    """Report-style figure: caption in a filled title bar inside the frame."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(80, 80, 460, 360), color=(0.2, 0.3, 0.5), width=1)
    page.draw_rect(fitz.Rect(80, 80, 460, 100), color=None, fill=(0.2, 0.3, 0.5))
    page.insert_text((86, 94), "Figure 7. Measures of rental price inflation", fontsize=10, color=(1, 1, 1))
    _bar_chart(page, 130, 330)
    page.insert_text((80, 400), "Figure 8. Measures of inflation expectations", fontsize=10)
    page.insert_text((80, 420), "is discussed in the next section of this report.", fontsize=10)
    path = tmp_path / "framed.pdf"
    doc.save(path)
    return path


@pytest.fixture
def side_by_side_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "The two attention variants are compared below.", fontsize=11)
    page.insert_image(fitz.Rect(72, 80, 272, 230), stream=_png(400, 300, "red"))
    page.insert_image(fitz.Rect(300, 80, 500, 250), stream=_png(400, 340, "blue"))
    page.insert_text((72, 270), "Figure 2: (left) Scaled attention. (right) Multi-head attention.", fontsize=9)
    path = tmp_path / "side.pdf"
    doc.save(path)
    return path


def test_vector_chart_is_found_captioned_and_marked(chart_pdf: Path):
    result = chomper.parse(str(chart_pdf), include_images=True)
    markers = MARKER.findall(result.text)
    assert markers == [("Figure 3: Revenue by region, 2026", "p1-1")]
    # Marker sits between the text above the chart and the caption line.
    text = result.text
    assert text.index("Annual revenue") < text.index("](image:p1-1)") < text.index("\nFigure 3: Revenue")

    [chart] = result.images
    assert chart["kind"] == "vector" and chart["mime_type"] == "image/png"
    rendered = Image.open(io.BytesIO(base64.b64decode(chart["content"])))
    assert max(rendered.size) <= 1568
    # Axis labels are part of the crop, not cut off at the bars.
    assert chart["position"]["x0"] < 110 - 15 and chart["position"]["y1"] > 300 + 5


def test_shaded_text_box_is_not_a_figure(chart_pdf: Path):
    result = chomper.parse(str(chart_pdf), include_images=True)
    assert len(result.images) == 1


def test_caption_inside_title_bar_wins_over_next_figures_caption(framed_pdf: Path):
    markers = MARKER.findall(chomper.parse(str(framed_pdf)).text)
    assert markers == [("Figure 7. Measures of rental price inflation", "p1-1")]


def test_side_by_side_panels_share_a_caption(side_by_side_pdf: Path):
    result = chomper.parse(str(side_by_side_pdf), include_images=True)
    alts = {image["id"]: image.get("alt", "") for image in result.images}
    assert set(alts) == {"p1-1", "p1-2"}
    assert all(alt.startswith("Figure 2: (left)") for alt in alts.values())


def test_image_ids_round_trip_to_get_document_images(side_by_side_pdf: Path):
    import asyncio

    from src.handlers.images import handle_get_document_images

    text = chomper.parse(str(side_by_side_pdf)).text
    for _, image_id in MARKER.findall(text):
        reply = asyncio.run(
            handle_get_document_images({"file_path": str(side_by_side_pdf), "image_id": image_id})
        )
        assert sum(1 for item in reply if item.type == "image") == 1


def test_vector_figures_can_be_turned_off(chart_pdf: Path):
    from src.extractors.pdf_extractor import PDFExtractor

    raw = PDFExtractor(extract_vector_figures=False).extract(str(chart_pdf))
    assert raw.structure["images"] == []
    assert "image:" not in raw.text
