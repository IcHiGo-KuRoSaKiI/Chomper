"""Layout PDF chunker: the layout-model Markdown, split by structure.

:class:`~src.extractors.pdf_extractor.PDFExtractor` (``pymupdf-layout`` backend)
already turns a PDF into Markdown with real headings, joined paragraphs, nested
lists, tables with header rows and ``![caption](image:<id>)`` figure markers, and
drops running headers and footers that repeat. This chunker splits *that* text --
the same text ``chomper.parse()`` returns -- with the structure-aware splitter in
:mod:`src.chunking.text_splitter`:

* Hard section cuts at headings of level <= ``section_level`` (default 2); deeper
  headings are preferred cut points inside a section.
* A table is one unit: it is never cut unless it alone is larger than the chunk
  size. Then it is cut between rows, and every continuation chunk starts with the
  table's header rows again (``metadata["table_header_repeated"]``). Pipe tables and
  single-line HTML tables (``table_format="html"``) are both handled.
* A line holding a figure marker is never cut.
* ``start_char``/``end_char`` are offsets into ``parse()`` text, and
  ``text == parse_text[start_char:end_char]`` for every chunk except a table
  continuation, whose text additionally carries the repeated header (and, for an
  HTML table, the ``<table>``/``</table>`` wrapper).
* ``page``/``pages`` come from per-page offsets of the joined page Markdown.
* Running heads the extractor kept (a line at the top or bottom of many pages, such
  as ``## Dept. of Health and Human Services`` or a bare page number) neither cut
  a chunk nor enter ``heading_path``. They stay in the chunk text, which must
  remain a substring of ``parse()`` text.
* The extractor joins pages, and columns, with a blank line even when a sentence
  runs on. A sentence interrupted that way is kept in one unit across the break,
  so the splitter does not mistake the break for a paragraph end and cut it.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, replace
from typing import Any

from ...models.document import Chunk, RawDocument
from ...pdf_structure.sentences import ends_mid_sentence
from ..base import BaseChunker
from ..text_splitter import (
    BLOCK,
    HEADING,
    SENTENCE,
    HeadingIndex,
    Unit,
    pack,
    section_spans,
    segment,
    sentence_units,
)

#: A line that is (or holds) a figure marker written by the extractor.
_MARKER_LINE_RE = re.compile(r"^[^\n]*!\[[^\]\n]*\]\(image:[^)\s]+\)[^\n]*$", re.M)
_MARKER_ID_RE = re.compile(r"!\[[^\]\n]*\]\(image:([^)\s]+)\)")
_PIPE_ROW_RE = re.compile(r"^\s*\|")
_PIPE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
_HTML_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
#: Trailing inline markup (emphasis, underline tags) ignored when judging a line end.
_TRAILING_MARKUP_RE = re.compile(r"(?:</?[a-z]+>|[*_`\s])+$", re.I)
_TAG_RE = re.compile(r"</?[a-z]+>", re.I)
#: A line that is structure, not running prose.
_STRUCTURAL_LINE_RE = re.compile(r"^\s*(?:#|\||<|!\[|[-*+\u2022]\s|\d{1,3}[.)]\s|>|```|~~~)")


@dataclass(frozen=True)
class _Decor:
    """Text added around a table piece so a split table stays a valid table."""

    prefix: str = ""
    suffix: str = ""


@dataclass(frozen=True)
class PageSpan:
    """Where one page's Markdown sits in the joined document text."""

    start: int
    end: int
    page: int


def page_spans(raw_doc: RawDocument) -> list[PageSpan]:
    """Character span of each page's Markdown inside ``raw_doc.text``.

    The extractor joins the stripped page texts with blank lines, so each page is
    found in order with a forward search; a page that cannot be located (an
    extractor that rewrote text after joining) is skipped and offsets in it are
    attributed to the previous page.
    """
    text = raw_doc.text or ""
    spans: list[PageSpan] = []
    cursor = 0
    for number, page in enumerate((raw_doc.structure or {}).get("pages") or [], start=1):
        page_text = (page.get("markdown_text") or "").strip()
        if not page_text:
            continue
        found = text.find(page_text, cursor)
        if found < 0:
            continue
        end = found + len(page_text)
        spans.append(PageSpan(found, end, int(page.get("page_number", number))))
        cursor = end
    return spans


