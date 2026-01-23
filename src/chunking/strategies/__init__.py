"""Chunking strategies for different document formats."""

from .code_chunker import CodeChunker
from .docx_chunker import DOCXChunker
from .excel_chunker import ExcelChunker
from .html_chunker import HTMLChunker
from .markdown_chunker import MarkdownChunker
from .pdf_chunker import PDFChunker
from .pptx_chunker import PPTXChunker
from .text_chunker import TextChunker

# Semantic chunker (requires sentence-transformers, lazy-loaded)
try:
    from .semantic_chunker import SemanticChunker
except ImportError:
    SemanticChunker = None

__all__ = [
    "PDFChunker",
    "DOCXChunker",
    "PPTXChunker",
    "CodeChunker",
    "TextChunker",
    "MarkdownChunker",
    "ExcelChunker",
    "HTMLChunker",
    "SemanticChunker",
]
