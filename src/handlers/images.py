"""
Image document handler for Chomper.
"""
import json
import logging
from typing import Any

from mcp.types import ImageContent, TextContent

from src.server.config import DEFAULT_MAX_IMAGES
from src.server.helpers import (
    detect_mime_type,
    extract_images_from_structure,
    get_extractor_for_file,
    validate_file_path,
)

logger = logging.getLogger("chomper")


async def handle_get_document_images(arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
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
    file_path = validate_file_path(file_path_str)

    logger.info(f"Getting document images: {file_path} (page={page_filter}, max={max_images})")

    # Get extractor
    extractor = get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Get all images first to count total
    all_images = extract_images_from_structure(raw_doc.structure)
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
    images = extract_images_from_structure(
        raw_doc.structure,
        page_filter=page_filter,
        max_images=max_images
    )

    # Build response
    response_items: list[TextContent | ImageContent] = []

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
            mime_type = detect_mime_type(base64_data)
            response_items.append(ImageContent(
                type="image",
                data=base64_data,
                mimeType=mime_type
            ))

    return response_items
