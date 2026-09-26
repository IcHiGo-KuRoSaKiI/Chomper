"""Regression tests for code chunk overlap handling."""

from __future__ import annotations

import signal
from contextlib import contextmanager

import pytest

from src.chunking.strategies.code_chunker import CodeChunker
from src.models.document import RawDocument


@contextmanager
def _fail_if_slow(seconds: float = 0.25):
    """Interrupt a non-terminating chunk loop without relying on pytest plugins."""
    if not hasattr(signal, "setitimer"):
        yield
        return

    def raise_timeout(_signum, _frame):
        raise TimeoutError("CodeChunker did not make forward progress")

    previous = signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize(
    "structure",
    [
        None,
        {"functions": [{"name": "pathological", "line_start": 1, "line_end": 1}]},
        {"classes": [{"name": "Pathological", "line_start": 1, "line_end": 1}]},
    ],
    ids=["simple", "function", "class"],
)
def test_overlap_equal_to_target_size_always_terminates(structure):
    """An overlap covering the whole chunk must still advance toward EOF."""
    text = "x" * 64
    raw_doc = RawDocument(
        text=text,
        metadata={"language": "python"},
        structure=structure,
    )
    chunker = CodeChunker(target_size=16, overlap=16)

    with _fail_if_slow():
        chunks = chunker.chunk(raw_doc)

    assert chunks
    assert len(chunks) <= len(text)
    assert chunks[-1].text.endswith("x")
