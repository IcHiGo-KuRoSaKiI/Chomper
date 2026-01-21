#!/usr/bin/env python3
"""
Chomper - Chomp through any document.

An MCP server that parses 36+ file formats for AI systems like Claude.

Features:
- Full document parsing with text, metadata, and image extraction
- Semantic chunking with sentence-transformers for RAG
- TOON format for ~40% token reduction
- MCP prompts for document analysis
- Batch processing for multiple files
- Support for PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, JSON, YAML, XML, Email, EPUB, RTF, and code files

Usage:
    python server.py

    Or via MCP client configuration:
    {
        "mcpServers": {
            "chomper": {
                "command": "python",
                "args": ["/path/to/server.py"]
            }
        }
    }
"""

import asyncio
import base64
import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    ImageContent,
    Tool,
    Prompt,
    PromptArgument,
    PromptMessage,
    GetPromptResult,
)

# Add parsers to path if needed
sys.path.insert(0, str(Path(__file__).parent))

from src import DocumentPipeline, SimpleFormatter
from src.formatters.toon_formatter import TOONFormatter
from src.prompts import PROMPTS, format_prompt
from src.extractors import (
    PDFExtractor,
    DOCXExtractor,
    PPTXExtractor,
    CodeExtractor,
    TextExtractor,
    MarkdownExtractor,
    ExcelExtractor,
    CSVExtractor,
    HTMLExtractor,
    JSONExtractor,
    YAMLExtractor,
    XMLExtractor,
    EMLExtractor,
    MSGExtractor,
    EPUBExtractor,
    RTFExtractor,
)
from src.chunking.strategies import (
    PDFChunker,
    DOCXChunker,
    PPTXChunker,
    CodeChunker,
    TextChunker,
    MarkdownChunker,
    ExcelChunker,
    HTMLChunker,
    SemanticChunker,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("chomper")

# Initialize MCP server
server = Server("chomper")

# Default constants
DEFAULT_SUMMARY_CHARS = 5000
DEFAULT_CHUNK_LIMIT = 5000
DEFAULT_MAX_IMAGES = 5

# Output format options
OUTPUT_FORMAT_JSON = "json"
OUTPUT_FORMAT_TOON = "toon"
DEFAULT_OUTPUT_FORMAT = OUTPUT_FORMAT_JSON

# Format descriptions for supported extensions
FORMAT_DESCRIPTIONS: Dict[str, str] = {
    ".pdf": "PDF documents with text and image extraction",
    ".docx": "Microsoft Word documents (OOXML format)",
    ".doc": "Microsoft Word documents (legacy format via DOCX handler)",
    ".pptx": "Microsoft PowerPoint presentations",
    ".ppt": "Microsoft PowerPoint presentations (legacy format)",
    ".xlsx": "Microsoft Excel spreadsheets",
    ".xlsm": "Microsoft Excel macro-enabled spreadsheets",
    ".xltx": "Microsoft Excel templates",
    ".xltm": "Microsoft Excel macro-enabled templates",
    ".csv": "Comma-separated values files",
    ".tsv": "Tab-separated values files",
    ".html": "HTML web pages",
    ".htm": "HTML web pages (alternate extension)",
    ".md": "Markdown documents",
    ".markdown": "Markdown documents (alternate extension)",
    ".txt": "Plain text files",
    ".text": "Plain text files (alternate extension)",
    ".log": "Log files",
    ".py": "Python source code",
    ".js": "JavaScript source code",
    ".jsx": "React JSX source code",
    ".ts": "TypeScript source code",
    ".tsx": "React TypeScript source code",
    ".java": "Java source code",
    ".cpp": "C++ source code",
    ".c": "C source code",
    ".go": "Go source code",
    ".rs": "Rust source code",
    ".json": "JSON data files",
    ".yaml": "YAML configuration/data files",
    ".yml": "YAML configuration/data files",
    ".xml": "XML documents",
    ".eml": "Email messages (RFC 822 format)",
    ".msg": "Outlook email messages",
    ".epub": "EPUB e-books",
    ".rtf": "Rich Text Format documents",
}

# Extractor mapping by extension
EXTRACTORS: Dict[str, type] = {}
CHUNKERS: Dict[str, type] = {}


def _initialize_extractors() -> None:
    """Initialize extractor and chunker mappings based on available dependencies."""
    global EXTRACTORS, CHUNKERS

    # Always available extractors
    code_extensions = [".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".go", ".rs"]
    for ext in code_extensions:
        EXTRACTORS[ext] = CodeExtractor
        CHUNKERS[ext] = CodeChunker

    EXTRACTORS[".txt"] = TextExtractor
    EXTRACTORS[".text"] = TextExtractor
    EXTRACTORS[".log"] = TextExtractor
    CHUNKERS[".txt"] = TextChunker
    CHUNKERS[".text"] = TextChunker
    CHUNKERS[".log"] = TextChunker

    EXTRACTORS[".md"] = MarkdownExtractor
    EXTRACTORS[".markdown"] = MarkdownExtractor
    CHUNKERS[".md"] = MarkdownChunker
    CHUNKERS[".markdown"] = MarkdownChunker

    # Optional extractors (require heavy dependencies)
    if PDFExtractor is not None:
        EXTRACTORS[".pdf"] = PDFExtractor
        CHUNKERS[".pdf"] = PDFChunker

    if DOCXExtractor is not None:
        EXTRACTORS[".docx"] = DOCXExtractor
        EXTRACTORS[".doc"] = DOCXExtractor
        CHUNKERS[".docx"] = DOCXChunker
        CHUNKERS[".doc"] = DOCXChunker

    if PPTXExtractor is not None:
        EXTRACTORS[".pptx"] = PPTXExtractor
        EXTRACTORS[".ppt"] = PPTXExtractor
        CHUNKERS[".pptx"] = PPTXChunker
        CHUNKERS[".ppt"] = PPTXChunker

    if ExcelExtractor is not None:
        for ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
            EXTRACTORS[ext] = ExcelExtractor
            CHUNKERS[ext] = ExcelChunker

    if CSVExtractor is not None:
        EXTRACTORS[".csv"] = CSVExtractor
        EXTRACTORS[".tsv"] = CSVExtractor
        CHUNKERS[".csv"] = ExcelChunker
        CHUNKERS[".tsv"] = ExcelChunker

    if HTMLExtractor is not None:
        EXTRACTORS[".html"] = HTMLExtractor
        EXTRACTORS[".htm"] = HTMLExtractor
        CHUNKERS[".html"] = HTMLChunker
        CHUNKERS[".htm"] = HTMLChunker

    # Data formats (JSON always available)
    EXTRACTORS[".json"] = JSONExtractor
    CHUNKERS[".json"] = TextChunker  # Use text chunker for data files

    if YAMLExtractor is not None:
        EXTRACTORS[".yaml"] = YAMLExtractor
        EXTRACTORS[".yml"] = YAMLExtractor
        CHUNKERS[".yaml"] = TextChunker
        CHUNKERS[".yml"] = TextChunker

    if XMLExtractor is not None:
        EXTRACTORS[".xml"] = XMLExtractor
        CHUNKERS[".xml"] = TextChunker

    # Email formats (EML always available via stdlib)
    EXTRACTORS[".eml"] = EMLExtractor
    CHUNKERS[".eml"] = TextChunker

    if MSGExtractor is not None:
        EXTRACTORS[".msg"] = MSGExtractor
        CHUNKERS[".msg"] = TextChunker

    # E-book and document formats
    if EPUBExtractor is not None:
        EXTRACTORS[".epub"] = EPUBExtractor
        CHUNKERS[".epub"] = TextChunker

    if RTFExtractor is not None:
        EXTRACTORS[".rtf"] = RTFExtractor
        CHUNKERS[".rtf"] = TextChunker


# Initialize on module load
_initialize_extractors()


def _validate_file_path(file_path: str) -> Path:
    """
    Validate and return absolute path.

    Args:
        file_path: Path to validate

    Returns:
        Validated Path object

    Raises:
        ValueError: If path is invalid or file does not exist
    """
    if not file_path:
        raise ValueError("File path is required")

    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise ValueError(f"File not found: {path}")

    if not path.is_file():
        raise ValueError(f"Not a file: {path}")

    return path


def _parse_from_base64(content_base64: str, filename: str) -> Tuple[Path, None]:
    """
    Decode base64 content and write to a temporary file.

    Args:
        content_base64: Base64-encoded file content
        filename: Filename with extension for format detection (e.g., 'report.pdf')

    Returns:
        Tuple of (temp_file_path, None) - second element reserved for future cleanup callback

    Raises:
        ValueError: If filename has no extension or base64 content is invalid
    """
    # Get extension from filename
    ext = Path(filename).suffix.lower()
    if not ext:
        raise ValueError(
            "filename must have an extension for format detection (e.g., 'document.pdf', 'data.xlsx')"
        )

    # Validate extension is supported
    if ext not in EXTRACTORS:
        raise ValueError(
            f"Unsupported file format: {ext}. "
            f"Supported formats: {', '.join(sorted(EXTRACTORS.keys()))}"
        )

    # Decode base64
    try:
        content_bytes = base64.b64decode(content_base64)
    except Exception as e:
        raise ValueError(f"Invalid base64 content: {e}")

    # Write to temp file with correct extension
    temp_file = tempfile.NamedTemporaryFile(
        suffix=ext,
        delete=False
    )
    try:
        temp_file.write(content_bytes)
        temp_file.close()
        return Path(temp_file.name), None
    except Exception as e:
        # Cleanup on error
        temp_file.close()
        Path(temp_file.name).unlink(missing_ok=True)
        raise ValueError(f"Failed to write temp file: {e}")


def _get_extractor_for_file(file_path: Path) -> Any:
    """
    Get appropriate extractor for file type.

    Args:
        file_path: Path to file

    Returns:
        Extractor instance

    Raises:
        ValueError: If file type is not supported
    """
    extension = file_path.suffix.lower()

    if extension not in EXTRACTORS:
        raise ValueError(
            f"Unsupported file format: {extension}. "
            f"Supported formats: {', '.join(sorted(EXTRACTORS.keys()))}"
        )

    return EXTRACTORS[extension]()


def _get_chunker_for_file(
    file_path: Path,
    target_size: int = 300,
    overlap: int = 50
) -> Any:
    """
    Get appropriate chunker for file type.

    Args:
        file_path: Path to file
        target_size: Target words per chunk
        overlap: Words to overlap

    Returns:
        Chunker instance
    """
    extension = file_path.suffix.lower()

    if extension not in CHUNKERS:
        raise ValueError(f"No chunker available for: {extension}")

    chunker_class = CHUNKERS[extension]
    return chunker_class(target_size=target_size, overlap=overlap)


def _extract_images_from_structure(
    structure: Optional[Dict[str, Any]],
    page_filter: Optional[int] = None,
    max_images: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Extract images from PDF structure.

    Args:
        structure: Document structure from extraction
        page_filter: If set, only return images from this page (1-indexed)
        max_images: Maximum number of images to return

    Returns:
        List of image dictionaries with page, base64, width, height
    """
    images = []

    if not structure or "pages" not in structure:
        return images

    for page in structure["pages"]:
        page_number = page.get("page_number", 0)

        # Filter by page if specified
        if page_filter is not None and page_number != page_filter:
            continue

        for item in page.get("content", []):
            if item.get("type") == "image":
                images.append({
                    "page": page_number,
                    "base64": item.get("content", ""),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                    "position": item.get("position", {})
                })

                # Check max_images limit
                if max_images is not None and len(images) >= max_images:
                    return images

    return images


def _remove_image_placeholders(text: str) -> str:
    """
    Remove [Image: WxH] placeholders from text.

    Args:
        text: Text containing image placeholders

    Returns:
        Text with placeholders removed
    """
    # Remove patterns like [Image: 800x600], [Image: 1024x768], etc.
    pattern = r'\[Image:\s*\d+x\d+\]\s*'
    return re.sub(pattern, '', text)


def _detect_mime_type(base64_data: str) -> str:
    """
    Detect MIME type from base64 data prefix.

    Args:
        base64_data: Base64 encoded image data

    Returns:
        MIME type string
    """
    if base64_data.startswith("/9j/"):
        return "image/jpeg"
    elif base64_data.startswith("R0lGOD"):
        return "image/gif"
    elif base64_data.startswith("iVBOR"):
        return "image/png"
    elif base64_data.startswith("UklGR"):
        return "image/webp"
    else:
        # Default to PNG
        return "image/png"


def _format_error_response(error: Exception) -> List[TextContent]:
    """
    Format error response as TextContent list.

    Args:
        error: Exception that occurred

    Returns:
        List with single TextContent containing error JSON
    """
    error_data = {
        "success": False,
        "error": str(error),
        "error_type": type(error).__name__
    }
    return [TextContent(type="text", text=json.dumps(error_data, indent=2))]


def _chunk_to_dict(chunk: Any) -> Dict[str, Any]:
    """
    Convert chunk to dictionary.

    Args:
        chunk: Chunk object

    Returns:
        Dictionary representation
    """
    return {
        "chunk_id": chunk.chunk_id,
        "text": chunk.text,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
        "word_count": chunk.word_count,
        "metadata": chunk.metadata,
        "keywords": getattr(chunk, "keywords", []),
        "section_name": getattr(chunk, "section_name", None),
        "section_type": getattr(chunk, "section_type", "text"),
    }


@server.list_tools()
async def list_tools() -> List[Tool]:
    """
    List available document parsing tools.

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


# ============================================================================
# MCP Prompts
# ============================================================================

@server.list_prompts()
async def list_prompts() -> List[Prompt]:
    """
    List available document analysis prompts.

    Returns:
        List of Prompt definitions
    """
    prompts = []
    for name, prompt_def in PROMPTS.items():
        arguments = [
            PromptArgument(
                name=arg["name"],
                description=arg.get("description", ""),
                required=arg.get("required", False)
            )
            for arg in prompt_def.get("arguments", [])
        ]
        prompts.append(
            Prompt(
                name=prompt_def["name"],
                description=prompt_def["description"],
                arguments=arguments
            )
        )
    return prompts


@server.get_prompt()
async def get_prompt(name: str, arguments: Dict[str, str] | None = None) -> GetPromptResult:
    """
    Get a specific prompt with document content filled in.

    Args:
        name: Prompt name
        arguments: Prompt arguments including file_path

    Returns:
        GetPromptResult with formatted prompt messages
    """
    if name not in PROMPTS:
        raise ValueError(f"Unknown prompt: {name}. Available: {list(PROMPTS.keys())}")

    arguments = arguments or {}

    # Get file_path (required for all document prompts)
    file_path_str = arguments.get("file_path")
    if not file_path_str:
        raise ValueError("file_path is required for document prompts")

    # Validate and parse document
    file_path = _validate_file_path(file_path_str)
    extractor = _get_extractor_for_file(file_path)
    raw_doc = extractor.extract(str(file_path))

    # Get document info
    doc_type = file_path.suffix.lower().lstrip('.')
    word_count = len(raw_doc.text.split())

    # Truncate very long documents for prompt context
    max_prompt_chars = 50000  # Reasonable limit for prompt context
    document_content = raw_doc.text
    if len(document_content) > max_prompt_chars:
        document_content = document_content[:max_prompt_chars] + f"\n\n[... truncated, {len(raw_doc.text) - max_prompt_chars} more characters ...]"

    # Format the prompt
    formatted_prompt = format_prompt(
        name=name,
        document_content=document_content,
        file_name=file_path.name,
        doc_type=doc_type,
        word_count=word_count,
        **{k: v for k, v in arguments.items() if k != "file_path"}
    )

    return GetPromptResult(
        description=f"Document analysis prompt: {PROMPTS[name]['description']}",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=formatted_prompt)
            )
        ]
    )


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent | ImageContent]:
    """
    Handle tool calls for document parsing.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent and ImageContent with results.
    """
    try:
        if name == "parse_document":
            return await _handle_parse_document(arguments)
        elif name == "parse_document_bytes":
            return await _handle_parse_document_bytes(arguments)
        elif name == "get_document_chunk":
            return await _handle_get_document_chunk(arguments)
        elif name == "get_document_images":
            return await _handle_get_document_images(arguments)
        elif name == "parse_document_chunked":
            return await _handle_parse_document_chunked(arguments)
        elif name == "extract_metadata":
            return await _handle_extract_metadata(arguments)
        elif name == "list_supported_formats":
            return await _handle_list_supported_formats(arguments)
        elif name == "batch_parse":
            return await _handle_batch_parse(arguments)
        else:
            return _format_error_response(ValueError(f"Unknown tool: {name}"))

    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return _format_error_response(e)


