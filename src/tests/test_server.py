"""MCP server behaviour: real errors, input validation, caching, concurrency, startup."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp.types import CallToolResult, TextContent

import chomper
import server
from src.extractors.text_extractor import TextExtractor
from src.server import cache as cache_mod
from src.server import helpers
from src.server.config import CHUNK_STRATEGIES, LazyRegistry

MARKDOWN = """# Title

Intro text for the document.

## Section A

- item one
- item two

| a | b |
|---|---|
| 1 | 2 |

## Section B

Closing words about section b and its contents.
"""


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache_mod.clear_caches()
    yield
    cache_mod.clear_caches()


@pytest.fixture
def count_text_extracts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every real TextExtractor.extract call."""
    calls: list[str] = []
    original = TextExtractor.extract

    def counting(self: TextExtractor, file_path: str) -> Any:
        calls.append(file_path)
        return original(self, file_path)

    monkeypatch.setattr(TextExtractor, "extract", counting)
    return calls


@pytest.fixture
def slow_text_extract(monkeypatch: pytest.MonkeyPatch) -> float:
    """Make text extraction take a fixed, measurable time (blocking, like real parsing)."""
    delay = 0.4
    original = TextExtractor.extract

    def slow(self: TextExtractor, file_path: str) -> Any:
        time.sleep(delay)
        return original(self, file_path)

    monkeypatch.setattr(TextExtractor, "extract", slow)
    return delay


def call(name: str, args: dict[str, Any]) -> Any:
    return asyncio.run(server.dispatch_tool(name, args))


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


# ----------------------------------------------------------------- real errors


@pytest.mark.parametrize(
    ("tool", "args", "expect"),
    [
        ("parse_document", {"file_path": "/no/such/file.pdf"}, "File not found"),
        ("parse_document", {}, "file_path is required"),
        ("get_document_chunk", {"offset": -1}, "offset must be >= 0"),
        ("get_document_chunk", {"limit": 0}, "limit must be >= 1"),
        ("get_document_chunk", {"offset": 10_000}, "past the end"),
        ("get_document_images", {"max_images": 0}, "max_images must be >= 1"),
        ("get_document_images", {"page": "two"}, "page must be an integer"),
        ("parse_document", {"file_path": "/x.txt", "full_text": "yes"}, "full_text must be a boolean"),
        ("parse_document_chunked", {"chunking_strategy": "bogus"}, "recursive"),
        ("parse_document_chunked", {"chunk_size": 0}, "chunk_size must be >= 1"),
        ("parse_document_chunked", {"overlap": -5}, "overlap must be >= 0"),
        ("parse_document_bytes", {"content_base64": "!!!", "filename": "a.txt"}, "Invalid base64"),
        ("parse_document_bytes", {"content_base64": "aGk=", "filename": "a.xyz"}, "Unsupported"),
        ("batch_parse", {"file_paths": []}, "file_paths must have at least 1 item"),
        ("no_such_tool", {}, "Unknown tool"),
    ],
)
def test_failures_are_reported_with_is_error(
    tmp_path: Path, tool: str, args: dict[str, Any], expect: str
) -> None:
    doc = write(tmp_path, "doc.txt", "hello world")
    if tool in {"get_document_chunk", "get_document_images", "parse_document_chunked"}:
        args = {"file_path": str(doc), **args}
    result = call(tool, args)
    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert expect in result.content[0].text
    assert result.content[0].text.startswith(f"{tool} failed")


def test_successful_call_is_plain_content(tmp_path: Path) -> None:
    result = call("parse_document", {"file_path": str(write(tmp_path, "a.txt", "hello"))})
    assert not isinstance(result, CallToolResult)
    assert result[0].text == "hello"


def test_parse_document_bytes_enforces_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helpers, "MAX_BYTES_INPUT", 1024)
    payload = base64.b64encode(b"x" * 2048).decode()
    result = call("parse_document_bytes", {"content_base64": payload, "filename": "big.txt"})
    assert isinstance(result, CallToolResult) and result.isError
    assert "limit" in result.content[0].text


def test_parse_document_bytes_is_never_cached() -> None:
    payload = base64.b64encode(b"bytes content here").decode()
    result = call("parse_document_bytes", {"content_base64": payload, "filename": "x.txt"})
    assert result[0].text == "bytes content here"
    assert len(cache_mod.DOCUMENT_CACHE) == 0


# ----------------------------------------------------------------------- cache


