"""
Extractor for EPUB e-book format.

EPUB files are essentially ZIP archives containing XHTML content,
CSS styles, images, and metadata in a structured format.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional
from .base import BaseExtractor
from ..models.document import RawDocument

# Optional import
try:
    import ebooklib
    from ebooklib import epub
    EBOOKLIB_AVAILABLE = True
except ImportError:
    ebooklib = None
    epub = None
    EBOOKLIB_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    BS4_AVAILABLE = False


class EPUBExtractor(BaseExtractor):
    """
    Extractor for EPUB e-book files.

    Extracts text content, table of contents, and metadata from EPUB files.
    Requires ebooklib and beautifulsoup4 libraries.
    """

    SUPPORTED_EXTENSIONS = [".epub"]

    def __init__(self, include_toc: bool = True, chapter_separator: str = "\n\n---\n\n"):
        """
        Initialize EPUB extractor.

        Args:
            include_toc: Include table of contents in output
            chapter_separator: String to separate chapters
        """
        if not EBOOKLIB_AVAILABLE:
            raise ImportError("ebooklib is required for EPUB extraction. Install with: pip install ebooklib")
        if not BS4_AVAILABLE:
            raise ImportError("beautifulsoup4 is required for EPUB extraction. Install with: pip install beautifulsoup4")
        self.include_toc = include_toc
        self.chapter_separator = chapter_separator

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from EPUB file."""
        self.validate_file(file_path)

        # Read EPUB file
        book = epub.read_epub(file_path)

        # Extract metadata
        book_metadata = self._extract_metadata(book)

        # Extract table of contents
        toc = self._extract_toc(book)

        # Extract chapters/content
        chapters = self._extract_chapters(book)

        # Build formatted output
        text_parts = []

        # Add metadata header
        if book_metadata.get('title'):
            text_parts.append(f"# {book_metadata['title']}\n")
        if book_metadata.get('creator'):
            text_parts.append(f"**Author:** {book_metadata['creator']}\n")

        # Add TOC if requested
        if self.include_toc and toc:
            text_parts.append("## Table of Contents\n")
            for item in toc:
                indent = "  " * item.get('level', 0)
                text_parts.append(f"{indent}- {item['title']}")
            text_parts.append("")

        # Add chapter content
        text_parts.append("## Content\n")
        for i, chapter in enumerate(chapters):
            if chapter.get('title'):
                text_parts.append(f"### {chapter['title']}\n")
            text_parts.append(chapter['text'])
            if i < len(chapters) - 1:
                text_parts.append(self.chapter_separator)

        formatted_text = "\n".join(text_parts)

        # Build metadata dict
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "epub",
            "title": book_metadata.get('title'),
            "creator": book_metadata.get('creator'),
            "author": book_metadata.get('creator'),  # Alias
            "publisher": book_metadata.get('publisher'),
            "language": book_metadata.get('language'),
            "identifier": book_metadata.get('identifier'),
            "description": book_metadata.get('description'),
            "chapter_count": len(chapters),
            "has_toc": len(toc) > 0,
            "toc_items": len(toc),
        })

        return RawDocument(
            text=formatted_text,
            metadata=metadata,
            structure={
                "type": "epub",
                "toc": toc if self.include_toc else [],
                "chapters": [{"title": c.get('title'), "word_count": len(c['text'].split())} for c in chapters],
                "spine_items": len(list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)))
            }
        )

    def _extract_metadata(self, book) -> Dict[str, Any]:
        """Extract EPUB metadata."""
        metadata = {}

        # Standard Dublin Core metadata
        dc_fields = ['title', 'creator', 'language', 'identifier', 'publisher', 'description', 'subject', 'date']

        for field in dc_fields:
            try:
                values = book.get_metadata('DC', field)
                if values:
                    # Get first value, handle tuple format
                    value = values[0]
                    if isinstance(value, tuple):
                        value = value[0]
                    metadata[field] = value
            except Exception:
                pass

        return metadata

    def _extract_toc(self, book) -> List[Dict[str, Any]]:
        """Extract table of contents."""
        toc_items = []

        def process_toc(items, level=0):
            for item in items:
                if isinstance(item, tuple):
                    # Section with nested items
                    section, nested = item
                    toc_items.append({
                        'title': section.title if hasattr(section, 'title') else str(section),
                        'level': level
                    })
                    process_toc(nested, level + 1)
                elif hasattr(item, 'title'):
                    # Single link
                    toc_items.append({
                        'title': item.title,
                        'level': level
                    })

        try:
            process_toc(book.toc)
        except Exception:
            pass

        return toc_items

    def _extract_chapters(self, book) -> List[Dict[str, Any]]:
        """Extract chapter content."""
        chapters = []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            try:
                content = item.get_content()
                if content:
                    # Parse HTML content
                    soup = BeautifulSoup(content, 'html.parser')

                    # Try to get title from <title> or first heading
                    title = None
                    title_tag = soup.find('title')
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                    if not title:
                        heading = soup.find(['h1', 'h2', 'h3'])
                        if heading:
                            title = heading.get_text(strip=True)

                    # Extract text content
                    text = soup.get_text(separator='\n', strip=True)

                    # Skip empty chapters
                    if text and len(text.strip()) > 50:
                        chapters.append({
                            'title': title,
                            'text': text,
                            'item_name': item.get_name()
                        })
            except Exception:
                continue

        return chapters
