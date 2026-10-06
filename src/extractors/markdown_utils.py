"""
Shared Markdown rendering for every extractor.

Each extractor maps its own format onto a handful of primitives here, so lists,
tables and inline formatting come out the same no matter where they started:

- ``heading``: ``#`` .. ``######``.
- ``list_marker`` / ``list_item``: ``- `` bullets and ``1.`` / ``a.`` / ``i.``
  ordered markers, two spaces of indent per nesting level, continuation lines
  indented to the item's content.
- ``render_table``: GitHub-flavoured pipe tables. ``|`` is escaped, newlines in a
  cell become ``<br>``, rows are padded to equal width, and merged cells keep
  their value in the first cell only (``TableGrid`` places spans).
- ``Run`` / ``render_runs``: ``**bold**``, ``*italic*`` and ``[text](url)``,
  merging neighbouring runs that share formatting (Word and PowerPoint split
  runs constantly) and never wrapping bare whitespace in markers.
- ``MarkdownBuilder``: joins blocks with one blank line, keeps the items of one
  list together with no blank lines between them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# --------------------------------------------------------------------- headings


def heading(text: str, level: int) -> str:
    """``## Text`` with the level clamped to 1..6 and the text on one line."""
    level = min(max(level, 1), 6)
    return f"{'#' * level} {one_line(text)}"


def one_line(text: str) -> str:
    """Collapse all whitespace (including newlines) to single spaces."""
    return " ".join(text.split())


# ------------------------------------------------------------------------ lists

#: Ordered list formats understood by ``format_number``. Names follow Word's
#: ``w:numFmt`` values; other formats map onto these.
ORDERED_FORMATS = {
    "decimal",
    "decimalZero",
    "lowerLetter",
    "upperLetter",
    "lowerRoman",
    "upperRoman",
}

_ROMAN = [
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
]


def to_roman(number: int) -> str:
    """Lower-case Roman numeral (``4`` -> ``iv``); non-positive falls back to digits."""
    if number <= 0:
        return str(number)
    out = []
    for value, numeral in _ROMAN:
        while number >= value:
            out.append(numeral)
            number -= value
    return "".join(out)


