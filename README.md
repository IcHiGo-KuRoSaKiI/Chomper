# Chomper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

**Chomp through any document.** An MCP server that parses 36+ file formats for AI systems like Claude.

## Features

- **15+ Format Categories**: PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, Text, Code (10+ languages), JSON, YAML, XML, Email (EML/MSG), EPUB, RTF
- **Smart Token Management**: Summary mode by default (5000 chars), pagination for large documents
- **TOON Output Format**: Token-Optimized Object Notation reduces token usage by ~40%
- **Semantic Chunking**: Embedding-based chunking using sentence-transformers for better RAG retrieval
- **Image Extraction**: PDF images returned as ImageContent for direct AI analysis
- **MCP Prompts**: Built-in document analysis prompts (summarize, extract entities, Q&A, etc.)
- **Rich Metadata**: Author, title, pages, word count, reading time, complexity scores
- **Batch Processing**: Parse multiple documents in a single request

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/IcHiGo-KuRoSaKiI/Chomper.git
cd chomper

# Create virtual environment and install
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -e .
```

### Running the Server

```bash
# Direct execution
python server.py

# Or via the installed command
chomper
```

### Configure in Claude Code

```bash
claude mcp add -s user chomper -- /path/to/chomper/venv/bin/python /path/to/chomper/server.py
```

### Configure in Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "chomper": {
      "command": "/path/to/chomper/venv/bin/python",
      "args": ["/path/to/chomper/server.py"]
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
print(result.text)
print(result.metadata)
print(f"Words: {result.word_count}, Format: {result.format}")

# Parse from base64 (cloud storage, APIs, databases)
import base64
with open("doc.pdf", "rb") as f:
    content = base64.b64encode(f.read()).decode()

result = chomper.parse_bytes(content, "doc.pdf")

# Quick metadata extraction
meta = chomper.extract_metadata("/path/to/report.pdf")
print(f"Author: {meta.author}, Pages: {meta.page_count}")

# Chunk for RAG/embeddings
chunks = chomper.chunk("/path/to/doc.pdf", strategy="semantic")
for chunk in chunks:
    print(f"Chunk {chunk.chunk_id}: {chunk.word_count} words")
    print(f"Keywords: {chunk.keywords}")

# Check format support
if chomper.is_supported("report.pdf"):
    result = chomper.parse("report.pdf")

# List all formats
formats = chomper.list_formats()
for ext, info in formats.items():
    if info["available"]:
        print(f"{ext}: {info['description']}")
```

### API Reference

| Function | Description |
|----------|-------------|
| `chomper.parse(file_path)` | Parse document, returns `ParseResult` |
| `chomper.parse_bytes(content, filename)` | Parse from bytes/base64 |
| `chomper.chunk(file_path, strategy)` | Split into chunks for RAG |
| `chomper.extract_metadata(file_path)` | Quick metadata extraction |
| `chomper.list_formats()` | List supported formats |
| `chomper.is_supported(file_path)` | Check if format supported |

### Result Objects

```python
# ParseResult
result.text           # Extracted text content
result.metadata       # Document metadata dict
result.format         # File format (pdf, docx, etc.)
result.word_count     # Total word count
result.char_count     # Total character count

# ChunkResult (from chomper.chunk())
chunk.text            # Chunk text
chunk.chunk_id        # Chunk index (0-based)
chunk.word_count      # Words in chunk
chunk.keywords        # Extracted keywords
chunk.section_name    # Detected section name

# MetadataResult (from chomper.extract_metadata())
meta.filename         # Base filename
meta.format           # File format
meta.file_size        # Size in bytes
meta.author           # Author (if available)
meta.title            # Title (if available)
meta.page_count       # Pages (if applicable)
```

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
chomper-parse book.pdf --chunk --strategy semantic

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

# Custom Jinja2 template
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
| `set max-chars N` | Limit output |
| `history` | Show parsed files |
| `status` | Show current settings |
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
| `--strategy` | Chunking: `auto`, `semantic`, `fixed` |
| `--chunk-size` | Words per chunk (default: 1000) |
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

