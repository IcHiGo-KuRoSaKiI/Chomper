"""Extractors for different document formats."""

from .base import BaseExtractor
from .code_extractor import CodeExtractor
from .text_extractor import TextExtractor
from .markdown_extractor import MarkdownExtractor

# Data formats (JSON always available, YAML/XML optional)
from .data_extractor import JSONExtractor

try:
    from .data_extractor import YAMLExtractor
except ImportError:
    YAMLExtractor = None

try:
    from .data_extractor import XMLExtractor
except ImportError:
    XMLExtractor = None

# Email formats (EML always available via stdlib)
from .email_extractor import EMLExtractor

try:
    from .email_extractor import MSGExtractor
except ImportError:
    MSGExtractor = None

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

try:
    from .epub_extractor import EPUBExtractor
except ImportError:
    EPUBExtractor = None

try:
    from .rtf_extractor import RTFExtractor
except ImportError:
    RTFExtractor = None

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
    "HTMLExtractor",
    "JSONExtractor",
    "YAMLExtractor",
    "XMLExtractor",
    "EMLExtractor",
    "MSGExtractor",
    "EPUBExtractor",
    "RTFExtractor",
]