def to_letters(number: int) -> str:
    """Spreadsheet-style letters (``1`` -> ``a``, ``27`` -> ``aa``)."""
    if number <= 0:
        return str(number)
    out = ""
    while number > 0:
        number, rem = divmod(number - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


def format_number(number: int, fmt: str) -> str:
    """Render ``number`` in a list numbering format (``decimal``, ``lowerRoman``...)."""
    if fmt == "lowerLetter":
        return to_letters(number)
    if fmt == "upperLetter":
        return to_letters(number).upper()
    if fmt == "lowerRoman":
        return to_roman(number)
    if fmt == "upperRoman":
        return to_roman(number).upper()
    if fmt == "decimalZero":
        return f"{number:02d}"
    return str(number)


def list_marker(fmt: str, number: int = 1, suffix: str = ".") -> str:
    """
    Marker for one list item.

    ``fmt`` is ``"bullet"`` for ``-`` or an ordered format from
    ``ORDERED_FORMATS``; ``suffix`` is the punctuation after the number
    (``.`` or ``)``), so ``list_marker("lowerLetter", 2)`` is ``b.``.
    """
    if fmt not in ORDERED_FORMATS:
        return "-"
    return f"{format_number(number, fmt)}{suffix if suffix in ('.', ')') else '.'}"


def list_item(text: str, depth: int, marker: str) -> str:
    """
    One list item at nesting ``depth`` (0 = top level).

    Extra lines in ``text`` (continuation paragraphs, ``<br>`` breaks) are
    indented to line up with the item's content.
    """
    indent = "  " * max(depth, 0)
    lines = text.split("\n")
    first = f"{indent}{marker} {lines[0]}".rstrip()
    if len(lines) == 1:
        return first
    pad = indent + " " * (len(marker) + 1)
    rest = [f"{pad}{line}" if line.strip() else "" for line in lines[1:]]
    return "\n".join([first, *rest])


# ----------------------------------------------------------------------- tables


def escape_cell(text: str) -> str:
    """Make arbitrary text safe for one GFM table cell."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"(?<!\\)\|", r"\\|", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "<br>", text)
    return text


def render_table(rows: Sequence[Sequence[str]], header_rows: int = 1) -> str:
    """
    Render rows of cell text as a GitHub-flavoured pipe table.

    The first row is the header (GFM requires exactly one). If ``header_rows``
    is greater than one, the extra header rows become ordinary rows, which keeps
    their text. ``header_rows=0`` emits an empty header so no data row is
    promoted to a header it never was. Empty input gives ``""``.
    """
    clean = [[escape_cell(str(cell)) for cell in row] for row in rows]
    clean = [row for row in clean if row]
    if not clean:
        return ""
    width = max(len(row) for row in clean)
    clean = [row + [""] * (width - len(row)) for row in clean]
    if header_rows <= 0:
        clean.insert(0, [""] * width)
    lines = [_table_row(clean[0]), _table_row(["---"] * width)]
    lines.extend(_table_row(row) for row in clean[1:])
    return "\n".join(lines)


def _table_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


class TableGrid:
    """
    Place cells with row/column spans onto a grid.

    ``add`` puts a value at the next free column of a row and reserves the
    spanned cells below and to the right, which stay empty: merged values are
    never duplicated.
    """

    def __init__(self) -> None:
        self._cells: dict[tuple[int, int], str] = {}
        self._taken: set[tuple[int, int]] = set()
        self.rows = 0
        self.cols = 0

    def add(self, row: int, text: str, rowspan: int = 1, colspan: int = 1) -> None:
        """Place ``text`` in ``row`` at the first column not already taken."""
        col = 0
        while (row, col) in self._taken:
            col += 1
        rowspan = max(rowspan, 1)
        colspan = max(colspan, 1)
        for r in range(row, row + rowspan):
            for c in range(col, col + colspan):
                self._taken.add((r, c))
        self._cells[(row, col)] = text
        self.rows = max(self.rows, row + 1)
        self.cols = max(self.cols, col + colspan)

    def to_rows(self) -> list[list[str]]:
        """The grid as rows of text, spanned cells empty."""
        return [
            [self._cells.get((r, c), "") for c in range(self.cols)] for r in range(self.rows)
        ]


# ----------------------------------------------------------------------- inline


@dataclass(frozen=True)
class Run:
    """A stretch of text sharing one set of inline formatting."""

    text: str
    bold: bool = False
    italic: bool = False
    href: str | None = None
    code: bool = False
    strike: bool = False


def _wrap(text: str, bold: bool, italic: bool, strike: bool) -> str:
    """Wrap text in emphasis markers, keeping outer whitespace outside them."""
    if not text.strip() or not (bold or italic or strike):
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    core = text.strip()
    if strike:
        core = f"~~{core}~~"
    if bold and italic:
        core = f"***{core}***"
    elif bold:
        core = f"**{core}**"
    elif italic:
        core = f"*{core}*"
    return f"{lead}{core}{trail}"


def _code_span(text: str) -> str:
    if not text.strip():
        return text
    ticks = "`"
    while ticks in text:
        ticks += "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def link(text: str, href: str) -> str:
    """``[text](href)``, or just the text when there is no usable target."""
    if not href or not text.strip():
        return text
    href = href.strip().replace(" ", "%20").replace(")", "%29").replace("(", "%28")
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    return f"{lead}[{text.strip()}]({href}){trail}"


def render_runs(runs: Iterable[Run]) -> str:
    """
    Render formatted runs as Markdown inline text.

    Neighbouring runs with identical formatting are merged first, so a word
    Word split across three runs does not come out as ``**Hel****lo**``.
    Whitespace-only runs never get markers.
    """
    merged: list[Run] = []
    for run in runs:
        if not run.text:
            continue
        if merged:
            prev = merged[-1]
            same = (prev.bold, prev.italic, prev.href, prev.code, prev.strike) == (
                run.bold,
                run.italic,
                run.href,
                run.code,
                run.strike,
            )
            # Whitespace can join a formatted neighbour without changing how it reads.
            if same or (not run.text.strip() and not run.href and not run.code and prev.href is None):
                merged[-1] = Run(prev.text + run.text, prev.bold, prev.italic, prev.href, prev.code, prev.strike)
                continue
        merged.append(run)

    # A link may span differently formatted runs: group by href, format inside.
    out: list[str] = []
    i = 0
    while i < len(merged):
        run = merged[i]
        if run.href:
            j = i
            inner: list[str] = []
            while j < len(merged) and merged[j].href == run.href:
                part = merged[j]
                piece = _code_span(part.text) if part.code else part.text
                inner.append(_wrap(piece, part.bold, part.italic, part.strike))
                j += 1
            out.append(link("".join(inner), run.href))
            i = j
            continue
        piece = _code_span(run.text) if run.code else run.text
        out.append(_wrap(piece, run.bold, run.italic, run.strike))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------- builder


class MarkdownBuilder:
    """
    Assemble Markdown blocks with consistent spacing.

    Blocks (paragraphs, headings, tables, code) are separated by one blank
    line. Consecutive ``add_list_item`` calls form one list with no blank lines
    between items, and a blank line before and after the list.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._in_list = False

    def add_block(self, text: str) -> None:
        """Add a standalone block; empty or whitespace-only text is ignored."""
        if not text or not text.strip():
            return
        self._parts.append(("\n\n" if self._parts else "") + text.strip("\n"))
        self._in_list = False

    def add_list_item(self, line: str) -> None:
        """Add a rendered list item (see ``list_item``) to the current list."""
        if not line.strip():
            return
        sep = "\n" if self._in_list else ("\n\n" if self._parts else "")
        self._parts.append(sep + line.rstrip())
        self._in_list = True

    def end_list(self) -> None:
        """Close the current list so the next item starts a new one."""
        self._in_list = False

    @property
    def in_list(self) -> bool:
        """Whether the last thing added was a list item."""
        return self._in_list

    def build(self) -> str:
        """The assembled Markdown."""
        return "".join(self._parts)


class ListDepth:
    """
    Track list nesting from source levels that may skip (0, 2, 3...).

    ``depth(level)`` returns the Markdown nesting depth for an item at a source
    level, so an item at Word ``ilvl`` 2 directly under ``ilvl`` 0 is nested
    once, not twice, and a list starting at level 1 is not indented.
    """

    def __init__(self) -> None:
        self._stack: list[int] = []

    def depth(self, level: int) -> int:
        """Markdown depth for an item at source ``level``."""
        while self._stack and self._stack[-1] > level:
            self._stack.pop()
        if not self._stack or self._stack[-1] < level:
            self._stack.append(level)
        return len(self._stack) - 1

    def reset(self) -> None:
        """Forget all open levels (a non-list block intervened)."""
        self._stack.clear()


__all__ = [
    "ORDERED_FORMATS",
    "ListDepth",
    "MarkdownBuilder",
    "Run",
    "TableGrid",
    "escape_cell",
    "format_number",
    "heading",
    "link",
    "list_item",
    "list_marker",
    "one_line",
    "render_runs",
    "render_table",
    "to_letters",
    "to_roman",
]
