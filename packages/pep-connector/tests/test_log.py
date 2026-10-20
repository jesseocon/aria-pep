from pep_connector.connector import file_line
from pep_connector.prepare import FileSummary


def test_file_line_includes_the_span_and_counts() -> None:
    line = file_line(
        FileSummary(
            source="Reservations.csv",
            output="reservations-all-20250118-20251025.csv",
            range_start="2025-01-18",
            range_end="2025-10-25",
            ok=0,
            healed=10,
            quarantined=1,
            sections=2,
        )
    )
    assert "Reservations.csv -> reservations-all-20250118-20251025.csv" in line
    assert "2025-01-18..2025-10-25" in line
    assert "quarantined=1" in line
