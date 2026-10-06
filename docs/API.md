# Chomper API Reference

Complete reference for all MCP tools exposed by Chomper. Tool schemas live in `src/server/tools.py`; handlers in `src/handlers/`.

Every handler reads documents through the shared extraction cache (`src/server/cache.py`) and runs extraction in a worker thread, so paging, metadata and image calls on an unchanged file reuse one extraction.

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
- [Image Markers](#image-markers)
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
| `parse_document_chunked` | Structure-aware chunking | RAG systems |
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
| `include_images` | boolean | No | `false` | Include up to 5 images as ImageContent |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Response

Returns `list[TextContent | ImageContent]`:

1. **TextContent[0]**: Document text as Markdown (first 5000 chars by default), with `![caption](image:<id>)` markers where figures sit
2. **TextContent[1]**: Metadata as JSON (with `output_format: "toon"`, text and metadata come as one TOON block instead)
3. With `include_images=true`: for each image, a TextContent `Image N info: {...}` (page, dimensions, position) followed by its ImageContent

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
    "extraction_method": "pymupdf-layout"
  },
  "continuation_hint": "Document has 45000 more characters. Use get_document_chunk(file_path, offset=5000) for more.",
  "page_count": 25,
  "image_count": 10,
  "images_hint": "Document contains 10 images. Use get_document_images(file_path) to retrieve them."
}
```

PDF `document_metadata` can also carry `pages_without_text_layer` (scanned pages with no text, listed with a `warning`) and `ocr_pages` (scanned pages read by OCR; needs Tesseract or RapidOCR). See [Image Markers](#image-markers).

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

Parse a document from base64-encoded content. Perfect for cloud storage, API responses, or in-memory documents. The content must be valid base64 and decode to at most 100 MB; it is written to a temporary file that is never cached and is deleted afterwards.

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
| `offset` | integer | No | `0` | Character offset to start from (`>= 0`, inside the document) |
| `limit` | integer | No | `5000` | Maximum characters to return (`>= 1`) |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

An offset past the end of the document is an error that states the valid range.

### Response

1. **TextContent[0]**: Chunk text
2. **TextContent[1]**: Chunk metadata (adds `next_chunk_hint` while `has_more` is true)

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

Retrieve images from a document on-demand. Images are decoded, converted and downscaled only for the ones returned (`src/extractors/image_utils.py`).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `page` | integer | No | all | Specific page or slide (1-indexed) |
| `max_images` | integer | No | `5` | Maximum images to return |
| `image_id` | string | No | - | Only this image: the id in a text marker like `![Figure 2](image:p3-1)` |
| `max_dimension` | integer | No | `1568` | Downscale so the long edge is at most this many pixels; `0` returns full resolution |

Returned images are PNG, JPEG, GIF or WebP and at most 3.5 MB each. Identical images (a logo on every page) are returned once. An unknown `image_id` is an error.

### Response

1. **TextContent[0]**: Summary
2. For each image: a TextContent `Image N: {...}` with its id, page, dimensions, position, original dimensions (when downscaled) and caption (`alt`), then the ImageContent

```json
{
  "file_path": "/docs/document.pdf",
  "total_images_in_document": 15,
  "returned_images": 5,
  "page_filter": null,
  "max_images": 5,
  "note": "Showing first 5 of 15 images. Use page, image_id or a larger max_images for others."
}
```

```
Image 1: {"image_index": 1, "id": "p3-1", "page": 3, "dimensions": "1568x1176", "position": {"x0": 72.0, "y0": 140.0, "x1": 540.0, "y1": 491.0}, "original_dimensions": "4000x3000", "alt": "Figure 2: Revenue by region"}
```

### Examples

```python
# First 5 images from entire document
get_document_images(file_path="/docs/report.pdf")

# First 3 images from page 2
get_document_images(file_path="/docs/report.pdf", page=2, max_images=3)

# All images from page 1 (up to 10)
get_document_images(file_path="/docs/report.pdf", page=1, max_images=10)

