import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from knowcel.chat.v1 import chat_pb2
from knowcel_chat.agent import NO_ROOM, ChatAgent
from knowcel_chat.chat import (
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
)
from knowcel_chat.config import Settings
from knowcel_chat.peers import LiveSources

SCOPE = AgentScope([], [])
PROMPT = [PromptMessage(PromptRole.SYSTEM, "sys"), PromptMessage(PromptRole.USER, "q")]


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(f"c-{name}-{len(args)}", name, json.dumps(args))


def cite(title: str, snippet: str = "text", index: int = 0, score: float = 0.9) -> Any:
    return chat_pb2.Citation(
        document_id=f"id-{title}",
        document_title=title,
        chunk_index=index,
        snippet=snippet,
        score=score,
    )


class ScriptedModel:
    """Answers each turn with the next entry: the tool calls to make, or text."""

    def __init__(self, *turns: Sequence[ToolCall] | str) -> None:
        self.turns = list(turns)
        self.prompts: list[list[PromptMessage]] = []
        self.tools: list[list[ToolSpec]] = []

    async def supports_tools(self, model: str) -> bool:
        return True

    async def turn(
        self, model: str, prompt: list[PromptMessage], tools: Sequence[ToolSpec]
    ) -> AsyncGenerator[str | ToolCall]:
        self.prompts.append(list(prompt))
        self.tools.append(list(tools))
        turn = self.turns.pop(0)
        if isinstance(turn, str):
            for word in turn.split(" "):
                yield word + " "
        else:
            for c in turn:
                yield c


class FakeDocuments:
    def __init__(self, **results: list[Any]) -> None:
        self.results = results
        self.queries: list[tuple[str, list[uuid.UUID]]] = []
        self.error: PeerError | None = None
        self.hang = False
        self.searching = asyncio.Event()

    async def search_documents(
        self,
        query: str,
        limit: int,
        document_ids: Sequence[uuid.UUID],
        team_ids: Sequence[uuid.UUID],
    ) -> list[Any]:
        self.queries.append((query, list(document_ids)))
        self.searching.set()
        if self.hang:
            await asyncio.Event().wait()
        if self.error:
            raise self.error
        return self.results.get(query, [])


class FakeReader:
    def __init__(self) -> None:
        self.reads: list[tuple[uuid.UUID, int]] = []

    async def read(
        self, document_id: uuid.UUID, section: int, team_ids: Sequence[uuid.UUID] = ()
    ) -> Any:
        self.reads.append((document_id, section))
        if section > 1:
            return None
        return chat_pb2.Citation(
            document_id=str(document_id), document_title="whole.md", snippet="all of it", score=1.0
        )


@dataclass
class FakeConnectors:
    live: LiveSources = field(default_factory=lambda: LiveSources([], []))
    asked: list[tuple[str, list[str]]] = field(default_factory=list)

    async def search(
        self,
        query: str,
        limit: int,
        team_ids: Sequence[uuid.UUID],
        connector_ids: Sequence[str] = (),
    ) -> LiveSources:
        self.asked.append((query, list(connector_ids)))
        return self.live


def agent(
    model: ScriptedModel,
    documents: FakeDocuments | None = None,
    connectors: FakeConnectors | None = None,
    reader: FakeReader | None = None,
    **settings: Any,
) -> ChatAgent:
    return ChatAgent(
        Settings(**settings),
        model,
        documents or FakeDocuments(),
        reader or FakeReader(),
        connectors,
    )


async def run(a: ChatAgent, scope: AgentScope = SCOPE) -> list[AnswerEvent]:
    return [e async for e in a.run("m", PROMPT, scope)]


def text(events: list[AnswerEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, AnswerDelta))


def last_sources(events: list[AnswerEvent]) -> list[Any]:
    return [e for e in events if isinstance(e, SourcesFound)][-1].citations


