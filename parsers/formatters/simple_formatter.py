"""
Simple formatter for standalone output.

Outputs plain Python dicts/JSON with no database dependencies.
"""
from typing import Dict, Any, List
from .base import BaseFormatter
from ..models.document import ProcessedDocument, EnrichedChunk


class SimpleFormatter(BaseFormatter):
    """
    Format documents as plain Python dicts/JSON.

    Use Case:
    - Standalone parsing (no database)
    - API responses
    - File export
    - Testing

    Output:
    - Plain dictionaries (JSON-serializable)
    - No database-specific schema
    """

    def __init__(self, include_metadata: bool = True):
        """
        Initialize simple formatter.

        Args:
            include_metadata: Include computed metadata in output
        """
        self.include_metadata = include_metadata

    def format(self, document: ProcessedDocument) -> Dict[str, Any]:
        """
        Format document as plain dictionary.

        Args:
            document: Processed document to format

        Returns:
            Dictionary with document and chunks
        """
        self._validate_document(document)

        return {
            "document_id": document.document_id,
            "source": document.source,
            "doc_type": document.doc_type,
            "total_chunks": document.total_chunks,
            "total_words": document.total_words,
            "metadata": document.metadata,
            "chunks": self._format_chunks(document.chunks)
        }

    def _format_chunks(self, chunks: List[EnrichedChunk]) -> List[Dict[str, Any]]:
        """
        Format chunks as dictionaries.

        Args:
            chunks: List of enriched chunks

        Returns:
            List of chunk dictionaries
        """
        formatted_chunks = []

        for chunk in chunks:
            chunk_dict = {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "keywords": chunk.keywords,
                "section_name": chunk.section_name,
                "section_type": chunk.section_type,
                "metadata": chunk.metadata
            }

            # Include computed metadata if enabled
            if self.include_metadata:
                chunk_dict["computed_metadata"] = chunk.computed_metadata

            formatted_chunks.append(chunk_dict)

        return formatted_chunks

    def format_chunks(self, chunks: List[EnrichedChunk]) -> List[Dict[str, Any]]:
        """
        Format just chunks (without document wrapper).

        Args:
            chunks: List of enriched chunks

        Returns:
            List of chunk dictionaries
        """
        return self._format_chunks(chunks)
