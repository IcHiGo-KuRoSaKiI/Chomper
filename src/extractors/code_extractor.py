"""
Code extractor using AST for Python and regex for other languages.

Extracts code structure (imports, functions, classes) from source files.
"""
import ast
import re
from typing import Dict, Any, List
from pathlib import Path

from .base import BaseExtractor
from ..models.document import RawDocument


class CodeExtractor(BaseExtractor):
    """
    Extract structure from code files.

    Features:
    - Python: AST-based parsing (imports, functions, classes)
    - Other languages: Regex-based parsing
    - Language detection from file extension
    - Docstring and comment extraction
    """

    # Language extensions mapping
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.cs': 'csharp',
        '.swift': 'swift',
        '.kt': 'kotlin'
    }

    SUPPORTED_EXTENSIONS = list(LANGUAGE_MAP.keys())

    def __init__(self):
        """Initialize code extractor."""
        pass

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from code file.

        Args:
            file_path: Path to code file

        Returns:
            RawDocument with extracted structure
        """
        self.validate_file(file_path)

        # Read file content
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Detect language
        extension = Path(file_path).suffix.lower()
        language = self.LANGUAGE_MAP.get(extension, 'unknown')

        # Extract structure based on language
        if language == 'python':
            structure = self._extract_python_structure(content)
        else:
            structure = self._extract_generic_structure(content, language)

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "language": language,
            "lines_of_code": len(content.splitlines()),
            "format": "code"
        })

        return RawDocument(
            text=content,
            metadata=metadata,
            structure=structure
        )

    def _extract_python_structure(self, content: str) -> Dict[str, Any]:
        """
        Extract Python code structure using AST.

        Args:
            content: Python code content

        Returns:
            Structure dictionary
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Fallback to generic if syntax error
            return self._extract_generic_structure(content, 'python')

        structure = {
            "imports": [],
            "functions": [],
            "classes": []
        }

        # Extract imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    structure["imports"].append({
                        "module": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno,
                        "type": "import"
                    })

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                items = [alias.name for alias in node.names]

                structure["imports"].append({
                    "module": module,
                    "items": items,
                    "line": node.lineno,
                    "type": "from_import"
                })

        # Extract top-level functions and classes (not nested)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = [arg.arg for arg in node.args.args]
                docstring = ast.get_docstring(node)

                structure["functions"].append({
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                    "parameters": params,
                    "docstring": docstring,
                    "is_async": isinstance(node, ast.AsyncFunctionDef)
                })

            elif isinstance(node, ast.ClassDef):
                # Extract method names
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(item.name)

                # Extract base classes
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)

                docstring = ast.get_docstring(node)

                structure["classes"].append({
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                    "methods": methods,
                    "inherits_from": bases,
                    "docstring": docstring
                })

        return structure

    def _extract_generic_structure(self, content: str, language: str) -> Dict[str, Any]:
        """
        Extract code structure using regex (for non-Python languages).

        Args:
            content: Code content
            language: Language name

        Returns:
            Structure dictionary
        """
        structure = {
            "imports": [],
            "functions": [],
            "classes": []
        }

        lines = content.splitlines()

        # Language-specific patterns
        if language in ['javascript', 'typescript']:
            # Imports: import X from 'Y' or const X = require('Y')
            import_pattern = r'(?:import|require)\s*\(?[\'"]([^\'"]+)[\'"]'
            func_pattern = r'(?:function|const|let|var)\s+(\w+)\s*\(([^)]*)\)'
            class_pattern = r'class\s+(\w+)'

        elif language == 'java':
            import_pattern = r'import\s+([\w.]+)'
            func_pattern = r'(?:public|private|protected)?\s+(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)'
            class_pattern = r'(?:public|private)?\s+class\s+(\w+)'

        elif language in ['c', 'cpp']:
            import_pattern = r'#include\s*[<"]([^>"]+)[>"]'
            func_pattern = r'[\w\s\*]+\s+(\w+)\s*\(([^)]*)\)\s*\{'
            class_pattern = r'class\s+(\w+)'

        elif language == 'go':
            import_pattern = r'import\s+["\']([^"\']+)["\']'
            func_pattern = r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)'
            class_pattern = r'type\s+(\w+)\s+struct'

        else:
            # Generic fallback
            import_pattern = r'(?:import|include|require|use)\s+[\'"]?([^\s\'"]+)'
            func_pattern = r'(?:function|def|fn)\s+(\w+)\s*\('
            class_pattern = r'class\s+(\w+)'

        # Extract imports
        for i, line in enumerate(lines, 1):
            match = re.search(import_pattern, line)
            if match:
                structure["imports"].append({
                    "module": match.group(1),
                    "line": i
                })

        # Extract functions (rough approximation)
        for i, line in enumerate(lines, 1):
            match = re.search(func_pattern, line)
            if match:
                structure["functions"].append({
                    "name": match.group(1),
                    "line_start": i,
                    "line_end": i  # Can't determine end without proper parsing
                })

        # Extract classes
        for i, line in enumerate(lines, 1):
            match = re.search(class_pattern, line)
            if match:
                structure["classes"].append({
                    "name": match.group(1),
                    "line_start": i,
                    "line_end": i  # Can't determine end without proper parsing
                })

        return structure
