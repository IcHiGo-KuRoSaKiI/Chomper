"""
Markdown extractor with header-aware structure.

Extracts content from Markdown files preserving heading hierarchy.
"""
import re
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor
from .encoding_utils import read_text

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_SETEXT_H1 = re.compile(r"^ {0,3}=+[ \t]*$")
_SETEXT_H2 = re.compile(r"^ {0,3}-+[ \t]*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])(?:\s|$)")


class MarkdownExtractor(BaseExtractor):
    """
    Extract content from Markdown files.

    Features:
    - Heading hierarchy detection (H1-H6)
    - Section structure based on headings
    - Code block detection
    - Link and image extraction
    """

    SUPPORTED_EXTENSIONS = ['.md', '.markdown']

    def __init__(self):
        """Initialize markdown extractor."""
        pass

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from Markdown file.

        Args:
            file_path: Path to Markdown file

        Returns:
            RawDocument with extracted content
        """
        self.validate_file(file_path)

        # Read file content
        content, encoding = read_text(file_path)

        # Extract structure
        structure = self._extract_sections(content)

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "markdown",
            "heading_count": sum(1 for s in structure.get("sections", []) if s.get("heading")),
            "encoding": encoding,
        })

        return RawDocument(
            text=content,
            metadata=metadata,
            structure=structure
        )

    def _extract_sections(self, content: str) -> dict[str, Any]:
        """
        Split Markdown into sections at its headings.

        Only real headings count. Lines inside fenced code blocks (```` ``` ````
        or ``~~~``) are code, however much they look like ``# headings``; YAML
        front matter at the top of the file is skipped; and a ``---`` line is a
        setext underline only directly below paragraph text, never below a
        blank line, list item, table row, quote, heading or code.

        Args:
            content: Markdown content

        Returns:
            Structure dictionary with sections. Fence lines are
            ``code_fence`` items and the lines between them ``code`` items.
        """
        sections: list[dict[str, Any]] = []
        lines = content.splitlines()
        current: dict[str, Any] | None = None

        def add(item: dict[str, Any]) -> None:
            nonlocal current
            if current is None:
                # Content before the first heading.
                current = {"heading": None, "level": 0, "content": []}
            current["content"].append(item)

        def start(level: int, heading: str) -> None:
            nonlocal current
            if current is not None:
                sections.append(current)
            current = {"heading": heading, "level": level, "content": []}

        i = self._front_matter_end(lines)
        for line in lines[:i]:
            add({"type": "front_matter", "text": line})

        fence: str | None = None
        while i < len(lines):
            line = lines[i]

            if fence is not None:
                closing = _FENCE.match(line)
                if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence) \
                        and not closing.group(2).strip():
                    add({"type": "code_fence", "text": line})
                    fence = None
                else:
                    add({"type": "code", "text": line})
                i += 1
                continue

            opening = _FENCE.match(line)
            if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
                fence = opening.group(1)
                add({"type": "code_fence", "text": line})
                i += 1
                continue

            atx = _ATX.match(line)
            if atx:
                start(len(atx.group(1)), re.sub(r"\s+#+\s*$", "", atx.group(2)).strip())
                i += 1
                continue

            if i + 1 < len(lines) and self._is_setext_text(line):
                underline = lines[i + 1]
                if _SETEXT_H1.match(underline):
                    start(1, line.strip())
                    i += 2
                    continue
                if _SETEXT_H2.match(underline):
                    start(2, line.strip())
                    i += 2
                    continue

            add(self._classify_line(line))
            i += 1

        if current is not None:
            sections.append(current)

        return {"sections": sections}

    @staticmethod
    def _front_matter_end(lines: list[str]) -> int:
        """Index just past a leading ``---`` ... ``---`` YAML block, or 0."""
        if not lines or lines[0].strip() != "---":
            return 0
        for index in range(1, len(lines)):
            if lines[index].strip() in ("---", "..."):
                return index + 1
        return 0

    @staticmethod
    def _is_setext_text(line: str) -> bool:
        """Whether ``line`` is paragraph text a setext underline can turn into a heading."""
        if not line.strip() or line.startswith("    ") or line.startswith("\t"):
            return False
        stripped = line.strip()
        return not (
            _ATX.match(line)
            or _FENCE.match(line)
            or _LIST_ITEM.match(line)
            or stripped.startswith(">")
            or stripped.startswith("|")
            or "|" in stripped and stripped.count("|") >= 2
            or _SETEXT_H2.match(line)
            or _SETEXT_H1.match(line)
        )

    def _classify_line(self, line: str) -> dict[str, Any]:
        """
        Classify a line of content.

        Args:
            line: Line of text

        Returns:
            Content item dictionary
        """
        # Code block fence
        if line.strip().startswith('```'):
            return {"type": "code_fence", "text": line}

        # List item
        if re.match(r'^\s*[-*+]\s+', line) or re.match(r'^\s*\d+\.\s+', line):
            return {"type": "list_item", "text": line}

        # Link
        if re.search(r'\[([^\]]+)\]\(([^)]+)\)', line):
            return {"type": "link", "text": line}

        # Image
        if re.search(r'!\[([^\]]*)\]\(([^)]+)\)', line):
            return {"type": "image", "text": line}

        # Blockquote
        if line.strip().startswith('>'):
            return {"type": "blockquote", "text": line}

        # Regular text
        return {"type": "text", "text": line}
