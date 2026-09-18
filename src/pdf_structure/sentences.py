"""Sentence and paragraph boundaries that survive accounting prose.

The naive ``re.split(r'(?<=[.!?])\\s+', text)`` in :mod:`src.chunking.base` breaks on
every abbreviation. Measured on a representative accounting string it produced 9
"sentences" where there are 6, splitting ``para.``, ``p.a.``, ``Ltd.`` and ``e.g.``.

``pysbd`` fixes most of those but still breaks an abbreviation followed by a digit
(``para. 43``), because that case is genuinely ambiguous. So we mask the known
abbreviation-plus-number forms before segmentation and restore them afterwards.

If ``pysbd`` is not installed we fall back to a guarded regex, which is weaker but
still far better than the unguarded one.
"""

from __future__ import annotations

import re

try:
    import pysbd
    PYSBD_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYSBD_AVAILABLE = False


#: Abbreviations that legitimately end in a period mid-sentence. Ordered longest
#: first so that ``paras.`` is masked before ``para.``.
ABBREVIATIONS: tuple[str, ...] = (
    "paras.", "para.", "p.a.", "e.g.", "i.e.", "etc.", "cf.", "viz.",
    "Ltd.", "plc.", "Inc.", "Co.", "Corp.", "No.", "Nos.", "Vol.",
    "Fig.", "Ch.", "Sched.", "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.",
    "Jan.", "Feb.", "Mar.", "Apr.", "Jun.", "Jul.", "Aug.", "Sep.",
    "Sept.", "Oct.", "Nov.", "Dec.",
)

#: Sentinel that cannot occur in extracted PDF text.
_DOT = "\x00DOT\x00"

# Abbreviation directly followed by a number, e.g. "para. 43", "No. 7", "Vol. 2".
# pysbd splits these; masking the period prevents it.
_ABBR_THEN_NUM = re.compile(
    r"(?i)\b(paras?|nos?|vol|fig|ch|sched|para)\.\s+(?=\d)"
)

# Single capital initial, e.g. "J. Smith".
_INITIAL = re.compile(r"\b([A-Z])\.\s+(?=[A-Z])")

_FALLBACK_SPLIT = re.compile(r"(?<=[.!?])\s+")

# A line ending in a hyphen whose continuation begins lower-case is a word split
# across the line break, not a real hyphen.
_SOFT_HYPHEN_END = re.compile(r"(\w)[-\u2010\u00ad]$")


def reflow(text: str) -> str:
    """Undo PDF soft line wrapping, joining wrapped lines into flowing prose.

    PDF text arrives pre-wrapped at whatever width the page used, so a single
    sentence is spread over several lines. That matters because ``pysbd`` treats a
    newline as a sentence boundary: on extracted course prose it turned 8 real
    sentences into 26 fragments such as ``'See IAS 16'`` and ``'Contact'``.
    Reflowing first is what makes the no-mid-sentence guarantee achievable.

    Blank lines are preserved as paragraph separators. Structural lines -- markdown
    table rows, fenced blocks and ATX headings -- are never joined, because their
    line breaks are meaningful.
    """
    if not text:
        return text

    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            out.append(" ".join(buffer))
            buffer.clear()

    def structural(line: str) -> bool:
        stripped = line.strip()
        return (
            stripped.startswith("|")
            or stripped.startswith("```")
            or stripped.startswith("#")
            or stripped.startswith(">")
            or bool(re.match(r"^\s*([-*+]|\d+[.)])\s", line))
        )

    for raw in text.splitlines():
        stripped = raw.strip()

        if not stripped:
            flush()
            out.append("")
            continue

        if structural(raw):
            flush()
            out.append(raw)
            continue

        if buffer:
            previous = buffer[-1]
            match = _SOFT_HYPHEN_END.search(previous)
            if match and stripped[:1].islower():
                # Word split across the break: rejoin without a space.
                buffer[-1] = previous[: match.start(1) + 1]
                buffer[-1] = buffer[-1] + stripped
                continue

        buffer.append(stripped)

    flush()

    # Collapse any run of blank lines to a single separator.
    result: list[str] = []
    for line in out:
        if line == "" and result and result[-1] == "":
            continue
        result.append(line)
    return "\n".join(result).strip()


def _mask(text: str) -> str:
    masked = text
    for abbr in ABBREVIATIONS:
        masked = masked.replace(abbr, abbr.replace(".", _DOT))
    masked = _ABBR_THEN_NUM.sub(lambda m: f"{m.group(1)}{_DOT} ", masked)
    masked = _INITIAL.sub(lambda m: f"{m.group(1)}{_DOT} ", masked)
    return masked


def _unmask(text: str) -> str:
    return text.replace(_DOT, ".")


