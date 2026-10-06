"""
HTML to Markdown, shared by the HTML, EPUB and email extractors.

A small BeautifulSoup walker built on ``markdown_utils``, so HTML lists and
tables render exactly like DOCX and PPTX ones:

- Block elements (``p``, ``div``, ``li``, ``td``...) always separate text, so
  words are never glued together across elements; inline elements join as the
  browser would. Whitespace collapses as in HTML, except inside ``pre``.
- ``ul``/``ol`` nest with two spaces per level; ``ol`` honours ``start``,
  ``type`` (``1 a A i I``), ``reversed`` and ``li value``. Paragraphs after the
  first inside an item are indented continuation lines.
- Tables are GFM with ``colspan``/``rowspan`` placed on a grid (spanned cells
  empty). A ``thead`` or all-``th`` first row is the header; otherwise the
  header row is left empty rather than promoting data. Layout tables
  (``role=presentation`` or one cell per row) are unwrapped.
- ``pre`` becomes a fenced code block (language from ``language-*``/``lang-*``
  classes) with indentation intact; ``code`` becomes a code span.
- ``blockquote`` -> ``>``, ``hr`` -> ``---``, ``dl`` -> ``**term**`` and
  ``: definition`` lines, ``figcaption`` -> an italic line.
- ``a`` -> ``[text](href)`` (relative links resolved against ``base_url`` when
  given; in-page ``#anchors`` and ``javascript:`` stay plain text).
- ``img`` -> ``![alt](src)`` with the real ``src``. Embedded images (``data:``
  URIs, or anything ``image_loader`` can resolve, such as EPUB resources and
  email ``cid:`` parts) become lazy image records with an
  ``![alt](image:img-<n>)`` marker instead.

``main_content`` picks the article body (``main``, ``[role=main]``, a single
``article``) and ``strip_boilerplate`` removes scripts, styles, navigation,
page headers/footers, sidebars and hidden elements.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote_to_bytes, urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from bs4.element import CData, Declaration, Doctype, ProcessingInstruction

from .image_utils import image_marker, image_record
from .markdown_utils import (
    TableGrid,
    escape_cell,
    heading,
    list_item,
    list_marker,
    one_line,
    render_table,
)

logger = logging.getLogger(__name__)

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "body", "caption", "center", "dd", "details",
    "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "html", "legend",
    "li", "listing", "main", "menu", "nav", "noscript", "ol", "p", "plaintext", "pre", "section",
    "summary", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul", "xmp",
}

#: Never content.
ALWAYS_STRIP = {
    "script", "style", "noscript", "template", "head", "link", "meta", "svg", "canvas",
    "iframe", "object", "embed", "applet", "button", "input", "select", "textarea", "option",
    "datalist", "map", "area", "audio", "video", "source", "track", "dialog",
}
#: Page chrome, removed when boilerplate stripping is on.
CHROME_TAGS = {"nav", "footer", "aside"}
CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "menu", "menubar"}
_CHROME_CLASS = re.compile(
    r"(?:^|[-_ ])(?:nav|navbar|navigation|menu|breadcrumbs?|sidebar|side-bar|footer|cookie|"
    r"consent|advert|advertisement|ads|social|share|sharing|newsletter|subscribe|popup|"
    r"skip-link|editsection|navbox|toc)(?:$|[-_ ])",
    re.I,
)

_BLOCK_LIST = sorted(BLOCK_TAGS)
_LANG_CLASS = re.compile(r"(?:language|lang|highlight-lang|highlight-source|brush:?)-?([A-Za-z0-9_+#.-]+)")
_OL_TYPES = {"1": "decimal", "a": "lowerLetter", "A": "upperLetter", "i": "lowerRoman", "I": "upperRoman"}
_SKIP_NODES = (Comment, Doctype, Declaration, CData, ProcessingInstruction)


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name)
    if isinstance(value, list):
        return " ".join(value)
    return value or ""


def _wrap(inner: str, marker: str) -> str:
    """``**inner**`` with surrounding whitespace kept outside the markers."""
    if not inner.strip():
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{inner.strip()}{marker}{trail}"


def _clean_inline(text: str) -> str:
    """Collapse HTML whitespace in rendered inline text, keeping ``<br>`` newlines."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _int(value: str, default: int) -> int:
    match = re.match(r"\s*-?\d+", value or "")
    return int(match.group()) if match else default