def test_paging_extracts_the_document_once(tmp_path: Path, count_text_extracts: list[str]) -> None:
    doc = write(tmp_path, "long.txt", "word " * 5000)
    offset, pages = 0, 0
    while True:
        result = call("get_document_chunk", {"file_path": str(doc), "offset": offset, "limit": 1000})
        meta = json.loads(result[1].text)
        pages += 1
        if not meta["has_more"]:
            break
        offset += 1000
    assert pages == 25
    assert len(count_text_extracts) == 1


def test_metadata_after_parse_reuses_extraction(
    tmp_path: Path, count_text_extracts: list[str]
) -> None:
    doc = write(tmp_path, "a.txt", "some text")
    call("parse_document", {"file_path": str(doc)})
    call("extract_metadata", {"file_path": str(doc)})
    chomper.parse(doc)
    chomper.extract_metadata(doc)
    assert len(count_text_extracts) == 1


def test_modified_file_is_re_extracted(tmp_path: Path, count_text_extracts: list[str]) -> None:
    doc = write(tmp_path, "a.txt", "first version")
    assert chomper.parse(doc).text == "first version"
    doc.write_text("second, longer version")
    assert chomper.parse(doc).text == "second, longer version"
    assert len(count_text_extracts) == 2
    assert len(cache_mod.DOCUMENT_CACHE) == 1  # the stale entry was dropped


def test_cache_can_be_disabled(tmp_path: Path, count_text_extracts: list[str]) -> None:
    cache_mod.DOCUMENT_CACHE.resize(0)
    try:
        doc = write(tmp_path, "a.txt", "text")
        chomper.parse(doc)
        chomper.parse(doc)
        assert len(count_text_extracts) == 2
    finally:
        cache_mod.DOCUMENT_CACHE.resize(cache_mod.cache_size_from_env())


def test_cache_size_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHOMPER_CACHE_SIZE", "3")
    assert cache_mod.cache_size_from_env() == 3
    monkeypatch.setenv("CHOMPER_DISABLE_CACHE", "1")
    assert cache_mod.cache_size_from_env() == 0


def test_lru_is_bounded_and_single_flight() -> None:
    lru: cache_mod.LRUCache[str, int] = cache_mod.LRUCache(maxsize=2)
    for key in "abc":
        lru.get_or_load(key, lambda k=key: ord(k))
    assert len(lru) == 2 and lru.peek("a") is None

    loads: list[int] = []

    def slow() -> int:
        time.sleep(0.2)
        loads.append(1)
        return 42

    async def both() -> list[int]:
        return list(await asyncio.gather(
            asyncio.to_thread(lru.get_or_load, "k", slow),
            asyncio.to_thread(lru.get_or_load, "k", slow),
        ))

    assert asyncio.run(both()) == [42, 42]
    assert loads == [1]


# ----------------------------------------------------------------- concurrency


def test_concurrent_calls_do_not_serialize(tmp_path: Path, slow_text_extract: float) -> None:
    docs = [write(tmp_path, f"{i}.txt", f"document {i}") for i in range(2)]

    async def run() -> float:
        start = time.perf_counter()
        await asyncio.gather(*(
            server.dispatch_tool("parse_document", {"file_path": str(d)}) for d in docs
        ))
        return time.perf_counter() - start

    elapsed = asyncio.run(run())
    # Serialized would take 2 x delay; concurrent takes about 1 x delay.
    assert elapsed < slow_text_extract * 1.6, elapsed


def test_event_loop_stays_responsive_during_extraction(
    tmp_path: Path, slow_text_extract: float
) -> None:
    doc = write(tmp_path, "a.txt", "text")
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    async def run() -> None:
        task = asyncio.create_task(ticker())
        await server.dispatch_tool("parse_document", {"file_path": str(doc)})
        task.cancel()

    asyncio.run(run())
    assert ticks >= (slow_text_extract / 0.02) * 0.5, ticks


