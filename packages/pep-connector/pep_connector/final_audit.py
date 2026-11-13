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
        return _v2_to_csv(rows)
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


# PEP's other Final Audit export ("FinalAuditV2.xlsx", what a person downloads from PEP by hand). Same
# figures, another layout: the title is in column B, "Date:" and the date are two cells, room and other
# room revenue share one "Revenue" table, payments sit under "Payment Information", lines have no
# numbers, amounts are text ("$1,234.56", "-$43.12"), and the ledgers are label/value pairs. It is
# written out as the same rows, sections, groups and number format as the original export, so the
# pipeline and the balancing engine read either one the same way.
_V2_SECTIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("Revenue & Charges", "Charges"): ("Charges", "Charge Type Name"),
    ("Revenue & Charges", "Taxes"): ("Taxes", "Tax Type"),
    ("Revenue & Charges", "Surcharges & Fees"): ("Fees", "Tax Type"),
    ("Payment Information", "Cash"): ("Payments", "Cash"),
    ("Payment Information", "Card"): ("Payments", "Card"),
    ("Payment Information", "Other"): ("Payments", "Other"),
    ("Payment Information", "Direct Bill"): ("Payments", "DIRECT BILL"),
}
# The original export splits "Revenue" into room revenue and the add-ons and upgrades.
_V2_OTHER_ROOM_REVENUE = re.compile(r"^ADD[- ]?ON\b|UPGRADE|^EXTRA ADULT$|CLUB ACCESS")
# (block, label prefix) -> the ledger's name and line in the original export's Balance Information.
_V2_LEDGERS: dict[tuple[str, str], tuple[str, int]] = {
    ("Guest Balance Ledger", "In House"): ("In House", 1),
    ("Guest Balance Ledger", "Group Master"): ("Group Master", 2),
    ("Guest Balance Ledger", "House Account"): ("House Account", 3),
    ("Guest Balance Ledger", "Total Closed Folio"): ("Closed Folio", 4),
    ("Advanced Deposit Balance", "Advance Deposit"): ("Advance Deposit", 5),
    ("Direct Bill Balance", "Direct Bill"): ("Direct Bill", 6),
    ("Advanced Deposit Balance", "Group Master"): ("Advance Deposit Group", 7),
}
_V2_LEDGER_PARTS = (
    (re.compile(r"\b(Opening|Starting) Balance:?$", re.I), "Opening Balance"),
    (re.compile(r"\bNet Change:?$", re.I), "Net Change"),
    (re.compile(r"\b(Closing|Ending) Balance:?$", re.I), "Closing Balance"),
)
_V2_DATE = re.compile(r"^[A-Za-z]{3} \d{1,2}, \d{4}$")


def _money(value: object) -> str:
    """"$1,234.50" / "-$43.12" / 0.0 as the original export's plain decimals ("1234.5", "-43.12", "0")."""
    if isinstance(value, (int, float)):
        return _number(value)
    text = _text(value).replace("$", "").replace(",", "").strip()
    if not text:
        return ""
    try:
        return _number(float(text))
    except ValueError:
        return ""


def _v2_to_csv(rows: list[tuple[object, ...]]) -> str | None:
    """CSV text of a FinalAuditV2 workbook, or None when it is not one."""
    if not any(_text(_cell(row, 1)) == _TITLE for row in rows[:12]):
        return None
    business_date = hotel = code = ""
    for row in rows[:6]:
        cells = [_text(cell) for cell in row]
        for position, text in enumerate(cells):
            if text == "Date:":
                following = next((c for c in cells[position + 1 :] if c), "")
                if _V2_DATE.match(following):
                    business_date = following
            elif text.startswith("Hotel ID:"):
                code = text.split(":", 1)[1].strip()
            elif not hotel and text and row is rows[0] and not text.endswith(":"):
                hotel = text
    if not business_date:
        return None

    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(CSV_HEADINGS)

    def write(section: str, group: str, number: int, name: str, values: dict[str, str]) -> None:
        line = {"Business Date": business_date, "Section": section, "Group": group, "Line": str(number), "Name": name,
                "Hotel": hotel, "Hotel Code": code, **values}
        writer.writerow([line.get(heading, "") for heading in CSV_HEADINGS])

    numbers: dict[str, int] = {}
    ledgers: dict[str, dict[str, str]] = {}
    block = group = ""
    columns: dict[int, str] = {}
    for row in rows[6:]:
        cells = [_text(cell) for cell in row]
        label = cells[1] if len(cells) > 1 else ""
        values = [c for c in cells[2:] if c]
        if label and not values:  # a block title: "Revenue & Charges", "Payment Information", "Guest Balance Ledger"
            block, group, columns = label, "", {}
            continue
        if label and _is_heading(row):
            group, columns = label, _columns(row) if any(c == "Actual Today" for c in cells[4:5]) else {}
            continue
        ledger_label = next((c for c in cells[1:6] if c.endswith(":")), "")
        if ledger_label:
            for (ledger_block, prefix), (name, _number_) in _V2_LEDGERS.items():
                if block == ledger_block and ledger_label.startswith(prefix):
                    for pattern, part in _V2_LEDGER_PARTS:
                        if pattern.search(ledger_label):
                            amount = next((_money(c) for c in row[6:] if _text(c)), "")
                            ledgers.setdefault(name, {})[part] = amount
            continue
        if not columns or not label or label.lower().startswith("total "):
            continue  # a total row, or a table this export adds (deposits, cash drops, statistics)
        name = label.upper()
        if (block, group) == ("Revenue & Charges", "Revenue"):
            section = "Other Room Revenue" if _V2_OTHER_ROOM_REVENUE.search(name) else "Room Revenue"
            mapped = (section, "Charge Type Name")
        else:
            mapped = _V2_SECTIONS.get((block, group))
        if mapped is None:
            continue
        numbers[mapped[0]] = numbers.get(mapped[0], 0) + 1
        write(mapped[0], mapped[1], numbers[mapped[0]], name,
              {heading: _money(_cell(row, position)) for position, heading in columns.items()})
    for (_block, _prefix), (name, number) in sorted(_V2_LEDGERS.items(), key=lambda item: item[1][1]):
        if name in ledgers:
            write("Balance Information", "Ledger Name", number, name, ledgers[name])
    return out.getvalue()


def business_day(text: str) -> str | None:
    """The ISO date of a Final Audit CSV's first line, for logs and tests."""
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    first = next(reader, None)
    if not first:
        return None
    return datetime.strptime(first[0], "%b %d, %Y").date().isoformat()  # noqa: DTZ007 - a calendar day
