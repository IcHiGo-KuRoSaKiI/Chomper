"""
Example: HTML parsing with the parsers module.

Demonstrates:
- HTML file parsing (boilerplate removal, article extraction)
- Table extraction from HTML
- Semantic section detection
- Different chunking strategies
- Metadata extraction (meta tags, Open Graph)
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

from pipeline import DocumentPipeline


def create_sample_html():
    """Create a sample HTML file for testing."""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="description" content="A comprehensive guide to machine learning">
    <meta name="author" content="Jane Doe">
    <meta name="keywords" content="machine learning, AI, neural networks">
    <meta property="og:title" content="Machine Learning Guide">
    <meta property="og:description" content="Learn the fundamentals of ML">
    <title>Machine Learning: A Comprehensive Guide</title>
</head>
<body>
    <nav>
        <ul>
            <li><a href="#intro">Introduction</a></li>
            <li><a href="#concepts">Core Concepts</a></li>
            <li><a href="#algorithms">Algorithms</a></li>
        </ul>
    </nav>

    <article>
        <header>
            <h1>Machine Learning: A Comprehensive Guide</h1>
            <p class="author">By Jane Doe</p>
            <p class="date">Published: January 15, 2024</p>
        </header>

        <section id="intro">
            <h2>Introduction</h2>
            <p>Machine learning is a subset of artificial intelligence that focuses on the development of algorithms that can learn from and make predictions on data.</p>
            <p>This guide covers the fundamental concepts and algorithms used in modern machine learning systems.</p>
        </section>

        <section id="concepts">
            <h2>Core Concepts</h2>
            <p>Understanding the following concepts is essential for working with machine learning:</p>

            <h3>Supervised Learning</h3>
            <p>Supervised learning involves training a model on labeled data, where each example has a known output.</p>

            <table border="1">
                <caption>Common Supervised Learning Algorithms</caption>
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
                        <td>Regression</td>
                        <td>Predicting continuous values</td>
                    </tr>
                    <tr>
                        <td>Logistic Regression</td>
                        <td>Classification</td>
                        <td>Binary classification</td>
                    </tr>
                    <tr>
                        <td>Random Forest</td>
                        <td>Both</td>
                        <td>General purpose</td>
                    </tr>
                </tbody>
            </table>

            <h3>Unsupervised Learning</h3>
            <p>Unsupervised learning works with unlabeled data to discover hidden patterns.</p>
            <ul>
                <li>Clustering (K-means, DBSCAN)</li>
                <li>Dimensionality Reduction (PCA, t-SNE)</li>
                <li>Anomaly Detection</li>
            </ul>
        </section>

        <section id="algorithms">
            <h2>Key Algorithms</h2>
            <p>Here are some of the most important machine learning algorithms:</p>

            <ol>
                <li>Neural Networks - Inspired by biological neurons</li>
                <li>Support Vector Machines - Finds optimal decision boundaries</li>
                <li>Decision Trees - Tree-based classification and regression</li>
                <li>Gradient Boosting - Ensemble method for high accuracy</li>
            </ol>
        </section>

        <aside>
            <h3>Quick Tip</h3>
            <p>Always start with simple models before moving to complex ones. Linear regression is a great baseline!</p>
        </aside>
    </article>

    <footer>
        <p>&copy; 2024 ML Education. All rights reserved.</p>
    </footer>
</body>
</html>
"""

    html_file = Path("sample_article.html")
    html_file.write_text(html_content, encoding='utf-8')
    return html_file


def create_simple_html():
    """Create a simple HTML file without semantic tags."""
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Simple Web Page</title>
</head>
<body>
    <h1>Welcome to My Website</h1>
    <p>This is a paragraph with some text.</p>

    <h2>About Us</h2>
    <p>We are a company that does great things.</p>
    <p>Our mission is to make the world better.</p>

    <h2>Our Products</h2>
    <p>We offer the following products:</p>
    <ul>
        <li>Product A</li>
        <li>Product B</li>
        <li>Product C</li>
    </ul>

    <h2>Contact</h2>
    <p>Email us at: contact@example.com</p>
