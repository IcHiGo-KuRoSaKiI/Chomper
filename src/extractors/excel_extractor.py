"""
Excel extractor using openpyxl.

Extracts text, tables, formulas, and metadata from Excel files (.xlsx, .xls).
Handles merged cells, multiple sheets, and table detection.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.cell.cell import Cell
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from .base import BaseExtractor
from ..models.document import RawDocument
from ..models.excel_models import (
    CellInfo,
    TableRange,
    SheetInfo,
    ExcelMetadata
)

logger = logging.getLogger(__name__)


class ExcelExtractor(BaseExtractor):
    """
    Extract content from Excel files (.xlsx, .xls).

    Features:
    - Multi-sheet support
    - Merged cell detection and handling
    - Formula extraction (value + formula)
    - Table boundary detection
    - Column type inference
    - Metadata extraction
    """

    SUPPORTED_EXTENSIONS = ['.xlsx', '.xlsm', '.xltx', '.xltm']

    def __init__(
        self,
        data_only: bool = True,
        detect_tables: bool = True,
        min_table_rows: int = 2,
        min_table_cols: int = 2,
        fill_merged_cells: bool = True
    ):
        """
        Initialize Excel extractor.

        Args:
            data_only: Extract calculated values instead of formulas
            detect_tables: Automatically detect table boundaries
            min_table_rows: Minimum rows to consider a table
            min_table_cols: Minimum columns to consider a table
            fill_merged_cells: Fill merged cell ranges with top-left value
        """
        if not OPENPYXL_AVAILABLE:
            raise ImportError(
                "openpyxl is required for Excel extraction. "
                "Install with: pip install openpyxl"
            )

        self.data_only = data_only
        self.detect_tables = detect_tables
        self.min_table_rows = min_table_rows
        self.min_table_cols = min_table_cols
        self.fill_merged_cells = fill_merged_cells

    def extract(self, file_path: str) -> RawDocument:
        """
        Extract content from Excel file.

        Args:
            file_path: Path to Excel file

        Returns:
            RawDocument with extracted content and structure
        """
        self.validate_file(file_path)

        # Load workbook
        workbook = openpyxl.load_workbook(
            file_path,
            data_only=self.data_only,
            read_only=False  # Need write mode to detect merged cells
        )

        # Extract all sheets
        sheets_data = []
        excel_metadata = ExcelMetadata(
            filename=Path(file_path).name,
            total_sheets=len(workbook.sheetnames)
        )

        for sheet_idx, sheet_name in enumerate(workbook.sheetnames):
            sheet = workbook[sheet_name]
            sheet_info = self._extract_sheet(sheet, sheet_idx)
            excel_metadata.sheets.append(sheet_info)

            if not sheet_info.is_empty:
                sheet_text = self._sheet_to_text(sheet, sheet_info)
                sheets_data.append({
                    'sheet_name': sheet_name,
                    'sheet_index': sheet_idx,
                    'text': sheet_text,
                    'info': sheet_info
                })

        # Combine all sheets into full text
        full_text = self._combine_sheets_text(sheets_data)

        # Get workbook metadata
        metadata = self._get_basic_metadata(file_path)
        metadata.update(self._extract_workbook_metadata(workbook, excel_metadata))

        workbook.close()

        return RawDocument(
            text=full_text,
            metadata=metadata,
            structure={
                'sheets': sheets_data,
                'excel_metadata': excel_metadata
            }
        )

    def _extract_sheet(self, sheet, sheet_idx: int) -> SheetInfo:
        """
        Extract metadata and structure from a single sheet.

        Args:
            sheet: openpyxl worksheet
            sheet_idx: Sheet index

        Returns:
            SheetInfo with detected tables and metadata
        """
        # Get sheet dimensions
        max_row = sheet.max_row
        max_column = sheet.max_column

        # Check if sheet has data
        has_data = max_row > 0 and max_column > 0

        if not has_data:
            return SheetInfo(
                name=sheet.title,
                index=sheet_idx,
                max_row=0,
                max_column=0,
                has_data=False
            )

        # Detect merged cells
        merged_cells = []
        has_merged_cells = False

        if hasattr(sheet, 'merged_cells') and sheet.merged_cells:
            has_merged_cells = True
            for merged_range in sheet.merged_cells.ranges:
                merged_cells.append((
                    merged_range.min_row,
                    merged_range.min_col,
                    merged_range.max_row,
                    merged_range.max_col
                ))

        # Detect formulas
        has_formulas = self._detect_formulas(sheet)

        # Detect tables
        tables = []
        if self.detect_tables:
            tables = self._detect_tables_in_sheet(sheet)

        # Infer column types
        column_types = self._infer_column_types(sheet, max_column)

        return SheetInfo(
            name=sheet.title,
            index=sheet_idx,
            max_row=max_row,
            max_column=max_column,
            has_data=has_data,
            tables=tables,
            merged_cells=merged_cells,
            has_formulas=has_formulas,
            has_merged_cells=has_merged_cells,
            column_types=column_types
        )

    def _detect_formulas(self, sheet) -> bool:
        """Check if sheet contains any formulas."""
        # Sample first 100 cells for performance
        sample_size = min(100, sheet.max_row * sheet.max_column)
        cells_checked = 0

        for row in sheet.iter_rows(max_row=min(10, sheet.max_row)):
            for cell in row:
                if cells_checked >= sample_size:
                    return False

                if cell.value and isinstance(cell.value, str):
                    if cell.value.startswith('='):
                        return True

                cells_checked += 1

        return False

    def _detect_tables_in_sheet(self, sheet) -> List[TableRange]:
        """
        Detect table boundaries in sheet.

        Uses heuristics:
        - Empty rows/columns as boundaries
        - Bold formatting as headers
        - Contiguous data regions

        Returns:
            List of detected TableRange objects
        """
        tables = []

        # Simple approach: Find contiguous data regions separated by empty rows
        current_table_start = None
        last_non_empty_row = 0

        for row_idx, row in enumerate(sheet.iter_rows(), start=1):
            row_has_data = any(cell.value is not None for cell in row)

            if row_has_data:
                if current_table_start is None:
                    current_table_start = row_idx

                last_non_empty_row = row_idx

            # Empty row - end current table if exists
            elif current_table_start is not None:
                # Check if table meets minimum size
                table_rows = last_non_empty_row - current_table_start + 1

                if table_rows >= self.min_table_rows:
                    # Determine column range
                    start_col, end_col = self._get_table_column_range(
                        sheet,
                        current_table_start,
                        last_non_empty_row
                    )

                    if end_col - start_col + 1 >= self.min_table_cols:
                        # Detect header row (first row is usually header)
                        header_row = current_table_start if self._is_header_row(sheet, current_table_start) else None

                        table = TableRange(
                            sheet_name=sheet.title,
                            start_row=current_table_start,
                            start_col=start_col,
                            end_row=last_non_empty_row,
                            end_col=end_col,
                            header_row=header_row,
                            has_headers=header_row is not None
                        )
                        tables.append(table)

                current_table_start = None

        # Handle table that extends to end of sheet
        if current_table_start is not None:
            table_rows = last_non_empty_row - current_table_start + 1

            if table_rows >= self.min_table_rows:
                start_col, end_col = self._get_table_column_range(
                    sheet,
                    current_table_start,
                    last_non_empty_row
                )

                if end_col - start_col + 1 >= self.min_table_cols:
                    header_row = current_table_start if self._is_header_row(sheet, current_table_start) else None

                    table = TableRange(
                        sheet_name=sheet.title,
                        start_row=current_table_start,
                        start_col=start_col,
                        end_row=last_non_empty_row,
                        end_col=end_col,
                        header_row=header_row,
                        has_headers=header_row is not None
                    )
                    tables.append(table)

        return tables

    def _get_table_column_range(self, sheet, start_row: int, end_row: int) -> Tuple[int, int]:
        """
        Determine the column range for a table.

        Args:
            sheet: Worksheet
            start_row: Table start row
            end_row: Table end row

        Returns:
            Tuple of (start_col, end_col)
        """
        min_col = sheet.max_column
        max_col = 1

        for row_idx in range(start_row, end_row + 1):
            for col_idx in range(1, sheet.max_column + 1):
                cell = sheet.cell(row_idx, col_idx)
                if cell.value is not None:
                    min_col = min(min_col, col_idx)
                    max_col = max(max_col, col_idx)

        return (min_col, max_col)

    def _is_header_row(self, sheet, row_idx: int) -> bool:
        """
        Heuristic to detect if row is a header row.

        Checks for:
        - Bold formatting
        - All text values
        - First row of table

        Args:
            sheet: Worksheet
            row_idx: Row index to check

        Returns:
            True if likely a header row
        """
        row = list(sheet.iter_rows(min_row=row_idx, max_row=row_idx))[0]

        # Check if all non-empty cells are text
        text_cells = 0
        bold_cells = 0
        total_cells = 0

        for cell in row:
            if cell.value is not None:
                total_cells += 1

                # Check if text
                if isinstance(cell.value, str):
                    text_cells += 1

                # Check if bold
                if hasattr(cell, 'font') and cell.font and cell.font.bold:
                    bold_cells += 1

        if total_cells == 0:
            return False

        # If more than 50% are bold, likely header
        if bold_cells / total_cells > 0.5:
            return True

        # If all are text and it's the first row, likely header
        if text_cells == total_cells and row_idx == 1:
            return True

        return False

    def _infer_column_types(self, sheet, max_column: int) -> Dict[int, str]:
        """
        Infer data types for each column.

        Args:
            sheet: Worksheet
            max_column: Number of columns

        Returns:
            Dict mapping column index to type
        """
        column_types = {}

        # Sample first 20 rows to infer types
        sample_rows = min(20, sheet.max_row)

        for col_idx in range(1, max_column + 1):
            types_seen = set()

            for row_idx in range(1, sample_rows + 1):
                cell = sheet.cell(row_idx, col_idx)
                if cell.value is not None:
                    cell_type = self._get_cell_type(cell)
                    types_seen.add(cell_type)

            # Determine predominant type
            if 'number' in types_seen and 'text' in types_seen:
                column_types[col_idx] = 'mixed'
            elif 'number' in types_seen:
                column_types[col_idx] = 'number'
            elif 'date' in types_seen:
                column_types[col_idx] = 'date'
            elif 'boolean' in types_seen:
                column_types[col_idx] = 'boolean'
            else:
                column_types[col_idx] = 'text'

        return column_types

    def _get_cell_type(self, cell) -> str:
        """
        Determine cell data type.

        Args:
            cell: Excel cell

        Returns:
            Type string: "text", "number", "date", "boolean", "formula", "empty"
        """
        if cell.value is None:
            return "empty"

        if isinstance(cell.value, bool):
            return "boolean"

        if isinstance(cell.value, (int, float)):
            return "number"

        if hasattr(cell, 'is_date') and cell.is_date:
            return "date"

        if isinstance(cell.value, str):
            if cell.value.startswith('='):
                return "formula"
            return "text"

        return "text"

    def _sheet_to_text(self, sheet, sheet_info: SheetInfo) -> str:
        """
        Convert sheet to plain text.

        Handles merged cells by filling them with top-left value.

        Args:
            sheet: Worksheet
            sheet_info: SheetInfo with metadata

        Returns:
            Plain text representation
        """
        # Create a dict to track merged cell values
        merged_values = {}

        if self.fill_merged_cells and sheet_info.has_merged_cells:
            for min_row, min_col, max_row, max_col in sheet_info.merged_cells:
                # Get top-left cell value
                top_left_value = sheet.cell(min_row, min_col).value

                # Fill all cells in merged range
                for row_idx in range(min_row, max_row + 1):
                    for col_idx in range(min_col, max_col + 1):
                        merged_values[(row_idx, col_idx)] = top_left_value

        # Convert to text row by row
        rows_text = []

        for row_idx in range(1, sheet_info.max_row + 1):
            row_values = []

            for col_idx in range(1, sheet_info.max_column + 1):
                # Check if cell is in merged range
                if (row_idx, col_idx) in merged_values:
                    value = merged_values[(row_idx, col_idx)]
                else:
                    cell = sheet.cell(row_idx, col_idx)
                    value = cell.value

                # Convert to string
                if value is not None:
                    row_values.append(str(value))
                else:
                    row_values.append("")

            # Join with tabs (TSV format)
            rows_text.append("\t".join(row_values))

        return "\n".join(rows_text)

    def _combine_sheets_text(self, sheets_data: List[Dict[str, Any]]) -> str:
        """
        Combine multiple sheets into single text.

        Args:
            sheets_data: List of sheet data dicts

        Returns:
            Combined text from all sheets
        """
        if not sheets_data:
            return ""

        combined_parts = []

        for sheet_data in sheets_data:
            sheet_header = f"=== Sheet: {sheet_data['sheet_name']} ==="
            combined_parts.append(sheet_header)
            combined_parts.append(sheet_data['text'])
            combined_parts.append("")  # Empty line between sheets

        return "\n".join(combined_parts)

    def _extract_workbook_metadata(self, workbook, excel_metadata: ExcelMetadata) -> Dict[str, Any]:
        """
        Extract workbook-level metadata.

        Args:
            workbook: Openpyxl workbook
            excel_metadata: ExcelMetadata object

        Returns:
            Metadata dictionary
        """
        metadata = {
            "format": "excel",
            "total_sheets": excel_metadata.total_sheets,
            "active_sheets": len(excel_metadata.active_sheets),
            "total_tables": excel_metadata.total_tables,
            "has_multiple_sheets": excel_metadata.has_multiple_sheets,
            "sheet_names": [sheet.name for sheet in excel_metadata.sheets]
        }

        # Extract document properties if available
        if hasattr(workbook, 'properties'):
            props = workbook.properties
            if props.creator:
                metadata["author"] = props.creator
            if props.created:
                metadata["created"] = str(props.created)
            if props.modified:
                metadata["modified"] = str(props.modified)
            if props.title:
                metadata["title"] = props.title

        return metadata
