"""
Tests for TOON (Token-Optimized Object Notation) formatter.
"""
import pytest

from src.formatters.toon_formatter import TOONFormatter
from src.models.document import EnrichedChunk, ProcessedDocument


class TestTOONFormatter:
    """Test cases for TOONFormatter class."""

    def test_format_basic_document(self):
        """Test basic document formatting."""
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="Test content for the first chunk.",
                start_char=0,
                end_char=33,
                keywords=["test", "content"],
                section_name="Introduction",
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="test.pdf",
            source="/path/test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={"author": "John Doe", "title": "Test Document"}
        )

        formatter = TOONFormatter()
        result = formatter.format(doc)

        # Check header
        assert "d:test.pdf" in result
        assert "t:pdf" in result

        # Check metadata
        assert "m:" in result
        assert "author=John Doe" in result
        assert "title=Test Document" in result

        # Check chunk separator
        assert "---" in result

        # Check chunk header
        assert "1|0-33|text|Introduction" in result

        # Check content
        assert "Test content for the first chunk." in result

        # Check keywords
        assert "k:test,content" in result

    def test_format_multiple_chunks(self):
        """Test formatting with multiple chunks."""
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="First chunk.",
                start_char=0,
                end_char=12,
                keywords=["first"],
                section_name="Intro",
                section_type="text"
            ),
            EnrichedChunk(
                chunk_id=2,
                text="Second chunk.",
                start_char=12,
                end_char=25,
                keywords=["second"],
                section_name="Body",
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="multi.pdf",
            source="/path/multi.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={}
        )

        formatter = TOONFormatter()
        result = formatter.format(doc)

        # Count chunk separators
        assert result.count("---") == 2

        # Check both chunks present
        assert "1|0-12|text|Intro" in result
        assert "2|12-25|text|Body" in result
        assert "First chunk." in result
        assert "Second chunk." in result

    def test_escape_pipe_character(self):
        """Test escaping of pipe character in fields."""
        formatter = TOONFormatter()
        assert formatter._escape_field("test|pipe") == "test\\|pipe"
        assert formatter._escape_field("no pipe") == "no pipe"

    def test_escape_newline_in_fields(self):
        """Test escaping of newline in single-line fields."""
        formatter = TOONFormatter()
        assert formatter._escape_field("line1\nline2") == "line1 line2"

    def test_escape_comma_in_values(self):
        """Test escaping of comma in metadata values."""
        formatter = TOONFormatter()
        assert formatter._escape_value("a,b,c") == "a\\,b\\,c"

    def test_escape_equals_in_values(self):
        """Test escaping of equals sign in metadata values."""
        formatter = TOONFormatter()
        assert formatter._escape_value("key=value") == "key\\=value"

    def test_format_without_keywords(self):
        """Test formatting with keywords disabled."""
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="Test content",
                start_char=0,
                end_char=12,
                keywords=["test", "content"],
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="test.pdf",
            source="/path/test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={}
        )

        formatter = TOONFormatter(include_keywords=False)
        result = formatter.format(doc)

        # Keywords should not be present
        assert "k:" not in result

    def test_format_without_metadata(self):
        """Test formatting with metadata disabled."""
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="Test",
                start_char=0,
                end_char=4,
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="test.pdf",
            source="/path/test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={"author": "John"}
        )

        formatter = TOONFormatter(include_metadata=False)
        result = formatter.format(doc)

        # Metadata line should not be present
        assert "m:" not in result

    def test_format_with_text_preview_limit(self):
        """Test text truncation with max_text_preview."""
        long_text = "A" * 100
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text=long_text,
                start_char=0,
                end_char=100,
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="test.pdf",
            source="/path/test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={}
        )

        formatter = TOONFormatter(max_text_preview=20)
        result = formatter.format(doc)

        # Text should be truncated with ellipsis
        assert "A" * 20 + "..." in result
        assert "A" * 21 not in result

    def test_format_chunks_only(self):
        """Test format_chunks method without document wrapper."""
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="Chunk 1",
                start_char=0,
                end_char=7,
                section_type="text"
            ),
            EnrichedChunk(
                chunk_id=2,
                text="Chunk 2",
                start_char=7,
                end_char=14,
                section_type="text"
            )
        ]

        formatter = TOONFormatter()
        result = formatter.format_chunks(chunks)

        # Should have chunks but no document header
        assert "d:" not in result
        assert "---" in result
        assert "Chunk 1" in result
        assert "Chunk 2" in result

    def test_format_raw_document_basic(self):
        """Test static format_raw method."""
        result = TOONFormatter.format_raw(
            file_path="/path/to/test.pdf",
            text="Sample document text content.",
            metadata={"author": "Jane Doe", "title": "Sample Doc"},
            doc_type="pdf",
            total_chars=29,
            total_words=4,
            page_count=5
        )

        assert "d:test.pdf" in result
        assert "t:pdf" in result
        assert "w:4" in result
        assert "c:29" in result
        assert "p:5" in result
        assert "author=Jane Doe" in result
        assert "---" in result
        assert "Sample document text content." in result

    def test_format_raw_with_truncation(self):
        """Test format_raw with truncation hint."""
        result = TOONFormatter.format_raw(
            file_path="report.pdf",
            text="Truncated content...",
            metadata={},
            doc_type="pdf",
            total_chars=10000,
            total_words=2000,
            truncated=True,
            continuation_offset=5000
        )

        # Should have continuation hint
        assert "~+" in result
        assert "5000chars" in result
        assert "get_document_chunk" in result

    def test_format_raw_with_images(self):
        """Test format_raw with image count."""
        result = TOONFormatter.format_raw(
            file_path="images.pdf",
            text="Document with images",
            metadata={},
            doc_type="pdf",
            total_chars=20,
            total_words=3,
            page_count=3,
            image_count=5
        )

        assert "i:5" in result

    def test_format_metadata_only(self):
        """Test format_metadata_only static method."""
        result = TOONFormatter.format_metadata_only(
            file_path="/path/to/doc.pdf",
            metadata={
                "author": "Test Author",
                "title": "Test Title",
                "page_count": 10,
                "created": "2024-01-15"
            },
            doc_type="pdf",
            total_chars=5000,
            page_count=10
        )

        assert "d:doc.pdf" in result
        assert "t:pdf" in result
        assert "c:5000" in result
        assert "p:10" in result
        assert "m:" in result
        assert "author=Test Author" in result

    def test_format_chunk_response(self):
        """Test format_chunk_response static method."""
        result = TOONFormatter.format_chunk_response(
            file_path="/path/doc.pdf",
            text="This is the chunk content.",
            offset=1000,
            limit=500,
            total_chars=5000,
            has_more=True
        )

        assert "d:doc.pdf" in result
        assert "offset:1000" in result
        assert "limit:500" in result
        assert "total:5000" in result
        assert "~+" in result  # Continuation hint
        assert "next:get_document_chunk" in result
        assert "---" in result
        assert "This is the chunk content." in result

    def test_format_chunk_response_no_more(self):
        """Test format_chunk_response when has_more is False."""
        result = TOONFormatter.format_chunk_response(
            file_path="/path/doc.pdf",
            text="Final chunk.",
            offset=4500,
            limit=500,
            total_chars=5000,
            has_more=False
        )

        # Should not have continuation hint
        assert "~+" not in result
        assert "next:" not in result
        assert "Final chunk." in result

    def test_empty_section_name(self):
        """Test handling of empty section name."""
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="Content",
                start_char=0,
                end_char=7,
                section_name=None,
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="test.pdf",
            source="/path/test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={}
        )

        formatter = TOONFormatter()
        result = formatter.format(doc)

        # Section name should be empty
        assert "1|0-7|text|" in result

    def test_keyword_limit(self):
        """Test that keywords are limited to 10."""
        many_keywords = [f"kw{i}" for i in range(20)]
        chunks = [
            EnrichedChunk(
                chunk_id=1,
                text="Content",
                start_char=0,
                end_char=7,
                keywords=many_keywords,
                section_type="text"
            )
        ]
        doc = ProcessedDocument(
            document_id="test.pdf",
            source="/path/test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={}
        )

        formatter = TOONFormatter()
        result = formatter.format(doc)

        # Should have max 10 keywords
        keywords_line = [line for line in result.split("\n") if line.startswith("k:")][0]
        keyword_count = keywords_line.count(",") + 1
        assert keyword_count == 10