def split_sentences(text: str, *, do_reflow: bool = True) -> list[str]:
    """Split ``text`` into sentences without breaking on abbreviations.

    Args:
        text: input text.
        do_reflow: undo PDF soft line wrapping first. Leave enabled for text that
            came from a PDF; disable when the newlines are already meaningful.
    """
    if not text or not text.strip():
        return []

    prepared = reflow(text) if do_reflow else text
    # pysbd treats a newline as a boundary, so within a paragraph any remaining
    # single newline is flattened to a space.
    prepared = re.sub(r"(?<!\n)\n(?!\n)", " ", prepared)

    masked = _mask(prepared)

    if PYSBD_AVAILABLE:
        segmenter = pysbd.Segmenter(language="en", clean=False)
        pieces = segmenter.segment(masked)
    else:  # pragma: no cover - exercised only without pysbd
        pieces = _FALLBACK_SPLIT.split(masked)

    out = []
    for piece in pieces:
        restored = _unmask(str(piece)).strip()
        if restored:
            out.append(restored)
    return out


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, preserving markdown block integrity.

    Fenced code blocks and pipe-table runs are kept whole: a blank line inside a
    fence is not a paragraph boundary.
    """
    if not text:
        return []

    paragraphs: list[str] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        if buffer:
            joined = "\n".join(buffer).strip()
            if joined:
                paragraphs.append(joined)
            buffer.clear()

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("```"):
            in_fence = not in_fence
            buffer.append(line)
            if not in_fence:
                flush()
            continue

        if in_fence:
            buffer.append(line)
            continue

        if not stripped:
            flush()
            continue

        buffer.append(line)

    flush()
    return paragraphs


#: Trailing enumeration tokens: a bare list number or a bullet/tick glyph left at
#: the end of a run. Generic layout artefacts, not sentence content.
_TRAILING_ENUMERATION = re.compile(
    r"(?:[\s\u00a0]*(?:\d{1,2}|[\u2713\u2714\u2717\u2718\u25cb\u25cf\u2022]))+$"
)


def ends_mid_sentence(text: str) -> bool:
    """True when ``text`` looks like interrupted prose.

    A heuristic, and deliberately conservative. Long documents end blocks on all
    sorts of things that carry no full stop and are nonetheless complete: bullet
    lists, enumerated labels, icon legends, table rows, headings. It still
    over-reports on non-prose content, which is why
    :func:`verify_sentence_integrity` rather than this function is the authority
    on whether a cut was safe.
    """
    stripped = text.rstrip()
    if not stripped:
        return False

    last = stripped.splitlines()[-1].strip()
    if not last:
        return False

    # Structural tails are complete by construction.
    if last.startswith(("|", "```", "#", ">")):
        return False
    if re.match(r"^\s*([-*+\u2022]|\d+[.)])\s", last):
        return False
    # A lead-in ending in a colon or semicolon introduces what follows.
    if last.endswith((":", ";")):
        return False

    # Strip trailing enumeration and glyphs before judging the tail.
    last = _TRAILING_ENUMERATION.sub("", last).rstrip()
    if not last:
        return False
    if last.endswith((":", ";")):
        return False

    # Bare numbers or number runs.
    if re.match(r"^[\d\s.,)(]+$", last):
        return False
    # Very short fragments are labels, not sentences.
    if len(last.split()) <= 3:
        return False
    # No letters at all: a glyph or rule.
    if sum(1 for c in last if c.isalpha()) < 2:
        return False

    if last.endswith((".", "!", "?", '"', "'", ")", "]", "\u2026")):
        # Guard against an abbreviation being read as a terminator.
        for abbr in ABBREVIATIONS:
            if last.endswith(abbr):
                return True
        return False
    return True


def verify_cut_boundaries(original: str, pieces: list[str]) -> list[int]:
    """Check that every internal cut in ``pieces`` lands on a sentence boundary.

    This is the real invariant. An earlier version of this check compared each
    piece against its own re-tokenisation, which is trivially equal for any text
    and therefore proved nothing. The meaningful question is different: given the
    original text, does each boundary *between* pieces coincide with a sentence
    end in that original?

    Character offsets are computed with whitespace removed, so that re-joining
    cannot shift a boundary through added or lost spaces.

    Args:
        original: the text that was split.
        pieces: the resulting pieces, in order.

    Returns:
        Indices of pieces whose trailing boundary is not a sentence end. The final
        piece is never reported: its end is the end of the input.
    """
    if len(pieces) < 2:
        return []

    sentence_ends: set[int] = set()
    running = 0
    for sentence in split_sentences(original, do_reflow=False):
        running += len(_norm(sentence))
        sentence_ends.add(running)

    offenders: list[int] = []
    running = 0
    for index, piece in enumerate(pieces[:-1]):
        running += len(_norm(piece))
        if running not in sentence_ends:
            offenders.append(index)
    return offenders


def verify_sentence_integrity(pieces: list[str]) -> list[int]:
    """Deprecated shim. Use :func:`verify_cut_boundaries`.

    Retained only so existing callers keep working; it reconstructs the original
    by concatenation, which is valid when ``pieces`` came from splitting one text.
    """
    return verify_cut_boundaries(" ".join(pieces), pieces)


def _norm(text: str) -> str:
    """Whitespace-free form.

    The invariant being checked is that no characters were lost at a cut, so all
    whitespace is removed before comparison. Re-joining tokenised sentences can
    legitimately move a space -- ``pysbd`` places a full stop before a closing
    quote, so ``clouds.'`` round-trips as ``clouds. '`` -- and that is not a
    truncation.
    """
    return re.sub(r"\s+", "", text)
