"""
HTML extractor: one BeautifulSoup parse, Markdown out.

The page is parsed once (``lxml``; the encoding comes from the BOM or
``<meta charset>``). Metadata and the structural elements the HTML chunker uses
(tables, lists, forms, links, semantic sections) are read from that tree, then
boilerplate is stripped and the main content is converted to Markdown by
``html_markdown.HTMLToMarkdown``: headings, nested and numbered lists, GFM
tables with spans, fenced code with indentation, links and images.

Trafilatura is no longer used for the text. Measured on a saved Wikipedia
article, its Markdown mode glued 361 links to the following word, kept 17 of
373 list items, lost list nesting and code indentation and took 0.42 s against
0.12 s; on a short page it duplicated paragraphs and flattened an ``<ol>``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

from ..models.document import RawDocument
from ..models.html_models import (
    HTMLDocument,
    HTMLForm,
    HTMLLink,
    HTMLList,
    HTMLMetadata,
    HTMLSection,
    HTMLTable,
)
from .base import BaseExtractor

if BS4_AVAILABLE:
    from .html_markdown import (
        HTMLToMarkdown,
        attr_text,
        body_of,
        find_tag,
        main_content,
        strip_boilerplate,
    )

logger = logging.getLogger(__name__)

_DATE_META = (
    ("property", "article:published_time"),
    ("name", "article:published_time"),
    ("itemprop", "datePublished"),
    ("name", "date"),
    ("name", "pubdate"),
    ("name", "publishdate"),
    ("name", "dc.date.issued"),
    ("name", "dc.date"),
    ("property", "og:published_time"),
)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


class HTMLExtractor(BaseExtractor):
    """
    Extract content from HTML files and web pages as Markdown.

    Features:
    - Boilerplate removal (scripts, navigation, headers/footers, sidebars, ads)
    - Main-content selection (``main``, ``[role=main]``, a single ``article``)
    - Markdown with nested/numbered lists, GFM tables, fenced code and links
    - Structural extraction for the chunker (tables, lists, forms, links, sections)
    - Metadata (title, meta tags, Open Graph, JSON-LD, publish date)
    """

    SUPPORTED_EXTENSIONS = ['.html', '.htm']

    def __init__(
        self,
        remove_boilerplate: bool = True,
        extract_tables: bool = True,
        extract_lists: bool = True,
        extract_forms: bool = True,
        extract_links: bool = True,
        extract_metadata: bool = True,
        preserve_structure: bool = True,
        base_url: str | None = None
    ):
        """
        Initialize HTML extractor.

        Args:
            remove_boilerplate: Remove ads, navigation, footer, etc.
            extract_tables: Extract HTML tables as structured data
            extract_lists: Extract lists (ordered/unordered)
            extract_forms: Extract form structures
            extract_links: Extract hyperlinks
            extract_metadata: Extract meta tags and Open Graph data
            preserve_structure: Preserve semantic HTML structure (sections)
            base_url: Base URL for resolving relative links
        """
        if not BS4_AVAILABLE:
            raise ImportError(
                "BeautifulSoup4 is required for HTML extraction. "
                "Install with: pip install beautifulsoup4 lxml"
            )

        self.remove_boilerplate = remove_boilerplate
        self.extract_tables = extract_tables
        self.extract_lists = extract_lists
        self.extract_forms = extract_forms
        self.extract_links = extract_links
        self.extract_metadata_flag = extract_metadata
        self.preserve_structure = preserve_structure
        self.base_url = base_url

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from an HTML file as Markdown.

        Args:
            file_path: Path to HTML file

        Returns:
            RawDocument with Markdown text, metadata and structure
        """
        self.validate_file(file_path)
        soup = BeautifulSoup(Path(file_path).read_bytes(), "lxml")

        html_doc = HTMLDocument()
        if self.extract_metadata_flag:
            html_doc.metadata = self._extract_metadata(soup)

        # Structure for the HTML chunker, read before boilerplate is stripped.
        if self.extract_tables:
            html_doc.tables = self._extract_tables(soup)
        if self.extract_lists:
            html_doc.lists = self._extract_lists(soup)
        if self.extract_forms:
            html_doc.forms = self._extract_forms(soup)
        if self.extract_links:
            html_doc.links = self._extract_links(soup)
        if self.preserve_structure:
            html_doc.sections = self._extract_sections(soup)
        html_doc.has_article = soup.find("article") is not None
        html_doc.has_nav = soup.find("nav") is not None
        html_doc.num_headings = len(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))

        base_url = self.base_url or attr_text(find_tag(soup, "base", href=True), "href")
        strip_boilerplate(soup, chrome=False)  # scripts, styles, hidden elements
        html_doc.full_text = soup.get_text(separator="\n", strip=True)
        if self.remove_boilerplate:
            strip_boilerplate(soup, chrome=True)  # navigation, sidebars, footers
        converter = HTMLToMarkdown(base_url=base_url)
        body = body_of(soup)
        root = main_content(soup) if self.remove_boilerplate else body
        text = converter.convert(root)
        if not text and root is not body:
            text = converter.convert(body)
        title = html_doc.metadata.title
        if title and not any(line.startswith("# ") for line in text.splitlines()):
            text = f"# {' '.join(title.split())}\n\n{text}".strip()
        html_doc.main_content = text

        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._convert_html_metadata_to_dict(html_doc))
        if soup.original_encoding:
            metadata["encoding"] = soup.original_encoding

        return RawDocument(
            text=text,
            metadata=metadata,
            structure={
                "html_document": html_doc,
                "tables": html_doc.tables,
                "lists": html_doc.lists,
                "forms": html_doc.forms,
                "links": html_doc.links,
                "sections": html_doc.sections,
                "images": converter.images,
            },
        )

    def _extract_metadata(self, soup: BeautifulSoup) -> HTMLMetadata:
        """
        Metadata from ``<title>``, meta tags, Open Graph and JSON-LD.

        Read from the already-parsed tree (no second parse).
        """
        metadata = HTMLMetadata()
        title_tag = soup.find("title")
        if title_tag:
            metadata.title = title_tag.get_text().strip()

        for meta in soup.find_all("meta"):
            name = (meta.get("name") or "").lower()
            property_name = (meta.get("property") or "").lower()
            content = meta.get("content") or ""
            if name == "description" and not metadata.description:
                metadata.description = content
            elif name == "author" and not metadata.author:
                metadata.author = content
            elif name == "keywords":
                metadata.keywords = [k.strip() for k in content.split(",") if k.strip()]
            elif name in ("language", "content-language"):
                metadata.language = content
            if property_name.startswith("og:"):
                metadata.open_graph[property_name] = content
                if property_name == "og:title" and not metadata.title:
                    metadata.title = content
                elif property_name == "og:description" and not metadata.description:
                    metadata.description = content
            elif property_name == "article:author" and not metadata.author and "://" not in content:
                metadata.author = content
            elif property_name == "article:modified_time" and not metadata.modified_date:
                metadata.modified_date = _parse_date(content)
            if name.startswith("twitter:"):
                metadata.twitter_card[name[8:]] = content

        for attr, value in _DATE_META:
            if metadata.publish_date:
                break
            tag = find_tag(soup, "meta", attrs={attr: lambda v, want=value: (v or "").lower() == want})
            metadata.publish_date = _parse_date(attr_text(tag, "content"))

        if not metadata.language:
            metadata.language = attr_text(find_tag(soup, "html"), "lang")

        canonical = attr_text(find_tag(soup, "link", rel="canonical"), "href")
        if canonical:
            metadata.canonical_url = canonical

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            metadata.schema_org.append(data)
            for item in data if isinstance(data, list) else [data]:
                if not isinstance(item, dict):
                    continue
                if not metadata.publish_date:
                    metadata.publish_date = _parse_date(item.get("datePublished"))
                author = item.get("author")
                if not metadata.author and author:
                    first = author[0] if isinstance(author, list) and author else author
                    name = first.get("name") if isinstance(first, dict) else first
                    if isinstance(name, str):
                        metadata.author = name

        if not metadata.publish_date:
            metadata.publish_date = _parse_date(attr_text(find_tag(soup, "time", datetime=True), "datetime"))
        return metadata

    def _extract_tables(self, soup: BeautifulSoup) -> list[HTMLTable]:
        """
        Extract all tables from HTML.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of HTMLTable objects
        """
        tables = []
        table_tags = soup.find_all('table')

        for idx, table_tag in enumerate(table_tags):
            # Extract caption
            caption = None
            caption_tag = table_tag.find('caption')
            if caption_tag:
                caption = caption_tag.get_text().strip()

            # Extract headers
            headers = []
            thead = table_tag.find('thead')
            if thead:
                header_row = thead.find('tr')
                if header_row:
                    headers = [th.get_text().strip() for th in header_row.find_all(['th', 'td'])]

            # Extract rows
            rows = []
            tbody = table_tag.find('tbody')
            row_tags = tbody.find_all('tr') if tbody else table_tag.find_all('tr')

            for row_tag in row_tags:
                # Skip header rows
                if thead and row_tag in thead.find_all('tr'):
                    continue

                cells = [td.get_text().strip() for td in row_tag.find_all(['td', 'th'])]
                if cells:  # Only add non-empty rows
                    rows.append(cells)

            # Create table object
            html_table = HTMLTable(
                headers=headers,
                rows=rows,
                caption=caption,
                has_headers=len(headers) > 0,
                table_index=idx
            )

            if not html_table.is_empty:
                tables.append(html_table)

        return tables

    def _extract_lists(self, soup: BeautifulSoup) -> list[HTMLList]:
        """
        Extract all lists from HTML.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of HTMLList objects
        """
        lists = []
        list_index = 0

        for list_tag in soup.find_all(['ul', 'ol']):
            items = []
            for li in list_tag.find_all('li', recursive=False):
                items.append(li.get_text().strip())

            if items:
                html_list = HTMLList(
                    items=items,
                    is_ordered=(list_tag.name == 'ol'),
                    list_index=list_index,
                    nested_depth=len(list(list_tag.parents))
                )
                lists.append(html_list)
                list_index += 1

        return lists

    def _extract_forms(self, soup: BeautifulSoup) -> list[HTMLForm]:
        """
        Extract all forms from HTML.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of HTMLForm objects
        """
        forms = []
        form_tags = soup.find_all('form')

        for idx, form_tag in enumerate(form_tags):
            fields = []
            field_types = {}

            # Extract input fields
            for input_tag in form_tag.find_all(['input', 'textarea', 'select']):
                name = input_tag.get('name')
                if name:
                    fields.append(name)
                    input_type = input_tag.get('type', input_tag.name)
                    field_types[name] = input_type

            html_form = HTMLForm(
                form_id=form_tag.get('id'),
                action=form_tag.get('action'),
                method=form_tag.get('method', 'GET').upper(),
                fields=fields,
                field_types=field_types,
                form_index=idx
            )

            if html_form.num_fields > 0:
                forms.append(html_form)

        return forms

    def _extract_links(self, soup: BeautifulSoup) -> list[HTMLLink]:
        """
        Extract and classify all hyperlinks.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of HTMLLink objects
        """
        links = []
        base_domain = urlparse(self.base_url).netloc if self.base_url else None

        for a_tag in soup.find_all('a', href=True):
            url = a_tag['href']
            text = a_tag.get_text().strip()

            # Classify link
            is_anchor = url.startswith('#')
            is_external = False

            if not is_anchor and base_domain:
                link_domain = urlparse(url).netloc
                is_external = (link_domain and link_domain != base_domain)

            html_link = HTMLLink(
                url=url,
                text=text,
                is_external=is_external,
                is_anchor=is_anchor
            )
            links.append(html_link)

        return links

    def _extract_sections(self, soup: BeautifulSoup) -> list[HTMLSection]:
        """
        Extract semantic sections from HTML.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of HTMLSection objects
        """
        sections = []
        section_index = 0

        # Find semantic containers
        semantic_tags = ['article', 'section', 'nav', 'aside', 'header', 'footer', 'main']

        for tag_name in semantic_tags:
            for tag in soup.find_all(tag_name):
                # Find heading
                heading = None
                heading_level = None
                heading_tag = tag.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if heading_tag:
                    heading = heading_tag.get_text().strip()
                    heading_level = int(heading_tag.name[1])  # Extract number from h1-h6

                # Get section text
                text = tag.get_text(separator='\n', strip=True)

                section = HTMLSection(
                    tag=tag_name,
                    heading=heading,
                    heading_level=heading_level,
                    text=text,
                    section_index=section_index
                )

                if not section.is_empty:
                    sections.append(section)
                    section_index += 1

        return sections

    def _convert_html_metadata_to_dict(self, html_doc: HTMLDocument) -> dict[str, Any]:
        """
        Convert HTMLDocument to metadata dictionary.

        Args:
            html_doc: HTMLDocument object

        Returns:
            Metadata dictionary
        """
        metadata: dict[str, Any] = {
            "format": "html",
            "title": html_doc.metadata.title,
            "description": html_doc.metadata.description,
            "author": html_doc.metadata.author,
            "language": html_doc.metadata.language,
            "num_tables": html_doc.num_tables,
            "num_lists": html_doc.num_lists,
            "num_forms": html_doc.num_forms,
            "num_links": html_doc.num_links,
            "num_sections": html_doc.num_sections,
            "num_headings": html_doc.num_headings,
            "has_article": html_doc.has_article,
            "has_nav": html_doc.has_nav,
            "is_article": html_doc.is_article,
            "content_length": html_doc.content_length
        }

        # Add dates if present
        if html_doc.metadata.publish_date:
            metadata["publish_date"] = str(html_doc.metadata.publish_date)
        if html_doc.metadata.modified_date:
            metadata["modified_date"] = str(html_doc.metadata.modified_date)

        # Add keywords if present
        if html_doc.metadata.keywords:
            metadata["keywords"] = html_doc.metadata.keywords

        # Add Open Graph data
        if html_doc.metadata.open_graph:
            metadata["open_graph"] = html_doc.metadata.open_graph

        return metadata
