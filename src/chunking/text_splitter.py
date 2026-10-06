"""Structure-aware text splitting that works on character spans.

Every chunker that slices free text uses this module, so they all share one set of
guarantees:

* **Chunks are exact substrings.** A chunk is ``text[start:end]``. Line breaks, list
  indentation, table rows and code fences survive untouched, and ``start``/``end``
  point into the text that was split.
* **Structure decides where to cut.** Text is broken into units: whole fenced code
  blocks, single Markdown table rows, headings, lines, and -- only for a line that is
  itself too long -- sentences, then word windows. When a chunk is full the splitter
  cuts at the strongest boundary available (heading, blank line, line, sentence),
  never inside a code fence or a table row, and never between a heading and the text
  it introduces.
* **Always terminates.** Every chunk contains at least one unit the previous chunk did
  not, so overlap can never stall the loop, whatever ``overlap`` is.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from dataclasses import dataclass

# Boundary strength *before* a unit: how good a place it is to start a new chunk.
WORD = 0
SENTENCE = 1
TABLE_ROW = 1
LINE = 2
BLOCK = 3
HEADING = 4

#: Minimum fill (fraction of the target) a chunk must reach before the splitter will
#: cut at a boundary of this strength. Strong boundaries are worth a shorter chunk.
_MIN_FILL = {HEADING: 0.2, BLOCK: 0.4, LINE: 0.6, SENTENCE: 0.6, WORD: 0.0}

#: Units never repeated as overlap: a whole code block, table or figure line would
#: be duplicated in the next chunk.
_NO_OVERLAP_KINDS = frozenset({"code", "table", "pipe_table", "html_table", "figure"})

_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class Unit:
    """Smallest piece of text the splitter will not cut inside."""

    start: int
    end: int
    words: int
    strength: int
    kind: str = "text"  # text | heading | code | table_row


@dataclass(frozen=True)
class Heading:
    """A Markdown heading found in the text."""

    start: int
    level: int
    title: str


def _lines(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    """Yield ``(line_start, line_end)`` for each line in ``text[start:end]`` (no newline)."""
    pos = start
    while pos < end:
        nl = text.find("\n", pos, end)
        if nl == -1:
            yield pos, end
            return
        yield pos, nl
        pos = nl + 1


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _word_count(text: str, start: int, end: int) -> int:
    return len(text[start:end].split())


def _split_long_line(
    text: str, start: int, end: int, max_words: int, strength: int
) -> list[Unit]:
    """Sentences of an over-long line; word windows for an over-long sentence."""
    units: list[Unit] = []
    sent_start = start
    pieces: list[tuple[int, int]] = []
    for match in _SENTENCE_END_RE.finditer(text, start, end):
        pieces.append((sent_start, match.start()))
        sent_start = match.end()
    pieces.append((sent_start, end))

    first = True
    for s, e in pieces:
        s, e = _strip_span(text, s, e)
        if s >= e:
            continue
        words = _word_count(text, s, e)
        if words <= max_words:
            units.append(Unit(s, e, words, strength if first else SENTENCE))
            first = False
            continue
        spans = [m.span() for m in _WORD_RE.finditer(text, s, e)]
        for i in range(0, len(spans), max_words):
            window = spans[i : i + max_words]
            units.append(
                Unit(window[0][0], window[-1][1], len(window), strength if first else WORD)
            )
            first = False
    return units


def sentence_units(
    text: str, start: int, end: int, max_words: int, strength: int = BLOCK
) -> list[Unit]:
    """``text[start:end]`` as sentence units (word windows for an over-long sentence).

    The first unit gets ``strength``; later ones are sentence boundaries.
    """
    return _split_long_line(text, start, end, max(1, max_words), strength)


def segment(text: str, max_words: int, start: int = 0, end: int | None = None) -> list[Unit]:
    """Break ``text[start:end]`` into units no larger than ``max_words`` where possible.

    Code fences and table rows are atomic even when larger than ``max_words``: they
    are never cut.
    """
    end = len(text) if end is None else end
    max_words = max(1, max_words)
    units: list[Unit] = []
    pending = BLOCK  # strength of the boundary before the next unit
    fence: tuple[str, int] | None = None  # (marker, start offset)

    for line_start, line_end in _lines(text, start, end):
        line = text[line_start:line_end]

        if fence is not None:
            marker, fence_start = fence
            stripped = line.strip()
            if stripped.startswith(marker[0] * len(marker)) and set(stripped) <= {marker[0]}:
                units.append(
                    Unit(
                        fence_start,
                        line_end,
                        _word_count(text, fence_start, line_end),
                        pending,
                        "code",
                    )
                )
                fence = None
                pending = LINE
            continue

        if not line.strip():
            pending = max(pending, BLOCK)
            continue

        fence_match = _FENCE_RE.match(line)
        if fence_match:
            fence = (fence_match.group(1), line_start)
            continue

        s, e = _strip_span(text, line_start, line_end)
        if _HEADING_RE.match(line):
            units.append(Unit(s, e, _word_count(text, s, e), HEADING, "heading"))
            pending = LINE
            continue

        if _TABLE_ROW_RE.match(line):
            in_table = bool(units) and units[-1].kind == "table_row" and pending == LINE
            units.append(
                Unit(s, e, _word_count(text, s, e), TABLE_ROW if in_table else pending, "table_row")
            )
            pending = LINE
            continue

        words = _word_count(text, s, e)
        if words > max_words:
            units.extend(_split_long_line(text, s, e, max_words, pending))
        else:
            units.append(Unit(s, e, words, pending))
        pending = LINE

    if fence is not None:  # unterminated fence: keep the rest together
        fence_start = fence[1]
        s, e = _strip_span(text, fence_start, end)
        if s < e:
            units.append(Unit(s, e, _word_count(text, s, e), pending, "code"))
    return units


def _choose_break(units: list[Unit], s: int, fresh: int, i: int, target: int) -> int:
    """Pick where to end a chunk that starts at ``s`` and overflows at unit ``i``.

    Candidates are boundaries before units ``fresh+1 .. i`` so the chunk always keeps
    at least one unit the previous chunk did not have.
    """
    cumulative = 0
    best = i
    best_key: tuple[int, int] | None = None
    sizes = [0] * (i + 1)
    for k in range(s, i):
        cumulative += units[k].words
        sizes[k + 1] = cumulative
    for c in range(max(fresh + 1, s + 1), i + 1):
        if units[c - 1].kind == "heading":
            continue  # a heading stays with the text it introduces
        strength = units[c].strength if c < len(units) else BLOCK
        fill = sizes[c] / target if target else 1.0
        if fill < _MIN_FILL.get(strength, 0.6):
            continue
        key = (strength, c)
        if best_key is None or key > best_key:
            best_key, best = key, c
    if best_key is None:
        # No boundary is good enough: cut as late as possible, but not after a heading.
        best = i
        while best - 1 > max(fresh, s) and units[best - 1].kind == "heading":
            best -= 1
    return best


def pack(
    units: list[Unit], target: int, overlap: int = 0, *, prefer_structure: bool = True
) -> list[tuple[int, int]]:
    """Group units into chunks of about ``target`` words; return index ranges.

    Args:
        units: output of :func:`segment`.
        target: maximum words per chunk (a single atomic unit may exceed it).
        overlap: words repeated from the end of one chunk at the start of the next.
            Whole units only, never across a heading, always less than the chunk.
        prefer_structure: cut at the strongest nearby boundary; when false, cut as
            late as possible (plain fixed-size windows on unit boundaries).

    Returns:
        ``[(first_unit, end_unit), ...]`` half-open index ranges.
    """
    target = max(1, target)
    overlap = max(0, min(overlap, target - 1))
    n = len(units)
    ranges: list[tuple[int, int]] = []
    s = fresh = 0
    while fresh < n:
        total = 0
        i = s
        has_body = False  # a non-heading unit beyond the overlap is in the chunk
        while i < n and (
            i <= fresh
            or total + units[i].words <= target
            # A chunk that so far holds only headings takes the next unit even if
            # it overflows; otherwise the overflow is cut before the heading.
            or (units[i - 1].kind == "heading" and not has_body)
        ):
            total += units[i].words
            if i >= fresh and units[i].kind != "heading":
                has_body = True
            i += 1
        if i >= n:
            b = n
        elif prefer_structure:
            b = _choose_break(units, s, fresh, i, target)
        else:
            b = i
        ranges.append((s, b))
        if b >= n:
            break
        nxt = b
        if overlap and units[b].strength < HEADING:
            carried = 0
            while nxt - 1 > s:
                unit = units[nxt - 1]
                if carried + unit.words > overlap or unit.kind in _NO_OVERLAP_KINDS:
                    break
                carried += unit.words
                nxt -= 1
                if unit.kind == "heading" or unit.strength >= HEADING:
                    break
        s, fresh = nxt, b
    return ranges


def split_spans(
    text: str,
    target_words: int,
    overlap_words: int = 0,
    *,
    start: int = 0,
    end: int | None = None,
    prefer_structure: bool = True,
) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into ``(start, end)`` character spans.

    Each span is trimmed of surrounding whitespace, so ``text[s:e]`` is the chunk.
    """
    units = segment(text, target_words, start, end)
    return [
        (units[a].start, units[b - 1].end)
        for a, b in pack(units, target_words, overlap_words, prefer_structure=prefer_structure)
    ]


