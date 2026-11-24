"""The llm and document modules behind the tools of an answer."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import grpc
import pytest
from knowcel.document.v1 import document_pb2
from knowcel.ingestion.v1 import ingestion_pb2
from knowcel.llm.v1 import llm_pb2
from knowcel_chat.chat import Peer, PeerError, PromptMessage, PromptRole, ToolCall, ToolSpec
from knowcel_chat.peers import READ_CHUNKS, PeerConnectors, PeerDocuments, PeerGenerator

SEARCH = ToolSpec("search", "Searches.", {"type": "object"})


class FakeCall:
    def __init__(self, responses: list[llm_pb2.GenerateResponse]) -> None:
        self._responses = responses
        self.cancelled = False

    async def _iter(self) -> AsyncIterator[llm_pb2.GenerateResponse]:
        for r in self._responses:
            yield r

    def __aiter__(self) -> AsyncIterator[llm_pb2.GenerateResponse]:
        return self._iter()

    def cancel(self) -> bool:
        self.cancelled = True
        return True


class FakeLlm:
    def __init__(self, *responses: llm_pb2.GenerateResponse, models: list[Any] | None = None):
        self.call = FakeCall(list(responses))
        self.requests: list[llm_pb2.GenerateRequest] = []
        self.models = models or []
        self.status_error: grpc.StatusCode | None = None

    def Generate(self, request: llm_pb2.GenerateRequest) -> FakeCall:
        self.requests.append(request)
        return self.call

    async def ListModels(self, request: Any) -> llm_pb2.ListModelsResponse:
        if self.status_error:
            raise grpc.aio.AioRpcError(
                self.status_error, grpc.aio.Metadata(), grpc.aio.Metadata(), "down"
            )
        return llm_pb2.ListModelsResponse(models=self.models)

    async def GetProviderStatus(self, request: Any) -> llm_pb2.GetProviderStatusResponse:
        return llm_pb2.GetProviderStatusResponse(default_chat_model="dflt")


async def test_a_turn_sends_the_tools_and_yields_text_then_the_calls() -> None:
    wire = llm_pb2.ToolCall(id="c1", name="search", arguments_json='{"query": "x"}')
    llm = FakeLlm(
        llm_pb2.GenerateResponse(delta="Let me "),
        llm_pb2.GenerateResponse(delta="look."),
        llm_pb2.GenerateResponse(done=True, tool_calls=[wire]),
    )
    prompt = [
        PromptMessage(PromptRole.USER, "q"),
        PromptMessage(PromptRole.ASSISTANT, "", (ToolCall("c0", "search", "{}"),)),
        PromptMessage(PromptRole.TOOL, "found", tool_call_id="c0"),
    ]
    items = [i async for i in PeerGenerator(llm).turn("m", prompt, [SEARCH])]  # type: ignore[arg-type]

    assert items == ["Let me ", "look.", ToolCall("c1", "search", '{"query": "x"}')]
    [request] = llm.requests
    assert [(t.name, json.loads(t.parameters_json_schema)) for t in request.tools] == [
        ("search", {"type": "object"})
    ]
    assert [m.role for m in request.messages] == [
        llm_pb2.ROLE_USER,
        llm_pb2.ROLE_ASSISTANT,
        llm_pb2.ROLE_TOOL,
    ]
    assert request.messages[1].tool_calls[0].id == "c0"
    assert request.messages[2].tool_call_id == "c0"


async def test_generate_streams_only_the_text() -> None:
    llm = FakeLlm(
        llm_pb2.GenerateResponse(delta="Hi"),
        llm_pb2.GenerateResponse(done=True, tool_calls=[llm_pb2.ToolCall(id="c", name="x")]),
    )
    assert [d async for d in PeerGenerator(llm).generate("m", [])] == ["Hi"]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("model", "expected"),
    [("tools", True), ("plain", False), ("embed", False), ("unknown", False), ("", True)],
)
async def test_tool_support_is_read_from_the_models_of_the_llm_module(
    model: str, expected: bool
) -> None:
    chat = llm_pb2.MODEL_KIND_CHAT
    llm = FakeLlm(
        models=[
            llm_pb2.Model(id="tools", kind=chat, supports_tools=True),
            llm_pb2.Model(id="dflt", kind=chat, supports_tools=True),
            llm_pb2.Model(id="plain", kind=chat),
            llm_pb2.Model(id="embed", kind=llm_pb2.MODEL_KIND_EMBEDDING, supports_tools=True),
        ]
    )
    assert await PeerGenerator(llm).supports_tools(model) is expected  # type: ignore[arg-type]


async def test_unknown_tool_support_means_no_tools() -> None:
    llm = FakeLlm()
    llm.status_error = grpc.StatusCode.UNAVAILABLE
    assert not await PeerGenerator(llm).supports_tools("m")  # type: ignore[arg-type]


class FakeDocumentStub:
    def __init__(self, chunks: int, missing: bool = False, teams: list[str] | None = None) -> None:
        self.chunks = chunks
        self.missing = missing
        self.teams = teams or []

    async def GetDocument(self, request: Any) -> document_pb2.GetDocumentResponse:
        if self.missing:
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.NOT_FOUND, grpc.aio.Metadata(), grpc.aio.Metadata(), "gone"
            )
        return document_pb2.GetDocumentResponse(
            document=document_pb2.Document(title="doc.md", team_ids=self.teams)
        )

    async def ListChunks(self, request: Any) -> document_pb2.ListChunksResponse:
        start = int(request.page.page_token or 0)
        end = min(start + request.page.page_size, self.chunks)
        response = document_pb2.ListChunksResponse(
            chunks=[document_pb2.Chunk(index=i, text=f"chunk {i}") for i in range(start, end)]
        )
        if end < self.chunks:
            response.page.next_page_token = str(end)
        return response


async def test_a_document_is_read_in_sections_of_chunks() -> None:
    documents = PeerDocuments(FakeDocumentStub(READ_CHUNKS + 2))  # type: ignore[arg-type]
    doc = uuid.uuid4()

    first = await documents.read(doc, 1)
    second = await documents.read(doc, 2)

    assert first is not None
    assert (first.document_id, first.document_title, first.chunk_index) == (str(doc), "doc.md", 0)
    assert first.snippet.count("chunk") == READ_CHUNKS
    assert second is not None
    assert (second.chunk_index, second.snippet) == (READ_CHUNKS, "chunk 4\n\nchunk 5")
    assert await documents.read(doc, 3) is None


async def test_an_empty_document_has_no_sections() -> None:
    assert await PeerDocuments(FakeDocumentStub(0)).read(uuid.uuid4(), 1) is None  # type: ignore[arg-type]


async def test_a_document_that_cannot_be_read_is_a_document_error() -> None:
    with pytest.raises(PeerError) as err:
        await PeerDocuments(FakeDocumentStub(1, missing=True)).read(uuid.uuid4(), 1)  # type: ignore[arg-type]
    assert err.value.peer is Peer.DOCUMENT


async def test_connectors_can_be_limited_to_chosen_ones() -> None:
    class Ingestion:
        request: ingestion_pb2.SearchConnectorsRequest | None = None

        async def SearchConnectors(
            self,
            request: ingestion_pb2.SearchConnectorsRequest,
            timeout: float | None = None,  # noqa: ASYNC109
        ) -> ingestion_pb2.SearchConnectorsResponse:
            self.request = request
            return ingestion_pb2.SearchConnectorsResponse()

    ingestion = Ingestion()
    await PeerConnectors(ingestion, 0.8).search("q", 3, [], ["Orders"])  # type: ignore[arg-type]

    assert ingestion.request is not None
    assert list(ingestion.request.connector_ids) == ["Orders"]


async def test_a_document_outside_the_teams_of_the_conversation_is_not_read() -> None:
    team, other = uuid.uuid4(), uuid.uuid4()
    documents = PeerDocuments(FakeDocumentStub(2, teams=[str(team)]))  # type: ignore[arg-type]
    doc = uuid.uuid4()

    assert await documents.read(doc, 1, [team]) is not None
    assert await documents.read(doc, 1, [other]) is None
    assert await documents.read(doc, 1) is not None  # no teams: all the caller may read
