"""
Metadata handlers for Chomper.
"""
import json
import logging
from typing import Any

from mcp.types import TextContent

from src.formatters.toon_formatter import TOONFormatter
from src.server.config import (
    DEFAULT_OUTPUT_FORMAT,
    FORMAT_DESCRIPTIONS,
    OUTPUT_FORMAT_TOON,
    describe_formats,
)
from src.server.documents import load_document
from src.server.helpers import (
    count_images_in_structure,
    run_blocking,
    validate_file_path,
)

logger = logging.getLogger("chomper")


async def handle_extract_metadata(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Handle extract_metadata tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing document metadata as JSON or TOON
    """
    return await run_blocking(_extract_metadata_sync, arguments)


def _extract_metadata_sync(arguments: dict[str, Any]) -> list[TextContent]:
    file_path_str = arguments.get("file_path")
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = validate_file_path(file_path_str)

    logger.info(f"Extracting metadata: {file_path}")

    # Extract raw document (cached: free after parse_document on the same file)
    raw_doc = load_document(file_path)

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
    response: dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "metadata": raw_doc.metadata,
        "document_info": {
            "text_length": text_length,
            "has_structure": raw_doc.structure is not None,
        }
    }

    if page_count is not None:
        response["document_info"]["page_count"] = page_count
    response["document_info"]["image_count"] = count_images_in_structure(raw_doc.structure)

    return [TextContent(type="text", text=json.dumps(response, indent=2, default=str))]


async def handle_list_supported_formats(_arguments: dict[str, Any]) -> list[TextContent]:
    """
    Handle list_supported_formats tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing supported formats as JSON
    """
    # Availability resolves each extractor (importing it), so do it off the loop.
    formats = await run_blocking(describe_formats)

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
        "available_formats": sum(1 for f in formats if f["available"]),
        "formats": formats,
        "by_category": categorized
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]
