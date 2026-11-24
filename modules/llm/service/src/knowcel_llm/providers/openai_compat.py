import asyncio
import json
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

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
)
from .rerank import rerank_with_chat

# Statuses that mean "overloaded or restarting" rather than a bad request.
_RETRYABLE_STATUS = {502, 503, 504}


@dataclass(frozen=True)
class OpenAICompatLimits:
    """Timeouts in seconds and retry policy; see knowcel_llm.config.Settings."""

    connect_timeout: float = 5
    first_token_timeout: float = 120
    generate_timeout: float = 600
    embed_timeout: float = 120
    list_timeout: float = 10
    attempts: int = 3
    retry_delay: float = 0.5


class OpenAICompatProvider:
    """Talks to any server that implements the OpenAI API (OpenAI, vLLM, LM Studio,
    llama.cpp, ...) at `base_url`, which includes the version path (".../v1").

    The server hosts its own models, so pulling and deleting raise NotSupportedError."""

    name = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        chat_model: str,
        embedding_model: str,
        dimensions: int | None = None,
        limits: OpenAICompatLimits | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.default_chat_model = chat_model
        self.default_embedding_model = embedding_model
        self._dimensions = dimensions
        self._limits = limits or OpenAICompatLimits()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # A trailing slash makes httpx join relative paths below the version path.
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=self._timeout(self._limits.list_timeout),
            transport=transport,
        )

    async def generate(
        self,
        model: str,
        messages: list[Message],
        options: GenerationOptions,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncGenerator[Chunk]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [_message_param(m) for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [_tool_param(t) for t in tools]
        if options.temperature is not None:
            body["temperature"] = options.temperature
        if options.max_tokens is not None:
            body["max_tokens"] = options.max_tokens

        deadline = asyncio.get_running_loop().time() + self._limits.generate_timeout
        timeout = self._timeout(self._limits.first_token_timeout)
        input_tokens = output_tokens = 0
        calls: dict[int, dict[str, str]] = {}  # streamed tool calls by index
        try:
            async with self._http.stream(
                "POST", "chat/completions", json=body, timeout=timeout
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    if "error" in event:
                        raise ProviderError(f"openai: {_message(event['error'])}")
                    if usage := event.get("usage"):
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)
                    if asyncio.get_running_loop().time() > deadline:
                        raise ProviderUnavailableError("openai generation exceeded its time limit")
                    for choice in event.get("choices", []):
                        delta = choice.get("delta") or {}
                        if text := delta.get("content"):
                            yield Chunk(delta=text)
                        for part in delta.get("tool_calls") or []:
                            call = calls.setdefault(
                                part.get("index", 0), {"id": "", "name": "", "arguments": ""}
                            )
                            call["id"] = part.get("id") or call["id"]
                            function = part.get("function") or {}
                            call["name"] += function.get("name") or ""
                            call["arguments"] += function.get("arguments") or ""
        except httpx.HTTPError as exc:
            raise _translate(exc) from exc
        yield Chunk(
            done=True,
            tool_calls=tuple(
                ToolCall(c["id"], c["name"], c["arguments"] or "{}")
                for _, c in sorted(calls.items())
            ),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {"model": model, "input": inputs}
        if self._dimensions:
            body["dimensions"] = self._dimensions
        resp = await self._idempotent("POST", "embeddings", self._limits.embed_timeout, json=body)
        # The API does not promise the order of data; each item carries its index.
        data = sorted(resp.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    async def list_models(self) -> list[ModelInfo]:
        resp = await self._idempotent("GET", "models", self._limits.list_timeout)
        return [
            ModelInfo(
                id=m["id"],
                kind=ModelKind.EMBEDDING if "embed" in m["id"].lower() else ModelKind.CHAT,
                # The API does not describe a model's abilities; a model that
                # can't call tools is rejected by the server on the first request.
                supports_tools="embed" not in m["id"].lower(),
            )
            for m in resp.json().get("data", [])
        ]

    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]:
        return await rerank_with_chat(self, model, query, documents)

    async def pull_model(self, model: str) -> AsyncGenerator[PullProgress]:
        raise NotSupportedError("openai-compatible models are hosted by the server, not pulled")
        yield  # makes this an async generator, like the providers that can pull

    async def delete_model(self, model: str) -> None:
        raise NotSupportedError("openai-compatible models are hosted by the server, not deleted")

    async def status(self) -> Status:
        try:
            resp = await self._http.get("models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return Status(healthy=False, detail=f"openai unavailable: {_translate(exc)}")
        return Status(healthy=True, detail=f"openai api at {self._http.base_url}")

    async def aclose(self) -> None:
        await self._http.aclose()

    def _timeout(self, seconds: float) -> httpx.Timeout:
        return httpx.Timeout(seconds, connect=self._limits.connect_timeout)

    async def _idempotent(
        self, method: str, path: str, seconds: float, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        for attempt in range(self._limits.attempts):
            try:
                resp = await self._http.request(
                    method, path, json=json, timeout=self._timeout(seconds)
                )
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                if attempt == self._limits.attempts - 1 or not _retryable(exc):
                    raise _translate(exc) from exc
            await asyncio.sleep(self._limits.retry_delay * 2**attempt)
        raise ProviderError("openai: no attempts configured")


def _tool_param(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": json.loads(tool.parameters_json_schema or "{}")
            or {"type": "object", "properties": {}},
        },
    }


def _message_param(m: Message) -> dict[str, Any]:
    if m.role is Role.TOOL:
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    param: dict[str, Any] = {"role": m.role.value, "content": m.content}
    if m.tool_calls:
        param["content"] = m.content or None
        param["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments_json or "{}"},
            }
            for c in m.tool_calls
        ]
    return param


def _message(error: Any) -> str:
    return str(error.get("message", error)) if isinstance(error, dict) else str(error)


def _retryable(exc: httpx.HTTPError) -> bool:
    """Transient failures only; see the Ollama provider for why connects and
    timeouts are not retried."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, httpx.TransportError) and not isinstance(
        exc, httpx.ConnectError | httpx.TimeoutException
    )


def _translate(exc: httpx.HTTPError) -> ProviderError:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return ProviderAuthError(f"openai returned {code}")
        if code == 404:
            return ModelNotFoundError("the openai server does not have the requested model")
        if code == 429:
            return ProviderRateLimitedError("openai returned 429")
        if code in _RETRYABLE_STATUS:
            return ProviderUnavailableError(f"openai returned {code}")
        return ProviderError(f"openai returned {code}")
    if isinstance(exc, httpx.TimeoutException):
        return ProviderUnavailableError(f"openai timed out: {type(exc).__name__}")
    if isinstance(exc, httpx.TransportError):
        return ProviderUnavailableError(f"openai unreachable: {exc}")
    return ProviderError(f"openai request failed: {exc}")
