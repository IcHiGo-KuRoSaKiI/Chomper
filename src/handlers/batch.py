"""
Batch parsing handler for Chomper.
"""
import json
import logging
from typing import Any

from mcp.types import TextContent

from src.server.helpers import (
    extract_images_from_structure,
    get_extractor_for_file,
    remove_image_placeholders,
    validate_file_path,
)

logger = logging.getLogger("chomper")


async def handle_batch_parse(arguments: dict[str, Any]) -> list[TextContent]:
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
            file_path = validate_file_path(file_path_str)

            # Get extractor
            extractor = get_extractor_for_file(file_path)

            # Extract raw document
            raw_doc = extractor.extract(str(file_path))

            # Clean text
            clean_text = remove_image_placeholders(raw_doc.text)

            # Build summary result
            doc_result: dict[str, Any] = {
                "success": True,
                "file_path": str(file_path),
                "text_preview": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
                "total_characters": len(clean_text),
                "total_words": len(clean_text.split()),
                "metadata": raw_doc.metadata
            }

            # Add image info if requested
            if include_images:
                images = extract_images_from_structure(raw_doc.structure)
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
