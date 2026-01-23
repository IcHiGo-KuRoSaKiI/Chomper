"""
Base class for output formatters.

All formatters inherit from BaseFormatter.
"""
from abc import ABC, abstractmethod
from typing import Any

from ..models.document import EnrichedChunk, ProcessedDocument


class BaseFormatter(ABC):
    """
    Abstract base class for output formatters.

    Formatters transform enriched chunks into backend-specific
    formats (JSON, Weaviate, Neo4j, etc.)
    """

    @abstractmethod
    def format(self, document: ProcessedDocument) -> Any:
        """
        Format processed document for specific backend.

        Args:
            document: Processed document with enriched chunks

        Returns:
            Formatted output (type depends on formatter)

        Raises:
            ValueError: If document is invalid
        """
        pass

    def format_chunks(self, chunks: list[EnrichedChunk]) -> Any:
        """
        Format just the chunks (without document wrapper).

        Args:
            chunks: List of enriched chunks

        Returns:
            Formatted chunks

        Raises:
            ValueError: If chunks are invalid
        """
        # Default: create a temporary ProcessedDocument
        temp_doc = ProcessedDocument(
            document_id="temp",
            source="unknown",
            doc_type="unknown",
            chunks=chunks
        )
        return self.format(temp_doc)

    def _validate_document(self, document: ProcessedDocument) -> None:
        """
        Validate document before formatting.

        Args:
            document: Document to validate

        Raises:
            ValueError: If document is invalid
        """
        if not document.chunks:
            raise ValueError("Document must have at least one chunk")

        if not document.document_id:
            raise ValueError("Document must have an ID")
