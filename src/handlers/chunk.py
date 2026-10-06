"""
Chunk document handlers for Chomper.

Both handlers do their extraction and chunking in a worker thread and read the
document through the shared cache, so paging with ``get_document_chunk`` extracts
a file once, not once per page.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mcp.types import TextContent

from src.formatters.toon_formatter import TOONFormatter
from src.server.config import (
    CHUNK_STRATEGIES,
    DEFAULT_CHUNK_LIMIT,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_STRATEGY,
    DEFAULT_OUTPUT_FORMAT,
    OUTPUT_FORMAT_TOON,
)
from src.server.documents import chunk_document, load_document, validate_chunk_options
from src.server.helpers import (
    chunk_to_dict,
    int_arg,
    pdf_options,
    pdf_options_hint,
    remove_image_placeholders,
    run_blocking,
    validate_file_path,
)

logger = logging.getLogger("chomper")


async def handle_get_document_chunk(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Handle get_document_chunk tool call for paginated content retrieval.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing the chunk and metadata

    Raises:
        ValueError: negative offset, non-positive limit, or a bad path
    """
    offset = int_arg(arguments, "offset", 0, minimum=0, hint="Use 0 for the start of the document.")
    limit = int_arg(
        arguments, "limit", DEFAULT_CHUNK_LIMIT, minimum=1,
        hint=f"Use a positive number of characters, e.g. {DEFAULT_CHUNK_LIMIT}.",
    )
    assert offset is not None and limit is not None
    pdf_options(arguments)
    return await run_blocking(_get_document_chunk_sync, arguments, offset, limit)


def _get_document_chunk_sync(
    arguments: dict[str, Any], offset: int, limit: int
) -> list[TextContent]:
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)
    ocr, table_format = pdf_options(arguments)
    file_path = validate_file_path(arguments.get("file_path"))

    logger.info(f"Getting document chunk: {file_path} (offset={offset}, limit={limit})")

    raw_doc = load_document(file_path, ocr=ocr, table_format=table_format)

    clean_text = remove_image_placeholders(raw_doc.text)
    total_chars = len(clean_text)

    if offset >= total_chars and not (offset == 0 and total_chars == 0):
        raise ValueError(
            f"offset {offset} is past the end of the document ({total_chars} characters). "
            f"Use an offset between 0 and {max(total_chars - 1, 0)}."
        )

    end_pos = min(offset + limit, total_chars)
    chunk_text = clean_text[offset:end_pos]
    remaining = total_chars - end_pos
    has_more = remaining > 0

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

    response_items: list[TextContent] = [TextContent(type="text", text=chunk_text)]

    chunk_metadata: dict[str, Any] = {
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
            f"Use get_document_chunk(file_path, offset={end_pos}, limit={limit}"
            f"{pdf_options_hint(ocr, table_format)}) "
            f"to get next {min(remaining, limit)} of {remaining} remaining characters."
        )

    response_items.append(TextContent(type="text", text=json.dumps(chunk_metadata, indent=2)))
    return response_items


async def handle_parse_document_chunked(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Handle parse_document_chunked tool call.

    Builds the chunker with the same factory, defaults and strategy names as
    ``chomper.chunk()`` and the CLI.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing chunked document result as JSON or TOON
    """
    chunk_size = int_arg(arguments, "chunk_size", DEFAULT_CHUNK_SIZE, minimum=1)
    overlap = int_arg(arguments, "overlap", DEFAULT_CHUNK_OVERLAP, minimum=0)
    assert chunk_size is not None and overlap is not None
    strategy = arguments.get("chunking_strategy", DEFAULT_CHUNK_STRATEGY)
    embedding_model = arguments.get("embedding_model", "fast")
    if strategy not in CHUNK_STRATEGIES:
        raise ValueError(
            f"Unknown chunking_strategy {strategy!r}. Use one of: {', '.join(CHUNK_STRATEGIES)}."
        )
    validate_chunk_options(strategy, chunk_size, overlap, embedding_model)
    pdf_options(arguments)
    return await run_blocking(
        _parse_document_chunked_sync, arguments, chunk_size, overlap, strategy, embedding_model
    )


def _parse_document_chunked_sync(
    arguments: dict[str, Any],
    chunk_size: int,
    overlap: int,
    chunking_strategy: str,
    embedding_model: str,
) -> list[TextContent]:
    output_format = arguments.get("output_format", DEFAULT_OUTPUT_FORMAT)
    include_keywords = bool(arguments.get("include_keywords", False))
    ocr, table_format = pdf_options(arguments)
    file_path = validate_file_path(arguments.get("file_path"))

    logger.info(
        f"Parsing document chunked: {file_path} "
        f"(size={chunk_size}, overlap={overlap}, strategy={chunking_strategy})"
    )

    outcome = chunk_document(
        file_path,
        strategy=chunking_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
        embedding_model=embedding_model,
        keywords=include_keywords,
        ocr=ocr,
        table_format=table_format,
    )
    chunks = outcome.chunks
    doc_metadata, total_chars = _document_summary(file_path, outcome)

    total_words = sum(chunk.word_count for chunk in chunks)
    extension = file_path.suffix.lower()

    if output_format == OUTPUT_FORMAT_TOON:
        lines = []
        parts = [
            f"d:{file_path.name}",
            f"t:{extension[1:] if extension else 'unknown'}",
            f"w:{total_words}",
            f"c:{total_chars}",
            f"n:{len(chunks)}"
        ]
        lines.append("|".join(parts))

        meta_parts = []
        for key in ["author", "title"]:
            if doc_metadata.get(key):
                val = str(doc_metadata[key]).replace(",", "\\,")
                meta_parts.append(f"{key}={val}")
        if meta_parts:
            lines.append(f"m:{','.join(meta_parts)}")

        for chunk in chunks:
            info = chunk_to_dict(chunk)
            lines.append("---")
            lines.append(
                f"{chunk.chunk_id}|{chunk.start_char}-{chunk.end_char}|"
                f"{info['section_type']}|{info['section_name'] or ''}"
            )
            lines.append(chunk.text)
            if info["keywords"]:
                lines.append(f"k:{','.join(info['keywords'][:10])}")

        return [TextContent(type="text", text="\n".join(lines))]

    response: dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunking_strategy": chunking_strategy,
        "total_chunks": len(chunks),
        "chunks": [chunk_to_dict(chunk) for chunk in chunks],
        "metadata": doc_metadata,
    }

    response["statistics"] = {
        "total_words": total_words,
        "average_chunk_words": total_words // len(chunks) if chunks else 0,
        "total_characters": total_chars,
    }

    if chunking_strategy == "semantic":
        response["embedding_model"] = embedding_model
    if pdf_options_hint(ocr, table_format):
        response["ocr"] = ocr
        response["table_format"] = table_format

    return [TextContent(type="text", text=json.dumps(response, indent=2, default=str))]


def _document_summary(file_path: Path, outcome: Any) -> tuple[dict[str, Any], int]:
    """Document metadata and character count for the chunked response.

    PDFs chunked straight from the file (no extraction pass) report the
    structural parse's page count and text length unless an extraction is
    already cached.
    """
    if outcome.raw_doc is not None:
        return dict(outcome.raw_doc.metadata or {}), len(outcome.raw_doc.text)
    metadata: dict[str, Any] = {"filename": file_path.name, "file_path": str(file_path)}
    if outcome.document_info.get("page_count"):
        metadata["page_count"] = outcome.document_info["page_count"]
    chunks = outcome.chunks
    total_chars = chunks[-1].end_char if chunks else 0
    return metadata, total_chars