# The figure marked ![Figure 2: ...](image:p3-1) in the text, at full resolution
get_document_images(file_path="/docs/report.pdf", image_id="p3-1", max_dimension=0)
```

---

## parse_document_chunked

Split a document into chunks for RAG systems. Uses the same chunker factory, defaults and strategy names as `chomper.chunk()` and the CLI (`build_chunker` in `src/server/documents.py`).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | - | Absolute path to the document |
| `chunk_size` | integer | No | `1000` | Maximum words per chunk (`>= 1`) |
| `overlap` | integer | No | `100` | Words to overlap between chunks (`>= 0`; `0` means none) |
| `chunking_strategy` | string | No | `"auto"` | See strategies below |
| `embedding_model` | string | No | `"fast"` | `"fast"` or `"balanced"` |
| `include_keywords` | boolean | No | `false` | Attach TF-IDF keywords, fitted across the document's chunks |
| `output_format` | string | No | `"json"` | `"json"` or `"toon"` |

### Chunking Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `auto` | Format-aware: PDF structure (`StructuralPDFChunker`), DOCX/Markdown headings, code by function, spreadsheet sheets and tables, slides | General use |
| `recursive` | Headings, then blank lines, then lines, then sentences; never inside a code fence or table row | Structured text |
| `fixed` | Fixed word windows that only break between lines | Simple splitting |
| `semantic` | Embedding-based topic boundaries; `chunk_size` is the maximum (needs the `semantic` extra) | RAG systems |

Text-based chunkers cut exact slices of the document text (`src/chunking/text_splitter.py`), so line breaks, lists, tables and code blocks survive and `start_char`/`end_char` point into that text. `section_name` is filled from the heading, slide title or sheet name the chunk belongs to.

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
  "chunk_size": 500,
  "overlap": 50,
  "chunking_strategy": "semantic",
  "total_chunks": 15,
  "chunks": [
    {
      "chunk_id": 0,
      "text": "## Introduction\n\nIntroduction to the document...",
      "start_char": 0,
      "end_char": 2500,
      "word_count": 420,
      "metadata": {
        "chunk_strategy": "semantic",
        "breakpoint_strategy": "percentile"
      },
      "keywords": ["introduction", "overview", "background"],
      "section_name": "Introduction",
      "section_type": "text"
    }
  ],
  "metadata": {"filename": "document.pdf", "page_count": 25},
  "statistics": {
    "total_words": 6300,
    "average_chunk_words": 420,
    "total_characters": 41000
  },
  "embedding_model": "fast"
}
```

`keywords` is `[]` unless `include_keywords` is true. `embedding_model` appears only for the `semantic` strategy.

### Examples

```python
# Auto-detect best strategy for format
parse_document_chunked(file_path="/docs/report.pdf")

# Semantic chunking for RAG, with keywords
parse_document_chunked(
    file_path="/docs/report.pdf",
    chunking_strategy="semantic",
    embedding_model="balanced",
    chunk_size=500,
    overlap=50,
    include_keywords=True
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

Metadata without returning the text. It runs the same extraction as `parse_document` (served from the cache when the file was already parsed).

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
    "modified": "2024-01-20T14:45:00",
    "format": "pdf",
    "extraction_method": "pymupdf-layout"
  },
  "document_info": {
    "text_length": 50000,
    "has_structure": true,
    "page_count": 25,
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
      "reason": "Optional dependency missing for .msg. Install with: pip install 'chomper[email]'"
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

Parse multiple documents in a single request. Files are parsed concurrently (at most 4 at a time, fewer on machines with fewer CPUs) and results keep the order of `file_paths`. PDFs share one PyMuPDF lock (MuPDF is not thread-safe), so they gain less from concurrency.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_paths` | string[] | Yes | - | 1 to 500 absolute file paths |
| `options.include_images` | boolean | No | `false` | Add each file's `image_count` |
| `options.continue_on_error` | boolean | No | `true` | Report failures per file; when false, the first failure fails the call |

### Response

```json
{
  "success": true,
  "total_files": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    {
      "success": true,
      "file_path": "/docs/doc1.pdf",
      "text_preview": "First 500 characters...",
      "total_characters": 50000,
      "total_words": 8500,
      "metadata": {...}
    },
    {
      "success": true,
      "file_path": "/docs/doc2.docx",
      "text_preview": "Another document...",
      "total_characters": 1200,
      "total_words": 210,
      "metadata": {...}
    },
    {
      "file_path": "/docs/missing.pdf",
      "success": false,
      "error": "File not found: /docs/missing.pdf. Check the path and pass an absolute path.",
      "error_type": "ValueError"
    }
  ]
}
```

---

