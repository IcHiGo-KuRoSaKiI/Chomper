"""Regression tests for the chunkers: termination, structure, word coverage, metadata."""

from __future__ import annotations

import re
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import chomper
from src.chunking.base import BaseChunker
from src.chunking.strategies import (
    DOCXChunker,
    HTMLChunker,
    MarkdownChunker,
    PPTXChunker,
    StructuralPDFChunker,
    TextChunker,
)
from src.chunking.strategies.semantic_chunker import SemanticChunker
from src.chunking.text_splitter import split_spans
from src.models.document import Chunk, RawDocument
from src.server.cache import clear_caches

MARKDOWN = """# Guide

Intro paragraph that explains what this guide covers and why it matters to readers.

## Install

- step one does a thing
  - nested detail a
  - nested detail b
- step two does another thing
  1. numbered sub step
  2. another numbered sub step

| Name | Value | Notes |
|------|-------|-------|
| alpha | 1 | first row of the table with words |
| beta | 2 | second row of the table with words |
| gamma | 3 | third row of the table with words |

```python
def handler(event):

    # a blank line above must not end the fence
    return {"status": event["status"], "body": "ok"}
```

## Usage

""" + " ".join(f"Sentence number {i} describes one more usage detail." for i in range(40)) + "\n"


@contextmanager
def deadline(seconds: int) -> Iterator[None]:
    """Fail (instead of hanging forever) if the block runs longer than ``seconds``."""

    def on_alarm(signum: int, frame: Any) -> None:
        raise TimeoutError(f"did not finish within {seconds}s (infinite loop?)")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


class StubModel:
    """Deterministic embeddings so tests never download a model."""

    def encode(self, texts: list[str], convert_to_numpy: bool = True) -> np.ndarray:
        rng = np.random.default_rng(0)
        return rng.normal(size=(len(texts), 16))


def semantic(target: int, overlap: int, min_chunk: int = 50) -> SemanticChunker:
    chunker = SemanticChunker(target_size=target, overlap=overlap, min_chunk_size=min_chunk)
    chunker._model = StubModel()
    return chunker


def words(text: str) -> list[str]:
    return text.split()


# ------------------------------------------------------------------ termination


SMALL = RawDocument(text="just a few words here")
LONG_TEXT = "\n\n".join(" ".join(f"w{p}_{i}" for i in range(37)) for p in range(30))


@pytest.mark.parametrize(
    "make",
    [
        lambda: TextChunker(target_size=10, overlap=5),
        lambda: TextChunker(target_size=10, overlap=50),  # overlap > target
        lambda: TextChunker(target_size=10, overlap=5, prefer_structure=False),
        lambda: MarkdownChunker(target_size=10, overlap=9),
        lambda: DOCXChunker(target_size=10, overlap=10),
        lambda: PPTXChunker(target_size=10, overlap=5),
        lambda: HTMLChunker(target_size=10, overlap=5),
        lambda: semantic(target=10, overlap=5, min_chunk=3),
    ],
    ids=["text", "text-overlap>target", "fixed", "markdown", "docx", "pptx", "html", "semantic"],
)
@pytest.mark.parametrize("doc", [SMALL, RawDocument(text=LONG_TEXT)], ids=["small", "long"])
def test_every_chunker_terminates_with_overlap(make: Any, doc: RawDocument) -> None:
    with deadline(10):
        chunks = make().chunk(doc)
    assert chunks
    assert all(c.word_count <= 10 for c in chunks)
    covered = {w for c in chunks for w in words(c.text)}
    assert covered == set(words(doc.text))


def test_split_by_word_count_terminates_when_overlap_exceeds_target() -> None:
    class Plain(BaseChunker):
        def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
            return []

    with deadline(5):
        pieces = Plain(target_size=5, overlap=50)._split_by_word_count(LONG_TEXT)
    assert len(pieces) > 1
    assert all(len(words(p)) <= 5 for p in pieces)


