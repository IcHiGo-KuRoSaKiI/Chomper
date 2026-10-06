"""
Helper functions for Chomper MCP server.

Nothing here imports an extractor (or ``src.extractors``) at module load, so the
server starts without paying for PyMuPDF, pandas, trafilatura and friends.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from mcp.types import TextContent

from .config import EXTRACTORS, MAX_BYTES_INPUT, supported_extensions_hint
from .documents import (
    build_chunker,
    extractor_class_for,
    keywords_of,
    section_name_of,
    validate_path,
)

T = TypeVar("T")

#: Sentinel meaning "use image_utils.DEFAULT_MAX_DIMENSION" without importing it here.
_DEFAULT_DIMENSION = -1


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run CPU-bound or blocking work (extraction, chunking) off the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


def int_arg(
    arguments: dict[str, Any],
    name: str,
    default: int | None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    hint: str = "",
) -> int | None:
    """Read an integer tool argument, rejecting wrong types and out-of-range values.

    Raises:
        ValueError: naming the argument, the bad value and the accepted range.
    """
    value = arguments.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}.{(' ' + hint) if hint else ''}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}.{(' ' + hint) if hint else ''}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value}.{(' ' + hint) if hint else ''}")
    return value


def validate_file_path(file_path: str | None) -> Path:
    """
    Validate and return absolute path.

    Args:
        file_path: Path to validate

    Returns:
        Validated Path object

    Raises:
        ValueError: If path is invalid or file does not exist
    """
    return validate_path(file_path)


def decode_base64_content(content_base64: str) -> bytes:
    """Decode base64 tool input, enforcing the size cap before and after decoding.

    Raises:
        ValueError: invalid base64, or larger than ``MAX_BYTES_INPUT``.
    """
    limit_mb = MAX_BYTES_INPUT // (1024 * 1024)
    if len(content_base64) > MAX_BYTES_INPUT * 4 // 3 + 4:
        raise ValueError(
            f"content_base64 is larger than the {limit_mb} MB limit. "
            "Save the file to disk and call parse_document with its path instead."
        )
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(
            f"Invalid base64 content: {e}. Send standard base64 (RFC 4648) without line breaks."
        ) from e
    if len(content) > MAX_BYTES_INPUT:
        raise ValueError(
            f"Decoded content is {len(content)} bytes, over the {limit_mb} MB limit. "
            "Save the file to disk and call parse_document with its path instead."
        )
    return content


def parse_from_base64(content_base64: str, filename: str) -> tuple[Path, None]:
    """
    Decode base64 content and write to a temporary file.

    Args:
        content_base64: Base64-encoded file content
        filename: Filename with extension for format detection (e.g., 'report.pdf')

    Returns:
        Tuple of (temp_file_path, None) - second element reserved for future cleanup callback

    Raises:
        ValueError: If filename has no extension, the format is unsupported, or the
            content is invalid or too large
    """
    ext = Path(filename).suffix.lower()
    if not ext:
        raise ValueError(
            "filename must have an extension for format detection (e.g., 'document.pdf', 'data.xlsx')"
        )
    if ext not in EXTRACTORS:
        reason = EXTRACTORS.unavailable_reason(ext)
        if ext in EXTRACTORS.known() and reason:
            raise ValueError(reason)
        raise ValueError(
            f"Unsupported file format: {ext}. Supported formats: {supported_extensions_hint()}"
        )

    content_bytes = decode_base64_content(content_base64)

    temp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        temp_file.write(content_bytes)
        temp_file.close()
        return Path(temp_file.name), None
    except OSError as e:
        temp_file.close()
        Path(temp_file.name).unlink(missing_ok=True)
        raise ValueError(f"Failed to write temp file: {e}") from e


def get_extractor_for_file(file_path: Path) -> Any:
    """
    Get appropriate extractor for file type.

    Args:
        file_path: Path to file

    Returns:
        Extractor instance

    Raises:
        ValueError: If file type is not supported
    """
    return extractor_class_for(file_path)()


def get_chunker_for_file(
    file_path: Path,
    target_size: int = 1000,
    overlap: int = 100
) -> Any:
    """
    Get the format-aware ("auto") chunker for a file, as the library and CLI do.

    Args:
        file_path: Path to file
        target_size: Maximum words per chunk
        overlap: Words to overlap

    Returns:
        Chunker instance
    """
    return build_chunker(file_path.suffix.lower(), "auto", target_size, overlap)


def extract_images_from_structure(
    structure: dict[str, Any] | None,
    page_filter: int | None = None,
    max_images: int | None = None,
    max_dimension: int | None = _DEFAULT_DIMENSION,
    image_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Images from any document structure (PDF pages, PPTX slides, DOCX sections,
    or a flat top-level list), decoded and encoded only for those returned.

    Args:
        structure: Document structure from extraction
        page_filter: If set, only return images from this page/slide (1-indexed)
        max_images: Maximum number of images to return
        max_dimension: Downscale so the long edge is at most this; 0 keeps full size
            (default: ``image_utils.DEFAULT_MAX_DIMENSION``)
        image_id: Only the image whose marker in the text is ``![...](image:<id>)``

    Returns:
        List of image dictionaries with id, page, pages, base64, mime_type,
        width, height, position. Identical images (a logo on every page) are
        returned once, with ``pages`` listing every page they appear on.
    """
    from ..extractors.image_utils import DEFAULT_MAX_DIMENSION, collect_images

    if max_dimension == _DEFAULT_DIMENSION:
        max_dimension = DEFAULT_MAX_DIMENSION
    return [
        {
            "id": img.get("id"),
            "page": img.get("page"),
            "pages": img.get("pages", [img.get("page")]),
            "base64": img["content"],
            "mime_type": img["mime_type"],
            "width": img.get("width", 0),
            "height": img.get("height", 0),
            "original_width": img.get("original_width", img.get("width", 0)),
            "original_height": img.get("original_height", img.get("height", 0)),
            "position": img.get("position", {}),
            **({"alt": img["alt"]} if img.get("alt") else {}),
        }
        for img in collect_images(
            structure,
            page_filter=page_filter,
            max_images=max_images,
            max_dimension=max_dimension,
            image_id=image_id,
        )
    ]


