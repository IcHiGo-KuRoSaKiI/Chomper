"""Layout PDF chunking: structure-aware splitting of the layout-model Markdown."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import chomper
from src.chunking.strategies.layout_pdf_chunker import (
    LayoutPDFChunker,
    join_continuations,
    page_spans,
    running_head_lines,
)
from src.chunking.text_splitter import segment
from src.models.document import RawDocument
from src.server import cache as cache_mod
from src.server.documents import build_chunker


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache_mod.clear_caches()
    yield
    cache_mod.clear_caches()


def doc_from_pages(pages: list[str]) -> RawDocument:
    """A RawDocument shaped like PDFExtractor's layout output."""
    return RawDocument(
        text="\n\n".join(p.strip("\n") for p in pages if p.strip()),
        metadata={"extraction_method": "pymupdf-layout"},
        structure={
            "pages": [
                {"page_number": i, "markdown_text": p, "content": []}
                for i, p in enumerate(pages, start=1)
            ]
        },
    )


def prose(n: int, label: str = "Item") -> str:
    return " ".join(f"{label} {i} is described in one plain sentence." for i in range(n))


def pipe_table(rows: int) -> str:
    body = "\n".join(f"| Region {i} | {100 + i} | {i * 3}% |" for i in range(rows))
    return f"| Region | Branches | Growth |\n| --- | --- | --- |\n{body}"


def chunk(doc: RawDocument, size: int, overlap: int = 0) -> list:
    return LayoutPDFChunker(target_size=size, overlap=overlap).chunk(doc)


# ----------------------------------------------------------------- offsets, pages


def test_offsets_point_into_parse_text_and_pages_are_tracked() -> None:
    doc = doc_from_pages([
        f"# Report\n\n{prose(12)}\n\n## Scope\n\n{prose(12, 'Scope')}",
        f"{prose(12, 'More')}\n\n## Results\n\n{prose(12, 'Result')}",
        f"### Detail\n\n{prose(30, 'Detail')}",
    ])
    chunks = chunk(doc, size=60)
    assert len(chunks) > 3
    for c in chunks:
        assert doc.text[c.start_char : c.end_char] == c.text
        assert c.metadata["pages"] and c.metadata["page"] == c.metadata["pages"][0]
        assert c.metadata["page_span"] == [c.metadata["pages"][0], c.metadata["pages"][-1]]
        assert c.metadata["offsets"] == "parse_text"
        assert c.metadata["chunk_strategy"] == "layout"
    spans = page_spans(doc)
    assert [s.page for s in spans] == [1, 2, 3]
    for span, page in zip(spans, doc.structure["pages"], strict=True):
        assert doc.text[span.start : span.end] == page["markdown_text"].strip()
    by_text = {c.text.split("\n", 1)[0]: c for c in chunks}
    assert by_text["### Detail"].metadata["heading_path"] == "Report > Results > Detail"
    assert by_text["### Detail"].metadata["section_name"] == "Detail"
    assert by_text["### Detail"].metadata["pages"] == [3]
    big = chunk(doc, size=1000)
    assert [c.metadata["pages"] for c in big] == [[1], [1, 2], [2, 3]]


def test_level_two_headings_always_start_a_chunk() -> None:
    doc = doc_from_pages([f"# A\n\n{prose(2)}\n\n## B\n\n{prose(2)}\n\n### C\n\n{prose(2)}"])
    chunks = chunk(doc, size=500)
    assert [c.text.split("\n", 1)[0] for c in chunks] == ["# A", "## B"]
    assert "### C" in chunks[1].text  # level 3 is a preferred, not a forced, cut


# ------------------------------------------------------------------------ tables


def test_table_that_fits_is_never_split() -> None:
    table = pipe_table(6)
    doc = doc_from_pages([f"# T\n\n{prose(8)}\n\n{table}\n\n{prose(3, 'After')}"])
    chunks = chunk(doc, size=90)
    holders = [c for c in chunks if "| Region |" in c.text or "| Region " in c.text]
    assert len(holders) == 1 and table in holders[0].text


def test_oversized_table_is_split_by_rows_with_the_header_repeated() -> None:
    table = pipe_table(60)
    doc = doc_from_pages([f"# Big\n\n{prose(3)}\n\n{table}\n\n{prose(3, 'Tail')}"])
    chunks = chunk(doc, size=80, overlap=10)
    parts = [c for c in chunks if "| Region" in c.text]
    assert len(parts) > 2
    header = "| Region | Branches | Growth |\n| --- | --- | --- |"
    seen_rows: list[str] = []
    for i, c in enumerate(parts):
        table_text = c.text[c.text.index("| Region | Branches"):]
        assert table_text.startswith(header)
        assert c.metadata["table_header_repeated"] is (i > 0)
        if i > 0:
            assert c.text.startswith(header)  # nothing before the repeated header
            assert doc.text[c.start_char : c.end_char] == c.text[len(header) + 1 :]
        seen_rows += [r for r in table_text.splitlines()[2:] if r.startswith("| Region ")]
        assert c.word_count <= 80 + 6  # header words may be repeated on top
    assert seen_rows == table.splitlines()[2:]  # every row once, in order


def test_oversized_html_table_pieces_are_complete_tables() -> None:
    rows = "".join(f"<tr><td>Region {i}</td><td>{100 + i}</td></tr>" for i in range(200))
    table = f"<table><tr><th>Region</th><th>Branches</th></tr>{rows}</table>"
    doc = doc_from_pages([f"# Html\n\n{prose(3)}\n\n{table}\n\n{prose(2, 'Tail')}"])
    chunks = chunk(doc, size=60)
    parts = [c for c in chunks if "<tr>" in c.text]
    assert len(parts) > 2
    all_rows: list[str] = []
    for i, c in enumerate(parts):
        tables = re.findall(r"<table>.*?</table>", c.text, re.S)
        assert len(tables) == 1 and c.text.count("<table>") == c.text.count("</table>") == 1
        html = tables[0]
        assert "<th>Region</th>" in html
        assert c.metadata["table_header_repeated"] is (i > 0)
        all_rows += re.findall(r"<tr><td>.*?</tr>", html)
    assert "".join(all_rows) == rows


