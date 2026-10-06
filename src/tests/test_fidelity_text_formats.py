"""
Fidelity tests for the plain-text family: text, code, Markdown, JSON, YAML,
XML and RTF.

Every test writes a real file into ``tmp_path`` and asserts on the exact text
an LLM would receive, so a regression shows up as a diff, not a vague length
check.

Run: ``python -m pytest src/tests/test_fidelity_text_formats.py -q``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extractors.code_extractor import CodeExtractor  # noqa: E402
from src.extractors.data_extractor import JSONExtractor, XMLExtractor, YAMLExtractor  # noqa: E402
from src.extractors.encoding_utils import decode_bytes  # noqa: E402
from src.extractors.markdown_extractor import MarkdownExtractor  # noqa: E402
from src.extractors.rtf_extractor import RTFExtractor  # noqa: E402
from src.extractors.text_extractor import TextExtractor  # noqa: E402

# ------------------------------------------------------------------- encodings


def test_text_cp1252_keeps_every_character(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_bytes("Prix: 5 € – crème brûlée, naïve café\n".encode("cp1252"))

    doc = TextExtractor().extract(str(path))

    assert doc.text == "Prix: 5 € – crème brûlée, naïve café\n"
    assert doc.metadata["encoding"] == "cp1252"


def test_text_short_latin1_word_is_not_dropped(tmp_path: Path):
    path = tmp_path / "short.txt"
    path.write_bytes(b"caf\xe9 au lait\n")

    doc = TextExtractor().extract(str(path))

    assert doc.text == "café au lait\n"
    assert doc.metadata["encoding"] == "cp1252"


def test_text_utf16_with_bom(tmp_path: Path):
    path = tmp_path / "wide.txt"
    path.write_bytes("Grüße aus Köln\nZweite Zeile\n".encode("utf-16"))

    doc = TextExtractor().extract(str(path))

    assert doc.text == "Grüße aus Köln\nZweite Zeile\n"
    assert doc.metadata["encoding"] == "utf-16"


def test_text_utf8_reports_encoding(tmp_path: Path):
    path = tmp_path / "plain.txt"
    path.write_text("naïve ✓\n", encoding="utf-8")

    doc = TextExtractor().extract(str(path))

    assert doc.text == "naïve ✓\n"
    assert doc.metadata["encoding"] == "utf-8"


def test_cyrillic_legacy_bytes_are_not_read_as_western():
    text, encoding = decode_bytes("Привет, мир! Это тест кодировки.\n".encode("cp1251"))

    assert text == "Привет, мир! Это тест кодировки.\n"
    assert encoding == "cp1251"


def test_code_latin1_comment_survives(tmp_path: Path):
    path = tmp_path / "legacy.py"
    path.write_bytes("# Auteur: Hélène\ndef f():\n    return 'été'\n".encode("cp1252"))

    doc = CodeExtractor().extract(str(path))

    assert doc.text == "# Auteur: Hélène\ndef f():\n    return 'été'\n"
    assert doc.metadata["encoding"] == "cp1252"


# -------------------------------------------------------------------- markdown

MARKDOWN = """---
title: Demo
---

# Intro

Some text.

```python
# not a heading
x = 1
```

~~~
## also not a heading
~~~

Para line
---

Real setext
===========

- item
---

Closing words.
"""


def test_markdown_skips_fences_front_matter_and_breaks(tmp_path: Path):
    path = tmp_path / "doc.md"
    path.write_text(MARKDOWN, encoding="utf-8")

    doc = MarkdownExtractor().extract(str(path))
    headings = [(s["level"], s["heading"]) for s in doc.structure["sections"] if s["heading"]]

    assert doc.text == MARKDOWN
    assert headings == [(1, "Intro"), (2, "Para line"), (1, "Real setext")]
    assert doc.metadata["heading_count"] == 3
    assert doc.metadata["encoding"] == "utf-8"

    intro = doc.structure["sections"][1]
    code = [item["text"] for item in intro["content"] if item["type"] == "code"]
    assert "# not a heading" in code
    assert "## also not a heading" in code


def test_markdown_atx_closing_hashes_are_stripped(tmp_path: Path):
    path = tmp_path / "atx.md"
    path.write_text("## Setup ##\n\ntext\n", encoding="utf-8")

    doc = MarkdownExtractor().extract(str(path))

    assert doc.structure["sections"][0]["heading"] == "Setup"


# ------------------------------------------------------------------------ json


def test_json_with_utf8_bom(tmp_path: Path):
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + '{"b": 1, "a": "café"}'.encode())

    doc = JSONExtractor().extract(str(path))

    assert doc.text == '{\n  "b": 1,\n  "a": "café"\n}'
    assert doc.structure["root_keys"] == ["b", "a"]


# ------------------------------------------------------------------------ yaml

YAML = """# Service configuration
zeta: 1   # last alphabetically, first in the file
alpha:
  beta: two
  aardvark: [1, 2]
