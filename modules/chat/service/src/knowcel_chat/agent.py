"""The answer with tools: the model searches the knowledge base and the
connectors as often as it needs, up to `max_tool_steps` calls, then answers."""

import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from knowcel.chat.v1 import chat_pb2

from .chat import (
    AgentScope,
    AnswerDelta,
    AnswerEvent,
    Peer,
    PeerError,
    PeerUnavailableError,
    ProgressChanged,
    PromptMessage,
    PromptRole,
    RetrievalChanged,
    SourcesFound,
    ToolCall,
    ToolSpec,
    source_name,
)
from .config import Settings
from .context import MESSAGE_OVERHEAD_TOKENS, ApproximateTokenCounter, TokenCounter, fit

log = logging.getLogger("knowcel_chat")

_NO_MORE_STEPS = "No more searches are possible. Answer now with what you have."
NO_ROOM = "There is no room left for more results; answer with what you have."

SEARCH_KNOWLEDGE_BASE = "search_knowledge_base"
SEARCH_CONNECTORS = "search_connectors"
READ_DOCUMENT = "read_document"
# The tools whose calls show up as searches; reading a section is part of the answer.
_SEARCHES = (SEARCH_KNOWLEDGE_BASE, SEARCH_CONNECTORS)


class Model(Protocol):
    """The chat model with tool calling. Failures are raised as PeerError."""

    async def supports_tools(self, model: str) -> bool: ...

    def turn(
        self, model: str, prompt: list[PromptMessage], tools: Sequence[ToolSpec]
    ) -> AsyncGenerator[str | ToolCall]:
        """One generation: the text in deltas, then the tools the model called."""
        ...


class DocumentSearch(Protocol):
    """The passages of the documents (and manual) that match a query."""

    async def search_documents(
        self,
        query: str,
        limit: int,
        document_ids: Sequence[uuid.UUID],
        team_ids: Sequence[uuid.UUID],
    ) -> list[chat_pb2.Citation]: ...


class ConnectorSearch(Protocol):
    """Live search of the connectors; any failure is a result, not an error."""

    async def search(
        self,
        query: str,
        limit: int,
        team_ids: Sequence[uuid.UUID],
        connector_ids: Sequence[str] = (),
    ) -> "LiveResult": ...


class LiveResult(Protocol):
    @property
    def citations(self) -> list[chat_pb2.Citation]: ...
    @property
    def unavailable(self) -> list[str]: ...
    @property
    def searched(self) -> list[str]: ...
    @property
    def failed(self) -> bool: ...


class DocumentReader(Protocol):
    async def read(
        self, document_id: uuid.UUID, section: int, team_ids: Sequence[uuid.UUID] = ()
    ) -> chat_pb2.Citation | None:
        """The `section` (from 1) of a document as one source; None past its end
        or when the document is attached to none of `team_ids` (unless empty).
        Failures are raised as PeerError."""
        ...


@dataclass
class _Result:
    """What a tool call gives back: the text for the model and, for the user,
    the state of what was searched."""

    text: str
    retrieval: list[chat_pb2.RetrievalSource]


class _Sources:
    """The sources found while answering. A source gets its number when it is
    first seen and keeps it when another call finds it again."""

    def __init__(self) -> None:
        self.citations: list[chat_pb2.Citation] = []
        self._numbers: dict[tuple[Any, ...], int] = {}

    def number(self, c: chat_pb2.Citation, read: bool = False) -> int:
        """The number of `c`. A section read with read_document is a source of
        its own, even when its first chunk was found by a search before."""
        key = (
            (read, c.document_id, c.chunk_index, c.manual_page, c.manual_section)
            if c.document_id or c.manual_page
            else (c.connector, c.source_url, c.document_title, c.snippet)
        )
        if key not in self._numbers:
            self.citations.append(c)
            self._numbers[key] = len(self.citations)
        return self._numbers[key]


