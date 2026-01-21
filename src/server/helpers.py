"""
Helper functions for Chomper MCP server.
"""
import base64
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.types import TextContent

from .config import EXTRACTORS, CHUNKERS


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


def parse_from_base64(content_base64: str, filename: str) -> Tuple[Path, None]:
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


def detect_mime_type(base64_data: str) -> str:
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


def format_error_response(error: Exception) -> List[TextContent]:
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


def chunk_to_dict(chunk: Any) -> Dict[str, Any]:
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
