"""Structural PDF parsing for long, heavily-formatted documents.

Turns a PDF into heading-bounded, table-safe, sentence-safe blocks carrying full
provenance. Built for structural PDF parsing.

The pipeline is six pure stages over a positional line model:

.. code-block:: text

    lines      -> PageLine[]        typography + bbox per rendered line
    noise      -> drop running headers, footers, copyright
    tables     -> geometric table regions (atomic)
    math       -> formula / T-account regions (atomic)
    headings   -> font-size tiers + bold promotion + numbering override
    assemble   -> StructuralBlock[] with provenance

Typical use::

    from src.pdf_structure import parse_structure

    result = parse_structure("course.pdf")
    for block in result.blocks:
        print(block.sequence_index, block.content_kind, block.heading_path)
    print(result.noise_report.summary())
    print(result.heading_report.summary())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .assemble import (
    DEFAULT_MAX_WORDS,
    DEFAULT_SOFT_MIN_WORDS,
    StructuralBlock,
    assemble_blocks,
    audit_mid_sentence,
)
from .headings import (
    HeadingReport,
    HeadingSpan,
    detect_headings,
    heading_path,
    parent_heading_id,
)
from .lines import PageLine, body_size, extract_lines
from .math_regions import MathRegion, detect_math_regions, math_ordinals
from .noise import NoiseReport, filter_noise
from .sentences import (
    ends_mid_sentence,
    reflow,
    split_paragraphs,
    split_sentences,
    verify_cut_boundaries,
    verify_sentence_integrity,
)
from .tables import TableRegion, find_table_regions, table_ordinals

__all__ = [
    "PageLine",
    "HeadingSpan",
    "HeadingReport",
    "NoiseReport",
    "TableRegion",
    "MathRegion",
    "StructuralBlock",
    "StructureResult",
    "parse_structure",
    "extract_lines",
    "body_size",
    "filter_noise",
    "detect_headings",
    "heading_path",
    "parent_heading_id",
    "find_table_regions",
    "table_ordinals",
    "detect_math_regions",
    "math_ordinals",
    "assemble_blocks",
    "audit_mid_sentence",
    "split_sentences",
    "split_paragraphs",
    "ends_mid_sentence",
    "verify_sentence_integrity",
    "verify_cut_boundaries",
    "reflow",
]


@dataclass
class StructureResult:
    """Everything the structural parse produced, including its own diagnostics."""

    blocks: list[StructuralBlock] = field(default_factory=list)
    lines: list[PageLine] = field(default_factory=list)
    headings: list[HeadingSpan] = field(default_factory=list)
    tables: list[TableRegion] = field(default_factory=list)
    maths: list[MathRegion] = field(default_factory=list)
    noise_report: NoiseReport = field(default_factory=NoiseReport)
    heading_report: HeadingReport = field(default_factory=HeadingReport)
    source_pdf_filename: str = ""
    page_count: int = 0

    @property
    def mid_sentence_blocks(self) -> list[int]:
        """Heuristic report of blocks that read as truncated prose.

        Useful for eyeballing quality, but it cannot separate "prose cut short"
        from "option row that has no full stop", so on real documents it
        over-reports. Use :attr:`sentence_integrity_violations` for the guarantee.
        """
        return audit_mid_sentence(self.blocks)

    @property
    def sentence_integrity_violations(self) -> list[int]:
        """Size-chosen cuts that fell inside a sentence. Empty means the guarantee holds.

        The authoritative check. Each cut is verified at split time against the
        exact text being split, so this reports a recorded fact rather than an
        after-the-fact reconstruction. Structural boundaries -- headings, atomic
        regions, section ends -- are excluded: what precedes them is whatever the
        author wrote, and real documents are full of bullet rows and enumerated
        labels that legitimately carry no full stop.
        """
        return [b.sequence_index for b in self.blocks if b.cut_safe is False]

    def summary(self) -> str:
        return (
            f"{self.source_pdf_filename}: {self.page_count} pages -> "
            f"{len(self.blocks)} blocks "
            f"({len(self.tables)} tables, {len(self.maths)} math regions, "
            f"{len(self.headings)} headings); "
            f"noise: {self.noise_report.summary()}"
        )


def parse_structure(
    file_path: str | Path,
    *,
    source_folder: str = "",
    max_words: int = DEFAULT_MAX_WORDS,
    soft_min_words: int = DEFAULT_SOFT_MIN_WORDS,
    split_at_h3: bool = False,
    enable_noise_filter: bool = True,
    tier_gap: float | None = None,
) -> StructureResult:
    """Parse a PDF into structural blocks.

    Args:
        file_path: path to the PDF.
        source_folder: provenance value, e.g. ``"manuals/reference"``.
        max_words: soft ceiling before a heading section is subdivided.
        soft_min_words: below this, a trailing block merges backwards.
        split_at_h3: also break at H3, not only H1/H2.
        enable_noise_filter: strip running headers, footers and boilerplate.
        tier_gap: override the heading size-tier clustering gap, in points.

    Returns:
        A :class:`StructureResult`.

    Raises:
        ImportError: if PyMuPDF is unavailable.
        FileNotFoundError: if the file does not exist.
    """
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "PyMuPDF is required for structural PDF parsing. "
            "Install with: pip install pymupdf"
        ) from exc

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    document = fitz.open(str(path))
    try:
        raw_lines = extract_lines(document)
        page_count = len(document)

        if enable_noise_filter:
            kept, noise_report = filter_noise(raw_lines)
        else:
            kept, noise_report = raw_lines, NoiseReport(
                total_lines=len(raw_lines),
                total_chars=sum(len(l.text) for l in raw_lines),
            )

        tables = find_table_regions(document, kept)
        t_ordinals = table_ordinals(tables)

        maths = detect_math_regions(kept, exclude_ordinals=t_ordinals)
        m_ordinals = math_ordinals(maths)

        heading_kwargs = {}
        if tier_gap is not None:
            heading_kwargs["tier_gap"] = tier_gap

        headings, heading_report = detect_headings(
            kept,
            source=path.name,
            exclude_ordinals=t_ordinals | m_ordinals,
            **heading_kwargs,
        )

        blocks = assemble_blocks(
            kept,
            headings,
            tables,
            maths,
            max_words=max_words,
            soft_min_words=soft_min_words,
            split_at_h3=split_at_h3,
        )
    finally:
        document.close()

    return StructureResult(
        blocks=blocks,
        lines=kept,
        headings=headings,
        tables=tables,
        maths=maths,
        noise_report=noise_report,
        heading_report=heading_report,
        source_pdf_filename=path.name,
        page_count=page_count,
    )
