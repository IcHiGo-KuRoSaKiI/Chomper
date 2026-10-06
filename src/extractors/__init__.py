"""Extractors for different document formats.

Extractor classes load on first access (PEP 562), so importing this package -- or
a light module inside it -- does not pull in PyMuPDF, pandas, extract_msg and the
rest. An extractor whose optional dependency is missing resolves to ``None``,
as before.
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import BaseExtractor

#: Public name -> submodule that defines it.
_SOURCES = {
    "CodeExtractor": "code_extractor",
    "JSONExtractor": "data_extractor",
    "YAMLExtractor": "data_extractor",
    "XMLExtractor": "data_extractor",
    "MarkdownExtractor": "markdown_extractor",
    "TextExtractor": "text_extractor",
    "EMLExtractor": "email_extractor",
    "MSGExtractor": "email_extractor",
    "PDFExtractor": "pdf_extractor",
    "DOCXExtractor": "docx_extractor",
    "PPTXExtractor": "pptx_extractor",
    "ExcelExtractor": "excel_extractor",
    "CSVExtractor": "csv_extractor",
    "HTMLExtractor": "html_extractor",
    "EPUBExtractor": "epub_extractor",
    "RTFExtractor": "rtf_extractor",
}


def __getattr__(name: str) -> Any:
    module_name = _SOURCES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = getattr(importlib.import_module(f".{module_name}", __name__), name)
    except ImportError:
        value = None  # optional dependency not installed
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_SOURCES])


__all__ = ["BaseExtractor", *_SOURCES]
