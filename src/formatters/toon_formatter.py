"""
TOON (Token-Optimized Object Notation) formatter.

Outputs compact, token-efficient format for LLM consumption.
Achieves ~40% token reduction compared to JSON while remaining parseable.

TOON Schema:
    d:<doc_id>|t:<type>|w:<words>|c:<chars>|p:<pages>|i:<images>
    m:author=<value>,title=<value>
    ---
    <id>|<start>-<end>|<type>|<section_name>
    <text content>
    k:<keyword1>,<keyword2>
"""
from typing import Any

from ..models.document import EnrichedChunk, ProcessedDocument
from .base import BaseFormatter


class TOONFormatter(BaseFormatter):
    """
    Format documents as TOON (Token-Optimized Object Notation).

    Use Case:
    - LLM context windows (reduced token usage)
    - Fast parsing with minimal overhead
    - Human-readable compact format

    Output:
    - Line-based records
    - Minimal delimiters (| for fields, --- for sections)
    - No JSON overhead (quotes, braces, etc.)
    """

    SECTION_DELIMITER = "---"
    FIELD_DELIMITER = "|"
    KV_DELIMITER = "="
    LIST_DELIMITER = ","

    def __init__(
        self,
        include_metadata: bool = True,
        include_keywords: bool = True,
        max_text_preview: int | None = None
    ):
        """
        Initialize TOON formatter.

        Args:
            include_metadata: Include metadata line (default: True)
            include_keywords: Include keywords for chunks (default: True)
            max_text_preview: Max chars per chunk text (None = full text)
        """
        self.include_metadata = include_metadata
        self.include_keywords = include_keywords
        self.max_text_preview = max_text_preview

    def format(self, document: ProcessedDocument) -> str:
        """
        Format ProcessedDocument as TOON string.

        Args:
            document: ProcessedDocument to format

        Returns:
            TOON-formatted string
        """
        self._validate_document(document)

        lines = []

        # Document header
        lines.append(self._format_header(document))

        # Metadata line (optional)
        if self.include_metadata and document.metadata:
            meta_line = self._format_metadata(document.metadata)
            if meta_line:
                lines.append(meta_line)

        # Chunks
        for chunk in document.chunks:
            lines.append(self.SECTION_DELIMITER)
            lines.extend(self._format_chunk(chunk))

        return "\n".join(lines)

    def _format_header(self, document: ProcessedDocument) -> str:
        """Format document header line."""
        parts = [
            f"d:{self._escape_field(document.document_id)}",
            f"t:{document.doc_type}",
        ]

        if document.source:
            # Only include filename, not full path
            source_name = document.source.split("/")[-1].split("\\")[-1]
            parts.append(f"s:{self._escape_field(source_name)}")

        # Add computed stats
        parts.append(f"w:{document.total_words}")
        parts.append(f"n:{document.total_chunks}")

        # Page count if available
        if "page_count" in document.metadata:
            parts.append(f"p:{document.metadata['page_count']}")

        return self.FIELD_DELIMITER.join(parts)

    def _format_metadata(self, metadata: dict[str, Any]) -> str | None:
        """Format metadata as key=value pairs."""
        # Select important metadata fields only
        important_keys = ["author", "title", "created", "modified", "subject"]
        pairs = []

        for key in important_keys:
            if key in metadata and metadata[key]:
                value = str(metadata[key])
                value = self._escape_value(value)
                pairs.append(f"{key}{self.KV_DELIMITER}{value}")

        if pairs:
            return f"m:{self.LIST_DELIMITER.join(pairs)}"
        return None

    def _format_chunk(self, chunk: EnrichedChunk) -> list[str]:
        """Format single chunk as TOON lines."""
        lines = []

        # Chunk header: id|start-end|type|name
        header_parts = [
            str(chunk.chunk_id),
            f"{chunk.start_char}-{chunk.end_char}",
            chunk.section_type or "text",
            self._escape_field(chunk.section_name or "")
        ]
        lines.append(self.FIELD_DELIMITER.join(header_parts))

        # Text content
        text = chunk.text
        if self.max_text_preview and len(text) > self.max_text_preview:
            text = text[:self.max_text_preview] + "..."
        lines.append(text)

        # Keywords
        if self.include_keywords and chunk.keywords:
            keywords_str = self.LIST_DELIMITER.join(chunk.keywords[:10])
            lines.append(f"k:{keywords_str}")

        return lines

    def _escape_field(self, text: str) -> str:
        """Escape field delimiters in single-line fields."""
        if not text:
            return ""
        return text.replace("|", "\\|").replace("\n", " ")

    def _escape_value(self, text: str) -> str:
        """Escape value delimiters in metadata values."""
        if not text:
            return ""
        return text.replace(",", "\\,").replace("=", "\\=").replace("\n", " ")

    def format_chunks(self, chunks: list[EnrichedChunk]) -> str:
        """Format just chunks without document wrapper."""
        lines = []
        for chunk in chunks:
            lines.append(self.SECTION_DELIMITER)
            lines.extend(self._format_chunk(chunk))
        return "\n".join(lines)

    @staticmethod
    def format_raw(
        file_path: str,
        text: str,
        metadata: dict[str, Any],
        doc_type: str,
        total_chars: int,
        total_words: int,
        page_count: int | None = None,
        image_count: int | None = None,
        truncated: bool = False,
        continuation_offset: int | None = None
    ) -> str:
        """
        Format raw document data as TOON (for server use without full pipeline).

        Args:
            file_path: Document file path
            text: Document text content
            metadata: Document metadata dict
            doc_type: Document type (pdf, docx, etc.)
            total_chars: Total character count
            total_words: Total word count
            page_count: Number of pages (optional)
            image_count: Number of images (optional)
            truncated: Whether text is truncated
            continuation_offset: Offset for continuation (if truncated)

        Returns:
            TOON-formatted string
        """
        lines = []

        # Extract filename from path
        filename = file_path.split("/")[-1].split("\\")[-1]

        # Header
        parts = [f"d:{filename}", f"t:{doc_type}", f"w:{total_words}", f"c:{total_chars}"]
        if page_count:
            parts.append(f"p:{page_count}")
        if image_count:
            parts.append(f"i:{image_count}")
        lines.append("|".join(parts))

        # Metadata
        meta_parts = []
        for key in ["author", "title", "subject"]:
            if key in metadata and metadata[key]:
                val = str(metadata[key]).replace(",", "\\,").replace("=", "\\=")
                meta_parts.append(f"{key}={val}")
        if meta_parts:
            lines.append(f"m:{','.join(meta_parts)}")

        # Continuation hint (if truncated)
        if truncated and continuation_offset is not None:
            remaining = total_chars - continuation_offset
            lines.append(f"~+{remaining}chars|use:get_document_chunk(offset={continuation_offset})")

        # Content section
        lines.append("---")
        lines.append("content")
        lines.append(text)

        return "\n".join(lines)

    @staticmethod
    def format_metadata_only(
        file_path: str,
        metadata: dict[str, Any],
        doc_type: str,
        total_chars: int,
        page_count: int | None = None
    ) -> str:
        """
        Format metadata-only response as TOON.

        Args:
            file_path: Document file path
            metadata: Document metadata dict
            doc_type: Document type
            total_chars: Total character count
            page_count: Number of pages (optional)

        Returns:
            TOON-formatted metadata string
        """
        filename = file_path.split("/")[-1].split("\\")[-1]

        # Header
        parts = [f"d:{filename}", f"t:{doc_type}", f"c:{total_chars}"]
        if page_count:
            parts.append(f"p:{page_count}")

        lines = ["|".join(parts)]

        # All metadata as key=value pairs
        meta_parts = []
        for key, val in metadata.items():
            if isinstance(val, (str, int, float, bool)) and val:
                val_str = str(val).replace(",", "\\,").replace("=", "\\=").replace("\n", " ")
                if len(val_str) <= 100:  # Skip very long values
                    meta_parts.append(f"{key}={val_str}")

        if meta_parts:
            lines.append(f"m:{','.join(meta_parts[:15])}")  # Limit to 15 fields

        return "\n".join(lines)

    @staticmethod
    def format_chunk_response(
        file_path: str,
        text: str,
        offset: int,
        limit: int,
        total_chars: int,
        has_more: bool
    ) -> str:
        """
        Format chunk retrieval response as TOON.

        Args:
            file_path: Document file path
            text: Chunk text content
            offset: Current offset
            limit: Requested limit
            total_chars: Total document chars
            has_more: Whether more content exists

        Returns:
            TOON-formatted chunk response
        """
        filename = file_path.split("/")[-1].split("\\")[-1]

        lines = [
            f"d:{filename}|offset:{offset}|limit:{limit}|total:{total_chars}"
        ]

        if has_more:
            next_offset = offset + len(text)
            remaining = total_chars - next_offset
            lines.append(f"~+{remaining}chars|next:get_document_chunk(offset={next_offset})")

        lines.append("---")
        lines.append(text)

        return "\n".join(lines)
