"""
MCP Tool definitions for Chomper.
"""

from mcp.types import Tool


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
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized, ~40% fewer tokens)"}
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
                    "content_base64": {"type": "string", "description": "Base64-encoded file content"},
                    "filename": {"type": "string", "description": "Filename with extension for format detection (e.g., 'report.pdf', 'data.xlsx', 'doc.docx')"},
                    "full_text": {"type": "boolean", "default": False, "description": "If true, return complete text. Default false returns first 5000 chars with continuation hint."},
                    "include_images": {"type": "boolean", "default": False, "description": "Include extracted images as ImageContent (default: false)."},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized, ~40% fewer tokens)"}
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
                    "offset": {"type": "integer", "default": 0, "description": "Character offset to start from (default: 0)"},
                    "limit": {"type": "integer", "default": 5000, "description": "Maximum characters to return (default: 5000)"},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized)"}
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_document_images",
            description="Retrieve images from a document on-demand. Returns images as ImageContent objects. Use this instead of include_images=true on parse_document for better control.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "page": {"type": "integer", "description": "Specific page number to get images from (1-indexed). Default: all pages."},
                    "max_images": {"type": "integer", "default": 5, "description": "Maximum number of images to return (default: 5)"}
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="parse_document_chunked",
            description="Parse a document into semantic chunks with configurable size and overlap. Ideal for processing large documents for RAG or embedding systems.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "chunk_size": {"type": "integer", "default": 1000, "description": "Target words per chunk (default: 1000)"},
                    "overlap": {"type": "integer", "default": 100, "description": "Words to overlap between chunks (default: 100)"},
                    "chunking_strategy": {"type": "string", "enum": ["auto", "semantic", "fixed", "recursive"], "default": "auto", "description": "Chunking strategy: 'auto' (format-aware), 'semantic' (embedding-based for RAG), 'fixed' (character count), 'recursive' (paragraph/sentence)"},
                    "embedding_model": {"type": "string", "enum": ["fast", "balanced"], "default": "fast", "description": "Embedding model for semantic chunking: 'fast' (~80MB) or 'balanced' (~420MB, better quality)"},
                    "output_format": {"type": "string", "enum": ["json", "toon"], "default": "json", "description": "Output format: 'json' (default) or 'toon' (token-optimized)"}
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
                    "file_paths": {"type": "array", "items": {"type": "string"}, "description": "Array of absolute paths to document files"},
                    "options": {
                        "type": "object",
                        "description": "Parsing options for all files",
                        "properties": {
                            "include_images": {"type": "boolean", "default": False, "description": "Include images (default: false)"},
                            "continue_on_error": {"type": "boolean", "default": True, "description": "Continue if a file fails (default: true)"}
                        }
                    }
                },
                "required": ["file_paths"]
            }
        )
    ]