async def test_two_searches_are_cited_with_distinct_numbers() -> None:
    documents = FakeDocuments(a=[cite("geo.md", "Paris")], b=[cite("eco.md", "Euro")])
    model = ScriptedModel(
        [call("search_knowledge_base", query="a")],
        [call("search_knowledge_base", query="b")],
        "Paris [1] uses the Euro [2].",
    )
    events = await run(agent(model, documents))

    assert [q for q, _ in documents.queries] == ["a", "b"]
    assert [c.document_title for c in last_sources(events)] == ["geo.md", "eco.md"]
    tool_texts = [m.content for m in model.prompts[-1] if m.role is PromptRole.TOOL]
    assert tool_texts == ["[1] geo.md:\nParis", "[2] eco.md:\nEuro"]
    assert text(events) == "Paris [1] uses the Euro [2]. "


async def test_the_same_source_found_twice_keeps_one_number() -> None:
    documents = FakeDocuments(
        a=[cite("geo.md", "Paris")], b=[cite("eco.md"), cite("geo.md", "Paris")]
    )
    model = ScriptedModel(
        [call("search_knowledge_base", query="a")],
        [call("search_knowledge_base", query="b")],
        "done",
    )
    events = await run(agent(model, documents))

    assert [c.document_title for c in last_sources(events)] == ["geo.md", "eco.md"]
    second = [m.content for m in model.prompts[-1] if m.role is PromptRole.TOOL][1]
    assert second.startswith("[2] eco.md:")
    assert "[1] geo.md:\nParis" in second


async def test_the_model_must_answer_after_max_tool_steps() -> None:
    documents = FakeDocuments(a=[cite("geo.md")])
    model = ScriptedModel(
        [call("search_knowledge_base", query="a")],
        [call("search_knowledge_base", query="a")],
        "Enough.",
    )
    events = await run(agent(model, documents, max_tool_steps=2))

    assert len(documents.queries) == 2
    assert [len(t) for t in model.tools] == [2, 2, 0]  # no tools for the last turn
    assert "Answer now" in model.prompts[-1][-1].content
    assert text(events) == "Enough. "


async def test_a_tool_called_after_the_last_step_is_not_run() -> None:
    documents = FakeDocuments()
    model = ScriptedModel([call("search_knowledge_base", query="a")], [call("read_document")])
    events = await run(agent(model, documents, max_tool_steps=1))

    assert len(documents.queries) == 1
    assert text(events) == ""


async def test_small_talk_triggers_no_retrieval() -> None:
    documents = FakeDocuments()
    events = await run(agent(ScriptedModel("You're welcome."), documents))

    assert documents.queries == []
    assert not [e for e in events if isinstance(e, ProgressChanged | RetrievalChanged)]
    assert text(events) == "You're welcome. "


async def test_each_tool_call_reports_searching_then_the_result() -> None:
    documents = FakeDocuments(a=[cite("geo.md"), cite("eco.md")])
    events = await run(
        agent(ScriptedModel([call("search_knowledge_base", query="a")], "ok"), documents)
    )

    assert events[0] == ProgressChanged(chat_pb2.PROGRESS_STAGE_SEARCHING)
    searching, done = [e for e in events if isinstance(e, RetrievalChanged)]
    assert [(s.kind, s.state) for s in searching.sources] == [
        (chat_pb2.RETRIEVAL_SOURCE_KIND_DOCUMENTS, chat_pb2.RETRIEVAL_STATE_SEARCHING)
    ]
    assert [(s.state, s.results) for s in done.sources] == [(chat_pb2.RETRIEVAL_STATE_DONE, 2)]


async def test_the_steps_so_far_are_sent_whole_each_with_its_query() -> None:
    documents = FakeDocuments(a=[cite("geo.md")], b=[])
    model = ScriptedModel(
        [call("search_knowledge_base", query=" a ")],
        [call("read_document", document_id=str(uuid.uuid4()))],
        [call("search_knowledge_base", query="b")],
        "ok",
    )
    events = await run(agent(model, documents))

    trails = [
        [(s.query, s.state, s.results) for s in e.sources]
        for e in events
        if isinstance(e, RetrievalChanged)
    ]
    searching, done = chat_pb2.RETRIEVAL_STATE_SEARCHING, chat_pb2.RETRIEVAL_STATE_DONE
    # Reading a section is no search step; the earlier steps stay in each snapshot.
    assert trails == [
        [("a", searching, 0)],
        [("a", done, 1)],
        [("a", done, 1), ("b", searching, 0)],
        [("a", done, 1), ("b", done, 0)],
    ]


