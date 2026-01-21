"""
Metadata handlers for Chomper.
"""
import json
import logging
from typing import Any, Dict, List

from mcp.types import TextContent

from src.formatters.toon_formatter import TOONFormatter
from src.server.config import (
    OUTPUT_FORMAT_TOON,
    DEFAULT_OUTPUT_FORMAT,
    FORMAT_DESCRIPTIONS,
    EXTRACTORS,
)
from src.server.helpers import (
    validate_file_path,
    get_extractor_for_file,
)

logger = logging.getLogger("chomper")


async def handle_extract_metadata(arguments: Dict[str, Any]) -> List[TextContent]:
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
    file_path = validate_file_path(file_path_str)

    logger.info(f"Extracting metadata: {file_path}")

    # Get extractor
    extractor = get_extractor_for_file(file_path)

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


async def handle_list_supported_formats(_arguments: Dict[str, Any]) -> List[TextContent]:
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