class TestTOONTokenEfficiency:
    """Tests to verify TOON format is more token-efficient than JSON."""

    def test_toon_shorter_than_json(self):
        """Verify TOON output is shorter than equivalent JSON."""
        import json

        chunks = [
            EnrichedChunk(
                chunk_id=i,
                text=f"This is chunk {i} with some content.",
                start_char=i * 100,
                end_char=(i + 1) * 100,
                keywords=[f"keyword{i}", "test"],
                section_name=f"Section {i}",
                section_type="text"
            )
            for i in range(5)
        ]
        doc = ProcessedDocument(
            document_id="efficiency_test.pdf",
            source="/path/efficiency_test.pdf",
            doc_type="pdf",
            chunks=chunks,
            metadata={"author": "Test Author", "title": "Efficiency Test"}
        )

        # Get TOON output
        formatter = TOONFormatter()
        toon_output = formatter.format(doc)

        # Get equivalent JSON output
        json_output = json.dumps({
            "document_id": doc.document_id,
            "source": doc.source,
            "doc_type": doc.doc_type,
            "total_chunks": len(chunks),
            "total_words": doc.total_words,
            "metadata": doc.metadata,
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "start_char": c.start_char,
                    "end_char": c.end_char,
                    "keywords": c.keywords,
                    "section_name": c.section_name,
                    "section_type": c.section_type
                }
                for c in chunks
            ]
        }, indent=2)

        # TOON should be significantly shorter
        assert len(toon_output) < len(json_output)

        # Calculate reduction percentage
        reduction = (1 - len(toon_output) / len(json_output)) * 100
        print(f"\nToken reduction: {reduction:.1f}%")
        print(f"TOON length: {len(toon_output)}")
        print(f"JSON length: {len(json_output)}")

        # Expect at least 30% reduction
        assert reduction > 30, f"Expected >30% reduction, got {reduction:.1f}%"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
