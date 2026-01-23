"""Data models for document parsing."""

from .document import Chunk, EnrichedChunk, ProcessedDocument, RawDocument
from .excel_models import CellInfo, CSVMetadata, ExcelMetadata, SheetInfo, TableRange
from .html_models import (
    HTMLDocument,
    HTMLForm,
    HTMLLink,
    HTMLList,
    HTMLMetadata,
    HTMLSection,
    HTMLTable,
)

__all__ = [
    # Core models
    "RawDocument",
    "Chunk",
    "EnrichedChunk",
    "ProcessedDocument",

    # Excel/CSV models
    "CellInfo",
    "TableRange",
    "SheetInfo",
    "ExcelMetadata",
    "CSVMetadata",

    # HTML models
    "HTMLTable",
    "HTMLList",
    "HTMLForm",
    "HTMLLink",
    "HTMLSection",
    "HTMLMetadata",
    "HTMLDocument"
]
