import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from scripts.build_native_company_template import build, load, q, strings, value


NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def make_template(path):
    """Minimal synthetic OOXML fixture; no customer workbook is used."""
    parts = {
        "xl/workbook.xml": f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="data" sheetId="1" r:id="rId1"/><sheet name="Dictionaries" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst xmlns="{NS}" count="3" uniqueCount="3"><si><t>COMPANY_NAME</t></si><si><t>ZIP</t></si><si><t>Sample</t></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{NS}"><dimension ref="A1:B2"/><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2" ht="20" customHeight="1"><c r="A2" s="1" t="s"><v>2</v></c><c r="B2" s="2"/></row></sheetData><dataValidations count="1"><dataValidation type="textLength" sqref="B2:B100"><formula1>5</formula1></dataValidation></dataValidations></worksheet>',
        "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{NS}"><sheetData/></worksheet>',
        "xl/styles.xml": f'<styleSheet xmlns="{NS}"/>',
        "docProps/custom.xml": "<properties><example>synthetic</example></properties>",
    }
    with ZipFile(path, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


class NativeTemplateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.template = Path(self.directory.name) / "template.xlsx"
        self.output = Path(self.directory.name) / "result.xlsx"
        make_template(self.template)

    def test_preserves_untouched_parts_and_text_zip(self):
        records = [
            {"COMPANY_NAME": "Example & Sons LLC", "ZIP": "00123"},
            {"COMPANY_NAME": "=Literal text", "ZIP": "00456"},
        ]
        before = load(self.template)
        build(self.template, self.output, records, "data")
        after = load(self.output)
        self.assertEqual(set(before), set(after))
        for name in before.keys() - {
            "xl/worksheets/sheet1.xml",
            "xl/sharedStrings.xml",
        }:
            self.assertEqual(before[name], after[name], name)
        _, shared = strings(after)
        sheet = ET.fromstring(after["xl/worksheets/sheet1.xml"])
        rows = sheet.find(q("sheetData")).findall(q("row"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(value(rows[1].findall(q("c"))[1], shared), "00123")
        self.assertEqual(value(rows[2].findall(q("c"))[0], shared), "=Literal text")
        self.assertIsNone(rows[2].findall(q("c"))[0].find(q("f")))
        self.assertEqual(rows[2].findall(q("c"))[1].get("s"), "2")
        self.assertEqual(rows[2].get("ht"), "20")
        self.assertEqual(sheet.find(q("dataValidations"))[0].get("sqref"), "B2:B100")
        self.assertEqual(sheet.find(q("dimension")).get("ref"), "A1:B3")
        self.assertEqual(load(self.template), before)
        with ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                if name.endswith(".xml"):
                    ET.fromstring(archive.read(name))

    def test_rejects_unknown_header_in_later_record(self):
        with self.assertRaisesRegex(ValueError, "Missing template headers"):
            build(
                self.template, self.output, [{"ZIP": "00123"}, {"UNKNOWN": "x"}], "data"
            )
        self.assertFalse(self.output.exists())

    def test_rejects_empty_and_non_text_records(self):
        for records in ([], [{"ZIP": 123}]):
            with self.assertRaises(ValueError):
                build(self.template, self.output, records, "data")

    def test_does_not_overwrite_source_template(self):
        before = self.template.read_bytes()
        with self.assertRaisesRegex(ValueError, "differ"):
            build(self.template, self.template, [{"ZIP": "00123"}], "data")
        self.assertEqual(self.template.read_bytes(), before)
