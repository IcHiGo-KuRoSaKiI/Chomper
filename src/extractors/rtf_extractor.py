"""
Extractor for RTF (Rich Text Format) files.

RTF is a document file format developed by Microsoft for
cross-platform document interchange.

striprtf does the heavy lifting, but it discards list numbering (``\\pntext``
and ``\\listtext`` are "destinations" it skips) and flattens tables to
``a|b|``. Before handing the source to striprtf we therefore swap those
constructs for control-character sentinels that survive as plain text, then
rebuild Markdown from them:

- list paragraphs become ``- item`` / ``1. item`` / ``a) item``, nested two
  spaces per level from ``\\ilvl`` (Word) or the paragraph's left indent
  ``\\li`` (older writers);
- table rows (``\\cell`` ... ``\\row``) become a GFM pipe table;
- ``\\line`` soft breaks stay inside their paragraph.
"""
from __future__ import annotations

import bisect
import codecs
import re
from pathlib import Path
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor
from .markdown_utils import ListDepth, MarkdownBuilder, list_item, render_table

# Optional import
try:
    from striprtf.striprtf import rtf_to_text
    STRIPRTF_AVAILABLE = True
except ImportError:
    rtf_to_text = None
    STRIPRTF_AVAILABLE = False

# Sentinels: written into the RTF as \'hh escapes, read back from striprtf's text.
_LIST = "\x01"  # \x01<level>\x01<marker>\x01 at the start of a list paragraph
_CELL = "\x02"  # end of a table cell
_BREAK = "\x03"  # \line soft break

_LIST_GROUP = re.compile(r"\{\\(?:pntext|listtext)\b((?:[^{}]|\{[^{}]*\})*)\}")
_PAR = re.compile(r"\\par(?![a-z])")
_ILVL = re.compile(r"\\ilvl(\d+)")
_LEFT_INDENT = re.compile(r"\\li(-?\d+)")
_CONTROL_WORD = re.compile(r"\\[a-zA-Z]+-?\d* ?")
_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
_ORDERED = re.compile(r"^\(?([0-9]{1,4}|[a-zA-Z]{1,6})([.)])$")
_CODEPAGE = re.compile(rb"\\ansicpg(\d+)")
# Bullet glyphs striprtf leaves behind for \bullet, \u8226 or Symbol/Wingdings
# private-use characters, followed by the tab or spaces that set them off.
_GLYPH_BULLET = re.compile(r"^[•·◦▪‣○■□➢✓\uf0b7\uf0a7\uf0d8\uf076\uf0fc][\t ]+|^[-–][\t]+")


