"""CLI flags match the help text; the format list says what is really readable."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

import chomper

ROOT = Path(__file__).resolve().parents[2]


def test_cli_t_is_short_for_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    """The help advertises ``-f template -t t.j2``; ``-t`` must work."""
    import cli

    doc = tmp_path / "doc.txt"
    doc.write_text("Hello template world.\n")
    template = tmp_path / "t.j2"
    template.write_text("WORDS={{ word_count }}")
    monkeypatch.setattr(sys, "argv", ["chomper-parse", str(doc), "-f", "template", "-t", str(template), "-q"])
    assert cli.main() == 0
    assert "WORDS=3" in capsys.readouterr().out
    assert "-t t.j2" in (ROOT / "cli.py").read_text()


def test_doc_description_does_not_claim_legacy_support() -> None:
    formats = chomper.list_formats()
    description = formats[".doc"]["description"].lower()
    assert "legacy format via docx handler" not in description
    assert "97-2003" in description and ".docx" in description


def test_ppt_is_listed_as_not_readable() -> None:
    info = chomper.list_formats()[".ppt"]
    assert info["available"] is False
    assert info["reason"] and ".pptx" in info["reason"]
    assert not chomper.is_supported("deck.ppt")


def test_ppt_errors_name_the_fix(tmp_path: Path) -> None:
    path = tmp_path / "old.ppt"
    path.write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    with pytest.raises(chomper.ChomperError, match=r"save the deck as \.pptx"):
        chomper.parse(str(path))
    with pytest.raises(chomper.ChomperError, match=r"save the deck as \.pptx"):
        chomper.parse_bytes(path.read_bytes(), "old.ppt")


def test_mcp_parse_of_ppt_names_the_fix(tmp_path: Path) -> None:
    from src.server.documents import extractor_class_for
    from src.server.helpers import parse_from_base64

    path = tmp_path / "old.ppt"
    path.write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    with pytest.raises(ValueError, match=r"save the deck as \.pptx"):
        extractor_class_for(path)
    with pytest.raises(ValueError, match=r"save the deck as \.pptx"):
        parse_from_base64("0M8R4A==", "old.ppt")


def test_mcp_list_supported_formats_is_truthful() -> None:
    from src.handlers.metadata import handle_list_supported_formats

    payload = json.loads(asyncio.run(handle_list_supported_formats({}))[0].text)
    by_ext = {f["extension"]: f for f in payload["formats"]}
    assert by_ext[".ppt"]["available"] is False
    assert "legacy format via docx handler" not in by_ext[".doc"]["description"].lower()
    assert payload["available_formats"] == sum(1 for f in payload["formats"] if f["available"])


def test_docx_saved_as_doc_still_reads(tmp_path: Path) -> None:
    import docx

    document = docx.Document()
    document.add_paragraph("Office Open XML under a .doc name.")
    path = tmp_path / "renamed.doc"
    document.save(path)
    assert "Office Open XML" in chomper.parse(str(path)).text
