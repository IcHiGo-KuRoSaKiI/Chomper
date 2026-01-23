"""
Markdown extractor with header-aware structure.

Extracts content from Markdown files preserving heading hierarchy.
"""
import re
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor


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
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Extract structure
        structure = self._extract_sections(content)

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "markdown",
            "heading_count": sum(1 for s in structure.get("sections", []) if s.get("heading"))
        })

        return RawDocument(
            text=content,
            metadata=metadata,
            structure=structure
        )

    def _extract_sections(self, content: str) -> dict[str, Any]:
        """
        Extract sections based on heading hierarchy.

        Args:
            content: Markdown content

        Returns:
            Structure dictionary with sections
        """
        sections = []
        lines = content.splitlines()

        current_section = None
        current_content = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check for ATX-style headers (# Header)
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)

            # Check for Setext-style headers (underlined)
            setext_heading = None
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if re.match(r'^=+\s*$', next_line):
                    setext_heading = (1, line)  # H1
                    i += 1  # Skip underline
                elif re.match(r'^-+\s*$', next_line):
                    setext_heading = (2, line)  # H2
                    i += 1  # Skip underline

            if heading_match or setext_heading:
                # Save previous section
                if current_section is not None:
                    current_section["content"] = current_content
                    sections.append(current_section)

                # Start new section
                if heading_match:
                    level = len(heading_match.group(1))
                    heading = heading_match.group(2).strip()
                else:
                    level, heading = setext_heading

                current_section = {
                    "heading": heading,
                    "level": level,
                    "content": []
                }
                current_content = []

            else:
                # Add to current section
                if current_section is None:
                    # Create default section for content before first heading
                    current_section = {
                        "heading": None,
                        "level": 0,
                        "content": []
                    }

                # Detect special content types
                content_item = self._classify_line(line)
                current_content.append(content_item)

            i += 1

        # Add final section
        if current_section is not None:
            current_section["content"] = current_content
            sections.append(current_section)

        return {"sections": sections}

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
