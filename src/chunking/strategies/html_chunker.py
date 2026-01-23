"""
HTML chunking strategies.

Provides 4 chunking strategies for HTML documents:
1. semantic: Chunk by semantic sections (article, section, nav, etc.)
2. structural: Chunk by heading hierarchy (h1-h6)
3. fixed_size: Fixed character-count chunks with paragraph boundaries
4. auto: Intelligent selection based on document structure
"""
import logging
import re
from typing import Any

from ...models.document import Chunk, RawDocument
from ...models.html_models import HTMLDocument, HTMLTable
from ..base import BaseChunker

logger = logging.getLogger(__name__)


class HTMLChunker(BaseChunker):
    """
    Chunk HTML documents using intelligent strategies.

    Strategies:
    - semantic: Chunk by semantic HTML5 sections (article, section, nav, etc.)
    - structural: Chunk by heading hierarchy (h1, h2, h3, etc.)
    - fixed_size: Fixed character-count chunks with paragraph boundaries
    - auto: Automatically select best strategy based on document structure

    Features:
    - Preserves tables as separate chunks
    - Respects paragraph boundaries
    - Includes heading context in chunks
    - Handles nested sections
    """

    def __init__(
        self,
        strategy: str = "auto",
        chunk_size: int = 1000,
        include_tables_separately: bool = True,
        preserve_headings: bool = True,
        overlap_size: int = 100
    ):
        """
        Initialize HTML chunker.

        Args:
            strategy: Chunking strategy ("semantic", "structural", "fixed_size", "auto")
            chunk_size: Target chunk size in characters (for fixed_size strategy)
            include_tables_separately: Extract tables as separate chunks
            preserve_headings: Include heading text in each chunk
            overlap_size: Overlap between fixed-size chunks
        """
        if strategy not in ["semantic", "structural", "fixed_size", "auto"]:
            raise ValueError(f"Invalid strategy: {strategy}")

        self.strategy = strategy
        self.chunk_size = chunk_size
        self.include_tables_separately = include_tables_separately
        self.preserve_headings = preserve_headings
        self.overlap_size = overlap_size

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk HTML document using selected strategy.

        Args:
            raw_doc: RawDocument with HTML structure

        Returns:
            List of chunks
        """
        html_doc = raw_doc.structure.get('html_document')

        if not html_doc:
            # Fallback to fixed-size chunking if no HTML structure
            logger.warning("No HTML structure found, using fixed-size chunking")
            return self._chunk_fixed_size(raw_doc.text, raw_doc.metadata)

        # Auto-select strategy if needed
        if self.strategy == "auto":
            selected_strategy = self._auto_select_strategy(html_doc)
            logger.info(f"Auto-selected strategy: {selected_strategy}")
        else:
            selected_strategy = self.strategy

        # Execute selected strategy
        if selected_strategy == "semantic":
            chunks = self._chunk_semantic(html_doc, raw_doc.metadata)
        elif selected_strategy == "structural":
            chunks = self._chunk_structural(raw_doc.text, html_doc, raw_doc.metadata)
        else:  # fixed_size
            chunks = self._chunk_fixed_size(html_doc.main_content, raw_doc.metadata)

        # Add tables as separate chunks if enabled
        if self.include_tables_separately and html_doc.tables:
            table_chunks = self._chunk_tables(html_doc.tables, raw_doc.metadata)
            chunks.extend(table_chunks)

        return chunks

    def _auto_select_strategy(self, html_doc: HTMLDocument) -> str:
        """
        Automatically select best chunking strategy.

        Logic:
        - Has semantic sections (article, section) → semantic
        - Has clear heading structure (3+ levels) → structural
        - Otherwise → fixed_size

        Args:
            html_doc: HTMLDocument object

        Returns:
            Selected strategy name
        """
        # Check for semantic sections
        if html_doc.num_sections >= 3:
            semantic_tags = {'article', 'section', 'aside'}
            has_semantic = any(
                section.tag in semantic_tags
                for section in html_doc.sections
            )
            if has_semantic:
                return "semantic"

        # Check for heading structure
        if html_doc.num_headings >= 5:
            # Has clear heading structure
            return "structural"

        # Default to fixed-size
        return "fixed_size"

    def _chunk_semantic(
        self,
        html_doc: HTMLDocument,
        metadata: dict[str, Any]
    ) -> list[Chunk]:
        """
        Chunk by semantic HTML sections.

        Creates one chunk per semantic section (article, section, nav, aside).

        Args:
            html_doc: HTMLDocument object
            metadata: Document metadata

        Returns:
            List of chunks
        """
        chunks = []
        chunk_id = 0

        for section in html_doc.sections:
            # Skip empty sections
            if section.is_empty:
                continue

            # Build chunk text
            chunk_text = ""
            if section.heading and self.preserve_headings:
                chunk_text = f"{section.heading}\n\n"

            chunk_text += section.text

            # Create chunk
            chunk = Chunk(
                chunk_id=f"chunk_{chunk_id}",
                text=chunk_text,
                start_char=section.start_char,
                end_char=section.end_char,
                metadata={
                    **metadata,
                    "chunk_strategy": "semantic",
                    "section_tag": section.tag,
                    "section_heading": section.heading,
                    "heading_level": section.heading_level,
                    "section_index": section.section_index,
                    "has_subsections": section.has_subsections
                }
            )
            chunks.append(chunk)
            chunk_id += 1

        return chunks

    def _chunk_structural(
        self,
        full_text: str,
        html_doc: HTMLDocument,
        metadata: dict[str, Any]
    ) -> list[Chunk]:
        """
        Chunk by heading hierarchy.

        Splits document at each heading (h1-h6) and includes heading in chunk.

        Args:
            full_text: Full document text
            html_doc: HTMLDocument object
            metadata: Document metadata

        Returns:
            List of chunks
        """
        chunks = []
        chunk_id = 0

        # Split by headings using main content
        text = html_doc.main_content
        if not text:
            text = full_text

        # Simple approach: Split on double newlines (paragraph boundaries)
        # and group paragraphs between headings
        paragraphs = text.split('\n\n')
        current_chunk_text = []
        current_heading = None
        current_heading_level = None

        heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$')  # Markdown-style headings
        start_char = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Check if paragraph is a heading
            match = heading_pattern.match(para)
            is_heading = match is not None

            if is_heading:
                # Save previous chunk
                if current_chunk_text:
                    chunk_text = '\n\n'.join(current_chunk_text)
                    end_char = start_char + len(chunk_text)

                    chunk = Chunk(
                        chunk_id=f"chunk_{chunk_id}",
                        text=chunk_text,
                        start_char=start_char,
                        end_char=end_char,
                        metadata={
                            **metadata,
                            "chunk_strategy": "structural",
                            "heading": current_heading,
                            "heading_level": current_heading_level
                        }
                    )
                    chunks.append(chunk)
                    chunk_id += 1
                    start_char = end_char

                # Start new chunk with heading
                current_heading = match.group(2)
                current_heading_level = len(match.group(1))
                current_chunk_text = [para]
            else:
                current_chunk_text.append(para)

        # Add final chunk
        if current_chunk_text:
            chunk_text = '\n\n'.join(current_chunk_text)
            end_char = start_char + len(chunk_text)

            chunk = Chunk(
                chunk_id=f"chunk_{chunk_id}",
                text=chunk_text,
                start_char=start_char,
                end_char=end_char,
                metadata={
                    **metadata,
                    "chunk_strategy": "structural",
                    "heading": current_heading,
                    "heading_level": current_heading_level
                }
            )
            chunks.append(chunk)

        return chunks

    def _chunk_fixed_size(
        self,
        text: str,
        metadata: dict[str, Any]
    ) -> list[Chunk]:
        """
        Chunk by fixed character count with paragraph boundaries.

        Args:
            text: Document text
            metadata: Document metadata

        Returns:
            List of chunks
        """
        chunks = []
        chunk_id = 0

        # Split into paragraphs
        paragraphs = text.split('\n\n')
        current_chunk_paras = []
        current_size = 0
        start_char = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_size = len(para)

            # Check if adding this paragraph exceeds chunk size
            if current_size + para_size > self.chunk_size and current_chunk_paras:
                # Save current chunk
                chunk_text = '\n\n'.join(current_chunk_paras)
                end_char = start_char + len(chunk_text)

                chunk = Chunk(
                    chunk_id=f"chunk_{chunk_id}",
                    text=chunk_text,
                    start_char=start_char,
                    end_char=end_char,
                    metadata={
                        **metadata,
                        "chunk_strategy": "fixed_size",
                        "chunk_size": self.chunk_size,
                        "actual_size": len(chunk_text)
                    }
                )
                chunks.append(chunk)
                chunk_id += 1

                # Add overlap from previous chunk
                if self.overlap_size > 0 and current_chunk_paras:
                    overlap_text = current_chunk_paras[-1]
                    if len(overlap_text) <= self.overlap_size:
                        current_chunk_paras = [overlap_text]
                        current_size = len(overlap_text)
                    else:
                        current_chunk_paras = []
                        current_size = 0
                else:
                    current_chunk_paras = []
                    current_size = 0

                start_char = end_char - (len(overlap_text) if self.overlap_size > 0 else 0)

            # Add paragraph to current chunk
            current_chunk_paras.append(para)
            current_size += para_size

        # Add final chunk
        if current_chunk_paras:
            chunk_text = '\n\n'.join(current_chunk_paras)
            end_char = start_char + len(chunk_text)

            chunk = Chunk(
                chunk_id=f"chunk_{chunk_id}",
                text=chunk_text,
                start_char=start_char,
                end_char=end_char,
                metadata={
                    **metadata,
                    "chunk_strategy": "fixed_size",
                    "chunk_size": self.chunk_size,
                    "actual_size": len(chunk_text)
                }
            )
            chunks.append(chunk)

        return chunks

    def _chunk_tables(
        self,
        tables: list[HTMLTable],
        metadata: dict[str, Any]
    ) -> list[Chunk]:
        """
        Extract tables as separate chunks.

        Converts tables to HTML format for better LLM understanding.

        Args:
            tables: List of HTMLTable objects
            metadata: Document metadata

        Returns:
            List of table chunks
        """
        chunks = []

        for table in tables:
            # Convert table to HTML
            table_html = table.to_html()

            chunk = Chunk(
                chunk_id=f"table_{table.table_index}",
                text=table_html,
                start_char=0,
                end_char=len(table_html),
                metadata={
                    **metadata,
                    "chunk_strategy": "table",
                    "chunk_type": "table",
                    "table_index": table.table_index,
                    "table_caption": table.caption,
                    "num_rows": table.num_rows,
                    "num_cols": table.num_cols,
                    "has_headers": table.has_headers
                }
            )
            chunks.append(chunk)

        return chunks
