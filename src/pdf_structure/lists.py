"""List items in PDF text: recognise them, keep them, and recover their nesting.

PDFs have no list structure. A bullet is a glyph (``•``, ``○``, ``▪``, a Wingdings
private-use character...) or a label (``1.``, ``(a)``, ``iv)``) at the start of
an indented line, and nesting exists only as horizontal indentation. Text that
does not recognise those markers reflows bullet rows into one run-on paragraph,
which is what the structural chunker did before this module existed.

Two entry points:

- :func:`render_list_lines` works on positional lines (``PageLine``). It joins
  wrapped continuation lines onto their item and turns indentation into nesting
  levels.
- :func:`normalize_markdown_lists` works on Markdown text from ``pymupdf4llm``.
  It re-levels inconsistent indentation (two, three and four spaces for the same
  depth were all seen) and drops the blank lines between items of one list.

Output follows one convention everywhere: ``- `` for bullets, ``N.`` kept for
numeric labels, other labels (``(a)``, ``iv)``) kept verbatim after ``- `` so
references like "(a)(1)(i)" survive, and two spaces of indent per level.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

#: Glyphs used as bullets. Private-use code points cover symbol fonts
#: (Wingdings, Symbol, ZapfDingbats) whose bullets extract as U+F0xx.
BULLET_CHARS = (
    "•●○◦▪▫■□‣⁃∙·⦁⦾⦿◆◇❖➢➤►▶▸▹→⇒✓✔✗✘☐☑☒"
    ""
)
_BULLET = re.compile(rf"^([{re.escape(BULLET_CHARS)}\-–—*])\s*(?=\S)")

# Ordered labels. Single letters and roman numerals need a closing bracket (or
# both brackets) unless followed by a period *and* we are already inside a list,
# because "A. Smith" and "I. Introduction" are common non-list line starts.
_ROMAN = r"(?:x{0,3})(?:ix|iv|v?i{0,3})"
_ORDERED_STRONG = re.compile(
    rf"^(\(\d{{1,3}}\)|\d{{1,3}}[.)]|\([a-zA-Z]\)|[a-zA-Z]\)|\({_ROMAN}\)|{_ROMAN}\))\s+(?=\S)",
    re.IGNORECASE,
)
_ORDERED_WEAK = re.compile(rf"^([a-zA-Z]\.|{_ROMAN}\.)\s+(?=\S)", re.IGNORECASE)
# "1.2 Scope" / "3.1.4" are section numbers, not list labels.
_SECTION_NUMBER = re.compile(r"^\d+\.\d")
# A non-empty roman numeral, to reject the empty match _ROMAN allows.
_HAS_LABEL = re.compile(r"\w")


class _Line(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def bbox(self) -> tuple[float, float, float, float]: ...


@dataclass
class ListMarker:
    """What starts a list item."""

    label: str
    """Original label, e.g. ``•``, ``3.``, ``(a)``."""

    ordered: bool
    body: str
    """Item text after the label."""

    def render(self, level: int) -> str:
        indent = "  " * level
        if not self.ordered:
            return f"{indent}- {self.body}"
        if re.fullmatch(r"\d{1,3}[.)]", self.label):
            return f"{indent}{self.label[:-1]}. {self.body}"
        return f"{indent}- {self.label} {self.body}"


def parse_marker(text: str, in_list: bool = False) -> ListMarker | None:
    """Return the list marker at the start of ``text``, if there is one."""
    stripped = text.strip()
    if not stripped or _SECTION_NUMBER.match(stripped):
        return None
    match = _BULLET.match(stripped)
    if match:
        body = stripped[match.end():].strip()
        # "-5%" or "--" are not bullets; a bullet is followed by whitespace or is
        # a dedicated glyph that extraction glued to the word.
        if match.group(1) in "-–—*" and not re.match(r"^[\-–—*]\s", stripped):
            return None
        return ListMarker(label=match.group(1), ordered=False, body=body) if body else None
    match = _ORDERED_STRONG.match(stripped)
    if not match and in_list:
        match = _ORDERED_WEAK.match(stripped)
    if match and _HAS_LABEL.search(match.group(1)):
        body = stripped[match.end():].strip()
        return ListMarker(label=match.group(1), ordered=True, body=body) if body else None
    return None


def _levels(xs: Sequence[float], tolerance: float = 4.0) -> dict[float, int]:
    """Map each indentation x to a nesting level by clustering nearby values."""
    levels: dict[float, int] = {}
    anchors: list[float] = []
    for x in sorted(set(xs)):
        if not anchors or x - anchors[-1] > tolerance:
            anchors.append(x)
        levels[x] = len(anchors) - 1
    return levels


def render_list_lines(lines: Sequence[_Line]) -> list[str]:
    """
    Render positional lines, turning list items into Markdown list lines.

    Non-list lines are returned unchanged (so prose can still be reflowed). A
    line following an item and indented past the item's marker is a wrapped
    continuation and is joined onto it. A line back at or left of the marker
    ends the list.
    """
    items: list[tuple[ListMarker, float, float]] = []  # marker, marker x, text x
    out: list[str | tuple[int, ListMarker]] = []
    in_list = False

    for line in lines:
        x0 = float(line.bbox[0])
        marker = parse_marker(line.text, in_list=in_list)
        if marker is not None:
            items.append((marker, x0, x0))
            out.append((len(items) - 1, marker))
            in_list = True
            continue
        if in_list and items:
            current, marker_x, _ = items[-1]
            if x0 > marker_x + 2.0:
                current.body = _join(current.body, line.text.strip())
                continue
        in_list = False
        out.append(line.text)

    if not items:
        return [line.text for line in lines]

    levels = _levels([x for _, x, _ in items])
    rendered: list[str] = []
    for entry in out:
        if isinstance(entry, tuple):
            index, marker = entry
            rendered.append(marker.render(levels[items[index][1]]))
        else:
            rendered.append(entry)
    return rendered


def _join(head: str, tail: str) -> str:
    if head.endswith(("-", "­")) and tail[:1].islower():
        return head.rstrip("-­") + tail
    return f"{head} {tail}"


_MD_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
#: Lines that are never an item's wrapped text.
_STRUCTURAL = re.compile(r"^\s*(#|\||```|>|!\[|\*\*[^*]+\*\*\s*$)")


def _hint_key(body: str) -> str:
    return " ".join(re.sub(r"[*_`]", "", body).split())[:60].casefold()


def list_indent_hints(lines: Sequence[_Line]) -> dict[str, tuple[float, float]]:
    """
    Map each list item's text to the (x, y) position of its marker on the page.

    ``pymupdf4llm`` rounds indentation to a few spaces, and siblings at the same
    depth come out with different widths. The page coordinates are exact, so
    :func:`normalize_markdown_lists` prefers them when it can match the item.
    """
    hints: dict[str, tuple[float, float]] = {}
    in_list = False
    for line in lines:
        marker = parse_marker(line.text, in_list=in_list)
        in_list = marker is not None
        if marker is not None:
            hints.setdefault(_hint_key(marker.body), (float(line.bbox[0]), float(line.bbox[1])))
    return hints


#: A list continuing in the next column jumps right by a column width and back
#: up the page; a nested item moves right by an indent and down. Indents are
#: well under this.
_MAX_INDENT_STEP = 72.0


def normalize_markdown_lists(
    markdown: str, indent_hints: dict[str, tuple[float, float]] | None = None
) -> str:
    """
    Make Markdown list blocks consistent: two-space nesting, no blank lines
    between items of one list, and recognised PDF bullet glyphs turned into
    ``- `` items.

    Nesting comes from ``indent_hints`` (marker x positions, see
    :func:`list_indent_hints`) when every item in a block can be matched, and
    otherwise from the indentation widths, so "2, 4, 3, 2 spaces" for "item,
    child, child, item" becomes levels "0, 1, 1, 0". Fenced code is left alone.
    """
    hints = indent_hints or {}
    lines = markdown.split("\n")
    out: list[str] = []
    block: list[tuple[int, str, str]] = []  # indent width, marker, body
    pending_blank = 0
    in_fence = False

    def flush_block() -> None:
        if not block:
            return
        # Walk in order with a stack of open indents: one space either way is the
        # same level (pymupdf4llm emits 4 then 3 spaces for siblings), two or
        # more deeper opens a level, shallower closes levels.
        found = [hints.get(_hint_key(body)) for _, _, body in block]
        positions = [p for p in found if p is not None]
        use_hints = len(positions) == len(block)
        if use_hints:
            depths = [x for x, _ in positions]
            tolerance = 3.0  # points
        else:
            depths = [float(width) for width, _, _ in block]
            tolerance = 1.0  # spaces
        stack: list[float] = []
        top_kind: bool | None = None
        previous: tuple[float, float] | None = None
        for index, (depth, (_, marker, body)) in enumerate(zip(depths, block, strict=True)):
            if use_hints:
                x, y = positions[index]
                if previous is not None and (y < previous[1] - 2 or x - previous[0] > _MAX_INDENT_STEP):
                    # Same list, next column: keep the depth the list had there.
                    shift = x - previous[0]
                    stack = [d + shift for d in stack]
                previous = (x, y)
            while stack and depth < stack[-1] - tolerance:
                stack.pop()
            if not stack or depth > stack[-1] + tolerance:
                stack.append(depth)
            ordered = marker != "-"
            if len(stack) == 1:
                # A bullet list followed by a numbered one (or vice versa) is two
                # lists; without a blank line Markdown would merge them.
                if top_kind is not None and ordered != top_kind:
                    out.append("")
                top_kind = ordered
            out.append(f"{'  ' * (len(stack) - 1)}{marker} {body}")
        block.clear()

    for raw in lines:
        if raw.strip().startswith("```"):
            in_fence = not in_fence
        if in_fence or raw.strip().startswith("```"):
            flush_block()
            out.extend([""] * pending_blank)
            pending_blank = 0
            out.append(raw)
            continue

        match = _MD_ITEM.match(raw)
        glyph = None if match else parse_marker(raw)
        if match or (glyph is not None and not glyph.ordered):
            if match:
                width, marker, body = len(match.group(1).expandtabs(4)), match.group(2), match.group(3)
                if marker in "*+":
                    marker = "-"
                elif marker[-1] == ")":
                    marker = marker[:-1] + "."
                if not body.strip():
                    out.append(raw)
                    continue
            else:
                assert glyph is not None
                width = len(raw) - len(raw.lstrip(" "))
                marker, body = "-", glyph.body
            if not block:
                out.extend([""] * pending_blank)
            pending_blank = 0
            block.append((width, marker, body.strip()))
            continue

        if not raw.strip():
            pending_blank += 1
            continue

        # An unindented line straight after an item, with no blank line, is the
        # item's text wrapping (Markdown "lazy continuation"): join it.
        if block and not pending_blank and not _STRUCTURAL.match(raw):
            width, marker, body = block[-1]
            block[-1] = (width, marker, _join(body, raw.strip()))
            continue

        # Anything else ends the block.
        flush_block()
        out.extend([""] * pending_blank)
        pending_blank = 0
        out.append(raw)

    flush_block()
    out.extend([""] * pending_blank)
    return "\n".join(out)
