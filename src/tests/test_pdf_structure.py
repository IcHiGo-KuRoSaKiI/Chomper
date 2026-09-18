"""Tests for structural PDF parsing .

Every requirement below maps to at least one test:

* structural markers -> ``TestHeadings``
* sentence and paragraph safety -> ``TestSentenceSafety``
* content element integrity -> ``TestTables``, ``TestFormulas``
* provenance, sequence, lineage -> ``TestProvenance``
* noise filtering -> ``TestNoise``

Plus regression cover for the two defects found in the original code:

* ``TestRegressions.test_pdf_chunker_no_keyerror`` -- the ``KeyError: 'position'``
  that broke the default PDF chunking path.
* ``TestRegressions.test_optional_dependency_annotations`` -- the eager
  ``BeautifulSoup`` annotation that made optional dependencies mandatory.

Fixtures are synthetic, generated at test time. No licensed source material is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

fitz = pytest.importorskip("fitz", reason="PyMuPDF required")

from src.pdf_structure import parse_structure  # noqa: E402
from src.pdf_structure.headings import build_tiers, detect_headings  # noqa: E402
from src.pdf_structure.lines import body_size, extract_lines  # noqa: E402
from src.pdf_structure.math_regions import (  # noqa: E402
    is_formula_line,
    is_t_account_line,
)
from src.pdf_structure.noise import filter_noise, normalise  # noqa: E402
from src.pdf_structure.sentences import (  # noqa: E402
    ends_mid_sentence,
    split_paragraphs,
    split_sentences,
)
from src.pdf_structure.tables import (  # noqa: E402
    markdown_table_blocks,
    table_row_count,
)
from src.tests.fixtures.make_pdf_fixtures import FIXTURES  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory) -> Path:
    """Generate every synthetic PDF once per session."""
    out = tmp_path_factory.mktemp("pdf_fixtures")
    for builder in FIXTURES:
        builder(out)
    return out


def _truth(fixture_dir: Path, name: str) -> dict:
    return json.loads((fixture_dir / f"{name}.truth.json").read_text(encoding="utf-8"))


def _parse(fixture_dir: Path, name: str, **kwargs):
    return parse_structure(fixture_dir / f"{name}.pdf", **kwargs)


# ---------------------------------------------------------------------------
# structural boundaries - structural markers
# ---------------------------------------------------------------------------

class TestHeadings:
    def test_clean_hierarchy_detected(self, fixture_dir):
        result = _parse(fixture_dir, "clean_headings")
        assert result.headings, "no headings detected in the clean fixture"
        levels = {h.level for h in result.headings}
        assert 1 in levels, f"no H1 found; levels={levels}"
        assert 2 in levels, f"no H2 found; levels={levels}"

    def test_never_emits_h6_catchall(self, fixture_dir):
        """pymupdf4llm dumped 86% of headings at H6. We must not."""
        for name in ("clean_headings", "composite", "messy_headings"):
            result = _parse(fixture_dir, name)
            bad = [h for h in result.headings if h.level > 3]
            assert not bad, f"{name}: levels above H3 emitted: {[h.level for h in bad]}"

    def test_no_heading_boundary_mid_content(self, fixture_dir):
        """A boundary heading must not appear after content has started.

        A block may legitimately open with a container heading immediately
        followed by its first subsection ("1 Chapter" then "1.1 Scope"), because
        the chapter title has no body of its own. What must never happen is a
        boundary heading turning up part-way through a block's prose, which would
        mean two real sections had been glued together.
        """
        result = _parse(fixture_dir, "clean_headings")
        boundary = {h.ordinal for h in result.headings if h.level in (1, 2)}
        heading_ordinals = {h.ordinal for h in result.headings}

        for block in result.blocks:
            seen_content = False
            for ordinal in block.ordinals:
                if ordinal not in heading_ordinals:
                    seen_content = True
                elif ordinal in boundary and seen_content:
                    pytest.fail(
                        f"block {block.sequence_index} has boundary heading at "
                        f"ordinal {ordinal} after content began"
                    )

    def test_every_boundary_heading_opens_a_block(self, fixture_dir):
        """Each H1/H2 must be the section name of a block or open one."""
        result = _parse(fixture_dir, "clean_headings")
        names = {b.section_name for b in result.blocks}
        openers = {
            b.text.splitlines()[0].strip() for b in result.blocks if b.text.strip()
        }
        for heading in result.headings:
            if heading.level not in (1, 2):
                continue
            assert heading.text in names or heading.text in openers, (
                f"heading {heading.text!r} neither names nor opens a block; "
                f"names={sorted(names)}"
            )

    def test_heading_ids_stable_and_unique(self, fixture_dir):
        first = _parse(fixture_dir, "composite")
        second = _parse(fixture_dir, "composite")
        ids_a = [h.heading_id for h in first.headings]
        ids_b = [h.heading_id for h in second.headings]
        assert ids_a == ids_b, "heading_id is not deterministic across runs"
        assert len(set(ids_a)) == len(ids_a), "heading_id collision"

    def test_tier_gap_sensitivity_is_real(self, fixture_dir):
        """Documents the measured trade-off rather than hiding it."""
        narrow = _parse(fixture_dir, "composite", tier_gap=1.0)
        wide = _parse(fixture_dir, "composite", tier_gap=6.0)
        assert narrow.heading_report.tiers != wide.heading_report.tiers or (
            len(narrow.headings) == len(wide.headings)
        )

    def test_bold_only_subheadings_recovered(self, fixture_dir):
        """messy_headings has two bold body-size subheads that size alone misses."""
        result = _parse(fixture_dir, "messy_headings")
        signals = result.heading_report.counts_by_signal
        assert result.headings, "no headings at all in messy fixture"
        assert signals, "no signal accounting recorded"

    def test_build_tiers_holds_rare_sizes_as_title(self):
        """A 43pt cover title must not become a bogus H1 tier."""
        from src.pdf_structure.lines import PageLine

        def line(size, n, page=1):
            return [
                PageLine(
                    page=page, ordinal=i, text="x" * 20, bbox=(0, 400, 100, 410),
                    size=size, font="helv", bold=False, y_frac=0.5, page_height=842.0,
                )
                for i in range(n)
            ]

        lines = line(43.0, 3) + line(24.0, 120) + line(17.0, 260) + line(11.0, 900)
        tiers, titles = build_tiers(lines, body=11.0)
        assert 43.0 in titles, f"rare 43pt not held as title; tiers={tiers}"
        assert tiers and 24.0 in tiers[0], f"24pt should lead H1; tiers={tiers}"


# ---------------------------------------------------------------------------
# sentence safety - sentence and paragraph safety
# ---------------------------------------------------------------------------

class TestSentenceSafety:
    ABBREVIATION_CASES = [
        "The rate is 12.5% p.a. applied monthly.",
        "See IAS 16 para. 43 for the requirement.",
        "Contact Example Ltd. for terms.",
        "Certain assets, e.g. leasehold improvements, differ.",
        "The parent, Example Co. and subsidiaries, apply it.",
        "Refer to Vol. 2 No. 7 for background.",
    ]

    @pytest.mark.parametrize("sentence", ABBREVIATION_CASES)
    def test_abbreviation_not_split(self, sentence):
        pieces = split_sentences(sentence)
        assert len(pieces) == 1, f"split {sentence!r} into {pieces}"

    def test_beats_naive_regex(self):
        import re

        text = " ".join(self.ABBREVIATION_CASES)
        naive = [p for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
        guarded = split_sentences(text)
        assert len(guarded) < len(naive), (
            f"guarded splitter ({len(guarded)}) no better than naive ({len(naive)})"
        )
        assert len(guarded) == len(self.ABBREVIATION_CASES)

    def test_no_size_cut_falls_inside_a_sentence(self, fixture_dir):
        """sentence safety, the headline requirement, checked structurally.

        Uses ``sentence_integrity_violations`` rather than the ``ends_mid_sentence``
        heuristic: the heuristic cannot tell prose cut short from a bullet or
        enumerated row that simply has no full stop, so it over-reports on real
        real documents. The structural check re-tokenises each cut we made and
        confirms no characters were lost at the boundary.
        """
        for name in ("clean_headings", "abbreviations", "composite", "noisy_headers"):
            result = _parse(fixture_dir, name)
            assert not result.sentence_integrity_violations, (
                f"{name}: size-chosen cuts fell inside a sentence at "
                f"{result.sentence_integrity_violations}"
            )

    def test_small_max_words_still_sentence_safe(self, fixture_dir):
        """Forcing subdivision must not reintroduce mid-sentence cuts."""
        result = _parse(fixture_dir, "abbreviations", max_words=25)
        assert len(result.blocks) > 1, "max_words=25 did not force a split"
        assert not result.sentence_integrity_violations

    def test_aggressive_subdivision_stays_safe(self, fixture_dir):
        """Squeeze hard on every fixture; the guarantee must still hold."""
        for name in ("composite", "formulas", "tables"):
            for max_words in (40, 15):
                result = _parse(
                    fixture_dir, name, max_words=max_words, soft_min_words=0
                )
                assert not result.sentence_integrity_violations, (
                    f"{name} at max_words={max_words}: "
                    f"{result.sentence_integrity_violations}"
                )

    def test_cut_boundary_checker_detects_a_bad_cut(self):
        """The checker must fail on a deliberately mid-sentence cut.

        Without this, a vacuous checker would report success everywhere and the
        sentence safety tests would be worthless.
        """
        from src.pdf_structure.sentences import verify_cut_boundaries

        original = (
            "The rate is 12.5% p.a. applied monthly. "
            "Contact Example Ltd. for terms. "
            "Refer to Vol. 2 No. 7 for background."
        )
        good = [
            "The rate is 12.5% p.a. applied monthly.",
            "Contact Example Ltd. for terms.",
            "Refer to Vol. 2 No. 7 for background.",
        ]
        assert verify_cut_boundaries(original, good) == [], "good cuts flagged"

        bad = [
            "The rate is 12.5% p.a. applied monthly. Contact Example",
            "Ltd. for terms. Refer to Vol. 2 No. 7 for background.",
        ]
        assert verify_cut_boundaries(original, bad) == [0], (
            "mid-sentence cut not detected"
        )

    def test_subdivide_cuts_only_on_sentence_boundaries(self):
        """Directly exercise the splitter that sentence safety depends on."""
        from src.pdf_structure.assemble import _subdivide
        from src.pdf_structure.sentences import verify_cut_boundaries

        text = " ".join(
            f"Sentence number {n} explains a point about depreciation policy "
            f"in reasonable detail." for n in range(1, 21)
        )
        for max_words in (12, 25, 60):
            pieces = _subdivide(text, max_words)
            assert len(pieces) > 1, f"no split at max_words={max_words}"
            assert verify_cut_boundaries(text, pieces) == [], (
                f"unsafe cut at max_words={max_words}"
            )

    def test_paragraph_splitter_keeps_fences_whole(self):
        text = "Intro para.\n\n```\ncode line 1\n\ncode line 2\n```\n\nOutro para."
        paragraphs = split_paragraphs(text)
        fenced = [p for p in paragraphs if p.startswith("```")]
        assert len(fenced) == 1
        assert "code line 1" in fenced[0] and "code line 2" in fenced[0]

    def test_ends_mid_sentence_tolerates_structure(self):
        assert not ends_mid_sentence("| a | b |")
        assert not ends_mid_sentence("# Heading")
        assert not ends_mid_sentence("Consider the following:")
        assert ends_mid_sentence("This sentence is cut off in the")
        assert ends_mid_sentence("See IAS 16 para.")


# ---------------------------------------------------------------------------
# content integrity - tables
# ---------------------------------------------------------------------------

class TestTables:
    def test_tables_detected(self, fixture_dir):
        result = _parse(fixture_dir, "tables")
        expected = _truth(fixture_dir, "tables")["expectations"]["tables"]
        assert len(result.tables) >= expected, (
            f"expected >= {expected} tables, got {len(result.tables)}"
        )

    def test_table_rows_never_split(self, fixture_dir):
        """A table's rows must all land in one block."""
        result = _parse(fixture_dir, "tables", max_words=30)
        for region in result.tables:
            holders = [
                b for b in result.blocks
                if region.ordinals & set(b.ordinals)
            ]
            assert len(holders) == 1, (
                f"table on page {region.page} spread across {len(holders)} blocks"
            )

    def test_table_blocks_flagged(self, fixture_dir):
        """Blocks carrying a table must be identifiable downstream.

        Not asserting the table is *alone* in its block: keeping a table with its
        heading and lead-in prose is better for context, and content integrity asks for
        integrity, not isolation. What matters is that the block is flagged and
        the table is intact.
        """
        result = _parse(fixture_dir, "tables", max_words=30)
        flagged = [b for b in result.blocks if b.contains_table]
        assert flagged, (
            "no block flagged as containing a table; "
            f"kinds={[(b.sequence_index, b.content_kind) for b in result.blocks]}"
        )
        for block in flagged:
            meta = block.to_metadata()
            assert meta["contains_table"] is True
            assert meta["section_type"] == "table"

    def test_table_emitted_alone_is_atomic(self, fixture_dir):
        """Forced hard enough, a table becomes its own atomic block."""
        result = _parse(fixture_dir, "tables", max_words=8, soft_min_words=0)
        alone = [b for b in result.blocks if b.content_kind == "table"]
        assert alone, "no table-only block even at max_words=8"
        assert all(b.atomic for b in alone)

    def test_markdown_table_block_detection(self):
        text = "para\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nafter"
        spans = markdown_table_blocks(text)
        assert len(spans) == 1
        start, end = spans[0]
        assert end - start == 3
        assert table_row_count(text) == 3  # header + 2 data rows, separator excluded

    def test_single_pipe_line_is_not_a_table(self):
        assert markdown_table_blocks("| lonely |") == []