async def test_a_connector_step_has_one_entry_per_connector_with_the_query() -> None:
    connectors = FakeConnectors(LiveSources([], ["Orders"], ["Orders", "Wiki"]))
    model = ScriptedModel([call("search_connectors", query="late")], "x")
    events = await run(agent(model, connectors=connectors))

    last = [e for e in events if isinstance(e, RetrievalChanged)][-1]
    assert [(s.connector, s.query) for s in last.sources] == [
        ("Orders", "late"),
        ("Wiki", "late"),
    ]


async def test_a_failing_connector_is_reported_to_the_model_and_the_answer() -> None:
    connectors = FakeConnectors(
        LiveSources([], ["Orders"], ["Orders", "Wiki"]),
    )
    model = ScriptedModel([call("search_connectors", query="late")], "Orders was down.")
    events = await run(agent(model, connectors=connectors))

    tool = next(m for m in model.prompts[-1] if m.role is PromptRole.TOOL)
    assert "Unavailable right now: Orders" in tool.content
    assert [e for e in events if isinstance(e, SourcesFound)][-1].unavailable == ["Orders"]
    states = [e for e in events if isinstance(e, RetrievalChanged)][-1].sources
    assert [(s.connector, s.state) for s in states] == [
        ("Orders", chat_pb2.RETRIEVAL_STATE_UNAVAILABLE),
        ("Wiki", chat_pb2.RETRIEVAL_STATE_DONE),
    ]
    assert text(events) == "Orders was down. "


async def test_connector_snippets_keep_their_connector_in_the_sources() -> None:
    snippet = chat_pb2.Citation(
        document_title="Order 7", snippet="delayed", connector="Orders", source_url="http://o/7"
    )
    connectors = FakeConnectors(LiveSources([snippet], [], ["Orders"]))
    model = ScriptedModel([call("search_connectors", query="late", connector_ids=["Orders"])], "x")
    events = await run(agent(model, connectors=connectors))

    assert connectors.asked == [("late", ["Orders"])]
    [source] = last_sources(events)
    assert (source.connector, source.source_url) == ("Orders", "http://o/7")
    tool = next(m for m in model.prompts[-1] if m.role is PromptRole.TOOL)
    assert tool.content == "[1] Order 7 (live from Orders):\ndelayed"


async def test_connectors_are_not_offered_without_them_or_for_chosen_documents() -> None:
    plain = ScriptedModel("x")
    await run(agent(plain))
    chosen = ScriptedModel("x")
    await run(agent(chosen, connectors=FakeConnectors()), AgentScope([uuid.uuid4()], []))
    both = ScriptedModel("x")
    await run(agent(both, connectors=FakeConnectors()))

    names = [[t.name for t in m.tools[0]] for m in (plain, chosen, both)]
    assert names[0] == names[1] == ["search_knowledge_base", "read_document"]
    assert names[2][-1] == "search_connectors"


@pytest.mark.parametrize("error_type", [PeerError, PeerUnavailableError])
async def test_a_document_peer_failure_is_a_result_the_model_can_report(
    error_type: type[PeerError],
) -> None:
    documents = FakeDocuments()
    documents.error = error_type(Peer.DOCUMENT, "down")
    model = ScriptedModel([call("search_knowledge_base", query="a")], "Search was down.")
    events = await run(agent(model, documents))

    states = [e for e in events if isinstance(e, RetrievalChanged)][-1].sources
    assert [s.state for s in states] == [chat_pb2.RETRIEVAL_STATE_UNAVAILABLE]
    assert text(events) == "Search was down. "


async def test_an_llm_failure_while_searching_ends_the_answer() -> None:
    documents = FakeDocuments()
    documents.error = PeerUnavailableError(Peer.LLM, "embedding down")
    with pytest.raises(PeerUnavailableError):
        await run(agent(ScriptedModel([call("search_knowledge_base", query="a")]), documents))


async def test_a_search_is_never_wider_than_the_conversations_documents() -> None:
    inside, outside = uuid.uuid4(), uuid.uuid4()
    documents = FakeDocuments()
    model = ScriptedModel(
        [
            call("search_knowledge_base", query="a", document_ids=[str(inside), str(outside)]),
            call("search_knowledge_base", query="b", document_ids=[str(outside)]),
            call("search_knowledge_base", query="c", document_ids=["not-an-id"]),
        ],
        "x",
    )
    await run(agent(model, documents, max_tool_steps=5), AgentScope([inside], []))

    assert [ids for _, ids in documents.queries] == [[inside], [inside], [inside]]


