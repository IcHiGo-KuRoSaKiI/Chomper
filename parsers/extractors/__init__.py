"""Extractors for different document formats."""

from .base import BaseExtractor
from .code_extractor import CodeExtractor
from .text_extractor import TextExtractor
from .markdown_extractor import MarkdownExtractor

# Optional heavy dependencies
try:
    from .pdf_extractor import PDFExtractor
except ImportError:
    PDFExtractor = None

try:
    from .docx_extractor import DOCXExtractor
except ImportError:
    DOCXExtractor = None

try:
    from .pptx_extractor import PPTXExtractor
except ImportError:
    PPTXExtractor = None

try:
    from .excel_extractor import ExcelExtractor
except ImportError:
    ExcelExtractor = None

try:
    from .csv_extractor import CSVExtractor
except ImportError:
    CSVExtractor = None

try:
    from .html_extractor import HTMLExtractor
except ImportError:
    HTMLExtractor = None

__all__ = [
    "BaseExtractor",
    "PDFExtractor",
    "DOCXExtractor",
    "PPTXExtractor",
    "CodeExtractor",
    "TextExtractor",
    "MarkdownExtractor",
    "ExcelExtractor",
    "CSVExtractor",
    "HTMLExtractor"
]
