import os
from pathlib import Path

import pytest

from pep_connector.prepare import prepare_directory

# Path to reservations-all-20250901-20250930.csv, a real export kept out of the repo.
SAMPLE = Path(os.environ.get("PEP_SAMPLE_CSV", "/nonexistent"))


@pytest.mark.skipif(not SAMPLE.is_file(), reason="set PEP_SAMPLE_CSV to the September sample export")
def test_september_sample_span_is_wider_than_the_filename(tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / SAMPLE.name).write_bytes(SAMPLE.read_bytes())

    summaries, bronze = prepare_directory(inbox, tmp_path / "out")

    assert summaries[0].sections == 6
    assert summaries[0].output == "reservations-all-20250118-20251025.csv"
    assert summaries[0].range_start == "2025-01-18"
    assert summaries[0].range_end == "2025-10-25"
    assert summaries[0].quarantined == 0
    assert summaries[0].healed == 2626
    assert len(bronze) == 2626
