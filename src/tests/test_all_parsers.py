"""
Comprehensive holistic test suite for the modular parser system.

Tests all extractors, chunkers, enrichers, and formatters.
"""
import os
import sys
import tempfile
import json
from pathlib import Path

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(parent_dir.parent))  # Add parsers parent dir

# Now import as package
from src.models.document import RawDocument, Chunk, EnrichedChunk, ProcessedDocument
from src.extractors import (
    PDFExtractor, DOCXExtractor, PPTXExtractor,
    CodeExtractor, TextExtractor, MarkdownExtractor,
    ExcelExtractor, CSVExtractor, HTMLExtractor
)
from src.chunking.strategies import (
    PDFChunker, DOCXChunker, PPTXChunker,
    CodeChunker, TextChunker, MarkdownChunker,
    ExcelChunker, HTMLChunker
)
from src.enrichment import KeywordExtractor, SectionDetector, TitleGenerator, MetadataEnricher
from src.formatters import SimpleFormatter, WeaviateFormatter, Neo4jFormatter
from src.pipeline import DocumentPipeline


class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def add_pass(self, test_name):
        self.passed += 1
        print(f"  ✅ {test_name}")

    def add_fail(self, test_name, error):
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"  ❌ {test_name}: {error}")

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 70)
        print(f"TEST SUMMARY: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"\nFailed tests:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        print("=" * 70)
        return self.failed == 0


results = TestResults()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_temp_file(content, extension):
    """Create temporary file with content."""
    fd, path = tempfile.mkstemp(suffix=extension)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def cleanup_file(path):
    """Remove temporary file."""
    try:
        os.remove(path)
    except:
        pass


# ============================================================================
# TEST SAMPLES
# ============================================================================

SAMPLE_TEXT = """Introduction to Artificial Intelligence

Artificial Intelligence (AI) is revolutionizing technology. It enables machines to learn from experience and perform tasks that typically require human intelligence.

Machine Learning Fundamentals

Machine learning is a subset of AI that focuses on algorithms that improve through experience. It includes supervised learning, unsupervised learning, and reinforcement learning.

Deep Learning Architecture

Deep learning uses neural networks with multiple layers to process complex patterns in data. It has achieved remarkable results in image recognition and natural language processing.
"""

SAMPLE_MARKDOWN = """# AI Development Guide

This comprehensive guide covers modern AI development practices.

## Machine Learning

Machine learning enables computers to learn from data without explicit programming.

### Supervised Learning

Supervised learning uses labeled datasets to train models. Common algorithms include:
- Linear Regression
- Decision Trees
- Neural Networks

### Unsupervised Learning

Unsupervised learning finds patterns in unlabeled data.

## Deep Learning

Deep learning uses neural networks with multiple layers.

```python
import tensorflow as tf

model = tf.keras.Sequential([
    tf.keras.layers.Dense(128, activation='relu'),
    tf.keras.layers.Dense(10, activation='softmax')
])
```

## Conclusion

AI development requires understanding both theory and practice.
"""

SAMPLE_PYTHON = '''"""
Sample Python module for AI utilities.
"""
import numpy as np
from typing import List, Optional


class DataProcessor:
    """Process and transform data for ML models."""

    def __init__(self, normalize: bool = True):
        """Initialize processor."""
        self.normalize = normalize
        self.scaler = None

    def fit_transform(self, data: np.ndarray) -> np.ndarray:
        """Fit and transform data."""
        if self.normalize:
            self.scaler = np.std(data)
            return data / self.scaler
        return data

    def transform(self, data: np.ndarray) -> np.ndarray:
        """Transform new data."""
        if self.scaler is not None:
            return data / self.scaler
        return data


def calculate_accuracy(predictions: List[float], targets: List[float]) -> float:
    """Calculate model accuracy."""
    correct = sum(p == t for p, t in zip(predictions, targets))
    return correct / len(predictions)


def load_dataset(filepath: str) -> Optional[np.ndarray]:
    """Load dataset from file."""
    try:
        return np.load(filepath)
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return None
'''

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="description" content="Guide to machine learning">
    <meta name="author" content="AI Research Team">
    <meta property="og:title" content="ML Guide">
    <meta property="og:description" content="Comprehensive ML guide">
    <title>Machine Learning Guide</title>
</head>
<body>
    <nav>
        <ul>
            <li><a href="#intro">Introduction</a></li>
            <li><a href="#ml">Machine Learning</a></li>
        </ul>
    </nav>

    <article>
        <h1>Machine Learning Guide</h1>

        <section id="intro">
            <h2>Introduction</h2>
            <p>Machine learning is transforming technology by enabling computers to learn from data.</p>
        </section>

        <section id="ml">
            <h2>Machine Learning Basics</h2>
            <p>ML algorithms improve through experience and data.</p>

            <table border="1">
                <caption>ML Algorithm Types</caption>
                <thead>
                    <tr>
                        <th>Algorithm</th>
                        <th>Type</th>
                        <th>Use Case</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Linear Regression</td>
                        <td>Supervised</td>
                        <td>Prediction</td>
                    </tr>
                    <tr>
                        <td>K-Means</td>
                        <td>Unsupervised</td>
                        <td>Clustering</td>
                    </tr>
                </tbody>
            </table>
        </section>
    </article>

    <footer>
        <p>&copy; 2024 AI Research Team</p>
    </footer>
</body>
</html>
"""


# ============================================================================
# EXTRACTOR TESTS
# ============================================================================

def test_extractors():
    """Test all extractors."""
    print("\n" + "=" * 70)
    print("TESTING EXTRACTORS")
    print("=" * 70)

    # Test TextExtractor
    try:
        temp_file = create_temp_file(SAMPLE_TEXT, ".txt")
        extractor = TextExtractor()
        raw_doc = extractor.extract(temp_file)

        assert isinstance(raw_doc, RawDocument), "Should return RawDocument"
        assert len(raw_doc.text) > 0, "Should have text content"
        assert raw_doc.metadata.get("format") == "text", "Should have text format"
        assert raw_doc.structure is not None, "Should have structure"

        cleanup_file(temp_file)
        results.add_pass("TextExtractor")
    except Exception as e:
        results.add_fail("TextExtractor", str(e))

    # Test MarkdownExtractor
    try:
        temp_file = create_temp_file(SAMPLE_MARKDOWN, ".md")
        extractor = MarkdownExtractor()
        raw_doc = extractor.extract(temp_file)

        assert isinstance(raw_doc, RawDocument), "Should return RawDocument"
        assert len(raw_doc.text) > 0, "Should have text content"
        assert raw_doc.metadata.get("format") == "markdown", "Should have markdown format"
        assert "sections" in raw_doc.structure, "Should have sections"
        assert len(raw_doc.structure["sections"]) > 0, "Should detect sections"

        cleanup_file(temp_file)
        results.add_pass("MarkdownExtractor")
    except Exception as e:
        results.add_fail("MarkdownExtractor", str(e))

    # Test CodeExtractor
    try:
        temp_file = create_temp_file(SAMPLE_PYTHON, ".py")
        extractor = CodeExtractor()
        raw_doc = extractor.extract(temp_file)

        assert isinstance(raw_doc, RawDocument), "Should return RawDocument"
        assert len(raw_doc.text) > 0, "Should have code content"
        assert raw_doc.metadata.get("language") == "python", "Should detect Python"
        assert "imports" in raw_doc.structure, "Should have imports"
        assert "functions" in raw_doc.structure, "Should have functions"
        assert "classes" in raw_doc.structure, "Should have classes"
        assert len(raw_doc.structure["classes"]) > 0, "Should detect DataProcessor class"

        cleanup_file(temp_file)
        results.add_pass("CodeExtractor")
    except Exception as e:
        results.add_fail("CodeExtractor", str(e))


# ============================================================================
# CHUNKER TESTS
# ============================================================================

def test_chunkers():
    """Test all chunkers."""
    print("\n" + "=" * 70)
    print("TESTING CHUNKERS")
    print("=" * 70)

    # Test TextChunker
    try:
        temp_file = create_temp_file(SAMPLE_TEXT, ".txt")
        extractor = TextExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = TextChunker(target_size=50, use_semantic=True)
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 0, "Should create chunks"
        assert all(isinstance(c, Chunk) for c in chunks), "Should return Chunk objects"
        assert all(len(c.text) > 0 for c in chunks), "All chunks should have text"

        cleanup_file(temp_file)
        results.add_pass("TextChunker")
    except Exception as e:
        results.add_fail("TextChunker", str(e))

    # Test MarkdownChunker
    try:
        temp_file = create_temp_file(SAMPLE_MARKDOWN, ".md")
        extractor = MarkdownExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = MarkdownChunker(target_size=100, chunk_by_section=False)
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 0, "Should create chunks"
        assert all(isinstance(c, Chunk) for c in chunks), "Should return Chunk objects"
        # Check metadata preservation
        assert any("heading_level" in c.metadata for c in chunks), "Should preserve heading metadata"

        cleanup_file(temp_file)
        results.add_pass("MarkdownChunker")
    except Exception as e:
        results.add_fail("MarkdownChunker", str(e))

    # Test CodeChunker
    try:
        temp_file = create_temp_file(SAMPLE_PYTHON, ".py")
        extractor = CodeExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = CodeChunker(target_size=500)
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 0, "Should create chunks"
        # Should have imports, class, and functions as separate chunks
        section_types = [c.metadata.get("section_type") for c in chunks]
        assert "imports" in section_types, "Should have imports chunk"
        assert "class" in section_types or "function" in section_types, "Should have code chunks"

        cleanup_file(temp_file)
        results.add_pass("CodeChunker")
    except Exception as e:
        results.add_fail("CodeChunker", str(e))


# ============================================================================
# ENRICHER TESTS
# ============================================================================

def test_enrichers():
    """Test all enrichers."""
    print("\n" + "=" * 70)
    print("TESTING ENRICHERS")
    print("=" * 70)

    # Create sample chunks
    sample_chunks = [
        Chunk(
            chunk_id=0,
            text="Machine learning is a subset of artificial intelligence that enables computers to learn from data.",
            metadata={"section_type": "text"}
        ),
        Chunk(
            chunk_id=1,
            text="Deep learning uses neural networks with multiple layers to process complex patterns.",
            metadata={"section_type": "text"}
        )
    ]

    # Test KeywordExtractor
    try:
        enricher = KeywordExtractor(method="rake", top_k=5)
        enriched = enricher.enrich(sample_chunks)

        assert len(enriched) == len(sample_chunks), "Should maintain chunk count"
        assert all(isinstance(c, EnrichedChunk) for c in enriched), "Should return EnrichedChunk"
        assert all(len(c.keywords) > 0 for c in enriched), "Should extract keywords"

        # Check if relevant keywords are found
        all_keywords = [kw.lower() for c in enriched for kw in c.keywords]
        assert any("learning" in kw or "machine" in kw or "data" in kw for kw in all_keywords), \
            "Should extract relevant keywords"

        results.add_pass("KeywordExtractor")
    except Exception as e:
        results.add_fail("KeywordExtractor", str(e))

    # Test SectionDetector
    try:
        enricher = SectionDetector(method="heuristic")
        enriched = enricher.enrich(sample_chunks)

        assert len(enriched) == len(sample_chunks), "Should maintain chunk count"
        assert all(hasattr(c, "section_type") for c in enriched), "Should have section_type"

        results.add_pass("SectionDetector")
    except Exception as e:
        results.add_fail("SectionDetector", str(e))

    # Test TitleGenerator
    try:
        enricher = TitleGenerator(method="keywords")
        enriched = enricher.enrich(sample_chunks)

        assert len(enriched) == len(sample_chunks), "Should maintain chunk count"
        assert all(c.section_name is not None for c in enriched), "Should generate section names"
        assert not any(c.section_name == "Section 1" for c in enriched), \
            "Should not generate generic names"

        results.add_pass("TitleGenerator")
    except Exception as e:
        results.add_fail("TitleGenerator", str(e))

    # Test MetadataEnricher
    try:
        enricher = MetadataEnricher()
        enriched = enricher.enrich(sample_chunks)

        assert len(enriched) == len(sample_chunks), "Should maintain chunk count"
        assert all("word_count" in c.computed_metadata for c in enriched), \
            "Should compute word count"
        assert all(c.computed_metadata["word_count"] > 0 for c in enriched), \
            "Word count should be positive"

        results.add_pass("MetadataEnricher")
    except Exception as e:
        results.add_fail("MetadataEnricher", str(e))


# ============================================================================
# FORMATTER TESTS
# ============================================================================

def test_formatters():
    """Test all formatters."""
    print("\n" + "=" * 70)
    print("TESTING FORMATTERS")
    print("=" * 70)

    # Create sample processed document
    enriched_chunks = [
        EnrichedChunk(
            chunk_id=0,
            text="Machine learning enables computers to learn.",
            metadata={"section_type": "text"},
            keywords=["machine learning", "computers", "learn"],
            section_name="Machine Learning Introduction",
            section_type="text",
            computed_metadata={"word_count": 6}
        )
    ]

    processed_doc = ProcessedDocument(
        document_id="test_doc_123",
        source="/tmp/test.txt",
        doc_type="txt",
        chunks=enriched_chunks,
        metadata={"format": "text"}
    )

    # Test SimpleFormatter
    try:
        formatter = SimpleFormatter()
        result = formatter.format(processed_doc)

        assert isinstance(result, dict), "Should return dict"
        assert "document_id" in result, "Should have document_id"
        assert "chunks" in result, "Should have chunks"
        assert len(result["chunks"]) == 1, "Should maintain chunk count"
        assert "keywords" in result["chunks"][0], "Should preserve keywords"

        results.add_pass("SimpleFormatter")
    except Exception as e:
        results.add_fail("SimpleFormatter", str(e))

    # Test WeaviateFormatter
    try:
        formatter = WeaviateFormatter()
        result = formatter.format(processed_doc)

        assert isinstance(result, list), "Should return list"
        assert len(result) == 1, "Should have one object"
        assert "class" in result[0], "Should have class field"
        assert "properties" in result[0], "Should have properties"

        # Check metadata unpacking
        props = result[0]["properties"]
        assert "keywords" in props, "Should unpack keywords"
        assert "sectionName" in props, "Should unpack section_name"
        assert "sectionType" in props, "Should unpack section_type"

        results.add_pass("WeaviateFormatter")
    except Exception as e:
        results.add_fail("WeaviateFormatter", str(e))

    # Test Neo4jFormatter
    try:
        formatter = Neo4jFormatter()
        result = formatter.format(processed_doc)

        assert isinstance(result, dict), "Should return dict"
        assert "nodes" in result, "Should have nodes"
        assert "relationships" in result, "Should have relationships"
        assert len(result["nodes"]) > 0, "Should create nodes"

        # Check for Document and Chunk nodes
        node_labels = [node["labels"] for node in result["nodes"]]
        assert any("Document" in labels for labels in node_labels), "Should have Document node"
        assert any("Chunk" in labels for labels in node_labels), "Should have Chunk node"

        # Check metadata unpacking in chunk properties
        chunk_nodes = [n for n in result["nodes"] if "Chunk" in n["labels"]]
        assert len(chunk_nodes) > 0, "Should have chunk nodes"
        assert "keywords" in chunk_nodes[0]["properties"], "Should unpack keywords as property"
        assert "sectionName" in chunk_nodes[0]["properties"], "Should unpack section_name"

        results.add_pass("Neo4jFormatter")
    except Exception as e:
        results.add_fail("Neo4jFormatter", str(e))


# ============================================================================
# PIPELINE TESTS
# ============================================================================

def test_pipeline():
    """Test DocumentPipeline end-to-end."""
    print("\n" + "=" * 70)
    print("TESTING DOCUMENT PIPELINE")
    print("=" * 70)

    # Test with text file
    try:
        temp_file = create_temp_file(SAMPLE_TEXT, ".txt")
        pipeline = DocumentPipeline()
        result = pipeline.process(temp_file)

        assert isinstance(result, dict), "Should return dict"
        assert "document_id" in result, "Should have document_id"
        assert "chunks" in result, "Should have chunks"
        assert len(result["chunks"]) > 0, "Should create chunks"

        # Check enrichment
        chunk = result["chunks"][0]
        assert "keywords" in chunk, "Should have keywords"
        assert "metadata" in chunk, "Should have metadata"

        cleanup_file(temp_file)
        results.add_pass("Pipeline - Text file")
    except Exception as e:
        results.add_fail("Pipeline - Text file", str(e))

    # Test with markdown file
    try:
        temp_file = create_temp_file(SAMPLE_MARKDOWN, ".md")
        pipeline = DocumentPipeline()
        result = pipeline.process(temp_file)

        assert len(result["chunks"]) > 0, "Should create chunks"

        # Check heading preservation
        chunks_with_headings = [c for c in result["chunks"] if c["metadata"].get("heading_level", 0) > 0]
        assert len(chunks_with_headings) > 0, "Should preserve heading structure"

        cleanup_file(temp_file)
        results.add_pass("Pipeline - Markdown file")
    except Exception as e:
        results.add_fail("Pipeline - Markdown file", str(e))

    # Test with code file
    try:
        temp_file = create_temp_file(SAMPLE_PYTHON, ".py")
        pipeline = DocumentPipeline()
        result = pipeline.process(temp_file)

        assert len(result["chunks"]) > 0, "Should create chunks"

        # Check code structure preservation
        section_types = [c["metadata"].get("section_type") for c in result["chunks"]]
        assert "imports" in section_types or "class" in section_types or "function" in section_types, \
            "Should preserve code structure"

        cleanup_file(temp_file)
        results.add_pass("Pipeline - Python file")
    except Exception as e:
        results.add_fail("Pipeline - Python file", str(e))

    # Test with custom formatter
    try:
        temp_file = create_temp_file(SAMPLE_TEXT, ".txt")
        pipeline = DocumentPipeline(formatter=WeaviateFormatter())
        result = pipeline.process(temp_file)

        assert isinstance(result, list), "Should return list with WeaviateFormatter"
        assert len(result) > 0, "Should create Weaviate objects"
        assert "class" in result[0], "Should have Weaviate class"

        cleanup_file(temp_file)
        results.add_pass("Pipeline - Custom formatter")
    except Exception as e:
        results.add_fail("Pipeline - Custom formatter", str(e))


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

def test_integration():
    """Test integration features."""
    print("\n" + "=" * 70)
    print("TESTING INTEGRATION")
    print("=" * 70)

    # Test format detection
    try:
        pipeline = DocumentPipeline()

        supported_formats = pipeline.get_supported_formats()
        assert ".txt" in supported_formats, "Should support .txt"
        assert ".md" in supported_formats, "Should support .md"
        assert ".py" in supported_formats, "Should support .py"
        assert ".pdf" in supported_formats, "Should support .pdf"

        results.add_pass("Format detection")
    except Exception as e:
        results.add_fail("Format detection", str(e))

    # Test adapter
    try:
        from src.integration import ParserFactoryAdapter

        temp_file = create_temp_file(SAMPLE_TEXT, ".txt")
        parser = ParserFactoryAdapter.create_parser(temp_file)

        # Should work like old interface
        import asyncio
        chunks = asyncio.run(parser.parse(temp_file))

        assert isinstance(chunks, list), "Should return list"
        assert len(chunks) > 0, "Should have chunks"
        assert "text" in chunks[0], "Should have text field"

        cleanup_file(temp_file)
        results.add_pass("Integration adapter")
    except Exception as e:
        results.add_fail("Integration adapter", str(e))


# ============================================================================
# EXCEL/CSV TESTS
# ============================================================================

def test_excel_extractors():
    """Test Excel extractors."""
    print("\n" + "=" * 70)
    print("TESTING EXCEL EXTRACTORS")
    print("=" * 70)

    # Test ExcelExtractor if available
    if ExcelExtractor is None:
        print("  ⚠️  ExcelExtractor not available (openpyxl not installed)")
        return

    try:
        # Create sample Excel file
        try:
            from openpyxl import Workbook
        except ImportError:
            print("  ⚠️  openpyxl not installed, skipping Excel tests")
            return

        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Sales Data"

        # Add headers
        ws['A1'] = 'Product'
        ws['B1'] = 'Price'
        ws['C1'] = 'Quantity'

        # Add data
        ws['A2'] = 'Laptop'
        ws['B2'] = 1200
        ws['C2'] = 5

        ws['A3'] = 'Mouse'
        ws['B3'] = 25
        ws['C3'] = 50

        # Add formula
        ws['D1'] = 'Total'
        ws['D2'] = '=B2*C2'
        ws['D3'] = '=B3*C3'

        # Merge cells
        ws.merge_cells('A5:C5')
        ws['A5'] = 'Summary Section'

        # Save to temp file
        fd, temp_file = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(temp_file)

        # Test extraction
        extractor = ExcelExtractor(
            detect_tables=True,
            fill_merged_cells=True
        )
        raw_doc = extractor.extract(temp_file)

        assert isinstance(raw_doc, RawDocument), "Should return RawDocument"
        assert len(raw_doc.text) > 0, "Should have text content"
        assert raw_doc.metadata.get("format") == "excel", "Should have excel format"
        assert raw_doc.metadata.get("num_sheets", 0) > 0, "Should have sheets"
        assert "excel_metadata" in raw_doc.structure, "Should have excel_metadata"

        # Check formula detection
        excel_metadata = raw_doc.structure["excel_metadata"]
        assert excel_metadata.has_formulas, "Should detect formulas"

        # Check merged cells
        assert excel_metadata.has_merged_cells, "Should detect merged cells"

        cleanup_file(temp_file)
        results.add_pass("ExcelExtractor - Basic extraction")
    except Exception as e:
        results.add_fail("ExcelExtractor - Basic extraction", str(e))

    # Test multi-sheet extraction
    try:
        wb = Workbook()

        # Sheet 1
        ws1 = wb.active
        ws1.title = "Q1 Sales"
        ws1['A1'] = 'Product'
        ws1['B1'] = 'Revenue'
        ws1['A2'] = 'Product A'
        ws1['B2'] = 10000

        # Sheet 2
        ws2 = wb.create_sheet("Q2 Sales")
        ws2['A1'] = 'Product'
        ws2['B1'] = 'Revenue'
        ws2['A2'] = 'Product B'
        ws2['B2'] = 15000

        # Save
        fd, temp_file = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(temp_file)

        # Extract
        extractor = ExcelExtractor()
        raw_doc = extractor.extract(temp_file)

        assert raw_doc.metadata.get("num_sheets", 0) == 2, "Should detect 2 sheets"
        excel_metadata = raw_doc.structure["excel_metadata"]
        assert excel_metadata.has_multiple_sheets, "Should detect multiple sheets"

        cleanup_file(temp_file)
        results.add_pass("ExcelExtractor - Multi-sheet")
    except Exception as e:
        results.add_fail("ExcelExtractor - Multi-sheet", str(e))


def test_excel_chunkers():
    """Test Excel chunkers."""
    print("\n" + "=" * 70)
    print("TESTING EXCEL CHUNKERS")
    print("=" * 70)

    if ExcelExtractor is None or ExcelChunker is None:
        print("  ⚠️  Excel components not available")
        return

    try:
        from openpyxl import Workbook
    except ImportError:
        print("  ⚠️  openpyxl not installed, skipping Excel chunker tests")
        return

    # Test by_sheet strategy
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws['A1'] = 'Data'
        ws['A2'] = 'Value 1'
        ws['A3'] = 'Value 2'

        fd, temp_file = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(temp_file)

        extractor = ExcelExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = ExcelChunker(strategy="by_sheet")
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 0, "Should create chunks"
        assert all(isinstance(c, Chunk) for c in chunks), "Should return Chunk objects"
        assert chunks[0].metadata.get("chunk_strategy") == "by_sheet", "Should use by_sheet strategy"

        cleanup_file(temp_file)
        results.add_pass("ExcelChunker - by_sheet strategy")
    except Exception as e:
        results.add_fail("ExcelChunker - by_sheet strategy", str(e))

    # Test auto strategy
    try:
        wb = Workbook()
        ws = wb.active
        ws['A1'] = 'Large'
        ws['A2'] = 'Dataset'
        for i in range(3, 200):
            ws[f'A{i}'] = f'Row {i}'

        fd, temp_file = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(temp_file)

        extractor = ExcelExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = ExcelChunker(strategy="auto", chunk_size=100)
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 1, "Should split large sheet into multiple chunks"

        cleanup_file(temp_file)
        results.add_pass("ExcelChunker - auto strategy")
    except Exception as e:
        results.add_fail("ExcelChunker - auto strategy", str(e))


def test_csv_extractors():
    """Test CSV extractors."""
    print("\n" + "=" * 70)
    print("TESTING CSV EXTRACTORS")
    print("=" * 70)

    if CSVExtractor is None:
        print("  ⚠️  CSVExtractor not available")
        return

    # Test basic CSV extraction
    try:
        csv_content = """Name,Age,City
John Doe,30,New York
Jane Smith,25,Los Angeles
Bob Johnson,35,Chicago
"""
        temp_file = create_temp_file(csv_content, ".csv")

        extractor = CSVExtractor()
        raw_doc = extractor.extract(temp_file)

        assert isinstance(raw_doc, RawDocument), "Should return RawDocument"
        assert len(raw_doc.text) > 0, "Should have text content"
        assert raw_doc.metadata.get("format") == "csv", "Should have csv format"
        assert raw_doc.metadata.get("num_rows", 0) > 0, "Should have rows"
        assert raw_doc.metadata.get("num_columns", 0) == 3, "Should detect 3 columns"

        cleanup_file(temp_file)
        results.add_pass("CSVExtractor - Basic CSV")
    except Exception as e:
        results.add_fail("CSVExtractor - Basic CSV", str(e))

    # Test delimiter detection
    try:
        tsv_content = """Name\tAge\tCity
John\t30\tNY
Jane\t25\tLA
"""
        temp_file = create_temp_file(tsv_content, ".tsv")

        extractor = CSVExtractor()
        raw_doc = extractor.extract(temp_file)

        assert raw_doc.metadata.get("delimiter") == "\t", "Should detect tab delimiter"

        cleanup_file(temp_file)
        results.add_pass("CSVExtractor - Delimiter detection")
    except Exception as e:
        results.add_fail("CSVExtractor - Delimiter detection", str(e))


# ============================================================================
# HTML TESTS
# ============================================================================

def test_html_extractors():
    """Test HTML extractors."""
    print("\n" + "=" * 70)
    print("TESTING HTML EXTRACTORS")
    print("=" * 70)

    if HTMLExtractor is None:
        print("  ⚠️  HTMLExtractor not available (beautifulsoup4 not installed)")
        return

    # Test basic HTML extraction
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor(
            remove_boilerplate=False,  # Keep all content for testing
            extract_tables=True,
            extract_metadata=True
        )
        raw_doc = extractor.extract(temp_file)

        assert isinstance(raw_doc, RawDocument), "Should return RawDocument"
        assert len(raw_doc.text) > 0, "Should have text content"
        assert raw_doc.metadata.get("format") == "html", "Should have html format"

        cleanup_file(temp_file)
        results.add_pass("HTMLExtractor - Basic extraction")
    except Exception as e:
        results.add_fail("HTMLExtractor - Basic extraction", str(e))

    # Test table extraction
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor(extract_tables=True)
        raw_doc = extractor.extract(temp_file)

        html_doc = raw_doc.structure.get('html_document')
        assert html_doc is not None, "Should have html_document structure"
        assert html_doc.num_tables > 0, "Should extract tables"

        # Check table content
        table = html_doc.tables[0]
        assert table.caption == "ML Algorithm Types", "Should extract table caption"
        assert len(table.headers) == 3, "Should have 3 headers"
        assert table.num_rows == 2, "Should have 2 data rows"

        cleanup_file(temp_file)
        results.add_pass("HTMLExtractor - Table extraction")
    except Exception as e:
        results.add_fail("HTMLExtractor - Table extraction", str(e))

    # Test metadata extraction
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor(extract_metadata=True)
        raw_doc = extractor.extract(temp_file)

        html_doc = raw_doc.structure.get('html_document')
        metadata = html_doc.metadata

        assert metadata.title == "Machine Learning Guide", "Should extract title"
        assert metadata.author == "AI Research Team", "Should extract author"
        assert metadata.description == "Guide to machine learning", "Should extract description"
        assert "og:title" in metadata.open_graph, "Should extract Open Graph data"

        cleanup_file(temp_file)
        results.add_pass("HTMLExtractor - Metadata extraction")
    except Exception as e:
        results.add_fail("HTMLExtractor - Metadata extraction", str(e))

    # Test semantic sections
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor(preserve_structure=True)
        raw_doc = extractor.extract(temp_file)

        html_doc = raw_doc.structure.get('html_document')
        assert html_doc.num_sections > 0, "Should detect sections"
        assert html_doc.has_article, "Should detect article tag"
        assert html_doc.has_nav, "Should detect nav tag"

        cleanup_file(temp_file)
        results.add_pass("HTMLExtractor - Semantic sections")
    except Exception as e:
        results.add_fail("HTMLExtractor - Semantic sections", str(e))


def test_html_chunkers():
    """Test HTML chunkers."""
    print("\n" + "=" * 70)
    print("TESTING HTML CHUNKERS")
    print("=" * 70)

    if HTMLExtractor is None or HTMLChunker is None:
        print("  ⚠️  HTML components not available")
        return

    # Test semantic strategy
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = HTMLChunker(strategy="semantic")
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 0, "Should create chunks"
        assert all(isinstance(c, Chunk) for c in chunks), "Should return Chunk objects"

        # Check for semantic chunking
        has_section_tags = any(
            c.metadata.get("section_tag") in ["article", "section", "nav"]
            for c in chunks
        )
        assert has_section_tags, "Should chunk by semantic sections"

        cleanup_file(temp_file)
        results.add_pass("HTMLChunker - semantic strategy")
    except Exception as e:
        results.add_fail("HTMLChunker - semantic strategy", str(e))

    # Test auto strategy
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor()
        raw_doc = extractor.extract(temp_file)

        chunker = HTMLChunker(strategy="auto")
        chunks = chunker.chunk(raw_doc)

        assert len(chunks) > 0, "Should create chunks with auto strategy"

        cleanup_file(temp_file)
        results.add_pass("HTMLChunker - auto strategy")
    except Exception as e:
        results.add_fail("HTMLChunker - auto strategy", str(e))

    # Test table separation
    try:
        temp_file = create_temp_file(SAMPLE_HTML, ".html")

        extractor = HTMLExtractor(extract_tables=True)
        raw_doc = extractor.extract(temp_file)

        chunker = HTMLChunker(
            strategy="auto",
            include_tables_separately=True
        )
        chunks = chunker.chunk(raw_doc)

        # Check if tables are separate chunks
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table"]
        assert len(table_chunks) > 0, "Should create separate table chunks"

        cleanup_file(temp_file)
        results.add_pass("HTMLChunker - table separation")
    except Exception as e:
        results.add_fail("HTMLChunker - table separation", str(e))


def test_table_extraction():
    """Test table extraction from multiple formats."""
    print("\n" + "=" * 70)
    print("TESTING TABLE EXTRACTION")
    print("=" * 70)

    # Test HTML table to HTML format
    if HTMLExtractor is not None:
        try:
            temp_file = create_temp_file(SAMPLE_HTML, ".html")

            extractor = HTMLExtractor(extract_tables=True)
            raw_doc = extractor.extract(temp_file)

            html_doc = raw_doc.structure.get('html_document')
            table = html_doc.tables[0]

            # Convert to HTML
            html_output = table.to_html()
            assert "<table" in html_output, "Should generate HTML table"
            assert "<thead>" in html_output, "Should have thead"
            assert "<tbody>" in html_output, "Should have tbody"
            assert table.caption in html_output, "Should include caption"

            cleanup_file(temp_file)
            results.add_pass("Table extraction - HTML table to HTML")
        except Exception as e:
            results.add_fail("Table extraction - HTML table to HTML", str(e))

    # Test Excel table detection
    if ExcelExtractor is not None:
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active

            # Create table
            ws['A1'] = 'Header1'
            ws['B1'] = 'Header2'
            ws['C1'] = 'Header3'
            ws['A2'] = 'Data1'
            ws['B2'] = 'Data2'
            ws['C2'] = 'Data3'

            fd, temp_file = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            wb.save(temp_file)

            extractor = ExcelExtractor(detect_tables=True)
            raw_doc = extractor.extract(temp_file)

            excel_metadata = raw_doc.structure["excel_metadata"]
            assert len(excel_metadata.active_sheets) > 0, "Should have sheets"
            sheet_info = excel_metadata.active_sheets[0]
            assert sheet_info.num_tables > 0, "Should detect tables in sheet"

            cleanup_file(temp_file)
            results.add_pass("Table extraction - Excel table detection")
        except Exception as e:
            results.add_fail("Table extraction - Excel table detection", str(e))


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("MODULAR PARSER SYSTEM - COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    try:
        # Test core parsers
        test_extractors()
        test_chunkers()
        test_enrichers()
        test_formatters()
        test_pipeline()
        test_integration()

        # Test new formats (Excel, CSV, HTML)
        test_excel_extractors()
        test_excel_chunkers()
        test_csv_extractors()
        test_html_extractors()
        test_html_chunkers()
        test_table_extraction()

        success = results.summary()

        if success:
            print("\n🎉 ALL TESTS PASSED! The parser system is working correctly.")
            return 0
        else:
            print(f"\n⚠️  {results.failed} test(s) failed. Please review the errors above.")
            return 1

    except Exception as e:
        print(f"\n💥 TEST SUITE CRASHED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
