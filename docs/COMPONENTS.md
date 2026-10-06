# Chomper Components

Detailed documentation for all Chomper components: extractors, chunkers, enrichers, formatters, and handlers.

## Table of Contents

- [Extractors](#extractors)
- [Images](#images)
- [Chunkers](#chunkers)
- [Enrichers](#enrichers)
- [Formatters](#formatters)
- [Handlers](#handlers)
- [Models](#models)

---

## Extractors

Extractors are responsible for converting files into `RawDocument` objects containing text, metadata, and optional structure information. Rich formats produce Markdown: headings, nested lists, GFM tables, fenced code and `![caption](image:<id>)` image markers.

Extractor classes are imported on first use (`src/extractors/__init__.py`); one whose dependency is missing resolves to `None`.

### Base Class

```python
class BaseExtractor(ABC):
    """Abstract base class for all extractors."""

    @abstractmethod
    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from file.

        Returns:
            RawDocument with text, metadata, and optional structure
        """
        pass

    def validate_file(self, file_path: str) -> None:
        """Validate file exists and has supported extension."""
        pass

    def _get_basic_metadata(self, file_path: str) -> dict:
        """Return basic file metadata (name, size, extension)."""
        pass
```

Text formats (text, code, Markdown, JSON, YAML, RTF) decode through `encoding_utils.read_text`: BOM, strict UTF-8, cp1252 for Western text, charset-normalizer, then latin-1. The encoding used is recorded in `metadata["encoding"]`.

### Extractors Without Extra Dependencies

#### CodeExtractor
**Extensions**: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.java`, `.cpp`, `.c`, `.go`, `.rs`

```python
# Features:
# - Language detection from extension
# - Line count and character metrics
# - Function/class structure detection (basic)

extractor = CodeExtractor()
doc = extractor.extract("main.py")
# doc.metadata includes: language, lines_of_code, format="code"
```

#### TextExtractor
**Extensions**: `.txt`, `.text`, `.log`

```python
# Features:
# - Paragraph detection
# - Line/word/character counts

extractor = TextExtractor(detect_paragraphs=True)
doc = extractor.extract("readme.txt")
```

#### MarkdownExtractor
**Extensions**: `.md`, `.markdown`

```python
# Features:
# - Heading hierarchy detection (ignores fenced code and front matter;
#   `---` is a setext underline only under paragraph text)
# - Code block identification
# - Link extraction

extractor = MarkdownExtractor()
doc = extractor.extract("README.md")
```

#### JSONExtractor
**Extensions**: `.json`

```python
# Features:
# - Pretty-printed output; a UTF-8 BOM is accepted
# - Structure analysis (keys, depth, array/object counts)
# - Max depth limiting

extractor = JSONExtractor(indent=2, max_depth=10)
doc = extractor.extract("config.json")
```

#### EMLExtractor
**Extensions**: `.eml`

```python
# Features:
# - Header parsing (From, To, CC, Subject, Date)
# - Body: the text/plain part, otherwise the HTML part converted to Markdown
#   with the shared HTML walker; never truncated (metadata["body_source"])
# - cid: inline images become image records (img-<n>) with markers
# - Attachment list with type and size (also in metadata)

extractor = EMLExtractor(include_headers=True, include_attachments=True)
doc = extractor.extract("email.eml")
```

### Extractors Using Core Dependencies

#### PDFExtractor
**Extensions**: `.pdf`
**Dependencies**: `pymupdf`, `pymupdf4llm`, `pymupdf-layout` (all `==1.28.2`)

```python
# Features:
# - One pymupdf-layout pass (src/extractors/pdf_layout.py): text, headings,
#   nested lists, tables and figures in reading order
# - Tables rendered from the model's cell grid, or from a grid rebuilt from
#   page geometry when that is clearly better (src/pdf_structure/table_geometry.py);
#   check marks restored (src/pdf_structure/cell_marks.py); continued tables
#   get their header back
# - Row hierarchy kept: first-column indent levels as em spaces, bold group and
#   total rows; typed or drawn rules become row attributes, never cells
# - Borderless tables the model left as text are rendered when they are clean grids
# - Figures (raster and vector) marked as ![caption](image:p<page>-<n>)
# - Running headers/footers dropped only when they repeat or are page numbers
# - Scanned pages reported, and OCR'd when Tesseract or RapidOCR is installed

extractor = PDFExtractor(
    backend="auto",               # "layout" when pymupdf-layout is installed, else "legacy"
    ocr="auto",                   # "off" or "force"; layout backend only
    table_format="markdown",      # or "html" (keeps merged cells); layout backend only
    extract_vector_figures=True,  # treat vector charts/diagrams as figures
)
doc = extractor.extract("report.pdf")
# doc.structure includes: pages[], images[], tables[] (layout backend, Markdown
#   tables: page, bbox, source grid and scores, header_rows, columns, rows with
#   cells/level/path/emphasis/rule_above/rule_below)
# doc.metadata includes: page_count, extraction_method ("pymupdf-layout"),
#   pages_without_text_layer / ocr_pages / warning when pages are scanned
```

Measured on 378 ground-truth tables (ICDAR-2013 corrected + SciTSR) against the previous `pymupdf4llm` + `find_tables` path: table adjacency F1 0.894 (was 0.421), detection F1 0.962 (was 0.776), at about 0.13 s/page. `backend="legacy"` keeps the old path (it also accepts `use_markdown` and `table_strategy`).

Geometric table reconstruction (`src/pdf_structure/table_geometry.py`), measured on 469 tables (ICDAR-2013 corrected, all four subsets, + 211 SciTSR test tables) against the model-grid-only output: adjacency F1 0.912 (was 0.883), TEDS 0.878 (was 0.868), detection 0.977 (was 0.972); unruled tables F1 0.888 (was 0.648). 101 of 450 compared tables change: 86 better, 8 worse. On 60 synthetic spec, comparison and statement tables, stub levels, group rows and paths are 100% correct.

#### DOCXExtractor
**Extensions**: `.docx` (`.doc` is recognised, but legacy binary Word files raise a clear error)
**Dependencies**: `python-docx`

```python
# Features:
# - Body XML walked in document order: content controls, text boxes,
#   nested tables and images in cells are kept
# - Real list numbering from numbering.xml (formats, start overrides,
#   per-list counters), nesting by indent
# - Title -> "#", Heading N shifted below it
# - GFM tables (spanned cells left empty), footnotes as Markdown footnotes,
#   links, bold and italic; headers/footers go to metadata
# - Images as img-<n> records with markers

extractor = DOCXExtractor()
doc = extractor.extract("document.docx")
```

#### PPTXExtractor
**Extensions**: `.pptx` (`.ppt` is recognised, but legacy binary files raise a clear error)
**Dependencies**: `python-pptx`

```python
# Features:
# - Each slide starts with "## Slide N: <title>"
# - Shapes in reading order (top-to-bottom, left-to-right, groups kept together)
# - Bullets and auto-numbering resolved from the paragraph, layout and master,
#   with nesting levels
# - Tables as GFM, charts as a title/type line plus a data table,
#   SmartArt text as a bullet list
# - Speaker notes under "### Notes"
# - Images as s<slide>-<n> records with alt text and markers

extractor = PPTXExtractor(extract_notes=True)
doc = extractor.extract("presentation.pptx")
```

#### ExcelExtractor
**Extensions**: `.xlsx`, `.xlsm`, `.xltx`, `.xltm`
**Dependencies**: `openpyxl`

```python
# Features:
# - Output bounded to cells that hold data; tables split at empty rows
# - Merged title rows become headings; real header row detected
# - Merged values kept in the top-left cell only
# - Number formats followed: ISO dates, percentages, thousands, decimals
# - Formulas without a cached value shown as formula text
# - Hidden sheets marked and listed in metadata["hidden_sheets"]
# - structure["sheets"][i]["markdown"] is the reader Markdown;
#   structure["sheets"][i]["text"] is a row-aligned grid for ExcelChunker

extractor = ExcelExtractor()
doc = extractor.extract("data.xlsx")
```

#### HTMLExtractor
**Extensions**: `.html`, `.htm`
**Dependencies**: `beautifulsoup4`, `lxml`

```python
# Features:
# - One parse; DOM-to-Markdown walker (src/extractors/html_markdown.py),
#   shared with EPUB and email
# - Headings, nested ordered/unordered lists (start/type/value), GFM tables
#   with colspan/rowspan, fenced code, quotes, figures, definition lists,
#   links and images
# - Scripts, styles, nav, headers, footers, asides and hidden elements stripped
# - data: images become image records (img-<n>)
# - Metadata (title, description, ...) read from the same tree

extractor = HTMLExtractor()
doc = extractor.extract("page.html")
```

#### XMLExtractor
**Extensions**: `.xml`
**Dependencies**: `lxml`

```python
# Features:
# - One representation: fenced XML for data documents, text for prose
# - External entities are not resolved
# - Tag/attribute analysis

extractor = XMLExtractor(include_comments=False, strip_namespaces=False)
doc = extractor.extract("data.xml")
```

### Extractors Using Extras

#### CSVExtractor
**Extensions**: `.csv`, `.tsv`
**Dependencies**: `pandas`, `chardet` (`pip install 'chomper[csv]'`)

```python
# Features:
# - One GFM table; values exactly as written (integers stay integers)
# - Delimiter detected across the first lines (, ; TAB |), Excel "sep=" hint honoured
# - Encoding detection (metadata["encoding"]); preamble lines kept out of the header
# - Malformed rows padded or merged, never dropped; listed in
#   metadata["bad_lines"] and metadata["bad_line_count"]

extractor = CSVExtractor(
    delimiter=None,   # Auto-detect
    encoding=None,    # Auto-detect
    has_header=None   # Auto-detect
)
doc = extractor.extract("data.csv")
```

#### YAMLExtractor
**Extensions**: `.yaml`, `.yml`
**Dependencies**: `pyyaml` (`pip install 'chomper[yaml]'`)

```python
# Features:
# - Source passed through in its original order
# - Multi-document support, structure analysis

extractor = YAMLExtractor(indent=2)
doc = extractor.extract("config.yaml")
```

#### MSGExtractor
**Extensions**: `.msg`
**Dependencies**: `extract-msg` (`pip install 'chomper[email]'`)

```python
# Same output layout as EMLExtractor: headers, body, inline images, attachments

extractor = MSGExtractor(include_headers=True, include_attachments=True)
doc = extractor.extract("email.msg")
```

#### EPUBExtractor
**Extensions**: `.epub`
**Dependencies**: `ebooklib`, `beautifulsoup4` (`pip install 'chomper[epub]'`)

```python
# Features:
# - Chapters in spine (reading) order, converted to Markdown
# - Short chapters kept; headings not duplicated (a heading-less chapter
#   gets its TOC title)
# - Images stored in the book become img-<n> records with markers
# - Metadata (author, title, etc.)

extractor = EPUBExtractor(include_toc=True, chapter_separator="\n\n")
doc = extractor.extract("book.epub")
```

#### RTFExtractor
**Extensions**: `.rtf`
**Dependencies**: `striprtf` (`pip install 'chomper[rtf]'`)

```python
# Features:
# - Bullets and numbering kept as Markdown lists, nested by level
# - Tables as GFM pipe tables

extractor = RTFExtractor()
doc = extractor.extract("document.rtf")
```

---

## Images

`src/extractors/image_utils.py` is shared by every extractor and entry point.

- **Lazy records.** Extractors call `image_record(...)` with size, position, page, a stable `id` and a loader. Nothing is decoded during a text-only parse.
- **Markers.** `image_marker(id, alt)` writes `![alt](image:<id>)` into the text. Ids are `p<page>-<n>` (PDF), `s<slide>-<n>` (PPTX) and `img-<n>` (DOCX, HTML, EPUB, email).
- **On request.** `collect_images(structure, page_filter=None, max_images=None, max_dimension=1568, image_id=None)` finds records however the extractor nested them, applies the filters, then loads, converts (PNG/JPEG/GIF/WebP, RGB-family) and downscales only the images it returns, capping each at 3.5 MB. Identical images are returned once with `pages` and `aliases`.
- **PDF vector figures** are rendered from their page region only when requested. PDF image loads take the shared PyMuPDF lock (`src/extractors/pymupdf_lock.py`).

---

## Chunkers

Chunkers split `RawDocument` text into smaller, manageable `Chunk` objects. Build them with `build_chunker()` in `src/server/documents.py`, which the library, CLI and MCP server all use.

### Base Class

```python
class BaseChunker(ABC):
    """Abstract base class for all chunkers."""

    def __init__(self, target_size: int = 300, overlap: int = 50, preserve_context: bool = True):
        self.target_size = target_size  # Maximum words per chunk
        self.overlap = overlap          # Words to overlap

    @abstractmethod
    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """Split document into chunks."""
        pass

    # Helper methods:
    def _split_by_word_count(self, text: str) -> list[str]
    def _split_by_paragraphs(self, text: str) -> list[str]
    def _split_by_sentences(self, text: str) -> list[str]
    def _create_chunk(self, text: str, chunk_id: int, start: int, end: int) -> Chunk
```

`build_chunker()` passes `target_size=chunk_size` (default 1000) and `overlap` (default 100).

### Structure-Aware Splitting

`src/chunking/text_splitter.py` is used by the Text, Markdown, DOCX, HTML and PPTX-fallback chunkers:

- Chunks are exact substrings (`text[start:end]`), so line breaks, list indentation, table rows and code fences survive and offsets are true.
- Cuts prefer headings, then blank lines, lines, sentences, and finally words; never inside a code fence or Markdown table row, never right after a heading.
- Every chunk adds at least one new unit, so the loop always terminates whatever the overlap; `overlap=0` is honoured.

### Format-Specific Chunkers

#### StructuralPDFChunker
Default for `.pdf` on `auto`. Reads the PDF directly (`src/pdf_structure/`): heading-bounded, table-safe and sentence-safe blocks with provenance. See [PDF_STRUCTURE.md](PDF_STRUCTURE.md).
```python
chunker = StructuralPDFChunker(target_size=500, overlap=50)
chunks = chunker.chunk_path("report.pdf", "report.pdf")
```

#### PDFChunker
Page or word-count slicing of an extracted PDF; still importable, no longer the default.

#### DOCXChunker
Preserves heading hierarchy:
```python
chunker = DOCXChunker(target_size=500)
# Respects heading boundaries
```

#### PPTXChunker
Slide-aware; `section_name` is the slide title.

#### CodeChunker
Respects function/class boundaries:
```python
chunker = CodeChunker(target_size=300)
# Tries to keep functions/classes intact
```

#### MarkdownChunker
Respects heading structure:
```python
chunker = MarkdownChunker(target_size=500)
# Splits at heading boundaries; metadata carries heading_path and heading_level
```

#### HTMLChunker
DOM structure aware:
```python
chunker = HTMLChunker(target_size=500)
# Respects semantic HTML elements
```

#### ExcelChunker
By sheet and table (also used for CSV/TSV); `section_name` is the sheet name.

#### TextChunker
Plain text, and the `recursive` (structure-first) and `fixed` (word windows on line breaks) strategies.

### SemanticChunker

Embedding-based chunking for RAG applications (needs `pip install 'chomper[semantic]'`):

```python
class SemanticChunker(BaseChunker):
    """
    Chunks documents based on semantic similarity.
    Uses sentence embeddings to find natural breakpoints.
    """

    MODELS = {
        "fast": "all-MiniLM-L6-v2",      # ~80MB, fastest
        "balanced": "all-mpnet-base-v2",  # ~420MB, better quality
    }

    STRATEGIES = ["percentile", "standard_deviation", "interquartile"]

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        model: str = "fast",
        breakpoint_strategy: str = "percentile",
        breakpoint_threshold: float = 0.5,
        min_chunk_size: int = 50,
        preserve_context: bool = True,
    ):
        ...

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        # 1. Split into sentences
        # 2. Compute embeddings (lazy model loading)
        # 3. Calculate cosine distances between adjacent sentences
        # 4. Find breakpoints using strategy
        # 5. Group sentences; small groups merge forward (no text is lost)
        # 6. Enforce target_size as a maximum and apply overlap
```

**Usage Example**:
```python
chunker = SemanticChunker(
    model="fast",                      # Quick embedding model
    breakpoint_strategy="percentile",  # Break at high-distance points
    breakpoint_threshold=0.75,         # 75th percentile
    target_size=300,                   # at most ~300 words per chunk
    overlap=50                         # 50 word overlap
)

chunks = chunker.chunk(raw_doc)
```

---

## Enrichers

Enrichers add computed metadata to chunks. Each takes a list of chunks and returns `EnrichedChunk`s: `enrich(chunks: list[Chunk]) -> list[EnrichedChunk]`. `DocumentPipeline` runs all four by default; the library, CLI and MCP tools use only TF-IDF keywords, on request.

### KeywordExtractor

Extracts important terms from text:
```python
enricher = KeywordExtractor(method="tfidf", top_k=8)   # or method="rake" (default)
enriched = enricher.enrich(chunks)

# IDF fitted across all of a document's chunks (what keywords=True uses):
keywords = enricher.keywords_for_texts([c.text for c in chunks])
```
TF-IDF needs scikit-learn (`keywords` extra) and falls back to RAKE without it. URLs, link targets and image file names are stripped before scoring.

### SectionDetector

Identifies document sections:
```python
detector = SectionDetector(method="heuristic")
enriched = detector.enrich(chunks)
# section_name: "Introduction" | "Methods" | "Results" | etc.
```

### TitleGenerator

Generates titles for sections:
```python
generator = TitleGenerator(method="first_sentence", max_length=80)
enriched = generator.enrich(chunks)
```

### MetadataEnricher

Adds computed metadata:
```python
enricher = MetadataEnricher(reading_speed=200)
enriched = enricher.enrich(chunks)
# Adds: reading_time, complexity_score, etc.
```

---

## Formatters

Formatters convert `ProcessedDocument` to output.

### SimpleFormatter

Plain dictionary output:
```python
formatter = SimpleFormatter(include_metadata=True)
output = formatter.format(document)
# Returns: dict
```

### TOONFormatter

Token-Optimized Object Notation (~40% token reduction):

```python
formatter = TOONFormatter(
    include_metadata=True,
    include_keywords=True,
    max_text_preview=None  # None = full text
)

# For full pipeline:
output = formatter.format(processed_document)

# For raw data (server use):
output = TOONFormatter.format_raw(
    file_path="doc.pdf",
    text="content...",
    metadata={"author": "John"},
    doc_type="pdf",
    total_chars=10000,
    total_words=2000
)

# For metadata only:
output = TOONFormatter.format_metadata_only(
    file_path="doc.pdf",
    metadata={...},
    doc_type="pdf",
    total_chars=10000,
    page_count=5
)

# For chunk response:
output = TOONFormatter.format_chunk_response(
    file_path="doc.pdf",
    text="chunk content...",
    offset=5000,
    limit=5000,
    total_chars=50000,
    has_more=True
)
```

**TOON Format Structure**:
```
d:filename.pdf|t:pdf|w:2000|c:10000|n:5
m:author=John,title=Report
---
0|0-2000|text|Introduction
Content of first chunk...
k:keyword1,keyword2
---
1|2000-4000|text|Methods
Content of second chunk...
k:keyword3,keyword4
```

### WeaviateFormatter

Vector database format:
```python
formatter = WeaviateFormatter(collection_name="Document")
output = formatter.format(document)
# Returns: list of Weaviate objects
```

### Neo4jFormatter

Graph database format:
```python
formatter = Neo4jFormatter()
output = formatter.format(document)
# Returns: dict with document_node, chunk_nodes, section_nodes and relationships
```

---

## Handlers

Handlers implement MCP tool logic. Each async handler validates its arguments and runs the blocking work in a worker thread (`run_blocking`), reading documents through the shared cache. Errors are raised and turned into `isError` results by `server.dispatch_tool`.

### parse.py

```python
async def handle_parse_document(arguments: dict) -> list[TextContent | ImageContent]:
    """
    Main document parsing handler.

    Arguments:
        file_path: Absolute path to document
        full_text: Return all text (default: False, returns 5000 chars)
        include_images: Include up to 5 images (default: False)
        output_format: "json" or "toon"

    Returns:
        [TextContent(text), TextContent(metadata), (TextContent(info), ImageContent)...]
    """

async def handle_parse_document_bytes(arguments: dict) -> list[TextContent | ImageContent]:
    """
    Parse base64-encoded document (decoded size at most 100 MB, never cached).

    Arguments:
        content_base64: Base64-encoded file content
        filename: Filename with extension for format detection
        full_text, include_images, output_format: Same as parse_document

    Returns:
        Same as parse_document
    """
```

### chunk.py

```python
async def handle_get_document_chunk(arguments: dict) -> list[TextContent]:
    """
    Paginated document retrieval.

    Arguments:
        file_path: Document path
        offset: Character offset (default: 0; must be inside the document)
        limit: Max characters (default: 5000)
        output_format: "json" or "toon"

    Returns:
        [TextContent(chunk), TextContent(metadata)]
    """

async def handle_parse_document_chunked(arguments: dict) -> list[TextContent]:
    """
    Chunking for RAG, through chunk_document().

    Arguments:
        file_path: Document path
        chunk_size: Maximum words per chunk (default: 1000)
        overlap: Overlap words (default: 100)
        chunking_strategy: "auto", "recursive", "fixed", "semantic"
        embedding_model: "fast" or "balanced"
        include_keywords: TF-IDF keywords per chunk (default: False)
        output_format: "json" or "toon"

    Returns:
        [TextContent(chunks_json)]
    """
```

### images.py

```python
async def handle_get_document_images(arguments: dict) -> list[TextContent | ImageContent]:
    """
    On-demand image retrieval.

    Arguments:
        file_path: Document path
        page: Specific page or slide (1-indexed, optional)
        max_images: Limit (default: 5)
        image_id: Only the image with this id (from an ![...](image:<id>) marker)
        max_dimension: Long-edge cap in pixels (default: 1568; 0 = full size)

    Returns:
        [TextContent(summary), (TextContent(image info), ImageContent)...]
    """
```

### metadata.py

```python
async def handle_extract_metadata(arguments: dict) -> list[TextContent]:
    """
    Metadata extraction (cached extraction reused).

    Arguments:
        file_path: Document path
        output_format: "json" or "toon"

    Returns:
        [TextContent(metadata_json)]
    """

async def handle_list_supported_formats(arguments: dict) -> list[TextContent]:
    """
    List formats with availability and install hints.

    Returns:
        [TextContent(formats_json)]
    """
```

### batch.py

```python
async def handle_batch_parse(arguments: dict) -> list[TextContent]:
    """
    Batch document processing: up to 500 files, min(4, CPUs) at a time,
    results in input order.

    Arguments:
        file_paths: Array of paths
        options:
            include_images: bool (default: False) - adds image_count
            continue_on_error: bool (default: True)

    Returns:
        [TextContent(results_json)]
    """
```

---

## Models

### RawDocument

```python
@dataclass
class RawDocument:
    """Output from extractors."""
    text: str                                       # Full extracted text
    metadata: dict[str, Any] = field(default_factory=dict)  # File metadata
    structure: dict[str, Any] | None = None         # Pages, sections, images
```

### Chunk

```python
@dataclass
class Chunk:
    """Output from chunkers."""
    chunk_id: int
    text: str
    start_char: int = 0
    end_char: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())
```

### EnrichedChunk

```python
@dataclass
class EnrichedChunk(Chunk):
    """Output from enrichers."""
    keywords: list[str] = field(default_factory=list)
    section_name: str | None = None
    section_type: str = "text"
    computed_metadata: dict[str, Any] = field(default_factory=dict)
```

### ProcessedDocument

```python
@dataclass
class ProcessedDocument:
    """Final pipeline output."""
    document_id: str
    source: str
    doc_type: str
    chunks: list[EnrichedChunk]
    metadata: dict[str, Any]
```

---

## Adding New Components

### Adding a New Extractor

1. Create `src/extractors/my_extractor.py`:
```python
from ..models.document import RawDocument
from .base import BaseExtractor

try:
    import my_library
    MY_LIBRARY_AVAILABLE = True
except ImportError:
    MY_LIBRARY_AVAILABLE = False

class MyExtractor(BaseExtractor):
    SUPPORTED_EXTENSIONS = [".myext"]

    def extract(self, file_path: str) -> RawDocument:
        self.validate_file(file_path)
        text = ...
        metadata = self._get_basic_metadata(file_path)
        return RawDocument(text=text, metadata=metadata)
```

2. Add the class to `_SOURCES` in `src/extractors/__init__.py`
3. Register in `src/server/config.py`:
```python
FORMAT_DESCRIPTIONS[".myext"] = "My format description"
_EXTRACTOR_SPECS[".myext"] = (
    "src.extractors.my_extractor", "MyExtractor",
    ("MY_LIBRARY_AVAILABLE",),        # flags that must be true
    "'chomper[myext]'",               # install hint
)
_CHUNKER_SPECS[".myext"] = ("src.chunking.strategies.text_chunker", "TextChunker", (), "")
```
4. Add an extra for the dependency in `pyproject.toml` (and `requirements.txt`)

### Adding a New Chunker

1. Create `src/chunking/strategies/my_chunker.py`:
```python
from ..base import BaseChunker

class MyChunker(BaseChunker):
    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        # Implementation; prefer src/chunking/text_splitter.py for free text
```

2. Add to `src/chunking/strategies/__init__.py`
3. Register the extension in `_CHUNKER_SPECS` in `src/server/config.py`. It is constructed by `build_chunker()` as `MyChunker(target_size=chunk_size, overlap=overlap)`.

### Adding a New Formatter

1. Create `src/formatters/my_formatter.py`:
```python
from .base import BaseFormatter

class MyFormatter(BaseFormatter):
    def format(self, document: ProcessedDocument) -> Any:
        # Implementation
```

2. Add to `src/formatters/__init__.py`
