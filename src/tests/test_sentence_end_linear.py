"""``ends_mid_sentence`` must run in linear time on long digit runs.

The trailing-enumeration regex ``(?:[\\s\\u00a0]*(?:\\d{1,2}|<glyph>))+$`` backtracks
exponentially on a run of digits that is not at the very end (chart axis labels
such as ``2019 2020 2021 ... Percent``): each extra digit multiplies the number of
ways ``\\d{1,2}`` can tile the run. On a Federal Reserve report it hung for over an
hour. Both the structural assembler and the layout chunker call the check, so they
share one linear implementation.
"""

from __future__ import annotations

import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.pdf_structure import sentences

ROOT = Path(__file__).resolve().parents[2]

#: The pattern the old implementation used; safe as a reference on short inputs.
_OLD_TRAILING = re.compile(
    r"(?:[\s ]*(?:\d{1,2}|[✓✔✗✘○●•]))+$"
)


def _timed_in_child(expression: str, setup: str, limit: float = 30.0) -> float:
    """Seconds ``expression`` takes in a fresh interpreter (killed after ``limit``)."""
    script = (
        "import time\n"
        f"{setup}\n"
        "start = time.perf_counter()\n"
        f"{expression}\n"
        "print(time.perf_counter() - start)\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=limit,
            check=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"did not finish within {limit:.0f}s (exponential backtracking)")
    return float(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "module",
    ["src.pdf_structure.sentences", "src.chunking.strategies.layout_pdf_chunker"],
)
def test_five_thousand_token_digit_run_finishes_under_a_second(module: str) -> None:
    setup = (
        f"from {module} import ends_mid_sentence\n"
        "text = 'Real GDP growth ' + ' '.join(str(2000 + i % 30) for i in range(5000))"
        " + ' percent change from a year earlier'"
    )
    elapsed = _timed_in_child("assert ends_mid_sentence(text) is True", setup)
    assert elapsed < 1.0


def test_unbroken_digit_run_before_text_is_linear() -> None:
    setup = (
        "from src.pdf_structure.sentences import ends_mid_sentence\n"
        "text = 'Axis labels ' + '2019202020212022' * 400 + 'x and more words here'"
    )
    assert _timed_in_child("ends_mid_sentence(text)", setup) < 1.0


def test_layout_chunker_uses_the_shared_implementation() -> None:
    from src.chunking.strategies import layout_pdf_chunker

    assert layout_pdf_chunker.ends_mid_sentence is sentences.ends_mid_sentence


NORMAL_INPUTS = [
    "This sentence is cut off in the",
    "A complete sentence.",
    "See IAS 16 para.",
    "Results are shown in Table 3",
    "Results are shown in Table 3 4 5",
    "Ticks after a phrase that is long enough ✓ ✗",
    "Bullets after a phrase long enough • ● 12",
    "Ends with a year like 2024",
    "Ends with a list number after a colon: 1",
    "Ends with a list number after a semicolon; 12 3",
    "Text that ends with non-breaking 12",
    "Numbers 1 2 3",
    "12 34 56",
    "| a | b |",
    "# Heading",
    "- a list item without a full stop",
    "Introduces a list:",
    "Short label",
    "",
    "   ",
    "Line one.\nLine two runs on and on without",
    "As described in Fig.",
    "Amounts in thousands 123 456 789",
    "The value rose to 3.5 percent in 2024 1",
]


@pytest.mark.parametrize("text", NORMAL_INPUTS)
def test_strip_matches_old_regex(text: str) -> None:
    for line in [text, text.strip(), *text.splitlines()]:
        stripped = line.strip()
        assert sentences.strip_trailing_enumeration(stripped) == _OLD_TRAILING.sub("", stripped).rstrip()


def _old_ends_mid_sentence(text: str) -> bool:
    """The previous implementation, verbatim apart from the regex reference."""
    from src.pdf_structure.sentences import ABBREVIATIONS

    stripped = text.rstrip()
    if not stripped:
        return False
    last = stripped.splitlines()[-1].strip()
    if not last:
        return False
    if last.startswith(("|", "```", "#", ">")):
        return False
    if re.match(r"^\s*([-*+•]|\d+[.)])\s", last):
        return False
    if last.endswith((":", ";")):
        return False
    last = _OLD_TRAILING.sub("", last).rstrip()
    if not last:
        return False
    if last.endswith((":", ";")):
        return False
    if re.match(r"^[\d\s.,)(]+$", last):
        return False
    if len(last.split()) <= 3:
        return False
    if sum(1 for c in last if c.isalpha()) < 2:
        return False
    if last.endswith((".", "!", "?", '"', "'", ")", "]", "…")):
        return any(last.endswith(abbr) for abbr in ABBREVIATIONS)
    return True


@pytest.mark.parametrize("text", NORMAL_INPUTS)
def test_ends_mid_sentence_matches_old_behaviour(text: str) -> None:
    assert sentences.ends_mid_sentence(text) == _old_ends_mid_sentence(text)


def test_random_inputs_match_old_behaviour() -> None:
    rng = random.Random(1234)
    alphabet = ["a", "word", " ", " ", "1", "23", ".", ":", ";", "✓", "•", "Fig.", "\n", ")"]
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 14)))
        assert sentences.ends_mid_sentence(text) == _old_ends_mid_sentence(text), repr(text)
