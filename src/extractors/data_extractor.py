"""
Extractors for structured data formats: JSON, YAML, XML.

These extractors handle common data interchange formats,
providing both readable text output and structure metadata.
"""
import json
from pathlib import Path
from typing import Any, Dict, List
from .base import BaseExtractor
from ..models.document import RawDocument

# Optional imports with graceful fallback
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False

try:
    from lxml import etree
    LXML_AVAILABLE = True
except ImportError:
    etree = None
    LXML_AVAILABLE = False


class JSONExtractor(BaseExtractor):
    """
    Extractor for JSON files.

    Extracts JSON content as formatted text with structure metadata.
    """

    SUPPORTED_EXTENSIONS = [".json"]

    def __init__(self, indent: int = 2, max_depth: int = 10):
        """
        Initialize JSON extractor.

        Args:
            indent: Indentation for pretty-printing (default: 2)
            max_depth: Maximum depth to analyze for structure info
        """
        self.indent = indent
        self.max_depth = max_depth

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from JSON file."""
        self.validate_file(file_path)

        path = Path(file_path)
        content = path.read_text(encoding='utf-8')

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        # Pretty-print the JSON
        formatted_text = json.dumps(data, indent=self.indent, ensure_ascii=False)

        # Analyze structure
        structure_info = self._analyze_structure(data)

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "json",
            "root_type": type(data).__name__,
            "total_keys": structure_info["total_keys"],
            "max_depth": structure_info["max_depth"],
            "array_count": structure_info["array_count"],
            "object_count": structure_info["object_count"],
        })

        return RawDocument(
            text=formatted_text,
            metadata=metadata,
            structure={
                "type": "json",
                "root_keys": structure_info["root_keys"],
                "schema_preview": structure_info["schema_preview"]
            }
        )

    def _analyze_structure(self, data: Any, depth: int = 0) -> Dict[str, Any]:
        """Analyze JSON structure recursively."""
        result = {
            "total_keys": 0,
            "max_depth": depth,
            "array_count": 0,
            "object_count": 0,
            "root_keys": [],
            "schema_preview": {}
        }

        if depth > self.max_depth:
            return result

        if isinstance(data, dict):
            result["object_count"] = 1
            result["total_keys"] = len(data)
            result["root_keys"] = list(data.keys())[:20]  # Limit to first 20 keys

            # Build schema preview
            schema = {}
            for key, value in list(data.items())[:10]:  # Preview first 10 keys
                schema[key] = self._get_type_preview(value)
            result["schema_preview"] = schema

            # Recurse into values
            for value in data.values():
                child = self._analyze_structure(value, depth + 1)
                result["total_keys"] += child["total_keys"]
                result["max_depth"] = max(result["max_depth"], child["max_depth"])
                result["array_count"] += child["array_count"]
                result["object_count"] += child["object_count"]

        elif isinstance(data, list):
            result["array_count"] = 1
            for item in data[:100]:  # Limit to first 100 items
                child = self._analyze_structure(item, depth + 1)
                result["total_keys"] += child["total_keys"]
                result["max_depth"] = max(result["max_depth"], child["max_depth"])
                result["array_count"] += child["array_count"]
                result["object_count"] += child["object_count"]

        return result

    def _get_type_preview(self, value: Any) -> str:
        """Get a type preview string for a value."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, str):
            return f"string({len(value)} chars)"
        elif isinstance(value, list):
            return f"array({len(value)} items)"
        elif isinstance(value, dict):
            return f"object({len(value)} keys)"
        return type(value).__name__