async def _handle_parse_document(arguments: Dict[str, Any]) -> List[TextContent | ImageContent]:
    """
    Handle parse_document tool call.

    Returns:
    - TextContent[0]: Plain extracted text (no JSON wrapping)
    - TextContent[1]: Metadata as JSON (or TOON format if output_format=toon)
    - ImageContent[]: Each image as separate ImageContent (if include_images=true)

    Args:
        arguments: Tool arguments

    Returns:
        List of TextContent and ImageContent
    """
    file_path_str = arguments.get("file_path")
    full_text = arguments.get("full_text", False)
    include_images = arguments.get("include_images", False)
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Parsing document: {file_path} (full_text={full_text}, include_images={include_images})")

    # Get extractor
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Clean text by removing image placeholders
    clean_text = _remove_image_placeholders(raw_doc.text)
    total_chars = len(clean_text)
    total_words = len(clean_text.split())
    extension = file_path.suffix.lower()

    # Get page/image count for PDFs
    page_count = None
    image_count = 0
    if extension == ".pdf" and raw_doc.structure:
        pages = raw_doc.structure.get("pages", [])
        page_count = len(pages)
        image_count = sum(
            1 for page in pages
            for item in page.get("content", [])
            if item.get("type") == "image"
        )

    # Determine text to return
    if full_text or total_chars <= DEFAULT_SUMMARY_CHARS:
        text_content = clean_text
        truncated = False
        continuation_offset = None
    else:
        text_content = clean_text[:DEFAULT_SUMMARY_CHARS]
        truncated = True
        continuation_offset = DEFAULT_SUMMARY_CHARS

    # Build response content list
    response_items: List[TextContent | ImageContent] = []

    # TOON format output
    if output_format == OUTPUT_FORMAT_TOON:
        toon_output = TOONFormatter.format_raw(
            file_path=str(file_path),
            text=text_content,
            metadata=raw_doc.metadata,
            doc_type=extension[1:] if extension else "unknown",
            total_chars=total_chars,
            total_words=total_words,
            page_count=page_count,
            image_count=image_count if image_count > 0 else None,
            truncated=truncated,
            continuation_offset=continuation_offset
        )
        response_items.append(TextContent(type="text", text=toon_output))

    # JSON format output (default)
    else:
        # TextContent[0]: Plain extracted text
        response_items.append(TextContent(type="text", text=text_content))

        # Build metadata
        metadata_dict: Dict[str, Any] = {
            "file_path": str(file_path),
            "total_characters": total_chars,
            "total_words": total_words,
            "document_metadata": raw_doc.metadata,
        }

        # Add continuation hint if applicable
        if truncated:
            metadata_dict["continuation_hint"] = (
                f"Document has {total_chars - DEFAULT_SUMMARY_CHARS} more characters. "
                f"Use get_document_chunk(file_path, offset={DEFAULT_SUMMARY_CHARS}) for more."
            )

        # Add page/image count for PDFs
        if page_count is not None:
            metadata_dict["page_count"] = page_count
            metadata_dict["image_count"] = image_count
            if image_count > 0 and not include_images:
                metadata_dict["images_hint"] = (
                    f"Document contains {image_count} images. "
                    f"Use get_document_images(file_path) to retrieve them."
                )

        # TextContent[1]: Metadata as JSON
        response_items.append(TextContent(type="text", text=json.dumps(metadata_dict, indent=2, default=str)))

    # Add images if requested (same for both formats)
    if include_images:
        images = _extract_images_from_structure(raw_doc.structure, max_images=DEFAULT_MAX_IMAGES)

        for idx, img in enumerate(images):
            page_num = img.get("page", 0)
            width = img.get("width", 0)
            height = img.get("height", 0)
            position = img.get("position", {})

            # Add image position info as TextContent
            if output_format == OUTPUT_FORMAT_TOON:
                response_items.append(TextContent(
                    type="text",
                    text=f"img:{idx + 1}|p:{page_num}|{width}x{height}"
                ))
            else:
                position_info = {
                    "image_index": idx + 1,
                    "page": page_num,
                    "dimensions": f"{width}x{height}",
                    "position": position
                }
                response_items.append(TextContent(
                    type="text",
                    text=f"Image {idx + 1} info: {json.dumps(position_info)}"
                ))

            # Add actual image as ImageContent
            base64_data = img.get("base64", "")
            if base64_data:
                mime_type = _detect_mime_type(base64_data)
                response_items.append(ImageContent(
                    type="image",
                    data=base64_data,
                    mimeType=mime_type
                ))

        # Note if there are more images
        total_images = len(_extract_images_from_structure(raw_doc.structure))
        if total_images > len(images):
            if output_format == OUTPUT_FORMAT_TOON:
                response_items.append(TextContent(
                    type="text",
                    text=f"~{len(images)}/{total_images}imgs|use:get_document_images"
                ))
            else:
                response_items.append(TextContent(
                    type="text",
                    text=f"Showing {len(images)} of {total_images} images. Use get_document_images for more."
                ))

    return response_items


