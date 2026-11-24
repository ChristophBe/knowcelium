# 0016. Give chat tool calling natively through the llm module

- Status: Accepted
- Date: 2026-11-24

## Context

Chat retrieves once with the raw user message. Follow-ups are searched verbatim, small talk triggers retrieval, and connectors ([ADR 0015](0015-live-retrieval-through-connectors.md)) can only be merged in at a fixed step. If the model chooses when and what to search, these cases improve. That needs tool calling.

Options considered:

- **LangChain/LangGraph in `chat`.** It ships agent loops, but its provider integrations call vendors directly from `chat`, which bypasses the gateway ([ADR 0005](0005-llm-module-is-the-only-vendor-gateway.md)) and with it provider configuration, model listing and usage accounting. It would duplicate the provider layer that `llm` already has and add a second streaming and cancellation model next to `AnswerRunner`.
- **Native tool calling in `llm`.** The `llm` contract gains tool specs, tool calls and a tool message role, and each provider maps them to its vendor format. `chat` runs a small bounded loop itself and keeps `AnswerRunner` for streaming, stop and partial answers.

Not every model can call tools, especially local ones served through Ollama.

## Decision

We will add tool calling natively to the `llm` module and will not use LangChain or LangGraph.

- **`llm` owns the vendor mapping.** The contract changes are additive (`ToolSpec`, `ToolCall`, a `tool` message role, `supports_tools` on `Model`). Providers translate them; `chat` never sees a vendor format.
- **`chat` owns the loop.** A bounded agent loop (`max_tool_steps`) calls tools that reuse the existing retrieval clients, including the connector search of ADR 0015. Cancel and stop stay in `AnswerRunner`, so there is one cancellation model.
- **Fallback.** A model that reports `supports_tools = false`, or an installation with the `agentic` setting off, uses the fixed retrieval pipeline unchanged.
- **Relation to ADR 0015.** Connector search stays `IngestionService.SearchConnectors` with the same permissions and failure isolation. The agent loop only changes who decides to call it: the model, through `search_connectors`, instead of a fixed step. A connector that fails is reported to the model as unavailable and the answer still arrives.

## Consequences

- One provider layer, one place for usage accounting, one streaming and cancel path.
- Each provider must map tools itself, and tool support is detected per model; local models vary.
- We build the loop, step bound and source numbering ourselves instead of getting them from a framework. This is small for a single-agent, bounded loop.
- Revisit LangGraph only if durable multi-agent graphs become a need.