class RTFExtractor(BaseExtractor):
    """
    Extractor for RTF (Rich Text Format) files.

    Uses striprtf library for text extraction; see the module docstring for how
    lists and tables are preserved as Markdown.
    """

    SUPPORTED_EXTENSIONS = [".rtf"]

    def __init__(self):
        """Initialize RTF extractor."""
        if not STRIPRTF_AVAILABLE:
            raise ImportError("striprtf is required for RTF extraction. Install with: pip install striprtf")

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from RTF file."""
        self.validate_file(file_path)

        raw = Path(file_path).read_bytes()
        encoding = self._codepage(raw)
        try:
            content = raw.decode(encoding)
        except UnicodeDecodeError:
            content = raw.decode("latin-1")

        try:
            plain = rtf_to_text(self._mark_structure(content), encoding=encoding, errors="replace")
        except Exception as e:
            raise ValueError(f"Failed to parse RTF: {e}") from e

        text, has_lists, has_tables = self._to_markdown(plain)

        # Analyze text structure
        structure_info = self._analyze_structure(text)

        # Build metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "rtf",
            "encoding": encoding,
            "paragraph_count": structure_info["paragraph_count"],
            "line_count": structure_info["line_count"],
            "word_count": structure_info["word_count"],
            "char_count": len(text),
        })

        return RawDocument(
            text=text,
            metadata=metadata,
            structure={
                "type": "rtf",
                "paragraph_count": structure_info["paragraph_count"],
                "has_lists": has_lists,
                "has_tables": has_tables,
            }
        )

    # ---------------------------------------------------------------- source

    @staticmethod
    def _codepage(raw: bytes) -> str:
        """Python codec for the document's ``\\ansicpgNNNN`` (default cp1252)."""
        match = _CODEPAGE.search(raw[:4096])
        if match:
            name = f"cp{int(match.group(1))}"
            try:
                codecs.lookup(name)
                return name
            except LookupError:
                pass
        return "cp1252"

    def _mark_structure(self, rtf: str) -> str:
        """Replace list labels, cell ends and soft breaks with sentinels."""
        groups = list(_LIST_GROUP.finditer(rtf))
        pars = [(m.start(), m.end()) for m in _PAR.finditer(rtf)] if groups else []
        # Old writers give no \ilvl; the left indent ranks nesting instead.
        indents: list[int | None] = []
        levels: list[int | None] = []
        for match in groups:
            segment = self._paragraph_around(rtf, pars, match.start(), match.end())
            ilvl = _ILVL.search(segment)
            levels.append(int(ilvl.group(1)) if ilvl else None)
            left = _LEFT_INDENT.findall(segment)
            indents.append(int(left[-1]) if left else None)
        ranked = sorted({i for i in indents if i is not None})

        out: list[str] = []
        pos = 0
        for match, level, indent in zip(groups, levels, indents, strict=True):
            if level is None:
                level = ranked.index(indent) if indent is not None else 0
            marker = self._marker(match.group(1))
            out.append(rtf[pos:match.start()])
            out.append("{" + self._sentinel(f"{_LIST}{level}{_LIST}{marker}{_LIST}") + "}")
            pos = match.end()
        out.append(rtf[pos:])
        marked = "".join(out)

        marked = re.sub(r"\\(?:nest)?cell(?![a-z])", lambda _: self._sentinel(_CELL), marked)
        marked = re.sub(r"\\line(?![a-z])", lambda _: self._sentinel(_BREAK), marked)
        return marked

    @staticmethod
    def _sentinel(text: str) -> str:
        """Plain ASCII text as RTF, control characters as ``\\'hh`` escapes."""
        return "".join(f"\\'{ord(ch):02x}" if ord(ch) < 32 else ch for ch in text)

    @staticmethod
    def _paragraph_around(rtf: str, pars: list[tuple[int, int]], start: int, end: int) -> str:
        """Source of the paragraph containing ``rtf[start:end]``; ``pars`` are ``\\par`` spans."""
        index = bisect.bisect_left(pars, (start,))
        begin = pars[index - 1][1] if index else 0
        after = bisect.bisect_left(pars, (end,))
        finish = pars[after][0] if after < len(pars) else len(rtf)
        return rtf[begin:finish]

    @staticmethod
    def _marker(label_source: str) -> str:
        """``-`` for a bullet label, or the literal ``1.`` / ``a)`` of a number."""
        label = _HEX.sub(lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), label_source)
        label = _CONTROL_WORD.sub("", label).replace("{", "").replace("}", "").strip()
        match = _ORDERED.match(label)
        if match:
            return f"{match.group(1)}{match.group(2)}"
        return "-"

    # ---------------------------------------------------------------- output

    def _to_markdown(self, plain: str) -> tuple[str, bool, bool]:
        """Rebuild Markdown from striprtf output carrying our sentinels."""
        builder = MarkdownBuilder()
        depth = ListDepth()
        table: list[list[str]] = []
        has_lists = has_tables = False

        def flush_table() -> None:
            nonlocal has_tables
            if table:
                builder.add_block(render_table(table))
                table.clear()
                has_tables = True

        for line in plain.split("\n"):
            if _CELL in line:
                cells = line.split(_CELL)
                if not cells[-1].strip():
                    cells = cells[:-1]
                table.append([c.replace(_BREAK, "\n").strip() for c in cells])
                continue
            flush_table()

            line = line.strip()
            if not line:
                continue

            level, marker, body = 0, None, line
            if line.startswith(_LIST):
                parts = line.split(_LIST, 3)
                if len(parts) == 4:
                    _, raw_level, marker, body = parts
                    level = int(raw_level) if raw_level.isdigit() else 0
            else:
                glyph = _GLYPH_BULLET.match(line)
                if glyph:
                    marker, body = "-", line[glyph.end():]

            body = "\n".join(part.strip() for part in body.split(_BREAK)).strip()
            if marker is not None:
                has_lists = True
                builder.add_list_item(list_item(body, depth.depth(level), marker))
            else:
                depth.reset()
                builder.add_block(body)
        flush_table()

        return builder.build(), has_lists, has_tables

    def _analyze_structure(self, text: str) -> dict[str, Any]:
        """Analyze text structure."""
        lines = text.split('\n')
        paragraphs = [p for p in text.split('\n\n') if p.strip()]

        return {
            "paragraph_count": len(paragraphs),
            "line_count": len([line for line in lines if line.strip()]),
            "word_count": len(text.split()),
        }
