# Structural PDF parsing

Adds heading-bounded, table-safe, sentence-safe PDF chunking with provenance, and
fixes two defects that made the original PDF path unusable.

Aimed at long, heavily-formatted documents — textbooks, manuals, reference works —
where headings, tables and worked calculations carry the structure.

---

## Why

The original `PDFChunker` sliced a flat word list. Measured on a test document, **13 of
15 chunks ended mid-sentence**, and on its default settings it did not run at all.

## Defects fixed

| | Problem | Fix |
|---|---|---|
| **C-1** | `PDFChunker` raised `KeyError: 'position'` on its own default path. `pdf_extractor._extract_with_markdown` built text items as `{type, content, format}`, while `pdf_chunker._finalize_chunk` indexed `item["position"]` unconditionally. Only `chunk_by_page=True` worked. | Markdown text items now always carry `position` (the page rect). `_finalize_chunk` treats it as optional so the class of bug cannot recur. |
| **C-2** | `import src` failed without `beautifulsoup4`, because `html_extractor.py` used `BeautifulSoup` in a runtime-evaluated annotation. "Optional" dependencies were mandatory. | Added `from __future__ import annotations`. |

## What is new

`src/pdf_structure/` — six pure stages over a positional line model:

| Module | Job |
|---|---|
| `lines.py` | One `PageLine` per rendered line: font size, weight, bbox, page band. |
| `noise.py` | Removes running headers, footers and boilerplate. |
| `headings.py` | Heading levels from font-size tiers + bold promotion + numbering override. |
| `tables.py` | Geometric table regions, merged and made contiguous so they stay atomic. |
| `math_regions.py` | Formula and T-account regions, kept atomic. |
| `sentences.py` | Reflow, abbreviation-safe sentence splitting, cut verification. |
| `assemble.py` | Builds blocks and stamps provenance. |

`src/chunking/strategies/structural_pdf_chunker.py` — `StructuralPDFChunker`,
now the default for `.pdf`. `PDFChunker` remains importable for page or
word-count slicing.

```python
from src.pdf_structure import parse_structure

result = parse_structure("course.pdf", source_folder="manuals/reference")
print(result.summary())
print(result.sentence_integrity_violations)   # [] means no cut split a sentence
```

## Measured on the real 438-page document

68,880 words. Statistics only; no licensed content is reproduced in this repo.

| | max_words=600 | max_words=60 | max_words=30 |
|---|---|---|---|
| blocks | 775 | 1,665 | 2,926 |
| size-chosen cuts | 0 | 1,165 | 2,630 |
| **cuts splitting a sentence** | **0** | **0** | **0** |
| **tables split** | **0/192** | **0/192** | **0/192** |
| **math regions split** | **0/148** | **0/148** | **0/148** |
| sequence gap-free | yes | yes | yes |
| running header removed | yes | yes | yes |
| page numbers removed | yes | yes | yes |

Noise removal strips 4.8% of characters across 20 distinct forms. Extraction is
~215s for 438 pages, so cache it rather than re-running per stage.

## Three findings worth knowing

**Heading levels from `pymupdf4llm` are not usable.** On the real document it emitted
1,270 headings of which 1,090 (86%) were H6 and only 2 were H1 — H6 is a catch-all.
Levels are computed here from font-size tiers instead.

**Font-size tier boundaries are not settled.** Clustering with a 1.0pt gap yields three
tiers but discards 164 probable heading lines; 2.0pt discards none but collapses
13pt–18pt into one H2 bucket. `gap=2.0` is the default because losing content is worse
than over-merging, but **neither is provably right without labelled ground truth**. See
`test_tier_gap_sensitivity_is_real` and the `messy_headings` fixture. This is the
component to calibrate first.

**LaTeX is deliberately not generated.** The real document contains *zero* unicode
superscripts, so exponents are already flattened before any parser sees them.
Reconstructing LaTeX from `x2` is guesswork, and silently-wrong maths is worse than
plainly-preserved maths. Formula regions are detected, kept atomic and tagged, and their
bounding boxes travel with them so a vision model can transcribe them if needed.

## Provenance on every block

`source_folder`, `source_pdf_filename`, `page_number`, `page_span`,
`sequence_index`, `parent_heading_id`, `heading_path`, `heading_level`, `section_name`,
`content_kind`, `contains_table`, `contains_math`, `source_hash`.

## Tests

```bash
pip install pymupdf pymupdf4llm pysbd pytest
pytest src/tests/test_pdf_structure.py -q      # 58 tests
```

Fixtures are synthetic, generated at test time by
`src/tests/fixtures/make_pdf_fixtures.py`, each with a labelled ground-truth sidecar.
Their *shape* copies measurements from real documents; all wording is invented.

```bash
python src/tests/fixtures/make_pdf_fixtures.py --list
```

Two tests exist specifically to stop the suite becoming self-congratulatory:

- `test_cut_boundary_checker_detects_a_bad_cut` — proves the checker fails on a
  deliberately mid-sentence cut. An earlier version of that checker compared each piece
  against its own re-tokenisation, which is trivially equal for any text and therefore
  proved nothing.
- `test_noise_filter_spares_body` — a paragraph repeated verbatim on every page must
  **survive**. Filtering on repetition alone deletes real content; it is the conjunction
  of page band, repetition and length that identifies chrome.

## Scope

Parsing only. Question/option grouping, answer-key cross-referencing
(`parent_question_id`), flowchart alt-text and image analysis are deliberately absent —
they are post-text semantic concerns for a later stage. The parser carries no
course-domain vocabulary.

## New dependencies

`pymupdf`, `pymupdf4llm`, `pysbd`. All already optional-PDF territory except `pysbd`,
which is small and pure Python; the sentence splitter degrades to a guarded regex
without it.