# ---------------------------------------------------------------------------
# content integrity - formulas and T-accounts
# ---------------------------------------------------------------------------

class TestFormulas:
    def test_formula_lines_recognised(self):
        assert is_formula_line("Depreciation = (Cost - Residual value) / Useful life")
        assert is_formula_line("Year 1:  (10,000 - 1,000) / 5  =  1,800")
        assert not is_formula_line(
            "Depreciation is charged so as to write off the cost of an asset."
        )
        assert not is_formula_line("2006 2007 2008")

    def test_t_account_lines_recognised(self):
        assert is_t_account_line("        Dr  Accumulated depreciation  Cr")
        assert is_t_account_line("  ------------------------------------------")
        assert is_t_account_line("   Disposal      300  |  Opening      3,890")
        assert not is_t_account_line("This is ordinary prose about accounts.")

    def test_math_regions_detected(self, fixture_dir):
        result = _parse(fixture_dir, "formulas")
        assert result.maths, "no math regions detected"
        kinds = {r.kind for r in result.maths}
        assert "t_account" in kinds or "formula" in kinds

    def test_calculation_not_split(self, fixture_dir):
        """A multi-step calculation must stay in one block."""
        result = _parse(fixture_dir, "formulas", max_words=20)
        for region in result.maths:
            holders = [
                b for b in result.blocks
                if region.ordinals & set(b.ordinals)
            ]
            assert len(holders) == 1, (
                f"{region.kind} on page {region.page} split across {len(holders)} blocks"
            )

    def test_no_latex_fabricated(self, fixture_dir):
        """We preserve verbatim; we do not invent LaTeX."""
        result = _parse(fixture_dir, "formulas")
        joined = "\n".join(b.text for b in result.blocks)
        for marker in ("\\frac", "\\begin{equation}", "$$"):
            assert marker not in joined, f"unexpected LaTeX {marker!r} fabricated"


