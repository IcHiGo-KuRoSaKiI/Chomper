"""
CSV extractor using pandas.

Extracts text and metadata from CSV/TSV files.
Handles encoding detection, delimiter detection, and large files.
"""
import logging
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

logger = logging.getLogger(__name__)


class CSVExtractor(BaseExtractor):
    """
    Extract content from CSV/TSV files.

    Features:
    - Auto-detect delimiter (, ; \t |)
    - Auto-detect encoding (UTF-8, Latin-1, etc.)
    - Header detection
    - Column type inference
    - Memory-efficient for large files
    """

    SUPPORTED_EXTENSIONS = ['.csv', '.tsv', '.txt']

    def __init__(
        self,
        delimiter: str | None = None,
        encoding: str | None = None,
        has_header: bool | None = None,
        sample_size: int = 5000
    ):
        """
        Initialize CSV extractor.

        Args:
            delimiter: CSV delimiter (auto-detect if None)
            encoding: File encoding (auto-detect if None)
            has_header: Whether first row is header (auto-detect if None)
            sample_size: Number of bytes to sample for detection
        """
        if not PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is required for CSV extraction. "
                "Install with: pip install pandas"
            )

        self.delimiter = delimiter
        self.encoding = encoding
        self.has_header = has_header
        self.sample_size = sample_size

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from CSV file.

        Args:
            file_path: Path to CSV file

        Returns:
            RawDocument with extracted content
        """
        self.validate_file(file_path)

        # Auto-detect encoding if not specified
        encoding = self.encoding or self._detect_encoding(file_path)

        # Auto-detect delimiter if not specified
        delimiter = self.delimiter or self._detect_delimiter(file_path, encoding)

        # Read CSV
        try:
            df = pd.read_csv(
                file_path,
                delimiter=delimiter,
                encoding=encoding,
                on_bad_lines='skip',  # Skip problematic lines
                low_memory=False  # More accurate type inference
            )
        except Exception as e:
            logger.error(f"Failed to read CSV: {e}")
            # Try with Python engine as fallback
            df = pd.read_csv(
                file_path,
                delimiter=delimiter,
                encoding=encoding,
                engine='python',
                on_bad_lines='skip'
            )

        # Infer column types
        column_types = self._infer_column_types(df)

        # Create CSV metadata
        csv_metadata = CSVMetadata(
            filename=Path(file_path).name,
            delimiter=delimiter,
            encoding=encoding,
            has_header=len(df.columns) > 0 and isinstance(df.columns[0], str),
            num_rows=len(df),
            num_columns=len(df.columns),
            column_names=list(df.columns),
            column_types=column_types
        )

        # Convert to text (TSV format for consistency with Excel)
        text = self._dataframe_to_text(df)

        # Get metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_csv_metadata(csv_metadata))

        # Create structure (similar to Excel single-sheet)
        structure = {
            'csv_metadata': csv_metadata,
            'dataframe_shape': df.shape,
            'column_info': {
                col: {
                    'type': column_types.get(col, 'object'),
                    'null_count': df[col].isnull().sum(),
                    'unique_count': df[col].nunique()
                }
                for col in df.columns
            }
        }

        return RawDocument(
            text=text,
            metadata=metadata,
            structure=structure
        )

    def _detect_encoding(self, file_path: str) -> str:
        """
        Auto-detect file encoding.

        Args:
            file_path: Path to file

        Returns:
            Detected encoding (defaults to 'utf-8')
        """
        if not CHARDET_AVAILABLE:
            logger.warning("chardet not available, defaulting to UTF-8")
            return 'utf-8'

        try:
            with open(file_path, 'rb') as f:
                sample = f.read(self.sample_size)
                result = chardet.detect(sample)
                encoding = result['encoding']
                confidence = result['confidence']

                logger.info(f"Detected encoding: {encoding} (confidence: {confidence:.2f})")

                # If confidence is low, default to UTF-8
                if confidence < 0.7:
                    logger.warning(f"Low confidence ({confidence:.2f}), defaulting to UTF-8")
                    return 'utf-8'

                return encoding or 'utf-8'

        except Exception as e:
            logger.warning(f"Encoding detection failed: {e}, defaulting to UTF-8")
            return 'utf-8'

    def _detect_delimiter(self, file_path: str, encoding: str) -> str:
        """
        Auto-detect CSV delimiter.

        Tries common delimiters: , ; \t |

        Args:
            file_path: Path to file
            encoding: File encoding

        Returns:
            Detected delimiter (defaults to ',')
        """
        try:
            with open(file_path, encoding=encoding) as f:
                # Read first few lines
                sample_lines = [f.readline() for _ in range(5) if f.readable()]
                ''.join(sample_lines)

            # Try common delimiters
            delimiters = [',', ';', '\t', '|']
            delimiter_counts = {}

            for delim in delimiters:
                # Count occurrences in first line
                count = sample_lines[0].count(delim) if sample_lines else 0
                delimiter_counts[delim] = count

            # Choose delimiter with highest count
            best_delimiter = max(delimiter_counts, key=delimiter_counts.get)

            # If no delimiter found, default to comma
            if delimiter_counts[best_delimiter] == 0:
                logger.warning("No delimiter detected, defaulting to comma")
                return ','

            logger.info(f"Detected delimiter: {repr(best_delimiter)}")
            return best_delimiter

        except Exception as e:
            logger.warning(f"Delimiter detection failed: {e}, defaulting to comma")
            return ','

    def _infer_column_types(self, df: 'pd.DataFrame') -> dict[str, str]:
        """
        Infer data types for each column.

        Args:
            df: Pandas DataFrame

        Returns:
            Dict mapping column name to type
        """
        column_types = {}

        for col in df.columns:
            dtype = df[col].dtype

            if pd.api.types.is_integer_dtype(dtype):
                column_types[col] = 'integer'
            elif pd.api.types.is_float_dtype(dtype):
                column_types[col] = 'float'
            elif pd.api.types.is_bool_dtype(dtype):
                column_types[col] = 'boolean'
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                column_types[col] = 'datetime'
            elif pd.api.types.is_object_dtype(dtype):
                # Try to infer if it's actually numeric or date
                sample = df[col].dropna().head(100)

                if sample.empty:
                    column_types[col] = 'text'
                    continue

                # Check if convertible to numeric
                try:
                    pd.to_numeric(sample)
                    column_types[col] = 'numeric_text'
                except (ValueError, TypeError):
                    # Check if convertible to datetime
                    try:
                        pd.to_datetime(sample)
                        column_types[col] = 'datetime_text'
                    except (ValueError, TypeError):
                        column_types[col] = 'text'
            else:
                column_types[col] = str(dtype)

        return column_types

    def _dataframe_to_text(self, df: 'pd.DataFrame', use_markdown: bool = True) -> str:
        """
        Convert DataFrame to Markdown table format.

        Outputs proper Markdown pipe tables that LLMs prefer.

        Args:
            df: Pandas DataFrame
            use_markdown: Output Markdown pipe tables (default True)

        Returns:
            Markdown table representation
        """
        if not use_markdown:
            # Fallback to TSV format
            return df.to_csv(sep='\t', index=False, na_rep='')

        # Build Markdown pipe table
        lines = []

        # Header row
        headers = [str(col).replace('|', '\\|') for col in df.columns]
        lines.append("|" + "|".join(headers) + "|")

        # Header separator
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")

        # Data rows
        for _, row in df.iterrows():
            cells = []
            for val in row:
                if pd.isna(val):
                    cells.append("")
                else:
                    cells.append(str(val).replace('|', '\\|'))
            lines.append("|" + "|".join(cells) + "|")

        return "\n".join(lines)

    def _extract_csv_metadata(self, csv_metadata: CSVMetadata) -> dict[str, Any]:
        """
        Extract CSV-specific metadata.

        Args:
            csv_metadata: CSVMetadata object

        Returns:
            Metadata dictionary
        """
        return {
            "format": "csv",
            "delimiter": csv_metadata.delimiter,
            "delimiter_name": self._get_delimiter_name(csv_metadata.delimiter),
            "encoding": csv_metadata.encoding,
            "has_header": csv_metadata.has_header,
            "num_rows": csv_metadata.num_rows,
            "num_columns": csv_metadata.num_columns,
            "column_names": csv_metadata.column_names,
            "column_types": csv_metadata.column_types
        }

    def _get_delimiter_name(self, delimiter: str) -> str:
        """Get human-readable delimiter name."""
        delimiter_names = {
            ',': 'comma',
            ';': 'semicolon',
            '\t': 'tab',
            '|': 'pipe'
        }
        return delimiter_names.get(delimiter, 'custom')