# ----------------------------------------------------------------------- figures


def test_figure_marker_line_is_never_split() -> None:
    caption = " ".join(f"Caption sentence {i} describes the chart." for i in range(20))
    marker = f"![{caption}](image:p1-1)"
    doc = doc_from_pages([f"# Fig\n\n{prose(4)}\n\n{marker}\n\n{prose(4, 'After')}"])
    chunks = chunk(doc, size=30)
    holders = [c for c in chunks if "image:p1-1" in c.text]
    assert len(holders) == 1 and marker in holders[0].text
    assert holders[0].metadata["image_ids"] == ["p1-1"]
    assert holders[0].metadata["has_images"] is True


def test_overlap_never_repeats_a_table_or_figure() -> None:
    doc = doc_from_pages([
        f"# O\n\n{prose(5)}\n\n{pipe_table(3)}\n\n![Small chart](image:p1-1)\n\n{prose(30, 'Next')}"
    ])
    chunks = chunk(doc, size=60, overlap=40)
    assert sum(c.text.count("image:p1-1") for c in chunks) == 1
    assert sum(c.text.count("| Region | Branches") for c in chunks) == 1


# ---------------------------------------------------------- page/column seams


def test_sentence_running_over_a_page_break_is_not_cut_there() -> None:
    first = f"# Seam\n\n{prose(10)} The total for the year rose because the branches"
    second = f"opened in the spring added new borrowers. {prose(10, 'Later')}"
    doc = doc_from_pages([first, second])
    seam = doc.text.index("opened in the spring")
    units = join_continuations(doc.text, segment(doc.text, 40), 40)
    joined = next(u for u in units if u.start < seam < u.end)
    assert doc.text[joined.start : joined.end].startswith("The total for the year")
    assert doc.text[joined.start : joined.end].endswith("added new borrowers.")
    for size in (30, 60, 110):
        for c in chunk(doc, size=size):
            assert not c.text.rstrip().endswith("the branches")
            assert not c.text.startswith("opened")


def test_running_heads_do_not_cut_chunks_or_enter_heading_paths() -> None:
    pages = []
    for n in range(6):
        head = "## Dept. of Examples" if n % 2 else "## 45 CFR Subtitle A (2023 Edition)"
        pages.append(f"{head}\n\n{prose(8, f'P{n}')} The rule applies to every\n\n{600 + n}")
        pages[-1] = pages[-1].replace("applies to every\n\n", f"applies to every\n\nrecord kept on page {n}.\n\n")
    doc = doc_from_pages([f"# Part 1\n\n{prose(2)}"] + pages)
    running = {doc.text[s:e] for s, e in running_head_lines(doc.text, page_spans(doc))}
    assert "## Dept. of Examples" in running and "## 45 CFR Subtitle A (2023 Edition)" in running
    assert "600" in running  # folios too
    chunks = chunk(doc, size=2000)
    assert len(chunks) == 1  # running heads are not section cuts
    assert chunks[0].metadata["heading_path"] == "Part 1"
    assert chunks[0].metadata["has_running_heads"] is True
    assert doc.text[chunks[0].start_char : chunks[0].end_char] == chunks[0].text


# --------------------------------------------------------------- factory wiring


def test_layout_strategy_is_pdf_only() -> None:
    assert isinstance(build_chunker(".pdf", "layout"), LayoutPDFChunker)
    assert not isinstance(build_chunker(".md", "layout"), LayoutPDFChunker)
    assert type(build_chunker(".md", "layout")) is type(build_chunker(".md", "auto"))


def _story_pdf(path: Path) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    rows = "".join(f"<tr><td>Region {i}</td><td>{100 + i}</td></tr>" for i in range(1, 31))
    para = " ".join(f"Sentence {i} explains the operating results." for i in range(1, 30))
    html = (
        f"<h1>Annual Review</h1><p>{para}</p><h2>1. Operations</h2><p>{para}</p>"
        f"<table><tr><th>Region</th><th>Branches</th></tr>{rows}</table>"
        f"<h2>2. Outlook</h2><p>{para}</p>"
    )
    css = "h1{font-size:22pt} h2{font-size:16pt} td,th{border:1px solid black}"
    story = pymupdf.Story(html=html, user_css=css)
    writer = pymupdf.DocumentWriter(str(path))
    more = True
    while more:
        device = writer.begin_page(pymupdf.paper_rect("a5"))
        more, _ = story.place(pymupdf.paper_rect("a5") + (36, 36, -36, -36))
        story.draw(device)
        writer.end_page()
    writer.close()
    return path


def test_layout_chunks_of_a_real_pdf_index_parse_text(tmp_path: Path) -> None:
    pdf = _story_pdf(tmp_path / "story.pdf")
    text = chomper.parse(pdf).text
    chunks = chomper.chunk(pdf, strategy="layout", chunk_size=120, overlap=0)
    assert len(chunks) > 3
    assert len({p for c in chunks for p in c.metadata["pages"]}) > 1
    for c in chunks:
        if not c.metadata["table_header_repeated"]:
            assert text[c.start_char : c.end_char] == c.text
        assert c.metadata["heading_path"].startswith("Annual Review")
    assert any(c.section_name == "1. Operations" for c in chunks)
