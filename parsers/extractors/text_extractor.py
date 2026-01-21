"""
Text extractor for plain text files.

Extracts content from plain text files with minimal processing.
"""
from typing import Dict, Any
from .base import BaseExtractor
from ..models.document import RawDocument


class TextExtractor(BaseExtractor):
    """
    Extract content from plain text files.

    Features:
    - Simple text extraction
    - Paragraph detection
    - Basic structure preservation
    """

    SUPPORTED_EXTENSIONS = ['.txt', '.text', '.log']

    def __init__(self, detect_paragraphs: bool = True):
        """
        Initialize text extractor.

        Args:
            detect_paragraphs: Detect paragraph boundaries
        """
        self.detect_paragraphs = detect_paragraphs

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from text file.

        Args:
            file_path: Path to text file

        Returns:
            RawDocument with extracted content
        """
        self.validate_file(file_path)

        # Read file content
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Detect structure
        structure = None
        if self.detect_paragraphs:
            structure = self._detect_paragraphs(content)

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "text",
            "line_count": len(content.splitlines())
        })

        return RawDocument(
            text=content,
            metadata=metadata,
            structure=structure
        )

    def _detect_paragraphs(self, content: str) -> Dict[str, Any]:
        """
        Detect paragraph boundaries in text.

        Args:
            content: Text content

        Returns:
            Structure dictionary with paragraphs
        """
        # Split by double newlines (paragraph breaks)
        paragraphs = []
        current_para = []

        for line in content.splitlines():
            if line.strip():
                current_para.append(line)
            else:
                # Empty line - end of paragraph
                if current_para:
                    para_text = '\n'.join(current_para)
                    paragraphs.append({
                        "type": "paragraph",
                        "text": para_text
                    })
                    current_para = []

        # Add final paragraph
        if current_para:
            para_text = '\n'.join(current_para)
            paragraphs.append({
                "type": "paragraph",
                "text": para_text
            })

        return {"paragraphs": paragraphs}
