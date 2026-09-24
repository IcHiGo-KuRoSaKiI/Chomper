"""
Helper functions for Chomper MCP server.
"""
import base64
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from mcp.types import TextContent

from ..extractors.image_utils import collect_images, detect_mime_type  # noqa: F401
from .config import CHUNKERS, EXTRACTORS


def validate_file_path(file_path: str) -> Path:
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


def parse_from_base64(content_base64: str, filename: str) -> tuple[Path, None]:
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
        raise ValueError(f"Invalid base64 content: {e}") from e

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
    extension = file_path.suffix.lower()

    if extension not in EXTRACTORS:
        raise ValueError(
            f"Unsupported file format: {extension}. "
            f"Supported formats: {', '.join(sorted(EXTRACTORS.keys()))}"
        )

    return EXTRACTORS[extension]()


def get_chunker_for_file(
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


def extract_images_from_structure(
    structure: dict[str, Any] | None,
    page_filter: int | None = None,
    max_images: int | None = None
) -> list[dict[str, Any]]:
    """
    Extract images from any document structure (PDF pages, PPTX slides,
    DOCX sections, or a flat top-level list).

    Args:
        structure: Document structure from extraction
        page_filter: If set, only return images from this page/slide (1-indexed)
        max_images: Maximum number of images to return

    Returns:
        List of image dictionaries with page, pages, base64, mime_type,
        width, height, position. Identical images (a logo on every page) are
        returned once, with ``pages`` listing every page they appear on.
    """
    return [
        {
            "page": img.get("page"),
            "pages": img.get("pages", [img.get("page")]),
            "base64": img["content"],
            "mime_type": img["mime_type"],
            "width": img.get("width", 0),
            "height": img.get("height", 0),
            "position": img.get("position", {}),
        }
        for img in collect_images(structure, page_filter=page_filter, max_images=max_images)
    ]


def remove_image_placeholders(text: str) -> str:
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


def format_error_response(error: Exception) -> list[TextContent]:
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


def chunk_to_dict(chunk: Any) -> dict[str, Any]:
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
