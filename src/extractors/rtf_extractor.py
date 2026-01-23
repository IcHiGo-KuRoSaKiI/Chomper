"""
Extractor for RTF (Rich Text Format) files.

RTF is a document file format developed by Microsoft for
cross-platform document interchange.
"""
from pathlib import Path
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor

# Optional import
try:
    from striprtf.striprtf import rtf_to_text
    STRIPRTF_AVAILABLE = True
except ImportError:
    rtf_to_text = None
    STRIPRTF_AVAILABLE = False


class RTFExtractor(BaseExtractor):
    """
    Extractor for RTF (Rich Text Format) files.

    Uses striprtf library for text extraction.
    """

    SUPPORTED_EXTENSIONS = [".rtf"]

    def __init__(self):
        """Initialize RTF extractor."""
        if not STRIPRTF_AVAILABLE:
            raise ImportError("striprtf is required for RTF extraction. Install with: pip install striprtf")

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from RTF file."""
        self.validate_file(file_path)

        path = Path(file_path)

        # Read RTF content
        try:
            # Try UTF-8 first
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            # Fall back to latin-1
            content = path.read_text(encoding='latin-1')

        # Extract text from RTF
        try:
            text = rtf_to_text(content)
        except Exception as e:
            raise ValueError(f"Failed to parse RTF: {e}") from e

        # Clean up the text
        text = self._clean_text(text)

        # Analyze text structure
        structure_info = self._analyze_structure(text)

        # Build metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "rtf",
            "paragraph_count": structure_info["paragraph_count"],
            "line_count": structure_info["line_count"],
            "word_count": structure_info["word_count"],
            "char_count": len(text),
        })

        return RawDocument(
            text=text,
            metadata=metadata,
            structure={
                "type": "rtf",
                "paragraph_count": structure_info["paragraph_count"],
                "has_lists": structure_info["has_lists"],
                "has_tables": structure_info["has_tables"],
            }
        )

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace while preserving paragraph breaks
        lines = text.split('\n')
        cleaned_lines = []
        prev_empty = False

        for line in lines:
            line = line.strip()
            if not line:
                if not prev_empty:
                    cleaned_lines.append('')
                prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False

        return '\n'.join(cleaned_lines).strip()

    def _analyze_structure(self, text: str) -> dict[str, Any]:
        """Analyze text structure."""
        lines = text.split('\n')
        paragraphs = [p for p in text.split('\n\n') if p.strip()]

        # Check for common list patterns
        has_lists = any(
            line.strip().startswith(('- ', '* ', '• ', '1.', '2.', 'a.', 'b.'))
            for line in lines
        )

        # Check for table-like patterns (multiple tabs or pipes)
        has_tables = any(
            line.count('\t') >= 2 or line.count('|') >= 2
            for line in lines
        )

        return {
            "paragraph_count": len(paragraphs),
            "line_count": len([line for line in lines if line.strip()]),
            "word_count": len(text.split()),
            "has_lists": has_lists,
            "has_tables": has_tables,
        }