async def test_invalid_arguments_are_answered_to_the_model() -> None:
    documents = FakeDocuments()
    model = ScriptedModel(
        [
            ToolCall("1", "search_knowledge_base", "{oops"),
            ToolCall("2", "search_knowledge_base", "{}"),
            ToolCall("3", "no_such_tool", "{}"),
        ],
        "x",
    )
    await run(agent(model, documents, max_tool_steps=5))

    results = [m.content for m in model.prompts[-1] if m.role is PromptRole.TOOL]
    assert results == [
        "The arguments are not a valid JSON object.",
        "query is required.",
        "There is no tool no_such_tool.",
    ]
    assert documents.queries == []


async def test_read_document_adds_the_section_as_a_source() -> None:
    reader = FakeReader()
    doc = uuid.uuid4()
    model = ScriptedModel(
        [
            call("read_document", document_id=str(doc)),
            call("read_document", document_id=str(doc), section=2),
            call("read_document", document_id="nope"),
        ],
        "x",
    )
    events = await run(agent(model, reader=reader, max_tool_steps=5))

    assert reader.reads == [(doc, 1), (doc, 2)]
    results = [m.content for m in model.prompts[-1] if m.role is PromptRole.TOOL]
    assert results[0] == "[1] whole.md:\nall of it"
    assert "not available" in results[1]
    assert results[2] == "document_id must be the id of a document a search found."
    assert [c.document_title for c in last_sources(events)] == ["whole.md"]


async def test_results_are_bounded_by_the_room_left_in_the_prompt() -> None:
    big = [cite(f"d{i}.md", "word " * 400, score=1 - i / 10) for i in range(3)]
    documents = FakeDocuments(a=big, b=[cite("other.md", "more " * 600)])
    model = ScriptedModel(
        [call("search_knowledge_base", query="a")], [call("search_knowledge_base", query="b")], "x"
    )
    events = await run(agent(model, documents, context_tokens=2000, answer_reserve_tokens=500))

    first, second = [m.content for m in model.prompts[-1] if m.role is PromptRole.TOOL]
    assert 0 < first.count("word") < 1200  # the lowest ranked passages were dropped
    assert second == NO_ROOM
    # Only what the model was shown can be cited.
    assert [c.document_title for c in last_sources(events)] == ["d0.md", "d1.md"]


async def test_stopping_during_a_tool_cancels_it() -> None:
    documents = FakeDocuments()
    documents.hang = True
    model = ScriptedModel([call("search_knowledge_base", query="a")])
    task = asyncio.create_task(run(agent(model, documents)))
    await documents.searching.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_text_before_the_tools_is_separated_from_the_text_after_them() -> None:
    documents = FakeDocuments()
    model = ScriptedModel(
        [call("search_knowledge_base", query="a")],  # no narration: nothing to separate
        "Based on it.",
    )
    assert text(await run(agent(model, documents))) == "Based on it. "

    class Narrating(ScriptedModel):
        async def turn(
            self, model: str, prompt: list[PromptMessage], tools: Sequence[ToolSpec]
        ) -> AsyncGenerator[str | ToolCall]:
            if not self.prompts:
                yield "Let me search."
                self.prompts.append(prompt)
                yield call("search_knowledge_base", query="a")
                return
            async for item in super().turn(model, prompt, tools):
                yield item

    events = await run(agent(Narrating("Found it."), documents))
    assert text(events) == "Let me search.\n\nFound it. "


async def test_only_max_tool_steps_calls_are_run_but_each_gets_an_answer() -> None:
    documents = FakeDocuments()
    model = ScriptedModel([call("search_knowledge_base", query=str(i)) for i in range(5)], "ok")
    await run(agent(model, documents, max_tool_steps=2))

    assert [q for q, _ in documents.queries] == ["0", "1"]
    results = [m for m in model.prompts[-1] if m.role is PromptRole.TOOL]
    assert len(results) == 5
    assert all("No more searches" in m.content for m in results[2:])
