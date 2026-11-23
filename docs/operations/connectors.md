# Connectors

A connector keeps documents in step with an external system. The ingestion worker runs the connectors listed in its connectors file on a schedule: it lists what the source has, adds documents for new items, replaces the file of changed ones and deletes the documents of items that are gone. Everything it creates goes through the same upload, processing and access rules as a user's upload. The `folder` connector watches a directory; two more, `showcase_engineering` and `showcase_logistics`, read the mock systems of the [showcase](#showcase-connectors). To write one, see [Build a connector](../connectors.md). The runtime lives in `modules/ingestion/worker/src/knowcel_ingestion_worker/connectors/`.

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
    sync: true              # copy the source into documents; false for a connector that is only searched live
    live_search: false      # also search the source at question time (see below)
    enabled: true
    settings:               # specific to the kind
      path: /watch
      recursive: true
```

- **Owner.** The connector acts as this user, who must be a platform admin; documents are owned by them. A connector whose owner is not a platform admin does not sync and reports that as its error.
- **Sharing.** The documents are shared with `team_ids` (the owner has to be a member of each) or public. The document module has no private mode for documents yet, so there is no default: a connector that sets neither is rejected.
- **Invalid entries** never stop the others. The worker logs the problem and records it as that entry's error. The status of an entry that has no valid name is stored under `invalid.<name>-<hash>.status`; an entry whose name is also used by a valid one gets the suffix `(entry n)` in its name. Only valid entries claim a name, so a valid entry is not rejected because an earlier invalid one has the same name.

## Live search

A connector whose kind implements `search` can also be asked at question time, so that fast-changing data does not have to be synced. Chat asks every such connector the user may read while it searches documents, merges what they return with the document passages and cites it; the answer's sources show the connector's name, a **Live** label and a link to the original. See [Build a connector](../connectors.md#searchquery-limit-optional).

```yaml
  - name: stock
    kind: folder            # kinds that implement search; the folder searches its text files
    owner: 3f5c6d3e-...
    public: true
    sync: false             # live only: nothing is copied
    live_search: true
    settings: {path: /watch}
```

- **Opt in.** Live search is off until `live_search: true`. A live search runs with the connector's own access to the source, not the asking user's, and a connector cannot filter by user. So everyone who may read the connector (`public: true`, or a member of one of its `team_ids`) sees whatever its search returns, and you should only enable it for sources where that is fine. Only a platform admin can change this file, and the connector's owner must be a platform admin when it is searched (as for syncing). With iam down, only public connectors are searched.
- **Scope.** A conversation limited to chosen documents does not ask connectors; one limited to teams asks only connectors shared with those teams.
- **Failures.** Connectors are asked concurrently with a timeout (`KNOWCEL_CONNECTOR_SEARCH_TIMEOUT` of `ingestion-service`, 5 s). One that fails or is too slow is skipped; the answer then says **Some sources were unavailable** and names it, and the other sources still answer. With `ingestion-service` or the worker stopped, chat answers from documents alone. Chat asks with its own `KNOWCEL_CONNECTORS_TIMEOUT` (8 s), `KNOWCEL_CONNECTORS_TOP_K` snippets per connector and ranks them with `KNOWCEL_CONNECTORS_SCORE`; `KNOWCEL_CONNECTORS_ENABLED=false` turns live retrieval off. See [Configuration](../configuration.md).
- **How it is reached.** Chat calls `IngestionService.SearchConnectors`; the service asks the worker over NATS (request/reply on `knowcel.connectors.search`), see [ADR 0015](../adr/0015-live-retrieval-through-connectors.md). Run at least one `ingestion-worker` for it to work.

## Watched folder (`kind: folder`)

| Setting | Meaning |
|---|---|
| `path` | The directory, as the worker sees it. The compose stack mounts `KNOWCEL_WATCH_DIR` (default `modules/ingestion/watch/`) read-only as `/watch`. |
| `recursive` | Also read subdirectories (default `true`). |

It reads the file types the worker can process (PDF, Word, HTML, Markdown and plain text formats) and skips hidden files and directories and files that are links leading outside the folder (a warning in the log names them). A folder that cannot be read or is missing fails the run instead of counting as empty, and so does a path inside it that cannot be read: the documents are kept. Live search finds the paragraphs of its text, Markdown and HTML files that contain the words of the question (PDF and Word files are only found once synced). A file's external id is its path inside the folder, so editing it replaces the document's file and removing it deletes the document. Renaming or moving a file removes the old document and adds a new one.

## Showcase connectors

`showcase_engineering` and `showcase_logistics` sync the mock engineering and logistics systems of the fictional e-bike maker Velora Mobility (`examples/showcase/`). They are examples of the [connector SDK](../connectors.md) and are not started with the main stack. `task showcase:up` starts the stack with both mock systems and mounts `examples/showcase/connectors.yaml` (public documents, a sync every minute) instead of the default connectors file, whatever `KNOWCEL_CONNECTORS_CONFIG` says in `.env`. The owner is the dev admin `alice@example.com` by her id; until she has signed in once every sync fails with "not a platform admin" and is retried at the next interval.

| Setting | Meaning |
|---|---|
| `base_url` | The mock system as the worker reaches it (`http://showcase-engineering:8091`, `http://showcase-logistics:8092`). |
| `page_size` | Records per request, 1 to 100 (default 50). |
| `timeout_seconds` | Seconds a request may wait for connecting, sending and each answer (default 10). |

