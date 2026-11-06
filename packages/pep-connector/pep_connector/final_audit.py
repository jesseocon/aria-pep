"""PEP's Final Audit (Excel): every revenue, tax, payment and ledger line of one business date.

The workbook is one sheet of sections ("Room Revenue", "Charges", "Taxes", "Payments", ...).
Each section is a title row, then a heading row whose first cell names the group ("Charge
Type Name", "Tax Type", or "Cash" / "Card" / "Other" inside Payments), then numbered lines,
then an unnumbered total row. The headings differ by section (amount sections have Actual
Today ... LY-T-D Variance; Balance Information has Opening Balance, Net Change, Closing
Balance), so each value lands in the column its heading names.

`xlsx_to_csv` turns the workbook into CSV text with one row per numbered line, so the report
pipeline classifies and heals it like PEP's CSV exports.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

CSV_HEADINGS = [
    "Business Date",
    "Section",
    "Group",
    "Line",
    "Name",
    "Actual Today",
    "Adjusted",
    "Adjusted Transferred",
    "Net Today",
    "M-T-D",
    "LY-M-T-D",
    "M-T-D Variance",
    "Y-T-D",
    "LY-T-D",
    "Y-T-D Variance",
    "Opening Balance",
    "Net Change",
    "Closing Balance",
    "Hotel",
    "Hotel Code",
]
_TITLE = "Final Audit"
_DATE = re.compile(r"^Date:\s*([A-Za-z]{3} \d{1,2}, \d{4})$")
# A heading row's first cell names its group; its other cells name the value columns.
_VALUE_HEADINGS = {name.lower(): name for name in CSV_HEADINGS[5:18]}
_VALUE_HEADINGS.update({"variance": "Variance"})


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value: object) -> str:
    """Excel's floats as plain decimals: 50491.899999999994 is 50491.9, 0.9315 stays 0.9315."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text
    return str(value).strip()


def _is_heading(row: tuple[object, ...]) -> bool:
    return any(_text(cell).lower() in ("actual today", "opening balance") for cell in row[2:])


def _columns(heading: tuple[object, ...]) -> dict[int, str]:
    """Value column for each heading cell from column C on; the second "Variance" is Y-T-D's."""
    out: dict[int, str] = {}
    seen_variance = False
    for position, cell in enumerate(heading[2:], start=2):
        name = _text(cell).lower()
        if name == "variance":
            out[position] = "Y-T-D Variance" if seen_variance else "M-T-D Variance"
            seen_variance = True
        elif name in _VALUE_HEADINGS:
            out[position] = _VALUE_HEADINGS[name]
    return out


def _cell(row: tuple[object, ...], position: int) -> object:
    return row[position] if position < len(row) else None


def xlsx_to_csv(data: bytes) -> str | None:
    """CSV text of a Final Audit workbook, or None when the workbook is not one.

    Column A holds the line number, column B the line name (or a section title or a group
    heading), columns C on the values under that group's headings.
    """
    from openpyxl import load_workbook  # noqa: PLC0415 - only Final Audit attachments need it

    try:
        sheet = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
    except Exception:  # noqa: BLE001 - a workbook that will not open is not a Final Audit
        return None
    rows = list(sheet.iter_rows(values_only=True))
    if not any(_text(_cell(row, 0)) == _TITLE for row in rows[:12]):
        return None
    business_date = ""
    for row in rows[:6]:
        for cell in row:
            match = _DATE.match(_text(cell))
            if match:
                business_date = match.group(1)
    if not business_date:
        return None
    hotel = _text(_cell(rows[0], 0)) if rows else ""
    code = _text(_cell(rows[1], 0)) if len(rows) > 1 else ""

    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(CSV_HEADINGS)
    section = group = ""
    columns: dict[int, str] = {}
    for row in rows[8:]:
        number, label = _cell(row, 0), _cell(row, 1)
        rest = [cell for cell in row[2:] if cell not in (None, "")]
        if isinstance(label, str) and number is None and not rest:
            if label.strip() != "END OF REPORT":
                section, group, columns = label.strip(), "", {}
            continue
        if isinstance(label, str) and number is None and _is_heading(row):
            group, columns = label.strip(), _columns(row)
            continue
        if not columns or not isinstance(number, (int, float)) or label is None:
            continue  # a total row (no line number), or text outside a table
        line = {
            "Business Date": business_date,
            "Section": section,
            "Group": group,
            "Line": _text(number),
            "Name": _text(label),
            "Hotel": hotel,
            "Hotel Code": code,
        }
        line.update({name: _number(_cell(row, position)) for position, name in columns.items()})
        writer.writerow([line.get(name, "") for name in CSV_HEADINGS])
    return out.getvalue()


def business_day(text: str) -> str | None:
    """The ISO date of a Final Audit CSV's first line, for logs and tests."""
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    first = next(reader, None)
    if not first:
        return None
    return datetime.strptime(first[0], "%b %d, %Y").date().isoformat()  # noqa: DTZ007 - a calendar day