#: Running-head candidates: at most this many words, and not table/figure markup.
_RUNNING_MAX_WORDS = 12
_RUNNING_EXCLUDE_RE = re.compile(r"^\s*(?:\||<|!\[)")


def _running_key(line: str) -> str:
    line = re.sub(r"^[#>\s*_]+|[\s*_]+$", "", _TAG_RE.sub("", line))
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line)).strip().lower()


def running_head_lines(
    text: str,
    spans: list[PageSpan],
    *,
    edge_lines: int = 2,
    edge_share: float = 0.15,
    heading_share: float = 0.25,
) -> list[tuple[int, int]]:
    """Spans of running heads and folios left in the text.

    Two signals, digits ignored when comparing text:

    * a short line among the first or last ``edge_lines`` lines of a page whose
      text sits at a page edge on at least three pages and ``edge_share`` of pages;
    * a Markdown heading whose text recurs on at least three pages and
      ``heading_share`` of pages wherever it sits (reading order can put a running
      head in the middle of a page's text; a real section heading does not recur
      on a quarter of all pages).
    """
    edge_hits: dict[str, list[tuple[int, int, int]]] = {}
    heading_hits: dict[str, list[tuple[int, int, int]]] = {}
    for span in spans:
        lines: list[tuple[int, int]] = []
        pos = span.start
        for raw in text[span.start : span.end].split("\n"):
            if raw.strip():
                lines.append((pos, pos + len(raw)))
            pos += len(raw) + 1
        edges = set(lines[:edge_lines] + lines[max(edge_lines, len(lines) - edge_lines) :])
        for start, end in lines:
            line = text[start:end]
            if _RUNNING_EXCLUDE_RE.match(line) or len(line.split()) > _RUNNING_MAX_WORDS:
                continue
            key = _running_key(line)
            if not key:
                continue
            if (start, end) in edges:
                edge_hits.setdefault(key, []).append((start, end, span.page))
            if line.lstrip().startswith("#"):
                heading_hits.setdefault(key, []).append((start, end, span.page))

    found: set[tuple[int, int]] = set()
    for table, share in ((edge_hits, edge_share), (heading_hits, heading_share)):
        needed = max(3, share * len(spans))
        for hits in table.values():
            if len({page for _, _, page in hits}) >= needed:
                found.update((start, end) for start, end, _ in hits)
    return sorted(found)


def interrupting_headings(text: str) -> list[tuple[int, int]]:
    """Heading lines that sit inside a sentence, e.g. ``## Box 4 —continued``.

    The prose before the heading ends mid-sentence and the prose after it starts
    with a lowercase letter: the heading is a continuation label (or a reading-order
    artefact), not the start of a section.
    """
    found: list[tuple[int, int]] = []
    lines: list[tuple[int, int]] = []
    pos = 0
    for raw in text.split("\n"):
        if raw.strip():
            lines.append((pos, pos + len(raw)))
        pos += len(raw) + 1
    for i in range(1, len(lines) - 1):
        start, end = lines[i]
        if not text[start:end].lstrip().startswith("#"):
            continue
        before, after = text[lines[i - 1][0] : lines[i - 1][1]], text[lines[i + 1][0] : lines[i + 1][1]]
        head = after.lstrip()
        if (
            head[:1].islower()
            and not _STRUCTURAL_LINE_RE.match(after)
            and prose_ends_mid_sentence(before)
        ):
            found.append((start, end))
    return found


def mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """``text`` with each span blanked out (same length, so offsets still match)."""
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        parts.append(" " * (end - start))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def prose_ends_mid_sentence(text: str) -> bool:
    """:func:`ends_mid_sentence` on ``text`` with inline markup removed, so
    ``... go to _<u>IRS.gov</u>_ <u>.</u>`` counts as finished.
    """
    tail = text.rstrip().rsplit("\n", 1)[-1]
    if _STRUCTURAL_LINE_RE.match(tail):
        return False
    return ends_mid_sentence(_TRAILING_MARKUP_RE.sub("", _TAG_RE.sub("", tail)))