- **Engineering** creates a document per part, specification and change request. A document's metadata names the `supplier_id` (and `part_id` or `part_ids`), which links it to the logistics documents.
- **Logistics** creates a document per supplier and stock record, with `supplier_id` and `part_id` in the metadata. Shipments are not copied: their status changes too quickly, so the connector answers `search` by asking the system (shipment status, delays, shipments of a supplier named by its ID). Live retrieval does not call it yet.
- Both ask only for records updated since the last successful sync, so a second sync changes nothing and an edited record replaces its document. The mock systems never delete records, so nothing is deleted.

## How a sync works

- **Change detection.** Each item has a version (for files, modification time and size). An item whose version is unchanged is not read again; a changed one is read and uploaded only if its content differs. A sync that did not fail does not upload anything twice.
- **Last success.** A sync records its start time when it succeeds and passes it to the next one, so a source that can report changes (`since`) only has to list those. A failed run does not move it: the next run starts again from the last success, skipping what already worked.
- **Deletes.** A source that lists everything (`complete`, like the folder) has the documents of items missing from the listing deleted, but only after a run without failures, and never when the listing is empty while documents exist: that run fails with an error saying so (an unmounted folder looks like an emptied one). To really remove everything, delete the documents by hand and the connector's `<name>.item.*` keys, or remove the connector. A source that lists only changes marks removed items as `deleted`.
- **Documents edited by hand.** What a sync overwrites (file, title, metadata) is also changed by the document's owner; the document page tells the owner that the document comes from a connector. A document deleted by hand is added again at the next change.
- **Empty files.** An item that is empty (for instance a file truncated to 0 bytes) is not uploaded; its document keeps the old content. The version is remembered so the file is not read at every sync, and the status says `n items skipped; first: ...` until the item has content again. The run still counts as successful.
- **Several workers.** A lease in the key-value bucket keeps two workers from syncing the same connector at once. A running sync renews it, so a long sync is not started a second time. A failing state store (NATS) fails that sync only: it is logged and retried at the next interval, and the lease is always released.

State (the bookkeeping of each connector, the document of each item) lives in the JetStream key-value bucket `ingestion_connectors`. If it is lost, the next sync adds the items again as new documents.

## Status and errors

Two copies of a connector's status exist:

- **The worker's** is stored under `<name>.status` in the bucket: start and end of the last run, last successful run and its start (where the next run continues), number of synced documents and the last error (empty when the run succeeded). It is the worker's own memory, not meant to be read.
- **The ingestion service's** is what people read: `IngestionService.ListConnectors` and `GetConnector`, for platform admins only (`PERMISSION_DENIED` for everyone else, `UNAVAILABLE` while iam, which tells who is one, is down). The worker reports to it by event: `knowcel.ingestion.connectors_configured` at start and every five minutes with every entry of the connectors file (valid or not; connectors no longer listed disappear, one that never ran is `UNKNOWN`), and `knowcel.ingestion.connector_synced` after each sync run. A lost event only delays the status until the next run.

Errors caused by the settings (an unknown kind, a missing directory, an owner who is not a platform admin) are recorded in both, not only in the worker's log.

### Health

The service derives a connector's health when it is read:

| Health | When |
|---|---|
| `HEALTHY` | The last sync succeeded, and it ended within twice the connector's interval. |
| `DEGRADED` | The last sync had partial failures: some items synced, others did not (`last_error` names the first). |
| `FAILING` | The last sync failed: it could not run (settings, permissions, an unreachable source), or no item synced (`last_error` says why). |
| `STALE` | The last sync ended more than twice the interval ago, whatever its outcome: syncs have stopped, for instance because the worker is down. |
| `UNKNOWN` | The connector has not synced yet. |

A disabled connector or an invalid entry (no interval) is never `STALE`. Skipped empty files do not fail a run; the note shows as `last_error` while the connector stays `HEALTHY`. The worker announces its connectors every five minutes, so a removed connector disappears from the list within that time, and a connector that is listed but never ran is `UNKNOWN`. Platform admins see the connectors and their health on the **Connectors** page of the web UI (`/m/ingestion/connectors`), which refreshes every 30 seconds; the [user manual](../user-manual/ingestion.md#connectors) describes it.
