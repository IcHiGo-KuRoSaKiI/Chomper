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

Chomper follows a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MCP Client (Claude)                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SERVER LAYER (server.py)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────┐  │
│  │ list_tools  │ │ call_tool   │ │list_prompts │ │  get_prompt  │  │
│  └─────────────┘ └─────────────┘ └─────────────┘ └──────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    HANDLER LAYER (src/handlers/)                    │
│  ┌───────────┐ ┌────────────┐ ┌───────────┐ ┌──────────┐ ┌───────┐ │
│  │  parse.py │ │  chunk.py  │ │ images.py │ │metadata.py│ │batch.py│ │
│  └───────────┘ └────────────┘ └───────────┘ └──────────┘ └───────┘ │
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
│    RawDocument         List[Chunk]    List[EnrichedChunk]   JSON/TOON
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Server Layer

### Entry Point: `server.py`

The MCP server entry point (~200 lines) delegates all work to modular handlers:

```python
# server.py structure
from mcp.server import Server
from src.server.tools import get_tools
from src.handlers import handle_parse_document, handle_parse_document_bytes, ...

server = Server("chomper")

@server.list_tools()
async def list_tools() -> List[Tool]:
    return get_tools()  # Defined in src/server/tools.py

@server.call_tool()
async def call_tool(name: str, arguments: Dict) -> Sequence[TextContent | ImageContent]:
    if name == "parse_document":
        return await handle_parse_document(arguments)
    elif name == "parse_document_bytes":
        return await handle_parse_document_bytes(arguments)
    # ... dispatch to other handlers
```

### MCP Decorators

| Decorator | Purpose | Delegates To |
|-----------|---------|--------------|
| `@server.list_tools()` | Return available tools | `get_tools()` from tools.py |
| `@server.call_tool()` | Execute tool requests | Handlers in `src/handlers/` |
| `@server.list_prompts()` | Return analysis prompts | `PROMPTS` from prompts.py |
| `@server.get_prompt()` | Format prompt with content | `format_prompt()` |

---

## Modular Structure

### Directory Layout

```
src/
├── server/                    # Server infrastructure
│   ├── __init__.py           # Exports all server components
│   ├── config.py             # Constants, EXTRACTORS, CHUNKERS mappings
│   ├── tools.py              # MCP Tool definitions (get_tools())
│   └── helpers.py            # Shared utilities (11 functions)
│
├── handlers/                  # Tool implementations
│   ├── __init__.py           # Exports all handlers
│   ├── parse.py              # parse_document, parse_document_bytes
│   ├── chunk.py              # get_document_chunk, parse_document_chunked
│   ├── images.py             # get_document_images
│   ├── metadata.py           # extract_metadata, list_supported_formats
│   └── batch.py              # batch_parse
│
├── extractors/                # Format-specific extraction (18 extractors)
├── chunking/                  # Chunking strategies (9 chunkers)
├── enrichment/                # Metadata enrichment (4 enrichers)
├── formatters/                # Output formatting (4 formatters)
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
OUTPUT_FORMAT_JSON = "json"     # Default output
OUTPUT_FORMAT_TOON = "toon"     # Token-optimized

# Format descriptions (36+ extensions)
FORMAT_DESCRIPTIONS = {
    ".pdf": "PDF documents with text and image extraction",
    ".docx": "Microsoft Word documents (OOXML format)",
    # ... 34 more
}

# Dynamic mappings (populated at import time)
EXTRACTORS: Dict[str, type] = {}
CHUNKERS: Dict[str, type] = {}

def initialize_extractors():
    """Conditionally load extractors based on dependencies"""
    # Always available
    EXTRACTORS[".py"] = CodeExtractor
    EXTRACTORS[".json"] = JSONExtractor

    # Optional (check import success)
    if PDFExtractor is not None:
        EXTRACTORS[".pdf"] = PDFExtractor
```

### src/server/helpers.py

Shared utility functions:

| Function | Purpose |
|----------|---------|
| `validate_file_path()` | Expand, resolve, validate file paths |
| `parse_from_base64()` | Decode base64 to temp file |
| `get_extractor_for_file()` | Return instantiated extractor |
| `get_chunker_for_file()` | Return instantiated chunker |
| `extract_images_from_structure()` | Extract images with filtering |
| `remove_image_placeholders()` | Clean `[Image: WxH]` patterns |
| `detect_mime_type()` | Infer MIME from base64 prefix |
| `format_error_response()` | Wrap errors in TextContent |
| `chunk_to_dict()` | Serialize Chunk to dict |

