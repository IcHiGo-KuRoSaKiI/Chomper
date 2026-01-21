"""
Excel/CSV chunker with intelligent strategies.

Provides multiple chunking strategies:
- by_sheet: One chunk per sheet
- by_table: One chunk per detected table
- by_rows: Fixed number of rows per chunk
- auto: Automatically select best strategy
"""
import logging
from typing import List, Optional
from ...models.document import RawDocument, Chunk
from ...models.excel_models import SheetInfo, TableRange, ExcelMetadata
from ..base import BaseChunker

logger = logging.getLogger(__name__)


class ExcelChunker(BaseChunker):
    """
    Intelligent chunking for Excel/CSV files.

    Strategies:
    - by_sheet: Each sheet becomes one chunk (multi-sheet workbooks)
    - by_table: Each detected table becomes one chunk
    - by_rows: Fixed row ranges (large single tables)
    - auto: Automatically choose best strategy

    Auto-selection logic:
    - Multiple sheets with data → by_sheet
    - Single sheet with multiple tables → by_table
    - Single sheet with one large table → by_rows
    """

    def __init__(
        self,
        strategy: str = "auto",
        chunk_size: int = 100,  # For by_rows strategy
        preserve_headers: bool = True,
        convert_to_html: bool = True
    ):
        """
        Initialize Excel chunker.

        Args:
            strategy: Chunking strategy ("auto", "by_sheet", "by_table", "by_rows")
            chunk_size: Number of rows per chunk (for by_rows strategy)
            preserve_headers: Include headers in each chunk
            convert_to_html: Convert tables to HTML format for LLMs
        """
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.preserve_headers = preserve_headers
        self.convert_to_html = convert_to_html

        if strategy not in ["auto", "by_sheet", "by_table", "by_rows"]:
            raise ValueError(f"Unknown strategy: {strategy}")

    def chunk(self, raw_doc: RawDocument) -> List[Chunk]:
        """
        Chunk Excel/CSV document.

        Args:
            raw_doc: RawDocument from ExcelExtractor or CSVExtractor

        Returns:
            List of chunks
        """
        # Determine format
        is_csv = raw_doc.metadata.get("format") == "csv"
        is_excel = raw_doc.metadata.get("format") == "excel"

        if not (is_csv or is_excel):
            raise ValueError("ExcelChunker only supports Excel/CSV documents")

        # Get structure
        structure = raw_doc.structure

        # CSV files are treated as single-sheet Excel files
        if is_csv:
            return self._chunk_csv(raw_doc, structure)

        # Excel files may have multiple sheets
        return self._chunk_excel(raw_doc, structure)

    def _chunk_csv(self, raw_doc: RawDocument, structure: dict) -> List[Chunk]:
        """
        Chunk CSV file.

        CSV is treated as a single table, so we use by_rows strategy.

        Args:
            raw_doc: RawDocument
            structure: Document structure

        Returns:
            List of chunks
        """
        csv_metadata = structure.get('csv_metadata')
        num_rows = csv_metadata.num_rows if csv_metadata else 0

        # For small CSV files, return as single chunk
        if num_rows <= self.chunk_size:
            return [
                Chunk(
                    chunk_id=0,
                    text=raw_doc.text,
                    metadata={
                        "source_type": "csv",
                        "delimiter": csv_metadata.delimiter if csv_metadata else ",",
                        "num_rows": num_rows,
                        "num_columns": csv_metadata.num_columns if csv_metadata else 0,
                        "column_names": csv_metadata.column_names if csv_metadata else []
                    }
                )
            ]

        # For large CSV, chunk by rows
        return self._chunk_by_rows_csv(raw_doc, csv_metadata)

    def _chunk_excel(self, raw_doc: RawDocument, structure: dict) -> List[Chunk]:
        """
        Chunk Excel file using selected or auto-detected strategy.

        Args:
            raw_doc: RawDocument
            structure: Document structure

        Returns:
            List of chunks
        """
        excel_metadata: ExcelMetadata = structure.get('excel_metadata')
        sheets_data = structure.get('sheets', [])

        if not excel_metadata or not sheets_data:
            # Fallback: single chunk
            return [
                Chunk(
                    chunk_id=0,
                    text=raw_doc.text,
                    metadata={"source_type": "excel", "strategy": "fallback"}
                )
            ]

        # Auto-select strategy
        if self.strategy == "auto":
            selected_strategy = self._auto_select_strategy(excel_metadata, sheets_data)
            logger.info(f"Auto-selected strategy: {selected_strategy}")
        else:
            selected_strategy = self.strategy

        # Apply selected strategy
        if selected_strategy == "by_sheet":
            return self._chunk_by_sheet(excel_metadata, sheets_data)
        elif selected_strategy == "by_table":
            return self._chunk_by_table(excel_metadata, sheets_data)
        elif selected_strategy == "by_rows":
            return self._chunk_by_rows(excel_metadata, sheets_data)
        else:
            # Fallback to by_sheet
            return self._chunk_by_sheet(excel_metadata, sheets_data)

    def _auto_select_strategy(self, excel_metadata: ExcelMetadata, sheets_data: List[dict]) -> str:
        """
        Automatically select best chunking strategy.

        Logic:
        - Multiple sheets with data → by_sheet
        - Single sheet with multiple tables → by_table
        - Single sheet with large single table → by_rows

        Args:
            excel_metadata: Excel metadata
            sheets_data: Sheets data

        Returns:
            Strategy name
        """
        # Multiple sheets with data
        if excel_metadata.has_multiple_sheets:
            return "by_sheet"

        # Single sheet
        if len(excel_metadata.active_sheets) == 1:
            sheet_info = excel_metadata.active_sheets[0]

            # Multiple tables detected
            if sheet_info.num_tables > 1:
                return "by_table"

            # Single large table
            if sheet_info.num_tables == 1:
                table = sheet_info.tables[0]
                if table.data_rows > self.chunk_size:
                    return "by_rows"
                else:
                    return "by_table"

            # No tables detected, chunk by rows
            if sheet_info.max_row > self.chunk_size:
                return "by_rows"

        # Default: by_sheet
        return "by_sheet"

    def _chunk_by_sheet(self, excel_metadata: ExcelMetadata, sheets_data: List[dict]) -> List[Chunk]:
        """
        Create one chunk per sheet.

        Args:
            excel_metadata: Excel metadata
            sheets_data: Sheets data

        Returns:
            List of chunks
        """
        chunks = []

        for idx, sheet_data in enumerate(sheets_data):
            sheet_info: SheetInfo = sheet_data.get('info')
            sheet_text = sheet_data.get('text', '')

            # Convert to HTML if requested
            if self.convert_to_html:
                html_text = self._convert_to_html_table(sheet_text, sheet_info)
                display_text = html_text
            else:
                display_text = sheet_text

            chunk = Chunk(
                chunk_id=idx,
                text=display_text,
                metadata={
                    "source_type": "excel",
                    "strategy": "by_sheet",
                    "sheet_name": sheet_data.get('sheet_name'),
                    "sheet_index": sheet_data.get('sheet_index'),
                    "num_rows": sheet_info.max_row if sheet_info else 0,
                    "num_columns": sheet_info.max_column if sheet_info else 0,
                    "has_formulas": sheet_info.has_formulas if sheet_info else False,
                    "has_merged_cells": sheet_info.has_merged_cells if sheet_info else False,
                    "num_tables": sheet_info.num_tables if sheet_info else 0
                }
            )
            chunks.append(chunk)

        return chunks

    def _chunk_by_table(self, excel_metadata: ExcelMetadata, sheets_data: List[dict]) -> List[Chunk]:
        """
        Create one chunk per detected table.

        Args:
            excel_metadata: Excel metadata
            sheets_data: Sheets data

        Returns:
            List of chunks
        """
        chunks = []
        chunk_id = 0

        for sheet_data in sheets_data:
            sheet_info: SheetInfo = sheet_data.get('info')
            sheet_text = sheet_data.get('text', '')

            if not sheet_info or not sheet_info.tables:
                # No tables, treat entire sheet as one chunk
                chunk = Chunk(
                    chunk_id=chunk_id,
                    text=sheet_text,
                    metadata={
                        "source_type": "excel",
                        "strategy": "by_table",
                        "sheet_name": sheet_data.get('sheet_name'),
                        "table_index": None
                    }
                )
                chunks.append(chunk)
                chunk_id += 1
                continue

            # Extract each table
            for table_idx, table in enumerate(sheet_info.tables):
                table_text = self._extract_table_text(sheet_text, table)

                # Convert to HTML if requested
                if self.convert_to_html:
                    html_text = self._table_to_html(table_text, table)
                    display_text = html_text
                else:
                    display_text = table_text

                chunk = Chunk(
                    chunk_id=chunk_id,
                    text=display_text,
                    metadata={
                        "source_type": "excel",
                        "strategy": "by_table",
                        "sheet_name": sheet_data.get('sheet_name'),
                        "table_index": table_idx,
                        "table_range": table.range_str,
                        "num_rows": table.num_rows,
                        "num_columns": table.num_cols,
                        "has_headers": table.has_headers
                    }
                )
                chunks.append(chunk)
                chunk_id += 1

        return chunks

    def _chunk_by_rows(self, excel_metadata: ExcelMetadata, sheets_data: List[dict]) -> List[Chunk]:
        """
        Create chunks of fixed row ranges.

        Args:
            excel_metadata: Excel metadata
            sheets_data: Sheets data

        Returns:
            List of chunks
        """
        chunks = []
        chunk_id = 0

        for sheet_data in sheets_data:
            sheet_info: SheetInfo = sheet_data.get('info')
            sheet_text = sheet_data.get('text', '')

            if not sheet_info:
                continue

            # Split sheet text by rows
            rows = sheet_text.split('\n')
            header_row = rows[0] if self.preserve_headers and len(rows) > 0 else None

            # Chunk rows
            start_idx = 1 if header_row else 0

            while start_idx < len(rows):
                end_idx = min(start_idx + self.chunk_size, len(rows))

                # Build chunk text
                chunk_rows = []
                if header_row and self.preserve_headers:
                    chunk_rows.append(header_row)

                chunk_rows.extend(rows[start_idx:end_idx])
                chunk_text = '\n'.join(chunk_rows)

                chunk = Chunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    metadata={
                        "source_type": "excel",
                        "strategy": "by_rows",
                        "sheet_name": sheet_data.get('sheet_name'),
                        "row_start": start_idx + 1,  # Excel is 1-indexed
                        "row_end": end_idx,
                        "chunk_size": self.chunk_size
                    }
                )
                chunks.append(chunk)

                chunk_id += 1
                start_idx = end_idx

        return chunks

    def _chunk_by_rows_csv(self, raw_doc: RawDocument, csv_metadata) -> List[Chunk]:
        """
        Chunk CSV by row ranges.

        Args:
            raw_doc: RawDocument
            csv_metadata: CSV metadata

        Returns:
            List of chunks
        """
        chunks = []
        rows = raw_doc.text.split('\n')

        header_row = rows[0] if csv_metadata.has_header and len(rows) > 0 else None
        start_idx = 1 if header_row else 0

        chunk_id = 0
        while start_idx < len(rows):
            end_idx = min(start_idx + self.chunk_size, len(rows))

            chunk_rows = []
            if header_row and self.preserve_headers:
                chunk_rows.append(header_row)

            chunk_rows.extend(rows[start_idx:end_idx])
            chunk_text = '\n'.join(chunk_rows)

            chunk = Chunk(
                chunk_id=chunk_id,
                text=chunk_text,
                metadata={
                    "source_type": "csv",
                    "strategy": "by_rows",
                    "row_start": start_idx + 1,
                    "row_end": end_idx,
                    "has_header": csv_metadata.has_header
                }
            )
            chunks.append(chunk)

            chunk_id += 1
            start_idx = end_idx

        return chunks

    def _extract_table_text(self, sheet_text: str, table: TableRange) -> str:
        """
        Extract text for a specific table from sheet text.

        Args:
            sheet_text: Full sheet text (TSV format)
            table: TableRange object

        Returns:
            Table text
        """
        rows = sheet_text.split('\n')

        # Extract rows for this table (Excel is 1-indexed)
        table_rows = rows[table.start_row - 1:table.end_row]

        # Extract columns for this table
        filtered_rows = []
        for row_text in table_rows:
            cells = row_text.split('\t')
            # Excel columns are 1-indexed
            table_cells = cells[table.start_col - 1:table.end_col]
            filtered_rows.append('\t'.join(table_cells))

        return '\n'.join(filtered_rows)

    def _convert_to_html_table(self, text: str, sheet_info: Optional[SheetInfo]) -> str:
        """
        Convert TSV text to HTML table format.

        Args:
            text: TSV text
            sheet_info: Sheet information

        Returns:
            HTML table string
        """
        rows = text.split('\n')
        if not rows:
            return text

        html_parts = ['<table border="1">']

        # First row as header
        if sheet_info and sheet_info.tables and sheet_info.tables[0].has_headers:
            header_cells = rows[0].split('\t')
            html_parts.append('  <thead>')
            html_parts.append('    <tr>')
            for cell in header_cells:
                html_parts.append(f'      <th>{cell}</th>')
            html_parts.append('    </tr>')
            html_parts.append('  </thead>')
            data_rows = rows[1:]
        else:
            data_rows = rows

        # Data rows
        html_parts.append('  <tbody>')
        for row_text in data_rows:
            cells = row_text.split('\t')
            html_parts.append('    <tr>')
            for cell in cells:
                html_parts.append(f'      <td>{cell}</td>')
            html_parts.append('    </tr>')
        html_parts.append('  </tbody>')

        html_parts.append('</table>')

        return '\n'.join(html_parts)

    def _table_to_html(self, table_text: str, table: TableRange) -> str:
        """
        Convert table text to HTML.

        Args:
            table_text: TSV table text
            table: TableRange object

        Returns:
            HTML string
        """
        rows = table_text.split('\n')
        if not rows:
            return table_text

        html_parts = [f'<table border="1" summary="Table from {table.sheet_name}: {table.range_str}">']

        # Header row
        if table.has_headers and len(rows) > 0:
            header_cells = rows[0].split('\t')
            html_parts.append('  <thead>')
            html_parts.append('    <tr>')
            for cell in header_cells:
                html_parts.append(f'      <th>{cell}</th>')
            html_parts.append('    </tr>')
            html_parts.append('  </thead>')
            data_rows = rows[1:]
        else:
            data_rows = rows

        # Data rows
        html_parts.append('  <tbody>')
        for row_text in data_rows:
            cells = row_text.split('\t')
            html_parts.append('    <tr>')
            for cell in cells:
                html_parts.append(f'      <td>{cell}</td>')
            html_parts.append('    </tr>')
        html_parts.append('  </tbody>')

        html_parts.append('</table>')

        return '\n'.join(html_parts)
