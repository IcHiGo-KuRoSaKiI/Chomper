"""PDF ``ocr`` / ``table_format`` options: library, CLI and MCP reach the extractor,
the document cache keeps them apart, and the MCP schemas validate them.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult

import chomper
import server
from src.models.document import RawDocument
from src.server import cache as cache_mod
from src.server import documents
from src.server.config import PDF_OCR_MODES, PDF_TABLE_FORMATS
from src.server.helpers import validate_arguments
from src.server.tools import get_tools

PAGE = "# Title\n\n" + " ".join(f"Sentence {i} of the fake PDF." for i in range(1500))


class FakePDFExtractor:
    """Stands in for PDFExtractor: records constructor options, returns layout-shaped text."""

    calls: list[dict[str, Any]] = []

    def __init__(self, **options: Any) -> None:
        FakePDFExtractor.calls.append(options)

    def extract(self, file_path: str) -> RawDocument:
        return RawDocument(
            text=PAGE,
            metadata={"filename": Path(file_path).name, "page_count": 1},
            structure={"pages": [{"page_number": 1, "markdown_text": PAGE, "content": []}]},
        )


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache_mod.clear_caches()
    FakePDFExtractor.calls = []
    yield
    cache_mod.clear_caches()


@pytest.fixture
def fake_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``.pdf`` path whose extraction goes to :class:`FakePDFExtractor`."""
    real = documents.extractor_class_for

    def extractor_for(path: Path) -> type:
        return FakePDFExtractor if path.suffix.lower() == ".pdf" else real(path)

    monkeypatch.setattr(documents, "extractor_class_for", extractor_for)
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.7 fake")
    return path


def call(name: str, args: dict[str, Any]) -> Any:
    return asyncio.run(server.dispatch_tool(name, args))


def test_option_values_match_the_extractor() -> None:
    from src.extractors.pdf_layout import OCR_MODES

    assert tuple(OCR_MODES) == PDF_OCR_MODES
    assert PDF_TABLE_FORMATS == ("markdown", "html")


# --------------------------------------------------------------------- library


def test_library_options_reach_the_extractor(fake_pdf: Path) -> None:
    chomper.parse(fake_pdf, ocr="off", table_format="html")
    assert FakePDFExtractor.calls[-1] == {"ocr": "off", "table_format": "html"}
    chomper.extract_metadata(fake_pdf, ocr="force")
    assert FakePDFExtractor.calls[-1] == {"ocr": "force"}
    chomper.chunk(fake_pdf, strategy="layout", table_format="html")
    assert FakePDFExtractor.calls[-1] == {"table_format": "html"}
    chomper.parse_bytes(fake_pdf.read_bytes(), "x.pdf", ocr="off")
    assert FakePDFExtractor.calls[-1] == {"ocr": "off"}
    chomper.parse(fake_pdf)
    assert FakePDFExtractor.calls[-1] == {}  # defaults are not passed explicitly


def test_cache_keeps_options_apart_and_defaults_together(fake_pdf: Path) -> None:
    chomper.parse(fake_pdf)
    chomper.parse(fake_pdf, ocr="auto", table_format="markdown")  # same as the default
    chomper.extract_metadata(fake_pdf)
    assert len(FakePDFExtractor.calls) == 1

    chomper.parse(fake_pdf, ocr="off")
    chomper.parse(fake_pdf, table_format="html")
    chomper.parse(fake_pdf, ocr="off", table_format="html")
    assert len(FakePDFExtractor.calls) == 4

    chomper.extract_metadata(fake_pdf, ocr="off")  # reuses the ocr="off" parse
    chomper.chunk(fake_pdf, strategy="layout", ocr="off", table_format="html")
    assert len(FakePDFExtractor.calls) == 4

    keys = {key[-1] for key in cache_mod.DOCUMENT_CACHE._data}
    assert keys == {
        (),
        (("ocr", "off"),),
        (("table_format", "html"),),
        (("ocr", "off"), ("table_format", "html")),
    }


def test_options_are_ignored_for_other_formats(tmp_path: Path) -> None:
    doc = tmp_path / "a.txt"
    doc.write_text("plain text")
    assert chomper.parse(doc, ocr="force", table_format="html").text == "plain text"
    assert {key[-1] for key in cache_mod.DOCUMENT_CACHE._data} == {()}


