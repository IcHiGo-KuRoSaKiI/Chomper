#!/usr/bin/env python3
"""
Chomper - Chomp through any document.

An MCP server that parses 36+ file formats for AI systems like Claude.

Features:
- Full document parsing with text, metadata, and image extraction
- Semantic chunking with sentence-transformers for RAG
- TOON format for ~40% token reduction
- MCP prompts for document analysis
- Batch processing for multiple files
- Support for PDF, DOCX, PPTX, Excel, CSV, HTML, Markdown, JSON, YAML, XML, Email, EPUB, RTF, and code files

Usage:
    python server.py

    Or via MCP client configuration:
    {
        "mcpServers": {
            "chomper": {
                "command": "python",
                "args": ["/path/to/server.py"]
            }
        }
    }
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    ImageContent,
    Tool,
    Prompt,
    PromptArgument,
    PromptMessage,
    GetPromptResult,
)

# Add src to path if needed
sys.path.insert(0, str(Path(__file__).parent))

# Import from new modular structure
from src.server.config import EXTRACTORS
from src.server.tools import get_tools
from src.server.helpers import validate_file_path, get_extractor_for_file, format_error_response
from src.prompts import PROMPTS, format_prompt
from src.handlers import (
    handle_parse_document,
    handle_parse_document_bytes,
    handle_get_document_chunk,
    handle_parse_document_chunked,
    handle_get_document_images,
    handle_extract_metadata,
    handle_list_supported_formats,
    handle_batch_parse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("chomper")

# Initialize MCP server
server = Server("chomper")


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available document parsing tools."""
    return get_tools()


@server.list_prompts()
async def list_prompts() -> List[Prompt]:
    """List available document analysis prompts."""
    prompts = []
    for name, prompt_def in PROMPTS.items():
        arguments = [
            PromptArgument(
                name=arg["name"],
                description=arg.get("description", ""),
                required=arg.get("required", False)
            )
            for arg in prompt_def.get("arguments", [])
        ]
        prompts.append(
            Prompt(
                name=prompt_def["name"],
                description=prompt_def["description"],
                arguments=arguments
            )
        )
    return prompts


@server.get_prompt()
async def get_prompt(name: str, arguments: Dict[str, str] | None = None) -> GetPromptResult:
    """Get a specific prompt with document content filled in."""
    if name not in PROMPTS:
        raise ValueError(f"Unknown prompt: {name}. Available: {list(PROMPTS.keys())}")

    arguments = arguments or {}

    # Get file_path (required for all document prompts)
    file_path_str = arguments.get("file_path")
    if not file_path_str:
        raise ValueError("file_path is required for document prompts")

    # Validate and parse document
    file_path = validate_file_path(file_path_str)
    extractor = get_extractor_for_file(file_path)
    raw_doc = extractor.extract(str(file_path))

    # Get document info
    doc_type = file_path.suffix.lower().lstrip('.')
    word_count = len(raw_doc.text.split())

    # Truncate very long documents for prompt context
    max_prompt_chars = 50000
    document_content = raw_doc.text
    if len(document_content) > max_prompt_chars:
        document_content = document_content[:max_prompt_chars] + f"\n\n[... truncated, {len(raw_doc.text) - max_prompt_chars} more characters ...]"

    # Format the prompt
    formatted_prompt = format_prompt(
        name=name,
        document_content=document_content,
        file_name=file_path.name,
        doc_type=doc_type,
        word_count=word_count,
        **{k: v for k, v in arguments.items() if k != "file_path"}
    )

    return GetPromptResult(
        description=f"Document analysis prompt: {PROMPTS[name]['description']}",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=formatted_prompt)
            )
        ]
    )


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent | ImageContent]:
    """Handle tool calls for document parsing."""
    try:
        if name == "parse_document":
            return await handle_parse_document(arguments)
        elif name == "parse_document_bytes":
            return await handle_parse_document_bytes(arguments)
        elif name == "get_document_chunk":
            return await handle_get_document_chunk(arguments)
        elif name == "get_document_images":
            return await handle_get_document_images(arguments)
        elif name == "parse_document_chunked":
            return await handle_parse_document_chunked(arguments)
        elif name == "extract_metadata":
            return await handle_extract_metadata(arguments)
        elif name == "list_supported_formats":
            return await handle_list_supported_formats(arguments)
        elif name == "batch_parse":
            return await handle_batch_parse(arguments)
        else:
            return format_error_response(ValueError(f"Unknown tool: {name}"))

    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return format_error_response(e)


async def main() -> None:
    """Main entry point for the MCP server."""
    logger.info("Starting Chomper MCP Server")
    logger.info(f"Available formats: {', '.join(sorted(EXTRACTORS.keys()))}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
