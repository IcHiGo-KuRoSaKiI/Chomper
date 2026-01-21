"""
Handler functions for Chomper MCP server tools.
"""
from .parse import handle_parse_document, handle_parse_document_bytes
from .chunk import handle_get_document_chunk, handle_parse_document_chunked
from .images import handle_get_document_images
from .metadata import handle_extract_metadata, handle_list_supported_formats
from .batch import handle_batch_parse

__all__ = [
    "handle_parse_document",
    "handle_parse_document_bytes",
    "handle_get_document_chunk",
    "handle_parse_document_chunked",
    "handle_get_document_images",
    "handle_extract_metadata",
    "handle_list_supported_formats",
    "handle_batch_parse",
]