</body>
</html>
"""

    html_file = Path("simple_page.html")
    html_file.write_text(html_content, encoding='utf-8')
    return html_file


def example_1_basic_html_parsing():
    """Example 1: Basic HTML parsing with boilerplate removal."""
    print("\n" + "="*60)
    print("Example 1: Basic HTML Parsing")
    print("="*60)

    # Create sample HTML
    html_file = create_sample_html()

    try:
        # Create pipeline
        pipeline = DocumentPipeline()

        # Process HTML
        result = pipeline.process(str(html_file))

        print(f"\n✓ Successfully parsed HTML file")
        print(f"  Format: {result['metadata']['format']}")
        print(f"  Title: {result['metadata'].get('title', 'N/A')}")
        print(f"  Author: {result['metadata'].get('author', 'N/A')}")
        print(f"  Description: {result['metadata'].get('description', 'N/A')}")
        print(f"  Total chunks: {result['metadata']['total_chunks']}")

        print(f"\n  Document structure:")
        print(f"    Tables: {result['metadata'].get('num_tables', 0)}")
        print(f"    Lists: {result['metadata'].get('num_lists', 0)}")
        print(f"    Sections: {result['metadata'].get('num_sections', 0)}")
        print(f"    Headings: {result['metadata'].get('num_headings', 0)}")
        print(f"    Is article: {result['metadata'].get('is_article', False)}")

        print(f"\n  First chunk preview:")
        first_chunk = result['chunks'][0]
        print(f"    Text (first 200 chars): {first_chunk['text'][:200]}...")
        print(f"    Strategy: {first_chunk['metadata'].get('chunk_strategy', 'N/A')}")

    finally:
        # Cleanup
        html_file.unlink(missing_ok=True)


def example_2_table_extraction():
    """Example 2: HTML table extraction."""
    print("\n" + "="*60)
    print("Example 2: Table Extraction")
    print("="*60)

    html_file = create_sample_html()

    try:
        from extractors.html_extractor import HTMLExtractor

        # Extract with table extraction enabled
        extractor = HTMLExtractor(extract_tables=True)
        raw_doc = extractor.extract(str(html_file))

        html_doc = raw_doc.structure['html_document']

        print(f"\n✓ Extracted {len(html_doc.tables)} table(s)")

        for idx, table in enumerate(html_doc.tables):
            print(f"\n  Table {idx}:")
            print(f"    Caption: {table.caption}")
            print(f"    Size: {table.num_rows} rows × {table.num_cols} columns")
            print(f"    Has headers: {table.has_headers}")
            print(f"    Headers: {table.headers}")
            print(f"\n    First row: {table.rows[0] if table.rows else 'N/A'}")

            print(f"\n    HTML representation:")
            print(f"    {table.to_html()[:200]}...")

    finally:
        html_file.unlink(missing_ok=True)


def example_3_semantic_chunking():
    """Example 3: Semantic section-based chunking."""
    print("\n" + "="*60)
    print("Example 3: Semantic Chunking")
    print("="*60)

    html_file = create_sample_html()

    try:
        from chunking.strategies.html_chunker import HTMLChunker
        from extractors.html_extractor import HTMLExtractor

        # Extract
        extractor = HTMLExtractor()
        raw_doc = extractor.extract(str(html_file))

        # Chunk by semantic sections
        chunker = HTMLChunker(strategy="semantic")
        chunks = chunker.chunk(raw_doc)

        print(f"\n✓ Created {len(chunks)} semantic chunks")

        for idx, chunk in enumerate(chunks[:5]):  # Show first 5
            print(f"\n  Chunk {idx}:")
            section_tag = chunk.metadata.get('section_tag', 'N/A')
            section_heading = chunk.metadata.get('section_heading', 'N/A')
            print(f"    Tag: <{section_tag}>")
            print(f"    Heading: {section_heading}")
            print(f"    Text preview: {chunk.text[:150]}...")

    finally:
        html_file.unlink(missing_ok=True)


def example_4_chunking_strategies():
    """Example 4: Comparing different chunking strategies."""
    print("\n" + "="*60)
    print("Example 4: Chunking Strategy Comparison")
    print("="*60)

    html_file = create_simple_html()

    try:
        from chunking.strategies.html_chunker import HTMLChunker
        from extractors.html_extractor import HTMLExtractor

        # Extract
        extractor = HTMLExtractor()
        raw_doc = extractor.extract(str(html_file))

        # Try different strategies
        strategies = ["auto", "semantic", "structural", "fixed_size"]

        for strategy in strategies:
            chunker = HTMLChunker(strategy=strategy, chunk_size=500)
            chunks = chunker.chunk(raw_doc)

            print(f"\n  Strategy: {strategy}")
            print(f"    Total chunks: {len(chunks)}")

            for idx, chunk in enumerate(chunks[:2]):  # Show first 2
                actual_strategy = chunk.metadata.get('chunk_strategy', 'N/A')
                chunk_type = chunk.metadata.get('chunk_type', 'text')
                print(f"    Chunk {idx}: {actual_strategy} ({chunk_type}) - {len(chunk.text)} chars")

    finally:
        html_file.unlink(missing_ok=True)


def example_5_metadata_extraction():
    """Example 5: Extracting metadata from HTML."""
    print("\n" + "="*60)
    print("Example 5: Metadata Extraction")
    print("="*60)

    html_file = create_sample_html()

    try:
        from extractors.html_extractor import HTMLExtractor

        # Extract with metadata
        extractor = HTMLExtractor(extract_metadata=True)
        raw_doc = extractor.extract(str(html_file))

        html_doc = raw_doc.structure['html_document']
        metadata = html_doc.metadata

        print(f"\n✓ Extracted metadata:")
        print(f"    Title: {metadata.title}")
        print(f"    Description: {metadata.description}")
        print(f"    Author: {metadata.author}")
        print(f"    Language: {metadata.language}")
        print(f"    Keywords: {', '.join(metadata.keywords)}")

        print(f"\n  Open Graph data:")
        for key, value in metadata.open_graph.items():
            print(f"    og:{key} = {value}")

    finally:
        html_file.unlink(missing_ok=True)


def example_6_full_pipeline():
    """Example 6: Full pipeline with all features."""
    print("\n" + "="*60)
    print("Example 6: Full Pipeline with All Features")
    print("="*60)

    html_file = create_sample_html()

    try:
        from extractors.html_extractor import HTMLExtractor
        from chunking.strategies.html_chunker import HTMLChunker
        from formatters import SimpleFormatter

        # Custom extractor with all features
        extractor = HTMLExtractor(
            remove_boilerplate=True,
            extract_tables=True,
            extract_lists=True,
            extract_forms=True,
            extract_links=True,
            extract_metadata=True,
            preserve_structure=True
        )

        # Extract
        raw_doc = extractor.extract(str(html_file))

        # Custom chunker
        chunker = HTMLChunker(
            strategy="auto",
            include_tables_separately=True
        )

        # Chunk
        chunks = chunker.chunk(raw_doc)

        # Format
        formatter = SimpleFormatter()
        result = formatter.format_chunks(chunks, raw_doc.metadata)

        print(f"\n✓ Full pipeline completed")
        print(f"    Total chunks: {len(chunks)}")

        # Show chunk breakdown
        chunk_types = {}
        for chunk in chunks:
            chunk_type = chunk.metadata.get('chunk_type', 'text')
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1

        print(f"\n  Chunk breakdown:")
        for chunk_type, count in chunk_types.items():
            print(f"    {chunk_type}: {count}")

        print(f"\n  Sample chunks:")
        for idx, chunk in enumerate(chunks[:3]):
            strategy = chunk.metadata.get('chunk_strategy', 'N/A')
            chunk_type = chunk.metadata.get('chunk_type', 'text')
            print(f"    Chunk {idx}: {strategy} ({chunk_type}) - {len(chunk.text)} chars")

    finally:
        html_file.unlink(missing_ok=True)


def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("HTML Parsing Examples")
    print("="*60)

    print("\nℹ️  These examples demonstrate:")
    print("  - HTML parsing with boilerplate removal")
    print("  - Table extraction and conversion")
    print("  - Semantic section detection")
    print("  - Multiple chunking strategies")
    print("  - Metadata extraction (meta tags, Open Graph)")
    print("  - Full pipeline integration")

    # Run examples
    try:
        example_1_basic_html_parsing()
        example_2_table_extraction()
        example_3_semantic_chunking()
        example_4_chunking_strategies()
        example_5_metadata_extraction()
        example_6_full_pipeline()

        print("\n" + "="*60)
        print("✓ All examples completed successfully!")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