## Image Markers

Parsed text marks each image or figure where it sits, as `![caption](image:<id>)`. Pass the id to `get_document_images(image_id=...)`.

| Format | Id | What gets a marker |
|--------|----|--------------------|
| PDF | `p<page>-<n>` (`p3-1`) | Raster images and vector-drawn charts or diagrams (rendered only when requested). The caption comes from the adjacent caption region, a title bar inside the figure frame, or is shared by side-by-side panels. Logos repeated on most pages get no marker but are still returned as images. |
| PPTX | `s<slide>-<n>` (`s2-1`) | Pictures, with their alt text |
| DOCX, HTML, EPUB, email | `img-<n>` | Embedded images, HTML `data:` images, `cid:` inline email images. HTML images that only link to a URL stay ordinary Markdown images. |

Scanned PDF pages (a page-sized image and no text layer) get a marker too. With an OCR engine installed (Tesseract or RapidOCR; `ocr="auto"` in `PDFExtractor`) the OCR text follows the marker and the page is listed in `metadata["ocr_pages"]`; otherwise the page is listed in `metadata["pages_without_text_layer"]` and `metadata["warning"]` says its text is missing.

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

~40% fewer tokens than JSON. `parse_document` with `output_format: "toon"`:

```
d:report.pdf|t:pdf|w:5000|c:25000|p:10
m:author=John Doe,title=Annual Report
~+20000chars|use:get_document_chunk(offset=5000)
---
content
First 5000 characters of document text here...
```

`p:` is the page count, and `i:` the image count when there are images. `get_document_chunk` returns a `d:report.pdf|offset:5000|limit:5000|total:50000` header and a `next:` hint; `parse_document_chunked` returns one `id|start-end|type|section` block per chunk.

**Enable with**: `output_format: "toon"` on `parse_document`, `parse_document_bytes`, `get_document_chunk`, `parse_document_chunked` and `extract_metadata`.

---

## Error Handling

A failed call is an MCP tool error: `CallToolResult` with `isError: true` and one text item, `<tool> failed (<ExceptionType>): <message>` (`tool_error` in `server.py`). Messages say what was wrong and what to pass instead:

```
get_document_chunk failed (ValueError): offset must be >= 0, got -3.
parse_document_chunked failed (ValueError): chunking_strategy must be one of ['auto', 'semantic', 'fixed', 'recursive'], got 'bogus'.
```

Arguments are validated against the tool's input schema (required, type, enum, minimum, length and item limits) before the handler runs, and the message names the argument.

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `File not found` | Invalid path | Verify the file exists; pass an absolute path |
| `Unsupported file format` | Unknown extension | Check `list_supported_formats` |
| `Optional dependency missing` | Extra not installed | Run the `pip install` command in the message |
| `legacy binary ...` | Word 97-2003 `.doc` or old `.ppt` file | Save as `.docx` / `.pptx` |
| `offset ... is past the end` | Paged beyond the text | Use an offset in the stated range |
| `... over the 100 MB limit` | Oversized `parse_document_bytes` payload | Save to a file and use `parse_document` |
| `Invalid base64 content` | Payload is not standard base64 | Send RFC 4648 base64 without line breaks |

`batch_parse` reports per-file failures inside its result (`"success": false`, `error`, `error_type`) unless `continue_on_error` is false.

---

## Best Practices

### For Large Documents

```python
# 1. Start with summary
result = parse_document(file_path="large.pdf")

# 2. Paginate if needed
chunk = get_document_chunk(file_path="large.pdf", offset=5000)

# 3. Fetch a figure the text points to, or images separately
figure = get_document_images(file_path="large.pdf", image_id="p4-2")
images = get_document_images(file_path="large.pdf", max_images=3)
```

### For RAG Systems

```python
# Structure-aware chunks with keywords
chunks = parse_document_chunked(
    file_path="document.pdf",
    chunk_size=500,
    include_keywords=True
)

# Each chunk has: text, start_char/end_char, keywords, section_name
for chunk in chunks["chunks"]:
    embed_and_store(chunk["text"], chunk["keywords"], chunk["section_name"])
```

### For Token-Constrained Contexts

```python
# Use TOON format throughout
parse_document(file_path="doc.pdf", output_format="toon")
get_document_chunk(file_path="doc.pdf", offset=5000, output_format="toon")
```