def test_explicit_zero_overlap_is_honoured() -> None:
    class Plain(BaseChunker):
        def chunk(self, raw_doc: RawDocument) -> list[Chunk]:
            return []

    pieces = Plain(target_size=8, overlap=4)._split_by_word_count(LONG_TEXT, overlap=0)
    assert [w for p in pieces for w in words(p)] == words(LONG_TEXT)


def test_library_chunk_on_small_json_does_not_hang(tmp_path: Path) -> None:
    path = tmp_path / "small.json"
    path.write_text('{"a": 1, "b": [1, 2, 3], "c": "hello world"}')
    with deadline(10):
        chunks = chomper.chunk(str(path))
    assert len(chunks) == 1
    assert '"hello world"' in chunks[0].text


# -------------------------------------------------------------------- structure


@pytest.mark.parametrize("target", [12, 25, 60, 400])
@pytest.mark.parametrize("overlap", [0, 6])
def test_markdown_chunks_are_exact_substrings_and_keep_structure(target: int, overlap: int) -> None:
    chunks = MarkdownChunker(target_size=target, overlap=overlap).chunk(RawDocument(text=MARKDOWN))
    for c in chunks:
        assert MARKDOWN[c.start_char:c.end_char] == c.text
        # A fenced code block is never cut: fences come in pairs.
        assert c.text.count("```") % 2 == 0
        # A table row is never cut: every line starting with '|' is a whole source line.
        for line in c.text.splitlines():
            if line.lstrip().startswith("|"):
                assert line + "\n" in MARKDOWN
    # Nested list indentation survives (whenever the list fits in one chunk).
    if target >= 25:
        assert any("\n  - nested detail a\n  - nested detail b" in c.text for c in chunks)
    # Nothing lost.
    covered = {w for c in chunks for w in words(c.text)}
    assert covered == set(words(MARKDOWN))


def test_code_fence_stays_whole_even_when_larger_than_target() -> None:
    chunks = TextChunker(target_size=5, overlap=0).chunk(RawDocument(text=MARKDOWN))
    fences = [c.text for c in chunks if "```python" in c.text]
    assert len(fences) == 1
    assert fences[0].startswith("```python") and fences[0].endswith("```")
    assert "\n\n    # a blank line above" in fences[0]


def test_single_paragraph_longer_than_target_is_split_on_sentences() -> None:
    para = " ".join(f"This is sentence {i} with exactly eight words." for i in range(30))
    chunks = TextChunker(target_size=40, overlap=0).chunk(RawDocument(text=para))
    assert len(chunks) > 1
    assert all(c.word_count <= 40 for c in chunks)
    assert all(c.text.endswith(".") for c in chunks)
    assert [w for c in chunks for w in words(c.text)] == words(para)


def test_fixed_and_recursive_strategies_differ_but_both_break_on_lines() -> None:
    # Paragraphs of four 5-word lines: recursive cuts at blank lines (20 words),
    # fixed packs as many whole lines as fit (30 words).
    paragraphs = [
        "\n".join(f"p{p} line {i} has words" for i in range(4)) for p in range(12)
    ]
    text = "\n\n".join(paragraphs)
    fixed = split_spans(text, 30, 0, prefer_structure=False)
    recursive = split_spans(text, 30, 0)
    assert fixed != recursive
    for spans in (fixed, recursive):
        for s, e in spans:
            assert s == 0 or text[s - 1] == "\n"
            assert e == len(text) or text[e] == "\n"


def test_heading_is_never_left_at_the_end_of_a_chunk() -> None:
    chunks = MarkdownChunker(target_size=8, overlap=0).chunk(RawDocument(text=MARKDOWN))
    for c in chunks:
        assert not c.text.splitlines()[-1].startswith("#")


# --------------------------------------------------------------------- semantic


def make_paragraphs(n: int = 120) -> str:
    rng = np.random.default_rng(1)
    vocab = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu".split()
    return "\n\n".join(
        " ".join(rng.choice(vocab, size=int(rng.integers(10, 80)))) + "." for _ in range(n)
    )


