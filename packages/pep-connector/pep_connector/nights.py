"""Stay nights and reservation-night OTB from healed reservation rows.

OTB is one row per reservation, per stay night, per as-of date. It is not a
property total. Coarser grids are a sum of room_night.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from pep_connector.span import parse_pep_date

_OFF_BOOKS = {"CANCELLED", "CANCELED", "NO SHOW"}


def _date(row: dict[str, str], field: str) -> date | None:
    return parse_pep_date(row.get(field, ""))


def stay_nights(rows: Iterable[dict[str, str]], property_id: str) -> list[dict[str, object]]:
    nights: list[dict[str, object]] = []
    for row in rows:
        arrival = _date(row, "arrival_date")
        departure = _date(row, "departure_date")
        confirmation = (row.get("external_confirmation_number") or "").strip()
        if arrival is None or departure is None or departure <= arrival or not confirmation:
            continue
        status = (row.get("status") or "").strip()
        occupied = status.upper() not in _OFF_BOOKS
        stay = arrival
        while stay < departure:
            nights.append(
                {
                    "property_id": property_id,
                    "stay_date": stay,
                    "external_confirmation_number": confirmation,
                    "confirmation_number": row.get("confirmation_number", ""),
                    "booking_date": _date(row, "booking_date"),
                    "cancellation_date": _date(row, "cancellation_date"),
                    "arrival_date": arrival,
                    "departure_date": departure,
                    "status": status,
                    "market_segment": row.get("market_segment", ""),
                    "market_segment_code": row.get("market_segment_code", ""),
                    "rate_plan": row.get("rate_plan", ""),
                    "source": row.get("source", ""),
                    "room_revenue": row.get("average_room_rate", ""),
                    "room_night": 1,
                    "is_occupied_night": occupied,
                }
            )
            stay += timedelta(days=1)
    return nights


def otb_nights(nights: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """A night is on the books at as_of when it was booked by then and not yet cancelled."""
    grouped: dict[tuple[str, date], list[dict[str, object]]] = {}
    for night in nights:
        stay_date = night["stay_date"]
        assert isinstance(stay_date, date)
        grouped.setdefault((str(night["property_id"]), stay_date), []).append(night)

    rows: list[dict[str, object]] = []
    for (_property, stay_date), stay_rows in grouped.items():
        booked = [row["booking_date"] or row["arrival_date"] for row in stay_rows]
        starts = [value for value in booked if isinstance(value, date)]
        if not starts:
            continue
        as_of = min(starts)
        while as_of <= stay_date:
            for night in stay_rows:
                booked_on = night["booking_date"] or night["arrival_date"]
                cancelled_on = night["cancellation_date"]
                if not isinstance(booked_on, date) or booked_on > as_of:
                    continue
                if isinstance(cancelled_on, date) and cancelled_on <= as_of:
                    continue
                rows.append({**night, "as_of_date": as_of})
            as_of += timedelta(days=1)
    return rows
