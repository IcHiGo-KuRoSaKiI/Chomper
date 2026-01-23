# Chomper Components

Detailed documentation for all Chomper components: extractors, chunkers, enrichers, formatters, and handlers.

## Table of Contents

- [Extractors](#extractors)
- [Chunkers](#chunkers)
- [Enrichers](#enrichers)
- [Formatters](#formatters)
- [Handlers](#handlers)
- [Models](#models)

---

## Extractors

Extractors are responsible for converting files into `RawDocument` objects containing text, metadata, and optional structure information.

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

    def validate_file(self, file_path: str) -> Path:
        """Validate file exists and has supported extension."""
        pass

    def _get_basic_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Return basic file metadata (name, size, extension)."""
        pass
```

### Always Available Extractors

These extractors use only Python standard library:

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

extractor = TextExtractor()
doc = extractor.extract("readme.txt")
```

#### MarkdownExtractor
**Extensions**: `.md`, `.markdown`

```python
# Features:
# - Heading hierarchy detection
# - Code block identification
# - Link extraction

extractor = MarkdownExtractor()
doc = extractor.extract("README.md")
# doc.structure includes: headings, code_blocks, links
```

#### JSONExtractor
**Extensions**: `.json`

```python
# Features:
# - Pretty-printed output
# - Structure analysis (keys, depth, array/object counts)
# - Max depth limiting

extractor = JSONExtractor(indent=2, max_depth=10)
doc = extractor.extract("config.json")
```

#### EMLExtractor
**Extensions**: `.eml`

```python
# Features:
# - Header parsing (From, To, Subject, Date)
# - Body extraction (plain text and HTML)
# - Attachment listing

extractor = EMLExtractor(include_headers=True, include_attachments=True)
doc = extractor.extract("email.eml")
```

### Optional Extractors

These require additional dependencies:

#### PDFExtractor
**Extensions**: `.pdf`
**Dependencies**: `pymupdf`, optional `pymupdf4llm`

```python
# Features:
# - Text extraction with layout preservation
# - Markdown table formatting (with pymupdf4llm)
# - Image extraction with position info
# - Page-by-page structure

extractor = PDFExtractor(
    use_markdown=True,           # Use pymupdf4llm for better tables
    table_strategy='lines_strict' # Table detection strategy
)
doc = extractor.extract("report.pdf")
# doc.structure includes: pages[], images[]
```

#### DOCXExtractor
**Extensions**: `.docx`, `.doc`
**Dependencies**: `python-docx`

```python
# Features:
# - Paragraph extraction
# - Heading detection
# - Table extraction
# - Style preservation

extractor = DOCXExtractor()
doc = extractor.extract("document.docx")
```

#### PPTXExtractor
**Extensions**: `.pptx`, `.ppt`
**Dependencies**: `python-pptx`

```python
# Features:
# - Slide-by-slide extraction
# - Speaker notes
# - Shape text extraction

extractor = PPTXExtractor()
doc = extractor.extract("presentation.pptx")
```

#### ExcelExtractor
**Extensions**: `.xlsx`, `.xlsm`, `.xltx`, `.xltm`
**Dependencies**: `openpyxl`

```python
# Features:
# - Sheet-by-sheet extraction
# - Cell type detection
# - Formula handling

extractor = ExcelExtractor()
doc = extractor.extract("data.xlsx")
```

#### CSVExtractor
**Extensions**: `.csv`, `.tsv`
**Dependencies**: `pandas`, `chardet`

```python
# Features:
# - Auto-delimiter detection (, ; \t |)
# - Encoding auto-detection
# - Header inference

extractor = CSVExtractor(
    delimiter=None,   # Auto-detect
    encoding=None,    # Auto-detect via chardet
    has_header=None   # Auto-detect
)
doc = extractor.extract("data.csv")
```

#### HTMLExtractor
**Extensions**: `.html`, `.htm`
**Dependencies**: `beautifulsoup4`, `trafilatura`, `lxml`

```python
# Features:
# - Main content extraction (via trafilatura)
# - Semantic structure preservation
# - Metadata extraction (title, description)

extractor = HTMLExtractor()
doc = extractor.extract("page.html")
```

#### YAMLExtractor
**Extensions**: `.yaml`, `.yml`
**Dependencies**: `pyyaml`

```python
# Features:
# - Multi-document support
# - Structure analysis

extractor = YAMLExtractor(indent=2)
doc = extractor.extract("config.yaml")
```

#### XMLExtractor
**Extensions**: `.xml`
**Dependencies**: `lxml`

```python
# Features:
# - Pretty-printed output
# - Tag/attribute analysis
# - Depth limiting

extractor = XMLExtractor(pretty_print=True, max_depth=10)
doc = extractor.extract("data.xml")
```

#### MSGExtractor
**Extensions**: `.msg`
**Dependencies**: `extract-msg`

```python
# Features:
# - Outlook message parsing
# - Attachment extraction
# - Rich header support

extractor = MSGExtractor(include_headers=True, include_attachments=True)
doc = extractor.extract("email.msg")
```

#### EPUBExtractor
**Extensions**: `.epub`
**Dependencies**: `ebooklib`, `beautifulsoup4`

```python
# Features:
# - Chapter extraction
# - Table of contents
# - Metadata (author, title, etc.)

extractor = EPUBExtractor(
    include_toc=True,
    chapter_separator="\n\n---\n\n"
)
doc = extractor.extract("book.epub")
```

#### RTFExtractor
**Extensions**: `.rtf`
**Dependencies**: `striprtf`

```python
# Features:
# - RTF tag stripping
# - Text content extraction

extractor = RTFExtractor()
doc = extractor.extract("document.rtf")
```

---

## Chunkers

Chunkers split `RawDocument` text into smaller, manageable `Chunk` objects.

### Base Class

```python
class BaseChunker(ABC):
    """Abstract base class for all chunkers."""

    def __init__(self, target_size: int = 1000, overlap: int = 100):
        self.target_size = target_size  # Target words per chunk
        self.overlap = overlap          # Words to overlap

    @abstractmethod
    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        """Split document into chunks."""
        pass

    # Helper methods:
    def _split_by_word_count(self, text: str) -> List[str]
    def _split_by_paragraphs(self, text: str) -> List[str]
    def _split_by_sentences(self, text: str) -> List[str]
    def _create_chunk(self, text: str, chunk_id: int, start: int, end: int) -> Chunk
```

### Format-Specific Chunkers

#### PDFChunker
Respects page boundaries:
```python
chunker = PDFChunker(target_size=500, overlap=50)
# Keeps content from same page together when possible
```

#### DOCXChunker
Preserves heading hierarchy:
```python
chunker = DOCXChunker(target_size=500)
# Respects heading boundaries
```

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
# Splits at heading boundaries
```

#### HTMLChunker
DOM structure aware:
```python
chunker = HTMLChunker(target_size=500)
# Respects semantic HTML elements
```

### SemanticChunker

Embedding-based chunking for RAG applications:

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

    STRATEGIES = {
        "percentile": "Break at distances > Nth percentile",
        "standard_deviation": "Break at N std devs from mean",
        "interquartile": "Break outside IQR"
    }

    def __init__(
        self,
        target_size: int = 300,
        overlap: int = 50,
        model: str = "fast",
        breakpoint_strategy: str = "percentile",
        breakpoint_threshold: float = 0.5,
        min_chunk_size: int = 50
    ):
        ...

    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        # 1. Split into sentences
        # 2. Compute embeddings (lazy model loading)
        # 3. Calculate cosine distances between adjacent sentences
        # 4. Find breakpoints using strategy
        # 5. Group sentences into chunks
        # 6. Apply overlap
```

**Usage Example**:
```python
chunker = SemanticChunker(
    model="fast",                      # Quick embedding model
    breakpoint_strategy="percentile",  # Break at high-distance points
    breakpoint_threshold=0.75,         # 75th percentile
    target_size=300,                   # ~300 words per chunk
    overlap=50                         # 50 word overlap
)

chunks = chunker.chunk(raw_doc)
```

---

## Enrichers

Enrichers add computed metadata to chunks.

### KeywordExtractor

Extracts important terms from text:
```python
enricher = KeywordExtractor(max_keywords=10, method="tfidf")
keywords = enricher.extract(chunk.text)
# Returns: ["important", "terms", "from", "text"]
```

### SectionDetector

Identifies document sections:
```python
detector = SectionDetector()
section = detector.detect(chunk.text, position=0.1)
# Returns: "Introduction" | "Methods" | "Results" | etc.
```

### TitleGenerator

Generates titles for sections:
```python
generator = TitleGenerator()
title = generator.generate(chunk.text)
# Returns: "Overview of Machine Learning Concepts"
```

### MetadataEnricher

Adds computed metadata:
```python
enricher = MetadataEnricher()
metadata = enricher.enrich(chunk)
# Adds: reading_time, complexity_score, etc.
```

---

## Formatters

Formatters convert `ProcessedDocument` to output strings.

### SimpleFormatter

Standard JSON output:
```python
formatter = SimpleFormatter(
    include_metadata=True,
    include_keywords=True
)
output = formatter.format(document)
# Returns: JSON string
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
    doc_info={...}
)

# For chunk response:
output = TOONFormatter.format_chunk_response(
    file_path="doc.pdf",
    text="chunk content...",
    offset=5000,
    limit=5000,
    total_chars=50000
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
formatter = WeaviateFormatter(class_name="Document")
output = formatter.format(document)
# Returns: Weaviate-compatible objects
```

### Neo4jFormatter

Graph database format:
```python
formatter = Neo4jFormatter()
output = formatter.format(document)
# Returns: Cypher-compatible data
```

---

## Handlers

Handlers implement MCP tool logic.

### parse.py

```python
async def handle_parse_document(arguments: dict) -> List[TextContent | ImageContent]:
    """
    Main document parsing handler.

    Arguments:
        file_path: Absolute path to document
        full_text: Return all text (default: False, returns 5000 chars)
        include_images: Include images (default: False)
        output_format: "json" or "toon"

    Returns:
        [TextContent(text), TextContent(metadata), ImageContent[]...]
    """

async def handle_parse_document_bytes(arguments: dict) -> List[TextContent | ImageContent]:
    """
    Parse base64-encoded document.

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
async def handle_get_document_chunk(arguments: dict) -> List[TextContent]:
    """
    Paginated document retrieval.

    Arguments:
        file_path: Document path
        offset: Character offset (default: 0)
        limit: Max characters (default: 5000)
        output_format: "json" or "toon"

    Returns:
        [TextContent(chunk), TextContent(metadata)]
    """

async def handle_parse_document_chunked(arguments: dict) -> List[TextContent]:
    """
    Semantic chunking for RAG.

    Arguments:
        file_path: Document path
        chunk_size: Target words per chunk (default: 1000)
        overlap: Overlap words (default: 100)
        chunking_strategy: "auto", "semantic", "fixed", "recursive"
        embedding_model: "fast" or "balanced"
        output_format: "json" or "toon"

    Returns:
        [TextContent(chunks_json)]
    """
```

### images.py

```python
async def handle_get_document_images(arguments: dict) -> List[TextContent | ImageContent]:
    """
    On-demand image retrieval.

    Arguments:
        file_path: Document path
        page: Specific page (1-indexed, optional)
        max_images: Limit (default: 5)

    Returns:
        [TextContent(summary), ImageContent[]...]
    """
```

### metadata.py

```python
async def handle_extract_metadata(arguments: dict) -> List[TextContent]:
    """
    Quick metadata extraction.

    Arguments:
        file_path: Document path
        output_format: "json" or "toon"

    Returns:
        [TextContent(metadata_json)]
    """

async def handle_list_supported_formats(arguments: dict) -> List[TextContent]:
    """
    List available formats.

    Returns:
        [TextContent(formats_json)]
    """
```

### batch.py

```python
async def handle_batch_parse(arguments: dict) -> List[TextContent]:
    """
    Batch document processing.

    Arguments:
        file_paths: Array of paths
        options:
            include_images: bool (default: False)
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
    text: str                           # Full extracted text
    metadata: Dict[str, Any]            # File metadata
    structure: Optional[Dict] = None    # Pages, sections, images
```

### Chunk

```python
@dataclass
class Chunk:
    """Output from chunkers."""
    chunk_id: int
    text: str
    start_char: int
    end_char: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())
```

### EnrichedChunk

```python
@dataclass
class EnrichedChunk(Chunk):
    """Output from enrichers."""
    keywords: List[str] = field(default_factory=list)
    section_name: Optional[str] = None
    section_type: str = "text"
    computed_metadata: Dict[str, Any] = field(default_factory=dict)
```

### ProcessedDocument

```python
@dataclass
class ProcessedDocument:
    """Final pipeline output."""
    document_id: str
    source: str
    doc_type: str
    chunks: List[EnrichedChunk]
    metadata: Dict[str, Any]
```

---

## Adding New Components

### Adding a New Extractor

1. Create `src/extractors/my_extractor.py`:
```python
from .base import BaseExtractor
from src.models import RawDocument

class MyExtractor(BaseExtractor):
    def extract(self, file_path: str) -> RawDocument:
        path = self.validate_file(file_path)
        text = self._extract_text(path)
        metadata = self._get_basic_metadata(path)
        return RawDocument(text=text, metadata=metadata)
```

2. Add to `src/extractors/__init__.py`
3. Register in `src/server/config.py`:
```python
EXTRACTORS[".myext"] = MyExtractor
FORMAT_DESCRIPTIONS[".myext"] = "My format description"
```

### Adding a New Chunker

1. Create `src/chunking/strategies/my_chunker.py`:
```python
from .base import BaseChunker

class MyChunker(BaseChunker):
    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        # Implementation
```

2. Add to `src/chunking/strategies/__init__.py`
3. Register in `src/server/config.py`

### Adding a New Formatter

1. Create `src/formatters/my_formatter.py`:
```python
from .base import BaseFormatter

class MyFormatter(BaseFormatter):
    def format(self, document: ProcessedDocument) -> str:
        # Implementation
```

2. Add to `src/formatters/__init__.py`
