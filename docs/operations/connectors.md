# Connectors

A connector keeps documents in step with an external system. The ingestion worker runs the connectors listed in its connectors file on a schedule: it lists what the source has, adds documents for new items, replaces the file of changed ones and deletes the documents of items that are gone. Everything it creates goes through the same upload, processing and access rules as a user's upload. The first connector, `folder`, watches a directory. The runtime lives in `modules/ingestion/worker/src/knowcel_ingestion_worker/connectors/`.

## Configure a connector

Connectors are listed in a YAML file, `KNOWCEL_CONNECTORS_FILE` of the ingestion worker (`modules/ingestion/connectors.yaml` in the compose stack, or the file `KNOWCEL_CONNECTORS_CONFIG` points to). Restart `ingestion-worker` after changing it.

```yaml
connectors:
  - name: handbook          # lower-case letters, digits, "-" and "_"; names the origin shown on documents
    kind: folder
    owner: 3f5c6d3e-...     # the id of the platform admin the connector runs as
    team_ids: [8a1b...]     # who can read what it syncs ...
    # public: true          # ... or everyone; one of the two is required
    interval_seconds: 300   # time between the starts of two syncs, at least 10
    enabled: true
    settings:               # specific to the kind
      path: /watch
      recursive: true
```

- **Owner.** The connector acts as this user, who must be a platform admin; documents are owned by them. A connector whose owner is not a platform admin does not sync and reports that as its error.
- **Sharing.** The documents are shared with `team_ids` (the owner has to be a member of each) or public. The document module has no private mode for documents yet, so there is no default: a connector that sets neither is rejected.
- **Invalid entries** never stop the others. The worker logs the problem and records it as that connector's error.

## Watched folder (`kind: folder`)

| Setting | Meaning |
|---|---|
| `path` | The directory, as the worker sees it. The compose stack mounts `KNOWCEL_WATCH_DIR` (default `modules/ingestion/watch/`) read-only as `/watch`. |
| `recursive` | Also read subdirectories (default `true`). |

It reads the file types the worker can process (PDF, Word, HTML, Markdown and plain text formats) and skips hidden files and directories. A file's external id is its path inside the folder, so editing it replaces the document's file and removing it deletes the document. Renaming or moving a file removes the old document and adds a new one.

## How a sync works

- **Change detection.** Each item has a version (for files, modification time and size). An item whose version is unchanged is not read again; a changed one is read and uploaded only if its content differs. A sync that did not fail does not upload anything twice.
- **Last success.** A sync records its start time when it succeeds and passes it to the next one, so a source that can report changes (`since`) only has to list those. A failed run does not move it: the next run starts again from the last success, skipping what already worked.
- **Deletes.** A source that lists everything (`complete`, like the folder) has the documents of items missing from the listing deleted, but only after a run without failures. A source that lists only changes marks removed items as `deleted`.
- **Documents edited by hand.** What a sync overwrites (file, title, metadata) is also changed by the document's owner; the document page tells the owner that the document comes from a connector. A document deleted by hand is added again at the next change.
- **Several workers.** A lease in the key-value bucket keeps two workers from syncing the same connector at once.

State (status of each connector, the document of each item) lives in the JetStream key-value bucket `ingestion_connectors`. If it is lost, the next sync adds the items again as new documents.

## Status and errors

Each connector's status is stored under `<name>.status` in that bucket: start and end of the last run, last successful run and its start, number of synced documents and the last error (empty when the run succeeded). Errors caused by the settings (an unknown kind, a missing directory, an owner who is not a platform admin) are recorded there, not only in the worker's log. A page that shows connectors and their health is planned (issues #259 and #260).

## Limits

- Only the folder connector exists; the SDK for writing others follows (#254).
- The worker uploads through `ingestion-service` and reaches the storage at `KNOWCEL_CONNECTORS_UPLOAD_ENDPOINT` (the presigned URLs name the public storage address). Without that setting it uploads to the address in the URL.
- The Helm chart does not mount a connectors file yet; connectors run in the compose stack.
