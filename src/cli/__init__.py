"""
Chomper CLI module - Output formatters and CLI utilities.

This module provides formatters for converting ParseResult, ChunkResult, and
MetadataResult objects into various output formats (text, JSON, CSV, Markdown, XML,
and custom templates).
"""

from __future__ import annotations

from .formatters import (
    OutputFormatter,
    TextFormatter,
    JSONFormatter,
    CSVFormatter,
    MarkdownFormatter,
    XMLFormatter,
    TemplateFormatter,
    get_formatter,
)

__all__ = [
    "OutputFormatter",
    "TextFormatter",
    "JSONFormatter",
    "CSVFormatter",
    "MarkdownFormatter",
    "XMLFormatter",
    "TemplateFormatter",
    "get_formatter",
]