@pytest.mark.parametrize(
    "kwargs", [{"ocr": "sometimes"}, {"table_format": "latex"}, {"ocr": "AUTO"}]
)
def test_library_rejects_unknown_option_values(fake_pdf: Path, kwargs: dict[str, str]) -> None:
    for fn in (
        lambda: chomper.parse(fake_pdf, **kwargs),
        lambda: chomper.extract_metadata(fake_pdf, **kwargs),
        lambda: chomper.chunk(fake_pdf, strategy="layout", **kwargs),
        lambda: chomper.parse_bytes(b"%PDF", "x.pdf", **kwargs),
    ):
        with pytest.raises(chomper.ChomperError, match="Use one of"):
            fn()
    assert FakePDFExtractor.calls == []


def test_auto_pdf_chunking_refuses_options_it_cannot_honour(fake_pdf: Path) -> None:
    with pytest.raises(chomper.ChomperError, match="strategy 'layout'"):
        chomper.chunk(fake_pdf, ocr="force")


# ------------------------------------------------------------------------- MCP

EXTRACTING_TOOLS = (
    "parse_document",
    "parse_document_bytes",
    "parse_document_chunked",
    "get_document_chunk",
)


@pytest.mark.parametrize("tool", EXTRACTING_TOOLS)
def test_schemas_declare_the_options(tool: str) -> None:
    schema = next(t.inputSchema for t in get_tools() if t.name == tool)
    ocr, table_format = schema["properties"]["ocr"], schema["properties"]["table_format"]
    assert ocr["enum"] == list(PDF_OCR_MODES) and ocr["default"] == "auto"
    assert table_format["enum"] == list(PDF_TABLE_FORMATS) and table_format["default"] == "markdown"
    assert "text layer" in ocr["description"] and "Tesseract" in ocr["description"]
    assert "PDFs only" in table_format["description"]


def test_batch_schema_declares_the_options_and_validates_them() -> None:
    schema = next(t.inputSchema for t in get_tools() if t.name == "batch_parse")
    options = schema["properties"]["options"]["properties"]
    assert options["ocr"]["enum"] == list(PDF_OCR_MODES)
    assert options["table_format"]["enum"] == list(PDF_TABLE_FORMATS)
    with pytest.raises(ValueError, match="options: ocr must be one of"):
        validate_arguments(schema, {"file_paths": ["/x.pdf"], "options": {"ocr": "always"}})
    validate_arguments(schema, {"file_paths": ["/x.pdf"], "options": {"ocr": "off"}})


def test_chunked_schema_offers_layout() -> None:
    schema = next(t.inputSchema for t in get_tools() if t.name == "parse_document_chunked")
    strategy = schema["properties"]["chunking_strategy"]
    assert "layout" in strategy["enum"] and "'layout'" in strategy["description"]


@pytest.mark.parametrize("tool", [*EXTRACTING_TOOLS, "batch_parse"])
@pytest.mark.parametrize(("name", "value"), [("ocr", "maybe"), ("table_format", "csv")])
def test_mcp_rejects_bad_option_values(fake_pdf: Path, tool: str, name: str, value: str) -> None:
    args: dict[str, Any] = {
        "parse_document": {"file_path": str(fake_pdf), name: value},
        "parse_document_bytes": {"content_base64": "JVBERg==", "filename": "a.pdf", name: value},
        "parse_document_chunked": {"file_path": str(fake_pdf), name: value},
        "get_document_chunk": {"file_path": str(fake_pdf), name: value},
        "batch_parse": {"file_paths": [str(fake_pdf)], "options": {name: value}},
    }[tool]
    result = call(tool, args)
    assert isinstance(result, CallToolResult) and result.isError
    assert f"{name} must be one of" in result.content[0].text
    assert FakePDFExtractor.calls == []


