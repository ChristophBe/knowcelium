import asyncio
import hashlib
import json
import math
import re
from collections.abc import AsyncGenerator, Sequence

from .base import (
    Chunk,
    GenerationOptions,
    Message,
    ModelInfo,
    ModelKind,
    NotSupportedError,
    PullProgress,
    Role,
    Status,
    ToolCall,
    ToolSpec,
)

# A user message containing `[tool:NAME]` or `[tool:NAME {"arg": 1}]` makes the
# fake model call the tool NAME (when the request offers it) with those arguments;
# several triggers are called one after the other, in the order they are written.
_TOOL_TRIGGER = re.compile(r"\[tool:([\w.-]+)")


def _triggers(text: str) -> list[tuple[str, str]]:
    """The (tool, arguments JSON) of each `[tool:NAME]` or `[tool:NAME {json}]` in `text`.
    The arguments are decoded as JSON, so they can hold any text, also `}]`; a
    trigger whose arguments are not valid JSON calls the tool without any."""
    found = []
    for match in _TOOL_TRIGGER.finditer(text):
        rest = text[match.end() :]
        arguments = "{}"
        if rest.startswith(" "):
            try:
                _, end = json.JSONDecoder().raw_decode(rest, 1)
            except ValueError:
                end = 0
            if rest[end : end + 1] == "]":
                arguments = rest[1:end]
        elif not rest.startswith("]"):
            continue
        found.append((match[1], arguments))
    return found


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class FakeProvider:
    """Deterministic provider for tests and for running the stack without a
    model server. Generation echoes the last user message, optionally waiting
    `token_delay` seconds before each word (to watch or stop a stream);
    a user message with a `[tool:NAME]` trigger makes it call that tool when
    the request offers it, and the tool messages after it are answered with
    their content;
    embeddings are derived from a hash of the model and the text, so identical
    text gets identical vectors for one model."""

    name = "fake"
    default_chat_model = "fake-chat"

    def __init__(
        self, dimensions: int, token_delay: float = 0, embedding_model: str = "fake-embed"
    ) -> None:
        self._dimensions = dimensions
        self._token_delay = token_delay
        # Settable, to try out a change of the embedding model without a model server.
        self.default_embedding_model = embedding_model

    async def generate(
        self,
        model: str,
        messages: list[Message],
        options: GenerationOptions,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncGenerator[Chunk]:
        last = messages[-1] if messages else None
        call = self._tool_call(messages, tools)
        if call:
            yield Chunk(
                done=True,
                tool_calls=(call,),
                input_tokens=sum(len(m.content.split()) for m in messages),
                output_tokens=len(call.arguments_json.split()) or 1,
            )
            return
        if last and last.role is Role.TOOL:
            results = " ".join(m.content for m in self._since_user(messages) if m.role is Role.TOOL)
            text = f"(fake answer) The tool returned: {results}"
        else:
            text = f"(fake answer) You said: {last.content if last else ''}"
        words = text.split(" ")
        for i, word in enumerate(words):
            if self._token_delay:
                await asyncio.sleep(self._token_delay)
            yield Chunk(delta=word if i == 0 else " " + word)
        yield Chunk(
            done=True,
            input_tokens=sum(len(m.content.split()) for m in messages),
            output_tokens=len(words),
        )

    @staticmethod
    def _since_user(history: list[Message]) -> list[Message]:
        """The messages after the last user message."""
        for i in range(len(history) - 1, -1, -1):
            if history[i].role is Role.USER:
                return history[i + 1 :]
        return history

    @classmethod
    def _tool_call(cls, history: list[Message], tools: Sequence[ToolSpec]) -> ToolCall | None:
        user = next((m for m in reversed(history) if m.role is Role.USER), None)
        if not tools or user is None:
            return None
        offered = {t.name for t in tools}
        triggers = [t for t in _triggers(user.content) if t[0] in offered]
        answered = sum(m.role is Role.TOOL for m in cls._since_user(history))
        if answered >= len(triggers):
            return None
        name, arguments = triggers[answered]
        return ToolCall(
            id=f"call-{name}-{sum(m.role is Role.TOOL for m in history)}",
            name=name,
            arguments_json=arguments,
        )

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        return [self._vector(f"{model}:{text}") for text in inputs]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self._dimensions:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            values.extend((b - 127.5) / 127.5 for b in digest)
            counter += 1
        values = values[: self._dimensions]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]:
        # Share of the query's words found in the document: lexical, but
        # deterministic, so tests can tell a reordering from the input order.
        words = _words(query)
        if not words:
            return [0.0] * len(documents)
        return [len(words & _words(d)) / len(words) for d in documents]

    async def pull_model(self, model: str) -> AsyncGenerator[PullProgress]:
        raise NotSupportedError("the fake provider has no models to pull")
        yield  # makes this an async generator, like the providers that can pull

    async def delete_model(self, model: str) -> None:
        raise NotSupportedError("the fake provider has no models to delete")

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id=self.default_chat_model, kind=ModelKind.CHAT, supports_tools=True),
            ModelInfo(id=self.default_embedding_model, kind=ModelKind.EMBEDDING),
        ]

    async def status(self) -> Status:
        return Status(healthy=True, detail="fake provider")

    async def aclose(self) -> None:
        return None
