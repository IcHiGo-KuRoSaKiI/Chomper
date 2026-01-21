# Document Parser MCP Server

A production-ready [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes multi-format document parsing capabilities to AI systems like Claude.

## Features

- **9 Format Categories**: PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, Text, Code (10+ languages)
- **Image Extraction**: PDF images returned as base64 for direct AI analysis
- **Intelligent Chunking**: Format-aware semantic chunking with configurable size/overlap
- **Rich Metadata**: Author, title, pages, word count, reading time, complexity scores
- **Batch Processing**: Parse multiple documents in a single request

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/ichigo/Parser-MCP.git
cd Parser-MCP

# Install dependencies
pip install -e .

# Or install with minimal dependencies (text/code/markdown only)
pip install -e ".[minimal]"
```

### Running the Server

```bash
# Direct execution
python server.py

# Or via the installed command
document-parser-mcp
```

### Configure in Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "document-parser": {
      "command": "python",
      "args": ["/path/to/Parser-MCP/server.py"]
    }
  }
}
```

### Configure in Claude Code

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "document-parser": {
      "command": "python",
      "args": ["/path/to/Parser-MCP/server.py"]
    }
  }
}
```

## Available Tools

### 1. `parse_document`

Parse a document and extract text, metadata, and images.

**Input:**
```json
{
  "file_path": "/path/to/document.pdf",
  "options": {
    "include_images": true,
    "chunk_size": 300,
    "output_format": "full"
  }
}
```

**Output:**
```json
{
  "success": true,
  "file_path": "/path/to/document.pdf",
  "text": "Full document text...",
  "metadata": {
    "author": "John Doe",
    "title": "Document Title",
    "page_count": 10
  },
  "images": [
    {
      "page": 1,
      "base64": "iVBORw0KGgo...",
      "width": 800,
      "height": 600,
      "position": {"x0": 50, "y0": 100, "x1": 450, "y1": 400}
    }
  ],
  "chunks": [...],
  "total_chunks": 15,
  "total_words": 5000
}
```

### 2. `parse_document_chunked`

Parse a document into semantic chunks with configurable size and overlap.

**Input:**
```json
{
  "file_path": "/path/to/document.pdf",
  "chunk_size": 1000,
  "overlap": 100
}
```

**Output:**
```json
{
  "success": true,
  "file_path": "/path/to/document.pdf",
  "chunk_size": 1000,
  "overlap": 100,
  "total_chunks": 25,
  "chunks": [
    {
      "chunk_id": 0,
      "text": "First chunk content...",
      "start_char": 0,
      "end_char": 1500,
      "word_count": 250,
      "metadata": {"page_number": 1},
      "keywords": ["key", "terms"],
      "section_name": "Introduction",
      "section_type": "text"
    }
  ],
  "statistics": {
    "total_words": 6000,
    "average_chunk_words": 240,
    "total_characters": 35000
  }
}
```

### 3. `extract_metadata`

Quick metadata extraction without full document processing.

**Input:**
```json
{
  "file_path": "/path/to/document.pdf"
}
```

**Output:**
```json
{
  "success": true,
  "file_path": "/path/to/document.pdf",
  "metadata": {
    "author": "John Doe",
    "title": "Document Title",
    "creator": "Microsoft Word",
    "producer": "PDF Library",
    "format": "PDF 1.7"
  },
  "document_info": {
    "text_length": 35000,
    "has_structure": true,
    "page_count": 10,
    "image_count": 5
  }
}
```

### 4. `list_supported_formats`

List all supported document formats with availability status.

**Input:**
```json
{}
```

**Output:**
```json
{
  "success": true,
  "total_formats": 28,
  "available_formats": 28,
  "formats": [
    {
      "extension": ".pdf",
      "description": "PDF documents with text and image extraction",
      "available": true
    }
  ],
  "by_category": {
    "documents": [...],
    "spreadsheets": [...],
    "web": [...],
    "text": [...],
    "code": [...]
  }
}
```

### 5. `batch_parse`

Parse multiple documents in a single request.

**Input:**
```json
{
  "file_paths": [
    "/path/to/doc1.pdf",
    "/path/to/doc2.docx",
    "/path/to/doc3.md"
  ],
  "options": {
    "include_images": false,
    "chunk_size": 300,
    "continue_on_error": true
  }
}
```

**Output:**
```json
{
  "success": true,
  "total_files": 3,
  "successful": 3,
  "failed": 0,
  "results": [
    {"success": true, "file_path": "/path/to/doc1.pdf", ...},
    {"success": true, "file_path": "/path/to/doc2.docx", ...},
    {"success": true, "file_path": "/path/to/doc3.md", ...}
  ]
}
```

## Supported Formats

| Category | Extensions | Description |
|----------|-----------|-------------|
| **Documents** | `.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt` | Office documents with full structure |
| **Spreadsheets** | `.xlsx`, `.xlsm`, `.xltx`, `.xltm`, `.csv`, `.tsv` | Tables with type inference |
| **Web** | `.html`, `.htm`, `.md`, `.markdown` | Semantic structure preservation |
| **Text** | `.txt`, `.text`, `.log` | Plain text with paragraph detection |
| **Code** | `.py`, `.js`, `.ts`, `.java`, `.cpp`, `.c`, `.go`, `.rs` | AST-aware parsing |

## Architecture

The server wraps a 4-layer document processing pipeline:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Extractors │ -> │  Chunkers   │ -> │  Enrichers  │ -> │ Formatters  │
│ (Layer 1)   │    │ (Layer 2)   │    │ (Layer 3)   │    │ (Layer 4)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
     │                   │                  │                   │
     v                   v                  v                   v
 Raw text +         Semantic           Keywords +           JSON/Dict
 Structure          Chunks             Metadata              Output
```

### Extractors (10 formats)
- PDF: PyMuPDF with image/layout extraction
- DOCX: python-docx with heading hierarchy
- Code: AST parsing for Python, regex for others

### Chunkers (9 strategies)
- Format-aware semantic splitting
- Preserves document structure
- Configurable size/overlap

### Enrichers (4 types)
- Keywords: RAKE or TF-IDF extraction
- Sections: Heuristic or TextTiling detection
- Titles: Smart title generation
- Metadata: Word count, reading time, complexity

## Error Handling

All responses include a `success` field. On failure:

```json
{
  "success": false,
  "error": "File not found: /path/to/missing.pdf",
  "error_type": "ValueError"
}
```

For batch processing with `continue_on_error: true`, individual file errors are captured in results while processing continues.

## Large Document Handling

For documents over 100KB of text, the response includes pagination info:

```json
{
  "pagination": {
    "total_characters": 150000,
    "is_large_document": true,
    "recommendation": "Consider using parse_document_chunked for better handling"
  }
}
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black .

# Lint
ruff check .

# Type check
mypy server.py
```

## License

MIT License - see LICENSE file for details.
