"""
Simple test script to validate new modular parser system.

Tests each parser with sample content.
"""
import sys
import os

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Now import
from pipeline import DocumentPipeline


def test_text_parser():
    """Test text parser with simple content."""
    print("\n" + "=" * 60)
    print("Testing Text Parser")
    print("=" * 60)

    # Create sample text file
    sample_text = """Introduction to AI

Artificial Intelligence (AI) is transforming the world.

Machine Learning
Machine learning is a subset of AI.

Deep Learning
Deep learning uses neural networks."""

    test_file = "/tmp/test_sample.txt"
    with open(test_file, 'w') as f:
        f.write(sample_text)

    # Process with pipeline
    pipeline = DocumentPipeline()
    result = pipeline.process(test_file)

    # Display results
    print(f"\nDocument: {result['document_id']}")
    print(f"Type: {result['doc_type']}")
    print(f"Total chunks: {result['metadata']['total_chunks']}")
    print(f"\nChunks:")
    for chunk in result['chunks']:
        print(f"\n  Chunk {chunk['chunk_id']}:")
        print(f"    Text: {chunk['text'][:100]}...")
        print(f"    Keywords: {chunk.get('keywords', [])}")
        print(f"    Section: {chunk['metadata'].get('section_name', 'N/A')}")

    # Cleanup
    os.remove(test_file)
    print("\n✅ Text parser test passed!")


def test_markdown_parser():
    """Test markdown parser with sample content."""
    print("\n" + "=" * 60)
    print("Testing Markdown Parser")
    print("=" * 60)

    # Create sample markdown file
    sample_md = """# AI Development Guide

This is an introduction to AI development.

## Machine Learning

Machine learning enables computers to learn from data.

### Supervised Learning

Supervised learning uses labeled data.

### Unsupervised Learning

Unsupervised learning finds patterns in unlabeled data.

## Deep Learning

Deep learning uses neural networks with multiple layers.
"""

    test_file = "/tmp/test_sample.md"
    with open(test_file, 'w') as f:
        f.write(sample_md)

    # Process with pipeline
    pipeline = DocumentPipeline()
    result = pipeline.process(test_file)

    # Display results
    print(f"\nDocument: {result['document_id']}")
    print(f"Type: {result['doc_type']}")
    print(f"Total chunks: {result['metadata']['total_chunks']}")
    print(f"\nChunks:")
    for chunk in result['chunks']:
        print(f"\n  Chunk {chunk['chunk_id']}:")
        print(f"    Text: {chunk['text'][:100]}...")
        print(f"    Keywords: {chunk.get('keywords', [])}")
        print(f"    Section: {chunk['metadata'].get('section_name', 'N/A')}")
        print(f"    Heading Level: {chunk['metadata'].get('heading_level', 'N/A')}")

    # Cleanup
    os.remove(test_file)
    print("\n✅ Markdown parser test passed!")


def test_code_parser():
    """Test code parser with Python sample."""
    print("\n" + "=" * 60)
    print("Testing Code Parser")
    print("=" * 60)

    # Create sample Python file
    sample_code = '''"""Sample Python module for testing."""
import os
import sys
from typing import List


def hello_world():
    """Print hello world."""
    print("Hello, World!")


class Calculator:
    """Simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def subtract(self, a: int, b: int) -> int:
        """Subtract two numbers."""
        return a - b
'''

    test_file = "/tmp/test_sample.py"
    with open(test_file, 'w') as f:
        f.write(sample_code)

    # Process with pipeline
    pipeline = DocumentPipeline()
    result = pipeline.process(test_file)

    # Display results
    print(f"\nDocument: {result['document_id']}")
    print(f"Type: {result['doc_type']}")
    print(f"Language: {result['metadata'].get('language', 'N/A')}")
    print(f"Total chunks: {result['metadata']['total_chunks']}")
    print(f"\nChunks:")
    for chunk in result['chunks']:
        print(f"\n  Chunk {chunk['chunk_id']}:")
        print(f"    Section: {chunk['metadata'].get('section_type', 'N/A')}")
        if chunk['metadata'].get('function_name'):
            print(f"    Function: {chunk['metadata']['function_name']}")
        if chunk['metadata'].get('class_name'):
            print(f"    Class: {chunk['metadata']['class_name']}")
        print(f"    Text: {chunk['text'][:80]}...")

    # Cleanup
    os.remove(test_file)
    print("\n✅ Code parser test passed!")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("MODULAR PARSER SYSTEM TEST")
    print("=" * 60)

    try:
        test_text_parser()
        test_markdown_parser()
        test_code_parser()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
