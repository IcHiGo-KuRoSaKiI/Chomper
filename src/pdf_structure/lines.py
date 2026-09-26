"""Line-level PDF model.

``pymupdf4llm`` gives good markdown but throws away the typographic signals we need
to decide what is a heading, what is running noise and what is a formula. This module
keeps a parallel, positional view of the same document: one record per rendered line,
carrying font size, weight and bounding box.

Everything downstream in :mod:`src.pdf_structure` works from :class:`PageLine`.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:  # pragma: no cover
    FITZ_AVAILABLE = False


#: Fraction of page height treated as the top/bottom band where running
#: headers and footers live.
DEFAULT_BAND = 0.10


@dataclass(frozen=True)
class PageLine:
    """One rendered line of text with the typography needed to classify it."""

    page: int
    """1-based page number."""

    ordinal: int
    """Position of this line within the whole document, in reading order."""

    text: str
    """Line text, whitespace-stripped."""

    bbox: tuple[float, float, float, float]
    """(x0, y0, x1, y1) in PDF points."""

    size: float
    """Largest span font size on the line, rounded to 1dp."""

    font: str
    """Font name of the dominant span."""

    bold: bool
    """True when the dominant span's flags or font name advertise bold weight."""

    y_frac: float
    """bbox[1] divided by page height. Used for band tests."""

    page_height: float

    @property
    def band(self) -> str:
        """``TOP``, ``BOT`` or ``MID`` according to vertical position."""
        if self.y_frac < DEFAULT_BAND:
            return "TOP"
        if self.y_frac > 1.0 - DEFAULT_BAND:
            return "BOT"
        return "MID"

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "ordinal": self.ordinal,
            "text": self.text,
            "bbox": list(self.bbox),
            "size": self.size,
            "font": self.font,
            "bold": self.bold,
            "y_frac": self.y_frac,
            "band": self.band,
        }


def _is_bold(font_name: str, flags: int = 0) -> bool:
    """Return whether a PyMuPDF span advertises a bold or medium weight."""
    lowered = font_name.lower()
    weight_markers = ("bold", "semibold", "demi", "medium", "heavy", "black", "-medi")
    return bool(flags & 2**4) or any(marker in lowered for marker in weight_markers)


def extract_lines(pdf_document: Any) -> list[PageLine]:
    """Build the positional line model for an open PyMuPDF document.

    Args:
        pdf_document: an open ``fitz.Document``.

    Returns:
        Lines in reading order, with ``ordinal`` assigned document-wide.
    """
    lines: list[PageLine] = []
    ordinal = 0

    for page_index in range(len(pdf_document)):
        page = pdf_document[page_index]
        height = float(page.rect.height) or 1.0
        raw = page.get_text("dict")

        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(span.get("text", "") for span in spans).strip()
                if not text:
                    continue

                # The dominant span is the one contributing the most characters;
                # its font decides weight. Size uses the maximum, because a
                # heading followed by a footnote marker should still read as a
                # heading.
                dominant = max(spans, key=lambda s: len(s.get("text", "") or ""))
                size = round(max(float(s.get("size", 0.0)) for s in spans), 1)
                font = str(dominant.get("font", ""))
                bbox = tuple(float(v) for v in line.get("bbox", (0, 0, 0, 0)))

                title = lines[-1] if lines else None
                if (
                    title is not None
                    and title.page == page_index + 1
                    and _joins_section_number(title, text, bbox, size, font, spans)
                ):
                    # "3.1" and its title arrive as two runs on one row (LaTeX
                    # does this). Joined, the numbering signal can fire and the
                    # number cannot be stranded at the end of the previous chunk.
                    lines[-1] = PageLine(
                        page=title.page,
                        ordinal=title.ordinal,
                        text=f"{title.text} {text}",
                        bbox=(
                            min(title.bbox[0], bbox[0]), min(title.bbox[1], bbox[1]),
                            max(title.bbox[2], bbox[2]), max(title.bbox[3], bbox[3]),
                        ),
                        size=max(title.size, size),
                        font=font,
                        bold=True,
                        y_frac=title.y_frac,
                        page_height=height,
                    )
                    continue

                lines.append(
                    PageLine(
                        page=page_index + 1,
                        ordinal=ordinal,
                        text=text,
                        bbox=bbox,  # type: ignore[arg-type]
                        size=size,
                        font=font,
                        bold=_is_bold(font, int(dominant.get("flags", 0))),
                        y_frac=bbox[1] / height,
                        page_height=height,
                    )
                )
                ordinal += 1

    return lines


_SECTION_NUMBER = re.compile(r"^(?:[A-Z]|\d+)(?:\.\d+)*\.?$")


def _joins_section_number(
    number: PageLine,
    text: str,
    bbox: tuple[float, ...],
    size: float,
    font: str,
    spans: list[dict],
) -> bool:
    """True when ``number`` is a bare bold section number and ``text`` its title.

    Both runs must be bold, the same size and on one row, with the title just to
    the right and carrying words. Bold numeric table cells fail the last test.
    """
    if not number.bold or not _SECTION_NUMBER.match(number.text):
        return False
    dominant = max(spans, key=lambda s: len(s.get("text", "") or ""))
    if not _is_bold(font, int(dominant.get("flags", 0))):
        return False
    if abs(number.size - size) > 0.5 or sum(c.isalpha() for c in text) < 2:
        return False
    height = max(number.bbox[3] - number.bbox[1], 1e-6)
    overlap = min(number.bbox[3], bbox[3]) - max(number.bbox[1], bbox[1])
    gap = bbox[0] - number.bbox[2]
    return overlap >= 0.5 * height and 0 <= gap <= 1.5 * max(size, 1.0)


def body_size(lines: list[PageLine]) -> float:
    """Return the dominant body font size, by total character count.

    Character count rather than line count: a document with many short headings
    and few long paragraphs would otherwise pick a heading size as the body.
    """
    if not lines:
        return 0.0
    weight: dict[float, int] = {}
    for line in lines:
        if line.band != "MID":
            continue  # headers/footers must not influence the body baseline
        weight[line.size] = weight.get(line.size, 0) + len(line.text)
    if not weight:
        weight = {line.size: len(line.text) for line in lines}
    return max(weight.items(), key=lambda kv: kv[1])[0]
