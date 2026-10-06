"""
MCP Tool definitions for Chomper.
"""

from typing import Any

from mcp.types import Tool

from .config import (
    CHUNK_STRATEGIES,
    DEFAULT_PDF_OCR,
    DEFAULT_PDF_TABLE_FORMAT,
    PDF_OCR_MODES,
    PDF_TABLE_FORMATS,
)

#: ``ocr`` argument, shared by every tool that extracts text.
OCR_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(PDF_OCR_MODES),
    "default": DEFAULT_PDF_OCR,
    "description": (
        "PDFs only (ignored for other formats). OCR matters only for pages without a "
        "text layer, such as scans: 'auto' (default) OCRs just those pages; 'off' never "
        "OCRs (scanned pages come back as image markers you can fetch with "
        "get_document_images); 'force' OCRs every page, which is slow and only useful "
        "when the text layer is garbled. OCR needs Tesseract or RapidOCR installed on "
        "the server; without one, scanned pages stay unread and the metadata says so."
    ),
}
#: ``table_format`` argument, shared by every tool that extracts text.
TABLE_FORMAT_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(PDF_TABLE_FORMATS),
    "default": DEFAULT_PDF_TABLE_FORMAT,
    "description": (
        "PDFs only (ignored for other formats). How tables are written into the text: "
        "'markdown' (default) pipe tables, or 'html' <table> markup that keeps merged "
        "and spanning cells. Offsets from get_document_chunk depend on this, so page "
        "with the same value you parsed with."
    ),
}


def _pdf_options() -> dict[str, Any]:
    return {"ocr": dict(OCR_PROPERTY), "table_format": dict(TABLE_FORMAT_PROPERTY)}


def get_tools() -> list[Tool]:
    """
    Get list of available document parsing tools.

    Returns:
        List of Tool definitions
    """
    return [
        Tool(
            name="parse_document",
            description="Parse a document and extract text, metadata, and images. Returns summary by default (first 5000 chars). Use full_text=true for complete content. Supports PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, and code files. Text is returned as plain text (not JSON wrapped). Images returned as ImageContent if include_images=true.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "full_text": {"type": "boolean", "default": False, "description": "If true, return complete text. Default false returns first 5000 chars with continuation hint."},
                    "include_images": {"type": "boolean", "default": False, "description": "Include extracted images as ImageContent (default: false). Use get_document_images for on-demand retrieval."},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized, ~40% fewer tokens)"},
                    **_pdf_options(),
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="parse_document_bytes",
            description="Parse a document from base64-encoded content. Use when document exists in memory, from cloud storage (S3, Azure Blob), API responses, or database. Supports all formats that parse_document supports.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_base64": {"type": "string", "maxLength": 139810140, "description": "Base64-encoded file content (decoded size at most 100 MB)"},
                    "filename": {"type": "string", "description": "Filename with extension for format detection (e.g., 'report.pdf', 'data.xlsx', 'doc.docx')"},
                    "full_text": {"type": "boolean", "default": False, "description": "If true, return complete text. Default false returns first 5000 chars with continuation hint."},
                    "include_images": {"type": "boolean", "default": False, "description": "Include extracted images as ImageContent (default: false)."},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized, ~40% fewer tokens)"},
                    **_pdf_options(),
                },
                "required": ["content_base64", "filename"]
            }
        ),
        Tool(
            name="get_document_chunk",
            description="Get a specific portion of document text. Use for paginated retrieval of large documents. Returns plain text content plus metadata about remaining content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "offset": {"type": "integer", "default": 0, "minimum": 0, "description": "Character offset to start from (default: 0)"},
                    "limit": {"type": "integer", "default": 5000, "minimum": 1, "description": "Maximum characters to return (default: 5000)"},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized)"},
                    **_pdf_options(),
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_document_images",
            description="Retrieve images from a document on-demand as ImageContent, each preceded by its id, page and position. Parsed text marks where each image sits as ![caption](image:<id>); pass that id as image_id to fetch one figure. Filter by page, cap with max_images.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "page": {"type": "integer", "minimum": 1, "description": "Specific page number to get images from (1-indexed). Default: all pages."},
                    "max_images": {"type": "integer", "default": 5, "minimum": 1, "description": "Maximum number of images to return (default: 5)"},
                    "image_id": {"type": "string", "description": "Return only this image: the id in a text marker like ![Figure 2](image:p3-1)."},
                    "max_dimension": {"type": "integer", "default": 1568, "minimum": 0, "description": "Downscale so the longest edge is at most this many pixels (default 1568, what vision models use). 0 returns full resolution."}
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="parse_document_chunked",
            description="Split a document into chunks for RAG or embedding systems. Chunk text keeps line breaks, lists, tables and code blocks; each chunk carries section_name, offsets and (with include_keywords) TF-IDF keywords. Same chunkers and defaults as the chomper library and CLI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "chunk_size": {"type": "integer", "default": 1000, "minimum": 1, "description": "Maximum words per chunk (default: 1000)"},
                    "overlap": {"type": "integer", "default": 100, "minimum": 0, "description": "Words to overlap between chunks (default: 100)"},
                    "chunking_strategy": {"type": "string", "enum": list(CHUNK_STRATEGIES), "default": "auto", "description": "Chunking strategy: 'auto' (format-aware: 'layout' for PDFs, headings, code functions, sheets), 'recursive' (headings > paragraphs > lines > sentences, never inside code fences or table rows), 'fixed' (fixed word windows that break only between lines), 'semantic' (embedding-based topic boundaries), 'layout' (PDFs: chunks the layout-model text that parse_document returns, cut at headings, never inside a table or figure marker, oversized tables split by rows with the header repeated; chunks carry page/pages and heading_path, and start_char/end_char index parse_document text; other formats: same as 'auto'), 'structural' (PDFs: chunks the chunker's own parse of the file, no OCR, offsets index its own text; other formats: same as 'auto'). ocr and table_format apply to every strategy except 'structural'."},
                    "embedding_model": {"type": "string", "enum": ["fast", "balanced"], "default": "fast", "description": "Embedding model for semantic chunking: 'fast' (~80MB) or 'balanced' (~420MB, better quality)"},
                    "include_keywords": {"type": "boolean", "default": False, "description": "Attach TF-IDF keywords (fitted across the document's chunks) to each chunk"},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized)"},
                    **_pdf_options(),
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="extract_metadata",
            description="Extract only metadata from a document without full processing. Useful for quick document analysis, file type detection, and previews.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized)"}
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="list_supported_formats",
            description="List all supported document formats with their descriptions. Returns available file extensions and format details.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="batch_parse",
            description="Parse multiple documents in a single request. Efficiently processes batches of files with shared options.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 500, "description": "Array of absolute paths to document files (parsed concurrently)"},
                    "options": {
                        "type": "object",
                        "description": "Parsing options for all files",
                        "properties": {
                            "include_images": {"type": "boolean", "default": False, "description": "Include images (default: false)"},
                            "continue_on_error": {"type": "boolean", "default": True, "description": "Continue if a file fails (default: true)"},
                            **_pdf_options(),
                        }
                    }
                },
                "required": ["file_paths"]
            }
        )
    ]