"""


def test_yaml_passes_original_text_through(tmp_path: Path):
    path = tmp_path / "svc.yaml"
    path.write_text(YAML, encoding="utf-8")

    doc = YAMLExtractor().extract(str(path))

    assert doc.text == YAML
    assert doc.structure["root_keys"] == ["zeta", "alpha"]
    assert doc.metadata["total_keys"] == 4


def test_yaml_invalid_still_raises(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("a: [1, 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid YAML"):
        YAMLExtractor().extract(str(path))


# ------------------------------------------------------------------------- xml


def test_xml_data_is_one_fenced_copy(tmp_path: Path):
    path = tmp_path / "items.xml"
    path.write_text(
        '<?xml version="1.0"?><catalog><item id="1" price="3.50"><name>Tea</name></item>'
        '<item id="2" price="1.20"><name>Bun</name></item></catalog>',
        encoding="utf-8",
    )

    doc = XMLExtractor().extract(str(path))

    assert doc.text == (
        "```xml\n"
        "<catalog>\n"
        '  <item id="1" price="3.50">\n'
        "    <name>Tea</name>\n"
        "  </item>\n"
        '  <item id="2" price="1.20">\n'
        "    <name>Bun</name>\n"
        "  </item>\n"
        "</catalog>\n"
        "```"
    )
    assert doc.metadata["xml_representation"] == "xml"


def test_xml_prose_is_extracted_text_only(tmp_path: Path):
    path = tmp_path / "article.xml"
    path.write_text(
        "<article><title>On tea</title>"
        "<para>Tea is <emphasis>very</emphasis> popular in many countries.</para>"
        "<para>It is brewed from <term>Camellia sinensis</term> leaves.</para></article>",
        encoding="utf-8",
    )

    doc = XMLExtractor().extract(str(path))

    assert doc.text == (
        "On tea\n\n"
        "Tea is very popular in many countries.\n\n"
        "It is brewed from Camellia sinensis leaves."
    )
    assert doc.metadata["xml_representation"] == "text"


def test_xml_external_entities_are_not_resolved(tmp_path: Path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    path = tmp_path / "xxe.xml"
    path.write_text(
        f'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file://{secret}">]>'
        "<r><v>&x;</v><w>ok</w></r>",
        encoding="utf-8",
    )

    doc = XMLExtractor().extract(str(path))

    assert "TOP-SECRET" not in doc.text


# ------------------------------------------------------------------------- rtf

RTF_LEGACY = r"""{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Arial;}{\f1 Symbol;}}
{\pard Intro paragraph with caf\'e9.\par}
{\pard\fi-360\li720{\pntext\f1\'B7\tab}First bullet\par}
{\pard\fi-360\li720{\pntext\f1\'B7\tab}Second bullet\par}
{\pard\fi-360\li1440{\pntext\f1 o\tab}Nested bullet\par}
{\pard\fi-360\li720{\pntext\f0 1.\tab}Numbered one\par}
{\pard\fi-360\li720{\*\pn\pnlvlblt\pnf1{\pntxtb\'B7}}{\pntext\f1\'B7\tab}Third\par}
\pard\par
\trowd\cellx2000\cellx4000
\pard\intbl Name\cell Value\cell\row
\trowd\cellx2000\cellx4000
\pard\intbl alpha | beta\cell 1\cell\row
\pard After table.\par
{\pard \bullet\tab Bullet via control word\par}
{\pard Line one\line line two\par}
}"""


def test_rtf_bullets_nesting_and_tables(tmp_path: Path):
    path = tmp_path / "doc.rtf"
    path.write_text(RTF_LEGACY, encoding="ascii")

    doc = RTFExtractor().extract(str(path))

    assert doc.text == (
        "Intro paragraph with café.\n\n"
        "- First bullet\n"
        "- Second bullet\n"
        "  - Nested bullet\n"
        "1. Numbered one\n"
        "- Third\n\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| alpha \\| beta | 1 |\n\n"
        "After table.\n\n"
        "- Bullet via control word\n\n"
        "Line one\nline two"
    )
    assert doc.structure["has_lists"] is True
    assert doc.structure["has_tables"] is True


RTF_WORD = r"""{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Calibri;}{\f3 Symbol;}}
{\listtext\pard\plain\f3 \'b7\tab}\pard\plain\fi-360\li720\ls1\ilvl0 Word item\par
{\listtext\pard\plain\f0 a)\tab}\pard\plain\fi-360\li1440\ls2\ilvl1 Lettered sub item\par
{\listtext\pard\plain\f0 b)\tab}\pard\plain\fi-360\li1440\ls2\ilvl1 Second sub item\par
\pard\plain Plain closing paragraph.\par
}"""


def test_rtf_word_listtext_levels(tmp_path: Path):
    path = tmp_path / "word.rtf"
    path.write_text(RTF_WORD, encoding="ascii")

    doc = RTFExtractor().extract(str(path))

    assert doc.text == (
        "- Word item\n"
        "  a) Lettered sub item\n"
        "  b) Second sub item\n\n"
        "Plain closing paragraph."
    )
