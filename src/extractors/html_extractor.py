"""
HTML extractor using BeautifulSoup4 and Trafilatura.

Extracts text, tables, lists, forms, links, and metadata from HTML files and web pages.
Handles boilerplate removal, article extraction, and semantic structure detection.
"""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin

try:
    from bs4 import BeautifulSoup, Tag, NavigableString
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    from trafilatura import extract, extract_metadata
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

from .base import BaseExtractor
from ..models.document import RawDocument
from ..models.html_models import (
    HTMLTable,
    HTMLList,
    HTMLForm,
    HTMLLink,
    HTMLSection,
    HTMLMetadata,
    HTMLDocument
)

logger = logging.getLogger(__name__)


class HTMLExtractor(BaseExtractor):
    """
    Extract content from HTML files and web pages.

    Features:
    - Boilerplate removal (ads, navigation, footer, etc.)
    - Article extraction with Trafilatura
    - Table extraction (preserves structure)
    - List extraction (ordered/unordered)
    - Form detection
    - Link extraction and classification
    - Metadata extraction (meta tags, Open Graph, Schema.org)
    - Semantic section detection (article, section, nav, etc.)
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
        base_url: Optional[str] = None
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
        Extract content from HTML file.

        Args:
            file_path: Path to HTML file

        Returns:
            RawDocument with extracted content and structure
        """
        self.validate_file(file_path)

        # Read HTML content
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html_content, 'lxml')

        # Create HTML document structure
        html_doc = HTMLDocument()

        # Extract metadata
        if self.extract_metadata_flag:
            html_doc.metadata = self._extract_metadata(soup, html_content)

        # Extract main content (with boilerplate removal if enabled)
        html_doc.main_content = self._extract_main_content(html_content, soup)
        html_doc.full_text = self._get_full_text(soup)

        # Extract structural elements
        if self.extract_tables:
            html_doc.tables = self._extract_tables(soup)

        if self.extract_lists:
            html_doc.lists = self._extract_lists(soup)

        if self.extract_forms:
            html_doc.forms = self._extract_forms(soup)

        if self.extract_links:
            html_doc.links = self._extract_links(soup)

        # Extract semantic sections
        if self.preserve_structure:
            html_doc.sections = self._extract_sections(soup)

        # Detect document structure
        html_doc.has_article = soup.find('article') is not None
        html_doc.has_nav = soup.find('nav') is not None
        html_doc.num_headings = len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']))

        # Combine main content with extracted text
        if not html_doc.main_content:
            html_doc.main_content = html_doc.full_text

        # Get basic metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._convert_html_metadata_to_dict(html_doc))

        return RawDocument(
            text=html_doc.main_content,
            metadata=metadata,
            structure={
                'html_document': html_doc,
                'tables': html_doc.tables,
                'lists': html_doc.lists,
                'forms': html_doc.forms,
                'links': html_doc.links,
                'sections': html_doc.sections
            }
        )

    def _extract_metadata(self, soup: BeautifulSoup, html_content: str) -> HTMLMetadata:
        """
        Extract metadata from HTML meta tags and structured data.

        Args:
            soup: BeautifulSoup object
            html_content: Raw HTML content

        Returns:
            HTMLMetadata object
        """
        metadata = HTMLMetadata()

        # Extract title
        title_tag = soup.find('title')
        if title_tag:
            metadata.title = title_tag.get_text().strip()

        # Try Trafilatura metadata extraction if available
        if TRAFILATURA_AVAILABLE:
            try:
                traf_metadata = extract_metadata(html_content)
                if traf_metadata:
                    if not metadata.title and traf_metadata.title:
                        metadata.title = traf_metadata.title
                    if traf_metadata.author:
                        metadata.author = traf_metadata.author
                    if traf_metadata.description:
                        metadata.description = traf_metadata.description
                    if traf_metadata.date:
                        try:
                            metadata.publish_date = datetime.fromisoformat(traf_metadata.date)
                        except:
                            pass
            except Exception as e:
                logger.warning(f"Trafilatura metadata extraction failed: {e}")

        # Extract standard meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '').lower()
            property_name = meta.get('property', '').lower()
            content = meta.get('content', '')

            # Standard meta tags
            if name == 'description' and not metadata.description:
                metadata.description = content
            elif name == 'author' and not metadata.author:
                metadata.author = content
            elif name == 'keywords':
                metadata.keywords = [k.strip() for k in content.split(',')]
            elif name == 'language':
                metadata.language = content

            # Open Graph
            if property_name.startswith('og:'):
                og_key = property_name.replace('og:', '')
                metadata.open_graph[og_key] = content

                # Use OG data as fallback
                if og_key == 'title' and not metadata.title:
                    metadata.title = content
                elif og_key == 'description' and not metadata.description:
                    metadata.description = content

            # Twitter Card
            if name.startswith('twitter:'):
                tw_key = name.replace('twitter:', '')
                metadata.twitter_card[tw_key] = content

        # Extract canonical URL
        canonical = soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            metadata.canonical_url = canonical['href']

        # Extract Schema.org structured data
        schema_scripts = soup.find_all('script', type='application/ld+json')
        for script in schema_scripts:
            try:
                import json
                schema_data = json.loads(script.string)
                metadata.schema_org.append(schema_data)
            except:
                pass

        return metadata

    def _extract_main_content(self, html_content: str, soup: BeautifulSoup) -> str:
        """
        Extract main content with boilerplate removal.

        Args:
            html_content: Raw HTML content
            soup: BeautifulSoup object

        Returns:
            Clean main content text
        """
        if self.remove_boilerplate and TRAFILATURA_AVAILABLE:
            # Use Trafilatura for boilerplate removal
            try:
                main_text = extract(
                    html_content,
                    include_comments=False,
                    include_tables=True,
                    include_images=False,
                    output_format='txt'
                )
                if main_text:
                    return main_text
            except Exception as e:
                logger.warning(f"Trafilatura extraction failed: {e}")

        # Fallback: Extract from article tag or body
        article = soup.find('article')
        if article:
            return article.get_text(separator='\n', strip=True)

        main = soup.find('main')
        if main:
            return main.get_text(separator='\n', strip=True)

        # Last resort: get all text from body
        body = soup.find('body')
        if body:
            return body.get_text(separator='\n', strip=True)

        return ""

    def _get_full_text(self, soup: BeautifulSoup) -> str:
        """
        Get full document text without boilerplate removal.

        Args:
            soup: BeautifulSoup object

        Returns:
            Full text content
        """
        return soup.get_text(separator='\n', strip=True)

    def _extract_tables(self, soup: BeautifulSoup) -> List[HTMLTable]:
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

    def _extract_lists(self, soup: BeautifulSoup) -> List[HTMLList]:
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

    def _extract_forms(self, soup: BeautifulSoup) -> List[HTMLForm]:
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

    def _extract_links(self, soup: BeautifulSoup) -> List[HTMLLink]:
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

    def _extract_sections(self, soup: BeautifulSoup) -> List[HTMLSection]:
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

    def _convert_html_metadata_to_dict(self, html_doc: HTMLDocument) -> Dict[str, Any]:
        """
        Convert HTMLDocument to metadata dictionary.

        Args:
            html_doc: HTMLDocument object

        Returns:
            Metadata dictionary
        """
        metadata = {
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
