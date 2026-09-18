"""Heading detection: font-size tiers, bold promotion, numbering override.

``pymupdf4llm`` emits its own ``#`` markers, but they cannot be trusted. Measured on
the real 438-page the reference document it produced 1270 headings of which 1090 (86%) were H6 and
only 2 were H1 -- H6 is used as a catch-all. Reliable heading levels are needed for
H1/H2, so we compute levels ourselves from typography.

Three signals, in increasing order of precision:

* **size tier** -- broad, catches most headings, but the tier boundaries are sensitive
  to the clustering gap (see :func:`build_tiers`).
* **bold at body size** -- recovers sub-headings that size alone misses. On the reference document
  there are 2989 short bold lines at body size.
* **numeric prefix** (``1``, ``1.1``, ``1.1.1``) -- highest precision, overrides the
  other two when present, but sparse (only 72 lines on the reference document).

Honest limitation: tier boundaries need calibration against labelled headings. On
the reference document a 1.0pt gap yields three tiers but discards 164 probable heading lines, while
a 2.0pt gap discards none but collapses 13pt-18pt into one level. The default is 2.0pt
because losing content is worse than over-merging, but neither is provably right
without ground truth. :func:`detect_headings` therefore returns a
:class:`HeadingReport` exposing the tiers it chose so the decision is visible.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .lines import PageLine, body_size

#: A line must exceed body size by this ratio to be a size-based candidate.
#: 1.15 excludes the 12.0/12.2pt emphasis text on the reference document (9-11% above an 11pt
#: body), which is bolded body copy rather than headings.
DEFAULT_SIZE_RATIO = 1.15

#: Sizes closer together than this are merged into one tier.
DEFAULT_TIER_GAP = 2.0

#: Sizes within this distance are treated as the same size (15.0 vs 15.1).
SIZE_EPSILON = 0.5

#: A size with fewer lines than this is a one-off (cover title), held aside
#: rather than deleted or promoted to H1.
DEFAULT_MIN_TIER_LINES = 10

#: Deepest level emitted. Only H1/H2 are required; H3 is available for
#: finer-grained splitting when enabled.
MAX_LEVEL = 3

_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(\S.*)$")
_ALL_DIGITS = re.compile(r"^[\d\s.,:%()£$-]+$")
_MAX_HEADING_WORDS = 20


@dataclass(frozen=True)
class HeadingSpan:
    """A detected heading and where it sits."""

    heading_id: str
    level: int
    text: str
    page: int
    ordinal: int
    """``PageLine.ordinal`` of the heading line."""
    size: float
    signal: str
    """Which rule fired: ``size``, ``bold``, ``numbering`` or ``title``."""

    @property
    def is_title(self) -> bool:
        return self.level == 0


@dataclass
class HeadingReport:
    """Why the detector produced the levels it did."""

    body_size: float = 0.0
    tiers: list[list[float]] = field(default_factory=list)
    title_sizes: list[float] = field(default_factory=list)
    counts_by_level: dict[int, int] = field(default_factory=dict)
    counts_by_signal: dict[str, int] = field(default_factory=dict)
    tier_gap: float = DEFAULT_TIER_GAP

    def summary(self) -> str:
        tiers = "; ".join(
            f"H{i + 1}={t}" for i, t in enumerate(self.tiers[:MAX_LEVEL])
        )
        return (
            f"body={self.body_size}pt gap={self.tier_gap}pt "
            f"tiers[{tiers}] titles={self.title_sizes} "
            f"levels={dict(sorted(self.counts_by_level.items()))} "
            f"signals={self.counts_by_signal}"
        )


def build_tiers(
    lines: list[PageLine],
    *,
    body: float,
    size_ratio: float = DEFAULT_SIZE_RATIO,
    tier_gap: float = DEFAULT_TIER_GAP,
    min_tier_lines: int = DEFAULT_MIN_TIER_LINES,
) -> tuple[list[list[float]], list[float]]:
    """Cluster font sizes above the body into heading tiers.

    Returns:
        ``(tiers, title_sizes)`` where ``tiers[0]`` is H1. ``title_sizes`` holds
        rare oversized fonts (a cover title) which are neither a tier nor body.
    """
    counts: dict[float, int] = {}
    for line in lines:
        # No band filtering here. Running headers and footers are removed by
        # :func:`~src.pdf_structure.noise.filter_noise` before this runs, so a
        # surviving line near the top of a page is content -- typically a chapter
        # heading, which is exactly what we must not discard. A large heading's
        # glyph box can easily start above the 10% band line.
        if line.size > body * size_ratio:
            counts[line.size] = counts.get(line.size, 0) + 1
    if not counts:
        return [], []

    # Merge near-identical sizes into the larger of the pair.
    merged: dict[float, int] = {}
    for size in sorted(counts, reverse=True):
        target = next(
            (k for k in merged if abs(k - size) <= SIZE_EPSILON), None
        )
        if target is not None:
            merged[target] += counts[size]
        else:
            merged[size] = counts[size]

    # Rare sizes are one-offs, not a heading level of their own.
    title_sizes = sorted(
        (s for s, n in merged.items() if n < min_tier_lines), reverse=True
    )
    keep = {s: n for s, n in merged.items() if n >= min_tier_lines}
    if not keep:
        # Everything is rare: treat the largest as the single heading tier so a
        # short document still gets structure.
        if not title_sizes:
            return [], []
        return [[title_sizes[0]]], title_sizes[1:]

    ordered = sorted(keep, reverse=True)
    tiers: list[list[float]] = []
    current = [ordered[0]]
    for size in ordered[1:]:
        if current[-1] - size <= tier_gap:
            current.append(size)
        else:
            tiers.append(current)
            current = [size]
    tiers.append(current)

    return tiers, title_sizes


def _heading_id(source: str, page: int, ordinal: int, text: str) -> str:
    raw = f"{source}|{page}|{ordinal}|{text}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _plausible(line: PageLine) -> bool:
    """Reject lines that cannot be headings regardless of typography."""
    if line.word_count > _MAX_HEADING_WORDS:
        return False
    if _ALL_DIGITS.match(line.text):
        return False
    if line.text.startswith("|"):  # table row
        return False
    # Glyph-only lines: tick marks, bullets and margin icons get rendered large
    # but carry no words. On the reference document a 14pt tick was being promoted to
    # a heading and then used as a section name.
    if sum(1 for c in line.text if c.isalpha()) < 2:
        return False
    return True


def detect_headings(
    lines: list[PageLine],
    *,
    source: str = "",
    size_ratio: float = DEFAULT_SIZE_RATIO,
    tier_gap: float = DEFAULT_TIER_GAP,
    min_tier_lines: int = DEFAULT_MIN_TIER_LINES,
    enable_bold: bool = True,
    enable_numbering: bool = True,
    exclude_ordinals: frozenset[int] | None = None,
) -> tuple[list[HeadingSpan], HeadingReport]:
    """Detect headings and assign levels.

    Args:
        lines: filtered line model (run noise removal first).
        source: document identifier, mixed into ``heading_id``.
        exclude_ordinals: line ordinals inside tables or formulas, never headings.

    Returns:
        ``(headings, report)`` with headings in document order.
    """
    excluded = exclude_ordinals or frozenset()
    report = HeadingReport(tier_gap=tier_gap)
    if not lines:
        return [], report

    body = body_size(lines)
    report.body_size = body

    tiers, title_sizes = build_tiers(
        lines,
        body=body,
        size_ratio=size_ratio,
        tier_gap=tier_gap,
        min_tier_lines=min_tier_lines,
    )
    report.tiers = tiers
    report.title_sizes = title_sizes

    def level_for_size(size: float) -> int | None:
        for index, tier in enumerate(tiers[:MAX_LEVEL]):
            if any(abs(size - s) <= SIZE_EPSILON for s in tier):
                return index + 1
        return None

    def is_title_size(size: float) -> bool:
        return any(abs(size - s) <= SIZE_EPSILON for s in title_sizes)

    #: Deepest size-derived level in play, so bold promotion sits below it.
    deepest = min(len(tiers), MAX_LEVEL)
    bold_level = min(deepest + 1, MAX_LEVEL) if deepest else 1

    headings: list[HeadingSpan] = []

    for line in lines:
        # Band is deliberately not tested here; see the note in build_tiers.
        if line.ordinal in excluded:
            continue
        if not _plausible(line):
            continue

        level: int | None = None
        signal = ""

        if is_title_size(line.size):
            level, signal = 0, "title"
        else:
            size_level = level_for_size(line.size)
            if size_level is not None:
                level, signal = size_level, "size"
            elif (
                enable_bold
                and line.bold
                and line.size <= body * size_ratio
                and line.word_count <= 12
                and not line.text.rstrip().endswith(".")
            ):
                level, signal = bold_level, "bold"

        # Numbering is the most reliable signal and overrides the rest, but only
        # for lines that already look like a heading, or are bold/oversized.
        if enable_numbering:
            match = _NUMBERED.match(line.text)
            if match:
                depth = match.group(1).count(".") + 1
                looks_like_heading = (
                    level is not None
                    or line.bold
                    or line.size > body * 1.05
                )
                if looks_like_heading and depth <= MAX_LEVEL:
                    level, signal = depth, "numbering"

        if level is None:
            continue

        headings.append(
            HeadingSpan(
                heading_id=_heading_id(source, line.page, line.ordinal, line.text),
                level=level,
                text=line.text,
                page=line.page,
                ordinal=line.ordinal,
                size=line.size,
                signal=signal,
            )
        )

    for h in headings:
        report.counts_by_level[h.level] = report.counts_by_level.get(h.level, 0) + 1
        report.counts_by_signal[h.signal] = (
            report.counts_by_signal.get(h.signal, 0) + 1
        )

    return headings, report


def heading_path(headings: list[HeadingSpan], ordinal: int) -> str:
    """Breadcrumb of enclosing headings for a line, e.g. ``"Chapter 2 > 2.1 Scope"``."""
    stack: dict[int, str] = {}
    for h in headings:
        if h.ordinal > ordinal:
            break
        if h.level == 0:
            continue
        stack[h.level] = h.text
        for deeper in list(stack):
            if deeper > h.level:
                del stack[deeper]
    return " > ".join(stack[k] for k in sorted(stack))


def parent_heading_id(headings: list[HeadingSpan], ordinal: int) -> str | None:
    """``heading_id`` of the innermost enclosing H2, else H1, else None."""
    best: HeadingSpan | None = None
    for h in headings:
        if h.ordinal > ordinal:
            break
        if h.level in (1, 2):
            if best is None or h.level >= best.level or h.ordinal > best.ordinal:
                best = h
    return best.heading_id if best else None