### src/server/tools.py

MCP tool definitions:

```python
def get_tools() -> List[Tool]:
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
│ PDF → Text  │ -> │ Text →      │ -> │ Chunks →    │ -> │ Enriched →  │
│ DOCX → Text │    │ Chunks      │    │ Enriched    │    │ JSON/TOON   │
│ Code → Text │    │             │    │ Chunks      │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼
 RawDocument        List[Chunk]     List[EnrichedChunk]    Output String
```

### Stage 1: Extraction

**Input**: File path
**Output**: `RawDocument(text, metadata, structure)`

```python
class RawDocument:
    text: str                    # Full extracted text
    metadata: Dict[str, Any]     # author, title, created, etc.
    structure: Optional[Dict]    # pages, sections, images
```

**Extractors** (18 implementations):
- **Always Available**: Code, Text, Markdown, JSON, EML (stdlib-based)
- **With Dependencies**: PDF, DOCX, PPTX, Excel, CSV, HTML, YAML, XML, MSG, EPUB, RTF

### Stage 2: Chunking

**Input**: `RawDocument`
**Output**: `List[Chunk]`

```python
class Chunk:
    chunk_id: int
    text: str
    start_char: int
    end_char: int
    metadata: Dict[str, Any]
```

**Strategies**:
| Strategy | Description | Use Case |
|----------|-------------|----------|
| `auto` | Format-aware (PDF by page, Code by function) | Default |
| `semantic` | Embedding-based breakpoints | RAG systems |
| `fixed` | Fixed word count | Simple splitting |
| `recursive` | Paragraph/sentence boundaries | Structured text |

### Stage 3: Enrichment

**Input**: `List[Chunk]`
**Output**: `List[EnrichedChunk]`

```python
class EnrichedChunk(Chunk):
    keywords: List[str]              # Extracted key terms
    section_name: Optional[str]      # "Introduction", "Methods"
    section_type: str                # "text", "code", "table"
    computed_metadata: Dict[str, Any]
```

**Enrichers**:
- `KeywordExtractor` - Extract important terms
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
│ server.py: @server.call_tool()                  │
│   → dispatch to handle_parse_document()         │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ handlers/parse.py: handle_parse_document()      │
│   1. validate_file_path("/docs/report.pdf")     │
│   2. get_extractor_for_file() → PDFExtractor    │
│   3. extractor.extract() → RawDocument          │
│   4. remove_image_placeholders()                │
│   5. Truncate to 5000 chars (if full_text=false)│
│   6. Format metadata (JSON or TOON)             │
│   7. Extract images → List[ImageContent]        │
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
│   2. Reuse parse_document logic                 │
│   3. Replace temp paths with original filename  │
│   4. cleanup() → delete temp file               │
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
│ handlers/chunk.py: handle_parse_document_chunked│
│   1. validate_file_path()                       │
│   2. get_extractor_for_file() → PDFExtractor    │
│   3. extractor.extract() → RawDocument          │
│   4. SemanticChunker(model="fast")              │
│      - Load all-MiniLM-L6-v2 (lazy)             │
│      - Compute sentence embeddings              │
│      - Find semantic breakpoints                │
│   5. chunker.chunk() → List[Chunk]              │
│   6. Format chunks with metadata                │
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

---

## Component Details

### Extractors

**Base Class**:
```python
class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, file_path: str) -> RawDocument:
        """Extract text, metadata, and structure from file"""

    def validate_file(self, file_path: str) -> Path:
        """Validate file exists and has correct extension"""

    def _get_basic_metadata(self, file_path: Path) -> Dict:
        """Return filename, size, extension, etc."""
```

**Implementation Matrix**:

| Extractor | Extensions | Dependencies | Always Available |
|-----------|-----------|--------------|------------------|
| `CodeExtractor` | .py, .js, .ts, .java, etc. | None | Yes |
| `TextExtractor` | .txt, .text, .log | None | Yes |
| `MarkdownExtractor` | .md, .markdown | None | Yes |
| `JSONExtractor` | .json | None | Yes |
| `EMLExtractor` | .eml | None | Yes |
| `PDFExtractor` | .pdf | pymupdf, pymupdf4llm | No |
| `DOCXExtractor` | .docx, .doc | python-docx | No |
| `PPTXExtractor` | .pptx, .ppt | python-pptx | No |
| `ExcelExtractor` | .xlsx, .xlsm, etc. | openpyxl | No |
| `CSVExtractor` | .csv, .tsv | pandas, chardet | No |
| `HTMLExtractor` | .html, .htm | beautifulsoup4, lxml | No |
| `YAMLExtractor` | .yaml, .yml | pyyaml | No |
| `XMLExtractor` | .xml | lxml | No |
| `MSGExtractor` | .msg | extract-msg | No |
| `EPUBExtractor` | .epub | ebooklib | No |
| `RTFExtractor` | .rtf | striprtf | No |

### Chunkers

**SemanticChunker** (key implementation):
```python
class SemanticChunker(BaseChunker):
    MODELS = {
        "fast": "all-MiniLM-L6-v2",      # ~80MB, fastest
        "balanced": "all-mpnet-base-v2",  # ~420MB, best quality
    }

    STRATEGIES = {
        "percentile": "Break at distances > Nth percentile",
        "standard_deviation": "Break at N std devs from mean",
        "interquartile": "Break outside IQR"
    }

    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        # 1. Split into sentences
        # 2. Compute embeddings (lazy model loading)
        # 3. Calculate cosine distances between adjacent sentences
        # 4. Find breakpoints using strategy
        # 5. Group sentences into chunks
        # 6. Apply overlap
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
- Keywords: `k:word1,word2,word3`

---

## Design Patterns

### 1. Lazy Loading

Heavy dependencies loaded only when needed:

```python
# SemanticChunker - model loaded on first use
def _get_embedding_model(self):
    if self._model is None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.MODELS[self.model_name])
    return self._model
```

### 2. Graceful Degradation

Optional extractors don't break the system:

```python
# In config.py
try:
    from src.extractors import PDFExtractor
except ImportError:
    PDFExtractor = None

# In initialize_extractors()
if PDFExtractor is not None:
    EXTRACTORS[".pdf"] = PDFExtractor
```

### 3. Handler Delegation

Clean separation between server and implementation:

```python
# server.py - thin dispatcher
@server.call_tool()
async def call_tool(name, arguments):
    return await HANDLERS[name](arguments)

# handlers/parse.py - all logic here
async def handle_parse_document(arguments):
    # Validation, extraction, formatting
```

### 4. Configuration Centralization

Single source of truth:

```python
# All constants in config.py
from src.server.config import (
    DEFAULT_SUMMARY_CHARS,
    EXTRACTORS,
    FORMAT_DESCRIPTIONS
)
```

### 5. Dual Output Formats

All tools support JSON and TOON:

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
# Full installation (all formats)
pip install -e .

# Minimal (Code, Text, Markdown, JSON, EML only)
pip install -e ".[minimal]"

# Development
pip install -e ".[dev]"
```

### Dependency Tiers

| Tier | Packages | Formats Enabled |
|------|----------|-----------------|
| **Core** | mcp>=1.0.0 | MCP protocol |
| **Always** | (stdlib) | Code, Text, Markdown, JSON, EML |
| **Standard** | pymupdf, python-docx, openpyxl, beautifulsoup4 | PDF, DOCX, Excel, HTML |
| **Optional** | pandas, pyyaml, extract-msg, ebooklib, striprtf | CSV, YAML, MSG, EPUB, RTF |
| **Advanced** | sentence-transformers | Semantic chunking |

### Runtime Detection

```python
# list_supported_formats shows availability
{
    "extension": ".pdf",
    "description": "PDF documents with text and image extraction",
    "available": true,    # or false if pymupdf not installed
    "reason": null        # or "Missing dependency: pymupdf"
}
```

---

## Response Handling

### Standard Response Structure

```python
# All handlers return:
List[TextContent | ImageContent]

# Typical parse_document response:
[
    TextContent(text="<document content>"),
    TextContent(text="<metadata JSON>"),
    ImageContent(data="<base64>", mimeType="image/png"),  # if requested
]
```

### Error Response

```python
# format_error_response() wraps exceptions:
[TextContent(text=json.dumps({
    "success": False,
    "error": "File not found: /path/to/missing.pdf",
    "error_type": "ValueError"
}))]
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
4. **Efficiency**: TOON format, lazy loading, pagination
5. **MCP Native**: Built for AI system integration

For implementation details, see [COMPONENTS.md](COMPONENTS.md).