def find_tag(node: Tag, *args: Any, **kwargs: Any) -> Tag | None:
    """``node.find(...)`` narrowed to an element (or ``None``)."""
    found = node.find(*args, **kwargs)
    return found if isinstance(found, Tag) else None


def body_of(soup: Tag) -> Tag:
    """The ``<body>`` element, or the document itself when there is none."""
    return find_tag(soup, "body") or soup


def attr_text(tag: Tag | None, name: str) -> str | None:
    """An attribute as one string (``class``-style lists are joined)."""
    if tag is None or not tag.has_attr(name):
        return None
    return _attr(tag, name)


def strip_boilerplate(root: Tag, chrome: bool = True) -> None:
    """Remove non-content elements in place (scripts always; page chrome if ``chrome``)."""
    for node in root.find_all(string=lambda s: isinstance(s, _SKIP_NODES)):
        node.extract()
    body = root.find("body") if isinstance(root, Tag) else None
    total = len((body or root).get_text(" ", strip=True)) or 1
    doomed: list[Tag] = []
    for tag in root.find_all(True):
        name = tag.name
        if name in ALWAYS_STRIP:
            doomed.append(tag)
            continue
        if tag.has_attr("hidden") or _attr(tag, "aria-hidden") == "true":
            doomed.append(tag)
            continue
        style = _attr(tag, "style").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            doomed.append(tag)
            continue
        if not chrome:
            continue
        if name in CHROME_TAGS or _attr(tag, "role") in CHROME_ROLES:
            doomed.append(tag)
        elif name == "header" and not tag.find_parent(["article", "main"]) and not tag.find("h1"):
            doomed.append(tag)
        elif (
            name not in ("body", "html", "main", "article")
            and _CHROME_CLASS.search(f"{_attr(tag, 'class')} {_attr(tag, 'id')}")
            and not tag.find(["main", "article", "h1"])
            and len(tag.get_text(" ", strip=True)) < total * 0.5
        ):
            # A class like "page-menu-layout" on the wrapper of the whole page
            # must not take the content with it: only small, non-main elements go.
            doomed.append(tag)
    for tag in doomed:
        if not tag.decomposed:
            tag.decompose()


def main_content(soup: BeautifulSoup | Tag) -> Tag:
    """The element holding the page's main content, falling back to ``body``."""
    body = soup.find("body") or soup
    body_len = len(body.get_text(" ", strip=True))
    candidates = [soup.find("main"), soup.find(attrs={"role": "main"})]
    articles = soup.find_all("article")
    if len(articles) == 1:
        candidates.append(articles[0])
    for candidate in candidates:
        if isinstance(candidate, Tag):
            text_len = len(candidate.get_text(" ", strip=True))
            # Ignore a "main" that is an empty shell or a tiny fragment of the page.
            if text_len >= 200 or (body_len and text_len >= body_len * 0.5):
                return candidate
    return body if isinstance(body, Tag) else soup  # type: ignore[return-value]