def _is_continuation(text: str, prev: Unit, unit: Unit) -> bool:
    """True when the blank line before ``unit`` falls inside a sentence."""
    if not (BLOCK <= unit.strength < HEADING) or unit.kind != "text" or prev.kind != "text":
        return False
    head = text[unit.start : unit.end].split("\n", 1)[0]
    if _STRUCTURAL_LINE_RE.match(head):
        return False
    return prose_ends_mid_sentence(text[prev.start : prev.end])


def join_continuations(text: str, units: list[Unit], max_words: int) -> list[Unit]:
    """Keep sentences that run over a page or column break in one unit.

    A page or column break comes out of the extractor as a blank line even when the
    sentence carries on (``... must file Form 943 with`` / ``Schedule R ...``). When
    the text before such a blank line ends mid-sentence and the text after it is
    plain prose, both sides are broken into sentences and the interrupted sentence
    becomes one unit spanning the break, so no chunk can end inside it, while the
    other sentence boundaries stay available as cut points.
    """
    out: list[Unit] = []
    for unit in units:
        if not out or not _is_continuation(text, out[-1], unit):
            out.append(unit)
            continue
        prev = out.pop()
        before = sentence_units(text, prev.start, prev.end, max_words, prev.strength)
        after = sentence_units(text, unit.start, unit.end, max_words, SENTENCE)
        if not before or not after:  # pragma: no cover - spans are never blank
            out.extend([prev, unit])
            continue
        tail, head = before[-1], after[0]
        joined = Unit(tail.start, head.end, tail.words + head.words, tail.strength, "text")
        out.extend([*before[:-1], joined, *after[1:]])
    return out


def pages_for_span(spans: list[PageSpan], starts: list[int], start: int, end: int) -> list[int]:
    """Page numbers whose text overlaps ``[start, end)`` (at least the page at ``start``)."""
    if not spans:
        return []
    first = max(0, bisect.bisect_right(starts, start) - 1)
    pages = [
        span.page for span in spans[first:] if span.start < end and span.end > start
    ]
    if not pages:
        pages = [spans[first].page]
    return sorted(set(pages))


class LayoutPDFChunker(BaseChunker):
    """Chunk a PDF's layout Markdown on structure, with page provenance.

    Args:
        target_size: maximum words per chunk (a table or figure line larger than this
            is kept whole, or for a table split between rows).
        overlap: words repeated from the end of the previous chunk (whole lines or
            sentences; never across a heading).
        preserve_context: kept for interface compatibility.
        section_level: deepest heading level that always starts a new chunk.
        soft_min_words: a section shorter than this is merged into the next one
            when both fit in one chunk (a title page line, a heading with one line).
    """

    def __init__(
        self,
        target_size: int = 1000,
        overlap: int = 100,
        preserve_context: bool = True,
        *,
        section_level: int = 2,
        soft_min_words: int = 40,
    ) -> None:
        super().__init__(target_size, overlap, preserve_context)
        self.section_level = section_level
        self.soft_min_words = soft_min_words

    def _sections(self, view: str, target: int) -> list[tuple[int, int]]:
        sections = [(s, e) for s, e, _ in section_spans(view, self.section_level)]
        return _merge_small_sections(view, sections, target, self.soft_min_words)

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """Chunk ``raw_doc`` (a PDFExtractor result); offsets point into ``raw_doc.text``."""
        text = raw_doc.text or ""
        if not text.strip():
            return []
        target, over = self._resolve(None, None)
        spans = page_spans(raw_doc)
        starts = [span.start for span in spans]
        # Structure (cuts, headings, units) comes from a copy with running heads
        # blanked; chunk text always comes from ``text``.
        running = running_head_lines(text, spans)
        view = mask_spans(text, running)
        view = mask_spans(view, interrupting_headings(view))
        index = HeadingIndex(view)
        method = (raw_doc.metadata or {}).get("extraction_method")

        chunks: list[Chunk] = []
        for sec_start, sec_end in self._sections(view, target):
            units = join_continuations(view, segment(view, target, sec_start, sec_end), target)
            units, decor = protect_units(view, units, target)
            for a, b in pack(units, target, over):
                s, e = units[a].start, units[b - 1].end
                prefix = decor[a].prefix if a in decor else ""
                suffix = decor[b - 1].suffix if (b - 1) in decor else ""
                body = text[s:e]
                heading, path = index.for_span(view, s, e)
                pages = pages_for_span(spans, starts, s, e)
                image_ids = _MARKER_ID_RE.findall(body)
                tables = _count_tables(body)
                metadata: dict[str, Any] = {
                    "section_name": heading.title if heading else None,
                    "heading_path": " > ".join(path),
                    "heading_level": heading.level if heading else 0,
                    "page": pages[0] if pages else None,
                    "pages": pages,
                    "page_number": pages[0] if pages else None,
                    "page_span": [pages[0], pages[-1]] if pages else None,
                    "has_table": tables > 0,
                    "table_count": tables,
                    "table_header_repeated": bool(prefix),
                    "has_images": bool(image_ids),
                    "image_ids": image_ids,
                    "section_type": "table" if tables else "text",
                    "chunk_strategy": "layout",
                    "offsets": "parse_text",
                }
                if running and any(s < re_ and re_s < e for re_s, re_ in running):
                    metadata["has_running_heads"] = True
                if method:
                    metadata["extraction_method"] = method
                chunks.append(
                    Chunk(
                        chunk_id=len(chunks),
                        text=f"{prefix}{body}{suffix}",
                        start_char=s,
                        end_char=e,
                        metadata=metadata,
                    )
                )
        return chunks


