-- Connector status: what the worker reported about each connector. No query
-- takes a user; the server decides who may read it.

-- name: ListConnectorStatuses :many
SELECT * FROM ingestion.connector_status ORDER BY name;

-- name: GetConnectorStatus :one
SELECT * FROM ingestion.connector_status WHERE name = $1;

-- ConfigureConnector adds a connector the worker lists in its connectors file
-- or updates its configuration, leaving what its last run reported alone. An
-- invalid entry (error is not empty) has failed: its last run is the error.
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
    last_outcome = CASE WHEN sqlc.arg(error)::text = '' THEN ingestion.connector_status.last_outcome ELSE 3 END,
    last_end = CASE WHEN sqlc.arg(error)::text = '' THEN ingestion.connector_status.last_end ELSE sqlc.arg(time)::timestamptz END,
    last_error = CASE WHEN sqlc.arg(error)::text = '' THEN ingestion.connector_status.last_error ELSE sqlc.arg(error) END,
    updated_at = now();

-- DeleteConnectorsExcept forgets the connectors the worker no longer lists.
-- name: DeleteConnectorsExcept :exec
DELETE FROM ingestion.connector_status WHERE name <> ALL(sqlc.arg(names)::text[]);

-- RecordConnectorSync stores the outcome of a sync run. A report that ended
-- before the stored one is stale (events can arrive out of order) and changes
-- nothing. Only a clean run (outcome 1) moves last_success. A report for a
-- connector that is not known (yet) adds it, to be completed by
-- ConfigureConnector.
-- name: RecordConnectorSync :exec
INSERT INTO ingestion.connector_status (name, last_outcome, last_start, last_end, last_success, documents, last_error)
VALUES (
    sqlc.arg(name), sqlc.arg(outcome), sqlc.narg(start_time)::timestamptz, sqlc.arg(end_time)::timestamptz,
    CASE WHEN sqlc.arg(outcome)::smallint = 1 THEN sqlc.arg(end_time)::timestamptz END,
    sqlc.arg(documents), sqlc.arg(error)
)
ON CONFLICT (name) DO UPDATE
SET last_outcome = EXCLUDED.last_outcome, last_start = EXCLUDED.last_start, last_end = EXCLUDED.last_end,
    last_success = CASE WHEN EXCLUDED.last_outcome = 1 THEN EXCLUDED.last_end ELSE ingestion.connector_status.last_success END,
    documents = EXCLUDED.documents, last_error = EXCLUDED.last_error, updated_at = now()
WHERE ingestion.connector_status.last_end IS NULL OR ingestion.connector_status.last_end <= EXCLUDED.last_end;