async def _handle_parse_document_bytes(arguments: Dict[str, Any]) -> List[TextContent | ImageContent]:
    """
    Handle parse_document_bytes tool call for base64-encoded documents.

    Decodes base64 content to a temp file, parses it using existing infrastructure,
    then cleans up the temp file.

    Args:
        arguments: Tool arguments including content_base64 and filename

    Returns:
        List of TextContent and ImageContent (same as parse_document)
    """
    content_base64 = arguments.get("content_base64")
    filename = arguments.get("filename")

    if not content_base64:
        raise ValueError("content_base64 is required")
    if not filename:
        raise ValueError("filename is required (e.g., 'document.pdf', 'data.xlsx')")

    logger.info(f"Parsing document from base64: {filename}")

    # Create temp file from base64
    temp_path, _ = _parse_from_base64(content_base64, filename)

    try:
        # Reuse existing parse logic by building modified arguments
        modified_args = {
            "file_path": str(temp_path),
            "full_text": arguments.get("full_text", False),
            "include_images": arguments.get("include_images", False),
            "output_format": arguments.get("output_format", DEFAULT_OUTPUT_FORMAT),
        }

        # Use existing handler
        result = await _handle_parse_document(modified_args)

        # Update file_path in response to show original filename instead of temp path
        # Handle both the temp path and any symlinked variants (e.g., /var vs /private/var on macOS)
        temp_path_str = str(temp_path)
        temp_path_resolved = str(temp_path.resolve())
        temp_filename = temp_path.name  # Just the filename like "tmpXXXXX.json"

        updated_result = []
        for item in result:
            if isinstance(item, TextContent):
                # Replace temp path with original filename in text
                updated_text = item.text
                # Replace full paths first (more specific)
                updated_text = updated_text.replace(temp_path_resolved, filename)
                updated_text = updated_text.replace(temp_path_str, filename)
                # Replace just the temp filename (for TOON format which uses basename)
                updated_text = updated_text.replace(temp_filename, filename)
                updated_result.append(TextContent(type="text", text=updated_text))
            else:
                updated_result.append(item)

        return updated_result

    finally:
        # Always cleanup temp file
        temp_path.unlink(missing_ok=True)
        logger.debug(f"Cleaned up temp file: {temp_path}")


