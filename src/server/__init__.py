"""
Server module for Chomper MCP server.

Exports configuration, tools, and helpers. Attributes are imported on first
access (PEP 562) so that ``import src.server.config`` / ``src.server.cache`` stay
cheap for library users and do not pull in the MCP SDK.
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    # Config
    "DEFAULT_SUMMARY_CHARS": "config",
    "DEFAULT_CHUNK_LIMIT": "config",
    "DEFAULT_MAX_IMAGES": "config",
    "OUTPUT_FORMAT_JSON": "config",
    "OUTPUT_FORMAT_TOON": "config",
    "DEFAULT_OUTPUT_FORMAT": "config",
    "FORMAT_DESCRIPTIONS": "config",
    "EXTRACTORS": "config",
    "CHUNKERS": "config",
    # Helpers
    "validate_file_path": "helpers",
    "parse_from_base64": "helpers",
    "get_extractor_for_file": "helpers",
    "get_chunker_for_file": "helpers",
    "count_images_in_structure": "helpers",
    "extract_images_from_structure": "helpers",
    "remove_image_placeholders": "helpers",
    "detect_mime_type": "helpers",
    "format_error_response": "helpers",
    "chunk_to_dict": "helpers",
    # Tools
    "get_tools": "tools",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
