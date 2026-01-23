"""
Configuration constants and extractor/chunker initialization for Chomper.
"""

from src.chunking.strategies import (
    CodeChunker,
    DOCXChunker,
    ExcelChunker,
    HTMLChunker,
    MarkdownChunker,
    PDFChunker,
    PPTXChunker,
    TextChunker,
)
from src.extractors import (
    CodeExtractor,
    CSVExtractor,
    DOCXExtractor,
    EMLExtractor,
    EPUBExtractor,
    ExcelExtractor,
    HTMLExtractor,
    JSONExtractor,
    MarkdownExtractor,
    MSGExtractor,
    PDFExtractor,
    PPTXExtractor,
    RTFExtractor,
    TextExtractor,
    XMLExtractor,
    YAMLExtractor,
)

# Default constants
DEFAULT_SUMMARY_CHARS = 5000
DEFAULT_CHUNK_LIMIT = 5000
DEFAULT_MAX_IMAGES = 5

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

# Extractor mapping by extension
EXTRACTORS: dict[str, type] = {}
CHUNKERS: dict[str, type] = {}


def initialize_extractors() -> None:
    """Initialize extractor and chunker mappings based on available dependencies."""
    global EXTRACTORS, CHUNKERS

    # Always available extractors
    code_extensions = [".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".go", ".rs"]
    for ext in code_extensions:
        EXTRACTORS[ext] = CodeExtractor
        CHUNKERS[ext] = CodeChunker

    EXTRACTORS[".txt"] = TextExtractor
    EXTRACTORS[".text"] = TextExtractor
    EXTRACTORS[".log"] = TextExtractor
    CHUNKERS[".txt"] = TextChunker
    CHUNKERS[".text"] = TextChunker
    CHUNKERS[".log"] = TextChunker

    EXTRACTORS[".md"] = MarkdownExtractor
    EXTRACTORS[".markdown"] = MarkdownExtractor
    CHUNKERS[".md"] = MarkdownChunker
    CHUNKERS[".markdown"] = MarkdownChunker

    # Optional extractors (require heavy dependencies)
    if PDFExtractor is not None:
        EXTRACTORS[".pdf"] = PDFExtractor
        CHUNKERS[".pdf"] = PDFChunker

    if DOCXExtractor is not None:
        EXTRACTORS[".docx"] = DOCXExtractor
        EXTRACTORS[".doc"] = DOCXExtractor
        CHUNKERS[".docx"] = DOCXChunker
        CHUNKERS[".doc"] = DOCXChunker

    if PPTXExtractor is not None:
        EXTRACTORS[".pptx"] = PPTXExtractor
        EXTRACTORS[".ppt"] = PPTXExtractor
        CHUNKERS[".pptx"] = PPTXChunker
        CHUNKERS[".ppt"] = PPTXChunker

    if ExcelExtractor is not None:
        for ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
            EXTRACTORS[ext] = ExcelExtractor
            CHUNKERS[ext] = ExcelChunker

    if CSVExtractor is not None:
        EXTRACTORS[".csv"] = CSVExtractor
        EXTRACTORS[".tsv"] = CSVExtractor
        CHUNKERS[".csv"] = ExcelChunker
        CHUNKERS[".tsv"] = ExcelChunker

    if HTMLExtractor is not None:
        EXTRACTORS[".html"] = HTMLExtractor
        EXTRACTORS[".htm"] = HTMLExtractor
        CHUNKERS[".html"] = HTMLChunker
        CHUNKERS[".htm"] = HTMLChunker

    # Data formats (JSON always available)
    EXTRACTORS[".json"] = JSONExtractor
    CHUNKERS[".json"] = TextChunker  # Use text chunker for data files

    if YAMLExtractor is not None:
        EXTRACTORS[".yaml"] = YAMLExtractor
        EXTRACTORS[".yml"] = YAMLExtractor
        CHUNKERS[".yaml"] = TextChunker
        CHUNKERS[".yml"] = TextChunker

    if XMLExtractor is not None:
        EXTRACTORS[".xml"] = XMLExtractor
        CHUNKERS[".xml"] = TextChunker

    # Email formats (EML always available via stdlib)
    EXTRACTORS[".eml"] = EMLExtractor
    CHUNKERS[".eml"] = TextChunker

    if MSGExtractor is not None:
        EXTRACTORS[".msg"] = MSGExtractor
        CHUNKERS[".msg"] = TextChunker

    # E-book and document formats
    if EPUBExtractor is not None:
        EXTRACTORS[".epub"] = EPUBExtractor
        CHUNKERS[".epub"] = TextChunker

    if RTFExtractor is not None:
        EXTRACTORS[".rtf"] = RTFExtractor
        CHUNKERS[".rtf"] = TextChunker


# Initialize on module load
initialize_extractors()
