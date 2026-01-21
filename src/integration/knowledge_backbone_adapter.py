"""
Adapter for integrating new modular parsers with knowledge_backbone ingestion service.

Provides backwards-compatible interface while using new DocumentPipeline.
"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from parsers import DocumentPipeline
from parsers.formatters import SimpleFormatter


class KnowledgeBackboneAdapter:
    """
    Adapter that wraps DocumentPipeline for knowledge_backbone compatibility.

    Converts new ProcessedDocument format to old chunk format expected by ingestion service.
    """

    def __init__(self, image_helper=None):
        """
        Initialize adapter.

        Args:
            image_helper: Optional image processing helper (not used in new system)
        """
        # Create pipeline with simple formatter
        self.pipeline = DocumentPipeline(
            formatter=SimpleFormatter(),
            skip_enrichment_for_code=True  # Code doesn't need keyword enrichment
        )
        self.image_helper = image_helper

    async def parse(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse document using new pipeline, return old format.

        Args:
            file_path: Path to document

        Returns:
            List of chunk dictionaries in old format
        """
        # Use new pipeline to process
        result = self.pipeline.process(file_path)

        # Convert to old format
        chunks = []
        for chunk in result["chunks"]:
            chunk_dict = {
                "text": chunk["text"],
                "page_number": chunk["metadata"].get("page_number", chunk["metadata"].get("slide_number", chunk["chunk_id"] + 1)),
                "metadata": chunk["metadata"]
            }
            chunks.append(chunk_dict)

        return chunks


class ParserFactoryAdapter:
    """
    Drop-in replacement for old ParserFactory using new modular parsers.

    Maintains same interface for backwards compatibility.
    """

    @staticmethod
    def create_parser(file_path: str, image_helper=None):
        """
        Create parser for file.

        Args:
            file_path: Path to file
            image_helper: Optional image helper (ignored in new system)

        Returns:
            Parser instance
        """
        return KnowledgeBackboneAdapter(image_helper=image_helper)

    @staticmethod
    def create_image_helper(provider: str, model: str):
        """
        Create image helper (stub for compatibility).

        Args:
            provider: Provider name
            model: Model name

        Returns:
            None (not used in new system)
        """
        return None

    @staticmethod
    def get_supported_formats() -> List[str]:
        """
        Get supported file formats.

        Returns:
            List of extensions
        """
        pipeline = DocumentPipeline()
        return pipeline.get_supported_formats()
