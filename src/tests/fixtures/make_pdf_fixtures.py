"""Generate synthetic course-PDF fixtures for the the structural parsing work parser.

Why synthetic: no licensed source material may live in this repo,
so every fixture is written from scratch here. The *shape* is copied from measurements
taken on a real 438-page reference document -- 11pt body, heading tiers at 24/22/17/15pt, a running
header on every page, a ``Page N of M`` footer, ruled tables on ~58% of pages -- but all
wording is invented and deliberately bland.

Each fixture ships a ground-truth sidecar (``<name>.truth.json``) recording exactly which
lines are headings, at which level, which regions are atomic, and which lines are noise.
That sidecar is what lets us *measure* heading precision/recall instead of eyeballing it,
which is the gate on open question Q1 in ``docs/PDF_PARSING_SPEC.md``.

Usage::

    python tests/fixtures/pdf/make_fixtures.py            # writes ./out/
    python tests/fixtures/pdf/make_fixtures.py --list     # describe fixtures only
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    raise SystemExit("PyMuPDF required:  pip install pymupdf")

# Measured from the reference document. Keep these in step with the spec's evidence table.
BODY_SIZE = 11.0
H1_SIZE = 24.0
H2_SIZE = 17.0
H3_SIZE = 15.0
TITLE_SIZE = 43.0
NOISE_SIZE = 9.0
FOOTER_SIZE = 8.5

PAGE_W, PAGE_H = 595.0, 842.0  # A4 points
LEFT, RIGHT = 72.0, 523.0
TOP_BAND = 40.0
BOT_BAND = 800.0

#: First baseline for body content. Kept clear of the 10% top band (84pt) so that
#: a large heading's glyph box does not stray into the header zone -- real course
#: PDFs have a comparable top margin.
CONTENT_TOP = 130.0

RUNNING_HEADER = "Sample Manual - Chapter Guide"
COPYRIGHT = "(c) Example Foundation. All rights reserved."

# Bland invented prose. Long enough to force size-based subdivision when needed.
PROSE = (
    "Depreciation is charged so as to write off the cost of an asset over its estimated "
    "useful life. The straight line method is applied to plant and machinery, and the "
    "reducing balance method is applied to motor vehicles. Residual values are reviewed "
    "at each reporting date and adjusted where the carrying amount of an asset exceeds "
    "its recoverable amount. Any resulting impairment is recognised in profit or loss "
    "for the period in which it arises. "
)
ABBREV_PROSE = (
    "The rate is 12.5% p.a. applied monthly. See IAS 16 para. 43 for the detailed "
    "requirement. Contact Example Ltd. for commercial terms. Certain assets, e.g. "
    "leasehold improvements, are treated separately. The parent, Example Co. and its "
    "subsidiaries, apply a uniform policy. Refer to Vol. 2 No. 7 for background. "
)


@dataclass
class Truth:
    """Ground truth for one fixture."""

    fixture: str
    description: str
    pages: int
    headings: list[dict] = field(default_factory=list)
    noise_lines: list[dict] = field(default_factory=list)
    atomic_regions: list[dict] = field(default_factory=list)
    expectations: dict = field(default_factory=dict)


class Builder:
    """Thin wrapper that records ground truth as it draws."""

    def __init__(self, name: str, description: str) -> None:
        self.doc = fitz.open()
        self.truth = Truth(fixture=name, description=description, pages=0)
        self.page = None
        self.y = 0.0

    def new_page(self, *, header: bool = False, footer: bool = False,
                 page_no: int = 1, total: int = 1) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = CONTENT_TOP
        if header:
            self.page.insert_text((LEFT, TOP_BAND), RUNNING_HEADER, fontsize=NOISE_SIZE)
            self.truth.noise_lines.append(
                {"page": page_no, "text": RUNNING_HEADER, "kind": "running_header"}
            )
        if footer:
            f = f"Page {page_no} of {total}"
            self.page.insert_text((LEFT, BOT_BAND), f, fontsize=NOISE_SIZE)
            self.page.insert_text((300, BOT_BAND), COPYRIGHT, fontsize=FOOTER_SIZE)
            self.truth.noise_lines.append(
                {"page": page_no, "text": f, "kind": "page_number"}
            )
            self.truth.noise_lines.append(
                {"page": page_no, "text": COPYRIGHT, "kind": "copyright"}
            )
        self.truth.pages = len(self.doc)

    def heading(self, text: str, level: int, page_no: int, *,
                size: float | None = None, bold: bool = False) -> None:
        sizes = {1: H1_SIZE, 2: H2_SIZE, 3: H3_SIZE}
        sz = size if size is not None else sizes[level]
        font = "hebo" if bold else "helv"
        self.page.insert_text((LEFT, self.y), text, fontsize=sz, fontname=font)
        self.truth.headings.append(
            {"page": page_no, "text": text, "level": level,
             "size": sz, "bold": bold, "y": self.y}
        )
        self.y += sz * 1.9

    def prose(self, text: str, *, height: float = 100.0) -> None:
        rect = fitz.Rect(LEFT, self.y, RIGHT, self.y + height)
        self.page.insert_textbox(rect, text, fontsize=BODY_SIZE, fontname="helv")
        self.y += height + 10

    def ruled_table(self, page_no: int, rows: list[list[str]], label: str) -> None:
        """Draw a table WITH ruled lines so table_strategy='lines_strict' finds it."""
        y0 = self.y
        col_w = (RIGHT - LEFT) / len(rows[0])
        rh = 18.0
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                x = LEFT + c * col_w
                self.page.insert_text((x + 3, y0 + r * rh + 12), cell, fontsize=BODY_SIZE)
        # ruled grid
        for r in range(len(rows) + 1):
            yy = y0 + r * rh
            self.page.draw_line(fitz.Point(LEFT, yy), fitz.Point(RIGHT, yy))
        for c in range(len(rows[0]) + 1):
            xx = LEFT + c * col_w
            self.page.draw_line(fitz.Point(xx, y0), fitz.Point(xx, y0 + len(rows) * rh))
        self.truth.atomic_regions.append(
            {"page": page_no, "kind": "table", "label": label,
             "rows": len(rows), "cols": len(rows[0]),
             "bbox": [LEFT, y0, RIGHT, y0 + len(rows) * rh]})
        self.y = y0 + len(rows) * rh + 16

    def formula(self, page_no: int, lines: list[str], kind: str, label: str) -> None:
        y0 = self.y
        for ln in lines:
            self.page.insert_text((LEFT, self.y), ln, fontsize=BODY_SIZE, fontname="cour")
            self.y += 15
        self.truth.atomic_regions.append(
            {"page": page_no, "kind": kind, "label": label,
             "lines": len(lines), "bbox": [LEFT, y0, RIGHT, self.y]})
        self.y += 10

    def save(self, outdir: Path) -> tuple[Path, Path]:
        pdf = outdir / f"{self.truth.fixture}.pdf"
        truth = outdir / f"{self.truth.fixture}.truth.json"
        self.doc.save(str(pdf))
        self.doc.close()
        truth.write_text(json.dumps(asdict(self.truth), indent=2), encoding="utf-8")
        return pdf, truth


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

def fx_clean_headings(out: Path):
    """Well-behaved hierarchy. The happy path for P3."""
    b = Builder("clean_headings", "Consistent H1/H2/H3 font tiers, numbered, no noise.")
    total = 3
    b.new_page(page_no=1, total=total)
    b.heading("1 Non-current assets", 1, 1)
    b.heading("1.1 Depreciation methods", 2, 1)
    b.prose(PROSE)
    b.heading("1.1.1 Straight line", 3, 1)
    b.prose(PROSE)
    b.new_page(page_no=2, total=total)
    b.heading("1.2 Revaluation", 2, 2)
    b.prose(PROSE * 2, height=200)
    b.new_page(page_no=3, total=total)
    b.heading("2 Financial statements", 1, 3)
    b.heading("2.1 Statement of financial position", 2, 3)
    b.prose(PROSE)
    b.truth.expectations = {
        "headings_total": 7, "h1": 2, "h2": 3, "h3": 1,
        "note": "one H3 plus 1.1.1 counted at level 3",
        "min_blocks": 6,
    }
    return b.save(out)


def fx_noisy(out: Path):
    """Running header + page number + copyright on EVERY page. Targets noise removal."""
    b = Builder("noisy_headers",
                "Running header, page numbers and copyright on all pages; "
                "also repeats one legitimate body paragraph to catch over-filtering.")
    total = 6
    for p in range(1, total + 1):
        b.new_page(header=True, footer=True, page_no=p, total=total)
        if p == 1:
            b.heading("1 Regulatory framework", 1, p)
        b.heading(f"1.{p} Guidance note {p}", 2, p)
        b.prose(PROSE)
        # deliberately identical paragraph on every page -- must SURVIVE filtering
        b.prose("This paragraph is repeated verbatim on every page of the document and "
                "is legitimate body content that must not be removed by noise filtering.",
                height=60)
    b.truth.expectations = {
        "noise_kinds": ["running_header", "page_number", "copyright"],
        "noise_on_all_pages": True,
        "must_survive": "This paragraph is repeated verbatim on every page",
        "note": "frequency-only filtering would wrongly delete must_survive",
    }
    return b.save(out)


def fx_tables(out: Path):
    """Ruled financial tables. Targets content integrity-tables."""
    b = Builder("tables", "Ruled pro-forma statements and a reconciliation schedule.")
    # Four pages, not two: the noise filter needs a line to recur on at least
    # three pages before it will call it a running header, so a two-page fixture
    # would leave the header in and pollute the blocks.
    total = 4
    b.new_page(header=True, footer=True, page_no=1, total=total)
    b.heading("3 Statement of financial position", 1, 1)
    b.prose(PROSE, height=70)
    b.ruled_table(1, [
        ["Asset", "Cost", "Depn", "NBV"],
        ["Plant", "10,000", "2,000", "8,000"],
        ["Vehicles", "5,000", "1,250", "3,750"],
        ["Fixtures", "3,200", "640", "2,560"],
        ["Total", "18,200", "3,890", "14,310"],
    ], label="ppe_summary")
    b.new_page(header=True, footer=True, page_no=2, total=total)
    b.heading("3.1 Property, plant and equipment roll-forward", 2, 2)
    b.ruled_table(2, [
        ["", "Opening", "Additions", "Disposals", "Closing"],
        ["Cost", "18,200", "4,000", "(1,200)", "21,000"],
        ["Depreciation", "(3,890)", "(1,100)", "300", "(4,690)"],
        ["Carrying amount", "14,310", "2,900", "(900)", "16,310"],
    ], label="ppe_rollforward")
    b.prose(PROSE, height=70)
    for page_no in (3, 4):
        b.new_page(header=True, footer=True, page_no=page_no, total=total)
        b.heading(f"3.{page_no} Further disclosure {page_no}", 2, page_no)
        b.prose(PROSE, height=110)
    b.truth.expectations = {
        "tables": 2,
        "table_must_not_split": True,
        "rows_preserved": {"ppe_summary": 5, "ppe_rollforward": 4},
    }
    return b.save(out)


def fx_formulas(out: Path):
    """Formulas and T-accounts. Targets content integrity-math."""
    b = Builder("formulas", "Inline formulas, a worked calculation and a T-account.")
    # Four pages so the running header repeats often enough to be recognised as
    # chrome. A single-page fixture cannot exercise running-noise removal at all.
    total = 4
    b.new_page(header=True, footer=True, page_no=1, total=total)
    b.heading("4 Depreciation workings", 1, 1)
    b.prose(PROSE, height=60)
    b.formula(1, ["Depreciation = (Cost - Residual value) / Useful life"],
              kind="formula", label="straight_line")
    b.formula(1, [
        "Year 1:  (10,000 - 1,000) / 5  =  1,800",
        "Year 2:  (10,000 - 1,000) / 5  =  1,800",
        "Year 3:  (10,000 - 1,000) / 5  =  1,800",
    ], kind="formula", label="worked_steps")
    b.new_page(header=True, footer=True, page_no=2, total=total)
    b.heading("4.1 Accumulated depreciation", 2, 2)
    b.prose(PROSE, height=60)
    b.formula(2, [
        "        Dr  Accumulated depreciation  Cr",
        "  ------------------------------------------",
        "   Disposal      300  |  Opening      3,890",
        "                      |  Charge       1,100",
        "  ------------------------------------------",
        "   Closing     4,690  |               4,990",
    ], kind="t_account", label="accum_depn_t")
    for page_no in (3, 4):
        b.new_page(header=True, footer=True, page_no=page_no, total=total)
        b.heading(f"4.{page_no} Worked example {page_no}", 2, page_no)
        b.prose(PROSE, height=110)
    b.truth.expectations = {
        "formula_regions": 2, "t_account_regions": 1,
        "must_not_split_mid_calculation": True,
        "latex_expected": False,
        "note": "parser preserves verbatim; LaTeX is the vision lane's job",
    }
    return b.save(out)


def fx_abbreviations(out: Path):
    """Abbreviation-dense prose. Targets sentence safety sentence safety."""
    b = Builder("abbreviations", "Prose dense in accounting abbreviations.")
    b.new_page(page_no=1, total=1)
    b.heading("5 Commercial terms", 1, 1)
    b.prose(ABBREV_PROSE * 3, height=320)
    b.truth.expectations = {
        "abbreviations": ["p.a.", "para.", "Ltd.", "e.g.", "Co.", "Vol.", "No."],
        "must_not_split_on_abbreviation": True,
        "naive_regex_errors_expected": 5,
    }
    return b.save(out)


def fx_messy_headings(out: Path):
    """The hard case: inconsistent heading sizes, bold-only subheads, no numbering."""
    b = Builder("messy_headings",
                "Inconsistent heading sizes and bold-only subheadings -- the case where "
                "font-size clustering alone is expected to struggle (spec Q1).")
    total = 3
    b.new_page(header=True, footer=True, page_no=1, total=total)
    b.heading("Introduction to leases", 1, 1, size=22.0)
    b.prose(PROSE, height=70)
    b.heading("Recognition", 2, 1, size=13.0)          # only 2pt above body
    b.prose(PROSE, height=70)
    b.heading("Measurement", 2, 1, size=BODY_SIZE, bold=True)  # bold-only, body size
    b.prose(PROSE, height=70)
    b.new_page(header=True, footer=True, page_no=2, total=total)
    b.heading("Subsequent treatment", 1, 2, size=24.0)   # different H1 size than page 1
    b.prose(PROSE, height=70)
    b.heading("Disclosure", 2, 2, size=16.0)             # different H2 size again
    b.prose(PROSE, height=70)
    b.new_page(header=True, footer=True, page_no=3, total=total)
    b.heading("Practical expedients", 2, 3, size=BODY_SIZE, bold=True)
    b.prose(PROSE, height=90)
    b.truth.expectations = {
        "headings_total": 6,
        "distinct_h1_sizes": [22.0, 24.0],
        "distinct_h2_sizes": [13.0, 16.0, BODY_SIZE],
        "bold_only_subheads": 2,
        "note": "size clustering alone will likely mis-level these; bold promotion "
                "and calibration are required. This fixture is the Q1 stress test.",
    }
    return b.save(out)


def fx_composite(out: Path):
    """Composite that mirrors the measured the reference document profile at small scale."""
    b = Builder("composite",
                "Composite mirroring measured the reference document shape: 11pt body, 24/17/15pt "
                "heading tiers, header+footer on every page, tables on ~60% of pages.")
    total = 10
    for p in range(1, total + 1):
        b.new_page(header=True, footer=True, page_no=p, total=total)
        if p == 1:
            b.page.insert_text((LEFT, CONTENT_TOP), "Financial Accounting", fontsize=TITLE_SIZE)
            b.truth.headings.append({"page": 1, "text": "Financial Accounting",
                                     "level": 0, "size": TITLE_SIZE, "bold": False,
                                     "y": CONTENT_TOP})
            b.y = CONTENT_TOP + TITLE_SIZE * 1.9
        if p % 4 == 1:
            b.heading(f"{p // 4 + 1} Chapter {p // 4 + 1}", 1, p)
        b.heading(f"{p // 4 + 1}.{p} Section {p}", 2, p)
        b.prose(PROSE, height=90)
        if p % 3 == 0:
            b.heading(f"Detail {p}", 3, p)
        if p % 5 == 0:
            b.prose(ABBREV_PROSE, height=90)
        # tables on ~60% of pages, matching the measured 252/438
        if p % 5 in (1, 2, 3):
            b.ruled_table(p, [
                ["Item", "Cost", "Depn", "NBV"],
                ["Plant", "10,000", "2,000", "8,000"],
                ["Vehicles", "5,000", "1,250", "3,750"],
            ], label=f"tbl_p{p}")
        if p % 4 == 0:
            b.formula(p, ["Depreciation = (Cost - Residual value) / Useful life"],
                      kind="formula", label=f"f_p{p}")
    b.truth.expectations = {
        "body_size": BODY_SIZE,
        "heading_tiers": [H1_SIZE, H2_SIZE, H3_SIZE],
        "title_size": TITLE_SIZE,
        "noise_on_all_pages": True,
        "tables_expected": 6,
        "note": "end-to-end smoke fixture for the whole P1..P6 chain",
    }
    return b.save(out)


FIXTURES = [
    fx_clean_headings, fx_noisy, fx_tables, fx_formulas,
    fx_abbreviations, fx_messy_headings, fx_composite,
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).parent / "out"))
    ap.add_argument("--list", action="store_true", help="describe fixtures and exit")
    args = ap.parse_args()

    if args.list:
        for fn in FIXTURES:
            print(f"  {fn.__name__.removeprefix('fx_'):18} {(fn.__doc__ or '').strip()}")
        return

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"writing fixtures to {out}")
    for fn in FIXTURES:
        pdf, truth = fn(out)
        d = json.loads(truth.read_text(encoding="utf-8"))
        print(f"  {pdf.name:24} {d['pages']:>2}pg  "
              f"headings={len(d['headings']):>2}  "
              f"noise={len(d['noise_lines']):>2}  "
              f"atomic={len(d['atomic_regions']):>2}")
    print("done")


if __name__ == "__main__":
    main()
