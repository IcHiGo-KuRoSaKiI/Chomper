"""Running header, footer and boilerplate removal.

On the real 438-page the reference document the running header appears on 437/438 pages, the
``Page N of M`` footer on 437/438, and together the top and bottom bands carry 6.9%
of all text in the document. Left in, that text lands inside every extracted chunk.

The filter requires three conditions together, never repetition alone:

1. the line sits in the top or bottom band of the page, **and**
2. its digit-normalised form recurs on at least ``page_ratio`` of pages, **and**
3. it is short.

That conjunction matters. A synthetic probe showed that frequency on its own also
flags a legitimate body paragraph that happens to repeat, and a formula printed on
every page. Filtering on frequency alone deletes real content, so conditions 1 and 3
are load-bearing rather than decorative.

A separate pattern list catches page numbers and copyright notices wherever they sit.

Known limitation: a *running* header cannot be identified from a document too short
for it to run. With ``min_pages`` defaulting to 3, a one or two page PDF keeps its
header, and only the explicit pattern list applies. That is the honest behaviour --
inferring chrome from a single sample would be guesswork -- and it does not affect the
hundreds-of-pages documents this is built for.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .lines import PageLine

#: Fraction of pages a candidate must appear on to count as running noise.
DEFAULT_PAGE_RATIO = 0.60

#: Longest line length still considered chrome rather than content.
DEFAULT_MAX_LEN = 120

#: Patterns that are noise regardless of position.
BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^page\s+\d+\s*(of|/)\s*\d+$", re.I),
    re.compile(r"^\d+\s*\|\s*page$", re.I),
    re.compile(r"^page\s+\d+$", re.I),
    re.compile(r"all rights reserved", re.I),
    re.compile(r"^\s*(©|\(c\))\s", re.I),
    re.compile(r"(©|\(c\))\s*\d{4}", re.I),
    re.compile(r"example foundation", re.I),
    re.compile(r"^\s*confidential\s*$", re.I),
)

_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Digit-insensitive, case-insensitive form used for repetition counting."""
    return _WS.sub(" ", _DIGITS.sub("#", text)).strip().casefold()


@dataclass
class NoiseReport:
    """What the filter removed, for the audit trail."""

    total_lines: int = 0
    removed_lines: int = 0
    removed_chars: int = 0
    total_chars: int = 0
    patterns: list[dict] = field(default_factory=list)
    """One entry per distinct noise form: shape, page count, reason."""

    @property
    def removed_char_pct(self) -> float:
        if not self.total_chars:
            return 0.0
        return 100.0 * self.removed_chars / self.total_chars

    def summary(self) -> str:
        return (
            f"removed {self.removed_lines}/{self.total_lines} lines "
            f"({self.removed_char_pct:.1f}% of characters) "
            f"across {len(self.patterns)} distinct noise forms"
        )


def _matches_boilerplate(text: str) -> str | None:
    for pattern in BOILERPLATE_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def filter_noise(
    lines: list[PageLine],
    *,
    page_ratio: float = DEFAULT_PAGE_RATIO,
    max_len: int = DEFAULT_MAX_LEN,
    min_pages: int = 3,
) -> tuple[list[PageLine], NoiseReport]:
    """Drop running headers, footers and boilerplate.

    Args:
        lines: the document line model.
        page_ratio: fraction of pages a banded line must recur on.
        max_len: maximum length for a line to be considered chrome.
        min_pages: absolute floor, so short documents are not over-filtered.

    Returns:
        ``(kept_lines, report)``.
    """
    report = NoiseReport(
        total_lines=len(lines),
        total_chars=sum(len(line.text) for line in lines),
    )
    if not lines:
        return [], report

    page_count = len({line.page for line in lines})
    threshold = max(min_pages, int(page_count * page_ratio))

    # Count banded, short candidates by normalised form.
    banded_pages: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        if line.band == "MID":
            continue
        if len(line.text) > max_len:
            continue
        banded_pages[normalise(line.text)].add(line.page)

    running = {
        form for form, pages in banded_pages.items()
        if len(pages) >= threshold
    }

    kept: list[PageLine] = []
    reasons: dict[str, dict] = {}

    for line in lines:
        form = normalise(line.text)
        reason: str | None = None

        pattern = _matches_boilerplate(line.text)
        if pattern is not None:
            reason = f"boilerplate:{pattern}"
        elif (
            line.band != "MID"
            and len(line.text) <= max_len
            and form in running
        ):
            reason = "running_header_footer"

        if reason is None:
            kept.append(line)
            continue

        report.removed_lines += 1
        report.removed_chars += len(line.text)
        entry = reasons.setdefault(
            form,
            {
                "shape": re.sub(r"[A-Za-z]", "a", form)[:60],
                "reason": reason,
                "pages": 0,
                "example_len": len(line.text),
            },
        )
        entry["pages"] += 1

    report.patterns = sorted(
        reasons.values(), key=lambda d: -int(d["pages"])
    )
    return kept, report
