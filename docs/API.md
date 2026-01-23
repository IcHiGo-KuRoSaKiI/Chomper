# Chomper API Reference

Complete reference for all MCP tools exposed by Chomper.

## Table of Contents

- [Tools Overview](#tools-overview)
- [parse_document](#parse_document)
- [parse_document_bytes](#parse_document_bytes)
- [get_document_chunk](#get_document_chunk)
- [get_document_images](#get_document_images)
- [parse_document_chunked](#parse_document_chunked)
- [extract_metadata](#extract_metadata)
- [list_supported_formats](#list_supported_formats)
- [batch_parse](#batch_parse)
- [MCP Prompts](#mcp-prompts)
- [Output Formats](#output-formats)
- [Error Handling](#error-handling)

---

## Tools Overview

| Tool | Purpose | Primary Use Case |
|------|---------|------------------|
| `parse_document` | Extract text and metadata | General document parsing |
| `parse_document_bytes` | Parse base64 content | Cloud storage, APIs |
| `get_document_chunk` | Paginated retrieval | Large documents |
| `get_document_images` | Image extraction | Visual analysis |
| `parse_document_chunked` | Semantic chunking | RAG systems |
| `extract_metadata` | Quick metadata | File indexing |
| `list_supported_formats` | Format discovery | Capability checking |
| `batch_parse` | Multi-file parsing | Bulk processing |

---

## parse_document

Parse a document and extract text, metadata, and optionally images.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `full_text` | boolean | No | `false` | Return complete text (may be large) |
| `include_images` | boolean | No | `false` | Include images as ImageContent |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Response

Returns `List[TextContent | ImageContent]`:

1. **TextContent[0]**: Document text (first 5000 chars by default)
2. **TextContent[1]**: Metadata as JSON/TOON
3. **ImageContent[]**: Images (if `include_images=true`)

### JSON Metadata Response

```json
{
  "file_path": "/path/to/document.pdf",
  "total_characters": 50000,
  "total_words": 8500,
  "document_metadata": {
    "filename": "document.pdf",
    "file_size": 1024000,
    "file_extension": ".pdf",
    "author": "John Doe",
    "title": "Annual Report",
    "page_count": 25,
    "format": "pdf",
    "extraction_method": "pymupdf4llm"
  },
  "page_count": 25,
  "image_count": 10,
  "continuation_hint": "Document has 45000 more characters. Use get_document_chunk(file_path, offset=5000) for more."
}
```

### Examples

```python
# Basic usage - returns summary (5000 chars)
parse_document(file_path="/docs/report.pdf")

# Full document (may exceed token limits)
parse_document(file_path="/docs/report.pdf", full_text=True)

# With images
parse_document(file_path="/docs/report.pdf", include_images=True)

# Token-optimized output
parse_document(file_path="/docs/report.pdf", output_format="toon")
```

---

## parse_document_bytes

Parse a document from base64-encoded content. Perfect for cloud storage, API responses, or in-memory documents.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content_base64` | string | Yes | - | Base64-encoded file content |
| `filename` | string | Yes | - | Filename with extension (e.g., `"report.pdf"`) |
| `full_text` | boolean | No | `false` | Return complete text |
| `include_images` | boolean | No | `false` | Include images |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Response

Same as `parse_document`.

### Examples

```python
import base64

# From file
with open("document.pdf", "rb") as f:
    content = base64.b64encode(f.read()).decode()

parse_document_bytes(
    content_base64=content,
    filename="document.pdf"
)

# From S3
import boto3
s3 = boto3.client('s3')
response = s3.get_object(Bucket='my-bucket', Key='doc.pdf')
content = base64.b64encode(response['Body'].read()).decode()

parse_document_bytes(
    content_base64=content,
    filename="doc.pdf"
)

# From API response
api_response = requests.get("https://api.example.com/document")
content = base64.b64encode(api_response.content).decode()

parse_document_bytes(
    content_base64=content,
    filename="api_document.docx"
)
```

---

## get_document_chunk

Get a specific portion of document text. Use for paginated retrieval of large documents.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `offset` | integer | No | `0` | Character offset to start from |
| `limit` | integer | No | `5000` | Maximum characters to return |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Response

1. **TextContent[0]**: Chunk text
2. **TextContent[1]**: Chunk metadata

```json
{
  "file_path": "/docs/document.pdf",
  "offset": 5000,
  "limit": 5000,
  "returned_chars": 5000,
  "total_chars": 50000,
  "remaining_chars": 40000,
  "has_more": true
}
```

### Example Workflow

```python
# 1. Initial parse returns first 5000 chars
result = parse_document(file_path="/docs/large_doc.pdf")
# metadata.continuation_hint: "use get_document_chunk(offset=5000)"

# 2. Get next chunk
chunk1 = get_document_chunk(file_path="/docs/large_doc.pdf", offset=5000)

# 3. Continue until has_more=false
chunk2 = get_document_chunk(file_path="/docs/large_doc.pdf", offset=10000)
chunk3 = get_document_chunk(file_path="/docs/large_doc.pdf", offset=15000)
# ...
```

---

## get_document_images

Retrieve images from a document on-demand.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `page` | integer | No | all | Specific page (1-indexed) |
| `max_images` | integer | No | `5` | Maximum images to return |

### Response

1. **TextContent[0]**: Summary with image positions
2. **ImageContent[]**: Actual images as base64

```json
{
  "file_path": "/docs/document.pdf",
  "total_images": 15,
  "returned_images": 5,
  "images": [
    {
      "index": 0,
      "page": 1,
      "width": 800,
      "height": 600,
      "format": "png"
    }
  ]
}
```

### Examples

```python
# First 5 images from entire document
get_document_images(file_path="/docs/report.pdf")

# First 3 images from page 2
get_document_images(file_path="/docs/report.pdf", page=2, max_images=3)

# All images from page 1 (up to 10)
get_document_images(file_path="/docs/report.pdf", page=1, max_images=10)
```

---

## parse_document_chunked

Parse document into semantic chunks for RAG systems.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `chunk_size` | integer | No | `1000` | Target words per chunk |
| `overlap` | integer | No | `100` | Words to overlap between chunks |
| `chunking_strategy` | string | No | `"auto"` | See strategies below |
| `embedding_model` | string | No | `"fast"` | `"fast"` or `"balanced"` |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Chunking Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `auto` | Format-aware (PDF by page, Code by function) | General use |
| `semantic` | Embedding-based breakpoints | RAG systems |
| `fixed` | Fixed word count | Simple splitting |
| `recursive` | Paragraph/sentence boundaries | Structured text |

### Embedding Models

| Model | Name | Size | Speed | Quality |
|-------|------|------|-------|---------|
| `fast` | all-MiniLM-L6-v2 | ~80MB | Fast | Good |
| `balanced` | all-mpnet-base-v2 | ~420MB | Medium | Better |

### Response

```json
{
  "success": true,
  "file_path": "/docs/document.pdf",
  "total_chunks": 15,
  "chunking_strategy": "semantic",
  "embedding_model": "fast",
  "chunks": [
    {
      "chunk_id": 0,
      "text": "Introduction to the document...",
      "start_char": 0,
      "end_char": 2500,
      "word_count": 420,
      "keywords": ["introduction", "overview", "background"],
      "section_name": "Introduction",
      "metadata": {
        "chunk_strategy": "semantic",
        "breakpoint_strategy": "percentile"
      }
    }
  ],
  "statistics": {
    "total_words": 6300,
    "average_chunk_words": 420,
    "min_chunk_words": 250,
    "max_chunk_words": 580
  }
}
```

### Examples

```python
# Auto-detect best strategy for format
parse_document_chunked(file_path="/docs/report.pdf")

# Semantic chunking for RAG
parse_document_chunked(
    file_path="/docs/report.pdf",
    chunking_strategy="semantic",
    embedding_model="balanced",
    chunk_size=500,
    overlap=50
)

# Fixed-size chunks
parse_document_chunked(
    file_path="/docs/report.pdf",
    chunking_strategy="fixed",
    chunk_size=1000
)
```

---

## extract_metadata

Quick metadata extraction without full document processing.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Response

```json
{
  "success": true,
  "file_path": "/docs/document.pdf",
  "metadata": {
    "filename": "document.pdf",
    "file_size": 1024000,
    "file_extension": ".pdf",
    "author": "John Doe",
    "title": "Annual Report 2024",
    "subject": "Financial Summary",
    "creator": "Microsoft Word",
    "producer": "Adobe PDF Library",
    "page_count": 25,
    "created": "2024-01-15T10:30:00",
    "modified": "2024-01-20T14:45:00"
  },
  "document_info": {
    "text_length": 50000,
    "has_structure": true,
    "image_count": 10
  }
}
```

---

## list_supported_formats

List all supported document formats with availability status.

### Parameters

None.

### Response

```json
{
  "success": true,
  "total_formats": 36,
  "available_formats": 36,
  "formats": [
    {
      "extension": ".pdf",
      "description": "PDF documents with text and image extraction",
      "available": true,
      "reason": null
    },
    {
      "extension": ".msg",
      "description": "Outlook email messages",
      "available": false,
      "reason": "Missing dependency: extract-msg"
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

---

## batch_parse

Parse multiple documents in a single request.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_paths` | string[] | Yes | - | Array of file paths |
| `options.include_images` | boolean | No | `false` | Include images |
| `options.continue_on_error` | boolean | No | `true` | Continue on failures |

### Response

```json
{
  "success": true,
  "total_files": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    {
      "file_path": "/docs/doc1.pdf",
      "success": true,
      "text": "Document content...",
      "metadata": {...}
    },
    {
      "file_path": "/docs/doc2.docx",
      "success": true,
      "text": "Another document...",
      "metadata": {...}
    },
    {
      "file_path": "/docs/missing.pdf",
      "success": false,
      "error": "File not found",
      "error_type": "ValueError"
    }
  ]
}
```

---

## MCP Prompts

Chomper exposes 5 document analysis prompts:

### summarize-document

Generate comprehensive document summary.

| Argument | Required | Values |
|----------|----------|--------|
| `file_path` | Yes | Document path |
| `length` | No | `"short"`, `"medium"`, `"long"` |

### extract-key-points

Extract main takeaways.

| Argument | Required | Default |
|----------|----------|---------|
| `file_path` | Yes | - |
| `max_points` | No | `10` |

### explain-document

Explain for different audiences.

| Argument | Required | Values |
|----------|----------|--------|
| `file_path` | Yes | - |
| `audience` | No | `"child"`, `"general"`, `"expert"` |

### extract-entities

Extract named entities.

| Argument | Required | Description |
|----------|----------|-------------|
| `file_path` | Yes | - |
| `entity_types` | No | People, organizations, locations |

### document-qa

Set up Q&A context.

| Argument | Required |
|----------|----------|
| `file_path` | Yes |

---

## Output Formats

### JSON (Default)

Standard JSON format with full structure.

### TOON (Token-Optimized)

~40% fewer tokens than JSON:

```
d:report.pdf|t:pdf|w:5000|c:25000|n:10
m:author=John Doe,title=Annual Report
~+20000chars|use:get_document_chunk(offset=5000)
---
content
First 5000 characters of document text here...
```

**Enable with**: `output_format: "toon"`

---

## Error Handling

All errors return structured JSON:

```json
{
  "success": false,
  "error": "Descriptive error message",
  "error_type": "ValueError"
}
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `File not found` | Invalid path | Verify file exists |
| `Unsupported format` | Unknown extension | Check `list_supported_formats` |
| `Missing dependency` | Optional dep not installed | Install required package |
| `Permission denied` | File not readable | Check file permissions |

---

## Best Practices

### For Large Documents

```python
# 1. Start with summary
result = parse_document(file_path="large.pdf")

# 2. Paginate if needed
chunk = get_document_chunk(file_path="large.pdf", offset=5000)

# 3. Fetch images separately
images = get_document_images(file_path="large.pdf", max_images=3)
```

### For RAG Systems

```python
# Use semantic chunking
chunks = parse_document_chunked(
    file_path="document.pdf",
    chunking_strategy="semantic",
    chunk_size=500
)

# Each chunk has: text, keywords, section_name
for chunk in chunks["chunks"]:
    embed_and_store(chunk["text"], chunk["keywords"])
```

### For Token-Constrained Contexts

```python
# Use TOON format throughout
parse_document(file_path="doc.pdf", output_format="toon")
get_document_chunk(file_path="doc.pdf", offset=5000, output_format="toon")
```
