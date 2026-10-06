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
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    ImageContent,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
)

# Add src to path if needed
sys.path.insert(0, str(Path(__file__).parent))

from src.handlers import (  # noqa: E402
    handle_batch_parse,
    handle_extract_metadata,
    handle_get_document_chunk,
    handle_get_document_images,
    handle_list_supported_formats,
    handle_parse_document,
    handle_parse_document_bytes,
    handle_parse_document_chunked,
)
from src.prompts import PROMPTS, format_prompt  # noqa: E402
from src.server.config import EXTRACTORS  # noqa: E402
from src.server.documents import load_document  # noqa: E402
from src.server.helpers import run_blocking, validate_file_path  # noqa: E402
from src.server.tools import get_tools  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("chomper")

# Initialize MCP server
server = Server("chomper")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available document parsing tools."""
    return get_tools()


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available document analysis prompts."""
    prompts = []
    for _name, prompt_def in PROMPTS.items():
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
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    """Get a specific prompt with document content filled in."""
    if name not in PROMPTS:
        raise ValueError(f"Unknown prompt: {name}. Available: {list(PROMPTS.keys())}")

    arguments = arguments or {}

    # Get file_path (required for all document prompts)
    file_path_str = arguments.get("file_path")
    if not file_path_str:
        raise ValueError("file_path is required for document prompts")

    # Validate and parse document (cached, off the event loop)
    file_path = validate_file_path(file_path_str)
    raw_doc = await run_blocking(load_document, file_path)

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


ToolHandler = Callable[[dict[str, Any]], Awaitable[Sequence[TextContent | ImageContent]]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "parse_document": handle_parse_document,
    "parse_document_bytes": handle_parse_document_bytes,
    "get_document_chunk": handle_get_document_chunk,
    "get_document_images": handle_get_document_images,
    "parse_document_chunked": handle_parse_document_chunked,
    "extract_metadata": handle_extract_metadata,
    "list_supported_formats": handle_list_supported_formats,
    "batch_parse": handle_batch_parse,
}


def tool_error(tool: str, error: Exception) -> CallToolResult:
    """A tool failure the client can see as one: ``isError=True`` plus a message
    saying what was wrong (the handlers' messages also say what to do instead).
    """
    message = str(error) or type(error).__name__
    return CallToolResult(
        content=[TextContent(type="text", text=f"{tool} failed ({type(error).__name__}): {message}")],
        isError=True,
    )


async def dispatch_tool(
    name: str, arguments: dict[str, Any] | None
) -> Sequence[TextContent | ImageContent] | CallToolResult:
    """Run a tool; failures come back as ``CallToolResult(isError=True)``."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return tool_error(
            name,
            ValueError(f"Unknown tool: {name}. Available tools: {', '.join(TOOL_HANDLERS)}."),
        )
    try:
        return await handler(arguments or {})
    except (ValueError, TypeError, FileNotFoundError, PermissionError, ImportError) as e:
        logger.warning("Tool %s rejected the request: %s", name, e)
        return tool_error(name, e)
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return tool_error(name, e)


@server.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> Sequence[TextContent | ImageContent] | CallToolResult:
    """Handle tool calls for document parsing."""
    return await dispatch_tool(name, arguments)


async def main() -> None:
    """Main entry point for the MCP server."""
    logger.info("Starting Chomper MCP Server")
    # Formats are resolved lazily; listing them here would import every extractor.
    logger.info(f"Known formats: {', '.join(EXTRACTORS.known())}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


def run() -> None:
    """Console-script entry point (``chomper``): run the async server."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
