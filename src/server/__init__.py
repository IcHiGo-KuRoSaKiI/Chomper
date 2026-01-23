"""
Server module for Chomper MCP server.

Exports configuration, tools, and helpers.
"""
from .config import (
    CHUNKERS,
    DEFAULT_CHUNK_LIMIT,
    DEFAULT_MAX_IMAGES,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_SUMMARY_CHARS,
    EXTRACTORS,
    FORMAT_DESCRIPTIONS,
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_TOON,
)
from .helpers import (
    chunk_to_dict,
    detect_mime_type,
    extract_images_from_structure,
    format_error_response,
    get_chunker_for_file,
    get_extractor_for_file,
    parse_from_base64,
    remove_image_placeholders,
    validate_file_path,
)
from .tools import get_tools

__all__ = [
    # Config
    "DEFAULT_SUMMARY_CHARS",
    "DEFAULT_CHUNK_LIMIT",
    "DEFAULT_MAX_IMAGES",
    "OUTPUT_FORMAT_JSON",
    "OUTPUT_FORMAT_TOON",
    "DEFAULT_OUTPUT_FORMAT",
    "FORMAT_DESCRIPTIONS",
    "EXTRACTORS",
    "CHUNKERS",
    # Helpers
    "validate_file_path",
    "parse_from_base64",
    "get_extractor_for_file",
    "get_chunker_for_file",
    "extract_images_from_structure",
    "remove_image_placeholders",
    "detect_mime_type",
    "format_error_response",
    "chunk_to_dict",
    # Tools
    "get_tools",
]
