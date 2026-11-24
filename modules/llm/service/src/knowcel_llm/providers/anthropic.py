import json
import logging
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaToolParam

from .base import (
    Chunk,
    GenerationOptions,
    Message,
    ModelInfo,
    ModelKind,
    ModelNotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    PullProgress,
    Role,
    Status,
    ToolCall,
    ToolSpec,
    tool_schema,
)
from .rerank import rerank_with_chat

log = logging.getLogger("knowcel_llm")

# Current Claude models offered in ListModels (all chat; Anthropic has no embeddings).
MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")

# Server-side fallback: if the model declines a request for policy reasons, the API
# retries it on a substitute model inside the same call. "default" lets the API pick
# the substitute; on a model without fallbacks the request runs on that model alone.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Error types the API reports, in a status error's body or a mid-stream error event
# (which arrives on an HTTP 200 response, so its status code says nothing).
_AUTH_TYPES = {"authentication_error", "permission_error"}
_UNAVAILABLE_TYPES = {"overloaded_error", "api_error", "timeout_error"}


@dataclass(frozen=True)
class AnthropicLimits:
    """Timeouts in seconds and retry policy; see knowcel_llm.config.Settings. The API
    sends pings while a model thinks, so the read timeout only trips on a stall."""

    connect_timeout: float = 5
    read_timeout: float = 120
    request_timeout: float = 600
    status_timeout: float = 10
    # Attempts per call; the SDK retries connection errors, 408, 409, 429 and 5xx
    # (before the first token only) with backoff.
    attempts: int = 3


class AnthropicProvider:
    """Talks to the Anthropic Messages API (Claude) through the official SDK.

    Chat only: Embed raises NotSupportedError, so pair it with an embedding
    provider. Sampling options (temperature) are not sent: current Claude models
    only accept the defaults."""

    name = "anthropic"
    default_embedding_model = ""

    def __init__(
        self,
        api_key: str | None,
        chat_model: str,
        max_tokens: int,
        limits: AnthropicLimits | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "KNOWCEL_ANTHROPIC_API_KEY is not set; it is required for the anthropic provider"
            )
        self.default_chat_model = chat_model
        self._max_tokens = max_tokens
        self._limits = limits or AnthropicLimits()
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=anthropic.Timeout(
                self._limits.request_timeout,
                connect=self._limits.connect_timeout,
                read=self._limits.read_timeout,
            ),
            max_retries=max(self._limits.attempts - 1, 0),
        )

    async def generate(
        self,
        model: str,
        messages: list[Message],
        options: GenerationOptions,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncGenerator[Chunk]:
        system, turns = to_anthropic_messages(messages)
        if not turns:
            raise ProviderError("anthropic: the request has no user message")
        try:
            async with self._client.beta.messages.stream(
                model=model,
                max_tokens=options.max_tokens or self._max_tokens,
                system=system or anthropic.omit,
                messages=turns,
                tools=[_tool_param(t) for t in tools] if tools else anthropic.omit,
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield Chunk(delta=text)
                final = await stream.get_final_message()
        except anthropic.AnthropicError as exc:
            raise translate_error(exc) from exc
        if final.stop_reason == "refusal":
            log.warning("anthropic declined the request (model %s)", model)
        if final.stop_reason == "max_tokens" and any(b.type == "tool_use" for b in final.content):
            raise ProviderError("anthropic: the answer was cut off inside a tool call")
        usage = final.usage
        yield Chunk(
            done=True,
            tool_calls=tuple(
                ToolCall(block.id, block.name, json.dumps(block.input))
                for block in final.content
                if block.type == "tool_use"
            ),
            input_tokens=usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0),
            output_tokens=usage.output_tokens,
        )

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        raise NotSupportedError(
            "the anthropic provider has no embedding models; use another provider for embeddings"
        )

    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]:
        return await rerank_with_chat(self, model, query, documents)

    async def pull_model(self, model: str) -> AsyncGenerator[PullProgress]:
        raise NotSupportedError("anthropic models are hosted by Anthropic and can't be pulled")
        yield  # makes this an async generator, like the providers that can pull

    async def delete_model(self, model: str) -> None:
        raise NotSupportedError("anthropic models are hosted by Anthropic and can't be deleted")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=m, kind=ModelKind.CHAT, supports_tools=True) for m in MODELS]

    async def status(self) -> Status:
        # Listing one model checks reachability and the key without using tokens.
        try:
            await self._client.with_options(
                timeout=self._limits.status_timeout, max_retries=0
            ).models.list(limit=1)
        except anthropic.AnthropicError as exc:
            return Status(healthy=False, detail=f"anthropic unavailable: {translate_error(exc)}")
        return Status(healthy=True, detail="anthropic api")

    async def aclose(self) -> None:
        await self._client.close()


def _tool_param(tool: ToolSpec) -> BetaToolParam:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": cast(Any, tool_schema(tool)),
    }


def to_anthropic_messages(messages: list[Message]) -> tuple[str, list[BetaMessageParam]]:
    """Splits kb messages into the Messages API's top-level system prompt and a
    history that starts with a user turn and alternates roles. System messages
    anywhere are joined into the system prompt; consecutive messages of one role
    are merged (so the results of parallel tool calls share one user turn);
    empty messages and assistant turns before the first user turn (which the API
    rejects) are dropped. Tool calls become `tool_use` blocks and tool messages
    `tool_result` blocks."""
    system: list[str] = []
    turns: list[tuple[Literal["user", "assistant"], list[dict[str, Any]]]] = []
    for m in messages:
        blocks: list[dict[str, Any]] = []
        if m.role == Role.TOOL:
            blocks.append(
                {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            )
        else:
            if m.content.strip():
                if m.role == Role.SYSTEM:
                    system.append(m.content)
                    continue
                blocks.append({"type": "text", "text": m.content})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": c.id,
                    "name": c.name,
                    "input": json.loads(c.arguments_json or "{}"),
                }
                for c in m.tool_calls
            )
        if not blocks or m.role == Role.SYSTEM:
            continue
        role: Literal["user", "assistant"] = "assistant" if m.role == Role.ASSISTANT else "user"
        if turns and turns[-1][0] == role:
            turns[-1][1].extend(blocks)
        elif turns or role == "user":
            turns.append((role, blocks))
    params: list[BetaMessageParam] = []
    for role, blocks in turns:
        # The API wants the results of tool calls ahead of any other text in a user turn.
        blocks.sort(key=lambda b: b["type"] != "tool_result")
        if all(b["type"] == "text" for b in blocks):
            content: Any = "\n\n".join(b["text"] for b in blocks)
        else:
            content = blocks
        params.append(cast(BetaMessageParam, {"role": role, "content": content}))
    return "\n\n".join(system), params


def translate_error(exc: anthropic.AnthropicError) -> ProviderError:
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return ProviderUnavailableError(f"anthropic unreachable: {type(exc).__name__}")
    if not isinstance(exc, anthropic.APIStatusError):
        return ProviderError(f"anthropic request failed: {exc}")
    kind = exc.type or ""
    code = exc.status_code
    detail = f"anthropic returned {kind or code} (request {exc.request_id})"
    if kind in _AUTH_TYPES or code in (401, 403):
        return ProviderAuthError(detail)
    if kind == "rate_limit_error" or code == 429:
        return ProviderRateLimitedError(detail)
    if kind == "not_found_error" or code == 404:
        return ModelNotFoundError("anthropic does not have the requested model")
    if kind in _UNAVAILABLE_TYPES or code >= 500:
        return ProviderUnavailableError(detail)
    return ProviderError(detail)
