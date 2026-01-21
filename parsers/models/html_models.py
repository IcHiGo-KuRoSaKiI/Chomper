"""
HTML-specific data models.

Data structures for representing HTML document structure, metadata,
and extracted elements (tables, lists, forms, etc.).
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class HTMLTable:
    """
    Represents an HTML table structure.

    Attributes:
        headers: List of header cell texts
        rows: List of rows, each row is a list of cell texts
        caption: Table caption if present
        has_headers: Whether table has header row
        num_rows: Number of data rows
        num_cols: Number of columns
        table_index: Index of table in document
    """
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    caption: Optional[str] = None
    has_headers: bool = True
    table_index: int = 0

    @property
    def num_rows(self) -> int:
        """Number of data rows."""
        return len(self.rows)

    @property
    def num_cols(self) -> int:
        """Number of columns."""
        if self.headers:
            return len(self.headers)
        if self.rows:
            return max(len(row) for row in self.rows)
        return 0

    @property
    def is_empty(self) -> bool:
        """Check if table has no data."""
        return self.num_rows == 0 or self.num_cols == 0

    def to_html(self) -> str:
        """Convert back to HTML string."""
        html_parts = ['<table border="1">']

        if self.caption:
            html_parts.append(f'  <caption>{self.caption}</caption>')

        if self.headers:
            html_parts.append('  <thead>')
            html_parts.append('    <tr>')
            for header in self.headers:
                html_parts.append(f'      <th>{header}</th>')
            html_parts.append('    </tr>')
            html_parts.append('  </thead>')

        if self.rows:
            html_parts.append('  <tbody>')
            for row in self.rows:
                html_parts.append('    <tr>')
                for cell in row:
                    html_parts.append(f'      <td>{cell}</td>')
                html_parts.append('    </tr>')
            html_parts.append('  </tbody>')

        html_parts.append('</table>')
        return '\n'.join(html_parts)


@dataclass
class HTMLList:
    """
    Represents an HTML list (ordered or unordered).

    Attributes:
        items: List of text items
        is_ordered: True for <ol>, False for <ul>
        list_index: Index of list in document
        nested_depth: Nesting level (0 for top-level)
    """
    items: List[str] = field(default_factory=list)
    is_ordered: bool = False
    list_index: int = 0
    nested_depth: int = 0

    @property
    def num_items(self) -> int:
        """Number of list items."""
        return len(self.items)

    @property
    def is_empty(self) -> bool:
        """Check if list has no items."""
        return self.num_items == 0


@dataclass
class HTMLForm:
    """
    Represents an HTML form structure.

    Attributes:
        form_id: Form ID attribute
        action: Form action URL
        method: HTTP method (GET/POST)
        fields: List of input field names
        field_types: Dict mapping field name to input type
        form_index: Index of form in document
    """
    form_id: Optional[str] = None
    action: Optional[str] = None
    method: str = "GET"
    fields: List[str] = field(default_factory=list)
    field_types: Dict[str, str] = field(default_factory=dict)
    form_index: int = 0

    @property
    def num_fields(self) -> int:
        """Number of form fields."""
        return len(self.fields)


@dataclass
class HTMLLink:
    """
    Represents an HTML hyperlink.

    Attributes:
        url: Link URL (href)
        text: Link text content
        is_external: Whether link points to external domain
        is_anchor: Whether link is an anchor (#)
    """
    url: str
    text: str
    is_external: bool = False
    is_anchor: bool = False


@dataclass
class HTMLSection:
    """
    Represents a semantic HTML section.

    Attributes:
        tag: HTML tag name (article, section, nav, aside, etc.)
        heading: Section heading text (from h1-h6)
        heading_level: Heading level (1-6)
        text: Section text content
        subsections: Nested subsections
        start_char: Start position in document
        end_char: End position in document
        section_index: Index of section in document
    """
    tag: str
    heading: Optional[str] = None
    heading_level: Optional[int] = None
    text: str = ""
    subsections: List['HTMLSection'] = field(default_factory=list)
    start_char: int = 0
    end_char: int = 0
    section_index: int = 0

    @property
    def has_subsections(self) -> bool:
        """Check if section has nested subsections."""
        return len(self.subsections) > 0

    @property
    def is_empty(self) -> bool:
        """Check if section has no content."""
        return not self.text.strip() and not self.has_subsections


@dataclass
class HTMLMetadata:
    """
    HTML document metadata extracted from meta tags and structure.

    Attributes:
        title: Document title (from <title> or og:title)
        description: Meta description
        author: Author name (from meta author)
        publish_date: Publication date
        modified_date: Last modified date
        keywords: Meta keywords
        language: Document language
        canonical_url: Canonical URL
        open_graph: Open Graph metadata
        twitter_card: Twitter Card metadata
        schema_org: Schema.org structured data
    """
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    publish_date: Optional[datetime] = None
    modified_date: Optional[datetime] = None
    keywords: List[str] = field(default_factory=list)
    language: Optional[str] = None
    canonical_url: Optional[str] = None
    open_graph: Dict[str, str] = field(default_factory=dict)
    twitter_card: Dict[str, str] = field(default_factory=dict)
    schema_org: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HTMLDocument:
    """
    Complete HTML document structure.

    Attributes:
        url: Source URL (if applicable)
        metadata: Document metadata
        sections: List of semantic sections
        tables: List of extracted tables
        lists: List of extracted lists
        forms: List of extracted forms
        links: List of extracted hyperlinks
        main_content: Main article/content text (cleaned)
        full_text: Full document text (with boilerplate)
        has_article: Whether document has <article> tag
        has_nav: Whether document has <nav> tag
        num_headings: Number of heading elements (h1-h6)
    """
    url: Optional[str] = None
    metadata: HTMLMetadata = field(default_factory=HTMLMetadata)
    sections: List[HTMLSection] = field(default_factory=list)
    tables: List[HTMLTable] = field(default_factory=list)
    lists: List[HTMLList] = field(default_factory=list)
    forms: List[HTMLForm] = field(default_factory=list)
    links: List[HTMLLink] = field(default_factory=list)
    main_content: str = ""
    full_text: str = ""
    has_article: bool = False
    has_nav: bool = False
    num_headings: int = 0

    @property
    def num_tables(self) -> int:
        """Number of tables in document."""
        return len(self.tables)

    @property
    def num_lists(self) -> int:
        """Number of lists in document."""
        return len(self.lists)

    @property
    def num_forms(self) -> int:
        """Number of forms in document."""
        return len(self.forms)

    @property
    def num_links(self) -> int:
        """Number of links in document."""
        return len(self.links)

    @property
    def num_sections(self) -> int:
        """Number of top-level sections."""
        return len(self.sections)

    @property
    def is_article(self) -> bool:
        """Check if document appears to be an article."""
        return self.has_article or (
            self.metadata.title is not None and
            len(self.main_content) > 500
        )

    @property
    def content_length(self) -> int:
        """Length of main content."""
        return len(self.main_content)
