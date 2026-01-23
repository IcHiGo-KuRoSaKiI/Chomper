"""
Lightweight test suite for parser system.

Tests core functionality without heavy dependencies (PyMuPDF, python-pptx, python-docx).
"""
import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(parent_dir.parent))

from src.enrichment import KeywordExtractor, MetadataEnricher, TitleGenerator
from src.extractors import CodeExtractor, MarkdownExtractor, TextExtractor
from src.formatters import Neo4jFormatter, SimpleFormatter, WeaviateFormatter
from src.models.document import Chunk, EnrichedChunk, ProcessedDocument, RawDocument
from src.pipeline import DocumentPipeline

print("\n" + "=" * 70)
print("LIGHTWEIGHT PARSER SYSTEM TEST")
print("=" * 70)

# Test samples
SAMPLE_TEXT = """Introduction to AI

Artificial Intelligence (AI) is changing the world.

Machine Learning
Machine learning is a subset of AI.

Deep Learning
Deep learning uses neural networks.
"""

SAMPLE_MD = """# AI Guide

This is a guide to AI.

## Machine Learning

Machine learning enables computers to learn.

### Types of Learning

There are several types:
- Supervised learning
- Unsupervised learning
- Reinforcement learning
"""

SAMPLE_CODE = '''"""Sample module."""
import os
from typing import List

def hello():
    """Say hello."""
    print("Hello!")

class Calculator:
    """Simple calculator."""
    def add(self, a, b):
        return a + b
'''

def test_text_pipeline():
    """Test text processing end-to-end."""
    print("\n🧪 Testing Text Pipeline...")
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    temp_file.write(SAMPLE_TEXT)
    temp_file.close()

    try:
        pipeline = DocumentPipeline()
        result = pipeline.process(temp_file.name)

        assert "document_id" in result
        assert "chunks" in result
        assert len(result["chunks"]) > 0
        assert "keywords" in result["chunks"][0]

        print("✅ Text pipeline works!")
    finally:
        os.unlink(temp_file.name)

def test_markdown_pipeline():
    """Test markdown processing."""
    print("\n🧪 Testing Markdown Pipeline...")
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
    temp_file.write(SAMPLE_MD)
    temp_file.close()

    try:
        pipeline = DocumentPipeline()
        result = pipeline.process(temp_file.name)

        assert len(result["chunks"]) > 0
        # Should have heading metadata
        has_headings = any(c["metadata"].get("heading_level", 0) > 0 for c in result["chunks"])
        assert has_headings, "Should preserve headings"

        print("✅ Markdown pipeline works!")
    finally:
        os.unlink(temp_file.name)

def test_code_pipeline():
    """Test code processing."""
    print("\n🧪 Testing Code Pipeline...")
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    temp_file.write(SAMPLE_CODE)
    temp_file.close()

    try:
        pipeline = DocumentPipeline()
        result = pipeline.process(temp_file.name)

        assert len(result["chunks"]) > 0
        # Should detect code structure
        section_types = [c["metadata"].get("section_type") for c in result["chunks"]]
        has_code_structure = any(st in ["imports", "class", "function"] for st in section_types)
        assert has_code_structure, "Should detect code structure"

        print("✅ Code pipeline works!")
    finally:
        os.unlink(temp_file.name)

def test_extractors():
    """Test individual extractors."""
    print("\n🧪 Testing Extractors...")

    # Text
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    temp_file.write(SAMPLE_TEXT)
    temp_file.close()

    try:
        extractor = TextExtractor()
        raw_doc = extractor.extract(temp_file.name)
        assert isinstance(raw_doc, RawDocument)
        assert len(raw_doc.text) > 0
        print("  ✅ TextExtractor")
    finally:
        os.unlink(temp_file.name)

    # Markdown
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
    temp_file.write(SAMPLE_MD)
    temp_file.close()

    try:
        extractor = MarkdownExtractor()
        raw_doc = extractor.extract(temp_file.name)
        assert "sections" in raw_doc.structure
        assert len(raw_doc.structure["sections"]) > 0
        print("  ✅ MarkdownExtractor")
    finally:
        os.unlink(temp_file.name)

    # Code
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    temp_file.write(SAMPLE_CODE)
    temp_file.close()

    try:
        extractor = CodeExtractor()
        raw_doc = extractor.extract(temp_file.name)
        assert raw_doc.metadata["language"] == "python"
        assert len(raw_doc.structure["classes"]) > 0
        print("  ✅ CodeExtractor")
    finally:
        os.unlink(temp_file.name)

def test_enrichers():
    """Test enrichers."""
    print("\n🧪 Testing Enrichers...")

    chunks = [
        Chunk(
            chunk_id=0,
            text="Machine learning enables computers to learn from data.",
            metadata={}
        )
    ]

    # Keywords
    enricher = KeywordExtractor(method="rake")
    enriched = enricher.enrich(chunks)
    assert len(enriched[0].keywords) > 0
    print("  ✅ KeywordExtractor")

    # Titles
    enricher = TitleGenerator(method="keywords")
    enriched = enricher.enrich(chunks)
    assert enriched[0].section_name is not None
    print("  ✅ TitleGenerator")

    # Metadata
    enricher = MetadataEnricher()
    enriched = enricher.enrich(chunks)
    assert "word_count" in enriched[0].computed_metadata
    print("  ✅ MetadataEnricher")

def test_formatters():
    """Test formatters."""
    print("\n🧪 Testing Formatters...")

    doc = ProcessedDocument(
        document_id="test",
        source="/tmp/test.txt",
        doc_type="txt",
        chunks=[
            EnrichedChunk(
                chunk_id=0,
                text="Test",
                metadata={},
                keywords=["test"],
                section_name="Test",
                section_type="text"
            )
        ],
        metadata={}
    )

    # Simple
    formatter = SimpleFormatter()
    result = formatter.format(doc)
    assert isinstance(result, dict)
    print("  ✅ SimpleFormatter")

    # Weaviate
    formatter = WeaviateFormatter()
    result = formatter.format(doc)
    assert isinstance(result, list)
    assert "class" in result[0]
    print("  ✅ WeaviateFormatter")

    # Neo4j
    formatter = Neo4jFormatter()
    result = formatter.format(doc)
    assert "document_node" in result or "nodes" in result  # Support both formats
    assert "relationships" in result
    print("  ✅ Neo4jFormatter")

def main():
    """Run all tests."""
    try:
        test_extractors()
        test_enrichers()
        test_formatters()
        test_text_pipeline()
        test_markdown_pipeline()
        test_code_pipeline()

        print("\n" + "=" * 70)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 70)
        print("\nThe modular parser system is working correctly.")
        print("Core features tested:")
        print("  ✅ Text extraction and chunking")
        print("  ✅ Markdown heading detection")
        print("  ✅ Code AST parsing (Python)")
        print("  ✅ Keyword extraction (RAKE)")
        print("  ✅ Section title generation")
        print("  ✅ Metadata enrichment")
        print("  ✅ JSON/Weaviate/Neo4j formatting")
        print("  ✅ End-to-end pipeline")
        return 0

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n💥 Test crashed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
