"""Independent invented OOXML tables; no registered fixtures or counterparties."""
import io
from pathlib import Path
import sys
import unittest
import warnings
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.ingest.tabular import extract_table
from compute_pricing.control.ingest.xlsx import MAIN_NS, DOC_REL_NS, PKG_REL_NS, WorkbookError, read_workbook


def invented_book(*, cells=None, relationships=None, duplicate_member=False, root_relationships=None, sheet_xml=None):
    if cells is None:
        cells = '<row r="1"><c r="A1" t="inlineStr"><is><t>Machine</t></is></c><c r="B1" t="inlineStr"><is><t>Rate declared</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Invented accelerator</t></is></c><c r="B2"><v>0.123456789012345678901234567890</v></c></row>'
    relationship = f'<Relationship Id="r1" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}"><sheets><sheet name="Invented table" sheetId="1" r:id="r1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{PKG_REL_NS}">{relationships if relationships is not None else relationship}</Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml', sheet_xml if sheet_xml is not None else f'<worksheet xmlns="{MAIN_NS}"><sheetData>{cells}</sheetData></worksheet>')
        if root_relationships is not None:
            archive.writestr('_rels/.rels', f'<Relationships xmlns="{PKG_REL_NS}">{root_relationships}</Relationships>')
        if duplicate_member:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr('xl/workbook.xml', 'shadow')
    return stream.getvalue()


def extract(data=None, **options):
    return extract_table(invented_book() if data is None else data, sheet_name='Invented table', header_row=1, **options)


