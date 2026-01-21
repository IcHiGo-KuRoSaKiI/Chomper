"""
Parse document handlers for Chomper.
"""
import json
import logging
from typing import Any, Dict, List

from mcp.types import TextContent, ImageContent

from src.formatters.toon_formatter import TOONFormatter
from src.server.config import (
    DEFAULT_SUMMARY_CHARS,
    DEFAULT_MAX_IMAGES,
    OUTPUT_FORMAT_TOON,
    DEFAULT_OUTPUT_FORMAT,
)
from src.server.helpers import (
    validate_file_path,
    parse_from_base64,
    get_extractor_for_file,
    remove_image_placeholders,
    extract_images_from_structure,
    detect_mime_type,
)

logger = logging.getLogger("chomper")


async def handle_parse_document(arguments: Dict[str, Any]) -> List[TextContent | ImageContent]:
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
    file_path = validate_file_path(file_path_str)

    logger.info(f"Parsing document: {file_path} (full_text={full_text}, include_images={include_images})")

    # Get extractor
    extractor = get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Clean text by removing image placeholders
    clean_text = remove_image_placeholders(raw_doc.text)
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
        images = extract_images_from_structure(raw_doc.structure, max_images=DEFAULT_MAX_IMAGES)

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
                mime_type = detect_mime_type(base64_data)
                response_items.append(ImageContent(
                    type="image",
                    data=base64_data,
                    mimeType=mime_type
                ))

        # Note if there are more images
        total_images = len(extract_images_from_structure(raw_doc.structure))
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


async def handle_parse_document_bytes(arguments: Dict[str, Any]) -> List[TextContent | ImageContent]:
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
    temp_path, _ = parse_from_base64(content_base64, filename)

    try:
        # Reuse existing parse logic by building modified arguments
        modified_args = {
            "file_path": str(temp_path),
            "full_text": arguments.get("full_text", False),
            "include_images": arguments.get("include_images", False),
            "output_format": arguments.get("output_format", DEFAULT_OUTPUT_FORMAT),
        }

        # Use existing handler
        result = await handle_parse_document(modified_args)

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
