-- +goose Up
-- What the worker last reported about each connector (ListConnectors). Health
-- is not stored: it is derived when read, from the last outcome and the times.
CREATE TABLE ingestion.connector_status (
    name             text PRIMARY KEY,
    kind             text NOT NULL DEFAULT '',
    enabled          boolean NOT NULL DEFAULT true,
    interval_seconds integer NOT NULL DEFAULT 0,
    -- ingestion.v1.SyncOutcome of the last run; 0 while it has not run.
    last_outcome     smallint NOT NULL DEFAULT 0,
    last_start       timestamptz,
    last_end         timestamptz,
    last_success     timestamptz,
    documents        integer NOT NULL DEFAULT 0,
    last_error       text NOT NULL DEFAULT '',
    updated_at       timestamptz NOT NULL DEFAULT now()
);