def test_semantic_chunker_loses_no_words() -> None:
    text = make_paragraphs()
    chunks = semantic(target=300, overlap=0).chunk(RawDocument(text=text))
    assert [w for c in chunks for w in words(c.text)] == words(text)  # 10% were lost before


def test_semantic_chunker_enforces_target_as_maximum_and_applies_overlap() -> None:
    text = make_paragraphs()
    plain = semantic(target=200, overlap=0).chunk(RawDocument(text=text))
    overlapped = semantic(target=200, overlap=40).chunk(RawDocument(text=text))
    assert max(c.word_count for c in plain) <= 200
    assert max(c.word_count for c in overlapped) <= 200
    assert sum(c.word_count for c in overlapped) > sum(c.word_count for c in plain)
    for c in overlapped:
        assert text[c.start_char:c.end_char] == c.text


# ---------------------------------------------------------- metadata / library


def test_library_chunk_populates_section_name(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(MARKDOWN)
    chunks = chomper.chunk(str(path), chunk_size=30, overlap=0)
    names = [c.section_name for c in chunks]
    assert "Install" in names and "Usage" in names
    assert all(n for n in names)
    source = path.read_text()
    for c in chunks:
        assert source[c.start_char:c.end_char] == c.text


@pytest.mark.parametrize("strategy", ["auto", "fixed", "recursive"])
def test_library_strategies_respect_chunk_size(tmp_path: Path, strategy: str) -> None:
    path = tmp_path / "notes.txt"
    path.write_text(LONG_TEXT)
    chunks = chomper.chunk(str(path), strategy=strategy, chunk_size=25, overlap=5)
    assert all(c.word_count <= 25 for c in chunks)
    assert {w for c in chunks for w in words(c.text)} == set(words(LONG_TEXT))


def test_library_rejects_unknown_strategy(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello")
    with pytest.raises(chomper.ChomperError, match="recursive"):
        chomper.chunk(str(path), strategy="bogus")  # type: ignore[arg-type]


# ------------------------------------------------------------ structural PDF


@dataclass
class FakeBlock:
    text: str
    heading_path: str
    sequence_index: int
    extra: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self, **kwargs: Any) -> dict[str, Any]:
        return {"heading_path": self.heading_path, "section_name": self.heading_path.split(" > ")[-1]}


@dataclass
class FakeResult:
    blocks: list[FakeBlock]
    source_pdf_filename: str = "report.pdf"


def test_structural_breadcrumb_not_repeated_when_block_starts_with_heading() -> None:
    result = FakeResult([
        FakeBlock("Quarterly Report\n\nThis report covers the quarter.", "Quarterly Report", 0),
        FakeBlock("Revenue grew.", "Quarterly Report > Revenue", 1),
        FakeBlock("Revenue\n\nRevenue grew again.", "Quarterly Report > Revenue", 2),
    ])
    chunks = StructuralPDFChunker()._blocks_to_chunks(result, None)
    assert chunks[0].text == "Quarterly Report\n\nThis report covers the quarter."
    assert chunks[1].text == "Quarterly Report > Revenue\n\nRevenue grew."
    assert chunks[2].text == "Revenue\n\nRevenue grew again."
    assert not re.search(r"Quarterly Report\n\nQuarterly Report", chunks[0].text)


def test_structural_offsets_index_the_structural_text() -> None:
    blocks = [FakeBlock(f"Body {i} text.", "", i) for i in range(3)]
    chunks = StructuralPDFChunker()._blocks_to_chunks(FakeResult(blocks), None)
    joined = "\n\n".join(b.text for b in blocks)
    for c, b in zip(chunks, blocks, strict=True):
        assert joined[c.start_char:c.end_char] == b.text
        assert c.metadata["offsets"] == "structural_text"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    clear_caches()
    yield
    clear_caches()
