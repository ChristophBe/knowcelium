import json
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class ProviderError(Exception):
    """A provider call failed. The message is logged, never sent to callers."""


class ProviderUnavailableError(ProviderError):
    """The provider cannot be reached, is overloaded or timed out; try again later."""


class ProviderRateLimitedError(ProviderUnavailableError):
    """The provider rejected the call because a rate limit or quota is used up."""


class ModelNotFoundError(ProviderError):
    """The provider does not know the requested model."""


class ProviderAuthError(ProviderError):
    """The provider rejected kb's credentials (a missing, wrong or revoked key)."""


class NotSupportedError(ProviderError):
    """The provider does not offer this operation (e.g. embeddings)."""


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelKind(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call; `parameters_json_schema` is a JSON Schema string."""

    name: str
    description: str
    parameters_json_schema: str


def tool_schema(tool: "ToolSpec") -> dict[str, Any]:
    """The tool's parameters as a JSON Schema object (an empty one when none are given)."""
    return json.loads(tool.parameters_json_schema or "{}") or {"type": "object", "properties": {}}


@dataclass(frozen=True)
class ToolCall:
    """A complete tool call; `arguments_json` is a JSON object string."""

    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    # On an assistant message: the calls it made. On a tool message: the id of
    # the call it answers.
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True)
class GenerationOptions:
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class Chunk:
    """One streamed piece of a generation. The final chunk has done=True and
    carries token usage when the provider reports it."""

    delta: str = ""
    done: bool = False
    # Complete calls on the final chunk; a provider joins streamed argument deltas first.
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelInfo:
    id: str
    kind: ModelKind
    supports_tools: bool = False


@dataclass(frozen=True)
class PullProgress:
    """One streamed step of a model download. `total` is 0 for steps without a
    size (e.g. "pulling manifest"). The final one has done=True."""

    status: str
    completed: int = 0
    total: int = 0
    done: bool = False


@dataclass(frozen=True)
class Status:
    healthy: bool
    detail: str = ""


class Provider(Protocol):
    """Adapter for one LLM vendor. Implementations live next to this file and
    are registered in knowcel_llm.providers.REGISTRY. Failures are raised as
    ProviderError, so the server needs no knowledge of a vendor's client."""

    name: str
    # Empty when the provider has no models of that kind; such a provider can't
    # be chosen for that task (see knowcel_llm.providers.build_providers).
    default_chat_model: str
    default_embedding_model: str

    # Providers or models without tool calling raise NotSupportedError when
    # `tools` is not empty.
    def generate(
        self,
        model: str,
        messages: list[Message],
        options: GenerationOptions,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncGenerator[Chunk]: ...

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]: ...

    # Scores in [0, 1], one per document, higher is more relevant. Providers
    # without a chat model raise NotSupportedError.
    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]: ...

    async def list_models(self) -> list[ModelInfo]: ...

    # Providers that can't manage their models raise NotSupportedError.
    def pull_model(self, model: str) -> AsyncGenerator[PullProgress]: ...

    async def delete_model(self, model: str) -> None: ...

    async def status(self) -> Status: ...

    async def aclose(self) -> None: ...
