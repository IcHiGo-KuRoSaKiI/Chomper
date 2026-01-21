#!/usr/bin/env python3
"""
Production-ready MCP Server for Document Parsing.

This server exposes the parsers library functionality via the Model Context Protocol,
enabling AI systems to parse and analyze documents across multiple formats.

Features:
- Full document parsing with text, metadata, and image extraction
- Chunked parsing with configurable size and overlap
- Metadata-only extraction for quick document analysis
- Batch processing for multiple files
- Support for PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, and code files

Usage:
    python server.py

    Or via MCP client configuration:
    {
        "mcpServers": {
            "document-parser": {
                "command": "python",
                "args": ["/path/to/server.py"]
            }
        }
    }
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    ImageContent,
    Tool,
)

# Add parsers to path if needed
sys.path.insert(0, str(Path(__file__).parent))

from src import DocumentPipeline, SimpleFormatter
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
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("document-parser-mcp")

# Initialize MCP server
server = Server("document-parser")

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


def _extract_images_from_structure(structure: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract images from PDF structure.

    Args:
        structure: Document structure from extraction

    Returns:
        List of image dictionaries with page, base64, width, height
    """
    images = []

    if not structure or "pages" not in structure:
        return images

    for page in structure["pages"]:
        page_number = page.get("page_number", 0)

        for item in page.get("content", []):
            if item.get("type") == "image":
                images.append({
                    "page": page_number,
                    "base64": item.get("content", ""),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                    "position": item.get("position", {})
                })

    return images


