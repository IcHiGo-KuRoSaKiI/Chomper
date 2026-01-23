"""
Code chunker with AST-aware structure preservation.

Chunks code files while preserving:
- Function boundaries
- Class boundaries
- Import sections
- Logical code units
"""

from ...models.document import Chunk, RawDocument
from ..base import BaseChunker


class CodeChunker(BaseChunker):
    """
    Chunk code files preserving logical structure.

    Strategy:
    - Chunk 0: Imports section
    - Chunk N: One function per chunk (or split if too large)
    - Chunk M: One class per chunk (or split if too large)
    - Fallback: Simple chunking if no structure detected
    """

    def __init__(
        self,
        target_size: int = 1000,  # Characters for code
        overlap: int = 200,
        preserve_context: bool = True
    ):
        """
        Initialize code chunker.

        Args:
            target_size: Target characters per chunk
            overlap: Characters to overlap
            preserve_context: Maintain code context
        """
        super().__init__(target_size, overlap, preserve_context)

    def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Chunk code document.

        Args:
            raw_doc: Raw code document

        Returns:
            List of chunks with code structure preserved
        """
        if not raw_doc.structure:
            # Fallback to simple chunking
            return self._simple_chunk(raw_doc)

        language = raw_doc.metadata.get("language", "unknown")
        structure = raw_doc.structure
        content = raw_doc.text
        lines = content.splitlines()

        chunks = []
        chunk_id = 0

        # Chunk 0: Imports section
        imports = structure.get("imports", [])
        if imports:
            import_chunk = self._create_imports_chunk(chunk_id, imports, lines, language)
            if import_chunk:
                chunks.append(import_chunk)
                chunk_id += 1

        # Chunk functions
        for func in structure.get("functions", []):
            func_chunks = self._chunk_function(chunk_id, func, lines, language)
            chunks.extend(func_chunks)
            chunk_id += len(func_chunks)

        # Chunk classes
        for cls in structure.get("classes", []):
            cls_chunks = self._chunk_class(chunk_id, cls, lines, language)
            chunks.extend(cls_chunks)
            chunk_id += len(cls_chunks)

        # If no structure found, fallback to simple chunking
        if len(chunks) == 0:
            return self._simple_chunk(raw_doc)

        return chunks

    def _create_imports_chunk(
        self,
        chunk_id: int,
        imports: list[dict],
        lines: list[str],
        language: str
    ) -> Chunk:
        """
        Create chunk for imports section.

        Args:
            chunk_id: Chunk ID
            imports: List of imports
            lines: File lines
            language: Programming language

        Returns:
            Chunk or None
        """
        if not imports:
            return None

        # Find max import line
        import_lines = [imp.get("line", 0) for imp in imports]
        max_import_line = max(import_lines)

        # Get imports section
        import_text = '\n'.join(lines[:max_import_line])

        if not import_text.strip():
            return None

        return self._create_chunk(
            chunk_id=chunk_id,
            text=import_text,
            metadata={
                "section_type": "imports",
                "language": language,
                "line_start": 1,
                "line_end": max_import_line,
                "chunk_strategy": "imports"
            }
        )

    def _chunk_function(
        self,
        start_chunk_id: int,
        func: dict,
        lines: list[str],
        language: str
    ) -> list[Chunk]:
        """
        Chunk a function.

        Args:
            start_chunk_id: Starting chunk ID
            func: Function dictionary
            lines: File lines
            language: Programming language

        Returns:
            List of chunks
        """
        line_start = func.get("line_start", 1)
        line_end = func.get("line_end", len(lines))

        # Extract function text
        func_lines = lines[line_start - 1:line_end]
        func_text = '\n'.join(func_lines)

        # If small enough, single chunk
        if len(func_text) <= self.target_size:
            return [self._create_chunk(
                chunk_id=start_chunk_id,
                text=func_text,
                metadata={
                    "section_type": "function",
                    "function_name": func.get("name", "unknown"),
                    "language": language,
                    "line_start": line_start,
                    "line_end": line_end,
                    "docstring": func.get("docstring"),
                    "chunk_strategy": "function"
                }
            )]

        # Split large function with overlap
        chunks = []
        func_name = func.get("name", "unknown")

        # Split by character count
        start = 0
        part_num = 0

        while start < len(func_text):
            end = min(start + self.target_size, len(func_text))

            # Try to break at line boundary
            if end < len(func_text):
                newline_pos = func_text.rfind('\n', start, end)
                if newline_pos > start:
                    end = newline_pos + 1

            chunk_text = func_text[start:end]
            chunks.append(self._create_chunk(
                chunk_id=start_chunk_id + part_num,
                text=chunk_text,
                metadata={
                    "section_type": "function",
                    "function_name": func_name,
                    "part": f"{part_num + 1}",
                    "language": language,
                    "chunk_strategy": "function_split"
                }
            ))

            part_num += 1
            start = end - self.overlap if self.overlap > 0 else end

        return chunks

    def _chunk_class(
        self,
        start_chunk_id: int,
        cls: dict,
        lines: list[str],
        language: str
    ) -> list[Chunk]:
        """
        Chunk a class.

        Args:
            start_chunk_id: Starting chunk ID
            cls: Class dictionary
            lines: File lines
            language: Programming language

        Returns:
            List of chunks
        """
        line_start = cls.get("line_start", 1)
        line_end = cls.get("line_end", len(lines))

        # Extract class text
        cls_lines = lines[line_start - 1:line_end]
        cls_text = '\n'.join(cls_lines)

        # If small enough, single chunk
        if len(cls_text) <= self.target_size:
            return [self._create_chunk(
                chunk_id=start_chunk_id,
                text=cls_text,
                metadata={
                    "section_type": "class",
                    "class_name": cls.get("name", "unknown"),
                    "methods": cls.get("methods", []),
                    "language": language,
                    "line_start": line_start,
                    "line_end": line_end,
                    "docstring": cls.get("docstring"),
                    "chunk_strategy": "class"
                }
            )]

        # Split large class with overlap
        chunks = []
        cls_name = cls.get("name", "unknown")

        start = 0
        part_num = 0

        while start < len(cls_text):
            end = min(start + self.target_size, len(cls_text))

            # Try to break at line boundary
            if end < len(cls_text):
                newline_pos = cls_text.rfind('\n', start, end)
                if newline_pos > start:
                    end = newline_pos + 1

            chunk_text = cls_text[start:end]
            chunks.append(self._create_chunk(
                chunk_id=start_chunk_id + part_num,
                text=chunk_text,
                metadata={
                    "section_type": "class",
                    "class_name": cls_name,
                    "part": f"{part_num + 1}",
                    "language": language,
                    "chunk_strategy": "class_split"
                }
            ))

            part_num += 1
            start = end - self.overlap if self.overlap > 0 else end

        return chunks

    def _simple_chunk(self, raw_doc: RawDocument) -> list[Chunk]:
        """
        Fallback to simple chunking if no structure available.

        Args:
            raw_doc: Raw document

        Returns:
            List of chunks
        """
        chunks = []
        content = raw_doc.text
        language = raw_doc.metadata.get("language", "unknown")

        chunk_id = 0
        start = 0

        while start < len(content):
            end = min(start + self.target_size, len(content))

            # Try to break at line boundary
            if end < len(content):
                newline_pos = content.rfind('\n', start, end)
                if newline_pos > start:
                    end = newline_pos + 1

            chunk_text = content[start:end]
            chunk = self._create_chunk(
                chunk_id=chunk_id,
                text=chunk_text,
                metadata={
                    "section_type": "code",
                    "language": language,
                    "chunk_strategy": "simple"
                }
            )
            chunks.append(chunk)

            chunk_id += 1
            start = end - self.overlap if self.overlap > 0 else end

        return chunks