def count_images_in_structure(structure: dict[str, Any] | None, page_filter: int | None = None) -> int:
    """Number of (de-duplicated) images, without decoding any of them."""
    from ..extractors.image_utils import count_images

    return count_images(structure, page_filter=page_filter)


def detect_mime_type(data: str) -> str:
    """MIME type of base64 image data (see ``image_utils.detect_mime_type``)."""
    from ..extractors.image_utils import detect_mime_type as _detect

    return _detect(data)


def remove_image_placeholders(text: str) -> str:
    """
    Remove legacy ``[Image: WxH]`` placeholders from text.

    The ``![alt](image:<id>)`` markers are kept: they tell the reader where a
    figure sits and which id to pass to ``get_document_images``.
    """
    return re.sub(r'\[Image:\s*\d+x\d+\]\s*', '', text)


def format_error_response(error: Exception) -> list[TextContent]:
    """
    Format error response as TextContent list (legacy shape; tool failures are now
    reported with ``isError=True`` by the server, see ``server.dispatch_tool``).

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


def chunk_to_dict(chunk: Any) -> dict[str, Any]:
    """
    Convert chunk to dictionary.

    Args:
        chunk: Chunk object

    Returns:
        Dictionary representation (``section_name`` and ``keywords`` are read from
        wherever the chunker recorded them, including ``chunk.metadata``)
    """
    metadata = dict(getattr(chunk, "metadata", None) or {})
    return {
        "chunk_id": chunk.chunk_id,
        "text": chunk.text,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
        "word_count": chunk.word_count,
        "metadata": metadata,
        "keywords": keywords_of(chunk),
        "section_name": section_name_of(chunk),
        "section_type": getattr(chunk, "section_type", None) or metadata.get("section_type", "text"),
    }