class HTMLToMarkdown:
    """Convert parsed HTML to Markdown; collects embedded image records."""

    def __init__(
        self,
        base_url: str | None = None,
        image_loader: Callable[[str], bytes | None] | None = None,
        min_image_width: int = 100,
        min_image_height: int = 100,
    ) -> None:
        """
        Args:
            base_url: Resolve relative ``href``/``src`` against this URL.
            image_loader: Returns the bytes for an ``img`` ``src`` that refers
                to an embedded resource (EPUB item, email ``cid:`` part), or
                ``None`` to leave it as an external reference.
            min_image_width: Size floor for embedded images.
            min_image_height: Size floor for embedded images.
        """
        self.base_url = base_url
        self.image_loader = image_loader
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.images: list[dict[str, Any]] = []
        self._image_count = 0
        self._cell_depth = 0

    # ----------------------------------------------------------------- public

    def convert(self, root: Tag | BeautifulSoup) -> str:
        """Markdown for ``root`` and everything inside it."""
        text = "\n\n".join(b for b in self._blocks(root) if b.strip())
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    # ----------------------------------------------------------------- blocks

    def _blocks(self, node: Tag) -> list[str]:
        """Block-level Markdown for the children of ``node``."""
        blocks: list[str] = []
        inline: list[str] = []

        def flush() -> None:
            text = _clean_inline("".join(inline))
            if text:
                blocks.append(text)
            inline.clear()

        for child in node.children:
            if isinstance(child, _SKIP_NODES):
                continue
            if isinstance(child, NavigableString):
                inline.append(self._text(child))
                continue
            if not isinstance(child, Tag):
                continue
            if self._is_block(child):
                flush()
                blocks.extend(self._block(child))
            else:
                inline.append(self._inline(child))
        flush()
        return blocks

    def _is_block(self, tag: Tag) -> bool:
        if tag.name in BLOCK_TAGS:
            return True
        if tag.name in _INLINE_TAGS:
            return False
        # Unknown/custom elements: block if they wrap block content.
        return tag.find(_BLOCK_LIST) is not None

    def _block(self, tag: Tag) -> list[str]:
        name = tag.name
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = one_line(_clean_inline(self._inline_children(tag)))
            return [heading(text, int(name[1]))] if text else []
        if name in ("ul", "ol", "menu", "dir"):
            return [self._list(tag, 0)]
        if name == "table":
            return self._table(tag)
        if name in ("pre", "listing", "xmp", "plaintext"):
            return [self._pre(tag)]
        if name == "blockquote":
            inner = "\n\n".join(self._blocks(tag))
            return ["\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))] if inner else []
        if name == "hr":
            return ["---"]
        if name == "dl":
            return [self._definition_list(tag)]
        if name in ("figcaption", "caption"):
            text = _clean_inline(self._inline_children(tag))
            return [_wrap(text, "*")] if text else []
        if name in ("summary", "legend", "dt"):
            text = _clean_inline(self._inline_children(tag))
            return [_wrap(text, "**")] if text else []
        return self._blocks(tag)

    # ------------------------------------------------------------------ lists

    def _list(self, tag: Tag, level: int) -> str:
        ordered = tag.name == "ol"
        fmt = _OL_TYPES.get(_attr(tag, "type"), "decimal") if ordered else "bullet"
        reverse = ordered and tag.has_attr("reversed")
        items = [c for c in tag.children if isinstance(c, Tag) and c.name in ("li", "ul", "ol")]
        count = sum(1 for c in items if c.name == "li")
        number = _int(_attr(tag, "start"), count if reverse else 1)
        lines: list[str] = []
        for child in items:
            if child.name in ("ul", "ol"):
                # Malformed but common: a nested list as a sibling of <li>.
                nested = self._list(child, level + 1)
                if nested:
                    lines.append(nested)
                continue
            if child.has_attr("value"):
                number = _int(_attr(child, "value"), number)
            marker = list_marker(fmt, number) if ordered else "-"
            number += -1 if reverse else 1
            first, rest = self._item_parts(child, level)
            lines.append(list_item(first, level, marker) if first else f"{'  ' * level}{marker}")
            pad = "  " * level + " " * (len(marker) + 1)
            for kind, text in rest:
                if kind == "list":
                    lines.append(text)
                else:
                    lines.extend(f"{pad}{line}" if line else "" for line in text.split("\n"))
        return "\n".join(line for line in lines if line.strip())

    def _item_parts(self, li: Tag, level: int) -> tuple[str, list[tuple[str, str]]]:
        """First line of an item, then ``(kind, text)`` for what follows it."""
        parts: list[tuple[str, str]] = []
        inline: list[str] = []

        def flush() -> None:
            text = _clean_inline("".join(inline))
            if text:
                parts.append(("text", text))
            inline.clear()

        for child in li.children:
            if isinstance(child, _SKIP_NODES):
                continue
            if isinstance(child, NavigableString):
                inline.append(self._text(child))
            elif isinstance(child, Tag) and child.name in ("ul", "ol", "menu", "dir"):
                flush()
                nested = self._list(child, level + 1)
                if nested:
                    parts.append(("list", nested))
            elif isinstance(child, Tag) and self._is_block(child):
                flush()
                parts.extend(("text", block) for block in self._block(child))
            elif isinstance(child, Tag):
                inline.append(self._inline(child))
        flush()
        if parts and parts[0][0] == "text":
            return parts[0][1], parts[1:]
        return "", parts

    def _definition_list(self, tag: Tag) -> str:
        lines = []
        for child in tag.find_all(["dt", "dd"]):
            if child.find_parent("dl") is not tag:
                continue
            if child.find(_BLOCK_LIST):
                text = "\n".join(self._blocks(child))
            else:
                text = _clean_inline(self._inline_children(child))
            text = text.replace("\n\n", "\n")
            if not text:
                continue
            lines.append(_wrap(text, "**") if child.name == "dt" else f": {text}")
        return "\n".join(lines)

    # ----------------------------------------------------------------- tables

    def _rows(self, table: Tag) -> list[Tag]:
        rows = []
        for child in table.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "tr":
                rows.append(child)
            elif child.name in ("thead", "tbody", "tfoot"):
                rows.extend(c for c in child.children if isinstance(c, Tag) and c.name == "tr")
        return rows

    def _table(self, table: Tag) -> list[str]:
        rows = self._rows(table)
        cells_per_row = [[c for c in r.children if isinstance(c, Tag) and c.name in ("td", "th")] for r in rows]
        if _attr(table, "role") == "presentation" or all(len(cells) <= 1 for cells in cells_per_row):
            # A layout table: its cells are just blocks.
            blocks: list[str] = []
            caption = find_tag(table, "caption")
            if caption is not None and caption.find_parent("table") is table:
                blocks.extend(self._block(caption))
            for cells in cells_per_row:
                for cell in cells:
                    blocks.extend(self._blocks(cell))
            return blocks
        grid = TableGrid()
        for r, cells in enumerate(cells_per_row):
            for cell in cells:
                colspan = min(max(_int(_attr(cell, "colspan"), 1), 1), 100)
                rowspan = _int(_attr(cell, "rowspan"), 1)
                rowspan = min(max(rowspan, 1), len(rows) - r) if rowspan > 0 else len(rows) - r
                grid.add(r, self._cell(cell), rowspan=rowspan, colspan=colspan)
        first = rows[0] if rows else None
        header = bool(
            first is not None
            and (
                (first.parent is not None and first.parent.name == "thead")
                or all(c.name == "th" for c in cells_per_row[0])
            )
        )
        out = []
        caption = find_tag(table, "caption")
        if caption is not None and caption.find_parent("table") is table:
            text = _clean_inline(self._inline_children(caption))
            if text:
                out.append(_wrap(text, "**"))
        if self._cell_depth:
            # GFM cannot nest tables: flatten a table inside a cell into lines.
            lines = ["; ".join(c for c in row if c) for row in grid.to_rows()]
            return ["\n".join(line for line in lines if line)]
        rendered = render_table(grid.to_rows(), header_rows=1 if header else 0)
        if rendered:
            out.append(rendered)
        return out

    def _cell(self, cell: Tag) -> str:
        """One table cell as single-line Markdown (``<br>`` between its lines)."""
        self._cell_depth += 1
        try:
            blocks = self._blocks(cell)
        finally:
            self._cell_depth -= 1
        return escape_cell(re.sub(r"\n\s*\n", "\n", "\n".join(blocks)))

    # ------------------------------------------------------------------- code

    def _pre(self, tag: Tag) -> str:
        code = tag.get_text()
        code = code[1:] if code.startswith("\n") else code
        code = code.rstrip()
        classes = " ".join(
            _attr(t, "class")
            for t in [tag, tag.find("code"), tag.parent]
            if isinstance(t, Tag)
        )
        match = _LANG_CLASS.search(classes)
        lang = match.group(1).lower() if match else ""
        fence = "```"
        while fence in code:
            fence += "`"
        return f"{fence}{lang}\n{code}\n{fence}"

    # ----------------------------------------------------------------- inline

    def _text(self, node: NavigableString) -> str:
        return str(node).replace("\xa0", " ")

    def _inline_children(self, tag: Tag) -> str:
        out = []
        for child in tag.children:
            if isinstance(child, _SKIP_NODES):
                continue
            if isinstance(child, NavigableString):
                out.append(self._text(child))
            elif isinstance(child, Tag):
                if child.name in BLOCK_TAGS and child.name not in ("br",):
                    # Block inside an inline context (e.g. <p> in <a>): keep it apart.
                    out.append(" " + " ".join(self._blocks(child)) + " ")
                else:
                    out.append(self._inline(child))
        return "".join(out)

    def _inline(self, tag: Tag) -> str:
        name = tag.name
        if name == "br":
            return "\n"
        if name == "img":
            return self._image(tag)
        if name in ("strong", "b"):
            return _wrap(self._inline_children(tag), "**")
        if name in ("em", "i", "cite", "dfn"):
            return _wrap(self._inline_children(tag), "*")
        if name in ("del", "s", "strike"):
            return _wrap(self._inline_children(tag), "~~")
        if name in ("code", "kbd", "samp", "tt", "var"):
            text = " ".join(tag.get_text().split())
            if not text:
                return ""
            ticks = "`"
            while ticks in text:
                ticks += "`"
            return f"{ticks}{text}{ticks}"
        if name == "q":
            inner = self._inline_children(tag)
            return f'"{inner.strip()}"' if inner.strip() else inner
        if name == "a":
            return self._link(tag)
        if name in ("wbr",):
            return ""
        return self._inline_children(tag)

    def _link(self, tag: Tag) -> str:
        inner = self._inline_children(tag)
        href = _attr(tag, "href").strip()
        if not inner.strip():
            return inner
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "data:")):
            return inner
        if self.base_url:
            href = urljoin(self.base_url, href)
        href = href.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
        lead = inner[: len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()) :]
        text = re.sub(r"\s*\n\s*", " ", inner.strip())
        return f"{lead}[{text}]({href}){trail}"

    def _image(self, tag: Tag) -> str:
        alt = " ".join(_attr(tag, "alt").split())
        src = (_attr(tag, "src") or _attr(tag, "data-src")).strip()
        if not src:
            return ""
        width, height = _int(_attr(tag, "width"), 0), _int(_attr(tag, "height"), 0)
        if 0 < width <= 2 or 0 < height <= 2:
            return ""  # tracking pixel / spacer
        data: bytes | None = None
        if src.lower().startswith("data:"):
            data = self._data_uri(src)
            if data is None:
                return image_marker("", alt) if alt else ""
        elif self.image_loader is not None:
            data = self.image_loader(src)
        if data is None:
            if self.base_url:
                src = urljoin(self.base_url, src)
            src = src.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
            alt_text = alt.replace("[", "(").replace("]", ")")
            return f"![{alt_text}]({src})"
        self._image_count += 1
        image_id = f"img-{self._image_count}"
        record = image_record(data, self.min_image_width, self.min_image_height, id=image_id, alt=alt)
        if record is not None:
            self.images.append(record)
            return image_marker(image_id, alt)
        return image_marker(image_id, alt) if alt else ""

    @staticmethod
    def _data_uri(src: str) -> bytes | None:
        header, _, payload = src.partition(",")
        try:
            if ";base64" in header.lower():
                return base64.b64decode(payload, validate=False)
            return unquote_to_bytes(payload)
        except (binascii.Error, ValueError) as e:
            logger.debug(f"Undecodable data: URI image: {e}")
            return None


_INLINE_TAGS = {
    "a", "abbr", "acronym", "b", "bdi", "bdo", "big", "br", "cite", "code", "data", "del",
    "dfn", "em", "font", "i", "img", "ins", "kbd", "label", "mark", "nobr", "q", "rp", "rt",
    "ruby", "s", "samp", "small", "span", "strike", "strong", "sub", "sup", "time", "tt", "u",
    "var", "wbr", "picture",
}


def html_to_markdown(
    html: str | bytes,
    *,
    base_url: str | None = None,
    image_loader: Callable[[str], bytes | None] | None = None,
    main_only: bool = False,
    min_image_width: int = 100,
    min_image_height: int = 100,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Convert an HTML string to Markdown in one call.

    Returns ``(markdown, image_records)``. ``main_only`` narrows to the main
    content and strips page chrome; scripts and styles are always removed.
    """
    soup = BeautifulSoup(html, "lxml")
    strip_boilerplate(soup, chrome=main_only)
    root = main_content(soup) if main_only else body_of(soup)
    converter = HTMLToMarkdown(base_url, image_loader, min_image_width, min_image_height)
    return converter.convert(root), converter.images
