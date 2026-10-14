"""Fresh invented packages for generic reader changes; no registered source data."""
import io
import unittest
import zipfile

from test_tabular_import_v3 import invented_book, extract
from compute_pricing.control.ingest.xlsx import DOC_REL_NS, MAIN_NS, WorkbookError, read_workbook


def package(parts):
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(invented_book())) as source, zipfile.ZipFile(stream, "w") as target:
        for name in source.namelist():
            target.writestr(name, parts.get(name, source.read(name)))
        for name, content in parts.items():
            if name not in source.namelist():
                target.writestr(name, content)
    return stream.getvalue()


class ReaderV4Tests(unittest.TestCase):
    def test_unknown_or_unsupported_xml_codecs_refuse_without_crashing(self):
        for codec in ("x-invented-codec", "rot13", "shift_jis"):
            with self.subTest(codec=codec), self.assertRaises(WorkbookError):
                read_workbook(invented_book(sheet_xml=f'<?xml version="1.0" encoding="{codec}"?><worksheet xmlns="{MAIN_NS}"><sheetData/></worksheet>'))

    def test_cell_reference_must_match_the_entire_string(self):
        for reference in ("A2&#10;", "A2 trailing"):
            with self.subTest(reference=reference), self.assertRaisesRegex(WorkbookError, "cell reference"):
                read_workbook(invented_book(cells=f'<row r="2"><c r="{reference}"><v>7</v></c></row>'))

    def test_case_insensitive_sheet_identity_collision_refuses(self):
        with zipfile.ZipFile(io.BytesIO(invented_book())) as source:
            workbook = source.read("xl/workbook.xml").replace(b'</sheets>', b'<sheet name="INVENTED TABLE" sheetId="2" r:id="r1"/></sheets>')
        with self.assertRaisesRegex(WorkbookError, "duplicate sheet names"):
            read_workbook(package({"xl/workbook.xml": workbook}))

    def test_shared_string_formula_cache_is_text_and_stays_unqualified(self):
        with zipfile.ZipFile(io.BytesIO(invented_book())) as source:
            rels = source.read("xl/_rels/workbook.xml.rels").replace(b'</Relationships>', f'<Relationship Id="cache" Type="{DOC_REL_NS}/sharedStrings" Target="strings.xml"/></Relationships>'.encode())
        worksheet = f'<worksheet xmlns="{MAIN_NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Claimed value</t></is></c></row><row r="2"><c r="A2" t="s"><f>"invented cache"</f><v>0</v></c></row></sheetData></worksheet>'
        parts = {"xl/_rels/workbook.xml.rels": rels, "xl/strings.xml": f'<sst xmlns="{MAIN_NS}"><si><t>Invented unresolved cache</t></si></sst>', "xl/worksheets/sheet1.xml": worksheet}
        report = extract(package(parts))["content"]
        cell = report["rows"][0]["cells"]["column:A"]
        self.assertEqual(cell["cached_text"], "Invented unresolved cache")
        self.assertIsNone(cell["value"])
        self.assertEqual(report["permissions"]["benchmark"], "FAIL")
        parts["xl/worksheets/sheet1.xml"] = worksheet.replace('<v>0</v>', '<v>4</v>')
        with self.assertRaisesRegex(WorkbookError, "shared string index"):
            read_workbook(package(parts))


if __name__ == "__main__":
    unittest.main()
