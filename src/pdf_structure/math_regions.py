"""Formula and T-account region detection.

The content-integrity requirement asks for equations and step-by-step arithmetic to survive
chunking without fragmentation. It also suggests converting them to LaTeX. We do the
first and deliberately not the second, for a measured reason: the reference document
contains **zero** unicode superscript characters, so exponent notation has already been
flattened by the time any parser sees the text. Reconstructing correct LaTeX from
``x2`` is guesswork, and silently-wrong maths is worse than plainly-preserved maths.

What this module does:

* detect formula lines by symbol density (``= × ÷ /``, bracketed negatives, currency),
* detect T-account and worked-calculation grids by structural repetition,
* return regions so the chunker can keep them atomic and tag them.

The bounding boxes travel with each region, so a caller that genuinely needs LaTeX can
render the crop and hand it to a vision model -- the same route already used for images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lines import PageLine

#: Symbols that suggest arithmetic rather than prose.
_MATH_CHARS = set("=+×÷*/^<>≤≥±≈")
_BRACKETED_NEGATIVE = re.compile(r"\(\s*[\d,]+(?:\.\d+)?\s*\)")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_T_ACCOUNT_MARKER = re.compile(r"\b(Dr|Cr|Debit|Credit)\b")
_RULE_LINE = re.compile(r"^[\s\-_=|+]{6,}$")
_ASSIGNMENT = re.compile(r"^[A-Za-z][\w\s()'-]{0,40}=\s*\S")

#: Minimum share of non-space characters that must be numeric or mathematical
#: for a line to read as a calculation.
DEFAULT_DENSITY = 0.30


@dataclass(frozen=True)
class MathRegion:
    """A contiguous run of formula or T-account lines."""

    kind: str
    """``formula`` or ``t_account``."""
    page: int
    start_ordinal: int
    end_ordinal: int
    bbox: tuple[float, float, float, float]
    line_count: int

    @property
    def ordinals(self) -> frozenset[int]:
        return frozenset(range(self.start_ordinal, self.end_ordinal + 1))


def math_density(text: str) -> float:
    """Share of non-space characters that are digits or maths symbols."""
    stripped = [c for c in text if not c.isspace()]
    if not stripped:
        return 0.0
    hits = sum(1 for c in stripped if c.isdigit() or c in _MATH_CHARS)
    return hits / len(stripped)


def is_formula_line(text: str, *, density: float = DEFAULT_DENSITY) -> bool:
    """True when a line reads as arithmetic rather than prose."""
    if not text.strip():
        return False
    if text.strip().startswith("|"):
        return False  # a table row, handled elsewhere

    # "Name = expression" is a formula even when symbol density is low.
    if _ASSIGNMENT.match(text.strip()) and any(
        c in _MATH_CHARS for c in text
    ):
        return True

    if math_density(text) < density:
        return False
    # Require at least one number and one operator, else "2006 2007 2008" counts.
    return bool(_NUMBER.search(text)) and any(c in _MATH_CHARS for c in text)


def is_t_account_line(text: str) -> bool:
    """True for T-account scaffolding: Dr/Cr markers or a ruled divider."""
    stripped = text.strip()
    if not stripped:
        return False
    if _RULE_LINE.match(stripped):
        return True
    if _T_ACCOUNT_MARKER.search(stripped) and len(stripped.split()) <= 12:
        return True
    # A line split by a vertical bar with numbers on both sides.
    if "|" in stripped and not stripped.startswith("|"):
        left, _, right = stripped.partition("|")
        if _NUMBER.search(left) and _NUMBER.search(right):
            return True
    return False


def detect_math_regions(
    lines: list[PageLine],
    *,
    exclude_ordinals: frozenset[int] | None = None,
    density: float = DEFAULT_DENSITY,
    min_lines: int = 1,
) -> list[MathRegion]:
    """Group adjacent formula or T-account lines into regions.

    Args:
        lines: the filtered line model.
        exclude_ordinals: ordinals already claimed by tables.
        density: symbol-density threshold for formula lines.
        min_lines: shortest run to report.

    Returns:
        Regions in document order.
    """
    excluded = exclude_ordinals or frozenset()
    regions: list[MathRegion] = []

    run: list[PageLine] = []
    run_kind = "formula"

    def flush() -> None:
        nonlocal run, run_kind
        if run and len(run) >= min_lines:
            xs0 = min(l.bbox[0] for l in run)
            ys0 = min(l.bbox[1] for l in run)
            xs1 = max(l.bbox[2] for l in run)
            ys1 = max(l.bbox[3] for l in run)
            regions.append(
                MathRegion(
                    kind=run_kind,
                    page=run[0].page,
                    start_ordinal=run[0].ordinal,
                    end_ordinal=run[-1].ordinal,
                    bbox=(xs0, ys0, xs1, ys1),
                    line_count=len(run),
                )
            )
        run = []
        run_kind = "formula"

    for line in lines:
        # Band is not tested: noise removal has already run, so a surviving line
        # high on the page is content and may well be part of a calculation.
        if line.ordinal in excluded:
            flush()
            continue

        t_account = is_t_account_line(line.text)
        formula = is_formula_line(line.text, density=density)

        if not (t_account or formula):
            flush()
            continue

        # Break the run when the page changes, so a region never straddles pages.
        if run and line.page != run[-1].page:
            flush()

        # Any T-account evidence in the run types the whole region.
        if t_account:
            run_kind = "t_account"
        run.append(line)

    flush()
    return regions


def math_ordinals(regions: list[MathRegion]) -> frozenset[int]:
    """Union of every line ordinal inside any math region."""
    out: set[int] = set()
    for region in regions:
        out |= region.ordinals
    return frozenset(out)
