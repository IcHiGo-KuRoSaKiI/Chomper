"""
Image document handler for Chomper.
"""
import json
import logging
from typing import Any

from mcp.types import ImageContent, TextContent

from src.server.cache import serialized_for
from src.server.config import DEFAULT_MAX_IMAGES
from src.server.documents import load_document
from src.server.helpers import (
    count_images_in_structure,
    detect_mime_type,
    extract_images_from_structure,
    run_blocking,
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
    return await run_blocking(_get_document_images_sync, arguments)


def _get_document_images_sync(arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    from src.extractors.image_utils import DEFAULT_MAX_DIMENSION

    file_path_str = arguments.get("file_path")
    page_filter = arguments.get("page")  # Optional, 1-indexed
    image_id = arguments.get("image_id")
    max_images = arguments.get("max_images", DEFAULT_MAX_IMAGES)
    max_dimension = arguments.get("max_dimension", DEFAULT_MAX_DIMENSION)
    if not isinstance(max_images, int) or max_images < 1:
        raise ValueError("max_images must be a positive integer")
    if not isinstance(max_dimension, int) or max_dimension < 0:
        raise ValueError("max_dimension must be 0 (full size) or a positive integer")

    # Validate path
    file_path = validate_file_path(file_path_str)

    logger.info(
        f"Getting document images: {file_path} "
        f"(page={page_filter}, id={image_id}, max={max_images})"
    )

    # Extract raw document (cached for unchanged files)
    raw_doc = load_document(file_path)

    # Count without decoding anything; only returned images are encoded.
    total_images = count_images_in_structure(raw_doc.structure)

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

    with serialized_for(file_path):  # PDF images are read with PyMuPDF
        images = extract_images_from_structure(
            raw_doc.structure,
            page_filter=page_filter,
            max_images=max_images,
            max_dimension=max_dimension or None,
            image_id=image_id,
        )
    if image_id is not None and not images:
        raise ValueError(f"No image with id '{image_id}' in {file_path.name}")

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

    if image_id is None and len(images) < total_images:
        if page_filter:
            summary["note"] = f"Showing images from page {page_filter} only"
        else:
            summary["note"] = (
                f"Showing first {len(images)} of {total_images} images. "
                "Use page, image_id or a larger max_images for others."
            )

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
            "id": img.get("id"),
            "page": page_num,
            "dimensions": f"{width}x{height}",
            "position": position
        }
        if (img.get("original_width"), img.get("original_height")) != (width, height):
            position_info["original_dimensions"] = (
                f"{img.get('original_width')}x{img.get('original_height')}"
            )
        if img.get("alt"):
            position_info["alt"] = img["alt"]
        response_items.append(TextContent(
            type="text",
            text=f"Image {idx + 1}: {json.dumps(position_info)}"
        ))

        # Actual image as ImageContent
        base64_data = img.get("base64", "")
        if base64_data:
            mime_type = img.get("mime_type") or detect_mime_type(base64_data)
            response_items.append(ImageContent(
                type="image",
                data=base64_data,
                mimeType=mime_type
            ))

    return response_items