def _words(text: str, start: int, end: int) -> int:
    return len(text[start:end].split())


def _merge_small_sections(
    text: str, sections: list[tuple[int, int]], target: int, soft_min: int
) -> list[tuple[int, int]]:
    """Merge a section under ``soft_min`` words into the next while both fit ``target``."""
    merged: list[tuple[int, int]] = []
    for start, end in sections:
        if merged:
            prev_start, prev_end = merged[-1]
            if (
                _words(text, prev_start, prev_end) < soft_min
                and _words(text, prev_start, end) <= target
            ):
                merged[-1] = (prev_start, end)
                continue
        merged.append((start, end))
    return merged


def _count_tables(body: str) -> int:
    """Pipe tables (header + separator) plus HTML tables in ``body``."""
    lines = body.splitlines()
    pipe = sum(
        1
        for i in range(1, len(lines))
        if _PIPE_SEPARATOR_RE.match(lines[i]) and _PIPE_ROW_RE.match(lines[i - 1])
    )
    return pipe + body.lower().count("<table")


# --------------------------------------------------------------------- protection
def _merge(text: str, units: list[Unit], first: int, last: int, kind: str) -> Unit:
    """One atomic unit covering ``units[first..last]``."""
    start, end = units[first].start, units[last].end
    return Unit(start, end, len(text[start:end].split()), units[first].strength, kind)


def protect_units(
    text: str, units: list[Unit], target: int
) -> tuple[list[Unit], dict[int, _Decor]]:
    """Make tables and figure-marker lines atomic; split oversized tables by rows.

    Returns the new unit list and, by unit index, the header/wrapper text a table
    continuation piece needs.
    """
    if not units:
        return units, {}
    # Search from the start of the first line: with re.M, ``^`` does not match at
    # an arbitrary ``pos``.
    lo, hi = text.rfind("\n", 0, units[0].start) + 1, units[-1].end
    # (start, end, kind) regions that must not be cut, in text order.
    regions: list[tuple[int, int, str]] = []
    for match in _HTML_TABLE_RE.finditer(text, lo, hi):
        regions.append((match.start(), match.end(), "html_table"))
    for match in _MARKER_LINE_RE.finditer(text, lo, hi):
        if not any(s <= match.start() < e for s, e, _ in regions):
            regions.append((match.start(), match.end(), "figure"))
    # Pipe tables: runs of table-row units with no blank line between them.
    i = 0
    while i < len(units):
        if units[i].kind == "table_row":
            j = i
            while j + 1 < len(units) and units[j + 1].kind == "table_row" and units[j + 1].strength < BLOCK:
                j += 1
            regions.append((units[i].start, units[j].end, "pipe_table"))
            i = j + 1
        else:
            i += 1
    regions.sort()

    out: list[Unit] = []
    decor: dict[int, _Decor] = {}
    k = 0
    for start, end, kind in regions:
        while k < len(units) and units[k].end <= start:
            out.append(units[k])
            k += 1
        if k >= len(units) or units[k].start >= end:
            continue  # already absorbed by an earlier region
        first = k
        while k < len(units) and units[k].start < end:
            k += 1
        last = k - 1
        merged = _merge(text, units, first, last, kind)
        if kind == "pipe_table" and merged.words > target:
            pieces = _split_pipe_table(text, units[first : last + 1], target)
        elif kind == "html_table" and merged.words > target:
            pieces = _split_html_table(text, merged, target)
        else:
            pieces = [(merged, None)]
        for unit, piece_decor in pieces:
            if piece_decor is not None:
                decor[len(out)] = piece_decor
            out.append(unit)
    out.extend(units[k:])
    return out, decor


