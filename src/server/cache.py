"""In-process LRU caches for extracted documents and structural PDF parses.

Paging through a document with ``get_document_chunk``, or calling
``extract_metadata`` after ``parse_document``, used to re-run the full extractor on
every call. One bounded cache, shared by the MCP handlers and the Python library,
keeps the most recently used results.

Keys include the resolved path, ``st_mtime_ns`` and ``st_size``, so an edited file
is re-extracted, plus the extractor class and options so different settings never
share an entry. Temporary files written by the ``*_bytes`` APIs are never cached.

Environment:
    ``CHOMPER_CACHE_SIZE``: entries per cache (default 16). ``0`` disables caching.
    ``CHOMPER_DISABLE_CACHE``: any of ``1``/``true``/``yes`` disables caching.

Cached values are shared between callers and must be treated as read-only.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import Any, Generic, TypeVar

# PyMuPDF (MuPDF) is not thread-safe, even across separate documents. Handlers run
# extraction in worker threads, so every PyMuPDF use -- PDF extraction, structural
# parsing and lazy PDF image loading -- is serialized on this one lock.
from ..extractors.pymupdf_lock import PYMUPDF_LOCK

logger = logging.getLogger("chomper")

DEFAULT_CACHE_SIZE = 16

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


def cache_size_from_env() -> int:
    """Configured entries per cache; 0 when caching is disabled."""
    if os.environ.get("CHOMPER_DISABLE_CACHE", "").strip().lower() in {"1", "true", "yes"}:
        return 0
    raw = os.environ.get("CHOMPER_CACHE_SIZE", "").strip()
    if not raw:
        return DEFAULT_CACHE_SIZE
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Ignoring invalid CHOMPER_CACHE_SIZE=%r", raw)
        return DEFAULT_CACHE_SIZE


class LRUCache(Generic[K, V]):
    """Thread-safe bounded LRU cache with single-flight loading.

    Concurrent requests for the same missing key run the loader once; the
    others wait for and share its result. Loader exceptions are not cached.
    """

    def __init__(self, maxsize: int | None = None) -> None:
        self.maxsize = cache_size_from_env() if maxsize is None else maxsize
        self._data: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: dict[K, threading.Lock] = {}
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._data)

    def peek(self, key: K) -> V | None:
        """Return a cached value without loading or touching recency."""
        with self._lock:
            return self._data.get(key)

    def get_or_load(self, key: K, loader: Callable[[], V]) -> V:
        """Cached value for ``key``, computing it with ``loader`` on a miss."""
        if self.maxsize <= 0:
            return loader()
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            key_lock = self._inflight.setdefault(key, threading.Lock())
        try:
            with key_lock:
                with self._lock:
                    if key in self._data:
                        self._data.move_to_end(key)
                        self.hits += 1
                        return self._data[key]
                    self.misses += 1
                value = loader()
                with self._lock:
                    self._evict_superseded(key)
                    self._data[key] = value
                    while len(self._data) > self.maxsize:
                        self._data.popitem(last=False)
                return value
        finally:
            with self._lock:
                if self._inflight.get(key) is key_lock:
                    del self._inflight[key]

    def _evict_superseded(self, key: K) -> None:
        """Drop entries for an older version of the same file (same path, other stat)."""
        if not (isinstance(key, tuple) and key and isinstance(key[0], str)):
            return
        stale = [
            k for k in self._data
            if isinstance(k, tuple) and k and k[0] == key[0] and k[1:3] != key[1:3]
        ]
        for k in stale:
            del self._data[k]

    def clear(self) -> None:
        """Remove every entry and reset statistics."""
        with self._lock:
            self._data.clear()
            self.hits = self.misses = 0

    def resize(self, maxsize: int) -> None:
        """Change the bound (0 disables), evicting least recently used entries."""
        with self._lock:
            self.maxsize = maxsize
            while len(self._data) > max(0, maxsize):
                self._data.popitem(last=False)


#: Extracted RawDocuments.
DOCUMENT_CACHE: LRUCache[tuple[Any, ...], Any] = LRUCache()
#: ``pdf_structure.parse_structure`` results for the structural PDF chunker.
STRUCTURE_CACHE: LRUCache[tuple[Any, ...], Any] = LRUCache()



_PYMUPDF_SUFFIXES = {".pdf"}


@contextlib.contextmanager
def serialized_for(path: str | Path) -> Iterator[None]:
    """Hold :data:`PYMUPDF_LOCK` while working on a file PyMuPDF will read."""
    if Path(path).suffix.lower() in _PYMUPDF_SUFFIXES:
        with PYMUPDF_LOCK:
            yield
    else:
        yield


def file_key(path: str | Path) -> tuple[str, int, int]:
    """``(resolved path, st_mtime_ns, st_size)`` identifying one version of a file."""
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    return str(resolved), stat.st_mtime_ns, stat.st_size


def cached_extract(
    path: str | Path,
    extractor_cls: type,
    options: tuple[tuple[str, Any], ...] = (),
    *,
    use_cache: bool = True,
) -> Any:
    """Extract ``path`` with ``extractor_cls(**options)``, through the document cache."""

    def load() -> Any:
        with serialized_for(path):
            return extractor_cls(**dict(options)).extract(str(path))

    if not use_cache:
        return load()
    key = (*file_key(path), f"{extractor_cls.__module__}.{extractor_cls.__qualname__}", options)
    return DOCUMENT_CACHE.get_or_load(key, load)


def peek_document(
    path: str | Path, extractor_cls: type, options: tuple[tuple[str, Any], ...] = ()
) -> Any | None:
    """A cached RawDocument for ``path`` and ``options`` if one exists, without extracting."""
    try:
        key = (*file_key(path), f"{extractor_cls.__module__}.{extractor_cls.__qualname__}", options)
    except OSError:
        return None
    return DOCUMENT_CACHE.peek(key)


def cached_parse_structure(path: str | Path, **options: Any) -> Any:
    """``pdf_structure.parse_structure(path, **options)`` through the structure cache."""
    from ..pdf_structure import parse_structure

    def load() -> Any:
        with PYMUPDF_LOCK:
            return parse_structure(path, **options)

    try:
        key = (*file_key(path), tuple(sorted(options.items())))
    except OSError:
        return load()
    return STRUCTURE_CACHE.get_or_load(key, load)


def clear_caches() -> None:
    """Empty every cache (tests, or after bulk file changes)."""
    DOCUMENT_CACHE.clear()
    STRUCTURE_CACHE.clear()


__all__ = [
    "DEFAULT_CACHE_SIZE",
    "DOCUMENT_CACHE",
    "STRUCTURE_CACHE",
    "LRUCache",
    "PYMUPDF_LOCK",
    "serialized_for",
    "cache_size_from_env",
    "cached_extract",
    "cached_parse_structure",
    "clear_caches",
    "file_key",
    "peek_document",
]
