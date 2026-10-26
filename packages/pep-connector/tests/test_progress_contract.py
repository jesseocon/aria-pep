"""The connector reports its run the way every aria-runner connector must."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from aria_runner.sdk import RunContext
from aria_runner.testing import assert_progress_contract

from pep_connector.connector import _step
OVERTIME = "budget"
from pep_connector.manifest import manifest


def _ctx(lines: list[str]) -> RunContext:
    return RunContext(
        run_id="r1",
        org_id="org",
        connection_id="c1",
        connector_key="pep",
        config={},
        params={},
        state={},
        work_dir=Path("/tmp"),
        session_path=None,
        logger=logging.getLogger("test"),
        log_sink=lambda _source, text: lines.append(text),
    )


def test_an_in_process_step_reports_its_streams_and_its_outcome() -> None:
    lines: list[str] = []
    ctx = _ctx(lines)
    with _step(ctx, "extract"):
        ctx.report("stream.started", stream=OVERTIME)
        ctx.report("stream.finished", stream=OVERTIME, records=3)
    with pytest.raises(RuntimeError), _step(ctx, "transform"):
        raise RuntimeError("dbt failed")
    events = assert_progress_contract(lines, streams={OVERTIME})
    assert events[-1] == {**events[-1], "kind": "step.finished", "step": "transform", "ok": False}
    assert manifest()["progress"] == "v1"