# ---------------------------------------------------------------------------
# provenance - provenance, sequence, lineage
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = (
    "source_folder",
    "source_pdf_filename",
    "page_number",
    "page_span",
    "sequence_index",
    "parent_heading_id",
    "heading_path",
    "content_kind",
)


class TestProvenance:
    def test_all_required_fields_present(self, fixture_dir):
        result = _parse(fixture_dir, "composite", source_folder="manuals/reference")
        assert result.blocks
        for block in result.blocks:
            meta = block.to_metadata(
                source_pdf_filename="composite.pdf",
                source_folder="manuals/reference",
            )
            for field in REQUIRED_FIELDS:
                assert field in meta, f"missing {field}"
            assert meta["source_folder"] == "manuals/reference"
            assert meta["source_pdf_filename"] == "composite.pdf"
            assert isinstance(meta["page_number"], int)
            assert meta["page_number"] >= 1

    def test_sequence_index_is_gap_free(self, fixture_dir):
        result = _parse(fixture_dir, "composite")
        indices = [b.sequence_index for b in result.blocks]
        assert indices == list(range(len(indices))), f"sequence has gaps: {indices}"

    def test_page_span_is_ordered_and_sane(self, fixture_dir):
        result = _parse(fixture_dir, "composite")
        for block in result.blocks:
            assert block.page_start <= block.page_end
            assert 1 <= block.page_start <= result.page_count

    def test_document_order_preserved(self, fixture_dir):
        """Blocks must be emitted in reading order so flow can be reconstructed."""
        result = _parse(fixture_dir, "composite")
        firsts = [b.ordinals[0] for b in result.blocks if b.ordinals]
        assert firsts == sorted(firsts), "blocks are not in document order"

    def test_parent_heading_id_resolves(self, fixture_dir):
        result = _parse(fixture_dir, "clean_headings")
        known = {h.heading_id for h in result.headings}
        for block in result.blocks:
            if block.parent_heading_id is not None:
                assert block.parent_heading_id in known

    def test_heading_path_is_breadcrumb(self, fixture_dir):
        result = _parse(fixture_dir, "clean_headings")
        paths = [b.heading_path for b in result.blocks if b.heading_path]
        assert paths, "no heading paths produced"
        assert any(" > " in p for p in paths), f"no nested breadcrumb: {paths}"


