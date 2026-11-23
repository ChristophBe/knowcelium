# Showcase mock systems

Stand-ins for an engineering system (PLM / issue tracker) and a logistics system (ERP / warehouse)
of the fictional e-bike maker Velora Mobility, so connectors can be built and demonstrated without a
vendor system. All data is made up. Both are read-only JSON-over-HTTP services on the Python
standard library.

```sh
task up -- --profile showcase       # the whole stack plus both mocks
curl 'localhost:8091/parts?limit=5'
curl 'localhost:8092/search?q=delayed'
```

| Service | Port (override) | Endpoints |
|---|---|---|
| engineering | 8091 (`KNOWCEL_SHOWCASE_ENGINEERING_PORT`) | `/parts`, `/specifications`, `/change-requests` (+ `/<id>`) |
| logistics | 8092 (`KNOWCEL_SHOWCASE_LOGISTICS_PORT`) | `/suppliers`, `/stock`, `/shipments` (+ `/<id>`), `/search` |

Inside the compose network they are `showcase-engineering:8091` and `showcase-logistics:8092`.

Every list endpoint returns `{items, total, limit, offset, next_offset}` (`next_offset` is `null` on
the last page), oldest change first, and takes:

- `limit` (1 to 100, default 20) and `offset` (default 0)
- `updated_since`: an ISO 8601 timestamp; returns records with `updated_at` at or after it (no offset means UTC; write an offset's `+` as `%2B`, though a bare `+01:00` is accepted too)
- exact-match filters (a blank value, or a parameter the endpoint does not know, is a 400): `status`/`supplier_id` on parts, change requests and shipments, `part_id` on specifications and stock

`GET /search?q=<words>[&type=supplier|stock|shipment]` on logistics matches records containing every word
(case-insensitive) and takes the paging parameters and `updated_since` too; each hit carries its `type`.

The two systems are linked by supplier IDs (`SUP-1001` to `SUP-1008`): engineering parts and change requests
name a `supplier_id` that exists in logistics, and logistics stock and shipments name the `part_id` they cover.
Several shipments are delayed (`status: delayed`, with `delay_days` and `delay_reason`).

The `showcase_engineering` and `showcase_logistics` connectors sync them into documents (see [Connectors](../../docs/operations/connectors.md#showcase-connectors)); `task showcase:up` starts the stack with the mocks and both connectors enabled.

```sh
uv run pytest -q --rootdir examples/showcase examples/showcase   # unit tests
```
