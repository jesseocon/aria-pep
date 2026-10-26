"""Run the PEP dbt project and send its output to the run log."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from aria_runner.sdk import RunContext

BQ_PROJECT = {"development": "hospitalityops-dev", "production": "hospitalityops"}


def dbt_vars(config: dict[str, Any], environment: str, slug: str) -> dict[str, str]:
    """Same shape Lighthouse passes to `dbt --vars`. Plain strings, not Jinja."""
    property_key = (
        "production_property_id" if environment == "production" else "development_property_id"
    )
    return {
        "bq_project": BQ_PROJECT[environment],
        "org_id": str(config.get("org_id") or ""),
        "source": "pep",
        "property_id": str(config.get(property_key) or ""),
        "property_slug": slug,
    }


def dbt_project_dir() -> Path:
    configured = os.environ.get("PEP_DBT_PROJECT")
    if configured:
        return Path(configured)
    candidate = Path(__file__).resolve().parents[3] / "transform"
    if (candidate / "dbt_project.yml").is_file():
        return candidate
    raise FileNotFoundError("PEP dbt project not found; set PEP_DBT_PROJECT")


def dbt_executable() -> Path:
    sibling = Path(sys.executable).parent / "dbt"
    if sibling.is_file():
        return sibling
    raise FileNotFoundError(f"dbt is not installed next to {sys.executable}")


def target_environments(ctx: RunContext) -> list[str]:
    only = ctx.params.get("environment")
    if only:
        return [str(only)]
    return [str(env) for env in (ctx.config.get("environments") or ["development"])]


def run_dbt(ctx: RunContext) -> list[str]:
    """Run dbt for each warehouse on the connection. Child output is the run log."""
    project = dbt_project_dir()
    dbt = dbt_executable()
    ran: list[str] = []
    for environment in target_environments(ctx):
        rendered = dbt_vars(ctx.config, environment, ctx.connection_id)
        vars_json = json.dumps(rendered, separators=(",", ":"))
        ctx.logger.info(
            "dbt run (%s) project=%s org=%s property=%s slug=%s",
            environment,
            rendered["bq_project"],
            rendered["org_id"],
            rendered["property_id"],
            rendered["property_slug"],
        )
        env = {
            **os.environ,
            "ARIA_ORG_ID": rendered["org_id"],
            "ARIA_PROPERTY_ID": rendered["property_id"],
            "ARIA_PROPERTY_SLUG": rendered["property_slug"],
            "ARIA_BQ_PROJECT": rendered["bq_project"],
            "MELTANO_ENVIRONMENT": environment,
            "DBT_PROFILE_TARGET": environment,
            "DBT_BIGQUERY_PROJECT": rendered["bq_project"],
            "DBT_BIGQUERY_DATASET": f"silver_{rendered['org_id']}",
        }
        ctx.run_command(
            [
                str(dbt),
                "run",
                "--project-dir",
                str(project),
                "--profiles-dir",
                str(project),
                "--vars",
                vars_json,
            ],
            env=env,
            cwd=project,
            step="transform",
        )
        ran.append(environment)
    return ran
