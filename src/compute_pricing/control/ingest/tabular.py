"""Schema-neutral, local table evidence. No normalization or formula execution."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
import hashlib
import json

from .xlsx import MAX_ROW, WorkbookError, column_letters, read_workbook

VERSION = "tabular-evidence/1.0"
MAX_TABLE_BYTES = 4 * 1024 * 1024
MAX_CELL_TEXT = 65536


def _cell(cell):
    value, kind = cell.value, "blank"
    if cell.formula is not None:
        value, kind = None, "formula_unevaluated"
    elif isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (datetime, time)):
        value, kind = value.isoformat(), "naive_datetime" if isinstance(value, datetime) else "naive_time"
    elif cell.excel_type == "n" and value is not None:
        try:
            number = Decimal(cell.raw_text)
        except (InvalidOperation, TypeError):
            raise WorkbookError("invalid stored numeric evidence") from None
        if not number.is_finite():
            raise WorkbookError("nonfinite stored numeric evidence")
        # Preserve the stored decimal text, including scale, without a float round trip.
        value, kind = cell.raw_text, "decimal_text"
    elif value is not None:
        kind = "error" if cell.excel_type == "e" else "text"
    packet = {"cell": cell.ref, "kind": kind, "value": value,
            "raw_text": cell.raw_text, "number_format": cell.number_format,
            "formula": cell.formula, "cached_text": cell.cached_text,
            "excel_type": cell.excel_type}
    if any(isinstance(item, str) and len(item) > MAX_CELL_TEXT for item in packet.values()):
        raise WorkbookError("cell text budget exceeded")
    return packet


def extract_table(data: bytes, *, sheet_name: str, header_row: int,
                  max_rows: int = 10000, max_columns: int = 512) -> dict:
    """Read explicitly selected table cells; retain all labels and unheaded columns.

    Limits refuse over-budget tables instead of publishing a silently partial
    table. Unknown units, currencies and dates require separate qualification.
    No expected field list is used.
    """
    if not isinstance(data, bytes) or not isinstance(sheet_name, str) or not sheet_name:
        raise WorkbookError("explicit workbook bytes and sheet required")
    if type(header_row) is not int or not 1 <= header_row < MAX_ROW:
        raise WorkbookError("invalid header row")
    if type(max_rows) is not int or not 1 <= max_rows <= 10000 or type(max_columns) is not int or not 1 <= max_columns <= 512:
        raise WorkbookError("invalid table budget")
    workbook = read_workbook(data, max_cells=100000)
    sheet = workbook.sheet(sheet_name)
    if sheet is None or sheet.kind != "worksheet":
        raise WorkbookError("selected worksheet unavailable")
    selected = [cell for cell in sheet.cells.values() if cell.row >= header_row and (cell.value is not None or cell.formula is not None)]
    columns = sorted({cell.column for cell in selected})
    row_numbers = sorted({cell.row for cell in selected if cell.row > header_row})
    if len(columns) > max_columns or len(row_numbers) > max_rows or len(columns) * len(row_numbers) > 100000:
        raise WorkbookError("table budget exceeded")
    emitted_bytes = 0
    def bounded_packet(packet):
        nonlocal emitted_bytes
        emitted_bytes += len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        if emitted_bytes > MAX_TABLE_BYTES:
            raise WorkbookError("table byte budget exceeded")
        return packet
    labels, definitions, warnings = set(), [], ["unqualified_local_table_evidence", "units_currency_and_timezone_not_inferred"]
    for column in columns:
        header = sheet.cell(header_row, column)
        if header.formula is not None or header.value is not None and header.excel_type != "s":
            raise WorkbookError("text or blank headers required")
        label = header.value
        if label is not None and label in labels:
            raise WorkbookError("duplicate table headers")
        if label is not None:
            labels.add(label)
        else:
            warnings.append("unheaded_column_retained:" + column_letters(column))
        definitions.append(bounded_packet({"id": "column:" + column_letters(column), "label": label,
                            "header": _cell(header)}))
    rows = [{"source_row": row, "cells": {"column:" + column_letters(column): bounded_packet(_cell(sheet.cell(row, column))) for column in columns}}
            for row in row_numbers]
    if any(cell["formula"] is not None for row in rows for cell in row["cells"].values()):
        warnings.append("formulas_preserved_not_evaluated_or_qualified")
    content = {"schema_version": VERSION, "source_sha256": workbook.sha256,
               "source_bytes": workbook.size_bytes, "sheet": sheet.name,
               "header_row": header_row, "columns": definitions, "rows": rows,
               "row_count": len(rows), "coverage": {"selected_sheet": True, "complete_selected_stored_table": True,
               "other_sheets_imported": False, "blank_rows_omitted": True, "merged_ranges": list(sheet.merged_ranges)},
               "authorization_scope": "caller_supplied_local_processing_no_reuse_rights_asserted",
               "permissions": {"observe": "UNKNOWN", "retain": "UNKNOWN", "benchmark": "FAIL", "execution": "FAIL"},
               "warnings": warnings, "execution_enabled": False}
    # Shared strings can repeat many times. Never allocate the entire expanded
    # serialization before its byte budget has been checked.
    checksum, serialized_bytes = hashlib.sha256(), 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(content):
        encoded = chunk.encode("utf-8")
        serialized_bytes += len(encoded)
        if serialized_bytes > MAX_TABLE_BYTES:
            raise WorkbookError("table byte budget exceeded")
        checksum.update(encoded)
    return {"content": content, "content_sha256": checksum.hexdigest()}