def test_batch_parse_runs_concurrently(
    tmp_path: Path, slow_text_extract: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.handlers import batch

    monkeypatch.setattr(batch, "BATCH_CONCURRENCY", 4)
    docs = [str(write(tmp_path, f"{i}.txt", f"doc {i}")) for i in range(4)]
    docs.append("/missing/file.txt")
    start = time.perf_counter()
    result = call("batch_parse", {"file_paths": docs})
    elapsed = time.perf_counter() - start
    payload = json.loads(result[0].text)
    assert payload["successful"] == 4 and payload["failed"] == 1
    assert all(r["file_path"].endswith(f"{i}.txt") for i, r in enumerate(payload["results"][:4]))
    assert elapsed < slow_text_extract * 2.5, elapsed  # 4 serialized files would take 4x


# ------------------------------------------------------------ chunked output


def test_chunked_output_has_section_names_and_optional_keywords(tmp_path: Path) -> None:
    doc = write(tmp_path, "g.md", MARKDOWN)
    plain = json.loads(call("parse_document_chunked", {
        "file_path": str(doc), "chunk_size": 12, "overlap": 0,
    })[0].text)
    assert {c["section_name"] for c in plain["chunks"]} >= {"Section A", "Section B"}
    assert all(c["keywords"] == [] for c in plain["chunks"])

    keyed = json.loads(call("parse_document_chunked", {
        "file_path": str(doc), "chunk_size": 12, "overlap": 0, "include_keywords": True,
    })[0].text)
    assert any(c["keywords"] for c in keyed["chunks"])


@pytest.mark.parametrize("strategy", [s for s in CHUNK_STRATEGIES if s != "semantic"])
def test_mcp_and_library_chunk_identically(tmp_path: Path, strategy: str) -> None:
    doc = write(tmp_path, "g.md", MARKDOWN * 5)
    mcp_chunks = json.loads(call("parse_document_chunked", {
        "file_path": str(doc), "chunking_strategy": strategy, "chunk_size": 20, "overlap": 5,
    })[0].text)["chunks"]
    lib_chunks = chomper.chunk(doc, strategy=strategy, chunk_size=20, overlap=5)  # type: ignore[arg-type]
    assert [c["text"] for c in mcp_chunks] == [c.text for c in lib_chunks]


# ------------------------------------------------------------ startup / entry


def test_console_script_entry_point_is_synchronous() -> None:
    assert callable(server.run) and not inspect.iscoroutinefunction(server.run)
    assert 'chomper = "server:run"' in (ROOT / "pyproject.toml").read_text()


def test_server_import_does_not_load_extractors() -> None:
    code = (
        "import sys, server; "
        "heavy = [m for m in ('src.extractors.pdf_extractor', 'src.extractors.excel_extractor', "
        "'pandas', 'trafilatura', 'extract_msg', 'fitz', 'numpy') if m in sys.modules]; "
        "print(heavy)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip().splitlines()[-1]
    assert out == "[]"


def test_registry_reports_missing_dependency_with_install_hint() -> None:
    registry = LazyRegistry({
        ".ok": ("src.extractors.text_extractor", "TextExtractor", (), ""),
        ".gone": ("no_such_module_xyz", "Nope", (), "'chomper[gone]'"),
        ".flag": ("src.extractors.data_extractor", "YAMLExtractor", ("NO_SUCH_FLAG_FALSE",), "x"),
    })
    assert ".ok" in registry and ".gone" not in registry
    assert list(registry) == [".ok", ".flag"]  # a missing flag attribute counts as present
    reason = registry.unavailable_reason(".gone")
    assert reason and "pip install 'chomper[gone]'" in reason


def test_list_supported_formats_counts_only_available(tmp_path: Path) -> None:
    payload = json.loads(call("list_supported_formats", {})[0].text)
    available = [f for f in payload["formats"] if f["available"]]
    assert payload["available_formats"] == len(available)
    assert all(f["reason"] is None for f in available)
    assert isinstance(call("list_supported_formats", {})[0], TextContent)


def test_errors_reach_a_real_mcp_client_as_is_error(tmp_path: Path) -> None:
    """End to end over stdio: the SDK client sees isError=True, and success is not."""
    import os

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    doc = write(tmp_path, "ok.txt", "hello over stdio")
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "server.py")], cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    async def session() -> tuple[Any, Any, Any]:
        with open(os.devnull, "w") as devnull:
            async with stdio_client(params, errlog=devnull) as (read, write_stream):
                async with ClientSession(read, write_stream) as client:
                    await client.initialize()
                    missing = await client.call_tool("parse_document", {"file_path": "/nope.pdf"})
                    bad = await client.call_tool(
                        "get_document_chunk", {"file_path": str(doc), "offset": -3}
                    )
                    good = await client.call_tool("parse_document", {"file_path": str(doc)})
                    return missing, bad, good

    missing, bad, good = asyncio.run(session())
    assert missing.isError and "File not found" in missing.content[0].text
    assert bad.isError and "offset must be >= 0" in bad.content[0].text
    assert not good.isError and good.content[0].text == "hello over stdio"