def find_headings(text: str) -> list[Heading]:
    """Markdown headings in ``text`` that are not inside a fenced code block."""
    headings: list[Heading] = []
    fence: str | None = None
    for line_start, line_end in _lines(text, 0, len(text)):
        line = text[line_start:line_end]
        if fence is not None:
            stripped = line.strip()
            if stripped and stripped.startswith(fence) and set(stripped) <= {fence[0]}:
                fence = None
            continue
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            fence = fence_match.group(1)
            continue
        match = _HEADING_RE.match(line)
        if match and match.group(2):
            offset = line_start + (len(line) - len(line.lstrip()))
            headings.append(Heading(offset, len(match.group(1)), match.group(2).strip()))
    return headings


class HeadingIndex:
    """Answers "which section is this offset in?" for chunk metadata."""

    def __init__(self, text: str) -> None:
        self.headings = find_headings(text)
        self._starts = [h.start for h in self.headings]
        self._paths: list[list[str]] = []
        stack: list[Heading] = []
        for heading in self.headings:
            while stack and stack[-1].level >= heading.level:
                stack.pop()
            stack.append(heading)
            self._paths.append([h.title for h in stack])

    def for_span(self, text: str, start: int, end: int) -> tuple[Heading | None, list[str]]:
        """Section of a chunk: the heading in effect after any headings it opens with.

        A chunk that starts ``# Guide`` / ``## Install`` / body belongs to "Install".
        """
        pos = start
        idx = bisect.bisect_left(self._starts, start)
        while idx < len(self._starts) and self._starts[idx] == pos and pos < end:
            nl = text.find("\n", pos, end)
            if nl == -1:
                break
            pos = nl + 1
            while pos < end and text[pos].isspace():
                pos += 1
            idx += 1
        return self.at(min(pos, max(start, end - 1)))

    def at(self, offset: int) -> tuple[Heading | None, list[str]]:
        """The heading in effect at ``offset`` and its breadcrumb."""
        idx = bisect.bisect_right(self._starts, offset) - 1
        if idx < 0:
            return None, []
        return self.headings[idx], self._paths[idx]

    def sections(self, max_level: int = 6) -> list[tuple[int, int, Heading | None]]:
        """``(start, end, heading)`` spans split at headings of level <= ``max_level``.

        Text before the first heading forms a section with ``heading=None``. A section
        holding nothing but its heading line is merged into the next section, so a
        heading is never separated from the content that follows it.
        """
        cuts = [h for h in self.headings if h.level <= max_level]
        bounds: list[tuple[int, Heading | None]] = [(0, None)] + [(h.start, h) for h in cuts]
        spans: list[tuple[int, int, Heading | None]] = []
        for i, (start, heading) in enumerate(bounds):
            end = bounds[i + 1][0] if i + 1 < len(bounds) else None
            spans.append((start, -1 if end is None else end, heading))
        return spans


def section_spans(
    text: str, max_level: int = 6
) -> list[tuple[int, int, Heading | None]]:
    """Split ``text`` into heading-bounded sections; see :meth:`HeadingIndex.sections`."""
    index = HeadingIndex(text)
    raw = index.sections(max_level)
    result: list[tuple[int, int, Heading | None]] = []
    carry_start: int | None = None
    carry_heading: Heading | None = None
    for start, end, heading in raw:
        end = len(text) if end == -1 else end
        s, e = _strip_span(text, start, end)
        if carry_start is not None:
            s, heading = carry_start, carry_heading
            carry_start = None
        if s >= e:
            continue
        if heading is not None and "\n" not in text[s:e]:
            # Heading-only section: attach it to the next one.
            carry_start, carry_heading = s, heading
            continue
        result.append((s, e, heading))
    if carry_start is not None:
        s, e = _strip_span(text, carry_start, len(text))
        if s < e:
            result.append((s, e, carry_heading))
    return result
