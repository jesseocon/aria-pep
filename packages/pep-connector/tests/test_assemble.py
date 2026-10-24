"""Row assembly against the ways PEP exports break, written the way PEP writes them:
every field quoted, quotes inside text not escaped."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from pep_connector.parse import heal_text
from pep_connector.prepare import prepare_directory, prepare_run
from pep_connector.reports import heal_transactions
from pep_connector.schema import V2_DISPLAY_HEADERS

H = V2_DISPLAY_HEADERS


def _row(n: int = 1, **overrides: str) -> list[str]:
    values = dict.fromkeys(H, "")
    values.update(
        {
            "Market Segment Code": "F",
            "Local Market Segment Code": "P",
            "Confirmation Number": f"{30000000 + n}",
            "External Confirmation Number": f"{900000000 + n}",
            "Status": "Arrival",
            "Guest Name": "Guest, Test",
            "Booking Date": "Oct 1, 2026",
            "Booking Time": "10:00 AM",
            "Arrival Date": "Nov 2, 2026",
            "Departure Date": "Nov 4, 2026",
            "Nights": "2",
            "Adults": "1",
            "CHILDREN": "0",
            "Total Charges": "$230.00",
            "Total Room Revenue": "$200.00",
            "Total Taxes": "$30.00",
            "Total Payments": "$0.00",
            "Balance": "$230.00",
            "DK": "No",
            "Virtual CC": "No",
            "Average Room Rate": "$100.00",
            "Booked By": "Front Desk",
        }
    )
    values.update({key.replace("_", " "): value for key, value in overrides.items()})
    return [values[header] for header in H]


def _line(values: list[str]) -> str:
    return ",".join(f'"{value}"' for value in values)  # PEP does not escape quotes


def _export(*rows: list[str], tail: str = "") -> str:
    return "\n".join([_line(list(H)), *(_line(row) for row in rows)]) + "\n" + tail


def _by_conf(text: str) -> dict[str, object]:
    return {r.fields["confirmation_number"]: r for r in heal_text(text, "Reservations.csv").records}


def test_local_market_segment_codes_do_not_hide_rows() -> None:
    rows = [_row(i, **{"Local Market Segment Code": code}) for i, code in enumerate(["", "P", "OD", "BAR", "LN"])]
    records = heal_text(_export(*rows), "Reservations.csv").records
    assert [r.parse_status for r in records] == ["ok"] * 5
    assert [r.fields["local_market_segment_code"] for r in records] == ["", "P", "OD", "BAR", "LN"]


def test_unescaped_quotes_in_text_stay_text() -> None:
    remark = 'guest asked for "the quiet side" and a 6" crib'
    records = _by_conf(_export(_row(1, **{"Booking Remarks": remark}), _row(2)))
    assert records["30000001"].fields["booking_remarks"] == remark
    assert records["30000002"].parse_status == "ok"


def test_line_breaks_in_text_are_kept_exactly() -> None:
    remark = 'late arrival\n\nsee "notes"\nVIP'
    linked = "30000007\n30000008"
    text = _export(_row(1, **{"Booking Remarks": remark, "Linked Reservations": linked}), _row(2))
    records = _by_conf(text)
    assert records["30000001"].fields["booking_remarks"] == remark
    assert records["30000001"].fields["linked_reservations"] == linked
    assert records["30000002"].parse_status == "ok"


def test_split_field_is_merged_back_where_the_types_fit() -> None:
    remark = 'rate per contract ", see group'
    record = _by_conf(_export(_row(1, **{"Booking Remarks": remark})))["30000001"]
    assert record.parse_status == "healed"
    assert "merged_split_field" in record.heal_action
    assert record.fields["booking_remarks"] == remark
    assert record.fields["average_room_rate"] == "$100.00"
    assert record.fields["dk"] == "No"


def test_totals_line_is_removed_not_glued_to_the_last_row() -> None:
    totals = dict.fromkeys(H, "")
    totals.update({"Nights": "1,204", "Adults": "1,530", "Total Charges": "$90,000.00"})
    text = _export(_row(1), _row(2), [totals[h] for h in H])
    records = heal_text(text, "Reservations.csv").records
    assert [r.parse_status for r in records] == ["ok", "ok", "removed_summary_row"]


def test_every_row_start_yields_exactly_one_record() -> None:
    rng = random.Random(7)
    junk = ['"', '",', "\n", "\n\n", ", ", 'say "hi"', "x", "$", "Oct 1, 2026"]
    rows = []
    for i in range(400):
        remark = "".join(rng.choice(junk) for _ in range(rng.randint(0, 6)))
        rows.append(_row(i, **{"Booking Remarks": remark, "Local Market Segment Code": rng.choice(["", "P", "OD"])}))
    records = heal_text(_export(*rows), "Reservations.csv").records
    assert sorted(r.fields["confirmation_number"] for r in records) == sorted(row[2] for row in rows)
    loaded = [r for r in records if r.parse_status in ("ok", "healed")]
    assert len(loaded) >= 0.95 * len(rows)
    for record in loaded:  # a loaded row is always aligned
        assert record.fields["arrival_date"] == "Nov 2, 2026"
        assert record.fields["average_room_rate"] == "$100.00"


def test_unreadable_rows_are_counted_and_fail_the_file(tmp_path: Path) -> None:
    broken = _row(1, **{"Nights": "two"})  # a typed column out of shape
    good = _export(*[_row(i) for i in range(2, 200)], broken)
    assert _by_conf(good)["30000001"].parse_status == "quarantined"

    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "ok.csv").write_text(good)
    bad_rows = [_row(i, **{"Nights": "two"}) if i % 10 == 0 else _row(i) for i in range(200)]
    (inbox / "bad.csv").write_text(_export(*bad_rows))
    run = prepare_run(inbox, tmp_path / "out")
    assert "limit 1%" in run.failed["bad.csv"]
    assert "ok.csv" not in run.failed


def test_fragment_before_the_first_row_is_quarantined() -> None:
    text = _line(list(H)) + "\nstray text\n" + _line(_row(1)) + "\n"
    records = heal_text(text, "Reservations.csv").records
    assert [r.parse_status for r in records] == ["quarantined", "ok"]
    assert "orphan_fragment" in records[0].heal_action


def test_transactions_use_the_same_assembly() -> None:
    from pep_connector.reports import TRANSACTIONS_V2_DISPLAY as T

    def tx(**overrides: str) -> list[str]:
        values = dict.fromkeys(T, "")
        values.update(
            {
                "Date": "Oct 15, 2026",
                "Time": "11:59 PM",
                "Confirmation Number": "31234567",
                "Guest Name": "Guest, Test",
                "Folio Number": "1",
                "Transaction Code": "1000",
                "Transaction Description": "GUEST ROOM",
                "Transaction Type": "Charge",
                "Amount": "$150.00",
                "Quantity": "1",
                "Adults": "1",
            }
        )
        values.update(overrides)
        return [values[h] for h in T]

    rows = [tx(), tx(Remarks='moved to "king"\nper GM'), tx(Amount="-$1,204.50")]
    text = "\n".join(_line(r) for r in [list(T), *rows]) + "\n"
    records = heal_transactions(text).records
    assert [r.parse_status for r in records] == ["ok", "healed", "ok"]
    assert records[1].fields[T.index("Remarks")] == 'moved to "king"\nper GM'


@pytest.mark.parametrize("width", [63, 66])
def test_header_versions_still_validate(width: int) -> None:
    from pep_connector.schema import V1_DISPLAY_HEADERS

    headers = V1_DISPLAY_HEADERS if width == 63 else V2_DISPLAY_HEADERS
    assert len(headers) == width
    with pytest.raises(ValueError):
        heal_text(_line([*headers[:-1], "Wrong"]) + "\n", "Reservations.csv")


def test_prepare_directory_loads_every_row(tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    rows = [_row(i, **{"Local Market Segment Code": "OD"}) for i in range(50)]
    (inbox / "Reservations.csv").write_text(_export(*rows))
    summaries, bronze = prepare_directory(inbox, tmp_path / "out")
    assert len(bronze) == 50 and summaries[0].quarantined == 0
