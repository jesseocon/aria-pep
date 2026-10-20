"""Heal PEP daily report exports: rate plan summary, occupancy summary, transactions.

Ported from aria-lighthouse/packages/transform/src/pep/{rate-plan-summary,
occupancy-summary,transactions}. Each export is the whole truth for its date
range (`block_start_date`..`block_end_date`), so bronze replaces that range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from pep_connector.parse import parse_csv_records

BLOCK_COLUMNS = [
    "block_start_date",
    "block_end_date",
    "source_file",
    "source_line",
    "parse_status",
    "heal_action",
    "row_date",
]

_MONTHS = {
    name: index
    for index, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}
_DISPLAY_DATE = re.compile(r"^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})$")
_CONFIRMATION = re.compile(r"^\d{8,12}$")


@dataclass(frozen=True)
class ReportRecord:
    fields: list[str]
    source_line: int
    parse_status: str
    heal_action: str


@dataclass(frozen=True)
class ReportHeal:
    records: list[ReportRecord]
    sections: int


@dataclass(frozen=True)
class ReportStream:
    name: str
    file_prefix: str
    header_start: str
    headers: list[str]
    heal: Callable[[str], ReportHeal]
    kept: frozenset[str]
    trim_dates: bool = True
    header_anywhere: bool = False

    def row_date(self, fields: list[str]) -> str | None:
        return display_date(fields[0], trim_inside=self.trim_dates)

    @property
    def output_headers(self) -> list[str]:
        return [*self.headers, *BLOCK_COLUMNS]


def _strip(value: str) -> str:
    text = value.strip()
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    return text


def display_date(value: str, *, trim_inside: bool = True) -> str | None:
    """`Jan 05, 2026` -> `2026-01-05`. Transactions do not trim inside the quotes."""
    text = _strip(value)
    match = _DISPLAY_DATE.match(text.strip() if trim_inside else text)
    if match is None:
        return None
    month = _MONTHS.get(match.group(1)[:3])
    if month is None:
        return None
    return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"


def _validate(headers: list[str], expected: list[str]) -> None:
    if len(headers) != len(expected):
        raise ValueError(f"Expected {len(expected)} columns, got {len(headers)}")
    for index, header in enumerate(headers):
        if header.strip().lower() != expected[index].lower():
            raise ValueError(
                f'Header mismatch at column {index + 1}: expected "{expected[index]}", got "{header}"'
            )


# Rate plan summary: one row per date x rate plan code, trailing totals row.

RATE_PLAN_DISPLAY = [
    "Date",
    "Day Of Week",
    "Rate Plan Name",
    "Rate Plan Code",
    "Rate Code Status",
    "Market Segment",
    "Market Segment Code",
    "Local Market Segment Code",
    "Local Market Segment",
    "Revenue",
    "Stays",
    "ADR",
    "Occupancy Contribution",
    "RevPAR Contribution",
]
RATE_PLAN_HEADERS = [
    "report_date",
    "day_of_week",
    "rate_plan_name",
    "rate_plan_code",
    "rate_code_status",
    "market_segment",
    "market_segment_code",
    "local_market_segment_code",
    "local_market_segment",
    "revenue",
    "stays",
    "adr",
    "occupancy_contribution",
    "revpar_contribution",
]


def heal_rate_plan_summary(text: str) -> ReportHeal:
    rows = parse_csv_records(text)
    if not rows:
        return ReportHeal([], 0)
    _validate(rows[0], RATE_PLAN_DISPLAY)
    records: list[ReportRecord] = []
    for index, row in enumerate(rows[1:]):
        if all(not value.strip() for value in row):
            continue
        if len(row) != len(RATE_PLAN_DISPLAY):
            raise ValueError(f"Expected {len(RATE_PLAN_DISPLAY)} fields, got {len(row)}")
        line = index + 2
        day, code = row[0], row[3]
        if display_date(day) is None and not code.strip():
            records.append(ReportRecord(row, line, "removed_summary_row", "removed_summary_row"))
        elif display_date(day) is None or not code.strip():
            records.append(ReportRecord(row, line, "quarantined", "invalid_daily_row"))
        else:
            records.append(ReportRecord(row, line, "ok", ""))
    return ReportHeal(records, 1)


# Occupancy summary: one row per date, trailing totals row.

OCCUPANCY_DISPLAY = [
    "Date",
    "Day Of Week",
    "Room Revenue",
    "Other Room Revenue",
    "Total Revenue",
    "Total Rooms",
    "Total Sold Rooms",
    "Sold Rooms Without Comp",
    "Down Rooms",
    "Vacant Rooms",
    "Clean Rooms",
    "DIRTY ROOMS",
    "Stayover Rooms",
    "Same Day Bookings",
    "Comp Rooms",
    "House Rooms",
    "Zero Rate Rooms",
    "Day Use Rooms",
    "Total No Shows",
    "Total Cancellations",
    "TOTAL GUESTS",
    "Total Guest Certificates",
    "ADR",
    "ADR Without Complimentary And House Use Rooms",
    "Occupancy Including OOO Comp and House Use",
    "Occupancy Excluding OOO Comp and House Use",
    "Occupancy Including OOO Excluding Comp and House Use",
    "Occupancy Excluding OOO Including Comp and House Use",
    "REVPAR WITH DOWN ROOMS",
    "REVPAR WITHOUT DOWN ROOMS",
]
OCCUPANCY_HEADERS = [
    "date",
    "day_of_week",
    "room_revenue",
    "other_room_revenue",
    "total_revenue",
    "total_rooms",
    "total_sold_rooms",
    "sold_rooms_without_comp",
    "down_rooms",
    "vacant_rooms",
    "clean_rooms",
    "dirty_rooms",
    "stayover_rooms",
    "same_day_bookings",
    "comp_rooms",
    "house_rooms",
    "zero_rate_rooms",
    "day_use_rooms",
    "total_no_shows",
    "total_cancellations",
    "total_guests",
    "total_guest_certificates",
    "adr",
    "adr_without_complimentary_and_house_use_rooms",
    "occupancy_including_ooo_comp_and_house_use",
    "occupancy_excluding_ooo_comp_and_house_use",
    "occupancy_including_ooo_excluding_comp_and_house_use",
    "occupancy_excluding_ooo_including_comp_and_house_use",
    "revpar_with_down_rooms",
    "revpar_without_down_rooms",
]


def heal_occupancy_summary(text: str) -> ReportHeal:
    rows = parse_csv_records(text)
    if not rows:
        return ReportHeal([], 0)
    _validate(rows[0], OCCUPANCY_DISPLAY)
    records: list[ReportRecord] = []
    for index, row in enumerate(rows[1:]):
        if all(not value.strip() for value in row):
            continue
        if len(row) != len(OCCUPANCY_DISPLAY):
            raise ValueError(f"Expected {len(OCCUPANCY_DISPLAY)} fields, got {len(row)}")
        line = index + 2
        if display_date(row[0]) is None:
            records.append(ReportRecord(row, line, "removed_summary_row", "removed_summary_row"))
        else:
            records.append(ReportRecord(row, line, "ok", ""))
    return ReportHeal(records, 1)


# Transactions: guest folio section only, remark newlines rejoined, v1 -> v2.

TRANSACTIONS_V1_DISPLAY = [
    "Date",
    "Time",
    "Confirmation Number",
    "Guest Name",
    "Room Number",
    "Folio Number",
    "Transaction Code",
    "Transaction Description",
    "Last 4 Digits",
    "Transaction Type",
    "Charge Type Category",
    "Sub Charge Type name",
    "Outlet Name",
    "Amount",
    "Username",
    "Remarks",
    "Charge Remarks",
    "Transferred Transactions",
    "POS Check Number",
    "Tax Invoice Number",
    "Fiscal Invoice Number",
    "Reference External Bill Number",
    "Company Name",
    "Refund Reason",
]
TRANSACTIONS_V2_DISPLAY = [
    "Date",
    "Time",
    "Confirmation Number",
    "Guest Name",
    "First Name",
    "Last Name",
    "Room Number",
    "Folio Number",
    "Transaction Code",
    "Transaction Description",
    "Last 4 Digits",
    "Transaction Type",
    "Charge Type Category",
    "Sub Charge Type name",
    "Outlet Name",
    "Amount",
    "Username",
    "Remarks",
    "Charge Remarks",
    "Transferred Transactions",
    "POS Check Number",
    "Tax Invoice Number",
    "Fiscal Invoice Number",
    "Reference External Bill Number",
    "Company Name",
    "Refund Reason",
    "Quantity",
    "Adults",
]
TRANSACTIONS_HEADERS = [
    "transaction_date",
    "transaction_time",
    "confirmation_number",
    "guest_name",
    "first_name",
    "last_name",
    "room_number",
    "folio_number",
    "transaction_code",
    "transaction_description",
    "last_4_digits",
    "transaction_type",
    "charge_type_category",
    "sub_charge_type_name",
    "outlet_name",
    "amount",
    "username",
    "remarks",
    "charge_remarks",
    "transferred_transactions",
    "pos_check_number",
    "tax_invoice_number",
    "fiscal_invoice_number",
    "reference_external_bill_number",
    "company_name",
    "refund_reason",
    "quantity",
    "adults",
]
_TRANSACTIONS_ANY_SECTION = '"Date","Time"'
_TRANSACTIONS_GUEST = '"Date","Time","Confirmation Number","Guest Name"'
_TRANSACTIONS_ROW_START = re.compile(r'^"[A-Za-z]{3} \d{1,2}, \d{4}","')
_V2_WIDTH = len(TRANSACTIONS_V2_DISPLAY)
_COMBINED_AT = TRANSACTIONS_V2_DISPLAY.index("Folio Number")
_COMBINED_EXTRA = [
    "Group Code",
    "Rate Plan",
    "Group Name",
    "House Account Code",
    "House Account Name",
    "Account Type",
]
TRANSACTIONS_COMBINED_DISPLAY = [
    *TRANSACTIONS_V2_DISPLAY[:_COMBINED_AT],
    *_COMBINED_EXTRA,
    *TRANSACTIONS_V2_DISPLAY[_COMBINED_AT:],
]
_COMBINED_WIDTH = len(TRANSACTIONS_COMBINED_DISPLAY)


def _transactions_guest_section(text: str) -> tuple[str, int, bool]:
    """Return the guest folio section, the section count, and whether it is the combined section.

    Exports whose first section uses a custom column order (e.g. starting with "Company Name")
    only carry the canonical layout in the trailing combined section, which also holds group,
    house account and company postings.
    """
    lines = re.split(r"\r?\n", text)
    header_at = [i for i, line in enumerate(lines) if line.startswith(_TRANSACTIONS_ANY_SECTION)]
    guest = next((i for i in header_at if lines[i].startswith(_TRANSACTIONS_GUEST)), None)
    start = guest if guest is not None and guest > 0 else 0
    combined = start > 0
    sections = len(header_at) + (1 if combined and not lines[0].startswith(_TRANSACTIONS_ANY_SECTION) else 0)
    following = [i for i in header_at if i > start]
    kept = lines[start : following[0]] if following else lines[start:]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), sections, combined


def _fit(fields: list[str], width: int) -> tuple[list[str], str]:
    if len(fields) > width:
        return [*fields[: width - 1], ",".join(fields[width - 1 :])], "merged_overflow"
    if len(fields) < width:
        return [*fields, *[""] * (width - len(fields))], "padded"
    return fields, ""


def _transactions_v2(fields: list[str]) -> list[str]:
    if len(fields) != len(TRANSACTIONS_V1_DISPLAY):
        return fields
    return [*fields[:4], "", "", *fields[4:24], "", ""]


def _transactions_width(fields: list[str], combined: bool = False) -> tuple[list[str], str]:
    if combined:
        fitted, action = _fit(fields, _COMBINED_WIDTH)
        return [*fitted[:_COMBINED_AT], *fitted[_COMBINED_AT + len(_COMBINED_EXTRA) :]], action
    normalized = _transactions_v2(fields)
    if len(normalized) > _V2_WIDTH:
        return [*normalized[: _V2_WIDTH - 1], ",".join(normalized[_V2_WIDTH - 1 :])], "merged_overflow"
    if len(normalized) < _V2_WIDTH:
        return [*normalized, *[""] * (_V2_WIDTH - len(normalized))], "padded"
    return normalized, ""


def _valid_transaction(fields: list[str]) -> bool:
    return (
        len(fields) == _V2_WIDTH
        and display_date(fields[0], trim_inside=False) is not None
        and _CONFIRMATION.match(_strip(fields[2])) is not None
        and bool(_strip(fields[11]))
    )


def heal_transactions(text: str) -> ReportHeal:
    section, sections, combined = _transactions_guest_section(text)
    lines = re.split(r"\r?\n", section)
    header = parse_csv_records(lines[0]) if lines else []
    if not header:
        raise ValueError("Missing CSV header row")
    layouts = {
        len(TRANSACTIONS_V1_DISPLAY): TRANSACTIONS_V1_DISPLAY,
        _V2_WIDTH: TRANSACTIONS_V2_DISPLAY,
        **({_COMBINED_WIDTH: TRANSACTIONS_COMBINED_DISPLAY} if combined else {}),
    }
    if len(header[0]) not in layouts:
        raise ValueError(f"Expected {' or '.join(map(str, layouts))} columns, got {len(header[0])}")
    _validate(header[0], layouts[len(header[0])])
    combined = len(header[0]) == _COMBINED_WIDTH

    chunks: list[tuple[str, int, int]] = []
    current: list[str] = []
    start = 0
    for index in range(1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        if _TRANSACTIONS_ROW_START.match(line):
            if current:
                chunks.append(("\n".join(current), start, len(current)))
            current, start = [line], index + 1
        elif not current:
            current, start = [line], index + 1
        else:
            current.append(line)
    if current:
        chunks.append(("\n".join(current), start, len(current)))

    records: list[ReportRecord] = []
    for chunk, line, count in chunks:
        parsed = parse_csv_records(chunk)
        fields, action = _transactions_width(parsed[0] if parsed else [""] * _V2_WIDTH, combined)
        actions = (["merged_continuation"] if count > 1 else []) + ([action] if action else [])
        if combined and not _strip(fields[2]) and display_date(fields[0], trim_inside=False) is not None:
            status = "out_of_scope"
        elif not _valid_transaction(fields):
            status = "quarantined"
        elif actions:
            status = "healed"
        else:
            status = "ok"
        records.append(ReportRecord(fields, line, status, "|".join(actions)))
    return ReportHeal(records, sections)


RATE_PLAN_SUMMARY = ReportStream(
    name="rate_plan_summary",
    file_prefix="rate-plan-summary",
    header_start='"Date","Day Of Week","Rate Plan Name"',
    headers=RATE_PLAN_HEADERS,
    heal=heal_rate_plan_summary,
    kept=frozenset({"ok"}),
)
OCCUPANCY_SUMMARY = ReportStream(
    name="occupancy_summary",
    file_prefix="occupancy-summary",
    header_start='"Date","Day Of Week","Room Revenue"',
    headers=OCCUPANCY_HEADERS,
    heal=heal_occupancy_summary,
    kept=frozenset({"ok"}),
)
TRANSACTIONS = ReportStream(
    name="transactions",
    file_prefix="transactions",
    header_start=_TRANSACTIONS_GUEST,
    headers=TRANSACTIONS_HEADERS,
    heal=heal_transactions,
    kept=frozenset({"ok", "healed"}),
    trim_dates=False,
    header_anywhere=True,
)
REPORT_STREAMS = [RATE_PLAN_SUMMARY, OCCUPANCY_SUMMARY, TRANSACTIONS]
