# Connector contract

`openapi.yaml` is the contract between Knowcelium and a connector service ([ADR 0017](../docs/adr/0017-connectors-are-services.md)). A connector service implements it in any language; the Python SDK will serve it for you.

| Path | What it is |
|---|---|
| `openapi.yaml` | The contract, v1. Edit this and run `task gen`. |
| `oapi-codegen.yaml` | Configuration of the Go generator. |
| `go/connectorapi/` | **Generated** Go types. Never edit. |
| `python/` | **Generated** pydantic models (`knowcel_connector_api`). Never edit. |

`task gen` validates the spec, regenerates both packages, and CI fails when they drift. Keep changes additive within v1 (new optional fields, endpoints or capabilities); a break needs a `/v2`.
