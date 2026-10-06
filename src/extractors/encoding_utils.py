"""
Decode text files without silently dropping bytes.

``open(..., errors="ignore")`` turns ``café`` saved by Windows Notepad into
``caf`` and nobody notices. Every text-like extractor reads through here instead:

    text, encoding = read_text(path)       # from a file
    text, encoding = decode_bytes(data)    # from bytes already in memory

Detection order:

1. A byte-order mark: UTF-8 (``utf-8-sig``), UTF-16 or UTF-32.
2. Strict UTF-8 (``utf-8``), which covers ASCII and almost all modern files.
3. Windows-1252 (``cp1252``) when the result looks like Western text: only
   Latin-1 letters and Windows punctuation, and never three or more non-ASCII
   letters in a row. charset-normalizer guesses badly on short Western files
   (``café`` comes back as Urdu ``cp1006``, ``crème`` as Central-European
   ``crčme``), and cp1252 is by far the most common legacy encoding. Cyrillic,
   Greek or CJK bytes decoded as cp1252 produce long runs of accented letters,
   so they fail this check and fall through.
4. charset-normalizer's best guess, when it is installed.
5. ``latin-1``, which maps every byte to a character and never fails.

The returned encoding name is what the extractors record as
``metadata["encoding"]``.
"""

from __future__ import annotations

import codecs
import logging
from pathlib import Path

try:
    import charset_normalizer

    CHARSET_NORMALIZER_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    charset_normalizer = None  # type: ignore[assignment]
    CHARSET_NORMALIZER_AVAILABLE = False

logger = logging.getLogger(__name__)

_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

# Characters cp1252 decodes to that are normal in Western European text.
_CP1252_PUNCT = set("€‚ƒ„…†‡ˆ‰‹›‘’“”•–—˜™¡¢£¤¥¦§¨©ª«¬\xad®¯°±²³´µ¶·¸¹º»¼½¾¿×÷\xa0")


def _looks_like_cp1252(text: str) -> bool:
    """True if ``text`` reads like Western European text, not mojibake."""
    run = 0
    for char in text:
        if char.isascii():
            run = 0
            continue
        if char.isalpha():
            if not ("À" <= char <= "ÿ" or char in "ŠšŒœŽžŸƒ"):
                return False
            run += 1
            if run >= 3:
                return False
        else:
            run = 0
            if char not in _CP1252_PUNCT:
                return False
    return True


def decode_bytes(data: bytes) -> tuple[str, str]:
    """
    Decode ``data`` to text, returning ``(text, encoding)``.

    Never raises and never drops bytes: the last resort, ``latin-1``, maps
    every byte to a character.
    """
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                break

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError:
        text = None
    if text is not None and _looks_like_cp1252(text):
        return text, "cp1252"

    if CHARSET_NORMALIZER_AVAILABLE:
        try:
            best = charset_normalizer.from_bytes(data).best()
        except Exception as e:  # charset-normalizer bugs must not fail a parse
            logger.debug(f"charset-normalizer failed: {e}")
            best = None
        if best is not None:
            return str(best), best.encoding

    return data.decode("latin-1"), "latin-1"


def read_text(path: str | Path) -> tuple[str, str]:
    """Read a file as text, returning ``(text, encoding)``; see ``decode_bytes``."""
    return decode_bytes(Path(path).read_bytes())


__all__ = ["decode_bytes", "read_text"]