## MCP Tools

The following tools are available via the MCP server:

## Available Tools

### 1. `parse_document`

Parse a document and extract text, metadata, and images. **Returns summary by default** (first 5000 chars) to stay within token limits.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `full_text` | boolean | `false` | Return complete text (may exceed token limits) |
| `include_images` | boolean | `false` | Include images as ImageContent |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` (token-optimized) |

**Response:**
- `TextContent[0]`: Plain extracted text (no JSON wrapping)
- `TextContent[1]`: Metadata as JSON (includes continuation hint if truncated)
- `ImageContent[]`: Images if `include_images=true`

**Example:**
```
parse_document(file_path: "/path/to/doc.pdf")
→ Returns first 5000 chars + metadata with hint to fetch more

parse_document(file_path: "/path/to/doc.pdf", output_format: "toon")
→ Returns in TOON format (~40% fewer tokens)
```

### 2. `parse_document_bytes`

Parse a document from **base64-encoded content**. Perfect for documents from cloud storage (S3, Azure Blob), API responses, database BLOBs, or in-memory documents.

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

### 4. `get_document_chunk`

Get a specific portion of document text. **Use for paginated retrieval of large documents.**

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `offset` | integer | `0` | Character offset to start from |
| `limit` | integer | `5000` | Maximum characters to return |
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

### 5. `get_document_images`

Retrieve images from a document on-demand. Returns images as ImageContent objects.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `page` | integer | all | Specific page number (1-indexed) |
| `max_images` | integer | `5` | Maximum images to return |

**Example:**
```
get_document_images(file_path: "doc.pdf", page: 1, max_images: 3)
→ Returns first 3 images from page 1 as ImageContent
```

### 6. `parse_document_chunked`

Parse a document into semantic chunks with configurable size and overlap. Ideal for RAG systems.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `chunk_size` | integer | `1000` | Target words per chunk |
| `overlap` | integer | `100` | Words to overlap between chunks |
| `chunking_strategy` | string | `"auto"` | Strategy: `"auto"`, `"semantic"`, `"fixed"`, `"recursive"` |
| `embedding_model` | string | `"fast"` | For semantic: `"fast"` (~80MB) or `"balanced"` (~420MB) |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` |

**Chunking Strategies:**
- `auto`: Format-aware chunking (uses specialized chunker per file type)
- `semantic`: Embedding-based chunking using sentence-transformers (best for RAG)
- `fixed`: Simple character count splitting
- `recursive`: Paragraph/sentence boundary splitting

**Response (JSON):**
```json
{
  "success": true,
  "total_chunks": 25,
  "chunking_strategy": "semantic",
  "embedding_model": "fast",
  "chunks": [
    {
      "chunk_id": 0,
      "text": "Chunk content...",
      "word_count": 250,
      "keywords": ["key", "terms"],
      "section_name": "Introduction",
      "metadata": {
        "chunk_strategy": "semantic",
        "breakpoint_strategy": "percentile"
      }
    }
  ],
  "statistics": {
    "total_words": 6000,
    "average_chunk_words": 240
  }
}
```

### 7. `extract_metadata`

Quick metadata extraction without full document processing.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `output_format` | string | `"json"` | Output format: `"json"` or `"toon"` |

**Response (JSON):**
```json
{
  "success": true,
  "metadata": {
    "author": "John Doe",
    "title": "Document Title",
    "page_count": 10
  },
  "document_info": {
    "text_length": 35000,
    "image_count": 5
  }
}
```

### 8. `list_supported_formats`

List all supported document formats with availability status.

### 9. `batch_parse`