class TabularImportV3Tests(unittest.TestCase):
    def test_exact_decimal_is_not_a_float_round_trip(self):
        result = extract()['content']
        self.assertEqual(result['rows'][0]['cells']['column:B']['value'], '0.123456789012345678901234567890')
        self.assertEqual(result['rows'][0]['cells']['column:B']['kind'], 'decimal_text')
        self.assertEqual(result['columns'][1]['label'], 'Rate declared')
        self.assertEqual(result['rows'][0]['cells']['column:B']['cell'], 'B2')

    def test_table_retains_new_labels_unheaded_data_blank_zero_and_boolean(self):
        cells = '<row r="1"><c r="A1" t="inlineStr"><is><t>New attribute</t></is></c></row><row r="3"><c r="B3"><v>0</v></c><c r="C3" t="b"><v>0</v></c></row>'
        content = extract(invented_book(cells=cells))['content']
        self.assertEqual([column['label'] for column in content['columns']], ['New attribute', None, None])
        self.assertIsNone(content['rows'][0]['cells']['column:A']['value'])
        self.assertEqual(content['rows'][0]['cells']['column:B']['value'], '0')
        self.assertIs(content['rows'][0]['cells']['column:C']['value'], False)
        self.assertEqual(content['rows'][0]['source_row'], 3)
        self.assertIn('unheaded_column_retained:B', content['warnings'])

    def test_formulas_are_separate_from_unqualified_caches(self):
        cells = '<row r="1"><c r="A1" t="inlineStr"><is><t>Estimate</t></is></c></row><row r="2"><c r="A2"><f>1+2</f><v>999</v></c></row>'
        content = extract(invented_book(cells=cells))['content']
        cell = content['rows'][0]['cells']['column:A']
        self.assertEqual(cell['formula'], '=1+2')
        self.assertEqual(cell['cached_text'], '999')
        self.assertIsNone(cell['value'])
        self.assertFalse(content['execution_enabled'])
        self.assertEqual(content['permissions']['benchmark'], 'FAIL')
        self.assertEqual(content['permissions']['execution'], 'FAIL')
        self.assertEqual(content['permissions']['retain'], 'UNKNOWN')

    def test_duplicates_or_nontext_headers_refuse_without_values(self):
        for headers in ('<c r="A1" t="inlineStr"><is><t>Secret invented label</t></is></c><c r="B1" t="inlineStr"><is><t>Secret invented label</t></is></c>', '<c r="A1"><v>314159</v></c>', '<c r="A1"><f>1+1</f><v>2</v></c>'):
            with self.assertRaises(WorkbookError) as caught:
                extract(invented_book(cells='<row r="1">'+headers+'</row>'))
            self.assertNotIn('Secret invented label', str(caught.exception))
            self.assertNotIn('314159', str(caught.exception))

    def test_table_limits_refuse_instead_of_silently_truncating(self):
        with self.assertRaises(WorkbookError):
            extract(max_columns=1)
        cells = '<row r="1"><c r="A1" t="inlineStr"><is><t>Label</t></is></c></row><row r="2"><c r="A2"><v>1</v></c></row><row r="4"><c r="A4"><v>2</v></c></row>'
        with self.assertRaises(WorkbookError):
            extract(invented_book(cells=cells), max_rows=1)

    def test_selection_and_budget_arguments_are_explicit(self):
        for options in ({'header_row': True}, {'header_row': 0}, {'header_row': 1048576}, {'max_rows': True}, {'max_rows': 10001}, {'max_columns': 513}, {'sheet_name': 'missing'}):
            settings = {'sheet_name': 'Invented table', 'header_row': 1, **options}
            with self.assertRaises(WorkbookError):
                extract_table(invented_book(), **settings)

    def test_reimport_is_deterministic_and_independent(self):
        data = invented_book()
        first, second = extract(data), extract(data)
        self.assertEqual(first, second)
        first['content']['rows'][0]['cells']['column:B']['value'] = 'changed'
        self.assertEqual(extract(data), second)

    def test_empty_selected_table_does_not_invent_records(self):
        content = extract(invented_book(cells=''))['content']
        self.assertEqual(content['row_count'], 0)
        self.assertEqual(content['columns'], [])

    def test_duplicate_archive_members_refused(self):
        with self.assertRaisesRegex(WorkbookError, 'duplicate archive member'):
            extract(invented_book(duplicate_member=True))

    def test_ambiguous_relationship_identity_refused(self):
        relationship = f'<Relationship Id="r1" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
        with self.assertRaisesRegex(WorkbookError, 'relationship identity'):
            extract(invented_book(relationships=relationship+relationship))

    def test_multiple_workbook_roots_refused(self):
        relationships = ''.join(f'<Relationship Id="r{index}" Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/>' for index in (1,2))
        with self.assertRaisesRegex(WorkbookError, 'ambiguous workbook relationship'):
            extract(invented_book(root_relationships=relationships))

    def test_ambiguous_metadata_parts_refused(self):
        relationship = f'<Relationship Id="r1" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
        for kind in ('styles','sharedStrings'):
            extras = ''.join(f'<Relationship Id="r{index}" Type="{DOC_REL_NS}/{kind}" Target="unused{index}.xml"/>' for index in (2,3))
            with self.assertRaisesRegex(WorkbookError, 'ambiguous workbook metadata relationship'):
                extract(invented_book(relationships=relationship+extras))

    def test_xml_entity_declarations_refused_in_utf16(self):
        text = f'<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE worksheet [<!ENTITY private "invented">]><worksheet xmlns="{MAIN_NS}"><sheetData/></worksheet>'
        with self.assertRaisesRegex(WorkbookError, 'declarations'):
            extract(invented_book(sheet_xml=text.encode('utf-16')))

    def test_wrong_worksheet_root_refused(self):
        with self.assertRaisesRegex(WorkbookError, 'worksheet namespace'):
            extract(invented_book(sheet_xml=f'<unrelated xmlns="{MAIN_NS}"><sheetData/></unrelated>'))

    def test_metadata_relationship_roots_are_checked(self):
        for kind, wrong, message in (('styles', 'notStyles', 'styles namespace'), ('sharedStrings', 'notStrings', 'shared strings namespace')):
            base = invented_book(relationships=f'<Relationship Id="r1" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Type="{DOC_REL_NS}/{kind}" Target="meta.xml"/>')
            stream = io.BytesIO(base)
            with zipfile.ZipFile(stream, 'a') as archive:
                archive.writestr('xl/meta.xml', f'<{wrong} xmlns="{MAIN_NS}"/>')
            with self.assertRaisesRegex(WorkbookError, message):
                extract(stream.getvalue())

    def test_cell_budget_applies_before_element_tree_allocation(self):
        from compute_pricing.control.ingest import xlsx
        original = xlsx.ET.fromstring
        calls = []
        def parse(data):
            calls.append(data)
            return original(data)
        with patch.object(xlsx.ET, 'fromstring', side_effect=parse):
            with self.assertRaisesRegex(WorkbookError, 'budget exceeded'):
                read_workbook(invented_book(), max_cells=1)
        self.assertFalse(any(b'<worksheet' in data for data in calls))

    def test_cumulative_cell_budget_covers_other_sheets(self):
        base = invented_book()
        stream = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(base)) as source, zipfile.ZipFile(stream, 'w') as target:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename == 'xl/workbook.xml':
                    data = data.replace(b'</sheets>', b'<sheet name="Other invented sheet" sheetId="2" r:id="r2"/></sheets>')
                elif entry.filename == 'xl/_rels/workbook.xml.rels':
                    extra = f'<Relationship Id="r2" Type="{DOC_REL_NS}/worksheet" Target="worksheets/second.xml"/>'.encode()
                    data = data.replace(b'</Relationships>', extra+b'</Relationships>')
                target.writestr(entry.filename, data)
            target.writestr('xl/worksheets/second.xml', f'<worksheet xmlns="{MAIN_NS}"><sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>')
        with self.assertRaisesRegex(WorkbookError, 'budget exceeded'):
            read_workbook(stream.getvalue(), max_cells=4)

    def test_noncell_xml_element_budget_is_independent(self):
        from compute_pricing.control.ingest import xlsx
        with patch.object(xlsx, 'MAX_XML_ELEMENTS', 4):
            with self.assertRaisesRegex(WorkbookError, 'budget exceeded'):
                extract()

    def test_conflicting_stored_cell_payloads_are_not_silently_selected(self):
        for content in ('<v>1</v><v>999</v>', '<f>1+1</f><f>9+9</f>', '<is><t>invented</t></is><v>1</v>'):
            with self.assertRaisesRegex(WorkbookError, 'cell payload'):
                extract(invented_book(cells='<row r="2"><c r="A2">'+content+'</c></row>'))
        with self.assertRaisesRegex(WorkbookError, 'cell payload'):
            extract(invented_book(cells='<row r="2"><c r="A2" t="inlineStr"><is><t>invented</t></is><v>1</v></c></row>'))

    def test_repeated_shared_strings_cannot_expand_unbounded_output(self):
        from compute_pricing.control.ingest import tabular
        base = invented_book(relationships=f'<Relationship Id="r1" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Type="{DOC_REL_NS}/sharedStrings" Target="strings.xml"/>', cells='<row r="1"><c r="A1" t="inlineStr"><is><t>Payload</t></is></c></row>'+''.join(f'<row r="{row}"><c r="A{row}" t="s"><v>0</v></c></row>' for row in range(2,7)))
        stream = io.BytesIO(base)
        with zipfile.ZipFile(stream, 'a') as archive:
            archive.writestr('xl/strings.xml', f'<sst xmlns="{MAIN_NS}"><si><t>{"x"*1024}</t></si></sst>')
        with patch.object(tabular, 'MAX_TABLE_BYTES', 2048):
            with self.assertRaisesRegex(WorkbookError, 'byte budget'):
                extract(stream.getvalue())

    def test_long_cell_text_refuses_before_large_serialization(self):
        from compute_pricing.control.ingest import tabular
        with patch.object(tabular, 'MAX_CELL_TEXT', 5):
            with self.assertRaisesRegex(WorkbookError, 'cell text budget'):
                extract()

    def test_final_byte_budget_includes_noncell_metadata(self):
        from compute_pricing.control.ingest import tabular
        xml = f'<worksheet xmlns="{MAIN_NS}"><sheetData/><mergeCells>'+''.join('<mergeCell ref="A1:B1048576"/>' for _ in range(300))+'</mergeCells></worksheet>'
        with patch.object(tabular, 'MAX_TABLE_BYTES', 1024):
            with self.assertRaisesRegex(WorkbookError, 'byte budget'):
                extract(invented_book(sheet_xml=xml))


if __name__ == '__main__':
    unittest.main()
