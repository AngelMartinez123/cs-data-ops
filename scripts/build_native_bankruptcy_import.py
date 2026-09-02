from __future__ import annotations

import argparse
import csv
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"x": MAIN}
DATE_HEADERS = {"FILING_DATE", "RELEASE_DATE", "SCH_341_DATE", "DATE_RECORD_UPLOADED", "POCDATE"}
TEXT_OVERRIDES = {"FILING_TYPES", "SCH_341_TIME"}


def column(ref: str) -> str:
    return re.match(r"[A-Z]+", ref).group(0)


def colnum(value: str) -> int:
    number = 0
    for char in value:
        number = number * 26 + ord(char) - 64
    return number


def excel_serial(value: str) -> str:
    parsed = datetime.strptime(value[:10], "%Y-%m-%d")
    epoch = datetime(1899, 12, 30)
    return str((parsed - epoch).days)


def shared_string_values(root) -> list[str]:
    return ["".join(node.itertext()) for node in root.xpath("x:si", namespaces=NS)]


def build(template: Path, source_csv: Path, output: Path) -> None:
    with ZipFile(template) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}

    sheet_path = "xl/worksheets/sheet1.xml"
    shared_path = "xl/sharedStrings.xml"
    parser = ET.XMLParser(remove_blank_text=False)
    sheet = ET.fromstring(parts[sheet_path], parser)
    shared = ET.fromstring(parts[shared_path], parser)
    rows = sheet.xpath("x:sheetData/x:row", namespaces=NS)
    if len(rows) < 2:
        raise ValueError("Bankruptcy template must contain a header and formatted sample row")

    existing_strings = shared_string_values(shared)
    string_index = {value: index for index, value in enumerate(existing_strings)}

    def add_string(value: str) -> int:
        if value in string_index:
            return string_index[value]
        index = len(existing_strings)
        existing_strings.append(value)
        string_index[value] = index
        si = ET.SubElement(shared, f"{{{MAIN}}}si")
        text = ET.SubElement(si, f"{{{MAIN}}}t")
        if value.startswith(" ") or value.endswith(" "):
            text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = value
        return index

    header_row, sample_row = rows[0], rows[1]
    headers = {}
    for cell in header_row.xpath("x:c", namespaces=NS):
        ref = cell.get("r")
        value_node = cell.find(f"{{{MAIN}}}v")
        if value_node is None:
            continue
        headers[column(ref)] = existing_strings[int(value_node.text)]
    expected = list(headers.values())
    with source_csv.open(newline="", encoding="utf-8-sig") as handle:
        records = list(csv.DictReader(handle))
    source_headers = [header.upper() for header in (records[0].keys() if records else [])]
    if source_headers != expected[: len(source_headers)]:
        raise ValueError(f"CSV headers do not match bankruptcy template: {source_headers} != {expected[:len(source_headers)]}")
    for record in records:
        record["POCDATE"] = record.pop("pocdate", record.get("POCDATE", ""))
        record.setdefault("DELETED_BY_IMPORT", "")
        record.setdefault("DELETED_BY_EDITING_TOOL", "")

    sheet_data = sheet.find(f"{{{MAIN}}}sheetData")
    for row in rows[1:]:
        sheet_data.remove(row)
    sample_cells = {column(cell.get("r")): cell for cell in sample_row.xpath("x:c", namespaces=NS)}

    for row_number, record in enumerate(records, start=2):
        new_row = deepcopy(sample_row)
        new_row.set("r", str(row_number))
        new_row.set("spans", "1:40")
        cells = {column(cell.get("r")): cell for cell in new_row.xpath("x:c", namespaces=NS)}
        for cell in cells.values():
            letter = column(cell.get("r"))
            cell.set("r", f"{letter}{row_number}")
            for child in list(cell):
                cell.remove(child)
            cell.attrib.pop("t", None)

        for letter, header in headers.items():
            value = str(record.get(header, "") or "").strip()
            cell = cells.get(letter)
            if cell is None:
                cell = ET.Element(f"{{{MAIN}}}c", r=f"{letter}{row_number}")
                cells[letter] = cell
                if header in DATE_HEADERS:
                    cell.set("s", "3")
            if not value:
                continue
            sample = sample_cells.get(letter)
            sample_is_text = sample is not None and sample.get("t") == "s"
            is_date = header in DATE_HEADERS
            is_text = sample_is_text or header in TEXT_OVERRIDES
            if is_date:
                cell.set("s", "3")
                numeric = excel_serial(value)
                ET.SubElement(cell, f"{{{MAIN}}}v").text = numeric
            elif is_text or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
                cell.set("t", "s")
                ET.SubElement(cell, f"{{{MAIN}}}v").text = str(add_string(value))
            else:
                ET.SubElement(cell, f"{{{MAIN}}}v").text = value

        for cell in list(new_row.xpath("x:c", namespaces=NS)):
            new_row.remove(cell)
        for cell in sorted(cells.values(), key=lambda item: colnum(column(item.get("r")))):
            new_row.append(cell)
        sheet_data.append(new_row)

    dimension = sheet.find(f"{{{MAIN}}}dimension")
    dimension.set("ref", f"A1:AN{len(records) + 1}")
    shared.set("count", str(len(existing_strings)))
    shared.set("uniqueCount", str(len(existing_strings)))
    parts[sheet_path] = ET.tostring(sheet, xml_declaration=True, encoding="UTF-8", standalone=True)
    parts[shared_path] = ET.tostring(shared, xml_declaration=True, encoding="UTF-8", standalone=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(delete=False, suffix=".xlsx", dir=output.parent) as handle:
        temp = Path(handle.name)
    with ZipFile(temp, "w", ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    with ZipFile(temp) as archive:
        if archive.testzip() is not None:
            raise ValueError("Generated XLSX package failed ZIP integrity validation")
        ET.fromstring(archive.read(sheet_path))
        ET.fromstring(archive.read(shared_path))
    temp.replace(output)
    print(f"BANKRUPTCY_ROWS={len(records)}")
    print(output.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.template, args.csv, args.output)


if __name__ == "__main__":
    main()
