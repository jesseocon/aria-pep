"""aria-runner entry.

Order is the safety: heal, stage, merge bronze, dbt silver and gold, then
file the Drive originals away. A stream that fails keeps its files in the
drop folder for the next run; the other streams still go through. If dbt
fails, nothing moves. Unrecognized files are never moved. Every step is safe
to repeat.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aria_runner.sdk import RunContext, RunResult

from pep_connector.drive import (
    SyncOutcome,
    build_service,
    drive_impersonate,
    fetch_drive,
    finalize_drive,
)
from pep_connector.load import STREAM_COLUMNS, ensure_bronze, load_bronze
from pep_connector.manifest import KEY, manifest
from pep_connector.prepare import FileSummary, PreparedRun, prepare_run
from pep_connector.transform import dbt_vars, run_dbt, target_environments


def file_line(item: FileSummary) -> str:
    line = (
        f"file [{item.stream}] {item.source} -> {item.output} {item.range_start}..{item.range_end} "
        f"ok={item.ok} healed={item.healed} quarantined={item.quarantined} sections={item.sections}"
    )
    return f"{line} removed={item.removed}" if item.removed else line


def log_summaries(logger: logging.Logger, summaries: list[FileSummary]) -> None:
    for item in summaries:
        logger.info("%s", file_line(item))


def log_prepared(logger: logging.Logger, prepared: PreparedRun, unrecognized: list[str], failed: dict[str, str]) -> None:
    for batch in prepared.batches.values():
        logger.info("stream %s files=%s rows=%s", batch.stream, len(batch.files), batch.rows)
    log_summaries(logger, prepared.files)
    for name in unrecognized:
        logger.warning("unrecognized file %s: left in the folder", name)
    for name, error in failed.items():
        logger.error("file %s did not heal, left in the folder: %s", name, error)


def log_outcome(logger: logging.Logger, outcome: SyncOutcome) -> None:
    logger.info(
        "drive status=%s files=%s rows=%s quarantined=%s",
        outcome.status,
        len(outcome.files),
        outcome.bronze_rows,
        sum(item.quarantined for item in outcome.files),
    )
    if outcome.prepared is not None:
        log_prepared(logger, outcome.prepared, outcome.unrecognized, outcome.failed)


class PepConnector:
    key = KEY

    def manifest(self) -> dict:
        return manifest()

    def probe(self, ctx: RunContext) -> None:
        return None

    def run(self, ctx: RunContext) -> RunResult:
        out = ctx.work_dir / "healed"
        if ctx.params.get("transform_only"):
            return RunResult(metrics={"status": "transform_only", "dbt": _transform(ctx)})

        raw = ctx.params.get("input_dir") or ctx.config.get("input_dir")
        if raw:
            ctx.logger.info("local input %s", raw)
            with _step(ctx, "extract"):
                prepared = prepare_run(Path(str(raw)), out)
            log_prepared(ctx.logger, prepared, prepared.unrecognized, prepared.failed)
            loads, failed_streams = _load(ctx, prepared)
            metrics = {"status": "ready", "files": len(prepared.files), "rows": prepared.rows, "bronze": loads}
            metrics["dbt"] = _transform(ctx)
            _raise_failures(failed_streams, prepared.failed)
            return RunResult(metrics=metrics)

        folder_id = str(ctx.config.get("drive_folder_id") or "")
        ctx.logger.info("drive folder %s as %s", folder_id, drive_impersonate())
        service = build_service()
        with _step(ctx, "extract"):
            outcome = fetch_drive(folder_id, out, service=service)
        log_outcome(ctx.logger, outcome)
        if outcome.status == "waiting":
            ctx.logger.info("a file changed in the last minute; nothing loaded, nothing moved")
            return RunResult(metrics={"status": "waiting"})
        if outcome.status == "empty" or outcome.prepared is None:
            ctx.logger.info("no new files; nothing loaded")
            _raise_failures(set(), outcome.failed)
            return RunResult(metrics={"status": "empty", "unrecognized": outcome.unrecognized})

        loads, failed_streams = _load(ctx, outcome.prepared)
        warehouses = _transform(ctx)
        moved = set(outcome.prepared.batches) - failed_streams
        finalize_drive(outcome, service=service, streams=moved)
        ctx.logger.info("drive moved=%s destination=%s", len(outcome.moved), outcome.destination or "-")
        _raise_failures(failed_streams, outcome.failed)
        return RunResult(
            metrics={
                "status": outcome.status,
                "files": len(outcome.files),
                "rows": outcome.bronze_rows,
                "quarantined": sum(item.quarantined for item in outcome.files),
                "bronze": loads,
                "dbt": warehouses,
                "moved": outcome.moved,
                "destination": outcome.destination,
                "unrecognized": outcome.unrecognized,
            }
        )


@contextmanager
def _step(ctx: RunContext, name: str) -> Iterator[None]:
    """A phase of the run that happens in this process, reported to the run log."""
    ctx.report("step.started", step=name)
    started = time.monotonic()
    ok = False
    try:
        yield
        ok = True
    finally:
        ctx.report("step.finished", step=name, ok=ok, seconds=round(time.monotonic() - started, 1))


def _load(ctx: RunContext, prepared: PreparedRun) -> tuple[list[dict[str, Any]], set[str]]:
    with _step(ctx, "load"):
        return _load_batches(ctx, prepared)


def _load_batches(ctx: RunContext, prepared: PreparedRun) -> tuple[list[dict[str, Any]], set[str]]:
    loads: list[dict[str, Any]] = []
    failed: set[str] = set()
    for batch in prepared.batches.values():
        ctx.report("stream.started", stream=batch.stream)
        for environment in target_environments(ctx):
            rendered = dbt_vars(ctx.config, environment, ctx.connection_id)
            try:
                result = load_bronze(
                    batch.staging_csv,
                    project=rendered["bq_project"],
                    org_id=rendered["org_id"],
                    slug=rendered["property_slug"],
                    run_id=ctx.run_id,
                    stream=batch.stream,
                )
            except Exception:
                ctx.logger.exception("stream %s failed to load (%s); its files stay in the folder", batch.stream, environment)
                failed.add(batch.stream)
                continue
            ctx.logger.info(
                "[%s] staging %s rows=%s -> bronze %s merged=%s",
                batch.stream,
                result.staging,
                result.staged_rows,
                result.bronze,
                result.merged_rows,
            )
            loads.append(
                {
                    "stream": batch.stream,
                    "environment": environment,
                    "staging": result.staging,
                    "bronze": result.bronze,
                    "staged_rows": result.staged_rows,
                    "merged_rows": result.merged_rows,
                }
            )
        if batch.stream in failed:
            ctx.report("stream.skipped", stream=batch.stream, reason="failed to load; its files stay in the folder",
                       code="load_failed")
        else:
            ctx.report("stream.finished", stream=batch.stream, records=batch.rows)
    return loads, failed


def _ensure_sources(ctx: RunContext) -> None:
    for environment in target_environments(ctx):
        rendered = dbt_vars(ctx.config, environment, ctx.connection_id)
        for stream in STREAM_COLUMNS:
            ensure_bronze(rendered["bq_project"], rendered["org_id"], rendered["property_slug"], stream)


def _transform(ctx: RunContext) -> list[str]:
    _ensure_sources(ctx)
    try:
        return run_dbt(ctx)
    except FileNotFoundError as exc:
        ctx.logger.error("%s", exc)
        raise


def _raise_failures(streams: set[str], files: dict[str, str]) -> None:
    problems = [f"stream {name} did not load" for name in sorted(streams)]
    problems += [f"file {name} did not heal" for name in sorted(files)]
    if problems:
        raise RuntimeError("; ".join(problems) + ". Those files are still in the Drive folder.")


connector = PepConnector()
