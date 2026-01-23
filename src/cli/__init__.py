"""
Chomper CLI module - Output formatters and CLI utilities.

This module provides:
- Formatters for converting ParseResult, ChunkResult, and MetadataResult objects
  into various output formats (text, JSON, CSV, Markdown, XML, and custom templates).
- Directory watcher for auto-parsing new/changed files.
- Interactive REPL for document parsing sessions.
"""

from __future__ import annotations

from .formatters import (
    CSVFormatter,
    JSONFormatter,
    MarkdownFormatter,
    OutputFormatter,
    TemplateFormatter,
    TextFormatter,
    XMLFormatter,
    get_formatter,
)
from .interactive import (
    InteractiveShell,
    SessionState,
    run_interactive,
)
from .watcher import (
    DirectoryWatcher,
    get_supported_extensions,
    parse_patterns,
)

__all__ = [
    # Formatters
    "OutputFormatter",
    "TextFormatter",
    "JSONFormatter",
    "CSVFormatter",
    "MarkdownFormatter",
    "XMLFormatter",
    "TemplateFormatter",
    "get_formatter",
    # Watcher
    "DirectoryWatcher",
    "parse_patterns",
    "get_supported_extensions",
    # Interactive
    "InteractiveShell",
    "SessionState",
    "run_interactive",
]
