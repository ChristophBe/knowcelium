# 0015. Search connectors live at question time, from chat through ingestion

- Status: Accepted
- Date: 2026-11-23

## Context

Connectors copy a source system into documents on a schedule. Fast-changing data (stock levels, shipments) is stale by the time it is synced, and some sources are too large to copy. The connector SDK has an optional `search` for asking the source directly, but nothing called it: chat only reads the document module's `SearchChunks`.

Chat has to reach the connectors, which live in the ingestion worker (Python, a process without a gRPC server). Options considered:

- **Chat calls the worker directly.** The worker serves no gRPC, and an extra port per worker complicates scaling and the Helm chart.
- **A new module for live sources.** More moving parts for what is one RPC and no state.
- **Chat calls the ingestion service, which asks the worker over NATS.** Chat depends on one more module through a generated client; the service-to-worker hop uses the NATS server both already have.

A live search runs with the connector's own credentials: the SDK's `search(query, limit)` does not know who is asking, so a connector cannot filter by user.

## Decision

We will add `IngestionService.SearchConnectors(query, connector_ids, limit, team_ids)` and add `ingestion` to the `depends_on` of `chat`.

- **Chat → ingestion** is gRPC with the generated client and a timeout. Ingestion is a soft peer: `UNAVAILABLE`, `DEADLINE_EXCEEDED` or any other error is logged and the answer is written from documents alone. `PeerRetriever` asks the connectors while it searches documents, merges the snippets with the passages, and cites them like other sources (`Citation.connector`, `Citation.source_url`). A question limited to chosen documents does not ask connectors; one limited to teams asks only connectors shared with those teams.
- **Service → worker** is a core NATS request/reply on `knowcel.connectors.search` carrying `ConnectorSearchRequest` and `ConnectorSearchReply` (events.proto), answered through the queue group `ingestion-worker`, so any running worker answers. The subject is deliberately outside the `INGESTION` stream (`knowcel.ingestion.>`), which would acknowledge the request itself. With no worker running NATS reports no responders and the service returns `UNAVAILABLE`. Workers answer even when they run no connector, which tells "no connectors" from "no worker".
- **Failure isolation.** The worker asks all connectors concurrently, each with its own timeout (80 % of the service's `KNOWCEL_CONNECTOR_SEARCH_TIMEOUT`, 5 s). A connector that raises, times out or cannot be created is left out and named in `unavailable_connectors`; the others still answer. Chat saves the names with the answer (`ChatMessage.unavailable_sources`) and the UI says that some sources were unavailable. A whole worker or ingestion service that cannot be reached cannot name connectors, so it is logged but not reported to the user.
- **Who may see what.** The service resolves the caller's teams through iam (never from the request) and sends them with the search; the worker asks only connectors that are public or shared (`team_ids`) with one of those teams. Because a connector cannot filter by user, live search is **off unless an administrator turns it on per connector** (`live_search: true` in the connectors file, which only a platform admin can edit), and the connector's owner must be a platform admin at search time. Everyone allowed to read the connector sees whatever its search returns, so such a connector must only expose what all of them may see. While iam is down, only public connectors are searched.
- **Ranking.** Snippets have no similarity. They are cited with a fixed score (`KNOWCEL_CONNECTORS_SCORE`, 0.8, minus 0.01 per rank), above weakly related passages and below close matches, and are never reranked.
- A connector can be live only (`sync: false`), copying nothing.

## Consequences

- Chat answers can include data that is seconds old; every answer pays at most the connector timeout when a connector is slow.
- One more soft dependency of chat, one more setting block (`KNOWCEL_INGESTION_ADDR`, `KNOWCEL_CONNECTORS_*`), and a NATS subject other than events that has to stay outside the stream.
- A connector that can filter by user would need the asker's identity in `search`; that is a later SDK change and would let such connectors be searched without the administrator's approval.
- Snippet text goes into the prompt as it is; a connector is trusted as far as an administrator trusts it. Citation links open only `http` and `https` addresses.
- Revisit if the connector count or latency makes a per-question fan-out too slow (cache, or sync instead).