async def _handle_get_document_chunk(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle get_document_chunk tool call for paginated content retrieval.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing the chunk and metadata
    """
    file_path_str = arguments.get("file_path")
    offset = arguments.get("offset", 0)
    limit = arguments.get("limit", DEFAULT_CHUNK_LIMIT)
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Getting document chunk: {file_path} (offset={offset}, limit={limit})")

    # Get extractor
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Clean text
    clean_text = _remove_image_placeholders(raw_doc.text)
    total_chars = len(clean_text)

    # Validate offset
    if offset >= total_chars:
        return [
            TextContent(type="text", text=""),
            TextContent(type="text", text=json.dumps({
                "file_path": str(file_path),
                "offset": offset,
                "limit": limit,
                "returned_chars": 0,
                "total_chars": total_chars,
                "remaining_chars": 0,
                "has_more": False,
                "error": f"Offset {offset} exceeds document length {total_chars}"
            }, indent=2))
        ]

    # Extract chunk
    end_pos = min(offset + limit, total_chars)
    chunk_text = clean_text[offset:end_pos]
    remaining = total_chars - end_pos
    has_more = remaining > 0

    # TOON format output
    if output_format == OUTPUT_FORMAT_TOON:
        toon_output = TOONFormatter.format_chunk_response(
            file_path=str(file_path),
            text=chunk_text,
            offset=offset,
            limit=limit,
            total_chars=total_chars,
            has_more=has_more
        )
        return [TextContent(type="text", text=toon_output)]

    # JSON format output (default)
    response_items: List[TextContent] = []

    # TextContent[0]: The text chunk
    response_items.append(TextContent(type="text", text=chunk_text))

    # TextContent[1]: Metadata about the chunk
    chunk_metadata = {
        "file_path": str(file_path),
        "offset": offset,
        "limit": limit,
        "returned_chars": len(chunk_text),
        "total_chars": total_chars,
        "remaining_chars": remaining,
        "has_more": has_more
    }

    if has_more:
        chunk_metadata["next_chunk_hint"] = (
            f"Use get_document_chunk(file_path, offset={end_pos}, limit={limit}) "
            f"to get next {min(remaining, limit)} of {remaining} remaining characters."
        )

    response_items.append(TextContent(type="text", text=json.dumps(chunk_metadata, indent=2)))

    return response_items


async def _handle_get_document_images(arguments: Dict[str, Any]) -> List[TextContent | ImageContent]:
    """
    Handle get_document_images tool call for on-demand image retrieval.

    Args:
        arguments: Tool arguments

    Returns:
        List of TextContent (position info) and ImageContent (actual images)
    """
    file_path_str = arguments.get("file_path")
    page_filter = arguments.get("page")  # Optional, 1-indexed
    max_images = arguments.get("max_images", DEFAULT_MAX_IMAGES)

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Getting document images: {file_path} (page={page_filter}, max={max_images})")

    # Get extractor
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Get all images first to count total
    all_images = _extract_images_from_structure(raw_doc.structure)
    total_images = len(all_images)

    if total_images == 0:
        return [TextContent(
            type="text",
            text=json.dumps({
                "file_path": str(file_path),
                "total_images": 0,
                "returned_images": 0,
                "message": "No images found in document"
            }, indent=2)
        )]

    # Get filtered images
    images = _extract_images_from_structure(
        raw_doc.structure,
        page_filter=page_filter,
        max_images=max_images
    )

    # Build response
    response_items: List[TextContent | ImageContent] = []

    # Summary metadata
    summary = {
        "file_path": str(file_path),
        "total_images_in_document": total_images,
        "returned_images": len(images),
        "page_filter": page_filter,
        "max_images": max_images
    }

    if len(images) < total_images:
        if page_filter:
            summary["note"] = f"Showing images from page {page_filter} only"
        else:
            summary["note"] = f"Showing first {len(images)} of {total_images} images"

    response_items.append(TextContent(type="text", text=json.dumps(summary, indent=2)))

    # Add each image with position info
    for idx, img in enumerate(images):
        page_num = img.get("page", 0)
        width = img.get("width", 0)
        height = img.get("height", 0)
        position = img.get("position", {})

        # Position info as TextContent
        position_info = {
            "image_index": idx + 1,
            "page": page_num,
            "dimensions": f"{width}x{height}",
            "position": position
        }
        response_items.append(TextContent(
            type="text",
            text=f"Image {idx + 1}: {json.dumps(position_info)}"
        ))

        # Actual image as ImageContent
        base64_data = img.get("base64", "")
        if base64_data:
            mime_type = _detect_mime_type(base64_data)
            response_items.append(ImageContent(
                type="image",
                data=base64_data,
                mimeType=mime_type
            ))

    return response_items


async def _handle_parse_document_chunked(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle parse_document_chunked tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing chunked document result as JSON or TOON
    """
    file_path_str = arguments.get("file_path")
    chunk_size = arguments.get("chunk_size", 1000)
    overlap = arguments.get("overlap", 100)
    chunking_strategy = arguments.get("chunking_strategy", "auto")
    embedding_model = arguments.get("embedding_model", "fast")
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Parsing document chunked: {file_path} (size={chunk_size}, overlap={overlap}, strategy={chunking_strategy})")

    # Get extractor
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Get chunker based on strategy
    if chunking_strategy == "semantic":
        # Use semantic chunker with embeddings
        if SemanticChunker is None:
            raise ValueError(
                "Semantic chunking requires sentence-transformers. "
                "Install with: pip install sentence-transformers"
            )
        chunker = SemanticChunker(
            target_size=chunk_size,
            overlap=overlap,
            model=embedding_model
        )
    elif chunking_strategy == "fixed":
        # Simple fixed-size chunking using TextChunker
        chunker = TextChunker(target_size=chunk_size, overlap=overlap)
    elif chunking_strategy == "recursive":
        # Recursive paragraph/sentence chunking
        chunker = TextChunker(target_size=chunk_size, overlap=overlap)
    else:
        # Auto: use format-aware chunker
        chunker = _get_chunker_for_file(file_path, target_size=chunk_size, overlap=overlap)

    # Chunk document
    chunks = chunker.chunk(raw_doc)

    # Calculate statistics
    total_words = sum(chunk.word_count for chunk in chunks)
    total_chars = len(raw_doc.text)
    extension = file_path.suffix.lower()

    # TOON format output
    if output_format == OUTPUT_FORMAT_TOON:
        lines = []

        # Document header
        parts = [
            f"d:{file_path.name}",
            f"t:{extension[1:] if extension else 'unknown'}",
            f"w:{total_words}",
            f"c:{total_chars}",
            f"n:{len(chunks)}"
        ]
        lines.append("|".join(parts))

        # Metadata
        meta_parts = []
        for key in ["author", "title"]:
            if key in raw_doc.metadata and raw_doc.metadata[key]:
                val = str(raw_doc.metadata[key]).replace(",", "\\,")
                meta_parts.append(f"{key}={val}")
        if meta_parts:
            lines.append(f"m:{','.join(meta_parts)}")

        # Chunks
        for chunk in chunks:
            lines.append("---")
            # Chunk header
            section_name = getattr(chunk, "section_name", "") or ""
            section_type = getattr(chunk, "section_type", "text") or "text"
            lines.append(f"{chunk.chunk_id}|{chunk.start_char}-{chunk.end_char}|{section_type}|{section_name}")
            # Chunk text
            lines.append(chunk.text)
            # Keywords
            keywords = getattr(chunk, "keywords", [])
            if keywords:
                lines.append(f"k:{','.join(keywords[:10])}")

        return [TextContent(type="text", text="\n".join(lines))]

    # JSON format output (default)
    response: Dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunking_strategy": chunking_strategy,
        "total_chunks": len(chunks),
        "chunks": [_chunk_to_dict(chunk) for chunk in chunks],
        "metadata": raw_doc.metadata,
    }

    response["statistics"] = {
        "total_words": total_words,
        "average_chunk_words": total_words // len(chunks) if chunks else 0,
        "total_characters": total_chars,
    }

    if chunking_strategy == "semantic":
        response["embedding_model"] = embedding_model

    return [TextContent(type="text", text=json.dumps(response, indent=2, default=str))]


