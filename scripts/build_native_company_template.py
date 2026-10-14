from __future__ import annotations
import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
ET.register_namespace("", M)


def q(name):
    return f"{{{M}}}{name}"


def col(reference):
    return re.match(r"[A-Z]+", reference).group(0)


def colnum(s):
    n = 0
    for c in s:
        n = n * 26 + ord(c) - 64
    return n


def load(path):
    with ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def sheet_path(parts, name):
    wb = ET.fromstring(parts["xl/workbook.xml"])
    node = next((x for x in wb.find(q("sheets")) if x.get("name") == name), None)
    if node is None:
        raise ValueError(f"Worksheet not found: {name}")
    rid = node.get(f"{{{R}}}id")
    rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    target = next(x.get("Target") for x in rels if x.get("Id") == rid).lstrip("/")
    return target if target.startswith("xl/") else "xl/" + target


def strings(parts):
    root = ET.fromstring(parts["xl/sharedStrings.xml"])
    vals = [
        "".join(t.text or "" for t in si.iter(q("t"))) for si in root.findall(q("si"))
    ]
    return root, vals


def value(cell, ss):
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q("t")))
    v = cell.find(q("v"))
    if v is None or v.text is None:
        return ""
    return ss[int(v.text)] if cell.get("t") == "s" else v.text


def clear_contents(cell):
    for child in list(cell):
        cell.remove(child)


def build(template, output, records, data_sheet):
    if not records:
        raise ValueError("At least one record is required")
    if any(not isinstance(v, str) for record in records for v in record.values()):
        raise ValueError("Record values must be strings")
    if template.resolve() == output.resolve():
        raise ValueError("Output must differ from the template")
    parts = load(template)
    sp = sheet_path(parts, data_sheet)
    root = ET.fromstring(parts[sp])
    sd = root.find(q("sheetData"))
    rows = sd.findall(q("row"))
    if len(rows) < 2:
        raise ValueError("Template needs header and sample row")
    header, sample = rows[0], rows[1]
    shared, ss = strings(parts)
    headers = {value(c, ss).strip(): col(c.get("r")) for c in header.findall(q("c"))}
    unknown = set().union(*(set(record) for record in records)) - set(headers)
    if unknown:
        raise ValueError(f"Missing template headers: {sorted(unknown)}")
    for row in rows[1:]:
        sd.remove(row)

    def add_s(text):
        ss.append(text)
        si = ET.SubElement(shared, q("si"))
        ET.SubElement(
            si, q("t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
        ).text = text
        return len(ss) - 1

    for rn, record in enumerate(records, 2):
        row = deepcopy(sample)
        row.set("r", str(rn))
        cells = {}
        for c in row.findall(q("c")):
            letter = col(c.get("r"))
            c.set("r", f"{letter}{rn}")
            clear_contents(c)
            c.attrib.pop("t", None)
            cells[letter] = c
        for head, text in record.items():
            letter = headers[head]
            c = cells.get(letter)
            if c is None:
                c = ET.SubElement(row, q("c"), {"r": f"{letter}{rn}"})
                cells[letter] = c
            c.set("t", "s")
            ET.SubElement(c, q("v")).text = str(add_s(text))
        for c in list(row.findall(q("c"))):
            row.remove(c)
        for c in sorted(cells.values(), key=lambda x: colnum(col(x.get("r")))):
            row.append(c)
        sd.append(row)
    dim = root.find(q("dimension"))
    if dim is not None:
        dim.set(
            "ref",
            f"A1:{max((col(c.get('r')) for c in header.findall(q('c'))),key=colnum)}{len(records)+1}",
        )
    shared.attrib.pop("count", None)
    shared.attrib.pop("uniqueCount", None)
    # Reserialization drops unused namespace declarations. This plain-grid
    # adapter removes the compatibility hint; extended templates need a
    # namespace-preserving, template-specific writer.
    root.attrib.pop(f"{{{MC}}}Ignorable", None)
    parts[sp] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parts["xl/sharedStrings.xml"] = ET.tostring(
        shared, encoding="utf-8", xml_declaration=True
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(delete=False, suffix=".xlsx", dir=output.parent) as f:
        tmp = Path(f.name)
    with ZipFile(tmp, "w", ZIP_DEFLATED) as z:
        for n, b in parts.items():
            z.writestr(n, b)
    with ZipFile(tmp) as z:
        if z.testzip():
            raise ValueError("XLSX integrity failure")
    tmp.replace(output)


def main():
    p = argparse.ArgumentParser(
        description="Populate a native XLSX template from JSON records"
    )
    p.add_argument("--records", required=True, type=Path)
    p.add_argument("--template", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--data-sheet", default="data")
    a = p.parse_args()
    records = json.loads(a.records.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        p.error("records must be a JSON array of objects with string values")
    build(a.template, a.output, records, a.data_sheet)
    print(f"ROWS={len(records)}")
    print(a.output.resolve())


if __name__ == "__main__":
    main()
