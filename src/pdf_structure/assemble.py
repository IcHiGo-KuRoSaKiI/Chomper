"""Assemble structural blocks from the line model.

Boundary rules, applied strictly in this order:

1. **A heading starts a new block.** H1 and H2 always; H3 optionally. The document's
   own headings are the structural markers we split on.
2. **Atomic regions are never split.** Tables, formulas and T-accounts pass through
   whole, so their internal structure survives.
3. **Only when a section exceeds ``max_words``** is it subdivided, and then at a
   paragraph boundary first, a sentence boundary second, and never mid-word.
4. **Runt tails are merged back** unless they are atomic.

Word-count is a *last resort* here, not the primary mechanism. That is the substantive
difference from the original ``PDFChunker``, which sliced a flat word list and left 13
of 15 chunks ending mid-sentence in measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .headings import HeadingSpan, heading_path, parent_heading_id
from .lines import PageLine
from .math_regions import MathRegion
from .sentences import (
    ends_mid_sentence,
    reflow,
    split_paragraphs,
    split_sentences,
    verify_cut_boundaries,
)
from .tables import TableRegion

DEFAULT_MAX_WORDS = 600
DEFAULT_SOFT_MIN_WORDS = 40


@dataclass
class StructuralBlock:
    """One assembled block, with full provenance."""

    text: str
    sequence_index: int
    page_start: int
    page_end: int
    heading_path: str
    parent_heading_id: str | None
    heading_level: int | None
    section_name: str
    content_kind: str
    """``prose``, ``table``, ``formula``, ``t_account`` or ``mixed``."""
    atomic: bool = False
    word_count: int = 0
    ordinals: tuple[int, ...] = field(default_factory=tuple)
    contains_table: bool = False
    """True when any table region contributes to this block."""
    contains_math: bool = False
    """True when any formula or T-account region contributes to this block."""
    ends_with_heading: bool = False
    """True when the final line is a heading.

    A heading is a complete structural unit, so a block ending on one is not a
    truncated sentence even though the text has no terminating full stop.
    """
    cut_safe: bool | None = None
    """Whether this block's trailing cut landed on a sentence boundary.

    `None` when the boundary was structural (a heading, an atomic region or the
    end of a section) and so not ours to guarantee. `True`/`False` only for
    cuts we chose, verified at split time against the exact source text.
    """
    split_by_size: bool = False
    """True when this block's end was chosen by us because the section was too big.

    This is the set the guarantee governs. Where a block ends at a heading or at the end of
    the document, the tail is whatever the author wrote -- real documents are full
    of bullet lists, option chips and icon legends that legitimately carry no full
    stop, and calling those "mid-sentence" would be wrong. Where *we* pick the cut,
    it must land on a paragraph or sentence boundary.
    """

    def to_metadata(
        self,
        *,
        source_pdf_filename: str = "",
        source_folder: str = "",
    ) -> dict:
        """Provenance metadata, matching the field names provenance specifies."""
        return {
            "source_folder": source_folder,
            "source_pdf_filename": source_pdf_filename,
            "page_number": self.page_start,
            "page_span": [self.page_start, self.page_end],
            "sequence_index": self.sequence_index,
            "parent_heading_id": self.parent_heading_id,
            "heading_path": self.heading_path,
            "heading_level": self.heading_level,
            "section_name": self.section_name,
            "content_kind": self.content_kind,
            "atomic": self.atomic,
            "contains_table": self.contains_table,
            "contains_math": self.contains_math,
            "has_images": False,
            "section_type": "table" if self.contains_table else "text",
            "chunk_strategy": "structural",
        }


@dataclass
class _Unit:
    """An indivisible piece of content: a line run that must stay together."""

    lines: list[PageLine]
    kind: str
    atomic: bool
    heading_ordinals: frozenset[int] = field(default_factory=frozenset)

    @property
    def text(self) -> str:
        """Rendered text.

        Tables, formulas and T-accounts are emitted verbatim, because their line
        breaks and column alignment carry the meaning. Prose is reflowed to undo
        PDF soft wrapping, with heading lines kept on their own line so they stay
        visible as structure rather than dissolving into the paragraph.
        """
        if self.kind != "prose":
            return "\n".join(l.text for l in self.lines)

        parts: list[str] = []
        run: list[str] = []

        def flush() -> None:
            if run:
                parts.append(reflow("\n".join(run)))
                run.clear()

        for line in self.lines:
            if line.ordinal in self.heading_ordinals:
                flush()
                parts.append(line.text)
            else:
                run.append(line.text)
        flush()

        return "\n\n".join(p for p in parts if p.strip())

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def _build_units(
    lines: list[PageLine],
    tables: list[TableRegion],
    maths: list[MathRegion],
    boundary_ordinals: frozenset[int] = frozenset(),
    heading_ordinals: frozenset[int] = frozenset(),
) -> list[_Unit]:
    """Group lines into atomic units, preserving document order.

    A unit breaks when the atomic-region membership changes **or** when a line is
    a structural boundary. Without the boundary break every run of prose would
    coalesce into one unit and heading boundaries would have nothing to split
    between, collapsing the whole document into a single block.
    """
    kind_by_ordinal: dict[int, str] = {}
    group_by_ordinal: dict[int, str] = {}

    for index, region in enumerate(tables):
        for ordinal in region.ordinals:
            kind_by_ordinal[ordinal] = "table"
            group_by_ordinal[ordinal] = f"table:{index}"

    for index, region in enumerate(maths):
        for ordinal in region.ordinals:
            # Tables win: a numeric grid already captured as a table stays a table.
            if ordinal in kind_by_ordinal:
                continue
            kind_by_ordinal[ordinal] = region.kind
            group_by_ordinal[ordinal] = f"{region.kind}:{index}"

    units: list[_Unit] = []
    current: list[PageLine] = []
    current_group: str | None = None

    def flush() -> None:
        nonlocal current, current_group
        if current:
            kind = kind_by_ordinal.get(current[0].ordinal, "prose")
            units.append(
                _Unit(
                    lines=current,
                    kind=kind,
                    atomic=current_group is not None,
                    heading_ordinals=heading_ordinals,
                )
            )
        current = []
        current_group = None

    for line in lines:
        group = group_by_ordinal.get(line.ordinal)
        if group != current_group or line.ordinal in boundary_ordinals:
            flush()
            current_group = group
        current.append(line)

    flush()
    return units


def _subdivide(text: str, max_words: int) -> list[str]:
    """Split oversized prose without ever cutting inside a sentence.

    Sentences are the atom. Paragraph boundaries are *preferred* cut points but
    never required, because a PDF paragraph is frequently a layout artefact -- one
    logical sentence routinely arrives as two "paragraphs" either side of a page
    or column break. Cutting on paragraph boundaries alone therefore still lands
    mid-sentence, which is what measurement on the real 438-page document showed:
    221 of 1405 size-chosen cuts were mid-sentence before this was restructured.

    So: tokenise into sentences first, then pack greedily. Every boundary is a
    sentence boundary by construction, and a paragraph end is taken when one falls
    inside the tail window of the budget.
    """
    paragraphs = split_paragraphs(reflow(text)) or [text]

    # Flatten to (sentence, ends_paragraph) preserving order.
    items: list[tuple[str, bool]] = []
    for paragraph in paragraphs:
        sentences = split_sentences(paragraph, do_reflow=False) or [paragraph]
        for index, sentence in enumerate(sentences):
            items.append((sentence, index == len(sentences) - 1))

    if not items:
        return []

    pieces: list[str] = []
    buffer: list[str] = []
    words = 0
    #: Once the buffer is this full, a paragraph end is a good place to stop.
    tail_window = max(1, int(max_words * 0.75))

    for sentence, ends_paragraph in items:
        count = len(sentence.split())

        # A single sentence longer than the budget is emitted whole. Truncating it
        # would violate the one guarantee this function exists to provide.
        if not buffer and count > max_words:
            pieces.append(sentence)
            continue

        if buffer and words + count > max_words:
            pieces.append(" ".join(buffer))
            buffer, words = [], 0

        buffer.append(sentence)
        words += count

        if ends_paragraph and words >= tail_window:
            pieces.append(" ".join(buffer))
            buffer, words = [], 0

    if buffer:
        pieces.append(" ".join(buffer))

    return [p.strip() for p in pieces if p.strip()]


def assemble_blocks(
    lines: list[PageLine],
    headings: list[HeadingSpan],
    tables: list[TableRegion],
    maths: list[MathRegion],
    *,
    max_words: int = DEFAULT_MAX_WORDS,
    soft_min_words: int = DEFAULT_SOFT_MIN_WORDS,
    split_at_h3: bool = False,
) -> list[StructuralBlock]:
    """Produce heading-bounded, atomic-safe, sentence-safe blocks."""
    if not lines:
        return []

    split_levels = {1, 2, 3} if split_at_h3 else {1, 2}
    heading_by_ordinal = {h.ordinal: h for h in headings}
    boundary_ordinals = frozenset(
        h.ordinal for h in headings if h.level in split_levels
    )

    units = _build_units(
        lines, tables, maths, boundary_ordinals, frozenset(heading_by_ordinal)
    )

    # --- group units into heading-bounded sections -----------------------------
    sections: list[list[_Unit]] = []
    current: list[_Unit] = []
    for unit in units:
        starts_section = any(
            line.ordinal in boundary_ordinals for line in unit.lines
        )
        if starts_section and current:
            sections.append(current)
            current = []
        current.append(unit)
    if current:
        sections.append(current)

    # A heading with no body of its own (a chapter title immediately followed by
    # its first subsection) is a container, not content. Fold it into the section
    # that follows so it does not become a three-word block.
    folded: list[list[_Unit]] = []
    carry: list[_Unit] = []
    for section in sections:
        body_words = sum(
            u.word_count
            for u in section
            if not any(l.ordinal in heading_by_ordinal for l in u.lines)
        )
        heading_only = body_words == 0 and all(
            all(l.ordinal in heading_by_ordinal for l in u.lines) for u in section
        )
        if heading_only:
            carry.extend(section)
            continue
        folded.append(carry + section)
        carry = []
    if carry:
        if folded:
            folded[-1].extend(carry)
        else:
            folded.append(carry)
    sections = folded

    # --- turn each section into one or more blocks -----------------------------
    blocks: list[StructuralBlock] = []

    for section in sections:
        section_words = sum(u.word_count for u in section)
        first_ordinal = section[0].lines[0].ordinal

        # Label the section by its most specific boundary heading, not the first
        # line. A folded container ("1 Chapter") followed by its first subsection
        # ("1.1 Scope") should read as 1.1, with 1 as the parent in the path.
        section_ordinals = [l.ordinal for u in section for l in u.lines]
        boundary_heads = [
            heading_by_ordinal[o]
            for o in section_ordinals
            if o in heading_by_ordinal
            and heading_by_ordinal[o].level in split_levels
        ]
        head = boundary_heads[-1] if boundary_heads else heading_by_ordinal.get(
            first_ordinal
        )

        anchor = head.ordinal if head else first_ordinal
        path = heading_path(headings, anchor)
        parent = parent_heading_id(headings, anchor)
        name = head.text if head else (path.split(" > ")[-1] if path else "Introduction")

        if section_words <= max_words:
            _emit(blocks, section, path, parent, head, name)
            continue

        # Oversized: split, but only between units, never inside an atomic one.
        pending: list[_Unit] = []
        pending_words = 0

        def flush_pending(*, by_size: bool = True) -> None:
            nonlocal pending, pending_words
            if pending:
                _emit(blocks, pending, path, parent, head, name, split_by_size=by_size)
            pending = []
            pending_words = 0

        for unit in section:
            if unit.atomic:
                # Atomic units are emitted whole. If the buffer is already full,
                # close it first so the table is not glued onto a full block.
                if pending_words + unit.word_count > max_words:
                    flush_pending()
                pending.append(unit)
                pending_words += unit.word_count
                continue

            if unit.word_count > max_words:
                flush_pending()
                pieces = _subdivide(unit.text, max_words)
                # Verify against the exact text we split, while we still have it.
                # Reassembling later from block text cannot work: heading lines get
                # folded in and shift every offset.
                unsafe = set(verify_cut_boundaries(unit.text, pieces))
                for piece_index, piece in enumerate(pieces):
                    blocks.append(
                        _make_block(
                            text=piece,
                            index=len(blocks),
                            lines=unit.lines,
                            kind=unit.kind,
                            atomic=False,
                            path=path,
                            parent=parent,
                            head=head,
                            name=name,
                            split_by_size=True,
                            cut_safe=piece_index not in unsafe,
                        )
                    )
                continue

            if pending and pending_words + unit.word_count > max_words:
                flush_pending()
            pending.append(unit)
            pending_words += unit.word_count

        # The trailing flush is the natural end of the section, not a size cut.
        flush_pending(by_size=False)

    # --- merge runt tails ------------------------------------------------------
    # The merge must never undo a split we just made on purpose: when
    # soft_min_words exceeds max_words, every subdivided piece would otherwise be
    # glued straight back together. Requiring the merged result to stay within
    # max_words keeps the two settings from fighting each other.
    merged: list[StructuralBlock] = []
    for block in blocks:
        if (
            merged
            and not block.atomic
            and not merged[-1].atomic
            and block.word_count < soft_min_words
            and block.heading_path == merged[-1].heading_path
            and merged[-1].word_count + block.word_count <= max_words
        ):
            previous = merged[-1]
            previous.text = f"{previous.text}\n\n{block.text}".strip()
            previous.word_count = len(previous.text.split())
            previous.page_end = max(previous.page_end, block.page_end)
            previous.ordinals = previous.ordinals + block.ordinals
            previous.contains_table = previous.contains_table or block.contains_table
            previous.contains_math = previous.contains_math or block.contains_math
            continue
        merged.append(block)

    for index, block in enumerate(merged):
        block.sequence_index = index

    return merged


def _emit(
    blocks: list[StructuralBlock],
    units: list[_Unit],
    path: str,
    parent: str | None,
    head: HeadingSpan | None,
    name: str,
    split_by_size: bool = False,
) -> None:
    text = "\n\n".join(u.text for u in units if u.text.strip())
    if not text.strip():
        return
    kinds = {u.kind for u in units}
    if len(kinds) == 1:
        kind = next(iter(kinds))
    elif kinds - {"prose"}:
        kind = "mixed"
    else:
        kind = "prose"
    all_lines = [l for u in units for l in u.lines]
    blocks.append(
        _make_block(
            text=text,
            index=len(blocks),
            lines=all_lines,
            kind=kind,
            atomic=any(u.atomic for u in units) and len(units) == 1,
            path=path,
            parent=parent,
            head=head,
            name=name,
            contains_table=any(u.kind == "table" for u in units),
            contains_math=any(u.kind in ("formula", "t_account") for u in units),
            ends_with_heading=bool(
                all_lines
                and all_lines[-1].ordinal in units[-1].heading_ordinals
            ),
            split_by_size=split_by_size,
        )
    )


def _make_block(
    *,
    text: str,
    index: int,
    lines: list[PageLine],
    kind: str,
    atomic: bool,
    path: str,
    parent: str | None,
    head: HeadingSpan | None,
    name: str,
    contains_table: bool = False,
    contains_math: bool = False,
    ends_with_heading: bool = False,
    split_by_size: bool = False,
    cut_safe: bool | None = None,
) -> StructuralBlock:
    pages = [l.page for l in lines] or [1]
    return StructuralBlock(
        text=text.strip(),
        sequence_index=index,
        page_start=min(pages),
        page_end=max(pages),
        heading_path=path,
        parent_heading_id=parent,
        heading_level=head.level if head else None,
        section_name=name,
        content_kind=kind,
        atomic=atomic,
        word_count=len(text.split()),
        ordinals=tuple(l.ordinal for l in lines),
        contains_table=contains_table,
        contains_math=contains_math,
        ends_with_heading=ends_with_heading,
        split_by_size=split_by_size,
        cut_safe=cut_safe,
    )


def audit_mid_sentence(blocks: list[StructuralBlock]) -> list[int]:
    """Sequence indices of blocks that end mid-sentence. Should be empty."""
    return [
        b.sequence_index
        for b in blocks
        if b.split_by_size
        and b.content_kind == "prose"
        and not b.ends_with_heading
        and ends_mid_sentence(b.text)
    ]
