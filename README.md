# Document Parser MCP Server

A production-ready [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes multi-format document parsing capabilities to AI systems like Claude.

## Features

- **9 Format Categories**: PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, Text, Code (10+ languages)
- **Smart Token Management**: Summary mode by default (5000 chars), pagination for large documents
- **Image Extraction**: PDF images returned as ImageContent for direct AI analysis
- **Intelligent Chunking**: Format-aware semantic chunking with configurable size/overlap
- **Rich Metadata**: Author, title, pages, word count, reading time, complexity scores
- **Batch Processing**: Parse multiple documents in a single request

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/Ichigo/Parser-MCP.git
cd Parser-MCP

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
document-parser-mcp
```

### Configure in Claude Code

```bash
claude mcp add -s user document-parser -- /path/to/Parser-MCP/venv/bin/python /path/to/Parser-MCP/server.py
```

### Configure in Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "document-parser": {
      "command": "/path/to/Parser-MCP/venv/bin/python",
      "args": ["/path/to/Parser-MCP/server.py"]
    }
  }
}
```

## Available Tools

### 1. `parse_document`

Parse a document and extract text, metadata, and images. **Returns summary by default** (first 5000 chars) to stay within token limits.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `full_text` | boolean | `false` | Return complete text (may exceed token limits) |
| `include_images` | boolean | `false` | Include images as ImageContent |

**Response:**
- `TextContent[0]`: Plain extracted text (no JSON wrapping)
- `TextContent[1]`: Metadata as JSON (includes continuation hint if truncated)
- `ImageContent[]`: Images if `include_images=true`

**Example:**
```
parse_document(file_path: "/path/to/doc.pdf")
→ Returns first 5000 chars + metadata with hint to fetch more
```

### 2. `get_document_chunk` ⭐ NEW

Get a specific portion of document text. **Use for paginated retrieval of large documents.**

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `offset` | integer | `0` | Character offset to start from |
| `limit` | integer | `5000` | Maximum characters to return |

**Example workflow:**
```
1. parse_document(file_path: "doc.pdf")
   → Returns chars 0-5000, hint: "use get_document_chunk(offset=5000)"

2. get_document_chunk(file_path: "doc.pdf", offset: 5000)
   → Returns chars 5000-10000

3. get_document_chunk(file_path: "doc.pdf", offset: 10000)
   → Returns chars 10000-15000, etc.
```

### 3. `get_document_images` ⭐ NEW

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

### 4. `parse_document_chunked`

Parse a document into semantic chunks with configurable size and overlap. Ideal for RAG systems.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |
| `chunk_size` | integer | `1000` | Target words per chunk |
| `overlap` | integer | `100` | Words to overlap between chunks |

**Response (JSON):**
```json
{
  "success": true,
  "total_chunks": 25,
  "chunks": [
    {
      "chunk_id": 0,
      "text": "Chunk content...",
      "word_count": 250,
      "keywords": ["key", "terms"],
      "section_name": "Introduction"
    }
  ],
  "statistics": {
    "total_words": 6000,
    "average_chunk_words": 240
  }
}
```

### 5. `extract_metadata`

Quick metadata extraction without full document processing.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_path` | string | required | Absolute path to the document |

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

### 6. `list_supported_formats`

List all supported document formats with availability status.

### 7. `batch_parse`

Parse multiple documents in a single request.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_paths` | string[] | required | Array of file paths |
| `include_images` | boolean | `false` | Include images |
| `continue_on_error` | boolean | `true` | Continue if a file fails |

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
```

**Avoid:**
```
# DON'T use full_text=true for large documents - will exceed token limits!
parse_document(file_path: "large_doc.pdf", full_text: true)  # ❌
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
python src/tests/test_lightweight.py

# Format code
black .

# Lint
ruff check .
```

## License

Proprietary