def _split_pipe_table(
    text: str, rows: list[Unit], target: int
) -> list[tuple[Unit, _Decor | None]]:
    """Row groups of an oversized pipe table; continuations repeat the header rows."""
    header_rows = 0
    if len(rows) >= 2 and _PIPE_SEPARATOR_RE.match(text[rows[1].start : rows[1].end]):
        header_rows = 2
    header = "\n".join(text[r.start : r.end] for r in rows[:header_rows])
    header_words = len(header.split())
    budget = max(1, target - header_words)

    groups: list[list[Unit]] = []
    current: list[Unit] = list(rows[:header_rows])
    words = sum(r.words for r in current)
    limit = target
    for row in rows[header_rows:]:
        if words + row.words > limit and len(current) > (header_rows if not groups else 0):
            groups.append(current)
            current, words, limit = [], 0, budget
        current.append(row)
        words += row.words
    if current:
        groups.append(current)

    pieces: list[tuple[Unit, _Decor | None]] = []
    for n, group in enumerate(groups):
        start, end = group[0].start, group[-1].end
        strength = group[0].strength if n == 0 else rows[-1].strength
        unit = Unit(start, end, len(text[start:end].split()), strength, "table")
        repeat = n > 0 and header_rows > 0
        pieces.append((unit, _Decor(prefix=f"{header}\n") if repeat else None))
    return pieces


def _split_html_table(
    text: str, table: Unit, target: int
) -> list[tuple[Unit, _Decor | None]]:
    """Row groups of an oversized HTML table, each wrapped as a complete table."""
    rows = list(_HTML_ROW_RE.finditer(text, table.start, table.end))
    if len(rows) < 2:
        return [(replace(table, kind="table"), None)]
    open_tag = text[table.start : rows[0].start()]
    header_rows = 0
    while header_rows < len(rows) - 1 and "<td" not in rows[header_rows].group(0).lower():
        header_rows += 1
    header = "".join(r.group(0) for r in rows[:header_rows])
    budget = max(1, target - len(header.split()))

    groups: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = list(rows[:header_rows])
    words = sum(len(r.group(0).split()) for r in current)
    limit = target
    for row in rows[header_rows:]:
        n = len(row.group(0).split())
        if words + n > limit and len(current) > (header_rows if not groups else 0):
            groups.append(current)
            current, words, limit = [], 0, budget
        current.append(row)
        words += n
    if current:
        groups.append(current)
    if len(groups) == 1:
        return [(replace(table, kind="table"), None)]

    pieces: list[tuple[Unit, _Decor | None]] = []
    for n, group in enumerate(groups):
        first_piece, last_piece = n == 0, n == len(groups) - 1
        start = table.start if first_piece else group[0].start()
        end = table.end if last_piece else group[-1].end()
        unit = Unit(start, end, len(text[start:end].split()), table.strength if first_piece else 0, "table")
        piece = _Decor(
            prefix="" if first_piece else f"{open_tag}{header}",
            suffix="" if last_piece else "</table>",
        )
        pieces.append((unit, piece))
    return pieces
