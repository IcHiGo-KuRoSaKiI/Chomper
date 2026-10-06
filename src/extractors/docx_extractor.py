"""
DOCX extractor: WordprocessingML body XML to clean Markdown.

The body XML is walked directly, in document order, instead of going through
python-docx's ``paragraphs``/``tables`` views, because those skip content
controls (cover pages, tables of contents), text boxes, nested tables and
images inside table cells.

Output decisions:

- **Headings.** The ``Title`` style becomes ``#``. ``Heading N`` (or any style
  or paragraph with an outline level) becomes ``N`` hashes, shifted down by one
  when the document has a ``Title`` paragraph, so the title stays the only top
  heading (``Heading 1`` -> ``##``). Levels are clamped to 6. Numbered headings
  keep their number (``## 2.1 Scope``).
- **Lists.** Real Word numbering is resolved through ``numbering.xml``:
  ``w:numPr`` on the paragraph or inherited from its style (``List Bullet``,
  ``List Number 2``...), the level's ``w:numFmt``/``w:lvlText``/``w:start``,
  and ``w:lvlOverride/w:startOverride``. Counters follow Word: lists that share
  an abstract definition continue each other unless a ``startOverride``
  restarts them, and an item resets the counters of deeper levels. Nesting
  comes from the item's effective left indent (then ``ilvl``), because
  ``List Bullet 2`` is a separate one-level list that Word simply indents
  further. Bullets render as ``-``; ordered items keep their format (``1.``,
  ``a.``, ``iv.``, ``3)``...).
- **Tables** become GFM tables (``gridSpan``/``vMerge`` spans stay empty, never
  duplicated). Nested tables are flattened into their cell (rows separated by
  ``<br>``, cells by ``; ``) since GFM cannot nest. A 1x1 table (a callout
  box) is unwrapped into ordinary blocks.
- **Text boxes** (DrawingML or VML; only one branch of ``mc:AlternateContent``)
  are emitted as blocks right after the paragraph that anchors them.
- **Images** are lazy records (``img-<n>`` in document order, alt text from
  ``wp:docPr/@descr`` or ``@title``) with a ``![alt](image:img-n)`` marker
  where they sit. Images under the size floor are dropped; their marker stays
  only when they carry alt text.
- **Headers and footers** go to ``metadata["headers"]``/``["footers"]``, not
  the body. **Footnotes and endnotes** are Markdown footnotes (``[^1]``,
  endnotes ``[^e1]``) defined at the end. Hyperlinks become ``[text](url)``;
  bold, italic and strikethrough runs are kept.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml import parse_xml

from ..models.document import RawDocument
from .base import BaseExtractor
from .image_utils import image_marker, image_record
from .markdown_utils import (
    ListDepth,
    MarkdownBuilder,
    Run,
    escape_cell,
    heading,
    list_item,
    list_marker,
    one_line,
    render_runs,
    render_table,
)

logger = logging.getLogger(__name__)

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}
W = f"{{{NS['w']}}}"
R = f"{{{NS['r']}}}"

#: First bytes of an OLE2 compound file: legacy .doc (or an encrypted .docx).
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_ORDERED = {"decimal", "decimalZero", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman"}
_HEADING_NAME = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
# ``HYPERLINK "url"`` links out; ``HYPERLINK \l "_Toc123"`` is an internal jump
# (TOC entries), which stays plain text.
_HYPERLINK_INSTR = re.compile(r'HYPERLINK\s+"([^"]+)"', re.I)


def _local(el: Any) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _val(el: Any, attr: str = "val") -> str | None:
    if el is None:
        return None
    value: str | None = el.get(f"{W}{attr}")
    return value


def _on(el: Any) -> bool:
    """A WordprocessingML on/off property (``<w:b/>``, ``<w:b w:val="0"/>``)."""
    if el is None:
        return False
    return _val(el) not in ("0", "false", "off", "none")


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _iter_outer(el: Any, tag: str) -> Iterator[Any]:
    """Descendants with local name ``tag``, not descending into matches."""
    for child in el:
        if _local(child) == tag:
            yield child
        else:
            yield from _iter_outer(child, tag)


# ----------------------------------------------------------------------- styles


@dataclass
class _Style:
    name: str = ""
    based_on: str | None = None
    num_id: str | None = None
    ilvl: int | None = None
    outline: int | None = None
    indent: int | None = None
    bold: bool | None = None
    italic: bool | None = None


class _Styles:
    def __init__(self, root: Any) -> None:
        self.styles: dict[str, _Style] = {}
        if root is None:
            return
        for el in root.findall(f"{W}style"):
            sid = el.get(f"{W}styleId")
            if not sid:
                continue
            style = _Style(name=(_val(el.find(f"{W}name")) or sid).strip())
            style.based_on = _val(el.find(f"{W}basedOn"))
            ppr = el.find(f"{W}pPr")
            if ppr is not None:
                num = ppr.find(f"{W}numPr")
                if num is not None:
                    style.num_id = _val(num.find(f"{W}numId"))
                    ilvl = _val(num.find(f"{W}ilvl"))
                    style.ilvl = _int(ilvl) if ilvl is not None else None
                outline = _val(ppr.find(f"{W}outlineLvl"))
                if outline is not None:
                    style.outline = _int(outline, 9)
                ind = ppr.find(f"{W}ind")
                if ind is not None:
                    left = ind.get(f"{W}left") or ind.get(f"{W}start")
                    if left is not None:
                        style.indent = _int(left)
            rpr = el.find(f"{W}rPr")
            if rpr is not None:
                if rpr.find(f"{W}b") is not None:
                    style.bold = _on(rpr.find(f"{W}b"))
                if rpr.find(f"{W}i") is not None:
                    style.italic = _on(rpr.find(f"{W}i"))
            self.styles[sid] = style

    def chain(self, style_id: str | None) -> Iterator[tuple[str, _Style]]:
        seen: set[str] = set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            style = self.styles[style_id]
            yield style_id, style
            style_id = style.based_on

    def name(self, style_id: str | None) -> str:
        style = self.styles.get(style_id or "")
        return style.name if style else (style_id or "")

    def heading_level(self, style_id: str | None) -> int | None:
        """``1``.. for heading styles, ``0`` for Title, ``None`` otherwise."""
        for _, style in self.chain(style_id):
            lowered = style.name.lower()
            if lowered == "title":
                return 0
            match = _HEADING_NAME.match(lowered)
            if match:
                return int(match.group(1))
            if style.outline is not None:
                return style.outline + 1 if style.outline < 9 else None
        return None

    def numbering(self, style_id: str | None) -> tuple[str, int | None, str] | None:
        """``(numId, ilvl, owning style id)`` inherited from the style chain."""
        for sid, style in self.chain(style_id):
            if style.num_id is not None:
                return style.num_id, style.ilvl, sid
        return None

    def indent(self, style_id: str | None) -> int | None:
        for _, style in self.chain(style_id):
            if style.indent is not None:
                return style.indent
        return None

    def run_format(self, style_id: str | None) -> tuple[bool, bool]:
        bold = italic = None
        for _, style in self.chain(style_id):
            if bold is None and style.bold is not None:
                bold = style.bold
            if italic is None and style.italic is not None:
                italic = style.italic
        return bool(bold), bool(italic)


# -------------------------------------------------------------------- numbering


@dataclass
class _Level:
    fmt: str = "decimal"
    text: str = "%1."
    start: int = 1
    indent: int | None = None
    style: str | None = None
    restart: int | None = None
    legal: bool = False


def _parse_level(el: Any) -> _Level:
    level = _Level()
    level.fmt = _val(el.find(f"{W}numFmt")) or "decimal"
    text = el.find(f"{W}lvlText")
    level.text = _val(text) if text is not None and _val(text) is not None else ""
    level.start = _int(_val(el.find(f"{W}start")), 1)
    level.style = _val(el.find(f"{W}pStyle"))
    restart = _val(el.find(f"{W}lvlRestart"))
    level.restart = _int(restart) if restart is not None else None
    level.legal = _on(el.find(f"{W}isLgl")) if el.find(f"{W}isLgl") is not None else False
    ind = el.find(f"{W}pPr/{W}ind")
    if ind is not None:
        left = ind.get(f"{W}left") or ind.get(f"{W}start")
        if left is not None:
            level.indent = _int(left)
    return level


@dataclass
class _Num:
    abstract: str
    start_overrides: dict[int, int] = field(default_factory=dict)
    level_overrides: dict[int, _Level] = field(default_factory=dict)


class _Numbering:
    """Word list numbering: definitions plus running counters."""

    def __init__(self, root: Any, styles: _Styles) -> None:
        self.styles = styles
        self.abstracts: dict[str, dict[int, _Level]] = {}
        self.style_links: dict[str, str] = {}
        self.nums: dict[str, _Num] = {}
        self.counters: dict[str, dict[int, int]] = {}
        self.started: set[str] = set()
        if root is None:
            return
        for el in root.findall(f"{W}abstractNum"):
            aid = el.get(f"{W}abstractNumId")
            if aid is None:
                continue
            self.abstracts[aid] = {
                _int(lvl.get(f"{W}ilvl")): _parse_level(lvl) for lvl in el.findall(f"{W}lvl")
            }
            link = _val(el.find(f"{W}numStyleLink"))
            if link:
                self.style_links[aid] = link
        for el in root.findall(f"{W}num"):
            nid = el.get(f"{W}numId")
            aid = _val(el.find(f"{W}abstractNumId"))
            if nid is None or aid is None:
                continue
            num = _Num(abstract=aid)
            for override in el.findall(f"{W}lvlOverride"):
                ilvl = _int(override.get(f"{W}ilvl"))
                start = _val(override.find(f"{W}startOverride"))
                if start is not None:
                    num.start_overrides[ilvl] = _int(start, 1)
                lvl = override.find(f"{W}lvl")
                if lvl is not None:
                    num.level_overrides[ilvl] = _parse_level(lvl)
            self.nums[nid] = num

    def _abstract(self, num: _Num) -> str:
        """Follow ``numStyleLink`` (a list style) to the abstract that defines levels."""
        aid = num.abstract
        link = self.style_links.get(aid)
        if link:
            inherited = self.styles.numbering(link)
            if inherited and inherited[0] in self.nums:
                return self.nums[inherited[0]].abstract
        return aid

    def list_id(self, num_id: str) -> str:
        """Identity of the list a numId belongs to (its abstract definition)."""
        num = self.nums.get(num_id)
        return self._abstract(num) if num is not None else num_id

    def level(self, num_id: str, ilvl: int) -> _Level | None:
        num = self.nums.get(num_id)
        if num is None:
            return None
        if ilvl in num.level_overrides:
            return num.level_overrides[ilvl]
        return self.abstracts.get(self._abstract(num), {}).get(ilvl)

    def ilvl_for_style(self, num_id: str, style_id: str) -> int:
        num = self.nums.get(num_id)
        if num is None:
            return 0
        for ilvl, lvl in self.abstracts.get(self._abstract(num), {}).items():
            if lvl.style == style_id:
                return ilvl
        return 0

    def advance(self, num_id: str, ilvl: int) -> tuple[_Level, list[int]] | None:
        """Count one item; return its level and the current value of levels 0..ilvl."""
        num = self.nums.get(num_id)
        lvl = self.level(num_id, ilvl)
        if num is None or lvl is None:
            return None
        aid = self._abstract(num)
        state = self.counters.setdefault(aid, {})
        if num_id not in self.started:
            self.started.add(num_id)
            for overridden in num.start_overrides:
                state.pop(overridden, None)
        if ilvl in state:
            state[ilvl] += 1
        else:
            state[ilvl] = num.start_overrides.get(ilvl, lvl.start)
        for deeper in [k for k in state if k > ilvl]:
            deeper_lvl = self.level(num_id, deeper)
            restart = deeper_lvl.restart if deeper_lvl else None
            if restart is None or (restart != 0 and ilvl < restart):
                del state[deeper]
        values = []
        for k in range(ilvl + 1):
            if k in state:
                values.append(state[k])
            else:
                k_lvl = self.level(num_id, k)
                values.append(num.start_overrides.get(k, k_lvl.start if k_lvl else 1))
        return lvl, values

    def label(self, num_id: str, ilvl: int, values: list[int]) -> str:
        """Render ``w:lvlText`` (``%1.%2.``) with each level's own format."""

        def sub(match: re.Match[str]) -> str:
            k = int(match.group(1)) - 1
            if k >= len(values):
                return ""
            k_lvl = self.level(num_id, k)
            fmt = k_lvl.fmt if k_lvl else "decimal"
            this = self.level(num_id, ilvl)
            if this is not None and this.legal:
                fmt = "decimal"
            if fmt not in _ORDERED:
                fmt = "decimal"
            return list_marker(fmt, values[k], suffix="")

        lvl = self.level(num_id, ilvl)
        return re.sub(r"%([1-9])", sub, lvl.text if lvl else "").strip()


