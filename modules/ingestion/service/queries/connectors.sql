-- Connector status: what the worker reported about each connector. No query
-- takes a user; the server decides who may read it.

-- name: ListConnectorStatuses :many
SELECT * FROM ingestion.connector_status ORDER BY name;

-- name: GetConnectorStatus :one
SELECT * FROM ingestion.connector_status WHERE name = $1;

-- ConfigureConnector adds a connector the worker lists in its connectors file
-- or updates its configuration, leaving what its last run reported alone. An
-- invalid entry (error is not empty) has failed: its last run is the error,
-- unless a run reported since (the events can arrive again or late). An entry
-- that was invalid (no kind, failed) and is valid now starts over unknown.
-- name: ConfigureConnector :exec
INSERT INTO ingestion.connector_status (name, kind, enabled, interval_seconds, last_outcome, last_end, last_error)
VALUES (
    sqlc.arg(name), sqlc.arg(kind), sqlc.arg(enabled), sqlc.arg(interval_seconds),
    CASE WHEN sqlc.arg(error)::text = '' THEN 0 ELSE 3 END,
    CASE WHEN sqlc.arg(error)::text = '' THEN NULL ELSE sqlc.arg(time)::timestamptz END,
    sqlc.arg(error)
)
ON CONFLICT (name) DO UPDATE
SET kind = EXCLUDED.kind, enabled = EXCLUDED.enabled, interval_seconds = EXCLUDED.interval_seconds,
    last_outcome = CASE
        WHEN sqlc.arg(error)::text <> '' THEN
            CASE WHEN ingestion.connector_status.last_end IS NULL OR ingestion.connector_status.last_end <= sqlc.arg(time)::timestamptz
                 THEN 3 ELSE ingestion.connector_status.last_outcome END
        WHEN ingestion.connector_status.kind = '' AND ingestion.connector_status.last_outcome = 3 THEN 0
        ELSE ingestion.connector_status.last_outcome END,
    last_end = CASE
        WHEN sqlc.arg(error)::text <> '' THEN
            CASE WHEN ingestion.connector_status.last_end IS NULL OR ingestion.connector_status.last_end <= sqlc.arg(time)::timestamptz
                 THEN sqlc.arg(time)::timestamptz ELSE ingestion.connector_status.last_end END
        WHEN ingestion.connector_status.kind = '' AND ingestion.connector_status.last_outcome = 3 THEN NULL
        ELSE ingestion.connector_status.last_end END,
    last_error = CASE
        WHEN sqlc.arg(error)::text <> '' THEN
            CASE WHEN ingestion.connector_status.last_end IS NULL OR ingestion.connector_status.last_end <= sqlc.arg(time)::timestamptz
                 THEN sqlc.arg(error) ELSE ingestion.connector_status.last_error END
        WHEN ingestion.connector_status.kind = '' AND ingestion.connector_status.last_outcome = 3 THEN ''
        ELSE ingestion.connector_status.last_error END,
    updated_at = now();

-- DeleteConnectorsExcept forgets the connectors the worker no longer lists.
-- name: DeleteConnectorsExcept :exec
DELETE FROM ingestion.connector_status WHERE name <> ALL(sqlc.arg(names)::text[]);

-- RecordConnectorSync stores the outcome of a sync run, with the connector's
-- configuration when the report has one (a kind). A report that ended before
-- the stored one is stale (events can arrive out of order) and changes
-- nothing. Only a clean run (outcome 1) moves last_success. A report for a
-- connector that is not known adds it. An unknown document count keeps the
-- last one.
-- name: RecordConnectorSync :exec
INSERT INTO ingestion.connector_status (name, kind, enabled, interval_seconds, last_outcome, last_start, last_end, last_success, documents, last_error)
VALUES (
    sqlc.arg(name), sqlc.arg(kind), sqlc.arg(enabled), sqlc.arg(interval_seconds),
    sqlc.arg(outcome), sqlc.narg(start_time)::timestamptz, sqlc.arg(end_time)::timestamptz,
    CASE WHEN sqlc.arg(outcome)::smallint = 1 THEN sqlc.arg(end_time)::timestamptz END,
    coalesce(sqlc.narg(documents)::integer, 0), sqlc.arg(error)
)
ON CONFLICT (name) DO UPDATE
SET kind = CASE WHEN EXCLUDED.kind = '' THEN ingestion.connector_status.kind ELSE EXCLUDED.kind END,
    enabled = CASE WHEN EXCLUDED.kind = '' THEN ingestion.connector_status.enabled ELSE EXCLUDED.enabled END,
    interval_seconds = CASE WHEN EXCLUDED.kind = '' THEN ingestion.connector_status.interval_seconds ELSE EXCLUDED.interval_seconds END,
    last_outcome = EXCLUDED.last_outcome, last_start = EXCLUDED.last_start, last_end = EXCLUDED.last_end,
    last_success = CASE WHEN EXCLUDED.last_outcome = 1 THEN EXCLUDED.last_end ELSE ingestion.connector_status.last_success END,
    documents = coalesce(sqlc.narg(documents)::integer, ingestion.connector_status.documents),
    last_error = EXCLUDED.last_error, updated_at = now()
WHERE ingestion.connector_status.last_end IS NULL OR ingestion.connector_status.last_end <= EXCLUDED.last_end;
