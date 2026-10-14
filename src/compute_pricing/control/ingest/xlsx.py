"""Bounded read-only OOXML cell evidence using the standard library.

Stored cell lexemes, formulas, formats and local date/time values remain
distinct. Formulas are never evaluated and relationships never fetched.
Unsupported or ambiguous structures refuse instead of guessing; callers may
supply a tighter cumulative stored-cell budget. See docs/third-party-notices.md
for number-format and serial-date compatibility attribution.
"""
from __future__ import annotations

import hashlib
import io
import math
import posixpath
import re
import zipfile
import zlib
import xml.etree.ElementTree as ET
import xml.parsers.expat
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TYPES = {
    "worksheet": DOC_REL_NS + "/worksheet",
    "chartsheet": DOC_REL_NS + "/chartsheet",
    "shared_strings": DOC_REL_NS + "/sharedStrings",
    "styles": DOC_REL_NS + "/styles",
    "office_document": DOC_REL_NS + "/officeDocument",
}

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_PART_BYTES = 32 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
MAX_CELLS = 2_000_000
MAX_XML_ELEMENTS = 500_000
MAX_ROW = 1_048_576
MAX_COLUMN = 16_384

# ECMA-376 built-in number formats as openpyxl 3.1.5 names them.
BUILTIN_FORMATS = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00",
    5: '"$"#,##0_);("$"#,##0)', 6: '"$"#,##0_);[Red]("$"#,##0)',
    7: '"$"#,##0.00_);("$"#,##0.00)', 8: '"$"#,##0.00_);[Red]("$"#,##0.00)',
    9: "0%", 10: "0.00%", 11: "0.00E+00", 12: "# ?/?", 13: "# ??/??",
    14: "mm-dd-yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm",
    37: "#,##0_);(#,##0)", 38: "#,##0_);[Red](#,##0)", 39: "#,##0.00_);(#,##0.00)",
    40: "#,##0.00_);[Red](#,##0.00)", 41: r'_(* #,##0_);_(* \(#,##0\);_(* "-"_);_(@_)',
    42: r'_("$"* #,##0_);_("$"* \(#,##0\);_("$"* "-"_);_(@_)',
    43: r'_(* #,##0.00_);_(* \(#,##0.00\);_(* "-"??_);_(@_)',
    44: r'_("$"* #,##0.00_)_("$"* \(#,##0.00\)_("$"* "-"??_)_(@_)',
    45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0", 49: "@",
}
# openpyxl 3.1.5 styles/numbers.py: quoted literals and bracketed locale/colour codes are ignored,
# except the elapsed-time codes [h], [hh], [m], [mm], [s], [ss].
_STRIP = re.compile(r'".*?"|\[(?!hh?\]|mm?\]|ss?\])[^\]]*\]')
_ELAPSED = re.compile(r"\[hh?\](:mm(:ss(\.0*)?)?)?|\[mm?\](:ss(\.0*)?)?|\[ss?\](\.0*)?", re.I)
_DATE_CHARS = re.compile(r"(?<![_\\])[dmhysDMHYS]")
_REF = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
WINDOWS_EPOCH = datetime(1899, 12, 30)
MAC_EPOCH = datetime(1904, 1, 1)
_ARCHIVE_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError,
                   OSError, ValueError)


class WorkbookError(ValueError):
    """Unreadable, unsafe or ambiguous workbook; messages never include cell values."""


def is_date_format(code: str | None) -> bool:
    if not code:
        return False
    return _DATE_CHARS.search(_STRIP.sub("", code.split(";")[0])) is not None


def is_elapsed_format(code: str | None) -> bool:
    return bool(code) and _ELAPSED.search(code.split(";")[0]) is not None


def column_index(letters: str) -> int:
    result = 0
    for char in letters:
        result = result * 26 + ord(char) - 64
    return result


def column_letters(index: int) -> str:
    if not 1 <= index <= MAX_COLUMN:
        raise WorkbookError("column index out of range")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def split_ref(ref: str) -> tuple[int, int]:
    match = _REF.fullmatch(ref or "")
    if not match:
        raise WorkbookError("invalid cell reference")
    row, column = int(match.group(2)), column_index(match.group(1))
    if row > MAX_ROW or column > MAX_COLUMN:
        raise WorkbookError("cell reference beyond the worksheet grid")
    return row, column


