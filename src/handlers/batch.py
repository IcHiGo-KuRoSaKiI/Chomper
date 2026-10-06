"""
Batch parsing handler for Chomper.

Files are parsed concurrently in worker threads, at most ``BATCH_CONCURRENCY`` at
a time; results keep the order of ``file_paths``. (PDF extraction is serialized
on the PyMuPDF lock, so PDFs gain less from concurrency than other formats.)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp.types import TextContent

from src.server.documents import load_document
from src.server.helpers import (
    count_images_in_structure,
    remove_image_placeholders,
    run_blocking,
    validate_file_path,
)

logger = logging.getLogger("chomper")

#: Files parsed at once by batch_parse.
BATCH_CONCURRENCY = max(1, min(4, os.cpu_count() or 1))
#: Upper bound on files in one batch_parse call.
MAX_BATCH_FILES = 500


def _parse_one(file_path_str: str, include_images: bool) -> dict[str, Any]:
    file_path = validate_file_path(file_path_str)
    raw_doc = load_document(file_path)
    clean_text = remove_image_placeholders(raw_doc.text)

    doc_result: dict[str, Any] = {
        "success": True,
        "file_path": str(file_path),
        "text_preview": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
        "total_characters": len(clean_text),
        "total_words": len(clean_text.split()),
        "metadata": raw_doc.metadata
    }
    if include_images:
        doc_result["image_count"] = count_images_in_structure(raw_doc.structure)
    return doc_result


async def handle_batch_parse(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Handle batch_parse tool call.

    Args:
        arguments: Tool arguments

    Returns:
        List with TextContent containing batch parsing results as JSON

    Raises:
        ValueError: empty/invalid ``file_paths``, or the first failure when
            ``continue_on_error`` is false
    """
    file_paths = arguments.get("file_paths", [])
    options = arguments.get("options") or {}

    include_images = bool(options.get("include_images", False))
    continue_on_error = bool(options.get("continue_on_error", True))

    if not file_paths or not isinstance(file_paths, list):
        raise ValueError("file_paths is required: a non-empty array of absolute file paths.")
    if len(file_paths) > MAX_BATCH_FILES:
        raise ValueError(
            f"file_paths has {len(file_paths)} entries; the limit is {MAX_BATCH_FILES}. "
            "Split the batch into several calls."
        )
    if not all(isinstance(p, str) for p in file_paths):
        raise ValueError("file_paths must contain only strings (absolute file paths).")

    logger.info(f"Batch parsing {len(file_paths)} documents ({BATCH_CONCURRENCY} at a time)")

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def run(file_path_str: str) -> dict[str, Any]:
        async with semaphore:
            try:
                return await run_blocking(_parse_one, file_path_str, include_images)
            except Exception as e:
                logger.warning(f"Failed to parse {file_path_str}: {e}")
                if not continue_on_error:
                    raise ValueError(f"Failed to parse {file_path_str}: {e}") from e
                return {
                    "success": False,
                    "file_path": file_path_str,
                    "error": str(e),
                    "error_type": type(e).__name__
                }

    results = await asyncio.gather(*(run(p) for p in file_paths))
    successful = sum(1 for r in results if r["success"])

    result = {
        "success": True,
        "total_files": len(file_paths),
        "successful": successful,
        "failed": len(results) - successful,
        "results": results
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
