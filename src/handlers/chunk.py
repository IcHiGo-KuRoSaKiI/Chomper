"""
Chunk document handlers for Chomper.
"""
import json
import logging
from typing import Any, Dict, List

from mcp.types import TextContent

from src.formatters.toon_formatter import TOONFormatter
from src.chunking.strategies import SemanticChunker, TextChunker
from src.server.config import (
    DEFAULT_CHUNK_LIMIT,
    OUTPUT_FORMAT_TOON,
    DEFAULT_OUTPUT_FORMAT,
)
from src.server.helpers import (
    validate_file_path,
    get_extractor_for_file,
    get_chunker_for_file,
    remove_image_placeholders,
    chunk_to_dict,
)

logger = logging.getLogger("chomper")


async def handle_get_document_chunk(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle get_document_chunk tool call for paginated content retrieval.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing the chunk and metadata
    """
    file_path_str = arguments.get("file_path")
    offset = arguments.get("offset", 0)
    limit = arguments.get("limit", DEFAULT_CHUNK_LIMIT)
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = validate_file_path(file_path_str)

    logger.info(f"Getting document chunk: {file_path} (offset={offset}, limit={limit})")

    # Get extractor
    extractor = get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Clean text
    clean_text = remove_image_placeholders(raw_doc.text)
    total_chars = len(clean_text)

    # Validate offset
    if offset >= total_chars:
        return [
            TextContent(type="text", text=""),
            TextContent(type="text", text=json.dumps({
                "file_path": str(file_path),
                "offset": offset,
                "limit": limit,
                "returned_chars": 0,
                "total_chars": total_chars,
                "remaining_chars": 0,
                "has_more": False,
                "error": f"Offset {offset} exceeds document length {total_chars}"
            }, indent=2))
        ]

    # Extract chunk
    end_pos = min(offset + limit, total_chars)
    chunk_text = clean_text[offset:end_pos]
    remaining = total_chars - end_pos
    has_more = remaining > 0

    # TOON format output
    if output_format == OUTPUT_FORMAT_TOON:
        toon_output = TOONFormatter.format_chunk_response(
            file_path=str(file_path),
            text=chunk_text,
            offset=offset,
            limit=limit,
            total_chars=total_chars,
            has_more=has_more
        )
        return [TextContent(type="text", text=toon_output)]

    # JSON format output (default)
    response_items: List[TextContent] = []

    # TextContent[0]: The text chunk
    response_items.append(TextContent(type="text", text=chunk_text))

    # TextContent[1]: Metadata about the chunk
    chunk_metadata = {
        "file_path": str(file_path),
        "offset": offset,
        "limit": limit,
        "returned_chars": len(chunk_text),
        "total_chars": total_chars,
        "remaining_chars": remaining,
        "has_more": has_more
    }

    if has_more:
        chunk_metadata["next_chunk_hint"] = (
            f"Use get_document_chunk(file_path, offset={end_pos}, limit={limit}) "
            f"to get next {min(remaining, limit)} of {remaining} remaining characters."
        )

    response_items.append(TextContent(type="text", text=json.dumps(chunk_metadata, indent=2)))

    return response_items


async def handle_parse_document_chunked(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle parse_document_chunked tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing chunked document result as JSON or TOON
    """
    file_path_str = arguments.get("file_path")
    chunk_size = arguments.get("chunk_size", 1000)
    overlap = arguments.get("overlap", 100)
    chunking_strategy = arguments.get("chunking_strategy", "auto")
    embedding_model = arguments.get("embedding_model", "fast")
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)

    # Validate path
    file_path = validate_file_path(file_path_str)

    logger.info(f"Parsing document chunked: {file_path} (size={chunk_size}, overlap={overlap}, strategy={chunking_strategy})")

    # Get extractor
    extractor = get_extractor_for_file(file_path)

    # Extract raw document
    raw_doc = extractor.extract(str(file_path))

    # Get chunker based on strategy
    if chunking_strategy == "semantic":
        # Use semantic chunker with embeddings
        if SemanticChunker is None:
            raise ValueError(
                "Semantic chunking requires sentence-transformers. "
                "Install with: pip install sentence-transformers"
            )
        chunker = SemanticChunker(
            target_size=chunk_size,
            overlap=overlap,
            model=embedding_model
        )
    elif chunking_strategy == "fixed":
        # Simple fixed-size chunking using TextChunker
        chunker = TextChunker(target_size=chunk_size, overlap=overlap)
    elif chunking_strategy == "recursive":
        # Recursive paragraph/sentence chunking
        chunker = TextChunker(target_size=chunk_size, overlap=overlap)
    else:
        # Auto: use format-aware chunker
        chunker = get_chunker_for_file(file_path, target_size=chunk_size, overlap=overlap)

    # Chunk document
    chunks = chunker.chunk(raw_doc)

    # Calculate statistics
    total_words = sum(chunk.word_count for chunk in chunks)
    total_chars = len(raw_doc.text)
    extension = file_path.suffix.lower()

    # TOON format output
    if output_format == OUTPUT_FORMAT_TOON:
        lines = []

        # Document header
        parts = [
            f"d:{file_path.name}",
            f"t:{extension[1:] if extension else 'unknown'}",
            f"w:{total_words}",
            f"c:{total_chars}",
            f"n:{len(chunks)}"
        ]
        lines.append("|".join(parts))

        # Metadata
        meta_parts = []
        for key in ["author", "title"]:
            if key in raw_doc.metadata and raw_doc.metadata[key]:
                val = str(raw_doc.metadata[key]).replace(",", "\\,")
                meta_parts.append(f"{key}={val}")
        if meta_parts:
            lines.append(f"m:{','.join(meta_parts)}")

        # Chunks
        for chunk in chunks:
            lines.append("---")
            # Chunk header
            section_name = getattr(chunk, "section_name", "") or ""
            section_type = getattr(chunk, "section_type", "text") or "text"
            lines.append(f"{chunk.chunk_id}|{chunk.start_char}-{chunk.end_char}|{section_type}|{section_name}")
            # Chunk text
            lines.append(chunk.text)
            # Keywords
            keywords = getattr(chunk, "keywords", [])
            if keywords:
                lines.append(f"k:{','.join(keywords[:10])}")

        return [TextContent(type="text", text="\n".join(lines))]

    # JSON format output (default)
    response: Dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunking_strategy": chunking_strategy,
        "total_chunks": len(chunks),
        "chunks": [chunk_to_dict(chunk) for chunk in chunks],
        "metadata": raw_doc.metadata,
    }

    response["statistics"] = {
        "total_words": total_words,
        "average_chunk_words": total_words // len(chunks) if chunks else 0,
        "total_characters": total_chars,
    }

    if chunking_strategy == "semantic":
        response["embedding_model"] = embedding_model

    return [TextContent(type="text", text=json.dumps(response, indent=2, default=str))]