def _specs(connectors: bool) -> list[ToolSpec]:
    specs = [
        ToolSpec(
            SEARCH_KNOWLEDGE_BASE,
            "Search the user's documents and the user manual for passages related to a query.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."},
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only search these documents; leave out to search all.",
                    },
                },
                "required": ["query"],
            },
        ),
        ToolSpec(
            READ_DOCUMENT,
            "Read a document found by a search, a section at a time.",
            {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "section": {
                        "type": "integer",
                        "description": "Which part to read, from 1 (the default).",
                    },
                },
                "required": ["document_id"],
            },
        ),
    ]
    if connectors:
        specs.append(
            ToolSpec(
                SEARCH_CONNECTORS,
                "Search the connected systems live, for current data that documents may not have.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to look for."},
                        "connector_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Only ask these connectors; leave out to ask all.",
                        },
                    },
                    "required": ["query"],
                },
            )
        )
    return specs


class ChatAgent:
    def __init__(
        self,
        settings: Settings,
        model: Model,
        documents: DocumentSearch,
        reader: DocumentReader,
        connectors: ConnectorSearch | None = None,
        counter: TokenCounter | None = None,
    ) -> None:
        self._settings = settings
        self._model = model
        self._documents = documents
        self._reader = reader
        self._connectors = connectors
        self._counter = counter or ApproximateTokenCounter()

    async def supports_tools(self, model: str) -> bool:
        return await self._model.supports_tools(model)

    async def run(
        self, model: str, prompt: list[PromptMessage], scope: AgentScope
    ) -> AsyncGenerator[AnswerEvent]:
        """Streams the answer, calling the tools the model asks for. After
        `max_tool_steps` calls no tools are offered, so the model must answer."""
        # Connected systems are not asked when the question is about chosen documents.
        use_connectors = self._connectors is not None and not scope.document_ids
        tools = _specs(use_connectors)
        sources = _Sources()
        unavailable: list[str] = []
        messages = list(prompt)
        spent = sum(self._tokens(m.content) for m in messages)
        budget = self._settings.context_tokens - self._settings.answer_reserve_tokens
        steps = 0
        searching = False
        trail: list[chat_pb2.RetrievalSource] = []
        wrote = False
        while True:
            last = steps >= self._settings.max_tool_steps
            said: list[str] = []
            calls: list[ToolCall] = []
            separate = wrote
            async with contextlib.aclosing(
                self._model.turn(model, messages, [] if last else tools)
            ) as turn:
                async for item in turn:
                    if isinstance(item, ToolCall):
                        calls.append(item)
                    else:
                        if separate:
                            # Text of an earlier turn, written before its tool calls.
                            separate = False
                            yield AnswerDelta("\n\n")
                        said.append(item)
                        wrote = True
                        yield AnswerDelta(item)
            if not calls or last:
                return
            messages.append(PromptMessage(PromptRole.ASSISTANT, "".join(said), tuple(calls)))
            spent += self._tokens("".join(said)) + sum(self._tokens(c.arguments) for c in calls)
            for call in calls:
                if steps >= self._settings.max_tool_steps:
                    # Every call gets an answer, but only so many are run.
                    messages.append(
                        PromptMessage(PromptRole.TOOL, _NO_MORE_STEPS, tool_call_id=call.id)
                    )
                    continue
                steps += 1
                if not searching:
                    searching = True
                    yield ProgressChanged(chat_pb2.PROGRESS_STAGE_SEARCHING)
                # The trail of searches so far goes out as a whole, each with its query.
                searched = call.name in _SEARCHES
                first = len(trail)
                if searched:
                    trail.append(_searching(call.name, _query(call)))
                    yield RetrievalChanged(_snapshot(trail))
                result = await self._call(
                    call, scope, use_connectors, sources, unavailable, budget - spent
                )
                if steps >= self._settings.max_tool_steps:
                    result.text += "\n\n" + _NO_MORE_STEPS
                spent += self._tokens(result.text)
                messages.append(PromptMessage(PromptRole.TOOL, result.text, tool_call_id=call.id))
                if searched:
                    trail[first:] = [_asked(s, _query(call)) for s in result.retrieval]
                    yield RetrievalChanged(_snapshot(trail))
                yield SourcesFound(list(sources.citations), list(unavailable))

    def _tokens(self, text: str) -> int:
        return self._counter.count(text) + MESSAGE_OVERHEAD_TOKENS

    async def _call(
        self,
        call: ToolCall,
        scope: AgentScope,
        use_connectors: bool,
        sources: _Sources,
        unavailable: list[str],
        room: int,
    ) -> _Result:
        """Runs a tool. Whatever goes wrong with a peer or with the model's
        arguments becomes the result, so the model can tell the user; only a
        failure of the llm module ends the answer."""
        try:
            args = json.loads(call.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except ValueError:
            return _Result(
                "The arguments are not a valid JSON object.",
                [_state(call.name, chat_pb2.RETRIEVAL_STATE_UNAVAILABLE)],
            )
        try:
            if call.name == SEARCH_KNOWLEDGE_BASE:
                found = await self._documents.search_documents(
                    _text(args, "query"),
                    self._settings.rag_top_k,
                    _in_scope(args.get("document_ids"), scope.document_ids),
                    scope.team_ids,
                )
                return self._found(found, sources, room, chat_pb2.RETRIEVAL_SOURCE_KIND_DOCUMENTS)
            if call.name == READ_DOCUMENT:
                return await self._read(args, scope, sources, room)
            if call.name == SEARCH_CONNECTORS and use_connectors and self._connectors:
                live = await self._connectors.search(
                    _text(args, "query"),
                    self._settings.connectors_top_k,
                    scope.team_ids,
                    _strings(args.get("connector_ids")),
                )
                unavailable.extend(n for n in live.unavailable if n not in unavailable)
                return self._live(live, sources, room)
        except PeerError as err:
            if err.peer is Peer.LLM:
                raise
            log.warning("tool %s failed: %s", call.name, err)
            what = "unavailable right now" if isinstance(err, PeerUnavailableError) else "failed"
            return _Result(
                f"The search {what}; tell the user if it matters for the answer.",
                [_state(call.name, chat_pb2.RETRIEVAL_STATE_UNAVAILABLE)],
            )
        except ValueError as err:
            return _Result(str(err), [_state(call.name, chat_pb2.RETRIEVAL_STATE_UNAVAILABLE)])
        return _Result(f"There is no tool {call.name}.", [])

    async def _read(
        self, args: dict[str, Any], scope: AgentScope, sources: _Sources, room: int
    ) -> _Result:
        try:
            document_id = uuid.UUID(_text(args, "document_id"))
        except ValueError:
            raise ValueError("document_id must be the id of a document a search found.") from None
        if scope.document_ids and document_id not in scope.document_ids:
            raise ValueError("That document is not part of this conversation.")
        section = args.get("section", 1)
        section = section if isinstance(section, int) and section >= 1 else 1
        found = await self._reader.read(document_id, section, scope.team_ids)
        if found is None:
            return _Result(
                f"Section {section} of that document is not available.",
                [_state(READ_DOCUMENT, chat_pb2.RETRIEVAL_STATE_DONE)],
            )
        return self._found(
            [found], sources, room, chat_pb2.RETRIEVAL_SOURCE_KIND_DOCUMENTS, read=True
        )

    def _found(
        self,
        found: list[chat_pb2.Citation],
        sources: _Sources,
        room: int,
        kind: chat_pb2.RetrievalSourceKind,
        note: str = "",
        read: bool = False,
    ) -> _Result:
        """The text of what a tool found, numbered, bounded by the room left in the prompt."""
        state = chat_pb2.RetrievalSource(
            kind=kind, state=chat_pb2.RETRIEVAL_STATE_DONE, results=len(found)
        )
        if not found:
            return _Result("Nothing related was found." + note, [state])
        if room <= 0:
            return _Result(NO_ROOM, [state])
        fitted = fit(room, self._counter, lambda kept, _: _render(kept), found, [], "")
        # `fit` keeps the best passage even when it alone is too big; that is
        # only for the first results, so the model has something to answer from.
        if sources.citations and self._tokens(_render(fitted.sources)) > room:
            return _Result(NO_ROOM, [state])
        text = _render(fitted.sources, sources, read)
        return _Result(text + note, [state])

    def _live(self, live: LiveResult, sources: _Sources, room: int) -> _Result:
        result = self._found(
            live.citations,
            sources,
            room,
            chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR,
            _live_note(live),
        )
        result.retrieval = _connector_states(live)
        return result


def _render(
    found: Sequence[chat_pb2.Citation], sources: _Sources | None = None, read: bool = False
) -> str:
    """The passages for the model. With `sources` they are numbered, as they are
    first seen; without, only their size is of interest."""
    return "\n\n".join(
        f"[{sources.number(c, read) if sources else 0}] {source_name(c)}:\n{c.snippet}"
        for c in found
    )


def _live_note(live: LiveResult) -> str:
    if live.failed:
        return "\n\nThe connectors are unavailable right now."
    if live.unavailable:
        return f"\n\nUnavailable right now: {', '.join(live.unavailable)}."
    return ""


def _connector_states(live: LiveResult) -> list[chat_pb2.RetrievalSource]:
    if live.failed:
        return [_state(SEARCH_CONNECTORS, chat_pb2.RETRIEVAL_STATE_UNAVAILABLE)]
    return [
        chat_pb2.RetrievalSource(
            kind=chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR,
            connector=name,
            state=chat_pb2.RETRIEVAL_STATE_UNAVAILABLE
            if name in live.unavailable
            else chat_pb2.RETRIEVAL_STATE_DONE,
            results=0
            if name in live.unavailable
            else sum(c.connector == name for c in live.citations),
        )
        for name in live.searched
    ]


def _searching(tool: str, query: str = "") -> chat_pb2.RetrievalSource:
    return _asked(_state(tool, chat_pb2.RETRIEVAL_STATE_SEARCHING), query)


def _asked(source: chat_pb2.RetrievalSource, query: str) -> chat_pb2.RetrievalSource:
    source.query = query
    return source


def _snapshot(trail: Sequence[chat_pb2.RetrievalSource]) -> list[chat_pb2.RetrievalSource]:
    """A copy, as the trail goes on changing."""
    copies = [chat_pb2.RetrievalSource() for _ in trail]
    for copy, step in zip(copies, trail, strict=True):
        copy.CopyFrom(step)
    return copies


def _query(call: ToolCall) -> str:
    """The query the model searched for; empty when its arguments have none."""
    try:
        args = json.loads(call.arguments or "{}")
    except ValueError:
        return ""
    query = args.get("query") if isinstance(args, dict) else None
    return query.strip() if isinstance(query, str) else ""


def _state(tool: str, state: chat_pb2.RetrievalState, results: int = 0) -> chat_pb2.RetrievalSource:
    kind = (
        chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR
        if tool == SEARCH_CONNECTORS
        else chat_pb2.RETRIEVAL_SOURCE_KIND_DOCUMENTS
    )
    return chat_pb2.RetrievalSource(kind=kind, state=state, results=results)


def _text(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    return value.strip()


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _in_scope(requested: Any, scope: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """The documents a search is limited to: the ones the model asked for, but
    never beyond the conversation's own."""
    wanted: list[uuid.UUID] = []
    for raw in _strings(requested):
        with contextlib.suppress(ValueError):
            wanted.append(uuid.UUID(raw))
    if not scope:
        return wanted
    return [d for d in wanted if d in scope] or list(scope)