Parse multiple documents in a single request.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_paths` | string[] | required | Array of file paths |
| `include_images` | boolean | `false` | Include images |
| `continue_on_error` | boolean | `true` | Continue if a file fails |

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

TOON format reduces token usage by ~40% compared to JSON, ideal for LLM contexts:

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

**Enable with:** `output_format: "toon"` on any tool.

## Supported Formats

| Category | Extensions | Description |
|----------|-----------|-------------|
| **Documents** | `.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt` | Office documents with full structure |
| **Spreadsheets** | `.xlsx`, `.xlsm`, `.xltx`, `.xltm`, `.csv`, `.tsv` | Tables with type inference |
| **Web** | `.html`, `.htm`, `.md`, `.markdown` | Semantic structure preservation |
| **Text** | `.txt`, `.text`, `.log` | Plain text with paragraph detection |
| **Code** | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.cpp`, `.c`, `.go`, `.rs` | Language-aware parsing |
| **Data** | `.json`, `.yaml`, `.yml`, `.xml` | Structured data with schema detection |
| **Email** | `.eml`, `.msg` | Email with headers, body, attachments |
| **E-books** | `.epub` | Chapter extraction with TOC |
| **Rich Text** | `.rtf` | Rich Text Format documents |

**Total: 36 file extensions supported**

## Recommended Usage Pattern

For best results with AI systems that have token limits:

```
# 1. Start with summary (default behavior)
parse_document(file_path: "large_doc.pdf")

# 2. If you need more content, paginate
get_document_chunk(file_path: "large_doc.pdf", offset: 5000)
get_document_chunk(file_path: "large_doc.pdf", offset: 10000)

# 3. Fetch images separately when needed
get_document_images(file_path: "large_doc.pdf", max_images: 3)

# 4. For RAG pipelines, use semantic chunking
parse_document_chunked(file_path: "doc.pdf", chunking_strategy: "semantic")
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
 Raw text +         Semantic           Keywords +         JSON/TOON
 Structure          Chunks             Metadata            Output
```

**Extractors:** Format-specific text and metadata extraction
**Chunkers:** Auto, semantic (embeddings), fixed, recursive strategies
**Enrichers:** Keywords, sections, titles, complexity scores
**Formatters:** JSON (default) or TOON (token-optimized)

## Dependencies

**Core (always available):**
- `mcp>=1.0.0` - Model Context Protocol
- Code, Text, Markdown extractors (no heavy dependencies)

**Optional (for additional formats):**
- PDF: `pymupdf`, `pymupdf4llm`, `pillow`
- Office: `python-docx`, `python-pptx`, `openpyxl`
- Web: `beautifulsoup4`, `lxml`, `trafilatura`
- Data: `pyyaml` (YAML), `lxml` (XML)
- Email: `extract-msg` (MSG files)
- E-books: `ebooklib` (EPUB)
- Rich Text: `striprtf` (RTF)
- Semantic Chunking: `sentence-transformers`

Install all dependencies:
```bash
pip install -r requirements.txt
```

## Error Handling

All responses include appropriate error information on failure:

```json
{
  "success": false,
  "error": "File not found: /path/to/missing.pdf",
  "error_type": "ValueError"
}
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
python src/tests/test_lightweight.py

# Format code
black .

# Lint
ruff check .
```

## Comparison with Other Tools

| Feature | Chomper | LlamaParse | Docling | Unstructured |
|---------|-------------|------------|---------|--------------|
| MCP Native | Yes | No | No | No |
| Format Count | 36 | ~15 | ~10 | ~20 |
| Token Optimization | TOON (~40% savings) | No | No | No |
| Semantic Chunking | Built-in | Separate | Separate | Separate |
| MCP Prompts | 5 built-in | No | No | No |
| Complex Tables | Good (pymupdf4llm) | Excellent | Excellent (AI) | Average |
| Cloud Required | No (local) | Yes | No | Optional |
| Cost | Free | Paid | Free | Freemium |

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Start for Contributors

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/chomper.git
cd chomper

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

MIT License - see [LICENSE](LICENSE) for details.

---

Built with love by [@IcHiGo-KuRoSaKiI](https://github.com/IcHiGo-KuRoSaKiI)
