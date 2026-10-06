"""
CSV/TSV extractor.

Rows are read with the standard ``csv`` module and rendered straight to one GFM
pipe table, so values come out exactly as written: ``3`` stays ``3`` even when
the column has gaps (no float coercion), dates keep their original spelling and
quoted newlines become ``<br>``.

- **Encoding:** UTF-8 (BOM-aware), then a chardet guess when installed, then
  cp1252 and latin-1. The one used is in ``metadata["encoding"]``.
- **Delimiter:** an Excel ``sep=;`` first line wins; otherwise each candidate
  (``, ; TAB |``) is parsed over the first 50 lines and the one giving the most
  lines with the same field count (more than one field) is chosen. That beats
  ``csv.Sniffer``, which is easily thrown by a title line or decimal commas.
- **Preamble:** leading lines with far fewer fields than the table (a title,
  "generated on ..." notes) are not taken as the header. They go in
  ``metadata["preamble"]`` rather than the text, because ``ExcelChunker`` treats
  the first text line as the header row when it splits large files.
- **Malformed rows are kept, not skipped:** short rows are padded with empty
  cells; extra fields are joined (with the delimiter) into the last column, so
  no value is lost. Their 1-based line numbers are listed in
  ``metadata["bad_lines"]`` (first 1000) with ``metadata["bad_line_count"]``.
  Trailing empty fields beyond the header are dropped silently.
- **Header:** the first row, unless every value in it is a number.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import chardet

    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False

from ..models.document import RawDocument
from ..models.excel_models import CSVMetadata
from .base import BaseExtractor
from .markdown_utils import render_table

logger = logging.getLogger(__name__)

_DELIMITERS = [",", ";", "\t", "|"]
_SEP_HINT_RE = re.compile(r"^﻿?sep=(.)$", re.I)
_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
_MAX_REPORTED_BAD_LINES = 1000
_TYPE_SAMPLE_ROWS = 1000

# csv refuses fields over 128 KB by default; real exports exceed that.
csv.field_size_limit(2**31 - 1)


class CSVExtractor(BaseExtractor):
    """
    Extract content from CSV/TSV files as a Markdown table.

    See the module docstring for how delimiters, preambles and malformed rows
    are handled.
    """

    SUPPORTED_EXTENSIONS = [".csv", ".tsv", ".txt"]

    def __init__(
        self,
        delimiter: str | None = None,
        encoding: str | None = None,
        has_header: bool | None = None,
        sample_size: int = 5000,
        sample_lines: int = 50,
    ):
        """
        Initialize CSV extractor.

        Args:
            delimiter: CSV delimiter (auto-detect if None)
            encoding: File encoding (auto-detect if None)
            has_header: Whether first row is header (auto-detect if None)
            sample_size: Bytes given to chardet when UTF-8 decoding fails
            sample_lines: Lines inspected to detect the delimiter and preamble
        """
        if not PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is required for CSV extraction. Install with: pip install pandas"
            )

        self.delimiter = delimiter
        self.encoding = encoding
        self.has_header = has_header
        self.sample_size = sample_size
        self.sample_lines = sample_lines

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from a CSV file.

        Args:
            file_path: Path to CSV file

        Returns:
            RawDocument with a Markdown table and CSV metadata
        """
        self.validate_file(file_path)

        content, encoding = self._decode(Path(file_path).read_bytes())
        lines = content.splitlines(keepends=True)

        start = 0
        delimiter = self.delimiter
        hint = _SEP_HINT_RE.match(lines[0].strip()) if lines else None
        if hint:
            delimiter = delimiter or hint.group(1)
            start = 1
        sample = lines[start : start + self.sample_lines]
        if not delimiter:
            delimiter = self._detect_delimiter(sample)

        header_at = start + self._preamble_length(sample, delimiter)
        preamble = [line.strip() for line in lines[start:header_at] if line.strip()]

        rows, bad_lines = self._read_rows("".join(lines[header_at:]), delimiter, header_at)

        has_header = self.has_header
        if has_header is None:
            has_header = bool(rows) and not all(
                _FLOAT_RE.fullmatch(value.strip()) for value in rows[0] if value.strip()
            )
        width = len(rows[0]) if rows else 0
        if has_header and rows:
            column_names = [value.strip() for value in rows[0]]
            data_rows = rows[1:]
        else:
            column_names = [f"Column {i}" for i in range(1, width + 1)]
            data_rows = rows

        column_types = self._infer_column_types(column_names, data_rows)
        text = render_table(rows, header_rows=1 if has_header else 0)

        csv_metadata = CSVMetadata(
            filename=Path(file_path).name,
            delimiter=delimiter,
            encoding=encoding,
            has_header=has_header,
            num_rows=len(data_rows),
            num_columns=width,
            column_names=column_names,
            column_types=column_types,
        )

        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_csv_metadata(csv_metadata))
        metadata["preamble"] = preamble
        metadata["bad_lines"] = bad_lines[:_MAX_REPORTED_BAD_LINES]
        metadata["bad_line_count"] = len(bad_lines)
        if bad_lines:
            logger.info(
                f"{Path(file_path).name}: {len(bad_lines)} row(s) with the wrong number "
                f"of fields were padded or merged (first at line {bad_lines[0]})"
            )

        structure = {
            "csv_metadata": csv_metadata,
            "dataframe_shape": (len(data_rows), width),
            "column_info": {
                name: {
                    "type": column_types.get(name, "text"),
                    "null_count": sum(1 for row in data_rows if not row[idx].strip()),
                    "unique_count": len({row[idx] for row in data_rows if row[idx].strip()}),
                }
                for idx, name in enumerate(column_names)
            },
        }

        return RawDocument(text=text, metadata=metadata, structure=structure)

    # -------------------------------------------------------------- decoding

    def _decode(self, data: bytes) -> tuple[str, str]:
        """Decode bytes, returning the text and the encoding that worked."""
        candidates: list[str] = []
        if self.encoding:
            candidates.append(self.encoding)
        candidates.append("utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8")
        if CHARDET_AVAILABLE:
            guess = chardet.detect(data[: self.sample_size])
            guessed = guess.get("encoding")
            if guessed and (guess.get("confidence") or 0) >= 0.5:
                candidates.append(guessed)
        candidates.extend(["cp1252", "latin-1"])
        for encoding in candidates:
            try:
                return data.decode(encoding), encoding.lower()
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("latin-1"), "latin-1"  # pragma: no cover - latin-1 never fails

    # -------------------------------------------------------- layout sniffing

    @staticmethod
    def _field_counts(lines: list[str], delimiter: str) -> list[int]:
        counts = []
        for line in lines:
            try:
                counts.append(len(next(csv.reader([line], delimiter=delimiter), [])))
            except csv.Error:
                counts.append(1)
        return counts

    def _detect_delimiter(self, sample: list[str]) -> str:
        """The delimiter giving the most lines with one consistent field count."""
        best: tuple[int, int] = (0, 0)
        chosen = ","
        for delimiter in _DELIMITERS:
            counts = [c for c in self._field_counts(sample, delimiter) if c > 1]
            if not counts:
                continue
            mode, freq = max(Counter(counts).items(), key=lambda item: (item[1], item[0]))
            if (freq, mode) > best:
                best = (freq, mode)
                chosen = delimiter
        if best == (0, 0):
            logger.debug("No delimiter detected, defaulting to comma")
        return chosen

    def _preamble_length(self, sample: list[str], delimiter: str) -> int:
        """Leading lines (titles, notes, blanks) with far fewer fields than the table."""
        counts = self._field_counts(sample, delimiter)
        multi = [c for c in counts if c > 1]
        if not multi:
            return 0
        mode = Counter(multi).most_common(1)[0][0]
        limit = max(1, mode // 2)
        skipped = 0
        for line, count in zip(sample, counts, strict=True):
            if line.strip() and count > limit:
                break
            skipped += 1
        return skipped if skipped < len(sample) else 0

    # --------------------------------------------------------------- reading

    @staticmethod
    def _read_rows(body: str, delimiter: str, line_offset: int) -> tuple[list[list[str]], list[int]]:
        """Parse rows, repairing ones with the wrong field count and noting where."""
        reader = csv.reader(io.StringIO(body), delimiter=delimiter)
        rows: list[list[str]] = []
        bad_lines: list[int] = []
        width = 0
        previous_line = 0
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as e:
                logger.warning(f"CSV parse error near line {line_offset + reader.line_num}: {e}")
                break
            first_line = line_offset + previous_line + 1
            previous_line = reader.line_num
            if not any(value.strip() for value in row):
                continue
            if not rows:
                while len(row) > 1 and not row[-1].strip():
                    row = row[:-1]
                width = len(row)
                rows.append(row)
                continue
            if len(row) > width and not any(value.strip() for value in row[width:]):
                row = row[:width]
            if len(row) != width:
                bad_lines.append(first_line)
                row = row + [""] * (width - len(row)) if len(row) < width else [
                    *row[: width - 1],
                    delimiter.join(row[width - 1 :]),
                ]
            rows.append(row)
        return rows, bad_lines

    # ----------------------------------------------------------------- types

    @staticmethod
    def _infer_column_types(names: list[str], rows: list[list[str]]) -> dict[str, str]:
        """integer / float / boolean / datetime / text, from a sample of values."""
        sample = rows[:_TYPE_SAMPLE_ROWS]
        types: dict[str, str] = {}
        for idx, name in enumerate(names):
            values = [row[idx].strip() for row in sample if row[idx].strip()]
            if not values:
                types[name] = "text"
            elif all(_INT_RE.fullmatch(v) for v in values):
                types[name] = "integer"
            elif all(_FLOAT_RE.fullmatch(v) for v in values):
                types[name] = "float"
            elif all(v.lower() in ("true", "false") for v in values):
                types[name] = "boolean"
            elif _looks_like_dates(values):
                types[name] = "datetime"
            else:
                types[name] = "text"
        return types

    def _extract_csv_metadata(self, csv_metadata: CSVMetadata) -> dict[str, Any]:
        """CSV-specific metadata."""
        return {
            "format": "csv",
            "delimiter": csv_metadata.delimiter,
            "delimiter_name": self._get_delimiter_name(csv_metadata.delimiter),
            "encoding": csv_metadata.encoding,
            "has_header": csv_metadata.has_header,
            "num_rows": csv_metadata.num_rows,
            "num_columns": csv_metadata.num_columns,
            "column_names": csv_metadata.column_names,
            "column_types": csv_metadata.column_types,
        }

    def _get_delimiter_name(self, delimiter: str) -> str:
        """Human-readable delimiter name."""
        return {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}.get(delimiter, "custom")


def _looks_like_dates(values: list[str]) -> bool:
    """True when every value parses as a date (pandas, warnings silenced)."""
    if not all(re.search(r"\d", v) for v in values):
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(pd.Series(values), format="mixed", errors="coerce")
    return bool(parsed.notna().all())
