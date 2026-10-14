# Populate a native company template

`scripts/build_native_company_template.py` is a generic adaptation of a reviewed
company-import builder developed in September 2026. It copies sample-row styles
and writes string values directly into an XLSX package using the Python standard
library. All package parts other than the selected sheet and shared strings are
copied byte for byte. No actual import template is distributed.

Provide a JSON array of objects whose keys exactly match the template headers:

```json
[
  {"COMPANY_NAME": "Example Holdings LLC", "ZIP": "00123"},
  {"COMPANY_NAME": "Example Services Inc", "ZIP": "00456"}
]
```

```powershell
python scripts/build_native_company_template.py --records work/records.json --template work/template.xlsx --output outputs/import.xlsx --data-sheet data
```

The template must contain a header row, sample row, and shared-string table.
Values must be strings, preserving leading zeros and preventing values beginning
with `=` from becoming formulas. Unknown headers and an output path equal to the
template path are rejected. The input workbook is not modified.

This is intended for plain import grids. Formula translation, table range
expansion, merged data cells, digital signatures, macro workbooks, and expansion
of validation ranges are not supported. Existing validation ranges remain as
supplied, so the template must cover the intended row count. The selected sheet
is reserialized; an unused compatibility hint is removed, and exact preservation
of that sheet's namespace layout is not guaranteed. Use a template-specific
validator and a read-only Excel open before operational upload.

The tests use a minimal synthetic XML fixture to verify package preservation,
cell types, styles, validation ranges, leading zeros, and rejection behavior.
They do not establish compatibility with an employer template or desktop Excel.
