"""
Output formatters for the Chomper CLI.

Provides multiple output format options for ParseResult, ChunkResult, and MetadataResult:
- TextFormatter: Plain text output (default)
- JSONFormatter: JSON output
- CSVFormatter: CSV format with proper escaping
- MarkdownFormatter: Markdown with headers and tables
- XMLFormatter: XML with proper escaping
- TemplateFormatter: Custom Jinja2 templates
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chomper import ChunkResult, MetadataResult, ParseResult


class OutputFormatter(ABC):
    """Base class for output formatters."""

    @abstractmethod
    def format_parse_result(self, result: ParseResult) -> str:
        """Format a parse result."""
        pass

    @abstractmethod
    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunk results."""
        pass

    @abstractmethod
    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata result."""
        pass


class TextFormatter(OutputFormatter):
    """Plain text formatter (default CLI output)."""

    def __init__(self, max_chars: int | None = None):
        """
        Initialize text formatter.

        Args:
            max_chars: Maximum characters to output (None = unlimited).
        """
        self.max_chars = max_chars

    def format_parse_result(self, result: ParseResult) -> str:
        """Format parse result as plain text."""
        text = result.text
        if self.max_chars and len(text) > self.max_chars:
            text = text[: self.max_chars] + "..."
        return text

    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunks as plain text."""
        lines = [
            f"Total chunks: {len(chunks)}",
            "=" * 60,
        ]

        for chunk in chunks:
            lines.append(f"\n--- Chunk {chunk.chunk_id} ({chunk.word_count} words) ---")
            if chunk.section_name:
                lines.append(f"Section: {chunk.section_name}")
            if chunk.keywords:
                lines.append(f"Keywords: {', '.join(chunk.keywords[:5])}")
            lines.append("")
            lines.append(chunk.text)

        return "\n".join(lines)

    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata as plain text."""
        lines = [
            f"File: {metadata.filename}",
            f"Format: {metadata.format}",
            f"Size: {metadata.file_size:,} bytes",
        ]

        if metadata.title:
            lines.append(f"Title: {metadata.title}")
        if metadata.author:
            lines.append(f"Author: {metadata.author}")
        if metadata.page_count:
            lines.append(f"Pages: {metadata.page_count}")
        if metadata.word_count:
            lines.append(f"Words: {metadata.word_count:,}")
        if metadata.image_count:
            lines.append(f"Images: {metadata.image_count}")

        return "\n".join(lines)


class JSONFormatter(OutputFormatter):
    """JSON formatter with pretty printing."""

    def __init__(self, indent: int = 2, ensure_ascii: bool = False):
        """
        Initialize JSON formatter.

        Args:
            indent: JSON indentation level.
            ensure_ascii: Whether to escape non-ASCII characters.
        """
        self.indent = indent
        self.ensure_ascii = ensure_ascii

    def _to_json(self, data: dict[str, Any]) -> str:
        """Convert data to JSON string."""
        return json.dumps(
            data, indent=self.indent, ensure_ascii=self.ensure_ascii, default=str
        )

    def format_parse_result(self, result: ParseResult) -> str:
        """Format parse result as JSON."""
        return self._to_json(
            {
                "file": result.file_path,
                "format": result.format,
                "word_count": result.word_count,
                "char_count": result.char_count,
                "metadata": result.metadata,
                "text": result.text,
            }
        )

    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunks as JSON."""
        chunk_data = [
            {
                "chunk_id": c.chunk_id,
                "text": c.text,
                "word_count": c.word_count,
                "start_char": c.start_char,
                "end_char": c.end_char,
                "keywords": c.keywords,
                "section_name": c.section_name,
            }
            for c in chunks
        ]
        return self._to_json(
            {
                "file": file_path,
                "total_chunks": len(chunks),
                "strategy": strategy,
                "chunks": chunk_data,
            }
        )

    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata as JSON."""
        return self._to_json(metadata.to_dict())


class CSVFormatter(OutputFormatter):
    """CSV formatter with proper escaping."""

    def __init__(self, delimiter: str = ",", quoting: int = csv.QUOTE_MINIMAL):
        """
        Initialize CSV formatter.

        Args:
            delimiter: Field delimiter character.
            quoting: CSV quoting mode.
        """
        self.delimiter = delimiter
        self.quoting = quoting

    def _write_csv(
        self, headers: list[str], rows: list[list[Any]]
    ) -> str:
        """Write CSV data to string."""
        output = io.StringIO()
        writer = csv.writer(
            output, delimiter=self.delimiter, quoting=self.quoting, lineterminator="\n"
        )
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        return output.getvalue()

    def format_parse_result(self, result: ParseResult) -> str:
        """Format parse result as CSV."""
        headers = ["file", "format", "word_count", "char_count", "metadata", "text"]
        metadata_json = json.dumps(result.metadata, ensure_ascii=False, default=str)
        rows = [
            [
                result.file_path,
                result.format,
                result.word_count,
                result.char_count,
                metadata_json,
                result.text,
            ]
        ]
        return self._write_csv(headers, rows)

    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunks as CSV."""
        headers = [
            "file",
            "strategy",
            "chunk_id",
            "word_count",
            "start_char",
            "end_char",
            "keywords",
            "section_name",
            "text",
        ]
        rows = [
            [
                file_path,
                strategy,
                c.chunk_id,
                c.word_count,
                c.start_char,
                c.end_char,
                ",".join(c.keywords) if c.keywords else "",
                c.section_name or "",
                c.text,
            ]
            for c in chunks
        ]
        return self._write_csv(headers, rows)

    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata as CSV."""
        headers = [
            "file_path",
            "filename",
            "format",
            "file_size",
            "author",
            "title",
            "page_count",
            "word_count",
            "image_count",
        ]
        rows = [
            [
                metadata.file_path,
                metadata.filename,
                metadata.format,
                metadata.file_size,
                metadata.author or "",
                metadata.title or "",
                metadata.page_count or "",
                metadata.word_count or "",
                metadata.image_count or "",
            ]
        ]
        return self._write_csv(headers, rows)


class MarkdownFormatter(OutputFormatter):
    """Markdown formatter with headers and tables."""

    def format_parse_result(self, result: ParseResult) -> str:
        """Format parse result as Markdown."""
        lines = [
            f"# Document: {Path(result.file_path).name}",
            "",
            f"**Format:** {result.format}  ",
            f"**Words:** {result.word_count:,}  ",
            f"**Characters:** {result.char_count:,}",
            "",
        ]

        # Add metadata table if present
        if result.metadata:
            lines.extend(
                [
                    "## Metadata",
                    "",
                    "| Key | Value |",
                    "|-----|-------|",
                ]
            )
            for key, value in result.metadata.items():
                # Escape pipe characters in values
                value_str = str(value).replace("|", "\\|")
                lines.append(f"| {key} | {value_str} |")
            lines.append("")

        # Add content
        lines.extend(
            [
                "## Content",
                "",
                result.text,
            ]
        )

        return "\n".join(lines)

    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunks as Markdown."""
        lines = [
            f"# Chunks: {Path(file_path).name}",
            "",
            f"**Total Chunks:** {len(chunks)}  ",
            f"**Strategy:** {strategy}",
            "",
            "---",
            "",
        ]

        for chunk in chunks:
            lines.append(f"## Chunk {chunk.chunk_id}")
            lines.append("")
            lines.append(f"**Words:** {chunk.word_count}  ")
            lines.append(f"**Position:** {chunk.start_char}-{chunk.end_char}")

            if chunk.section_name:
                lines.append(f"**Section:** {chunk.section_name}")
            if chunk.keywords:
                lines.append(f"**Keywords:** {', '.join(chunk.keywords)}")

            lines.extend(
                [
                    "",
                    "```",
                    chunk.text,
                    "```",
                    "",
                    "---",
                    "",
                ]
            )

        return "\n".join(lines)

    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata as Markdown."""
        lines = [
            f"# Metadata: {metadata.filename}",
            "",
            "## File Information",
            "",
            "| Property | Value |",
            "|----------|-------|",
            f"| File | {metadata.filename} |",
            f"| Format | {metadata.format} |",
            f"| Size | {metadata.file_size:,} bytes |",
            f"| Path | {metadata.file_path} |",
            "",
        ]

        # Document metadata section
        doc_meta = []
        if metadata.title:
            doc_meta.append(f"| Title | {metadata.title} |")
        if metadata.author:
            doc_meta.append(f"| Author | {metadata.author} |")
        if metadata.subject:
            doc_meta.append(f"| Subject | {metadata.subject} |")
        if metadata.creator:
            doc_meta.append(f"| Creator | {metadata.creator} |")
        if metadata.producer:
            doc_meta.append(f"| Producer | {metadata.producer} |")
        if metadata.created:
            doc_meta.append(f"| Created | {metadata.created} |")
        if metadata.modified:
            doc_meta.append(f"| Modified | {metadata.modified} |")

        if doc_meta:
            lines.extend(
                [
                    "## Document Properties",
                    "",
                    "| Property | Value |",
                    "|----------|-------|",
                ]
            )
            lines.extend(doc_meta)
            lines.append("")

        # Statistics section
        stats = []
        if metadata.page_count:
            stats.append(f"| Pages | {metadata.page_count} |")
        if metadata.word_count:
            stats.append(f"| Words | {metadata.word_count:,} |")
        if metadata.text_length:
            stats.append(f"| Characters | {metadata.text_length:,} |")
        if metadata.image_count:
            stats.append(f"| Images | {metadata.image_count} |")

        if stats:
            lines.extend(
                [
                    "## Statistics",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                ]
            )
            lines.extend(stats)
            lines.append("")

        return "\n".join(lines)


class XMLFormatter(OutputFormatter):
    """XML formatter with proper escaping."""

    def __init__(self, indent: str = "  "):
        """
        Initialize XML formatter.

        Args:
            indent: String to use for indentation.
        """
        self.indent = indent

    def _indent_xml(self, elem: ET.Element, level: int = 0) -> None:
        """Add indentation to XML element."""
        i = "\n" + level * self.indent
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + self.indent
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for child in elem:
                self._indent_xml(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convert element to indented XML string."""
        self._indent_xml(root)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    def _add_dict_elements(
        self, parent: ET.Element, data: dict[str, Any], parent_name: str = "item"
    ) -> None:
        """Add dictionary items as child elements."""
        for key, value in data.items():
            # Sanitize key for XML element name
            safe_key = self._sanitize_tag_name(key)
            child = ET.SubElement(parent, safe_key)

            if isinstance(value, dict):
                self._add_dict_elements(child, value, safe_key)
            elif isinstance(value, list):
                for item in value:
                    item_elem = ET.SubElement(child, "item")
                    if isinstance(item, dict):
                        self._add_dict_elements(item_elem, item)
                    else:
                        item_elem.text = str(item) if item is not None else ""
            else:
                child.text = str(value) if value is not None else ""

    def _sanitize_tag_name(self, name: str) -> str:
        """Sanitize a string to be a valid XML tag name."""
        # Replace invalid characters with underscore
        result = ""
        for i, char in enumerate(name):
            if i == 0:
                # First character must be letter or underscore
                if char.isalpha() or char == "_":
                    result += char
                else:
                    result += "_" + char if char.isalnum() else "_"
            else:
                # Subsequent characters can be letters, digits, hyphens, underscores, periods
                if char.isalnum() or char in "-_.":
                    result += char
                else:
                    result += "_"
        return result or "item"

    def format_parse_result(self, result: ParseResult) -> str:
        """Format parse result as XML."""
        root = ET.Element("document")

        ET.SubElement(root, "file").text = result.file_path
        ET.SubElement(root, "format").text = result.format
        ET.SubElement(root, "word_count").text = str(result.word_count)
        ET.SubElement(root, "char_count").text = str(result.char_count)

        # Metadata
        metadata_elem = ET.SubElement(root, "metadata")
        self._add_dict_elements(metadata_elem, result.metadata)

        # Text content
        ET.SubElement(root, "text").text = result.text

        return self._to_xml_string(root)

    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunks as XML."""
        root = ET.Element("chunks")
        root.set("file", file_path)
        root.set("strategy", strategy)
        root.set("total", str(len(chunks)))

        for chunk in chunks:
            chunk_elem = ET.SubElement(root, "chunk")
            chunk_elem.set("id", str(chunk.chunk_id))

            ET.SubElement(chunk_elem, "word_count").text = str(chunk.word_count)
            ET.SubElement(chunk_elem, "start_char").text = str(chunk.start_char)
            ET.SubElement(chunk_elem, "end_char").text = str(chunk.end_char)

            if chunk.section_name:
                ET.SubElement(chunk_elem, "section_name").text = chunk.section_name

            if chunk.keywords:
                keywords_elem = ET.SubElement(chunk_elem, "keywords")
                for kw in chunk.keywords:
                    ET.SubElement(keywords_elem, "keyword").text = kw

            ET.SubElement(chunk_elem, "text").text = chunk.text

        return self._to_xml_string(root)

    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata as XML."""
        root = ET.Element("metadata")

        # File info
        file_info = ET.SubElement(root, "file_info")
        ET.SubElement(file_info, "file_path").text = metadata.file_path
        ET.SubElement(file_info, "filename").text = metadata.filename
        ET.SubElement(file_info, "format").text = metadata.format
        ET.SubElement(file_info, "file_size").text = str(metadata.file_size)

        # Document properties
        doc_props = ET.SubElement(root, "document_properties")
        if metadata.title:
            ET.SubElement(doc_props, "title").text = metadata.title
        if metadata.author:
            ET.SubElement(doc_props, "author").text = metadata.author
        if metadata.subject:
            ET.SubElement(doc_props, "subject").text = metadata.subject
        if metadata.creator:
            ET.SubElement(doc_props, "creator").text = metadata.creator
        if metadata.producer:
            ET.SubElement(doc_props, "producer").text = metadata.producer
        if metadata.created:
            ET.SubElement(doc_props, "created").text = metadata.created
        if metadata.modified:
            ET.SubElement(doc_props, "modified").text = metadata.modified

        # Statistics
        stats = ET.SubElement(root, "statistics")
        if metadata.page_count is not None:
            ET.SubElement(stats, "page_count").text = str(metadata.page_count)
        if metadata.word_count is not None:
            ET.SubElement(stats, "word_count").text = str(metadata.word_count)
        if metadata.text_length is not None:
            ET.SubElement(stats, "text_length").text = str(metadata.text_length)
        if metadata.image_count is not None:
            ET.SubElement(stats, "image_count").text = str(metadata.image_count)

        return self._to_xml_string(root)


