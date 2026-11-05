"""aria-runner entry for PEP report packages that arrive by email (key pep_email).

The same heal, staging, bronze and dbt as the Drive connector; only the source differs.
Order is the safety: read the new emails, stage, merge bronze, dbt, then move the inbox
bookmark. A stream that fails to load moves nothing, so the next run reads the same emails
again (every step is safe to repeat). A file that cannot be healed is named in the log and
skipped: the bookmark moves past it and the run fails; `reprocess_from` reads it again
after a fix.

The daily check (off unless `alert_at` is set): the first run after `alert_at` fails when
an expected report has not arrived in the 24 hours before it. Later runs that day only warn.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aria_runner import mailbox
from aria_runner.sdk import RunContext, RunResult

from pep_connector.connector import _load, _step, _transform, log_prepared
from pep_connector.inbox import (
    DEFAULT_ALERT_TIMEZONE,
    EXPECTED_REPORTS,
    LOCAL_PART,
    InboxOutcome,
    fetch_inbox,
    latest_by_stream,
)
from pep_connector.manifest import EMAIL_KEY, email_manifest
from pep_connector.transform import bronze_slug


class PepEmailConnector:
    key = EMAIL_KEY

    def manifest(self) -> dict:
        return email_manifest()

    def probe(self, ctx: RunContext) -> None:
        return None

    def run(self, ctx: RunContext, *, now: datetime | None = None) -> RunResult:
        if ctx.params.get("transform_only"):
            return RunResult(metrics={"status": "transform_only", "dbt": _transform(ctx)})
        if ctx.inbox is None:
            raise RuntimeError("this connection has no inbox; the runner must be 0.1.27 or later")

        ctx.logger.info("inbox %s; bronze label %s", mailbox.address(LOCAL_PART, ctx.connection_id), bronze_slug(ctx))
        cursor = mailbox.Cursor.from_state(ctx.state)
        if ctx.params.get("reprocess_from"):
            moment = datetime.fromisoformat(str(ctx.params["reprocess_from"]).replace("Z", "+00:00"))
            moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
            cursor = mailbox.Cursor(ctx.inbox.bookmark_for(moment), [])
            ctx.report("notice", code="reprocess", message=f"reading every email received from {moment.isoformat()} again")

        with _step(ctx, "extract"):
            outcome = fetch_inbox(ctx.inbox, cursor, ctx.work_dir / "parsed")
        _report_outcome(ctx, outcome)

        metrics: dict[str, Any] = {
            "status": outcome.status,
            "emails": outcome.messages,
            "repeats": outcome.repeats,
            "files": len(outcome.files),
            "ignored": len(outcome.ignored),
        }
        if outcome.prepared is not None and outcome.prepared.batches:
            loads, failed_streams = _load(ctx, outcome.prepared)
            metrics["dbt"] = _transform(ctx)
            metrics["bronze"] = loads
            metrics["rows"] = outcome.prepared.rows
            metrics["quarantined"] = sum(item.quarantined for item in outcome.prepared.files)
            if failed_streams:
                # Nothing moves: the next run reads these emails again.
                raise RuntimeError(
                    "; ".join(f"stream {name} did not load" for name in sorted(failed_streams))
                    + ". The inbox bookmark did not move; the next run reads the same emails again."
                )

        state = {
            **ctx.state,
            "inbox": outcome.cursor.to_state(),
            "last_received": mailbox.merge_received(ctx.state.get("last_received") or {}, latest_by_stream(outcome)),
        }
        problems = [f"file {name} could not be healed" for name in sorted(outcome.failed)]
        problems += _check_overdue(ctx, state, now or datetime.now(timezone.utc))
        metrics["last_received"] = state["last_received"]
        if problems:
            ctx.checkpoint(state)
            raise RuntimeError("; ".join(problems))
        return RunResult(state=state, metrics=metrics)


def _report_outcome(ctx: RunContext, outcome: InboxOutcome) -> None:
    ctx.logger.info(
        "inbox status=%s emails=%s repeats=%s files=%s", outcome.status, outcome.messages, outcome.repeats, len(outcome.files)
    )
    if outcome.messages == 0:
        ctx.report("notice", code="no_new_email", message="no new email since the last run")
    for item in outcome.ignored:
        ctx.report("notice", code="ignored_email", message=f"email from {item.sender} ({item.subject!r}) has no CSV export ({item.name})")
    if outcome.prepared is not None:
        log_prepared(ctx.logger, outcome.prepared, outcome.unrecognized, {})
    for name, error in outcome.failed.items():
        ctx.report("error", code="heal_failed", message=f"file {name} (email {outcome.files.get(name, '?')}) could not be healed: {error}")
    if outcome.more:
        ctx.logger.info("more emails are waiting; the next run continues from here")


def _check_overdue(ctx: RunContext, state: dict[str, Any], now: datetime) -> list[str]:
    """Fails the first run of the day after the deadline when an expected report is missing."""
    alert_at = str(ctx.config.get("alert_at") or "")
    if not alert_at:
        return []
    alert_tz = str(ctx.config.get("alert_timezone") or DEFAULT_ALERT_TIMEZONE)
    expected = [str(item) for item in ctx.config.get("expected_reports") or EXPECTED_REPORTS]
    day, missing = mailbox.overdue(state["last_received"], expected, now=now, alert_at=alert_at, alert_tz=alert_tz)
    if not missing:
        return []
    message = f"not emailed by {alert_at} {alert_tz} on {day}: {', '.join(missing)}"
    if state.get("overdue_alerted_on") == day:
        ctx.report("warning", code="email_overdue", message=message)
        return []
    state["overdue_alerted_on"] = day
    ctx.report("error", code="email_overdue", message=message)
    return [message]


email_connector = PepEmailConnector()
