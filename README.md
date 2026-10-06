# Chomper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

**Chomp through any document.** An MCP server, Python library and CLI that parses 36 file extensions into Markdown for AI systems like Claude.

## Features

- **15+ Format Categories**: PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, Text, Code (Python, JS/TS, Java, C/C++, Go, Rust), JSON, YAML, XML, Email (EML/MSG), EPUB, RTF
- **Layout-model PDF parsing**: one `pymupdf-layout` pass for text, headings, lists, tables and figures. Table adjacency F1 0.89 (was 0.42) on 378 ground-truth tables, at about 0.13 s/page ([details](#pdf-parsing))
- **Figures in the text**: every image and vector chart gets an `![caption](image:<id>)` marker where it sits; fetch one by id with `get_document_images`
- **Lazy images**: decoded, downscaled (1568 px long edge, 3.5 MB cap) and encoded only when a caller asks for them
- **Scanned pages**: reported per page and OCR'd when Tesseract or RapidOCR is installed
- **Faithful Markdown**: nested and numbered lists keep their levels and labels (PDF, DOCX, PPTX, HTML); tables become GFM; check marks in PDF table cells are recovered
- **Smart Token Management**: Summary mode by default (5000 chars), pagination for large documents
- **TOON Output Format**: Token-Optimized Object Notation reduces token usage by ~40%
- **Chunking for RAG**: `auto`, `recursive`, `fixed` and `semantic` strategies; chunks keep line breaks, lists, tables and code blocks; TF-IDF keywords on request
- **MCP Prompts**: Built-in document analysis prompts (summarize, extract entities, Q&A, etc.)
- **Shared cache**: paging, metadata and image calls on an unchanged file reuse one extraction
- **Batch Processing**: Parse multiple documents concurrently in a single request

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/IcHiGo-KuRoSaKiI/Chomper.git
cd Chomper

# Create virtual environment and install
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -e ".[all]"   # every format and feature; `pip install -e .` for the core
```

See [Dependencies](#dependencies) for what the core install covers and what each extra adds.

### Running the Server

```bash
# Direct execution
python server.py

# Or via the installed command
chomper
```

### Configure in Claude Code

```bash
claude mcp add -s user chomper -- /path/to/Chomper/venv/bin/python /path/to/Chomper/server.py
```

### Configure in Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "chomper": {
      "command": "/path/to/Chomper/venv/bin/python",
      "args": ["/path/to/Chomper/server.py"]
    }
  }
}
```

## Python Library

Chomper can be used as a standalone Python library for document parsing:

```python
import chomper

# Parse a document
result = chomper.parse("/path/to/document.pdf")
print(result.text)        # Markdown, with ![caption](image:p1-1) figure markers
print(result.metadata)
print(f"Words: {result.word_count}, Format: {result.format}")

# Include images (decoded and downscaled only now)
result = chomper.parse("/path/to/document.pdf", include_images=True)
for img in result.images:
    print(img["id"], img["page"], img["width"], img["height"], img["mime_type"])

# Parse from bytes or base64 (cloud storage, APIs, databases); capped at 100 MB
import base64
with open("doc.pdf", "rb") as f:
    content = base64.b64encode(f.read()).decode()

result = chomper.parse_bytes(content, "doc.pdf")

# Quick metadata extraction
meta = chomper.extract_metadata("/path/to/report.pdf")
print(f"Author: {meta.author}, Pages: {meta.page_count}, Images: {meta.image_count}")

# Chunk for RAG/embeddings
chunks = chomper.chunk("/path/to/doc.pdf", chunk_size=500, keywords=True)
for chunk in chunks:
    print(f"Chunk {chunk.chunk_id}: {chunk.word_count} words, section {chunk.section_name!r}")
    print(f"Keywords: {chunk.keywords}")

# Check format support
if chomper.is_supported("report.pdf"):
    result = chomper.parse("report.pdf")

# List all formats
formats = chomper.list_formats()
for ext, info in formats.items():
    if info["available"]:
        print(f"{ext}: {info['description']}")
    else:
        print(f"{ext}: {info['reason']}")  # includes the pip install command
```

### API Reference

| Function | Description |
|----------|-------------|
| `chomper.parse(file_path, *, include_images=False, max_chars=None)` | Parse document, returns `ParseResult` |
| `chomper.parse_bytes(content, filename, *, include_images=False, max_chars=None)` | Parse from bytes or base64 (100 MB cap, never cached) |
| `chomper.chunk(file_path, *, strategy="auto", chunk_size=1000, overlap=100, embedding_model="fast", keywords=False)` | Split into chunks for RAG |
| `chomper.extract_metadata(file_path)` | Quick metadata extraction |
| `chomper.list_formats()` | Formats with availability and install hints |
| `chomper.is_supported(file_path)` | Format known and its dependencies installed |
| `chomper.get_format(file_path)` | Format name (`"pdf"`) or `None` |
| `chomper.clear_cache()` | Drop cached extractions |

Errors (missing file, unsupported format, bad options) raise `chomper.ChomperError`.

### Result Objects

```python
# ParseResult
result.text           # Extracted text (Markdown)
result.metadata       # Document metadata dict
result.format         # File format (pdf, docx, etc.)
result.word_count     # Total word count
result.char_count     # Total character count
result.images         # With include_images=True: dicts with id, page, width, height,
                      # content (base64), mime_type, position, alt
result.summary(500)   # First 500 characters

# ChunkResult (from chomper.chunk())
chunk.text            # Chunk text, an exact slice of the document text
chunk.chunk_id        # Chunk index (0-based)
chunk.start_char      # Offsets into the document text
chunk.end_char
chunk.word_count      # Words in chunk
chunk.keywords        # TF-IDF keywords (empty unless keywords=True)
chunk.section_name    # Heading, slide title or sheet the chunk belongs to
chunk.metadata        # Chunker-specific details

# MetadataResult (from chomper.extract_metadata())
meta.filename         # Base filename
meta.format           # File format
meta.file_size        # Size in bytes
meta.author           # Author (if available)
meta.title            # Title (if available)
meta.page_count       # Pages (if applicable)
meta.word_count       # Also text_length, image_count, created, modified, ...
meta.to_dict()        # Fields that are set
```

### PDF options

`chomper.parse` uses the default PDF settings. To change them, use the extractor directly (`src/extractors/pdf_extractor.py`):

```python
from src.extractors import PDFExtractor

doc = PDFExtractor(
    backend="auto",               # "layout" (pymupdf-layout model; default when installed) or "legacy"
    ocr="auto",                   # "auto" OCRs pages without a text layer if an engine is installed; "off"; "force"
    table_format="markdown",      # or "html" to keep merged cells (layout backend only)
    extract_vector_figures=True,  # mark vector charts/diagrams as figures, rendered on request
).extract("/path/to/report.pdf")
print(doc.text, doc.metadata)
```

### Cache

Extractions are cached in memory, keyed by path, modification time, size, extractor and options, so an edited file is re-read. The library, CLI and MCP server share one cache (`src/server/cache.py`).

| Variable | Effect |
|----------|--------|
| `CHOMPER_CACHE_SIZE` | Entries kept (default 16); `0` disables caching |
| `CHOMPER_DISABLE_CACHE` | `1`, `true` or `yes` disables caching |

## Command-Line Interface

Parse documents directly from the command line:

```bash
# Parse and print text
chomper-parse document.pdf

# Output as JSON
chomper-parse report.docx --json

# Output in different formats (csv, markdown, xml)
chomper-parse report.pdf --format markdown
chomper-parse data.xlsx --format csv

# Show metadata only
chomper-parse data.xlsx --metadata

# Split into chunks
chomper-parse book.pdf --chunk --strategy recursive --chunk-size 500 --keywords

# Save to file
chomper-parse document.pdf -o output.txt

# List supported formats
chomper-parse --formats

# Quiet mode (no progress messages)
chomper-parse document.pdf -q
```

### Output Formats

```bash
# Plain text (default)
chomper-parse document.pdf

# JSON output
chomper-parse document.pdf --format json
chomper-parse document.pdf --json  # shortcut

# CSV output
chomper-parse document.pdf --format csv

# Markdown output
chomper-parse document.pdf --format markdown

# XML output
chomper-parse document.pdf --format xml

# Custom Jinja2 template (needs the `templates` extra)
chomper-parse document.pdf --format template --template my_template.j2
```

### Watch Mode

Monitor a directory for new/changed files and auto-parse them:

```bash
# Watch a directory
chomper-parse --watch ./documents

# Watch with JSON output saved to files
chomper-parse --watch ./inbox --format json --output-dir ./parsed

# Watch only PDFs, check every 5 seconds
chomper-parse --watch ./docs --pattern "*.pdf" --interval 5

# Watch recursively (including subdirectories)
chomper-parse --watch ./project --recursive

# Watch with metadata only
chomper-parse --watch ./docs --metadata --format json
```

### Interactive Mode

Start an interactive shell for parsing multiple documents:

```bash
$ chomper-parse -i
Chomper Interactive Mode
Type 'help' for commands, 'exit' to quit.

chomper> parse ~/Documents/report.pdf
[Document content displayed...]

chomper> set format json
Output format set to: json

chomper> metadata ~/Documents/report.pdf
{
  "filename": "report.pdf",
  "format": "pdf",
  "page_count": 5
}

chomper> history
Files parsed this session:
  1. /Users/me/Documents/report.pdf

chomper> help
[Shows all available commands]

chomper> exit
```

**Interactive Commands:**
| Command | Description |
|---------|-------------|
| `parse <file>` | Parse a document |
| `metadata <file>` | Show metadata only |
| `chunk <file>` | Split into chunks |
| `formats` | List supported formats |
| `set format <name>` | Set output format |
| `set json on/off` | Toggle JSON mode |
| `set max-chars N` | Limit output (0 = unlimited) |
| `set chunk-size N` | Words per chunk |
| `set strategy <name>` | `auto`, `recursive`, `fixed` or `semantic` |
| `set template <path>` | Jinja2 template for `template` output |
| `history` | Show parsed files |
| `status` | Show current settings |
| `clear` | Clear the screen |
| `help` | Show all commands |
| `exit` | Exit interactive mode |

### CLI Options

| Option | Description |
|--------|-------------|
| `-f, --format` | Output format: `text`, `json`, `csv`, `markdown`, `xml`, `template` |
| `--template` | Jinja2 template file (with `--format template`) |
| `--json` | Shortcut for `--format json` |
| `--metadata` | Show metadata only |
| `--chunk` | Split into chunks |
| `--strategy` | Chunking: `auto`, `recursive`, `fixed`, `semantic` (default: `auto`) |
| `--chunk-size` | Maximum words per chunk (default: 1000) |
| `--overlap` | Words to overlap between chunks (default: 100) |
| `--keywords` | Attach TF-IDF keywords to each chunk |
| `--max-chars` | Limit output characters |
| `-o, --output` | Save to file |
| `-i, --interactive` | Start interactive mode |
| `-w, --watch` | Watch directory for changes |
| `--interval` | Watch interval in seconds (default: 2) |
| `--output-dir` | Save watch output to directory |
| `--pattern` | File pattern for watch mode |
| `--recursive` | Watch subdirectories |
| `--formats` | List supported formats |
| `-q, --quiet` | Suppress progress messages |
| `-v, --version` | Show version |

## MCP Tools

The following tools are available via the MCP server. Handlers run extraction in worker threads, so a long parse does not block other requests.

### 1. `parse_document`

Parse a document and extract text, metadata, and images. **Returns summary by default** (first 5000 chars) to stay within token limits.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `full_text` | boolean | `false` | Return complete text (may exceed token limits) |
| `include_images` | boolean | `false` | Include up to 5 images as ImageContent |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` (token-optimized) |

**Response:**
- `TextContent[0]`: Plain extracted text (no JSON wrapping), with `![caption](image:<id>)` figure markers
- `TextContent[1]`: Metadata as JSON (includes continuation hint if truncated, and an images hint)
- `ImageContent[]`: Images if `include_images=true`, each preceded by a TextContent with its position

**Example:**
```
parse_document(file_path: "/path/to/doc.pdf")
→ Returns first 5000 chars + metadata with hint to fetch more

parse_document(file_path: "/path/to/doc.pdf", output_format: "toon")
→ Returns in TOON format (~40% fewer tokens)
```

### 2. `parse_document_bytes`

Parse a document from **base64-encoded content**. Perfect for documents from cloud storage (S3, Azure Blob), API responses, database BLOBs, or in-memory documents. The decoded content is capped at 100 MB and never cached.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `content_base64` | string | required | Base64-encoded file content |
| `filename` | string | required | Filename with extension (e.g., `"report.pdf"`) for format detection |
| `full_text` | boolean | `false` | Return complete text |
| `include_images` | boolean | `false` | Include images as ImageContent |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` |

**Example:**
```python
import base64

# Read file and encode to base64
with open("document.pdf", "rb") as f:
    content = base64.b64encode(f.read()).decode()

# Send via MCP
parse_document_bytes(
    content_base64=content,
    filename="document.pdf"
)
→ Returns extracted text + metadata (same as parse_document)
```

**Use Cases:**
- Documents fetched from cloud storage (S3, Azure Blob, GCS)
- Files received from API responses
- Documents stored as BLOBs in databases
- In-memory document processing without disk I/O

### 3. `get_document_chunk`

Get a specific portion of document text. **Use for paginated retrieval of large documents.** The document is extracted once and served from the cache for every page.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `offset` | integer | `0` | Character offset to start from (must be inside the document) |
| `limit` | integer | `5000` | Maximum characters to return (at least 1) |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` |

**Example workflow:**
```
1. parse_document(file_path: "doc.pdf")
   → Returns chars 0-5000, hint: "use get_document_chunk(offset=5000)"

2. get_document_chunk(file_path: "doc.pdf", offset: 5000)
   → Returns chars 5000-10000

3. get_document_chunk(file_path: "doc.pdf", offset: 10000)
   → Returns chars 10000-15000, etc.
```

### 4. `get_document_images`

Retrieve images from a document on-demand. Returns a JSON summary, then each image as a TextContent line (id, page, dimensions, position, caption) followed by its ImageContent.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `page` | integer | all | Specific page or slide number (1-indexed) |
| `max_images` | integer | `5` | Maximum images to return |
| `image_id` | string | - | Return only this image: the id from a marker like `![Figure 2](image:p3-1)` |
| `max_dimension` | integer | `1568` | Downscale so the long edge is at most this many pixels; `0` returns full resolution |

**Example:**
```
get_document_images(file_path: "doc.pdf", page: 1, max_images: 3)
→ Returns first 3 images from page 1 as ImageContent

get_document_images(file_path: "doc.pdf", image_id: "p3-1")
→ Returns the figure marked ![...](image:p3-1) in the text
```

### 5. `parse_document_chunked`

Split a document into chunks with configurable size and overlap. Ideal for RAG systems. Uses the same chunkers and defaults as `chomper.chunk()` and the CLI.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `chunk_size` | integer | `1000` | Maximum words per chunk |
| `overlap` | integer | `100` | Words to overlap between chunks |
| `chunking_strategy` | string | `"auto"` | Strategy: `"auto"`, `"recursive"`, `"fixed"`, `"semantic"` |
| `embedding_model` | string | `"fast"` | For semantic: `"fast"` (~80MB) or `"balanced"` (~420MB) |
| `include_keywords` | boolean | `false` | Attach TF-IDF keywords (fitted across the document's chunks) |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` |

**Chunking Strategies:**
- `auto`: Format-aware: PDF structure (headings, tables kept whole), DOCX/Markdown headings, code by function, spreadsheet sheets and tables
- `recursive`: Headings, then blank lines, then lines, then sentences; never inside a code fence or table row
- `fixed`: Fixed word windows that only break between lines
- `semantic`: Embedding-based topic boundaries using sentence-transformers (`chunk_size` is the maximum)

Chunk text is an exact slice of the document text, so line breaks, lists, tables and code blocks survive.

**Response (JSON):**
```json
{
  "success": true,
  "file_path": "/path/to/doc.md",
  "chunk_size": 1000,
  "overlap": 100,
  "chunking_strategy": "auto",
  "total_chunks": 25,
  "chunks": [
    {
      "chunk_id": 0,
      "text": "## Introduction\n\nChunk content...",
      "start_char": 0,
      "end_char": 1840,
      "word_count": 250,
      "metadata": {
        "section_name": "Introduction",
        "heading_path": "Report > Introduction",
        "chunk_strategy": "markdown"
      },
      "keywords": ["key", "terms"],
      "section_name": "Introduction",
      "section_type": "text"
    }
  ],
  "metadata": { "filename": "doc.md", "...": "..." },
  "statistics": {
    "total_words": 6000,
    "average_chunk_words": 240,
    "total_characters": 41000
  }
}
```

With `chunking_strategy: "semantic"` the response also carries `embedding_model`. `keywords` is empty unless `include_keywords` is true.

### 6. `extract_metadata`

Metadata without returning the text. Reuses a cached extraction when the file was already parsed.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` |

**Response (JSON):**
```json
{
  "success": true,
  "file_path": "/path/to/report.pdf",
  "metadata": {
    "author": "John Doe",
    "title": "Document Title",
    "page_count": 10,
    "extraction_method": "pymupdf-layout"
  },
  "document_info": {
    "text_length": 35000,
    "has_structure": true,
    "page_count": 10,
    "image_count": 5
  }
}
```

### 7. `list_supported_formats`

List all supported document formats with availability status and, for unavailable ones, the install command.

### 8. `batch_parse`

Parse multiple documents in a single request. Up to 500 files, parsed 4 at a time (fewer on machines with fewer CPUs); results keep the input order and carry a 500-character text preview.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_paths` | string[] | required | Array of file paths |
| `options.include_images` | boolean | `false` | Report each file's `image_count` |
| `options.continue_on_error` | boolean | `true` | Continue if a file fails |

## Figures and Images

Extractors write a marker into the text wherever an image sits:

```
![Figure 3: Revenue by region](image:p4-2)
```

The alt text is the figure's caption (or the image's alt text), and the id is what `get_document_images(image_id=...)` takes.

| Source | Id form | Notes |
|--------|---------|-------|
| PDF | `p<page>-<n>` | Raster images and vector-drawn charts and diagrams; captions linked from "Figure N" text, title bars inside the figure frame, or side-by-side panels. Vector figures are rendered only when requested. Logos repeated on most pages get no marker. |
| PPTX | `s<slide>-<n>` | Pictures with their alt text |
| DOCX, HTML, EPUB, email | `img-<n>` | Embedded images, HTML `data:` images, `cid:` inline email images |

Images are lazy (`src/extractors/image_utils.py`). Extractors record size, position, page and id; the bytes are loaded, converted to PNG/JPEG/GIF/WebP, downscaled to 1568 px on the long edge and capped at 3.5 MB only for the images a caller requests. Identical images are returned once, with `pages` listing where they appear.

Scanned PDF pages are marked in the text so the reader can fetch the page image. If Tesseract or RapidOCR is installed, they are OCR'd (`ocr="auto"`) and listed in `metadata["ocr_pages"]`; pages left without text are listed in `metadata["pages_without_text_layer"]`, with a `warning`.

## PDF Parsing

PDFs go through the `pymupdf-layout` model in one pass (`src/extractors/pdf_layout.py`): it labels each region of a page (text, section header, list item, table, picture, caption, page header) and Chomper turns the result into Markdown.

Measured on 378 ground-truth tables (ICDAR-2013 corrected + SciTSR) against the previous `pymupdf4llm` + `find_tables` path:

| | Before | Now |
|---|---|---|
| Table adjacency F1 | 0.421 | 0.894 |
| Table detection F1 | 0.776 | 0.962 |

It runs at about 0.13 s/page, faster than the old path (IRS Pub 15: 12 s, was 43 s).

- Wrapped lines are joined into paragraphs and headings are found (the Transformer paper: 26 headings, was 1).
- Tables are rendered from the model's cell grid; `|` in cells is escaped, and a table continued on the next page gets its header row back.
- Check marks and crosses in table cells, which extraction loses (symbol-font codes, vector strokes, tiny icons), are restored into empty cells (`src/pdf_structure/cell_marks.py`).
- Lists keep their nesting and labels (`•`, `(a)`, `iv)`, `12)`), also across column breaks (`src/pdf_structure/lists.py`).
- Page headers and footers are dropped only when they repeat across pages or are page numbers.

`backend="legacy"` keeps the old path. The `auto` chunking strategy for PDFs uses `StructuralPDFChunker`, which reads the file directly; see [docs/PDF_STRUCTURE.md](docs/PDF_STRUCTURE.md).

## MCP Prompts

The server exposes 5 document analysis prompts that can be used with Claude:

| Prompt | Description | Arguments |
|--------|-------------|-----------|
| `summarize-document` | Generate comprehensive document summary | `file_path`, `length` (short/medium/long) |
| `extract-key-points` | Extract main takeaways and key points | `file_path`, `max_points` |
| `explain-document` | Explain document for different audiences | `file_path`, `audience` (child/general/expert) |
| `extract-entities` | Extract named entities (people, orgs, locations) | `file_path`, `entity_types` |
| `document-qa` | Set up Q&A context for document | `file_path` |

**Usage in Claude:**
```
Use the summarize-document prompt with file_path="/path/to/doc.pdf"
```

## TOON Format (Token-Optimized Output)

TOON format reduces token usage by ~40% compared to JSON, ideal for LLM contexts. `parse_document_chunked` with `output_format: "toon"`:

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

The `k:` lines appear when `include_keywords` is true.

**Enable with:** `output_format: "toon"` on `parse_document`, `parse_document_bytes`, `get_document_chunk`, `parse_document_chunked` and `extract_metadata`.

## Supported Formats

| Category | Extensions | Description |
|----------|-----------|-------------|
| **Documents** | `.pdf`, `.docx`, `.pptx` | Headings, nested lists, tables, figures; PPTX slides in reading order with notes, charts and SmartArt |
| **Spreadsheets** | `.xlsx`, `.xlsm`, `.xltx`, `.xltm`, `.csv`, `.tsv` | GFM tables bounded to real data, header detection, number formats kept |
| **Web** | `.html`, `.htm`, `.md`, `.markdown` | HTML converted to Markdown (nested lists, tables with spans, code, links) |
| **Text** | `.txt`, `.text`, `.log` | Plain text with encoding detection |
| **Code** | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.cpp`, `.c`, `.go`, `.rs` | Language-aware parsing |
| **Data** | `.json`, `.yaml`, `.yml`, `.xml` | JSON (BOM accepted), YAML as written, XML as fenced data or prose text; external entities are not resolved |
| **Email** | `.eml`, `.msg` | Headers, full body (HTML bodies converted to Markdown), inline images, attachment list |
| **E-books** | `.epub` | Chapters in spine (reading) order, with images |
| **Rich Text** | `.rtf` | Bullets, numbering and tables kept as Markdown |

**Total: 36 file extensions**, counting `.doc` and `.ppt`: they are recognised, but legacy binary Word and PowerPoint files are rejected with a message asking for `.docx`/`.pptx`.

## Recommended Usage Pattern

For best results with AI systems that have token limits:

```
# 1. Start with summary (default behavior)
parse_document(file_path: "large_doc.pdf")

# 2. If you need more content, paginate
get_document_chunk(file_path: "large_doc.pdf", offset: 5000)
get_document_chunk(file_path: "large_doc.pdf", offset: 10000)

# 3. Fetch a figure the text points to, or images separately when needed
get_document_images(file_path: "large_doc.pdf", image_id: "p4-2")
get_document_images(file_path: "large_doc.pdf", max_images: 3)

# 4. For RAG pipelines, chunk the document
parse_document_chunked(file_path: "doc.pdf", include_keywords: true)
```

**Avoid:**
```
# DON'T use full_text=true for large documents - will exceed token limits!
parse_document(file_path: "large_doc.pdf", full_text: true)  # Bad
```

## Architecture

The server wraps a 4-layer document processing pipeline:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Extractors │ -> │  Chunkers   │ -> │  Enrichers  │ -> │ Formatters  │
│ (Layer 1)   │    │ (Layer 2)   │    │ (Layer 3)   │    │ (Layer 4)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
     │                   │                  │                   │
     v                   v                  v                   v
 Markdown +         Structure-aware    Keywords +         JSON/TOON
 Structure          Chunks             Metadata            Output
```

**Extractors:** Format-specific text and metadata extraction, loaded on first use
**Chunkers:** Auto, recursive, fixed and semantic (embeddings) strategies
**Enrichers:** Keywords, sections, titles, complexity scores
**Formatters:** JSON (default) or TOON (token-optimized)

The library, CLI and MCP server share one loader (`src/server/documents.py`): one extractor registry, one cache and one chunker factory.

## Dependencies

**Core (`pip install -e .`):**
- `mcp` - Model Context Protocol
- PDF: `pymupdf`, `pymupdf4llm`, `pymupdf-layout`, all pinned to `==1.28.2` (they release together; `pymupdf-layout` brings `onnxruntime`)
- Office: `python-docx`, `python-pptx`, `openpyxl`
- Web and XML: `beautifulsoup4`, `lxml`
- Images: `pillow`
- Code, Text, Markdown, JSON and EML need nothing extra

**Extras (formats report themselves unavailable, with the install command, until installed):**

| Extra | Packages | Enables |
|-------|----------|---------|
| `csv` | pandas, chardet | CSV/TSV |
| `yaml` | pyyaml | YAML |
| `email` | extract-msg | Outlook `.msg` |
| `epub` | ebooklib | EPUB |
| `rtf` | striprtf | RTF |
| `keywords` | scikit-learn | TF-IDF keywords (falls back to RAKE) |
| `semantic` | sentence-transformers, numpy | Semantic chunking |
| `sentences` | pysbd | Abbreviation-safe PDF sentence splits (falls back to a regex) |
| `templates` | jinja2 | `chomper-parse -f template` |
| `all` | all of the above | |

Install everything:
```bash
pip install -e ".[all]"   # or: pip install -r requirements.txt
```

OCR of scanned PDF pages additionally needs an OCR engine: Tesseract (system install) or RapidOCR.

PyMuPDF, pymupdf4llm and pymupdf-layout are licensed AGPL-3.0 or commercially by Artifex, as PyMuPDF was before. Chomper's own code is MIT.

## Error Handling

Tool failures come back as MCP errors (`isError: true`) with a message that names the problem and what to do instead:

```
get_document_chunk failed (ValueError): offset must be >= 0, got -3.
parse_document failed (ValueError): File not found: /path/to/missing.pdf. Check the path and pass an absolute path.
```

Arguments are checked against the tool schemas (required, type, enum, minimum, limits) before the handler runs. In `batch_parse`, a failing file is reported in its result entry (`"success": false`, `error`, `error_type`) unless `continue_on_error` is false.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
python src/tests/test_lightweight.py

# Format code
black .

# Lint and type check
ruff check .
mypy
```

## Comparison with Other Tools

| Feature | Chomper | LlamaParse | Docling | Unstructured |
|---------|-------------|------------|---------|--------------|
| MCP Native | Yes | No | No | No |
| Format Count | 36 | ~15 | ~10 | ~20 |
| Token Optimization | TOON (~40% savings) | No | No | No |
| Semantic Chunking | Built-in | Separate | Separate | Separate |
| MCP Prompts | 5 built-in | No | No | No |
| Complex Tables | Good (pymupdf-layout) | Excellent | Excellent (AI) | Average |
| Cloud Required | No (local) | Yes | No | Optional |
| Cost | Free | Paid | Free | Freemium |

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Start for Contributors

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/Chomper.git
cd Chomper

# Setup dev environment
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black .
ruff check .
```

## License

MIT License - see [LICENSE](LICENSE) for details. The PDF dependencies (PyMuPDF family) are AGPL-3.0 or commercial; see [Dependencies](#dependencies).

---

Built with love by [@IcHiGo-KuRoSaKiI](https://github.com/IcHiGo-KuRoSaKiI)
