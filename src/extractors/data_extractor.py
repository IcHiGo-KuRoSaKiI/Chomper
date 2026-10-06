"""
Extractors for structured data formats: JSON, YAML, XML.

These extractors handle common data interchange formats,
providing both readable text output and structure metadata.
"""
import copy
import json
from pathlib import Path
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor
from .encoding_utils import read_text

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

    Extracts JSON content as formatted text with structure metadata. The file
    is decoded through ``encoding_utils`` so a UTF-8 byte-order mark (common
    from Windows tools) or UTF-16 does not make valid JSON "invalid".
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

        content, encoding = read_text(file_path)

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

        # Pretty-print the JSON
        formatted_text = json.dumps(data, indent=self.indent, ensure_ascii=False)

        # Analyze structure
        structure_info = self._analyze_structure(data)

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "json",
            "encoding": encoding,
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

    def _analyze_structure(self, data: Any, depth: int = 0) -> dict[str, Any]:
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

    The text is the original YAML source, passed through unchanged (apart from
    a byte-order mark). Re-dumping parsed YAML loses comments, anchors, quoting
    and -- with PyYAML's default ``sort_keys=True`` -- key order, all of which
    carry meaning for a reader. The file is still parsed, so invalid YAML is
    rejected and the metadata (root keys, depth, document count) is accurate.
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

        content, encoding = read_text(file_path)

        try:
            # Load all documents in the YAML file
            documents = list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from e

        # Handle single vs multi-document YAML
        if len(documents) == 1:
            data = documents[0]
            is_multi_doc = False
        else:
            data = documents
            is_multi_doc = True

        # The source text is the most faithful representation (see class docs).
        formatted_text = content.replace("\r\n", "\n")
        if not formatted_text.strip():
            formatted_text = yaml.dump(
                data, default_flow_style=False, allow_unicode=True, indent=self.indent, sort_keys=False
            )

        # Analyze structure (reuse JSON analyzer logic)
        json_extractor = JSONExtractor()
        structure_info = json_extractor._analyze_structure(data if not is_multi_doc else documents[0])

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "yaml",
            "encoding": encoding,
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

    The text holds exactly one representation of the file, chosen by shape:

    - **Data XML** (records, configs, feeds: elements hold either children or
      a value, never prose with inline markup) goes out as the re-indented XML
      in an ```` ```xml ```` fence. Tag and attribute names are the meaning of
      such files (``<item id="1" price="3.50">``); stripping them leaves a
      list of orphaned values.
    - **Document XML** (DocBook, TEI, XHTML-like prose: elements mixing text
      with inline child elements, and at least half as much text as markup) goes out as plain
      text, one paragraph per block element, inline markup flattened into its
      sentence. The tags there are formatting, and the fence would roughly
      double the tokens for no gain.

    ``metadata["xml_representation"]`` records which was used (``"xml"`` or
    ``"text"``). Earlier versions emitted both, doubling every token.

    Parsing never resolves external entities or touches the network (XXE).
    Uses lxml.
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
            parser = etree.XMLParser(
                remove_comments=not self.include_comments,
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
            )
            tree = etree.fromstring(content, parser=parser)
        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML: {e}") from e

        if self._is_document_like(tree):
            representation = "text"
            blocks: list[str] = []
            self._collect_blocks(tree, blocks)
            text = "\n\n".join(blocks)
        else:
            representation = "xml"
            text = self._fenced_xml(tree)

        # Analyze structure
        structure_info = self._analyze_structure(tree)

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "xml",
            "xml_representation": representation,
            "root_element": self._get_tag_name(tree),
            "total_elements": structure_info["element_count"],
            "max_depth": structure_info["max_depth"],
            "has_namespaces": bool(tree.nsmap),
            "encoding": tree.getroottree().docinfo.encoding if hasattr(tree.getroottree(), 'docinfo') else None,
        })

        return RawDocument(
            text=text,
            metadata=metadata,
            structure={
                "type": "xml",
                "representation": representation,
                "root_element": self._get_tag_name(tree),
                "child_elements": structure_info["child_elements"],
                "namespaces": dict(tree.nsmap) if tree.nsmap else {},
                "attributes": dict(tree.attrib) if tree.attrib else {}
            }
        )

    @staticmethod
    def _is_mixed(element) -> bool:
        """True if ``element`` interleaves its own text with child elements."""
        children = [child for child in element if isinstance(child.tag, str)]
        if not children:
            return False
        if element.text and element.text.strip():
            return True
        return any(child.tail and child.tail.strip() for child in children)

    def _is_document_like(self, root) -> bool:
        """Prose with inline markup (see class docs), judged on the whole tree."""
        mixed = 0
        text_chars = 0
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            text_chars += len((element.text or "").strip()) + len((element.tail or "").strip())
            if self._is_mixed(element):
                mixed += 1
        if not mixed:
            return False
        markup_chars = len(etree.tostring(root, encoding="unicode")) - text_chars
        # Inline tags are short but numerous; prose still outweighs half its markup.
        return text_chars * 2 >= markup_chars

    def _collect_blocks(self, element, blocks: list[str]) -> None:
        """One paragraph per text-bearing block; containers are descended into."""
        children = [child for child in element if isinstance(child.tag, str)]
        if not children or self._is_mixed(element):
            text = " ".join("".join(self._itertext(element)).split())
            if text:
                blocks.append(text)
            return
        for child in children:
            self._collect_blocks(child, blocks)

    def _itertext(self, element):
        """Element text without comment or processing-instruction text."""
        if element.text and isinstance(element.tag, str):
            yield element.text
        for child in element:
            if isinstance(child.tag, str):
                yield from self._itertext(child)
            if child.tail:
                yield child.tail

    def _fenced_xml(self, root) -> str:
        """The XML re-indented two spaces per level, in a ```xml fence."""
        pretty = copy.deepcopy(root)
        etree.indent(pretty, space="  ")
        body = etree.tostring(pretty, encoding="unicode").strip()
        fence = "```"
        while fence in body:
            fence += "`"
        return f"{fence}xml\n{body}\n{fence}"

    def _get_tag_name(self, element) -> str:
        """Get tag name, optionally stripping namespace."""
        tag = element.tag
        if self.strip_namespaces and tag.startswith('{'):
            tag = tag.split('}', 1)[1]
        return tag

    def _analyze_structure(self, element, depth: int = 0) -> dict[str, Any]:
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