# ----------------------------------------------------------------------- blocks


@dataclass
class _Block:
    kind: str  # heading | para | item | cont | table
    text: str = ""
    level: int = 0
    key: tuple[int, int] = (0, 0)
    marker: str = "-"
    list_id: str = ""
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class _Context:
    part: Any
    images: bool = True
    field_href: list[str | None] = field(default_factory=list)
    field_instr: list[str] = field(default_factory=list)


class DOCXExtractor(BaseExtractor):
    """Extract DOCX content as Markdown (see the module docstring for the rules)."""

    SUPPORTED_EXTENSIONS = [".docx", ".doc"]

    def __init__(
        self,
        min_image_width: int = 100,
        min_image_height: int = 100,
        image_helper: Any = None,
    ):
        """
        Initialize DOCX extractor.

        Args:
            min_image_width: Minimum image width to keep
            min_image_height: Minimum image height to keep
            image_helper: Unused; kept for API compatibility
        """
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.image_helper = image_helper

    # ------------------------------------------------------------------ entry

    def extract(self, file_path: str) -> RawDocument:
        """Extract a DOCX file into Markdown text, metadata and section structure."""
        self.validate_file(file_path)
        with open(file_path, "rb") as fh:
            head = fh.read(8)
        if head.startswith(OLE_MAGIC):
            raise ValueError(
                f"{Path(file_path).name} is a legacy binary Word 97-2003 (.doc) file, or a "
                "password-protected .docx. Only the .docx (Office Open XML) format can be read; "
                "open it in Word or LibreOffice and save it as .docx first."
            )
        try:
            doc = Document(file_path)
        except (PackageNotFoundError, KeyError, ValueError) as e:
            raise ValueError(f"{Path(file_path).name} is not a readable .docx file: {e}") from e

        self._setup(doc)
        body_blocks = self._blocks(doc.element.body, _Context(doc.part))
        segments = self._segments(body_blocks)

        full_text = "\n\n".join(md for _, md, _ in segments)
        notes = self._render_notes()
        if notes:
            full_text = f"{full_text}\n\n{notes}" if full_text else notes

        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_docx_metadata(doc))
        headers, footers = self._headers_footers(doc)
        if headers:
            metadata["headers"] = headers
        if footers:
            metadata["footers"] = footers
        if self._notes_used["footnote"] or self._notes_used["endnote"]:
            metadata["footnote_count"] = len(self._notes_used["footnote"])
            metadata["endnote_count"] = len(self._notes_used["endnote"])

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={"sections": self._sections(segments), "images": self._images},
        )

    def _setup(self, doc: Any) -> None:
        self._doc = doc
        styles_root = None
        try:
            styles_root = doc.part.part_related_by(RT.STYLES).element
        except (KeyError, AttributeError):
            logger.debug("DOCX has no styles part")
        self._styles = _Styles(styles_root)
        numbering_root = None
        try:
            numbering_root = doc.part.part_related_by(RT.NUMBERING).element
        except (KeyError, AttributeError):
            logger.debug("DOCX has no numbering part")
        self._numbering = _Numbering(numbering_root, self._styles)
        self._images: list[dict[str, Any]] = []
        self._image_count = 0
        self._notes: dict[str, dict[str, Any]] = {
            "footnote": self._load_notes(doc, RT.FOOTNOTES, "footnote"),
            "endnote": self._load_notes(doc, RT.ENDNOTES, "endnote"),
        }
        self._notes_used: dict[str, dict[str, str]] = {"footnote": {}, "endnote": {}}
        body = doc.element.body
        self._has_title = any(
            self._styles.heading_level(_val(p)) == 0 for p in body.iter(f"{W}pStyle")
        )

    # ----------------------------------------------------------------- blocks

    def _blocks(self, container: Any, ctx: _Context) -> list[_Block]:
        """Block-level content of a body, cell, text box or note, in order."""
        out: list[_Block] = []
        for child in container:
            tag = _local(child)
            if tag == "p":
                out.extend(self._paragraph(child, ctx))
            elif tag == "tbl":
                out.extend(self._table(child, ctx))
            elif tag in ("sdt", "customXml"):
                content = child.find(f"{W}sdtContent") if tag == "sdt" else child
                if content is not None:
                    out.extend(self._blocks(content, ctx))
            elif tag == "AlternateContent":
                branch = child.find("mc:Choice", NS)
                if branch is None:
                    branch = child.find("mc:Fallback", NS)
                if branch is not None:
                    out.extend(self._blocks(branch, ctx))
            elif tag == "altChunk":
                logger.warning("DOCX altChunk (embedded foreign document) content is not extracted")
        return out

    def _paragraph(self, p: Any, ctx: _Context) -> list[_Block]:
        ppr = p.find(f"{W}pPr")
        style_id = _val(ppr.find(f"{W}pStyle")) if ppr is not None else None
        runs: list[Run] = []
        floating: list[_Block] = []
        self._inline(p, ctx, runs, floating, None, style_id)
        level = self._heading_level(ppr, style_id)

        numbering = self._list_info(ppr, style_id)
        blocks: list[_Block] = []
        if level is not None:
            text = one_line("".join(r.text for r in runs if not r.text.startswith("![")))
            markers = "".join(r.text for r in runs if r.text.startswith("!["))
            if numbering and numbering[0] != "-":
                text = f"{numbering[2]} {text}".strip()
            if text:
                blocks.append(_Block("heading", text, level=level))
            if markers:
                blocks.append(_Block("para", markers))
        else:
            text = render_runs(runs).strip()
            if numbering is not None and text:
                marker, key, _, list_id = numbering
                blocks.append(_Block("item", text, key=key, marker=marker, list_id=list_id))
            elif text:
                name = self._styles.name(style_id).lower()
                kind = "cont" if name.startswith("list continue") or name == "list paragraph" else "para"
                blocks.append(_Block(kind, text))
        return blocks + floating

    def _heading_level(self, ppr: Any, style_id: str | None) -> int | None:
        level = None
        if ppr is not None and ppr.find(f"{W}outlineLvl") is not None:
            outline = _int(_val(ppr.find(f"{W}outlineLvl")), 9)
            level = outline + 1 if outline < 9 else None
        if level is None:
            level = self._styles.heading_level(style_id)
        if level is None:
            return None
        if level == 0:
            return 1
        return min(level + 1 if self._has_title else level, 6)

    def _list_info(self, ppr: Any, style_id: str | None) -> tuple[str, tuple[int, int], str, str] | None:
        """``(markdown marker, nesting key, full label, list id)`` for a numbered paragraph."""
        num_id: str | None = None
        ilvl: int | None = None
        num_pr = ppr.find(f"{W}numPr") if ppr is not None else None
        if num_pr is not None:
            num_id = _val(num_pr.find(f"{W}numId"))
            ilvl_val = _val(num_pr.find(f"{W}ilvl"))
            ilvl = _int(ilvl_val) if ilvl_val is not None else None
        owner = style_id
        if num_id is None:
            inherited = self._styles.numbering(style_id)
            if inherited:
                num_id, style_ilvl, owner = inherited
                ilvl = style_ilvl if ilvl is None else ilvl
        if num_id is None or num_id == "0":
            return self._list_style_fallback(style_id)
        if ilvl is None:
            ilvl = self._numbering.ilvl_for_style(num_id, owner or "")
        advanced = self._numbering.advance(num_id, ilvl)
        if advanced is None:
            return self._list_style_fallback(style_id)
        lvl, values = advanced
        if lvl.fmt == "none" or (lvl.fmt != "bullet" and not lvl.text):
            return None
        indent = None
        if ppr is not None:
            ind = ppr.find(f"{W}ind")
            if ind is not None and (ind.get(f"{W}left") or ind.get(f"{W}start")):
                indent = _int(ind.get(f"{W}left") or ind.get(f"{W}start"))
        if indent is None:
            indent = lvl.indent
        if indent is None:
            indent = self._styles.indent(style_id)
        if indent is None:
            indent = 720 * (ilvl + 1)
        key = (indent, ilvl)
        list_id = self._numbering.list_id(num_id)
        if lvl.fmt == "bullet":
            return "-", key, "", list_id
        fmt = lvl.fmt if lvl.fmt in _ORDERED else "decimal"
        tail = re.split(r"%[1-9]", lvl.text)[-1].strip()
        suffix = ")" if tail.startswith(")") else "."
        label = self._numbering.label(num_id, ilvl, values)
        return list_marker(fmt, values[ilvl], suffix), key, label, list_id

    def _list_style_fallback(self, style_id: str | None) -> tuple[str, tuple[int, int], str, str] | None:
        """``List Bullet 2``-style paragraphs whose numbering definition is missing."""
        match = re.match(r"list (bullet|number)(?: (\d))?$", self._styles.name(style_id).lower())
        if not match:
            return None
        depth = int(match.group(2) or 1) - 1
        key = (360 * (depth + 1), 0)
        if match.group(1) == "bullet":
            return "-", key, "", "style-bullet"
        return "1.", key, "1.", "style-number"

    # ----------------------------------------------------------------- inline

    def _inline(
        self,
        el: Any,
        ctx: _Context,
        runs: list[Run],
        floating: list[_Block],
        href: str | None,
        style_id: str | None,
    ) -> None:
        for child in el:
            tag = _local(child)
            if tag == "r":
                self._run(child, ctx, runs, floating, href)
            elif tag == "hyperlink":
                target = href
                rid = child.get(f"{R}id")
                if rid:
                    try:
                        target = ctx.part.rels[rid].target_ref
                    except KeyError:
                        logger.warning(f"DOCX hyperlink {rid} has no relationship; keeping its text")
                self._inline(child, ctx, runs, floating, target, style_id)
            elif tag == "fldSimple":
                match = _HYPERLINK_INSTR.search(child.get(f"{W}instr") or "")
                self._inline(child, ctx, runs, floating, match.group(1) if match else href, style_id)
            elif tag in ("ins", "smartTag", "customXml", "moveTo", "bdo", "dir"):
                self._inline(child, ctx, runs, floating, href, style_id)
            elif tag == "sdt":
                content = child.find(f"{W}sdtContent")
                if content is not None:
                    self._inline(content, ctx, runs, floating, href, style_id)
            elif tag in ("oMath", "oMathPara"):
                math = "".join(t.text or "" for t in child.iter(f"{{{NS['m']}}}t"))
                if math.strip():
                    runs.append(Run(math))

    def _run(
        self,
        r: Any,
        ctx: _Context,
        runs: list[Run],
        floating: list[_Block],
        href: str | None,
    ) -> None:
        rpr = r.find(f"{W}rPr")
        bold, italic = self._styles.run_format(_val(rpr.find(f"{W}rStyle")) if rpr is not None else None)
        strike = False
        if rpr is not None:
            if rpr.find(f"{W}b") is not None:
                bold = _on(rpr.find(f"{W}b"))
            if rpr.find(f"{W}i") is not None:
                italic = _on(rpr.find(f"{W}i"))
            strike = _on(rpr.find(f"{W}strike")) or _on(rpr.find(f"{W}dstrike"))

        def emit(text: str) -> None:
            target = href or next((h for h in reversed(ctx.field_href) if h), None)
            runs.append(Run(text, bold=bold, italic=italic, href=target, strike=strike))

        for child in r:
            tag = _local(child)
            if tag == "t":
                emit(child.text or "")
            elif tag == "tab":
                emit(" ")
            elif tag in ("br", "cr"):
                if _val(child, "type") != "page":
                    emit("\n")
            elif tag == "noBreakHyphen":
                emit("-")
            elif tag == "sym":
                try:
                    code = int(child.get(f"{W}char") or "", 16)
                except ValueError:
                    continue
                # F000-F0FF are Symbol/Wingdings glyph slots, not real characters.
                if not 0xF000 <= code <= 0xF0FF:
                    emit(chr(code))
            elif tag == "fldChar":
                kind = _val(child, "fldCharType")
                if kind == "begin":
                    ctx.field_href.append(None)
                    ctx.field_instr.append("")
                elif kind == "separate" and ctx.field_instr:
                    match = _HYPERLINK_INSTR.search(ctx.field_instr[-1])
                    ctx.field_href[-1] = match.group(1) if match else None
                elif kind == "end" and ctx.field_href:
                    ctx.field_href.pop()
                    ctx.field_instr.pop()
            elif tag == "instrText" and ctx.field_instr:
                ctx.field_instr[-1] += child.text or ""
            elif tag in ("footnoteReference", "endnoteReference"):
                kind = "footnote" if tag == "footnoteReference" else "endnote"
                runs.append(Run(self._note_label(kind, child.get(f"{W}id") or "")))
            elif tag == "drawing":
                self._drawing(child, ctx, runs, floating)
            elif tag in ("pict", "object"):
                self._vml(child, ctx, runs, floating)
            elif tag == "AlternateContent":
                choice = child.find("mc:Choice", NS)
                before = (len(runs), len(floating))
                if choice is not None:
                    self._run(choice, ctx, runs, floating, href)
                if (len(runs), len(floating)) == before:
                    fallback = child.find("mc:Fallback", NS)
                    if fallback is not None:
                        self._run(fallback, ctx, runs, floating, href)

    # ----------------------------------------------------------------- images

    def _drawing(self, el: Any, ctx: _Context, runs: list[Run], floating: list[_Block]) -> None:
        doc_pr = el.find(".//wp:docPr", NS)
        frame_alt = ""
        if doc_pr is not None:
            frame_alt = (doc_pr.get("descr") or doc_pr.get("title") or "").strip()
        for pic in self._outside_textboxes(el, f"{{{NS['pic']}}}pic"):
            c_nv = pic.find(".//pic:cNvPr", NS)
            alt = ""
            if c_nv is not None:
                alt = (c_nv.get("descr") or c_nv.get("title") or "").strip()
            blip = pic.find(".//a:blip", NS)
            if blip is None:
                continue
            rid = blip.get(f"{R}embed") or blip.get(f"{R}link")
            self._image(rid, alt or frame_alt, ctx, runs, external=blip.get(f"{R}embed") is None)
        for box in _iter_outer(el, "txbxContent"):
            floating.extend(self._blocks(box, ctx))

    def _vml(self, el: Any, ctx: _Context, runs: list[Run], floating: list[_Block]) -> None:
        for data in self._outside_textboxes(el, f"{{{NS['v']}}}imagedata"):
            rid = data.get(f"{R}id") or data.get(f"{R}href")
            shape = data.getparent()
            alt = ((shape.get("alt") if shape is not None else None) or data.get(f"{{{NS['o']}}}title") or "").strip()
            self._image(rid, alt, ctx, runs)
        for box in _iter_outer(el, "txbxContent"):
            floating.extend(self._blocks(box, ctx))

    @staticmethod
    def _outside_textboxes(el: Any, tag: str) -> Iterator[Any]:
        """Descendants matching ``tag`` that are not inside a text box."""
        stack = list(el)
        while stack:
            node = stack.pop(0)
            if _local(node) == "txbxContent":
                continue
            if node.tag == tag:
                yield node
            stack[0:0] = list(node)

    def _image(
        self,
        rid: str | None,
        alt: str,
        ctx: _Context,
        runs: list[Run],
        external: bool = False,
    ) -> None:
        if not rid:
            return
        self._image_count += 1
        image_id = f"img-{self._image_count}"
        if external:
            try:
                runs.append(Run(f"![{one_line(alt)}]({ctx.part.rels[rid].target_ref})"))
            except KeyError:
                logger.warning(f"DOCX linked image {rid} has no relationship")
            return
        record = None
        if ctx.images:
            try:
                blob = ctx.part.related_parts[rid].blob
            except (KeyError, AttributeError) as e:
                logger.warning(f"DOCX image {image_id} ({rid}) could not be loaded: {e}")
            else:
                record = image_record(
                    blob, self.min_image_width, self.min_image_height, id=image_id, alt=alt
                )
        if record is not None:
            self._images.append(record)
            runs.append(Run(image_marker(image_id, alt)))
        elif alt:
            runs.append(Run(image_marker(image_id, alt)))

    # ----------------------------------------------------------------- tables

    def _table(self, tbl: Any, ctx: _Context) -> list[_Block]:
        rows: list[list[str]] = []
        cells_blocks: list[list[_Block]] = []
        for tr in self._rows(tbl):
            row: list[str] = []
            trpr = tr.find(f"{W}trPr")
            if trpr is not None:
                row.extend([""] * _int(_val(trpr.find(f"{W}gridBefore"))))
            for tc in self._cells(tr):
                tcpr = tc.find(f"{W}tcPr")
                span = 1
                merged = False
                if tcpr is not None:
                    span = max(_int(_val(tcpr.find(f"{W}gridSpan")), 1), 1)
                    vmerge = tcpr.find(f"{W}vMerge")
                    merged = vmerge is not None and _val(vmerge) != "restart"
                blocks = self._blocks(tc, ctx)
                cells_blocks.append(blocks)
                row.append("" if merged else self._cell_text(blocks))
                row.extend([""] * (span - 1))
            rows.append(row)
        if not rows:
            return []
        if len(rows) == 1 and len(rows[0]) == 1 and len(cells_blocks) == 1:
            return cells_blocks[0]  # a 1x1 "callout box" table: just its content
        return [_Block("table", render_table(rows), rows=rows)]

    @staticmethod
    def _rows(tbl: Any) -> Iterator[Any]:
        for child in tbl:
            tag = _local(child)
            if tag == "tr":
                yield child
            elif tag in ("sdt", "customXml"):
                content = child.find(f"{W}sdtContent") if tag == "sdt" else child
                if content is not None:
                    yield from DOCXExtractor._rows(content)

    @staticmethod
    def _cells(tr: Any) -> Iterator[Any]:
        for child in tr:
            tag = _local(child)
            if tag == "tc":
                yield child
            elif tag in ("sdt", "customXml"):
                content = child.find(f"{W}sdtContent") if tag == "sdt" else child
                if content is not None:
                    yield from DOCXExtractor._cells(content)

    def _cell_text(self, blocks: list[_Block]) -> str:
        """One table cell's blocks as single-line Markdown (``<br>`` between lines)."""
        parts: list[str] = []
        for block in blocks:
            if block.kind == "table":
                # GFM cannot nest tables: flatten rows into the cell.
                parts.extend("; ".join(c for c in row if c) for row in block.rows)
            else:
                parts.append(self._render([block]))
        text = "\n".join(p for p in parts if p.strip())
        return escape_cell(re.sub(r"\n\s*\n", "\n", text))

    # ----------------------------------------------------------------- render

    def _render(self, blocks: list[_Block]) -> str:
        return "\n\n".join(md for _, md, _ in self._segments(blocks))

    def _segments(self, blocks: list[_Block]) -> list[tuple[str, str, int]]:
        """Group blocks into ``(kind, markdown, level)``; a list is one segment."""
        segments: list[tuple[str, str, int]] = []
        depth = ListDepth()
        builder: MarkdownBuilder | None = None
        last: tuple[int, str] | None = None  # depth and marker of the last item
        top_list = ""

        def close() -> None:
            nonlocal builder, last
            if builder is not None:
                segments.append(("text", builder.build(), 0))
            builder = None
            last = None
            depth.reset()

        for block in blocks:
            if block.kind == "item":
                d = depth.depth(block.key[0] * 10 + block.key[1])
                if builder is not None and d == 0 and block.list_id != top_list:
                    close()  # a different list starts: keep the two apart
                    d = depth.depth(block.key[0] * 10 + block.key[1])
                if builder is None:
                    builder = MarkdownBuilder()
                if d == 0:
                    top_list = block.list_id
                builder.add_list_item(list_item(block.text, d, block.marker))
                last = (d, block.marker)
                continue
            if block.kind == "cont" and builder is not None and last is not None:
                pad = "  " * last[0] + " " * (len(last[1]) + 1)
                builder.add_list_item("\n".join(pad + line for line in block.text.split("\n")))
                continue
            close()
            if block.kind == "heading":
                segments.append(("heading", heading(block.text, block.level), block.level))
            elif block.kind == "table":
                segments.append(("table", block.text, 0))
            elif block.text.strip():
                segments.append(("text", block.text, 0))
        close()
        return segments

    def _sections(self, segments: list[tuple[str, str, int]]) -> list[dict[str, Any]]:
        """Split segments at the shallowest heading level, for the DOCX chunker."""
        levels = [level for kind, _, level in segments if kind == "heading"]
        top = min(levels) if levels else 1
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for kind, md, level in segments:
            if kind == "heading" and level == top:
                current = {"heading": md.lstrip("#").strip(), "level": level, "content": []}
                sections.append(current)
                continue
            if current is None:
                current = {"heading": "", "level": 0, "content": []}
                sections.append(current)
            if kind == "heading":
                current["content"].append({"type": "heading", "level": level, "text": md.lstrip("#").strip()})
            else:
                current["content"].append({"type": "table" if kind == "table" else "text", "text": md})
        return sections

    # ------------------------------------------------------------------ notes

    def _load_notes(self, doc: Any, reltype: str, kind: str) -> dict[str, Any]:
        try:
            part = doc.part.part_related_by(reltype)
        except KeyError:
            return {}
        try:
            root = part.element if hasattr(part, "element") else parse_xml(part.blob)
        except (ValueError, SyntaxError) as e:
            logger.warning(f"DOCX {kind}s could not be parsed: {e}")
            return {}
        notes: dict[str, Any] = {}
        for note in root.findall(f"{W}{kind}"):
            if note.get(f"{W}type") in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            notes[note.get(f"{W}id") or ""] = (note, part)
        return notes

    def _note_label(self, kind: str, note_id: str) -> str:
        used = self._notes_used[kind]
        if note_id not in used:
            prefix = "" if kind == "footnote" else "e"
            used[note_id] = f"{prefix}{len(used) + 1}"
        return f"[^{used[note_id]}]"

    def _render_notes(self) -> str:
        lines: list[str] = []
        for kind in ("footnote", "endnote"):
            # Rendering a note can reference further notes; iterate until stable.
            done: set[str] = set()
            while True:
                pending = [(nid, label) for nid, label in self._notes_used[kind].items() if nid not in done]
                if not pending:
                    break
                for note_id, label in pending:
                    done.add(note_id)
                    entry = self._notes[kind].get(note_id)
                    if entry is None:
                        logger.warning(f"DOCX {kind} {note_id} is referenced but not defined")
                        continue
                    note, part = entry
                    body = self._render(self._blocks(note, _Context(part, images=False)))
                    body = "\n    ".join(line for line in body.split("\n") if line.strip())
                    lines.append(f"[^{label}]: {body}".rstrip())
        return "\n".join(lines)

    # -------------------------------------------------------- headers/footers

    def _headers_footers(self, doc: Any) -> tuple[list[str], list[str]]:
        headers: list[str] = []
        footers: list[str] = []
        rels = sorted(doc.part.rels.values(), key=lambda rel: _int(re.sub(r"\D", "", rel.rId), 0))
        for rel in rels:
            if rel.is_external or rel.reltype not in (RT.HEADER, RT.FOOTER):
                continue
            part = rel.target_part
            root = part.element if hasattr(part, "element") else parse_xml(part.blob)
            text = self._render(self._blocks(root, _Context(part, images=False))).strip()
            bucket = headers if rel.reltype == RT.HEADER else footers
            if text and text not in bucket:
                bucket.append(text)
        return headers, footers

    # --------------------------------------------------------------- metadata

    def _extract_docx_metadata(self, doc: Any) -> dict[str, Any]:
        core_props = doc.core_properties
        return {
            "author": core_props.author or "Unknown",
            "title": core_props.title or "",
            "subject": core_props.subject or "",
            "created": str(core_props.created) if core_props.created else "",
            "modified": str(core_props.modified) if core_props.modified else "",
            "format": "docx",
        }
