# 0017. Connectors are independently deployed services behind an HTTP contract

- Status: Accepted
- Date: 2026-11-28

## Context

A connector is a Python class that the ingestion worker loads ([Build a connector](../connectors.md)). Administrators list instances in a connectors file that only the worker reads, and the Connectors page is read-only. That has limits:

- A connector ships, scales and fails with the worker. Writing one means writing Python in this repository, and a connector for a system that has a good client in another language needs a port.
- Adding a connector needs a deployment of the worker with an edited file. There is no way for a service to announce itself, and no place for an administrator to add one or to keep a credential.
- Live search takes a detour: chat → ingestion service → NATS → worker → connector ([ADR 0015](0015-live-retrieval-through-connectors.md)).
- A source such as an MCP server needs credentials and tools that the class-based SDK has no place for.

Options considered:

- **Keep classes in the worker, add a database for instances.** Solves configuration, not deployment or language.
- **gRPC for connector services.** Fits the repository's protos, but is heavy for a small third-party service in another language, and a plain HTTP service is easier to run behind a gateway.
- **HTTP/JSON with an OpenAPI contract.** Any language can implement it, `curl` can talk to it, and the repository already generates code from contracts.

## Decision

We will make a connector a small web service, deployed independently of Knowcelium, that speaks the HTTP/JSON contract in [`connector-api/openapi.yaml`](../../connector-api/openapi.yaml).

- **The contract (v1)** is `GET /v1/info`, `POST /v1/validate`, `POST /v1/changes`, `POST /v1/content` and `POST /v1/search`. It is versioned by its path; additions that older clients can ignore stay in v1. The service describes itself in `/v1/info`: its kind, capabilities (`sync`, `search`), whether it lists every item (`complete`) and a JSON Schema of the settings of an instance. A property marked `writeOnly` is a secret.
- **Services hold no instance state.** The settings of an instance, secrets included, travel in each request, so one service can serve many instances (one MCP service, many MCP servers). Knowcelium stores them, the secrets encrypted, and sends them only over https unless an administrator allows http for that service.
- **Records and snippets** keep the meaning they have in the SDK: `external_id`, `version`, `deleted`, `complete`, `since`, and snippets with a citation URL. The runner, the state and the status events stay as they are; a worker-side adapter implements the existing `Source` over the contract.
- **Authentication** from Knowcelium to a service is a bearer secret issued when the service is approved. How a service gets known is specified with the registry: it registers with an administrator-issued token and stays `pending` until approved, or an administrator adds it by URL.
- **From ADR 0015 this stays:** live search is off unless an administrator turns it on per instance, a search runs with the connector's own credentials and cannot filter by user, the caller's teams come from iam, and one connector that fails or is slow is left out and named in `unavailable_connectors`. **What is replaced** is the transport: the ingestion service asks a connector service over HTTP and no longer goes through the worker over NATS (`knowcel.connectors.search`).
- **Language:** the Python SDK keeps the `Connector` class and serves the contract. The contract's Go and Python types are generated from the OpenAPI file by `task gen` and committed (CI fails on drift), like the protobuf bindings.
- **Removed:** the in-process kinds, the connectors file and the watched-folder connector.

## Consequences

- A connector is written in any language and runs, scales and is upgraded on its own. A broken connector can no longer take the worker down with it.
- Knowcelium gains a registry (services, instances, registration tokens, encrypted secrets) and an HTTP surface for registration. Search and tools depend on the connector service being up; a failure stays isolated to its instances.
- Secrets travel to services on every call, so https and the per-service bearer secret matter. A malicious or compromised connector service sees the credentials of its own instances only.
- Existing connectors files stop working; this is a breaking change, and the showcase connectors become services.
- Work is tracked in epic #446. We would revisit HTTP if connector calls needed streaming or server push (for example change notifications from the source).