class TemplateFormatter(OutputFormatter):
    """Custom Jinja2 template formatter."""

    def __init__(self, template_path: str | Path | None = None, template_string: str | None = None):
        """
        Initialize template formatter.

        Args:
            template_path: Path to Jinja2 template file.
            template_string: Jinja2 template string (alternative to path).

        Raises:
            ImportError: If Jinja2 is not installed.
            ValueError: If neither template_path nor template_string is provided.
        """
        try:
            from jinja2 import BaseLoader, Environment, FileSystemLoader
        except ImportError as e:
            raise ImportError(
                "Jinja2 is required for template formatting. "
                "Install it with: pip install jinja2"
            ) from e

        if template_path:
            template_path = Path(template_path)
            if not template_path.exists():
                raise ValueError(f"Template file not found: {template_path}")

            env = Environment(
                loader=FileSystemLoader(template_path.parent),
                autoescape=False,
            )
            self.template = env.get_template(template_path.name)
        elif template_string:
            env = Environment(loader=BaseLoader(), autoescape=False)
            self.template = env.from_string(template_string)
        else:
            raise ValueError("Either template_path or template_string must be provided")

    def format_parse_result(self, result: ParseResult) -> str:
        """Format parse result using template."""
        return self.template.render(
            result=result,
            file=result.file_path,
            format=result.format,
            word_count=result.word_count,
            char_count=result.char_count,
            metadata=result.metadata,
            text=result.text,
            mode="parse",
        )

    def format_chunks(
        self, chunks: list[ChunkResult], file_path: str, strategy: str
    ) -> str:
        """Format chunks using template."""
        return self.template.render(
            chunks=chunks,
            file=file_path,
            strategy=strategy,
            total_chunks=len(chunks),
            mode="chunks",
        )

    def format_metadata(self, metadata: MetadataResult) -> str:
        """Format metadata using template."""
        return self.template.render(
            metadata=metadata,
            file_path=metadata.file_path,
            filename=metadata.filename,
            format=metadata.format,
            file_size=metadata.file_size,
            mode="metadata",
        )


def get_formatter(
    format_name: str,
    *,
    template_path: str | Path | None = None,
    max_chars: int | None = None,
) -> OutputFormatter:
    """
    Get a formatter instance by name.

    Args:
        format_name: One of "text", "json", "csv", "markdown", "xml", "template".
        template_path: Path to Jinja2 template (required for "template" format).
        max_chars: Maximum characters for text output.

    Returns:
        OutputFormatter instance.

    Raises:
        ValueError: If format_name is invalid or template required but not provided.
    """
    format_name = format_name.lower()

    if format_name == "text":
        return TextFormatter(max_chars=max_chars)
    elif format_name == "json":
        return JSONFormatter()
    elif format_name == "csv":
        return CSVFormatter()
    elif format_name == "markdown":
        return MarkdownFormatter()
    elif format_name == "xml":
        return XMLFormatter()
    elif format_name == "template":
        if not template_path:
            raise ValueError("--template FILE is required when using --format template")
        return TemplateFormatter(template_path=template_path)
    else:
        raise ValueError(
            f"Unknown format: {format_name}. "
            f"Valid formats: text, json, csv, markdown, xml, template"
        )
