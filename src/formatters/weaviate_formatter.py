"""
Weaviate formatter for vector database ingestion.

Outputs Weaviate-ready objects with proper schema.
"""
from typing import Dict, Any, List
from .base import BaseFormatter
from ..models.document import ProcessedDocument, EnrichedChunk


class WeaviateFormatter(BaseFormatter):
    """
    Format documents for Weaviate vector database.

    Use Case:
    - Weaviate ingestion
    - Vector search preparation

    Output:
    - Weaviate collection objects
    - Properties properly mapped
    - Optional vector embeddings
    """

    def __init__(
        self,
        collection_name: str = "Document",
        unpack_metadata: bool = True,
        include_embeddings: bool = False
    ):
        """
        Initialize Weaviate formatter.

        Args:
            collection_name: Weaviate collection name
            unpack_metadata: Unpack metadata dict as individual properties
            include_embeddings: Include vector embeddings (if available)
        """
        self.collection_name = collection_name
        self.unpack_metadata = unpack_metadata
        self.include_embeddings = include_embeddings

    def format(self, document: ProcessedDocument) -> List[Dict[str, Any]]:
        """
        Format document as Weaviate objects.

        Args:
            document: Processed document to format

        Returns:
            List of Weaviate-ready objects
        """
        self._validate_document(document)

        weaviate_objects = []

        for chunk in document.chunks:
            obj = self._format_chunk(chunk, document)
            weaviate_objects.append(obj)

        return weaviate_objects

    def _format_chunk(self, chunk: EnrichedChunk, document: ProcessedDocument) -> Dict[str, Any]:
        """
        Format single chunk as Weaviate object.

        Args:
            chunk: Chunk to format
            document: Parent document

        Returns:
            Weaviate object dictionary
        """
        # Base properties
        properties = {
            "content": chunk.text,
            "docType": document.doc_type,
            "docId": document.document_id,
            "chunkIndex": chunk.chunk_id,
            "source": document.source,
            "title": document.metadata.get("title", "Untitled"),

            # Enrichment data
            "keywords": chunk.keywords if chunk.keywords else [],
            "sectionName": chunk.section_name,
            "sectionType": chunk.section_type,

            # Stats from metadata enricher
            "wordCount": chunk.computed_metadata.get("word_count", 0),
            "readingTime": chunk.computed_metadata.get("reading_time", ""),
        }

        # Unpack chunk metadata if enabled
        if self.unpack_metadata:
            # Add important metadata fields as properties
            for key, value in chunk.metadata.items():
                # Skip complex objects, only primitives
                if isinstance(value, (str, int, float, bool)):
                    properties[key] = value
                elif isinstance(value, list) and all(isinstance(x, (str, int, float, bool)) for x in value):
                    properties[key] = value

        # Create Weaviate object
        weaviate_obj = {
            "class": self.collection_name,
            "id": f"{document.document_id}_chunk_{chunk.chunk_id}",
            "properties": properties
        }

        # Add vector embeddings if available and enabled
        if self.include_embeddings and chunk.metadata.get("embedding"):
            weaviate_obj["vector"] = chunk.metadata["embedding"]

        return weaviate_obj

    def format_chunks(self, chunks: List[EnrichedChunk]) -> List[Dict[str, Any]]:
        """
        Format just chunks (creates temporary document).

        Args:
            chunks: List of enriched chunks

        Returns:
            List of Weaviate objects
        """
        # Create temporary document
        temp_doc = ProcessedDocument(
            document_id="temp",
            source="unknown",
            doc_type="unknown",
            chunks=chunks
        )
        return self.format(temp_doc)