async def _handle_extract_metadata(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle extract_metadata tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing document metadata as JSON or TOON
    """
    file_path_str = arguments.get("file_path")
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Extracting metadata: {file_path}")

    # Get extractor
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document (we only need metadata)
    raw_doc = extractor.extract(str(file_path))

    # Get format-specific info
    extension = file_path.suffix.lower()
    text_length = len(raw_doc.text)
    page_count = None

    if extension == ".pdf" and raw_doc.structure:
        pages = raw_doc.structure.get("pages", [])
        page_count = len(pages)

    # TOON format output
    if output_format == OUTPUT_FORMAT_TOON:
        toon_output = TOONFormatter.format_metadata_only(
            file_path=str(file_path),
            metadata=raw_doc.metadata,
            doc_type=extension[1:] if extension else "unknown",
            total_chars=text_length,
            page_count=page_count
        )
        return [TextContent(type="text", text=toon_output)]

    # JSON format output (default)
    response: Dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "metadata": raw_doc.metadata,
        "document_info": {
            "text_length": text_length,
            "has_structure": raw_doc.structure is not None,
        }
    }

    if extension == ".pdf" and raw_doc.structure:
        pages = raw_doc.structure.get("pages", [])
        image_count = sum(
            1 for page in pages
            for item in page.get("content", [])
            if item.get("type") == "image"
        )
        response["document_info"]["page_count"] = len(pages)
        response["document_info"]["image_count"] = image_count

    return [TextContent(type="text", text=json.dumps(response, indent=2, default=str))]


async def _handle_list_supported_formats(_arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle list_supported_formats tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing supported formats as JSON
    """
    # Build format list with availability status
    formats = []

    for ext, description in sorted(FORMAT_DESCRIPTIONS.items()):
        is_available = ext in EXTRACTORS
        formats.append({
            "extension": ext,
            "description": description,
            "available": is_available,
            "reason": None if is_available else "Required dependencies not installed"
        })

    # Group by category
    categories = {
        "documents": [".pdf", ".docx", ".doc", ".pptx", ".ppt"],
        "spreadsheets": [".xlsx", ".xlsm", ".xltx", ".xltm", ".csv", ".tsv"],
        "web": [".html", ".htm", ".md", ".markdown"],
        "text": [".txt", ".text", ".log"],
        "code": [".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".go", ".rs"]
    }

    categorized = {}
    for category, extensions in categories.items():
        categorized[category] = [
            f for f in formats if f["extension"] in extensions
        ]

    result = {
        "success": True,
        "total_formats": len(FORMAT_DESCRIPTIONS),
        "available_formats": len(EXTRACTORS),
        "formats": formats,
        "by_category": categorized
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_batch_parse(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle batch_parse tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing batch parsing results as JSON
    """
    file_paths = arguments.get("file_paths", [])
    options = arguments.get("options", {})

    include_images = options.get("include_images", False)
    continue_on_error = options.get("continue_on_error", True)

    if not file_paths:
        raise ValueError("file_paths array is required and cannot be empty")

    logger.info(f"Batch parsing {len(file_paths)} documents")

    results = []
    successful = 0
    failed = 0

    for file_path_str in file_paths:
        try:
            # Validate path
            file_path = _validate_file_path(file_path_str)

            # Get extractor
            extractor = _get_extractor_for_file(file_path)

            # Extract raw document
            raw_doc = extractor.extract(str(file_path))

            # Clean text
            clean_text = _remove_image_placeholders(raw_doc.text)

            # Build summary result
            doc_result: Dict[str, Any] = {
                "success": True,
                "file_path": str(file_path),
                "text_preview": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
                "total_characters": len(clean_text),
                "total_words": len(clean_text.split()),
                "metadata": raw_doc.metadata
            }

            # Add image info if requested
            if include_images:
                images = _extract_images_from_structure(raw_doc.structure)
                doc_result["image_count"] = len(images)

            results.append(doc_result)
            successful += 1

        except Exception as e:
            logger.warning(f"Failed to parse {file_path_str}: {e}")

            if continue_on_error:
                results.append({
                    "success": False,
                    "file_path": file_path_str,
                    "error": str(e),
                    "error_type": type(e).__name__
                })
                failed += 1
            else:
                raise

    result = {
        "success": True,
        "total_files": len(file_paths),
        "successful": successful,
        "failed": failed,
        "results": results
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main() -> None:
    """Main entry point for the MCP server."""
    logger.info("Starting Document Parser MCP Server")
    logger.info(f"Available formats: {', '.join(sorted(EXTRACTORS.keys()))}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
