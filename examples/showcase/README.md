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

## Ask across both systems

Start the showcase and look at both connectors, then ask in chat:

1. Sign in as `alice@example.com` once (she is the owner of the connectors; until then every sync fails with "not a platform admin").
2. `task showcase:up`, then open **Connectors** and wait until `showcase-engineering` and `showcase-logistics` are **Healthy** (the first sync takes up to a minute).
3. Open **Chat** and ask one of these. Each needs both systems, and each answer cites both.

| Question | Answered from | Expect |
|---|---|---|
| Which open change requests concern parts from our lowest-rated supplier, and why was the change requested? | Synced documents: engineering change requests and logistics suppliers | CR-3001 (second source for 21700 cells) and Voltaic Cells Ltd, rated C, with its late deliveries |
| Which open change requests affect parts whose supplier has a delayed shipment? | Synced engineering documents and the live shipment search | CR-3001 (SHP-5002, 12 days late, cell shortage) and CR-3004 (SHP-5004, 7 days late, customs hold) |
| How many torque sensors are in stock and when does Sensora Precision deliver more? | Synced stock document and the live shipment search | 95 on hand; SHP-5004, 300 sensors, 7 days late |

The first is answered from synced documents alone. Shipments are not copied, so the second and third
need the live search: while the answer is prepared, the step list shows **showcase-logistics**, and the
answer lists it under **Connector sources** with a **Live** label next to the engineering documents.
Stop the logistics mock (`docker compose stop showcase-logistics`) and ask again to see it reported
as unavailable while the answer still arrives from documents.

### Let the model pick the searches

With a chat model that supports tool calling (the model list shows which), chat does not search the question as typed: the model first searches the documents and then, for what only the live system knows, asks the logistics connector. Ask the second question again and watch the step list:

> Which open change requests affect parts whose supplier has a delayed shipment?

1. **Searched Your documents for “…”: found N passages**, a query the model wrote, for example the change requests and the delayed supplier.
2. **Searched showcase-logistics for “delayed”: found N results**, the live shipment search.

The answer cites CR-3001 and CR-3004 under **Sources** and the shipments under **Connector sources** with the **Live** label. The steps collapse into **Searched for …** and are the same after a reload. A model without tool support gets the fixed search of the question instead, without queries in the steps.

The fake LLM provider (`KNOWCEL_LLM_PROVIDER=fake`, as in the e2e stacks) never searches on its own. Script it with triggers in the question; it calls them one after the other and its answer echoes what they found:

```text
Which open change requests affect parts whose supplier has a delayed shipment? [tool:search_knowledge_base {"query": "change requests delayed shipment supplier"}] [tool:search_connectors {"query": "delayed"}]
```

`KNOWCEL_AGENTIC=false` turns the model's own searches off (the shared e2e stacks do, so that their questions are searched as typed).

For the user's view see the [user manual](../../docs/user-manual/connectors.md).

```sh
uv run pytest -q --rootdir examples/showcase examples/showcase   # unit tests
```

A browser check of the three questions and of the model-chosen searches, also after a reload, is in `tests/browser/showcase.spec.ts`
(`KNOWCEL_E2E_SHOWCASE=1`, with `KNOWCEL_E2E_WEB` set to the running web shell, as for the connectors page check).