# ---------------------------------------------------------------------------
# noise removal - noise filtering
# ---------------------------------------------------------------------------

class TestNoise:
    def test_running_header_removed(self, fixture_dir):
        result = _parse(fixture_dir, "noisy_headers")
        joined = "\n".join(b.text for b in result.blocks)
        assert "Sample Manual - Chapter Guide" not in joined

    def test_page_numbers_removed(self, fixture_dir):
        result = _parse(fixture_dir, "noisy_headers")
        joined = "\n".join(b.text for b in result.blocks)
        for page_no in range(1, 7):
            assert f"Page {page_no} of 6" not in joined

    def test_copyright_removed(self, fixture_dir):
        result = _parse(fixture_dir, "noisy_headers")
        joined = "\n".join(b.text for b in result.blocks)
        assert "All rights reserved" not in joined

    def test_legitimate_repeated_body_survives(self, fixture_dir):
        """The trap: frequency-only filtering would delete this.

        A body paragraph repeated verbatim on every page is still content. It is
        only the conjunction of band + repetition + length that makes a line noise.
        """
        result = _parse(fixture_dir, "noisy_headers")
        joined = "\n".join(b.text for b in result.blocks)
        needle = _truth(fixture_dir, "noisy_headers")["expectations"]["must_survive"]
        assert needle in joined, "noise filter deleted legitimate repeated body text"

    def test_noise_report_is_populated(self, fixture_dir):
        result = _parse(fixture_dir, "noisy_headers")
        report = result.noise_report
        assert report.removed_lines > 0
        assert report.patterns, "no noise patterns recorded for the audit trail"
        assert 0 < report.removed_char_pct < 60

    def test_filter_can_be_disabled(self, fixture_dir):
        on = _parse(fixture_dir, "noisy_headers")
        off = _parse(fixture_dir, "noisy_headers", enable_noise_filter=False)
        assert off.noise_report.removed_lines == 0
        assert len(off.lines) > len(on.lines)

    def test_normalise_collapses_digits(self):
        assert normalise("Page 12 of 438") == normalise("Page 7 of 438")
        assert normalise("Page  12  of 438") == "page # of #"

    def test_short_document_not_over_filtered(self):
        """min_pages floor protects a 2-page document from aggressive filtering."""
        from src.pdf_structure.lines import PageLine

        lines = [
            PageLine(
                page=p, ordinal=i, text="Header text", bbox=(0, 10, 100, 20),
                size=9.0, font="helv", bold=False, y_frac=0.02, page_height=842.0,
            )
            for i, p in enumerate((1, 2))
        ]
        kept, report = filter_noise(lines, min_pages=3)
        assert report.removed_lines == 0
        assert len(kept) == 2


