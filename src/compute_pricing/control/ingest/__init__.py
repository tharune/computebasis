"""Unqualified local table evidence; no normalization or execution."""
from .tabular import extract_table
from .xlsx import WorkbookError, read_workbook

__all__ = ["extract_table", "WorkbookError", "read_workbook"]