def test_mcp_options_reach_the_extractor(fake_pdf: Path) -> None:
    opts = {"ocr": "off", "table_format": "html"}
    expected = {"ocr": "off", "table_format": "html"}

    parsed = call("parse_document", {"file_path": str(fake_pdf), **opts})
    assert FakePDFExtractor.calls[-1] == expected
    hint = json.loads(parsed[1].text)["continuation_hint"]
    assert "ocr='off'" in hint and "table_format='html'" in hint

    FakePDFExtractor.calls.clear()
    page = call("get_document_chunk", {"file_path": str(fake_pdf), "limit": 100, **opts})
    assert FakePDFExtractor.calls == []  # shares parse_document's cached extraction
    assert "ocr='off'" in json.loads(page[1].text)["next_chunk_hint"]

    chunked = json.loads(call("parse_document_chunked", {
        "file_path": str(fake_pdf), "chunking_strategy": "layout", **opts,
    })[0].text)
    assert FakePDFExtractor.calls == []
    assert chunked["ocr"] == "off" and chunked["table_format"] == "html"
    assert chunked["chunks"][0]["metadata"]["chunk_strategy"] == "layout"

    call("parse_document_chunked", {
        "file_path": str(fake_pdf), "chunking_strategy": "recursive", "ocr": "force",
    })
    assert FakePDFExtractor.calls[-1] == {"ocr": "force"}

    result = call("parse_document_chunked", {"file_path": str(fake_pdf), "ocr": "force"})
    assert isinstance(result, CallToolResult) and result.isError
    assert "layout" in result.content[0].text

    batch = json.loads(call("batch_parse", {
        "file_paths": [str(fake_pdf)], "options": {"table_format": "html"},
    })[0].text)
    assert batch["successful"] == 1
    assert FakePDFExtractor.calls[-1] == {"table_format": "html"}

    payload = base64.b64encode(fake_pdf.read_bytes()).decode()
    call("parse_document_bytes", {"content_base64": payload, "filename": "b.pdf", "ocr": "force"})
    assert FakePDFExtractor.calls[-1] == {"ocr": "force"}


# ------------------------------------------------------------------------- CLI


def run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict[str, Any]:
    import cli

    seen: dict[str, Any] = {}

    def record(name: str, result: Any) -> Any:
        def fake(*args: Any, **kwargs: Any) -> Any:
            seen[name] = kwargs
            return result
        return fake

    monkeypatch.setattr(chomper, "parse", record("parse", chomper.ParseResult(
        text="t", metadata={}, file_path="f", format="pdf", word_count=1, char_count=1)))
    monkeypatch.setattr(chomper, "chunk", record("chunk", []))
    monkeypatch.setattr(chomper, "extract_metadata", record(
        "extract_metadata", chomper.MetadataResult(
            file_path="f", filename="f", format="pdf", file_size=1)))
    monkeypatch.setattr(sys, "argv", ["chomper-parse", *argv])
    assert cli.main() == 0
    return seen


def test_cli_passes_options(fake_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = run_cli(monkeypatch, str(fake_pdf), "--ocr", "off", "--table-format", "html", "-q")
    assert seen["parse"]["ocr"] == "off" and seen["parse"]["table_format"] == "html"
    seen = run_cli(monkeypatch, str(fake_pdf), "--chunk", "--strategy", "layout", "--ocr", "force", "-q")
    assert seen["chunk"]["strategy"] == "layout" and seen["chunk"]["ocr"] == "force"
    seen = run_cli(monkeypatch, str(fake_pdf), "--metadata", "--table-format", "html", "-q")
    assert seen["extract_metadata"]["table_format"] == "html"
    seen = run_cli(monkeypatch, str(fake_pdf), "-q")
    assert seen["parse"]["ocr"] == "auto" and seen["parse"]["table_format"] == "markdown"


def test_cli_rejects_unknown_ocr(fake_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cli

    monkeypatch.setattr(sys, "argv", ["chomper-parse", str(fake_pdf), "--ocr", "sometimes"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_interactive_settings_cover_the_options() -> None:
    from src.cli.interactive import InteractiveShell

    shell = InteractiveShell(quiet=True)
    shell._cmd_set("ocr force")
    shell._cmd_set("table-format html")
    shell._cmd_set("strategy layout")
    shell._cmd_set("ocr never")  # rejected, keeps the previous value
    assert (shell.state.ocr, shell.state.table_format, shell.state.chunk_strategy) == (
        "force", "html", "layout"
    )