def _int(text: str | None, what: str) -> int:
    try:
        return int(text)
    except (TypeError, ValueError) as exc:
        raise WorkbookError(f"invalid {what}") from exc


def _cast_number(text: str) -> int | float:
    try:
        value = float(text) if ("." in text or "E" in text or "e" in text) else int(text)
    except ValueError as exc:
        raise WorkbookError("invalid numeric cell") from exc
    if isinstance(value, float) and not math.isfinite(value):
        raise WorkbookError("non-finite numeric cell")
    return value


def _days_to_time(value: timedelta) -> time:
    minutes, seconds = divmod(value.seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return time(hours, minutes, seconds, value.microseconds)


def _from_excel(serial: int | float, epoch: datetime) -> datetime | time:
    """openpyxl 3.1.5 utils.datetime.from_excel without its timedelta branch."""
    day, fraction = divmod(serial, 1)
    diff = timedelta(milliseconds=round(fraction * 86400 * 1000))
    if 0 <= serial < 1 and diff.days == 0:
        return _days_to_time(diff)
    if 0 < serial < 60 and epoch == WINDOWS_EPOCH:
        day += 1
    return epoch + timedelta(days=day) + diff


@dataclass(frozen=True)
class Cell:
    """One cell as stored. ``value`` follows openpyxl's ``data_only=False`` view."""

    ref: str
    row: int
    column: int
    value: object
    excel_type: str
    number_format: str
    ooxml_type: str | None
    raw_text: str | None
    formula: str | None = None
    cached_text: str | None = None


@dataclass(frozen=True)
class Sheet:
    name: str
    state: str
    kind: str
    part: str
    part_sha256: str
    cells: dict[tuple[int, int], Cell] = field(repr=False)
    merged_ranges: tuple[str, ...] = ()

    @property
    def dimension(self) -> str | None:
        if not self.cells:
            return None
        rows = [key[0] for key in self.cells]
        columns = [key[1] for key in self.cells]
        return (f"{column_letters(min(columns))}{min(rows)}:"
                f"{column_letters(max(columns))}{max(rows)}")

    def cell(self, row: int, column: int) -> Cell:
        """A stored cell, or the blank cell openpyxl would create for an absent one."""
        existing = self.cells.get((row, column))
        if existing is not None:
            return existing
        return Cell(f"{column_letters(column)}{row}", row, column, None, "n", "General", None, None)

    @property
    def formula_count(self) -> int:
        return sum(1 for cell in self.cells.values() if cell.formula is not None)


@dataclass(frozen=True)
class Workbook:
    sha256: str
    size_bytes: int
    date1904: bool
    sheets: tuple[Sheet, ...]

    def sheet(self, name: str) -> Sheet | None:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        return None


def _refuse_declarations(data: bytes, *, max_cells: int = MAX_CELLS) -> None:
    """Reject DTDs and entity declarations after decoding, whatever the part's encoding."""
    def refuse(*_args):
        raise WorkbookError("XML document type or entity declarations are not accepted")

    parser = xml.parsers.expat.ParserCreate(namespace_separator="}")
    elements, cells = 0, 0
    def element(name, _attributes):
        nonlocal elements, cells
        elements += 1
        if name == MAIN_NS + "}c":
            cells += 1
        if cells > max_cells or elements > MAX_XML_ELEMENTS:
            raise WorkbookError("XML element or stored-cell budget exceeded")
    parser.StartElementHandler = element
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.UnparsedEntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse
    try:
        parser.Parse(data, True)
    except (xml.parsers.expat.ExpatError, LookupError, ValueError) as exc:
        if isinstance(exc, WorkbookError):
            raise
        raise WorkbookError("unsupported or malformed XML part") from exc


def _safe_xml(data: bytes, *, max_cells: int = MAX_CELLS) -> ET.Element:
    _refuse_declarations(data, max_cells=max_cells)
    try:
        return ET.fromstring(data)
    except (ET.ParseError, LookupError, ValueError) as exc:
        raise WorkbookError("unsupported or malformed XML part") from exc


class _Archive:
    def __init__(self, data: bytes):
        if len(data) > MAX_ARCHIVE_BYTES:
            raise WorkbookError("workbook too large")
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
            infos = self.zip.infolist()
        except _ARCHIVE_ERRORS as exc:
            raise WorkbookError("not a readable OOXML zip archive") from exc
        if len(infos) > MAX_MEMBERS:
            raise WorkbookError("too many archive members")
        total = 0
        self.names = set()
        for info in infos:
            name = info.filename
            if name in self.names:
                raise WorkbookError("duplicate archive member")
            if name.startswith("/") or "\\" in name or ".." in name.split("/"):
                raise WorkbookError("unsafe archive member name")
            if info.file_size > MAX_PART_BYTES:
                raise WorkbookError("archive member too large")
            total += info.file_size
            self.names.add(name)
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise WorkbookError("archive expands too far")
        self.read_bytes = 0

    def read(self, name: str) -> bytes:
        if name not in self.names:
            raise WorkbookError("required workbook part missing")
        try:
            with self.zip.open(name) as handle:
                data = handle.read(MAX_PART_BYTES + 1)
        except _ARCHIVE_ERRORS as exc:
            raise WorkbookError("corrupt or unsupported archive member") from exc
        if len(data) > MAX_PART_BYTES:
            raise WorkbookError("archive member too large")
        # Declared sizes can lie; bound what is actually decompressed as well.
        self.read_bytes += len(data)
        if self.read_bytes > MAX_TOTAL_UNCOMPRESSED:
            raise WorkbookError("archive expands too far")
        return data


def _text_of(element: ET.Element | None) -> str | None:
    """openpyxl's rich-text content: the plain run plus every formatted run, no phonetics."""
    if element is None:
        return None
    direct = element.findall(f"{{{MAIN_NS}}}t")
    if len(direct) > 1:
        raise WorkbookError("ambiguous rich-text string")
    parts = [direct[0].text or ""] if direct else []
    for run in element.findall(f"{{{MAIN_NS}}}r"):
        text = run.find(f"{{{MAIN_NS}}}t")
        if text is not None:
            parts.append(text.text or "")
    return "".join(parts)


def _resolve(base: str, target: str) -> str:
    if target.startswith("/"):
        resolved = posixpath.normpath(target.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    if resolved == ".." or resolved.startswith("../"):
        raise WorkbookError("relationship target outside the package")
    return resolved


def _relationships(archive: _Archive, part: str) -> list[tuple[str, str, str]]:
    rels_part = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rels_part not in archive.names:
        return []
    result, identities = [], set()
    root = _safe_xml(archive.read(rels_part))
    if root.tag != f"{{{PKG_REL_NS}}}Relationships":
        raise WorkbookError("unsupported relationships namespace")
    for rel in root.findall(f"{{{PKG_REL_NS}}}Relationship"):
        identity = rel.get("Id")
        if not identity or identity in identities:
            raise WorkbookError("duplicate or missing relationship identity")
        identities.add(identity)
        if rel.get("TargetMode") == "External":
            continue
        if not rel.get("Target"):
            raise WorkbookError("missing relationship target")
        result.append((rel.get("Id", ""), rel.get("Type", ""), _resolve(part, rel.get("Target", ""))))
    return result


def read_workbook(data: bytes, *, max_cells: int = MAX_CELLS) -> Workbook:
    """Parse a workbook's sheets, styles and strings without evaluating anything."""
    if type(max_cells) is not int or not 1 <= max_cells <= MAX_CELLS:
        raise WorkbookError("invalid stored-cell budget")
    archive = _Archive(data)
    office = [target for _, kind, target in _relationships(archive, "")
              if kind == REL_TYPES["office_document"]]
    if len(office) > 1:
        raise WorkbookError("ambiguous workbook relationship")
    workbook_part = office[0] if office else "xl/workbook.xml"
    workbook_xml = _safe_xml(archive.read(workbook_part))
    if workbook_xml.tag != f"{{{MAIN_NS}}}workbook":
        raise WorkbookError("unsupported workbook namespace")
    properties = workbook_xml.find(f"{{{MAIN_NS}}}workbookPr")
    flag = (properties.get("date1904") if properties is not None else None) or "false"
    if flag not in ("0", "1", "true", "false"):
        raise WorkbookError("invalid date1904 flag")
    epoch = MAC_EPOCH if flag in ("1", "true") else WINDOWS_EPOCH

    rels = _relationships(archive, workbook_part)
    for kind in (REL_TYPES["shared_strings"], REL_TYPES["styles"]):
        if sum(relationship_kind == kind for _, relationship_kind, _ in rels) > 1:
            raise WorkbookError("ambiguous workbook metadata relationship")
    by_id = {rel_id: (kind, target) for rel_id, kind, target in rels}

    strings: list[str] = []
    for _, kind, target in rels:
        if kind == REL_TYPES["shared_strings"]:
            strings_xml = _safe_xml(archive.read(target))
            if strings_xml.tag != f"{{{MAIN_NS}}}sst":
                raise WorkbookError("unsupported shared strings namespace")
            for item in strings_xml.findall(f"{{{MAIN_NS}}}si"):
                # openpyxl reader/strings.py removes Excel's escape for a literal underscore.
                strings.append((_text_of(item) or "").replace("x005F_", ""))

    formats = dict(BUILTIN_FORMATS)
    xf_formats: list[str] = []
    for _, kind, target in rels:
        if kind != REL_TYPES["styles"]:
            continue
        styles_xml = _safe_xml(archive.read(target))
        if styles_xml.tag != f"{{{MAIN_NS}}}styleSheet":
            raise WorkbookError("unsupported styles namespace")
        # Only the top-level list: <dxfs> conditional formats may reuse the same ids.
        numfmts = styles_xml.find(f"{{{MAIN_NS}}}numFmts")
        for numfmt in (numfmts.findall(f"{{{MAIN_NS}}}numFmt") if numfmts is not None else []):
            formats[_int(numfmt.get("numFmtId"), "number format id")] = numfmt.get("formatCode", "")
        cell_xfs = styles_xml.find(f"{{{MAIN_NS}}}cellXfs")
        for xf in (cell_xfs.findall(f"{{{MAIN_NS}}}xf") if cell_xfs is not None else []):
            xf_formats.append(formats.get(_int(xf.get("numFmtId", "0"), "number format id"), "General"))

    sheets = []
    total_cells = 0
    sheets_xml = workbook_xml.find(f"{{{MAIN_NS}}}sheets")
    for entry in (sheets_xml if sheets_xml is not None else []):
        kind, part = by_id.get(entry.get(f"{{{DOC_REL_NS}}}id"), (None, None))
        name, state = entry.get("name", ""), entry.get("state", "visible")
        if kind == REL_TYPES["chartsheet"]:
            raw = archive.read(part)
            if _safe_xml(raw).tag != f"{{{MAIN_NS}}}chartsheet":
                raise WorkbookError("unsupported chartsheet namespace")
            sheets.append(Sheet(name, state, "chartsheet", part, hashlib.sha256(raw).hexdigest(), {}))
            continue
        if kind != REL_TYPES["worksheet"]:
            raise WorkbookError("sheet relationship missing or unsupported")
        raw = archive.read(part)
        root = _safe_xml(raw, max_cells=max_cells - total_cells)
        if root.tag != f"{{{MAIN_NS}}}worksheet":
            raise WorkbookError("unsupported worksheet namespace")
        cells = _read_cells(root, strings, xf_formats, epoch, max_cells=max_cells - total_cells)
        total_cells += len(cells)
        if total_cells > max_cells:
            raise WorkbookError("too many cells")
        merged = root.find(f"{{{MAIN_NS}}}mergeCells")
        ranges = tuple(item.get("ref", "") for item in
                       (merged.findall(f"{{{MAIN_NS}}}mergeCell") if merged is not None else []))
        sheets.append(Sheet(name, state, "worksheet", part, hashlib.sha256(raw).hexdigest(), cells,
                            ranges))
    if len({sheet.name.casefold() for sheet in sheets}) != len(sheets):
        raise WorkbookError("duplicate sheet names")
    return Workbook(hashlib.sha256(data).hexdigest(), len(data), epoch == MAC_EPOCH, tuple(sheets))


def _read_cells(root: ET.Element, strings: list[str], xf_formats: list[str],
                epoch: datetime, *, max_cells: int = MAX_CELLS) -> dict[tuple[int, int], Cell]:
    cells: dict[tuple[int, int], Cell] = {}
    data = root.find(f"{{{MAIN_NS}}}sheetData")
    if data is None:
        return cells
    for row in data.findall(f"{{{MAIN_NS}}}row"):
        for element in row.findall(f"{{{MAIN_NS}}}c"):
            if len(cells) >= max_cells:
                raise WorkbookError("stored-cell budget exceeded")
            ref = element.get("r")
            if not ref:
                raise WorkbookError("cell without reference is not supported")
            row_index, column = split_ref(ref)
            if (row_index, column) in cells:
                raise WorkbookError("duplicate cell reference")
            canonical = f"{column_letters(column)}{row_index}"
            cells[(row_index, column)] = _parse_cell(element, canonical, row_index, column, strings,
                                                     xf_formats, epoch)
    return cells


def _parse_cell(element, ref, row, column, strings, xf_formats, epoch) -> Cell:
    ooxml_type = element.get("t")
    scalar = element.findall(f"{{{MAIN_NS}}}v")
    formulas = element.findall(f"{{{MAIN_NS}}}f")
    inline = element.findall(f"{{{MAIN_NS}}}is")
    if len(scalar) > 1 or len(formulas) > 1 or len(inline) > 1:
        raise WorkbookError("ambiguous cell payload")
    if inline and ooxml_type != "inlineStr" or ooxml_type == "inlineStr" and (scalar or formulas):
        raise WorkbookError("conflicting cell payload types")
    excel_type = ooxml_type or "n"
    style = _int(element.get("s", "0") or "0", "style index")
    if style < 0 or (style >= len(xf_formats) and style != 0):
        raise WorkbookError("style index out of range")
    number_format = xf_formats[style] if style < len(xf_formats) else "General"
    raw_text = element.findtext(f"{{{MAIN_NS}}}v")
    value_text = None if excel_type == "inlineStr" else (raw_text or None)
    formula_element = element.find(f"{{{MAIN_NS}}}f")
    if formula_element is not None:
        if formula_element.get("t") in ("shared", "array", "dataTable"):
            raise WorkbookError("shared, array and data-table formulas are not supported")
        formula = "=" + (formula_element.text or "")
        cached = raw_text
        if ooxml_type == "s" and raw_text:
            index = _int(raw_text, "shared string index")
            if not 0 <= index < len(strings):
                raise WorkbookError("shared string index out of range")
            cached = strings[index]
        return Cell(ref, row, column, formula, "f", number_format, ooxml_type, raw_text,
                    formula=formula, cached_text=cached)
    value: object = value_text
    if value_text is not None:
        if excel_type == "n":
            value = _cast_number(value_text)
            if is_date_format(number_format):
                if is_elapsed_format(number_format):
                    raise WorkbookError("elapsed-time number formats are not supported")
                try:
                    value = _from_excel(value, epoch)
                    excel_type = "d"
                except (OverflowError, ValueError):
                    # openpyxl 3.1.5 turns an out-of-range date serial into an error cell.
                    value, excel_type = "#VALUE!", "e"
        elif excel_type == "s":
            index = _int(value_text, "shared string index")
            if not 0 <= index < len(strings):
                raise WorkbookError("shared string index out of range")
            value = strings[index]
        elif excel_type == "b":
            if value_text not in ("0", "1"):
                raise WorkbookError("invalid boolean cell")
            value = value_text == "1"
        elif excel_type == "str":
            excel_type = "s"
        elif excel_type == "d":
            raise WorkbookError("ISO date cells are not supported")
        elif excel_type != "e":
            raise WorkbookError("unsupported cell type")
    elif excel_type == "inlineStr":
        inline = element.find(f"{{{MAIN_NS}}}is")
        if inline is not None:
            excel_type = "s"
            value = _text_of(inline)
    return Cell(ref, row, column, value, excel_type, number_format, ooxml_type, raw_text)
