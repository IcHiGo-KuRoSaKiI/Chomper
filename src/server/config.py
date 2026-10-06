"""
Configuration constants and the extractor/chunker registries for Chomper.

Extractor and chunker classes are resolved on first use, not at import time.
Importing every extractor eagerly pulled in pandas, trafilatura, extract_msg and
PyMuPDF before the server could even answer ``initialize``. ``EXTRACTORS`` and
``CHUNKERS`` are read-only mappings that import a class the first time its
extension is looked up, and report an extension as missing when its optional
dependency is not installed (the same graceful fallback as before).
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Iterator, Mapping
from typing import Any

logger = logging.getLogger("chomper")

# Default constants
DEFAULT_SUMMARY_CHARS = 5000
DEFAULT_CHUNK_LIMIT = 5000
DEFAULT_MAX_IMAGES = 5
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_CHUNK_STRATEGY = "auto"
#: Strategy names accepted by the library, the CLI and the MCP server alike.
CHUNK_STRATEGIES: tuple[str, ...] = ("auto", "semantic", "fixed", "recursive")
#: Largest decoded payload accepted by ``parse_document_bytes`` / ``parse_bytes``.
MAX_BYTES_INPUT = 100 * 1024 * 1024

# Output format options
OUTPUT_FORMAT_JSON = "json"
OUTPUT_FORMAT_TOON = "toon"
DEFAULT_OUTPUT_FORMAT = OUTPUT_FORMAT_JSON

# Format descriptions for supported extensions
FORMAT_DESCRIPTIONS: dict[str, str] = {
    ".pdf": "PDF documents with text and image extraction",
    ".docx": "Microsoft Word documents (OOXML format)",
    ".doc": "Microsoft Word documents (legacy format via DOCX handler)",
    ".pptx": "Microsoft PowerPoint presentations",
    ".ppt": "Microsoft PowerPoint presentations (legacy format)",
    ".xlsx": "Microsoft Excel spreadsheets",
    ".xlsm": "Microsoft Excel macro-enabled spreadsheets",
    ".xltx": "Microsoft Excel templates",
    ".xltm": "Microsoft Excel macro-enabled templates",
    ".csv": "Comma-separated values files",
    ".tsv": "Tab-separated values files",
    ".html": "HTML web pages",
    ".htm": "HTML web pages (alternate extension)",
    ".md": "Markdown documents",
    ".markdown": "Markdown documents (alternate extension)",
    ".txt": "Plain text files",
    ".text": "Plain text files (alternate extension)",
    ".log": "Log files",
    ".py": "Python source code",
    ".js": "JavaScript source code",
    ".jsx": "React JSX source code",
    ".ts": "TypeScript source code",
    ".tsx": "React TypeScript source code",
    ".java": "Java source code",
    ".cpp": "C++ source code",
    ".c": "C source code",
    ".go": "Go source code",
    ".rs": "Rust source code",
    ".json": "JSON data files",
    ".yaml": "YAML configuration/data files",
    ".yml": "YAML configuration/data files",
    ".xml": "XML documents",
    ".eml": "Email messages (RFC 822 format)",
    ".msg": "Outlook email messages",
    ".epub": "EPUB e-books",
    ".rtf": "Rich Text Format documents",
}

# (module, class name, module-level flags that must all be true, pip hint)
_Spec = tuple[str, str, tuple[str, ...], str]

_EX = "src.extractors."
_CODE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".go", ".rs")

_EXTRACTOR_SPECS: dict[str, _Spec] = {
    **dict.fromkeys(_CODE_EXTENSIONS, (_EX + "code_extractor", "CodeExtractor", (), "")),
    **dict.fromkeys((".txt", ".text", ".log"), (_EX + "text_extractor", "TextExtractor", (), "")),
    ".md": (_EX + "markdown_extractor", "MarkdownExtractor", (), ""),
    ".markdown": (_EX + "markdown_extractor", "MarkdownExtractor", (), ""),
    ".pdf": (_EX + "pdf_extractor", "PDFExtractor", (), "pymupdf pymupdf4llm"),
    ".docx": (_EX + "docx_extractor", "DOCXExtractor", (), "python-docx"),
    ".doc": (_EX + "docx_extractor", "DOCXExtractor", (), "python-docx"),
    ".pptx": (_EX + "pptx_extractor", "PPTXExtractor", (), "python-pptx"),
    ".ppt": (_EX + "pptx_extractor", "PPTXExtractor", (), "python-pptx"),
    **dict.fromkeys((".xlsx", ".xlsm", ".xltx", ".xltm"), (_EX + "excel_extractor", "ExcelExtractor", ("OPENPYXL_AVAILABLE",), "openpyxl")),
    ".csv": (_EX + "csv_extractor", "CSVExtractor", ("PANDAS_AVAILABLE",), "'chomper[csv]'"),
    ".tsv": (_EX + "csv_extractor", "CSVExtractor", ("PANDAS_AVAILABLE",), "'chomper[csv]'"),
    ".html": (_EX + "html_extractor", "HTMLExtractor", ("BS4_AVAILABLE",), "beautifulsoup4"),
    ".htm": (_EX + "html_extractor", "HTMLExtractor", ("BS4_AVAILABLE",), "beautifulsoup4"),
    ".json": (_EX + "data_extractor", "JSONExtractor", (), ""),
    ".yaml": (_EX + "data_extractor", "YAMLExtractor", ("YAML_AVAILABLE",), "'chomper[yaml]'"),
    ".yml": (_EX + "data_extractor", "YAMLExtractor", ("YAML_AVAILABLE",), "'chomper[yaml]'"),
    ".xml": (_EX + "data_extractor", "XMLExtractor", ("LXML_AVAILABLE",), "lxml"),
    ".eml": (_EX + "email_extractor", "EMLExtractor", (), ""),
    ".msg": (_EX + "email_extractor", "MSGExtractor", ("MSG_AVAILABLE",), "'chomper[email]'"),
    ".epub": (
        _EX + "epub_extractor", "EPUBExtractor",
        ("EBOOKLIB_AVAILABLE", "BS4_AVAILABLE"), "'chomper[epub]'",
    ),
    ".rtf": (_EX + "rtf_extractor", "RTFExtractor", ("STRIPRTF_AVAILABLE",), "'chomper[rtf]'"),
}

_CH = "src.chunking.strategies."
_CHUNKER_SPECS: dict[str, _Spec] = {
    **dict.fromkeys(_CODE_EXTENSIONS, (_CH + "code_chunker", "CodeChunker", (), "")),
    **dict.fromkeys((".txt", ".text", ".log", ".json", ".yaml", ".yml", ".xml", ".eml", ".msg", ".epub", ".rtf"), (_CH + "text_chunker", "TextChunker", (), "")),
    ".md": (_CH + "markdown_chunker", "MarkdownChunker", (), ""),
    ".markdown": (_CH + "markdown_chunker", "MarkdownChunker", (), ""),
    # Structural chunking is the default for PDFs: heading-bounded, table-safe and
    # sentence-safe. PDFChunker remains importable for page or word-count slicing.
    ".pdf": (_CH + "structural_pdf_chunker", "StructuralPDFChunker", (), ""),
    ".docx": (_CH + "docx_chunker", "DOCXChunker", (), ""),
    ".doc": (_CH + "docx_chunker", "DOCXChunker", (), ""),
    ".pptx": (_CH + "pptx_chunker", "PPTXChunker", (), ""),
    ".ppt": (_CH + "pptx_chunker", "PPTXChunker", (), ""),
    **dict.fromkeys((".xlsx", ".xlsm", ".xltx", ".xltm", ".csv", ".tsv"), (_CH + "excel_chunker", "ExcelChunker", (), "")),
    ".html": (_CH + "html_chunker", "HTMLChunker", (), ""),
    ".htm": (_CH + "html_chunker", "HTMLChunker", (), ""),
}


class LazyRegistry(Mapping[str, type]):
    """Extension -> class mapping that imports each class on first lookup.

    An extension whose module fails to import, or whose required dependency
    flag is false, is absent from the mapping, and :meth:`unavailable_reason`
    says why.
    """

    def __init__(self, specs: dict[str, _Spec], companion: LazyRegistry | None = None) -> None:
        self._specs = specs
        self._companion = companion  # e.g. chunkers only count where extraction works
        self._resolved: dict[str, type | None] = {}
        self._reasons: dict[str, str] = {}
        self._lock = threading.RLock()

    def _resolve(self, ext: str) -> type | None:
        if ext in self._resolved:
            return self._resolved[ext]
        with self._lock:
            if ext in self._resolved:
                return self._resolved[ext]
            cls: type | None = None
            spec = self._specs.get(ext)
            if spec is not None:
                module_name, class_name, flags, hint = spec
                try:
                    module = importlib.import_module(module_name)
                    cls = getattr(module, class_name)
                    missing = [flag for flag in flags if not getattr(module, flag, True)]
                    if missing:
                        cls = None
                        self._reasons[ext] = (
                            f"Optional dependency missing for {ext}. Install with: pip install {hint}"
                        )
                except (ImportError, AttributeError) as e:
                    logger.debug("Extractor for %s unavailable: %s", ext, e)
                    self._reasons[ext] = (
                        f"Optional dependency missing for {ext} ({e}). "
                        + (f"Install with: pip install {hint}" if hint else "")
                    ).strip()
            self._resolved[ext] = cls
            return cls

    def __getitem__(self, ext: str) -> type:
        cls = self._resolve(ext)
        if cls is None or (self._companion is not None and ext not in self._companion):
            raise KeyError(ext)
        return cls

    def __contains__(self, ext: object) -> bool:
        if not isinstance(ext, str):
            return False
        try:
            self[ext]
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return (ext for ext in self._specs if ext in self)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def known(self) -> list[str]:
        """Every extension Chomper knows about, without importing anything."""
        return sorted(self._specs)

    def unavailable_reason(self, ext: str) -> str | None:
        """Why ``ext`` is not available, or None when it is."""
        if ext not in self._specs:
            return f"Unsupported file format: {ext}"
        if ext in self:
            return None
        return self._reasons.get(ext, "Required dependencies not installed")


EXTRACTORS: LazyRegistry = LazyRegistry(_EXTRACTOR_SPECS)
CHUNKERS: LazyRegistry = LazyRegistry(_CHUNKER_SPECS, companion=EXTRACTORS)


def supported_extensions_hint() -> str:
    """Comma-separated list of known extensions, for error messages (no imports)."""
    return ", ".join(EXTRACTORS.known())


def initialize_extractors() -> None:
    """Resolve every registry entry now (kept for backwards compatibility)."""
    for ext in EXTRACTORS.known():
        ext in EXTRACTORS  # noqa: B015 - resolving is the side effect we want
    for ext in CHUNKERS.known():
        ext in CHUNKERS  # noqa: B015


def describe_formats() -> list[dict[str, Any]]:
    """Every known format with availability, for ``list_supported_formats``."""
    return [
        {
            "extension": ext,
            "description": description,
            "available": ext in EXTRACTORS,
            "reason": EXTRACTORS.unavailable_reason(ext),
        }
        for ext, description in sorted(FORMAT_DESCRIPTIONS.items())
    ]
