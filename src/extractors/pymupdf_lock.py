"""
The one lock every PyMuPDF call takes.

MuPDF is not thread-safe, even across separate documents. MCP handlers run
extraction in worker threads, so PDF extraction, structural parsing and the lazy
loaders that render PDF images on request all serialize on this lock. It lives
here, below both the extractors and the server, so neither imports the other.
"""

from __future__ import annotations

import threading

PYMUPDF_LOCK = threading.RLock()