class YAMLExtractor(BaseExtractor):
    """
    Extractor for YAML files.

    Extracts YAML content as formatted text with structure metadata.
    Requires PyYAML library.
    """

    SUPPORTED_EXTENSIONS = [".yaml", ".yml"]

    def __init__(self, indent: int = 2):
        """
        Initialize YAML extractor.

        Args:
            indent: Indentation for output formatting
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is required for YAML extraction. Install with: pip install pyyaml")
        self.indent = indent

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from YAML file."""
        self.validate_file(file_path)

        path = Path(file_path)
        content = path.read_text(encoding='utf-8')

        try:
            # Load all documents in the YAML file
            documents = list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        # Handle single vs multi-document YAML
        if len(documents) == 1:
            data = documents[0]
            is_multi_doc = False
        else:
            data = documents
            is_multi_doc = True

        # Format as readable YAML
        if is_multi_doc:
            formatted_parts = []
            for doc in documents:
                formatted_parts.append(yaml.dump(doc, default_flow_style=False, allow_unicode=True, indent=self.indent))
            formatted_text = "---\n".join(formatted_parts)
        else:
            formatted_text = yaml.dump(data, default_flow_style=False, allow_unicode=True, indent=self.indent)

        # Analyze structure (reuse JSON analyzer logic)
        json_extractor = JSONExtractor()
        structure_info = json_extractor._analyze_structure(data if not is_multi_doc else documents[0])

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "yaml",
            "multi_document": is_multi_doc,
            "document_count": len(documents),
            "root_type": type(data).__name__,
            "total_keys": structure_info["total_keys"],
            "max_depth": structure_info["max_depth"],
        })

        return RawDocument(
            text=formatted_text,
            metadata=metadata,
            structure={
                "type": "yaml",
                "multi_document": is_multi_doc,
                "root_keys": structure_info["root_keys"],
                "schema_preview": structure_info["schema_preview"]
            }
        )


class XMLExtractor(BaseExtractor):
    """
    Extractor for XML files.

    Extracts XML content as formatted text with structure metadata.
    Uses lxml for parsing.
    """

    SUPPORTED_EXTENSIONS = [".xml"]

    def __init__(self, include_comments: bool = False, strip_namespaces: bool = False):
        """
        Initialize XML extractor.

        Args:
            include_comments: Include XML comments in output
            strip_namespaces: Remove namespace prefixes from tags
        """
        if not LXML_AVAILABLE:
            raise ImportError("lxml is required for XML extraction. Install with: pip install lxml")
        self.include_comments = include_comments
        self.strip_namespaces = strip_namespaces

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from XML file."""
        self.validate_file(file_path)

        path = Path(file_path)
        content = path.read_bytes()

        try:
            # Parse with lxml
            parser = etree.XMLParser(remove_comments=not self.include_comments)
            tree = etree.fromstring(content, parser=parser)
        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML: {e}")

        # Extract text content
        text_parts = []
        self._extract_text_recursive(tree, text_parts)
        extracted_text = "\n".join(text_parts)

        # Also provide formatted XML
        formatted_xml = etree.tostring(tree, pretty_print=True, encoding='unicode')

        # Combine: show structure then extracted text
        combined_text = f"## XML Structure\n\n```xml\n{formatted_xml}\n```\n\n## Extracted Text\n\n{extracted_text}"

        # Analyze structure
        structure_info = self._analyze_structure(tree)

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "xml",
            "root_element": self._get_tag_name(tree),
            "total_elements": structure_info["element_count"],
            "max_depth": structure_info["max_depth"],
            "has_namespaces": bool(tree.nsmap),
            "encoding": tree.getroottree().docinfo.encoding if hasattr(tree.getroottree(), 'docinfo') else None,
        })

        return RawDocument(
            text=combined_text,
            metadata=metadata,
            structure={
                "type": "xml",
                "root_element": self._get_tag_name(tree),
                "child_elements": structure_info["child_elements"],
                "namespaces": dict(tree.nsmap) if tree.nsmap else {},
                "attributes": dict(tree.attrib) if tree.attrib else {}
            }
        )

    def _get_tag_name(self, element) -> str:
        """Get tag name, optionally stripping namespace."""
        tag = element.tag
        if self.strip_namespaces and tag.startswith('{'):
            tag = tag.split('}', 1)[1]
        return tag

    def _extract_text_recursive(self, element, text_parts: List[str], depth: int = 0) -> None:
        """Recursively extract text content from XML elements."""
        # Get direct text
        if element.text and element.text.strip():
            text_parts.append(element.text.strip())

        # Process children
        for child in element:
            self._extract_text_recursive(child, text_parts, depth + 1)

            # Get tail text (text after child element)
            if child.tail and child.tail.strip():
                text_parts.append(child.tail.strip())

    def _analyze_structure(self, element, depth: int = 0) -> Dict[str, Any]:
        """Analyze XML structure recursively."""
        result = {
            "element_count": 1,
            "max_depth": depth,
            "child_elements": []
        }

        # Get unique child element names
        child_tags = set()
        for child in element:
            child_tags.add(self._get_tag_name(child))
            child_info = self._analyze_structure(child, depth + 1)
            result["element_count"] += child_info["element_count"]
            result["max_depth"] = max(result["max_depth"], child_info["max_depth"])

        result["child_elements"] = list(child_tags)[:20]  # Limit to first 20

        return result
