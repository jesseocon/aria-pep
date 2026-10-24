# aria-pep

Hilton PEP exports in a Google Drive folder become PMS tables in BigQuery. Runs from aria-runner (connector key `pep`).

## File types

Drop any of these PEP exports into the connection's Drive folder. The header row decides the type; file names don't matter. Files of any other kind stay in the folder and show as `unrecognized` in the log.

| Export | Heal (ported from `aria-lighthouse/packages/transform/src/pep`) | Bronze merge |
| --- | --- | --- |
| Reservations | First section only, rows rebuilt (see below), v1 → v2, rows without an external confirmation number quarantined | Upsert on `external_confirmation_number`; the export whose range ends later wins |
| Rate Plan Summary | Totals row removed, rows without a date or code quarantined | Replace the export's date range |
| Occupancy Summary | Totals row removed | Replace the export's date range |
| Transactions | Guest folio section only, rows rebuilt (see below), v1 → v2, invalid rows quarantined | Replace the export's date range |

A daily report export is the whole truth for its dates, from its first to its last date. Bronze deletes those dates and inserts the export's rows in one transaction. Other dates are not touched. When two exports in one run cover the same date, the one whose range ends later supplies it.

Each heal was checked against the TypeScript on the Lighthouse sample exports. All rows match: reservations 11,683, rate plan summary 730,650, occupancy summary 918, transactions 482,516.

### Rebuilding rows

PEP quotes every field but does not escape quotes inside text, some text holds line breaks, and some holds `",`, which splits a field in two. Reservations and Transactions rows are rebuilt from what PEP's columns are, never from what one property's values look like (`pep_connector/assemble.py`):

- A quote closes a field only when a comma, a line end or the end of the file follows it, so `ask for "John"` stays text.
- A row starts at a record whose leading columns have PEP's row-start types (reservations: market segment code, local market segment code, confirmation number; transactions: date, time, confirmation number). Anything else is the rest of the row above, and that row is parsed again with its line breaks kept as text.
- A row wider than the header is merged back at the first text column that leaves every typed column (dates, times, money, counts) in shape. A totals line is removed. Rows that still do not fit are quarantined.

Every row start yields exactly one row, so nothing is dropped without being counted. A file in which more than 1% of rows (and more than 5) are quarantined fails instead of loading what could be read; the message names the first lines and the reasons. A new property's export that breaks in a new way therefore fails its first run instead of loading part of the hotel.

The first version anchored rows on a raw-line pattern that required an empty local market segment code. At a property that uses local codes, most rows were glued onto the row above and dropped: Dallas Love Field loaded 21–29% of its reservations. With the rebuild, stay nights for July–September 2026 match the Occupancy Summary within 0.05% (83 of 92 nights exact, none off by more than 3 rooms).

## Flow

Each run, in order. Every step is safe to repeat.

1. **Fetch.** List the CSVs directly in the connection's Drive folder. If any changed in the last 60 seconds, wait: load nothing, move nothing. Drive is not changed in this step.
2. **Heal**, per file type (table above).
3. **Staging.** `bronze_{org}.pep__{stream}_{connection}__staging`, overwritten every run and expiring after 7 days.
4. **Bronze.** `bronze_{org}.pep__{stream}_{connection}`, merged into, never rebuilt. Carries `_run_id` and `_loaded_at`. The connector creates all four bronze tables every run, so dbt builds even for a type that never arrived.
5. **Silver** (dbt). `silver_{org}.pep__{stream}_{property_id}`, typed. Reservations merge on `external_confirmation_number`. Daily reports replace the dates bronze replaced since silver last ran.
6. **Gold** (dbt). See the gold contract below.
7. **File away.** The originals move to `processed/<UTC timestamp>/` in the Drive folder after dbt succeeds, for each file type whose load succeeded. Nothing is uploaded: service accounts have no My Drive storage, and the healed rows are in BigQuery.

Failures: a file that fails to heal (including one with more than 1% of rows quarantined), or a file type that fails to load, stays in the folder and fails the run, and the other types still go through. If dbt fails, nothing moves.

The run log shows each file (type, ok, healed, quarantined, sections, summary rows), staging and bronze row counts per type, the full dbt output, unrecognized files, and the Drive destination.

## Gold contract

The gold tables are the PMS standard. Another PMS connector writes the same table names and the same columns: same names, same types, same grain. Values stay as the PMS sends them; only the column names are standard. `transform/models/marts/_marts.yml` enforces the contract, so a model that drifts fails to build.

Every row carries `pms` (`pep` here). `reservation_id` is the key. For PEP it is the External Confirmation Number. Changing a gold column or its key needs one `dbt run --select tag:gold --full-refresh`.

Tables:

- `mlt_mart__pms__stay_night` and `mlt_mart__pms__otb_night`, from reservations.
- `mlt_dim__pms__rate_plan`: the latest name per rate plan code, from Rate Plan Summary. Merged by code; a row is replaced only by a report date on or after the stored one. Join on `pms`, `property_id`, `rate_plan`.

Market segment names already come in the reservations export, so there is no segment table.

Gold only holds things that take real logic to define. Simple rollups are queries on these tables, not more tables. Planned: cancellations (built from reservations, transactions, and occupancy, with per-property policy settings) and property night (from occupancy summary).

## Drive access

Drive calls impersonate `aria-pep-drive@gn-shared-services-production.iam.gserviceaccount.com`; they bill `gn-shared-services-production`, where the Drive API is enabled. The token exchange bills the caller's own project, so the job account needs no role in `gn-shared-services-production`. Share the reservations folder with that account as Content manager. Your gcloud login and the Cloud Run job account (`aria-flagship-job@hospitalityops.iam.gserviceaccount.com`) need `roles/iam.serviceAccountTokenCreator` on it.

The connection's `drive_folder_id` is the only link to a property. A folder URL works too. The folder name is not read.

## Run locally

From the aria-runner console: open the connection and press **Sync**. The log is at `aria-runner/.local/tmp/logs/{run_id}.log`.

Without the runner:

```bash
cd aria-pep   # next to aria-runner
uv sync
uv run python -m pep_connector drive-ls --folder-id FOLDER_ID
uv run python -m pep_connector prepare --input path/to/csvs --out out   # heal only, no Drive, no BigQuery
uv run pytest
```

## Deploy

One Cloud Run job, `python -m aria_runner execute`, like the other connectors. The image installs `dbt-bigquery` through the package dependencies. Connection config: `org_id`, `development_property_id`, `production_property_id`, `drive_folder_id`, `environments`. Development writes to `hospitalityops-dev`, production to `hospitalityops`.

Not deployed yet: the `aria-connector-pep` image and job (push, Terraform entry).
