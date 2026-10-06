"""Chunking strategies for different document formats."""

from .code_chunker import CodeChunker
from .docx_chunker import DOCXChunker
from .excel_chunker import ExcelChunker
from .html_chunker import HTMLChunker
from .markdown_chunker import MarkdownChunker
from .pdf_chunker import PDFChunker
from .pptx_chunker import PPTXChunker
from .structural_pdf_chunker import StructuralPDFChunker
from .text_chunker import TextChunker


def __getattr__(name: str):
    """Import SemanticChunker (numpy, sentence-transformers) only when asked for.

    Resolves to None when numpy is missing, matching the old eager behaviour.
    """
    if name != "SemanticChunker":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        from .semantic_chunker import SemanticChunker as cls
    except ImportError:
        cls = None
    globals()["SemanticChunker"] = cls
    return cls

__all__ = [
    "PDFChunker",
    "StructuralPDFChunker",
    "DOCXChunker",
    "PPTXChunker",
    "CodeChunker",
    "TextChunker",
    "MarkdownChunker",
    "ExcelChunker",
    "HTMLChunker",
    "SemanticChunker",
]