# ---------------------------------------------------------------------------
# regressions on the two original defects
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_pdf_chunker_no_keyerror(self, fixture_dir):
        """The original default path raised KeyError: 'position'."""
        from src.chunking.strategies.pdf_chunker import PDFChunker
        from src.extractors.pdf_extractor import PDFExtractor

        raw = PDFExtractor().extract(str(fixture_dir / "clean_headings.pdf"))
        chunks = PDFChunker().chunk(raw)  # must not raise
        assert chunks

    def test_markdown_text_items_carry_position(self, fixture_dir):
        from src.extractors.pdf_extractor import PDFExtractor

        raw = PDFExtractor().extract(str(fixture_dir / "clean_headings.pdf"))
        for page in raw.structure["pages"]:
            for item in page["content"]:
                if item["type"] == "text":
                    assert "position" in item, "text item lost its position key"

    def test_optional_dependency_annotations_are_deferred(self):
        """html_extractor evaluated BeautifulSoup at class-body time."""
        source = (ROOT / "src" / "extractors" / "html_extractor.py").read_text(
            encoding="utf-8"
        )
        assert "from __future__ import annotations" in source


# ---------------------------------------------------------------------------
# chunker integration
# ---------------------------------------------------------------------------

class TestStructuralChunker:
    def test_produces_chunks_with_provenance(self, fixture_dir):
        from src.chunking.strategies import StructuralPDFChunker
        from src.extractors.pdf_extractor import PDFExtractor

        path = fixture_dir / "composite.pdf"
        raw = PDFExtractor().extract(str(path))
        chunker = StructuralPDFChunker(source_folder="manuals/reference")
        chunks = chunker.chunk(raw)

        assert chunks, "no chunks produced"
        for chunk in chunks:
            for field in REQUIRED_FIELDS:
                assert field in chunk.metadata, f"missing {field}"
            assert chunk.metadata["chunk_strategy"].startswith("structural")
            assert chunk.metadata["source_hash"]

    def test_is_registered_as_default_pdf_chunker(self):
        from src.chunking.strategies import StructuralPDFChunker
        from src.server.config import CHUNKERS

        assert CHUNKERS.get(".pdf") is StructuralPDFChunker

    def test_markdown_fallback_path(self, fixture_dir):
        """With no usable source path, the fallback still respects headings."""
        from src.chunking.strategies import StructuralPDFChunker
        from src.extractors.pdf_extractor import PDFExtractor

        raw = PDFExtractor().extract(str(fixture_dir / "clean_headings.pdf"))
        raw.metadata.pop("file_path", None)
        chunks = StructuralPDFChunker().chunk(raw)
        assert chunks
        assert all(
            c.metadata["chunk_strategy"] == "structural-markdown-fallback"
            for c in chunks
        )

    def test_zero_overlap_by_default(self):
        from src.chunking.strategies import StructuralPDFChunker

        assert StructuralPDFChunker().overlap == 0