def _format_error_response(error: Exception) -> Dict[str, Any]:
    """
    Format error response.

    Args:
        error: Exception that occurred

    Returns:
        Error response dictionary
    """
    return {
        "success": False,
        "error": str(error),
        "error_type": type(error).__name__
    }


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
            description=(
                "Parse a document and extract text, metadata, and images. "
                "Supports PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, and code files. "
                "For PDFs, images are extracted and returned as base64-encoded data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the document file"
                    },
                    "options": {
                        "type": "object",
                        "description": "Optional parsing options",
                        "properties": {
                            "include_images": {
                                "type": "boolean",
                                "description": "Include extracted images (default: true)",
                                "default": True
                            },
                            "chunk_size": {
                                "type": "integer",
                                "description": "Target words per chunk (default: 300)",
                                "default": 300
                            },
                            "output_format": {
                                "type": "string",
                                "description": "Output format: 'full' or 'summary' (default: 'full')",
                                "enum": ["full", "summary"],
                                "default": "full"
                            }
                        }
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="parse_document_chunked",
            description=(
                "Parse a document into semantic chunks with configurable size and overlap. "
                "Ideal for processing large documents for RAG or embedding systems."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the document file"
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": "Target words per chunk (default: 1000)",
                        "default": 1000
                    },
                    "overlap": {
                        "type": "integer",
                        "description": "Words to overlap between chunks (default: 100)",
                        "default": 100
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="extract_metadata",
            description=(
                "Extract only metadata from a document without full processing. "
                "Useful for quick document analysis, file type detection, and previews."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the document file"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="list_supported_formats",
            description=(
                "List all supported document formats with their descriptions. "
                "Returns available file extensions and format details."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="batch_parse",
            description=(
                "Parse multiple documents in a single request. "
                "Efficiently processes batches of files with shared options."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of absolute paths to document files"
                    },
                    "options": {
                        "type": "object",
                        "description": "Optional parsing options applied to all files",
                        "properties": {
                            "include_images": {
                                "type": "boolean",
                                "description": "Include extracted images (default: false for batch)",
                                "default": False
                            },
                            "chunk_size": {
                                "type": "integer",
                                "description": "Target words per chunk (default: 300)",
                                "default": 300
                            },
                            "continue_on_error": {
                                "type": "boolean",
                                "description": "Continue processing if a file fails (default: true)",
                                "default": True
                            }
                        }
                    }
                },
                "required": ["file_paths"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent | ImageContent]:
    """
    Handle tool calls for document parsing.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent and ImageContent with results.
        Images are returned as separate ImageContent items that Claude can analyze directly.
    """
    try:
        if name == "parse_document":
            result = await _handle_parse_document(arguments)
        elif name == "parse_document_chunked":
            result = await _handle_parse_document_chunked(arguments)
        elif name == "extract_metadata":
            result = await _handle_extract_metadata(arguments)
        elif name == "list_supported_formats":
            result = await _handle_list_supported_formats(arguments)
        elif name == "batch_parse":
            result = await _handle_batch_parse(arguments)
        else:
            result = _format_error_response(ValueError(f"Unknown tool: {name}"))

        # Build response with TextContent and optional ImageContent
        response_items: List[TextContent | ImageContent] = []

        # Extract images for direct Claude analysis (parse_document only)
        images_for_claude = []
        if name == "parse_document" and result.get("success") and result.get("images"):
            images_for_claude = result.get("images", [])
            # Create image reference in JSON (without base64 to reduce size)
            result["images"] = [
                {
                    "page": img.get("page"),
                    "width": img.get("width"),
                    "height": img.get("height"),
                    "position": img.get("position"),
                    "content_index": idx + 1  # Reference to ImageContent index
                }
                for idx, img in enumerate(images_for_claude)
            ]
            result["image_note"] = "Images are returned as separate ImageContent items for direct analysis"

        # Add main JSON response
        response_items.append(TextContent(
            type="text",
            text=json.dumps(result, indent=2, default=str)
        ))

        # Add images as ImageContent for Claude to analyze directly
        for img in images_for_claude:
            base64_data = img.get("base64", "")
            if base64_data:
                # Determine MIME type (default to PNG)
                mime_type = "image/png"
                if base64_data.startswith("/9j/"):
                    mime_type = "image/jpeg"
                elif base64_data.startswith("R0lGOD"):
                    mime_type = "image/gif"

                response_items.append(ImageContent(
                    type="image",
                    data=base64_data,
                    mimeType=mime_type,
                ))

        return response_items

    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(
            type="text",
            text=json.dumps(_format_error_response(e), indent=2)
        )]


async def _handle_parse_document(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle parse_document tool call.

    Args:
        arguments: Tool arguments

    Returns:
        Parsed document result
    """
    file_path_str = arguments.get("file_path")
    options = arguments.get("options", {})

    include_images = options.get("include_images", True)
    _chunk_size = options.get("chunk_size", 300)  # Reserved for future custom chunking
    output_format = options.get("output_format", "full")

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Parsing document: {file_path}")

    # Create pipeline with custom chunk size
    pipeline = DocumentPipeline(
        formatter=SimpleFormatter(include_metadata=True),
        skip_enrichment_for_code=True
    )

    # Check if supported
    if not pipeline.is_supported(str(file_path)):
        raise ValueError(f"Unsupported file format: {file_path.suffix}")

    # Process document
    result = pipeline.process(str(file_path))

    # Extract text from raw document for full text
    extractor = _get_extractor_for_file(file_path)
    raw_doc = extractor.extract(str(file_path))

    # Build response
    response: Dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "text": raw_doc.text,
        "metadata": raw_doc.metadata,
    }

    # Add images if requested and available (PDF)
    if include_images:
        images = _extract_images_from_structure(raw_doc.structure)
        if images:
            response["images"] = images
            response["image_count"] = len(images)

    # Add chunks
    if output_format == "full":
        response["chunks"] = result.get("chunks", [])
        response["total_chunks"] = result.get("total_chunks", 0)
        response["total_words"] = result.get("total_words", 0)
    else:
        # Summary mode - just chunk count and metadata
        response["total_chunks"] = result.get("total_chunks", 0)
        response["total_words"] = result.get("total_words", 0)
        response["chunk_preview"] = result.get("chunks", [])[:3] if result.get("chunks") else []

    # Add pagination info for large documents
    if len(raw_doc.text) > 100000:
        response["pagination"] = {
            "total_characters": len(raw_doc.text),
            "is_large_document": True,
            "recommendation": "Consider using parse_document_chunked for better handling"
        }

    return response


async def _handle_parse_document_chunked(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle parse_document_chunked tool call.

    Args:
        arguments: Tool arguments

    Returns:
        Chunked document result
    """
    file_path_str = arguments.get("file_path")
    chunk_size = arguments.get("chunk_size", 1000)
    overlap = arguments.get("overlap", 100)

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Parsing document chunked: {file_path} (size={chunk_size}, overlap={overlap})")

    # Get extractor and chunker
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Get custom chunker with specified parameters
    chunker = _get_chunker_for_file(file_path, target_size=chunk_size, overlap=overlap)

    # Chunk document
    chunks = chunker.chunk(raw_doc)

    # Build response
    response: Dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "total_chunks": len(chunks),
        "chunks": [_chunk_to_dict(chunk) for chunk in chunks],
        "metadata": raw_doc.metadata,
    }

    # Add statistics
    total_words = sum(chunk.word_count for chunk in chunks)
    response["statistics"] = {
        "total_words": total_words,
        "average_chunk_words": total_words // len(chunks) if chunks else 0,
        "total_characters": len(raw_doc.text),
    }

    return response


async def _handle_extract_metadata(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle extract_metadata tool call.

    Args:
        arguments: Tool arguments

    Returns:
        Document metadata
    """
    file_path_str = arguments.get("file_path")

    # Validate path
    file_path = _validate_file_path(file_path_str)

    logger.info(f"Extracting metadata: {file_path}")

    # Get extractor
    extractor = _get_extractor_for_file(file_path)

    # Extract raw document (we only need metadata)
    raw_doc = extractor.extract(str(file_path))

    # Build response
    response: Dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "metadata": raw_doc.metadata,
        "document_info": {
            "text_length": len(raw_doc.text),
            "has_structure": raw_doc.structure is not None,
        }
    }

    # Add format-specific info
    extension = file_path.suffix.lower()

    if extension == ".pdf" and raw_doc.structure:
        pages = raw_doc.structure.get("pages", [])
        image_count = sum(
            1 for page in pages
            for item in page.get("content", [])
            if item.get("type") == "image"
        )
        response["document_info"]["page_count"] = len(pages)
        response["document_info"]["image_count"] = image_count

    return response


async def _handle_list_supported_formats(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle list_supported_formats tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List of supported formats
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

    return {
        "success": True,
        "total_formats": len(FORMAT_DESCRIPTIONS),
        "available_formats": len(EXTRACTORS),
        "formats": formats,
        "by_category": categorized
    }


async def _handle_batch_parse(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle batch_parse tool call.

    Args:
        arguments: Tool arguments

    Returns:
        Batch parsing results
    """
    file_paths = arguments.get("file_paths", [])
    options = arguments.get("options", {})

    include_images = options.get("include_images", False)
    chunk_size = options.get("chunk_size", 300)
    continue_on_error = options.get("continue_on_error", True)

    if not file_paths:
        raise ValueError("file_paths array is required and cannot be empty")

    logger.info(f"Batch parsing {len(file_paths)} documents")

    results = []
    successful = 0
    failed = 0

    for file_path_str in file_paths:
        try:
            # Parse each document
            doc_result = await _handle_parse_document({
                "file_path": file_path_str,
                "options": {
                    "include_images": include_images,
                    "chunk_size": chunk_size,
                    "output_format": "summary"  # Use summary for batch
                }
            })

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

    return {
        "success": True,
        "total_files": len(file_paths),
        "successful": successful,
        "failed": failed,
        "results": results
    }


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
