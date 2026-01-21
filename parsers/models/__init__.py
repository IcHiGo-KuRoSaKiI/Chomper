"""Data models for document parsing."""

from .document import (
    RawDocument,
    Chunk,
    EnrichedChunk,
    ProcessedDocument
)

from .excel_models import (
    CellInfo,
    TableRange,
    SheetInfo,
    ExcelMetadata,
    CSVMetadata
)

from .html_models import (
    HTMLTable,
    HTMLList,
    HTMLForm,
    HTMLLink,
    HTMLSection,
    HTMLMetadata,
    HTMLDocument
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
