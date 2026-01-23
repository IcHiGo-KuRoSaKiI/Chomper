"""
Neo4j formatter for graph database ingestion.

Outputs Neo4j nodes and relationships with proper structure.
"""
from typing import Any

from ..models.document import EnrichedChunk, ProcessedDocument
from .base import BaseFormatter


class Neo4jFormatter(BaseFormatter):
    """
    Format documents for Neo4j graph database.

    Use Case:
    - Neo4j graph ingestion
    - Knowledge graph creation

    Output:
    - Document nodes
    - Chunk nodes
    - Section nodes (if enriched)
    - Relationships (PART_OF, HAS_SECTION, etc.)
    - Metadata unpacked as node properties (not JSON strings)
    """

    def __init__(
        self,
        unpack_metadata: bool = True,
        create_section_nodes: bool = True
    ):
        """
        Initialize Neo4j formatter.

        Args:
            unpack_metadata: Unpack metadata as individual properties (not JSON string)
            create_section_nodes: Create Section nodes for better graph structure
        """
        self.unpack_metadata = unpack_metadata
        self.create_section_nodes = create_section_nodes

    def format(self, document: ProcessedDocument) -> dict[str, Any]:
        """
        Format document as Neo4j nodes and relationships.

        Args:
            document: Processed document to format

        Returns:
            Dictionary with nodes and relationships
        """
        self._validate_document(document)

        return {
            "document_node": self._create_document_node(document),
            "chunk_nodes": self._create_chunk_nodes(document),
            "section_nodes": self._create_section_nodes(document) if self.create_section_nodes else [],
            "relationships": self._create_relationships(document)
        }

    def _create_document_node(self, document: ProcessedDocument) -> dict[str, Any]:
        """
        Create Document node.

        Args:
            document: Document to create node from

        Returns:
            Document node dictionary
        """
        node = {
            "labels": ["Document"],
            "properties": {
                "id": document.document_id,
                "docType": document.doc_type,
                "source": document.source,
                "title": document.metadata.get("title", "Untitled"),
                "totalChunks": document.total_chunks,
                "totalWords": document.total_words,
                "createdAt": "datetime()",  # Neo4j will set timestamp
                "updatedAt": "datetime()"
            }
        }

        # Unpack document metadata
        if self.unpack_metadata:
            for key, value in document.metadata.items():
                # Only add primitives as properties
                if isinstance(value, (str, int, float, bool)):
                    node["properties"][key] = value
                elif isinstance(value, list):
                    node["properties"][key] = value

        return node

    def _create_chunk_nodes(self, document: ProcessedDocument) -> list[dict[str, Any]]:
        """
        Create Chunk nodes.

        Args:
            document: Document containing chunks

        Returns:
            List of chunk node dictionaries
        """
        chunk_nodes = []

        for chunk in document.chunks:
            node = {
                "labels": ["Chunk"],
                "properties": {
                    "id": f"{document.document_id}_chunk_{chunk.chunk_id}",
                    "docId": document.document_id,
                    "chunkSeq": chunk.chunk_id,
                    "textPreview": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
                    "createdAt": "datetime()"
                }
            }

            # Unpack enrichment data as properties (NOT JSON string!)
            if self.unpack_metadata:
                node["properties"]["sectionName"] = chunk.section_name
                node["properties"]["sectionType"] = chunk.section_type
                node["properties"]["keywords"] = chunk.keywords if chunk.keywords else []

                # Add computed metadata
                node["properties"]["wordCount"] = chunk.computed_metadata.get("word_count", 0)
                node["properties"]["readingTime"] = chunk.computed_metadata.get("reading_time", "")
                node["properties"]["complexityScore"] = chunk.computed_metadata.get("complexity_score", 0)

                # Add important chunk metadata
                for key, value in chunk.metadata.items():
                    if isinstance(value, (str, int, float, bool)):
                        node["properties"][key] = value
            else:
                # Store as JSON string (old way)
                import json
                node["properties"]["metadata"] = json.dumps({
                    "section_name": chunk.section_name,
                    "section_type": chunk.section_type,
                    "keywords": chunk.keywords,
                    **chunk.metadata,
                    **chunk.computed_metadata
                })

            chunk_nodes.append(node)

        return chunk_nodes

    def _create_section_nodes(self, document: ProcessedDocument) -> list[dict[str, Any]]:
        """
        Create Section nodes from enriched section names.

        Args:
            document: Document with enriched chunks

        Returns:
            List of section node dictionaries
        """
        # Group chunks by section name
        sections = {}
        for chunk in document.chunks:
            section_name = chunk.section_name or "Untitled Section"
            if section_name not in sections:
                sections[section_name] = []
            sections[section_name].append(chunk)

        # Create Section nodes
        section_nodes = []
        for section_name, chunks in sections.items():
            node = {
                "labels": ["Section"],
                "properties": {
                    "id": f"{document.document_id}_section_{self._slugify(section_name)}",
                    "name": section_name,
                    "docId": document.document_id,
                    "chunkCount": len(chunks),
                    # Extract heading level if present
                    "headingLevel": chunks[0].metadata.get("heading_level", 0)
                }
            }
            section_nodes.append(node)

        return section_nodes

    def _create_relationships(self, document: ProcessedDocument) -> list[dict[str, Any]]:
        """
        Create relationships between nodes.

        Args:
            document: Document to create relationships from

        Returns:
            List of relationship dictionaries
        """
        relationships = []

        for chunk in document.chunks:
            chunk_id = f"{document.document_id}_chunk_{chunk.chunk_id}"

            # 1. Chunk -> PART_OF -> Document
            relationships.append({
                "type": "PART_OF",
                "from_node": chunk_id,
                "to_node": document.document_id,
                "properties": {}
            })

            # 2. Section -> CONTAINS -> Chunk (if sections enabled)
            if self.create_section_nodes and chunk.section_name:
                section_id = f"{document.document_id}_section_{self._slugify(chunk.section_name)}"

                # Document -> HAS_SECTION -> Section
                relationships.append({
                    "type": "HAS_SECTION",
                    "from_node": document.document_id,
                    "to_node": section_id,
                    "properties": {}
                })

                # Section -> CONTAINS -> Chunk
                relationships.append({
                    "type": "CONTAINS",
                    "from_node": section_id,
                    "to_node": chunk_id,
                    "properties": {}
                })

        return relationships

    def _slugify(self, text: str) -> str:
        """
        Convert text to slug for IDs.

        Args:
            text: Text to slugify

        Returns:
            Slugified text
        """
        import re
        # Convert to lowercase and replace spaces with underscores
        slug = text.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '_', slug)
        return slug

    def format_chunks(self, chunks: list[EnrichedChunk]) -> dict[str, Any]:
        """
        Format just chunks (creates temporary document).

        Args:
            chunks: List of enriched chunks

        Returns:
            Neo4j nodes and relationships
        """
        # Create temporary document
        temp_doc = ProcessedDocument(
            document_id="temp",
            source="unknown",
            doc_type="unknown",
            chunks=chunks
        )
        return self.format(temp_doc)
