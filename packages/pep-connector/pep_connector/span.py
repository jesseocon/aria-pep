"""File span is the least and greatest of four date columns, not the PEP filename."""

from __future__ import annotations

import re
from datetime import date, datetime

from pep_connector.parse import Record
from pep_connector.schema import SPAN_FIELDS

_FILENAME_RANGE = re.compile(r"reservations-all-(\d{8})-(\d{8})", re.IGNORECASE)


def parse_pep_date(value: str) -> date | None:
    text = " ".join(value.strip().split())
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def span_dates(records: list[Record]) -> tuple[date, date]:
    found: list[date] = []
    for record in records:
        if record.parse_status == "quarantined":
            continue
        for field in SPAN_FIELDS:
            parsed = parse_pep_date(record.fields.get(field, ""))
            if parsed is not None:
                found.append(parsed)
    if not found:
        raise ValueError("no booking, cancellation, arrival, or departure dates")
    return min(found), max(found)


def output_name(start: date, end: date) -> str:
    return f"reservations-all-{start:%Y%m%d}-{end:%Y%m%d}.csv"


def filename_range(name: str) -> tuple[date, date] | None:
    match = _FILENAME_RANGE.search(name)
    if match is None:
        return None
    start, end = match.group(1), match.group(2)
    return (
        datetime.strptime(start, "%Y%m%d").date(),
        datetime.strptime(end, "%Y%m%d").date(),
    )
