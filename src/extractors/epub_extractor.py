"""
Extractor for EPUB e-books.

Chapters are read in reading order (``book.spine``), not manifest order, and
each one is converted with the shared HTML-to-Markdown walker, so lists, tables
and code come out like any other format. A chapter keeps its own headings; a
chapter with no heading gets its table-of-contents title as ``##``, and no
heading is ever added twice. Nothing is dropped for being short (a one-line
epigraph is still content). Images stored in the book become lazy image records
(``img-<n>``) with markers where they sit.
"""

from __future__ import annotations

import logging
import posixpath
import warnings
from typing import Any
from urllib.parse import unquote, urldefrag

from ..models.document import RawDocument
from .base import BaseExtractor
from .markdown_utils import list_item

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

    from .html_markdown import HTMLToMarkdown, body_of, strip_boilerplate

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

logger = logging.getLogger(__name__)


class EPUBExtractor(BaseExtractor):
    """
    Extractor for EPUB e-book files.

    Extracts chapters in reading order as Markdown, the table of contents and
    Dublin Core metadata. Requires ebooklib and beautifulsoup4.
    """

    SUPPORTED_EXTENSIONS = [".epub"]

    def __init__(
        self,
        include_toc: bool = True,
        chapter_separator: str = "\n\n",
        min_image_width: int = 100,
        min_image_height: int = 100,
    ):
        """
        Initialize EPUB extractor.

        Args:
            include_toc: Include the table of contents (as a nested list)
            chapter_separator: String placed between chapters
            min_image_width: Size floor for images stored in the book
            min_image_height: Size floor for images stored in the book
        """
        if not EBOOKLIB_AVAILABLE:
            raise ImportError("ebooklib is required for EPUB extraction. Install with: pip install ebooklib")
        if not BS4_AVAILABLE:
            raise ImportError("beautifulsoup4 is required for EPUB extraction. Install with: pip install beautifulsoup4")
        self.include_toc = include_toc
        self.chapter_separator = chapter_separator
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from an EPUB file."""
        self.validate_file(file_path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # ebooklib's ignore_ncx deprecation chatter
            book = epub.read_epub(file_path)

        book_metadata = self._extract_metadata(book)
        toc = self._extract_toc(book)
        toc_titles = {self._href_key(item["href"]): item["title"] for item in toc if item.get("href")}
        chapters, images = self._extract_chapters(book, toc_titles)

        parts: list[str] = []
        if book_metadata.get("title"):
            parts.append(f"# {book_metadata['title']}")
        if book_metadata.get("creator"):
            parts.append(f"**Author:** {book_metadata['creator']}")
        if self.include_toc and toc:
            lines = [list_item(item["title"], item.get("level", 0), "-") for item in toc]
            parts.append("## Table of Contents\n\n" + "\n".join(lines))
        header = "\n\n".join(parts)
        body = self.chapter_separator.join(c["text"] for c in chapters)
        formatted_text = "\n\n".join(p for p in (header, body) if p)

        metadata = self._get_basic_metadata(file_path)
        metadata.update(
            {
                "format": "epub",
                "title": book_metadata.get("title"),
                "creator": book_metadata.get("creator"),
                "author": book_metadata.get("creator"),  # Alias
                "publisher": book_metadata.get("publisher"),
                "language": book_metadata.get("language"),
                "identifier": book_metadata.get("identifier"),
                "description": book_metadata.get("description"),
                "chapter_count": len(chapters),
                "has_toc": len(toc) > 0,
                "toc_items": len(toc),
            }
        )

        return RawDocument(
            text=formatted_text,
            metadata=metadata,
            structure={
                "type": "epub",
                "toc": toc if self.include_toc else [],
                "chapters": [
                    {"title": c.get("title"), "word_count": len(c["text"].split()), "item_name": c["item_name"]}
                    for c in chapters
                ],
                "spine_items": len(book.spine),
                "images": images,
            },
        )

    # --------------------------------------------------------------- metadata

    def _extract_metadata(self, book: Any) -> dict[str, Any]:
        """Dublin Core metadata (first value of each field)."""
        metadata: dict[str, Any] = {}
        for name in ("title", "creator", "language", "identifier", "publisher", "description", "subject", "date"):
            values = book.get_metadata("DC", name)
            if values:
                value = values[0]
                metadata[name] = value[0] if isinstance(value, tuple) else value
        return metadata

    def _extract_toc(self, book: Any) -> list[dict[str, Any]]:
        """Flattened table of contents with nesting levels and target hrefs."""
        toc_items: list[dict[str, Any]] = []

        def walk(items: Any, level: int = 0) -> None:
            for item in items:
                if isinstance(item, tuple):
                    section, nested = item
                    toc_items.append(
                        {
                            "title": getattr(section, "title", str(section)),
                            "level": level,
                            "href": getattr(section, "href", None),
                        }
                    )
                    walk(nested, level + 1)
                elif hasattr(item, "title"):
                    toc_items.append({"title": item.title, "level": level, "href": getattr(item, "href", None)})

        walk(book.toc)
        return [item for item in toc_items if item.get("title")]

    # --------------------------------------------------------------- chapters

    @staticmethod
    def _href_key(href: str) -> str:
        return posixpath.normpath(unquote(urldefrag(href)[0]))

    def _extract_chapters(
        self, book: Any, toc_titles: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Chapters in spine order, as Markdown, plus the image records they use."""
        current_dir = [""]

        def load_image(src: str) -> bytes | None:
            if "://" in src or src.startswith("data:"):
                return None
            path = posixpath.normpath(posixpath.join(current_dir[0], unquote(urldefrag(src)[0])))
            item = book.get_item_with_href(path)
            return item.get_content() if item is not None else None

        converter = HTMLToMarkdown(
            image_loader=load_image,
            min_image_width=self.min_image_width,
            min_image_height=self.min_image_height,
        )
        chapters: list[dict[str, Any]] = []
        for idref, _linear in book.spine:
            item = book.get_item_with_id(idref)
            if item is None:
                logger.warning(f"EPUB spine entry {idref!r} has no manifest item")
                continue
            if item.get_type() == ebooklib.ITEM_NAVIGATION or isinstance(item, epub.EpubNav):
                continue
            content = item.get_content()
            if not content:
                continue
            current_dir[0] = posixpath.dirname(item.get_name())
            soup = BeautifulSoup(content, "lxml")
            strip_boilerplate(soup, chrome=False)
            text = converter.convert(body_of(soup))
            if not text.strip():
                continue
            heading_line = next((line for line in text.splitlines() if line.startswith("#")), None)
            title = heading_line.lstrip("#").strip() if heading_line else toc_titles.get(self._href_key(item.get_name()))
            if heading_line is None and title:
                text = f"## {title}\n\n{text}"
            chapters.append({"title": title, "text": text, "item_name": item.get_name()})
        return chapters, converter.images
