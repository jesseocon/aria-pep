from datetime import date
from pathlib import Path

from pep_connector.nights import otb_nights, stay_nights
from pep_connector.prepare import prepare_directory
from pep_connector.schema import V1_DISPLAY_HEADERS


def _v1(**overrides: str) -> list[str]:
    fields = [""] * len(V1_DISPLAY_HEADERS)
    fields[0] = "BAR"
    fields[2] = "12345678"
    fields[5] = "EXT1"
    fields[9] = "RESERVED"
    fields[10] = "Guest, Test"
    fields[26] = "Jan 15, 2025"
    fields[30] = "Feb 1, 2025"
    fields[32] = "Feb 3, 2025"
    for header, value in {
        "Booking Time": "9:00 AM",
        "Nights": "2",
        "Adults": "1",
        "CHILDREN": "0",
        "Total Charges": "$230.00",
        "Total Room Revenue": "$200.00",
        "Total Taxes": "$30.00",
        "Total Payments": "$0.00",
        "Balance": "$230.00",
        "Average Room Rate": "$100.00",
    }.items():
        fields[V1_DISPLAY_HEADERS.index(header)] = value
    for key, value in overrides.items():
        fields[V1_DISPLAY_HEADERS.index(key)] = value
    return fields


def _csv(rows: list[list[str]]) -> str:
    lines = [",".join(f'"{header}"' for header in V1_DISPLAY_HEADERS)]
    for row in rows:
        lines.append(",".join(f'"{value}"' for value in row))
    return "\n".join(lines) + "\n"


def test_span_uses_all_four_dates_and_drops_later_sections(tmp_path: Path) -> None:
    first = _v1(**{"Cancellation Date": "Mar 2, 2025"})
    second = _v1(
        **{
            "Confirmation Number": "22345678",
            "External Confirmation Number": "EXT2",
            "Booking Date": "Dec 1, 2024",
            "Arrival Date": "Jan 10, 2025",
            "Departure Date": "Jan 11, 2025",
        }
    )
    text = _csv([first, second])
    text += _csv([_v1(**{"External Confirmation Number": "IGNORE"})])
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "Reservations(1).csv").write_text(text, encoding="utf-8")

    summaries, bronze = prepare_directory(inbox, tmp_path / "out")

    assert summaries[0].output == "reservations-all-20241201-20250302.csv"
    assert summaries[0].sections == 2
    assert {row["external_confirmation_number"] for row in bronze} == {"EXT1", "EXT2"}
    assert "IGNORE" not in {row["external_confirmation_number"] for row in bronze}


def test_later_file_replaces_the_same_confirmation(tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    early = _v1(**{"Status": "RESERVED", "Booking Date": "Jan 1, 2025"})
    late = _v1(**{"Status": "CANCELLED", "Booking Date": "Jan 1, 2025", "Cancellation Date": "Jun 1, 2025"})
    (inbox / "a.csv").write_text(_csv([early]), encoding="utf-8")
    (inbox / "b.csv").write_text(_csv([late]), encoding="utf-8")

    _summaries, bronze = prepare_directory(inbox, tmp_path / "out")

    assert len(bronze) == 1
    assert bronze[0]["status"] == "CANCELLED"
    assert bronze[0]["range_end"] == "2025-06-01"


def test_stay_night_and_otb_keep_the_reservation(tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "one.csv").write_text(
        _csv(
            [
                _v1(
                    **{
                        "Booking Date": "Feb 1, 2025",
                        "Arrival Date": "Feb 3, 2025",
                        "Departure Date": "Feb 5, 2025",
                        "Cancellation Date": "Feb 4, 2025",
                        "Status": "CANCELLED",
                    }
                )
            ]
        ),
        encoding="utf-8",
    )
    _summaries, bronze = prepare_directory(inbox, tmp_path / "out")
    nights = stay_nights(bronze, "property")
    otb = otb_nights(nights)

    assert [(row["stay_date"], row["is_occupied_night"]) for row in nights] == [
        (date(2025, 2, 3), False),
        (date(2025, 2, 4), False),
    ]
    # Booked Feb 1, cancelled Feb 4. Still on the books on Feb 3 for both nights.
    feb3 = [row for row in otb if row["as_of_date"] == date(2025, 2, 3)]
    assert {row["stay_date"] for row in feb3} == {date(2025, 2, 3), date(2025, 2, 4)}
    assert all(row["as_of_date"] < date(2025, 2, 4) or row["stay_date"] != date(2025, 2, 4) for row in otb)
    assert not any(row["as_of_date"] >= date(2025, 2, 4) for row in otb)
