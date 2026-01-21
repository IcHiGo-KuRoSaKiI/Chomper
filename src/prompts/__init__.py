"""
Centralized prompt management for all parsers.

Exports MCP prompt definitions and utilities.
"""
from .document_prompts import (
    PROMPTS,
    get_prompt_template,
    list_prompts,
    format_prompt,
)

__all__ = [
    "PROMPTS",
    "get_prompt_template",
    "list_prompts",
    "format_prompt",
]
