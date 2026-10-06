# Chomper Architecture

This document provides a comprehensive overview of Chomper's architecture, data flow, and component relationships.

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [Server Layer](#server-layer)
- [Modular Structure](#modular-structure)
- [Processing Pipeline](#processing-pipeline)
- [Data Flow](#data-flow)
- [Component Details](#component-details)
- [Design Patterns](#design-patterns)
- [Dependency Management](#dependency-management)

---

## High-Level Architecture

Chomper follows a **layered architecture** with clear separation of concerns. The MCP server, the Python library (`chomper.py`) and the CLI (`cli.py`) all load documents through one service module, `src/server/documents.py`.

```
┌─────────────────────────────────────────────────────────────────────┐
│          MCP Client (Claude)    │   chomper.py   │    cli.py        │
└─────────────────────────────────────────────────────────────────────┘
                 │                          │
                 ▼                          │
┌─────────────────────────────────────────────────────────────────────┐
│                      SERVER LAYER (server.py)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────┐  │
│  │ list_tools  │ │ call_tool   │ │list_prompts │ │  get_prompt  │  │
│  └─────────────┘ └─────────────┘ └─────────────┘ └──────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                 │                          │
                 ▼                          │
┌─────────────────────────────────────────────────────────────────────┐
│                    HANDLER LAYER (src/handlers/)                    │
│  ┌───────────┐ ┌────────────┐ ┌───────────┐ ┌──────────┐ ┌───────┐ │
│  │  parse.py │ │  chunk.py  │ │ images.py │ │metadata.py│ │batch.py│ │
│  └───────────┘ └────────────┘ └───────────┘ └──────────┘ └───────┘ │
└─────────────────────────────────────────────────────────────────────┘
                 │                          │
                 ▼                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│     SHARED SERVICE (src/server/documents.py, cache.py, config.py)   │
│   load_document (cached) · chunk_document · build_chunker           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   PROCESSING PIPELINE (src/)                        │
│                                                                     │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   │  Extractors │ -> │   Chunkers  │ -> │  Enrichers  │ -> │ Formatters  │
│   │  (Layer 1)  │    │  (Layer 2)  │    │  (Layer 3)  │    │  (Layer 4)  │
│   └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
│         │                  │                  │                  │
│         ▼                  ▼                  ▼                  ▼
│    RawDocument         list[Chunk]    list[EnrichedChunk]   JSON/TOON
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Server Layer

### Entry Point: `server.py`

The MCP server entry point delegates all work to modular handlers through a dispatch table:

```python
# server.py structure
from mcp.server import Server
from src.server.tools import get_tools
from src.handlers import handle_parse_document, handle_parse_document_bytes, ...

server = Server("chomper")

TOOL_HANDLERS = {
    "parse_document": handle_parse_document,
    "parse_document_bytes": handle_parse_document_bytes,
    # ... one entry per tool
}

async def dispatch_tool(name, arguments):
    handler = TOOL_HANDLERS.get(name)
    ...
    validate_arguments(_TOOL_SCHEMAS[name], arguments)  # names the bad argument
    return await handler(arguments)
    # any exception -> tool_error(): CallToolResult(isError=True)

@server.call_tool(validate_input=False)  # Chomper validates, with actionable messages
async def call_tool(name, arguments):
    return await dispatch_tool(name, arguments)

def run() -> None:          # the `chomper` console script
    asyncio.run(main())
```

### MCP Decorators

| Decorator | Purpose | Delegates To |
|-----------|---------|--------------|
| `@server.list_tools()` | Return available tools | `get_tools()` from tools.py |
| `@server.call_tool()` | Execute tool requests | `dispatch_tool()` → handlers in `src/handlers/` |
| `@server.list_prompts()` | Return analysis prompts | `PROMPTS` from `src/prompts/` |
| `@server.get_prompt()` | Format prompt with content | `format_prompt()` (document loaded through the cache) |

---

## Modular Structure

### Directory Layout

```
src/
├── server/                    # Server infrastructure
│   ├── __init__.py           # Lazy re-exports (PEP 562)
│   ├── config.py             # Constants, lazy EXTRACTORS/CHUNKERS registries
│   ├── documents.py          # validate_path, load_document, build_chunker, chunk_document
│   ├── cache.py              # Thread-safe LRU of extractions and structural parses
│   ├── tools.py              # MCP Tool definitions (get_tools())
│   └── helpers.py            # Argument validation, base64, images, run_blocking
│
├── handlers/                  # Tool implementations
│   ├── __init__.py           # Exports all handlers
│   ├── parse.py              # parse_document, parse_document_bytes
│   ├── chunk.py              # get_document_chunk, parse_document_chunked
│   ├── images.py             # get_document_images
│   ├── metadata.py           # extract_metadata, list_supported_formats
│   └── batch.py              # batch_parse
│
├── extractors/                # Format-specific extraction (16 extractor classes)
│   ├── pdf_extractor.py      # PDFExtractor (backend, ocr, table_format, ...)
│   ├── pdf_layout.py         # pymupdf-layout pass: Markdown, figures, OCR
│   ├── html_markdown.py      # DOM-to-Markdown walker (HTML, EPUB, email)
│   ├── markdown_utils.py     # Shared Markdown rendering (tables, lists)
│   ├── encoding_utils.py     # Text encoding detection
│   ├── image_utils.py        # Lazy image records, markers, downscaling
│   └── pymupdf_lock.py       # One lock for all PyMuPDF calls
├── pdf_structure/             # Structural PDF parse (headings, tables, lists, figures, cell marks)
├── chunking/                  # Chunking strategies (10 chunkers + SemanticChunker)
│   └── text_splitter.py      # Structure-aware span splitter shared by text chunkers
├── enrichment/                # Metadata enrichment (4 enrichers)
├── formatters/                # Output formatting (4 formatters)
├── cli/                       # CLI formatters, watch mode, interactive REPL
├── prompts/                   # MCP prompt definitions
├── models/                    # Data classes (RawDocument, Chunk, etc.)
└── pipeline.py               # DocumentPipeline orchestrator
```

### src/server/config.py

Centralized configuration hub:

```python
# Constants
DEFAULT_SUMMARY_CHARS = 5000    # Default text limit
DEFAULT_CHUNK_LIMIT = 5000      # Pagination limit
DEFAULT_MAX_IMAGES = 5          # Image retrieval limit
DEFAULT_CHUNK_SIZE = 1000       # Words per chunk
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_CHUNK_STRATEGY = "auto"
CHUNK_STRATEGIES = ("auto", "semantic", "fixed", "recursive")
MAX_BYTES_INPUT = 100 * 1024 * 1024   # parse_document_bytes / parse_bytes cap
OUTPUT_FORMAT_JSON = "json"     # Default output
OUTPUT_FORMAT_TOON = "toon"     # Token-optimized

# Format descriptions (36 extensions)
FORMAT_DESCRIPTIONS = {
    ".pdf": "PDF documents with text and image extraction",
    ".docx": "Microsoft Word documents (OOXML format)",
    # ...
}

# (module, class, availability flags, pip hint) per extension
_EXTRACTOR_SPECS = {
    ".pdf": ("src.extractors.pdf_extractor", "PDFExtractor", (), "pymupdf pymupdf4llm"),
    ".csv": ("src.extractors.csv_extractor", "CSVExtractor", ("PANDAS_AVAILABLE",), "'chomper[csv]'"),
    # ...
}

# Read-only mappings that import a class the first time its extension is looked up
EXTRACTORS = LazyRegistry(_EXTRACTOR_SPECS)
CHUNKERS = LazyRegistry(_CHUNKER_SPECS, companion=EXTRACTORS)

EXTRACTORS.known()                    # every extension, imports nothing
".csv" in EXTRACTORS                  # False if pandas is missing
EXTRACTORS.unavailable_reason(".csv") # "... Install with: pip install 'chomper[csv]'"
```

### src/server/documents.py

The one loader shared by the library, CLI, MCP handlers and `DocumentPipeline`:

| Function | Purpose |
|----------|---------|
| `validate_path()` | Expand, resolve and check the path is an existing file |
| `extractor_class_for()` | Extractor class for an extension, or a `ValueError` with the install hint |
| `load_document()` | Cached extraction into a `RawDocument` |
| `build_chunker()` | One chunker factory for `auto`/`recursive`/`fixed`/`semantic` |
| `chunk_document()` | Chunk a file; PDFs on `auto` go straight to `StructuralPDFChunker.chunk_path()` |
| `add_keywords()` | TF-IDF keywords fitted across a document's chunks |

### src/server/cache.py

A bounded, thread-safe LRU with single-flight loading: concurrent requests for the same file run the extractor once. Keys are resolved path, `st_mtime_ns`, `st_size`, extractor class and options, so an edited file is re-extracted. Temporary files from the `*_bytes` APIs are never cached.

| Variable | Effect |
|----------|--------|
| `CHOMPER_CACHE_SIZE` | Entries per cache (default 16); `0` disables |
| `CHOMPER_DISABLE_CACHE` | `1`/`true`/`yes` disables |

`serialized_for(path)` takes the PyMuPDF lock for PDFs, because MuPDF is not thread-safe and handlers run in worker threads.

### src/server/helpers.py

Shared utility functions:

| Function | Purpose |
|----------|---------|
| `run_blocking()` | Run blocking work in a thread (`asyncio.to_thread`) |
| `validate_arguments()` | Check arguments against a tool schema, naming the bad argument |
| `int_arg()` | Read and range-check an integer argument |
| `validate_file_path()` | Expand, resolve, validate file paths |
| `decode_base64_content()` / `parse_from_base64()` | Decode base64 (100 MB cap) to a temp file |
| `extract_images_from_structure()` | Select, load, downscale and encode images (page, id, max filters) |
| `count_images_in_structure()` | Count images without decoding them |
| `remove_image_placeholders()` | Clean legacy `[Image: WxH]` patterns (keeps `![...](image:<id>)` markers) |
| `detect_mime_type()` | Infer MIME from base64 prefix |
| `chunk_to_dict()` | Serialize Chunk to dict |

### src/server/tools.py

MCP tool definitions:

```python
def get_tools() -> list[Tool]:
    return [
        Tool(
            name="parse_document",
            description="Parse a document and extract text, metadata, and images...",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "..."},
                    "full_text": {"type": "boolean", "default": False},
                    "include_images": {"type": "boolean", "default": False},
                    "output_format": {"type": "string", "enum": ["json", "toon"]}
                },
                "required": ["file_path"]
            }
        ),
        # ... 7 more tools
    ]
```

---

## Processing Pipeline

### Four-Stage Pipeline

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  EXTRACTION │    │  CHUNKING   │    │ ENRICHMENT  │    │ FORMATTING  │
│             │    │             │    │             │    │             │
│ PDF → MD    │ -> │ Text →      │ -> │ Chunks →    │ -> │ Enriched →  │
│ DOCX → MD   │    │ Chunks      │    │ Enriched    │    │ JSON/TOON   │
│ Code → Text │    │             │    │ Chunks      │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼
 RawDocument        list[Chunk]     list[EnrichedChunk]    Output String
```

The MCP tools and the library use extraction and chunking, plus TF-IDF keywords on request (`include_keywords` / `keywords=True`). The full four stages run in `DocumentPipeline` (`src/pipeline.py`), which shares the same registry, cache and chunker factory.

### Stage 1: Extraction

**Input**: File path
**Output**: `RawDocument(text, metadata, structure)`

```python
class RawDocument:
    text: str                        # Full extracted text (Markdown for rich formats)
    metadata: dict[str, Any]         # author, title, created, etc.
    structure: dict | None           # pages, sections, sheets, images
```

Text carries `![caption](image:<id>)` markers where images sit. Image records in `structure` hold size, position, page, id and a loader; bytes are read only when requested.

**Extractors** (16 classes):
- **No extra dependencies**: Code, Text, Markdown, JSON, EML
- **Core dependencies**: PDF, DOCX, PPTX, Excel, HTML, XML
- **Extras**: CSV, YAML, MSG, EPUB, RTF

### Stage 2: Chunking

**Input**: `RawDocument` (or, for PDFs on `auto`, the file path)
**Output**: `list[Chunk]`

```python
class Chunk:
    chunk_id: int
    text: str
    start_char: int
    end_char: int
    metadata: dict[str, Any]
```

**Strategies**:
| Strategy | Description | Use Case |
|----------|-------------|----------|
| `auto` | Format-aware (PDF structure, headings, code by function, sheets) | Default |
| `recursive` | Headings > blank lines > lines > sentences | Structured text |
| `fixed` | Word windows that break between lines | Simple splitting |
| `semantic` | Embedding-based breakpoints | RAG systems |

Text-based chunkers cut with `src/chunking/text_splitter.py`: chunks are exact substrings, never cut inside a code fence or table row or right after a heading, and the loop always terminates whatever the overlap.

### Stage 3: Enrichment

**Input**: `list[Chunk]`
**Output**: `list[EnrichedChunk]`

```python
class EnrichedChunk(Chunk):
    keywords: list[str]              # Extracted key terms
    section_name: str | None         # "Introduction", "Methods"
    section_type: str                # "text", "code", "table"
    computed_metadata: dict[str, Any]
```

**Enrichers**:
- `KeywordExtractor` - Extract important terms (RAKE, or TF-IDF with scikit-learn)
- `SectionDetector` - Identify document sections
- `TitleGenerator` - Generate section titles
- `MetadataEnricher` - Add computed metadata

### Stage 4: Formatting

**Input**: `ProcessedDocument`
**Output**: String (JSON or TOON)

**Formatters**:
| Formatter | Output | Token Usage |
|-----------|--------|-------------|
| `SimpleFormatter` | JSON | Baseline |
| `TOONFormatter` | TOON | ~40% reduction |
| `WeaviateFormatter` | Vector DB format | - |
| `Neo4jFormatter` | Graph DB format | - |

---

## Data Flow

### Request: `parse_document`

```
MCP Request: parse_document(file_path="/docs/report.pdf", include_images=true)
    │
    ▼
┌─────────────────────────────────────────────────┐
│ server.py: dispatch_tool()                      │
│   → validate_arguments() against the schema     │
│   → handle_parse_document()                     │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ handlers/parse.py (in a worker thread)          │
│   1. validate_file_path("/docs/report.pdf")     │
│   2. load_document() → cache hit, or            │
│      PDFExtractor().extract() → RawDocument     │
│   3. remove_image_placeholders()                │
│   4. Truncate to 5000 chars (if full_text=false)│
│   5. Format metadata (JSON or TOON)             │
│   6. Load + downscale up to 5 images            │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ MCP Response:                                   │
│   TextContent[0]: Document text (5000 chars)    │
│   TextContent[1]: Metadata JSON                 │
│   ImageContent[]: Extracted images              │
└─────────────────────────────────────────────────┘
```

### Request: `parse_document_bytes`

```
MCP Request: parse_document_bytes(content_base64="...", filename="report.pdf")
    │
    ▼
┌─────────────────────────────────────────────────┐
│ handlers/parse.py: handle_parse_document_bytes()│
│   1. parse_from_base64() → temp_file_path       │
│      (validated base64, 100 MB cap)             │
│   2. Reuse parse_document logic, uncached       │
│   3. Replace temp paths with original filename  │
│   4. Delete temp file                           │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ MCP Response: Same as parse_document            │
│   (but file_path shows original filename)       │
└─────────────────────────────────────────────────┘
```

### Request: `parse_document_chunked` (Semantic)

```
MCP Request: parse_document_chunked(
    file_path="/docs/report.pdf",
    chunking_strategy="semantic",
    embedding_model="fast"
)
    │
    ▼
┌─────────────────────────────────────────────────┐
│ handlers/chunk.py (in a worker thread)          │
│   1. validate_chunk_options(), validate path    │
│   2. chunk_document()                           │
│      - build_chunker() → SemanticChunker        │
│        (loads all-MiniLM-L6-v2 lazily)          │
│      - load_document() → RawDocument (cached)   │
│      - chunker.chunk() → list[Chunk]            │
│      - add_keywords() if include_keywords       │
│   3. chunk_to_dict() per chunk                  │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ MCP Response:                                   │
│   {                                             │
│     "total_chunks": 15,                         │
│     "chunking_strategy": "semantic",            │
│     "chunks": [                                 │
│       {"chunk_id": 0, "text": "...", ...},      │
│       ...                                       │
│     ]                                           │
│   }                                             │
└─────────────────────────────────────────────────┘
```

With `auto` on a PDF, `chunk_document()` calls `StructuralPDFChunker.chunk_path()` on the file and skips the Markdown extraction pass; it falls back to extraction if the structural parse fails.

---

## Component Details

### Extractors

**Base Class**:
```python
class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, file_path: str) -> RawDocument:
        """Extract text, metadata, and structure from file"""

    def validate_file(self, file_path: str) -> None:
        """Validate file exists and has correct extension"""

    def _get_basic_metadata(self, file_path: str) -> dict:
        """Return filename, size, extension, etc."""
```

**Implementation Matrix**:

| Extractor | Extensions | Dependencies | Install |
|-----------|-----------|--------------|---------|
| `CodeExtractor` | .py, .js, .ts, .java, etc. | None | core |
| `TextExtractor` | .txt, .text, .log | None | core |
| `MarkdownExtractor` | .md, .markdown | None | core |
| `JSONExtractor` | .json | None | core |
| `EMLExtractor` | .eml | None (beautifulsoup4 for HTML bodies) | core |
| `PDFExtractor` | .pdf | pymupdf, pymupdf4llm, pymupdf-layout | core |
| `DOCXExtractor` | .docx (.doc rejected with a message) | python-docx | core |
| `PPTXExtractor` | .pptx (.ppt rejected with a message) | python-pptx | core |
| `ExcelExtractor` | .xlsx, .xlsm, .xltx, .xltm | openpyxl | core |
| `HTMLExtractor` | .html, .htm | beautifulsoup4, lxml | core |
| `XMLExtractor` | .xml | lxml | core |
| `CSVExtractor` | .csv, .tsv | pandas, chardet | `csv` extra |
| `YAMLExtractor` | .yaml, .yml | pyyaml | `yaml` extra |
| `MSGExtractor` | .msg | extract-msg | `email` extra |
| `EPUBExtractor` | .epub | ebooklib, beautifulsoup4 | `epub` extra |
| `RTFExtractor` | .rtf | striprtf | `rtf` extra |

**PDF**: `PDFExtractor` runs the `pymupdf-layout` model once per document (`src/extractors/pdf_layout.py`) for text, headings, lists, tables, figures and reading order. Options: `backend` (`auto`/`layout`/`legacy`), `ocr` (`auto`/`off`/`force`), `table_format` (`markdown`/`html`), `extract_vector_figures`. Table cells are post-processed by `src/pdf_structure/cell_marks.py` (check marks) and lists by `src/pdf_structure/lists.py`.

### Chunkers

**SemanticChunker** (key implementation):
```python
class SemanticChunker(BaseChunker):
    MODELS = {
        "fast": "all-MiniLM-L6-v2",      # ~80MB, fastest
        "balanced": "all-mpnet-base-v2",  # ~420MB, best quality
    }

    # breakpoint_strategy: break where adjacent-sentence distance is above the
    # Nth percentile, N standard deviations above the mean, or outside the IQR
    STRATEGIES = ["percentile", "standard_deviation", "interquartile"]

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        # 1. Split into sentences
        # 2. Compute embeddings (lazy model loading)
        # 3. Calculate cosine distances between adjacent sentences
        # 4. Find breakpoints using strategy
        # 5. Group sentences, merging small groups forward
        # 6. Enforce target_size as a maximum, apply overlap
```

### TOONFormatter

**Token-Optimized Object Notation**:
```
d:report.pdf|t:pdf|w:5000|c:25000|n:10
m:author=John Doe,title=Annual Report
---
0|0-2500|text|Introduction
The document begins with an overview...
k:overview,introduction,summary
---
1|2500-5000|text|Methodology
The methodology section describes...
k:methodology,approach,methods
```

**Format Breakdown**:
- Line 1: Document header (`d:id|t:type|w:words|c:chars|n:chunks`)
- Line 2: Metadata (`m:key=value,key=value`)
- `---`: Section delimiter
- Chunk: `id|char_range|type|section_name`
- Keywords: `k:word1,word2,word3` (when keywords were requested)

---

## Design Patterns

### 1. Lazy Loading

Heavy dependencies load only when needed. `src/extractors/__init__.py`, `src/__init__.py` and `src/server/__init__.py` resolve their exports on first access (PEP 562), and the registries in `config.py` import an extractor the first time its extension is used. A cold parse of a Markdown file does not import PyMuPDF or pandas, and `import server` loads no extractor.

```python
# semantic_chunker.py - model loaded on first use, cached per process
def _get_embedding_model(model_name: str):
    if model_name in _model_cache:
        return _model_cache[model_name]
    from sentence_transformers import SentenceTransformer
    ...
```

### 2. Graceful Degradation

Optional extractors don't break the system. Each registry entry names module-level availability flags; when one is false, or the import fails, the extension is absent and the reason carries the install command:

```python
# In config.py
".csv": ("src.extractors.csv_extractor", "CSVExtractor", ("PANDAS_AVAILABLE",), "'chomper[csv]'"),

".csv" in EXTRACTORS                    # False without pandas
EXTRACTORS.unavailable_reason(".csv")   # "Optional dependency missing for .csv. Install with: pip install 'chomper[csv]'"
```

### 3. Handler Delegation

Clean separation between server and implementation:

```python
# server.py - thin dispatcher
async def dispatch_tool(name, arguments):
    validate_arguments(_TOOL_SCHEMAS[name], arguments)
    return await TOOL_HANDLERS[name](arguments)

# handlers/parse.py - all logic here, off the event loop
async def handle_parse_document(arguments):
    return await run_blocking(parse_document_sync, arguments)
```

### 4. One Loader, One Cache

The library, CLI, MCP handlers and `DocumentPipeline` all extract through `load_document()` and chunk through `build_chunker()`/`chunk_document()`, so strategy names, defaults and results cannot drift between entry points, and repeated calls on an unchanged file reuse one extraction.

### 5. Dual Output Formats

Most tools support JSON and TOON:

```python
if output_format == "toon":
    return TOONFormatter.format_raw(...)
else:
    return json.dumps(...)
```

---

## Dependency Management

### Installation Modes

```bash
# Core: PDF, Office, HTML/XML, code, text, Markdown, JSON, EML
pip install -e .

# Everything (CSV, YAML, MSG, EPUB, RTF, keywords, semantic, sentences, templates)
pip install -e ".[all]"

# Development (all + pytest, ruff, mypy, black, reportlab)
pip install -e ".[dev]"
```

### Dependency Tiers

| Tier | Packages | Enables |
|------|----------|---------|
| **Core** | mcp, pymupdf/pymupdf4llm/pymupdf-layout ==1.28.2, python-docx, python-pptx, openpyxl, beautifulsoup4, lxml, pillow | MCP; PDF, DOCX, PPTX, Excel, HTML, XML; code, text, Markdown, JSON, EML |
| **Format extras** | `csv` (pandas, chardet), `yaml`, `email` (extract-msg), `epub` (ebooklib), `rtf` (striprtf) | CSV/TSV, YAML, MSG, EPUB, RTF |
| **Feature extras** | `keywords` (scikit-learn), `semantic` (sentence-transformers, numpy), `sentences` (pysbd), `templates` (jinja2) | TF-IDF keywords, semantic chunking, PDF sentence splits, CLI templates |
| **System** | Tesseract or RapidOCR | OCR of scanned PDF pages |

The three PDF packages are released together and pinned to the same version; `pymupdf-layout` brings `onnxruntime`. They are AGPL-3.0 or commercially licensed by Artifex.

### Runtime Detection

```python
# list_supported_formats shows availability
{
    "extension": ".msg",
    "description": "Outlook email messages",
    "available": false,
    "reason": "Optional dependency missing for .msg. Install with: pip install 'chomper[email]'"
}
```

---

## Response Handling

### Standard Response Structure

```python
# All handlers return:
list[TextContent | ImageContent]

# Typical parse_document response:
[
    TextContent(text="<document content>"),
    TextContent(text="<metadata JSON>"),
    TextContent(text="Image 1 info: {...}"),              # if requested
    ImageContent(data="<base64>", mimeType="image/png"),  # if requested
]
```

### Error Response

Failures are MCP tool errors, built by `tool_error()` in `server.py`:

```python
CallToolResult(
    content=[TextContent(text="get_document_chunk failed (ValueError): offset must be >= 0, got -3.")],
    isError=True,
)
```

### Continuation Hints

```json
{
    "total_characters": 50000,
    "continuation_hint": "Document has 45000 more characters. Use get_document_chunk(file_path, offset=5000) for more."
}
```

---

## Summary

Chomper's architecture prioritizes:

1. **Modularity**: Clear component boundaries
2. **Extensibility**: Easy to add formats/strategies
3. **Resilience**: Graceful handling of missing dependencies
4. **Efficiency**: Lazy imports and images, shared cache, TOON format, pagination
5. **MCP Native**: Built for AI system integration

For implementation details, see [COMPONENTS.md](COMPONENTS.md).