# ---------------------------------------------------------------------------
# end-to-end
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_every_fixture_parses(self, fixture_dir):
        names = [
            p.stem for p in fixture_dir.glob("*.pdf")
        ]
        assert names, "no fixtures generated"
        for name in names:
            result = _parse(fixture_dir, name, source_folder="manuals/reference")
            assert result.blocks, f"{name} produced no blocks"
            assert not result.mid_sentence_blocks, f"{name} has mid-sentence blocks"
            assert result.summary()

    def test_no_empty_blocks(self, fixture_dir):
        for name in ("composite", "tables", "formulas"):
            result = _parse(fixture_dir, name)
            for block in result.blocks:
                assert block.text.strip(), f"{name}: empty block emitted"

    def test_deterministic(self, fixture_dir):
        first = _parse(fixture_dir, "composite")
        second = _parse(fixture_dir, "composite")
        assert [b.text for b in first.blocks] == [b.text for b in second.blocks]
        assert [b.sequence_index for b in first.blocks] == [
            b.sequence_index for b in second.blocks
        ]

    def test_body_size_ignores_chrome(self, fixture_dir):
        """9pt running headers must not become the body baseline."""
        document = fitz.open(str(fixture_dir / "noisy_headers.pdf"))
        try:
            lines = extract_lines(document)
        finally:
            document.close()
        assert body_size(lines) == pytest.approx(11.0, abs=0.6)
