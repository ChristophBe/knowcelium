"""Live retrieval: the connectors of the ingestion module as a source of answers."""

import asyncio
import logging
import uuid
from copy import copy
from types import SimpleNamespace
from typing import Any

import grpc
import pytest
from knowcel.chat.v1 import chat_pb2
from knowcel.ingestion.v1 import ingestion_pb2
from knowcel_chat.chat import PeerError
from knowcel_chat.peers import PeerConnectors, PeerRetriever


def rpc_error(code: grpc.StatusCode) -> grpc.aio.AioRpcError:
    return grpc.aio.AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), "no")


class FakeIngestion:
    def __init__(
        self,
        snippets: list[ingestion_pb2.ConnectorSnippet] | None = None,
        unavailable: list[str] | None = None,
        searched: list[str] | None = None,
        error: grpc.StatusCode | None = None,
        hang: bool = False,
    ) -> None:
        self.snippets = snippets or []
        self.unavailable = unavailable or []
        self.searched = searched or []
        self.error = error
        self.hang = hang
        self.requests: list[ingestion_pb2.SearchConnectorsRequest] = []
        self.timeouts: list[float | None] = []

    async def SearchConnectors(
        self,
        request: ingestion_pb2.SearchConnectorsRequest,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> ingestion_pb2.SearchConnectorsResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.hang:
            await asyncio.sleep(60)
        if self.error:
            raise rpc_error(self.error)
        return ingestion_pb2.SearchConnectorsResponse(
            snippets=self.snippets,
            unavailable_connectors=self.unavailable,
            searched_connectors=self.searched,
        )


class FakeDocuments:
    def __init__(self, error: bool = False) -> None:
        self.error = error
        self.requests: list[Any] = []

    async def SearchChunks(self, request: Any) -> Any:
        self.requests.append(request)
        if self.error:
            raise rpc_error(grpc.StatusCode.UNAVAILABLE)
        chunk = SimpleNamespace(document_id="d1", index=0, text="Boxes are in the annex.")
        found = SimpleNamespace(
            chunk=chunk, document_title="Handbook", score=0.7, excerpt="", keyword_match=False
        )
        return SimpleNamespace(results=[found])


class FakeLlm:
    async def Embed(self, request: Any) -> Any:
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0])])


def snippet(connector: str = "stock", title: str = "Aisle 3") -> ingestion_pb2.ConnectorSnippet:
    return ingestion_pb2.ConnectorSnippet(
        connector=connector, title=title, text="40 boxes", source_url="https://wms.example/3"
    )


def retriever(ingestion: FakeIngestion, documents: FakeDocuments | None = None) -> PeerRetriever:
    return PeerRetriever(
        documents or FakeDocuments(),  # type: ignore[arg-type]
        FakeLlm(),  # type: ignore[arg-type]
        connectors=PeerConnectors(ingestion, 0.8, 4),  # type: ignore[arg-type]
        connector_limit=2,
    )


async def test_snippets_are_cited_with_connector_title_and_link() -> None:
    ingestion = FakeIngestion([snippet(), snippet("crm", title="")])
    found = await retriever(ingestion).retrieve("how many boxes", 5, [])

    live = [c for c in found if c.connector]
    assert [(c.connector, c.document_title, c.source_url) for c in live] == [
        ("stock", "Aisle 3", "https://wms.example/3"),
        ("crm", "crm", "https://wms.example/3"),
    ]
    assert live[0].snippet == "40 boxes"
    assert live[0].score > live[1].score > 0.7  # best first, above the weak passage
    assert [c.document_id for c in found if not c.connector] == ["d1"]
    assert not live[0].document_id
    request = ingestion.requests[0]
    assert (request.query, request.limit, ingestion.timeouts) == ("how many boxes", 2, [4])


async def test_the_teams_a_conversation_is_limited_to_are_passed_on() -> None:
    ingestion = FakeIngestion()
    team = uuid.uuid4()
    await retriever(ingestion).retrieve("q", 5, [], [team])
    assert list(ingestion.requests[0].team_ids) == [str(team)]


async def test_a_question_limited_to_documents_does_not_ask_connectors() -> None:
    ingestion = FakeIngestion([snippet()])
    found = await retriever(ingestion).retrieve("q", 5, [uuid.uuid4()])
    assert not ingestion.requests
    assert not [c for c in found if c.connector]


@pytest.mark.parametrize(
    "ingestion",
    [
        FakeIngestion(error=grpc.StatusCode.UNAVAILABLE),
        FakeIngestion(error=grpc.StatusCode.INTERNAL),
        FakeIngestion(error=grpc.StatusCode.DEADLINE_EXCEEDED),
    ],
)
async def test_documents_still_answer_when_ingestion_fails(
    ingestion: FakeIngestion, caplog: pytest.LogCaptureFixture
) -> None:
    unavailable: list[str] = []
    with caplog.at_level(logging.WARNING):
        found = await retriever(ingestion).retrieve("q", 5, [], on_unavailable=unavailable.extend)
    assert [c.document_id for c in found] == ["d1"]
    assert not unavailable  # ingestion being down is not a connector that failed to answer
    assert "connectors unavailable" in caplog.text


async def test_connectors_that_did_not_answer_are_reported_by_name() -> None:
    ingestion = FakeIngestion([snippet()], unavailable=["crm", "wiki"])
    unavailable: list[str] = []
    found = await retriever(ingestion).retrieve("q", 5, [], on_unavailable=unavailable.extend)
    assert unavailable == ["crm", "wiki"]
    assert any(c.connector == "stock" for c in found)


async def test_nothing_is_reported_when_all_connectors_answered() -> None:
    reported: list[list[str]] = []
    await retriever(FakeIngestion([snippet()])).retrieve(
        "q", 5, [], on_unavailable=lambda names: reported.append(list(names))
    )
    assert reported == []


async def test_a_failing_document_search_fails_the_answer_and_stops_the_connector_search() -> None:
    ingestion = FakeIngestion(hang=True)
    with pytest.raises(PeerError):
        await retriever(ingestion, FakeDocuments(error=True)).retrieve("q", 5, [])


async def test_retrieval_without_connectors_is_unchanged() -> None:
    plain = PeerRetriever(FakeDocuments(), FakeLlm())  # type: ignore[arg-type]
    found = await plain.retrieve("q", 5, [])
    assert [c.document_id for c in found] == ["d1"]


def states(snapshots: list[list[Any]]) -> list[list[tuple[int, str, int, int]]]:
    return [[(s.kind, s.connector, s.state, s.results) for s in snap] for snap in snapshots]


async def test_each_connector_asked_is_reported_with_its_state_and_result_count() -> None:
    ingestion = FakeIngestion(
        [snippet(), snippet()], unavailable=["crm"], searched=["stock", "crm", "wiki"]
    )
    snapshots: list[list[Any]] = []
    await retriever(ingestion).retrieve(
        "q", 5, [], on_retrieval=lambda sources: snapshots.append([copy(s) for s in sources])
    )
    docs, connector = (
        chat_pb2.RETRIEVAL_SOURCE_KIND_DOCUMENTS,
        chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR,
    )
    searching, done, down = (
        chat_pb2.RETRIEVAL_STATE_SEARCHING,
        chat_pb2.RETRIEVAL_STATE_DONE,
        chat_pb2.RETRIEVAL_STATE_UNAVAILABLE,
    )
    final = states(snapshots)[-1]
    assert final[0][:3] == (docs, "", done)
    assert final[1:] == [
        (connector, "stock", done, 2),
        (connector, "crm", down, 0),
        (connector, "wiki", done, 0),
    ]
    # Until the connectors answer there is one entry without a name.
    assert states(snapshots)[0] == [(docs, "", searching, 0), (connector, "", searching, 0)]


@pytest.mark.parametrize("error", [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.INTERNAL])
async def test_connectors_that_cannot_be_asked_at_all_are_reported_unavailable(
    error: grpc.StatusCode,
) -> None:
    snapshots: list[list[Any]] = []
    await retriever(FakeIngestion(error=error)).retrieve(
        "q", 5, [], on_retrieval=lambda sources: snapshots.append([copy(s) for s in sources])
    )
    connector = chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR
    assert states(snapshots)[-1][1:] == [(connector, "", chat_pb2.RETRIEVAL_STATE_UNAVAILABLE, 0)]


async def test_a_question_limited_to_documents_reports_only_the_documents() -> None:
    snapshots: list[list[Any]] = []
    await retriever(FakeIngestion([snippet()])).retrieve(
        "q",
        5,
        [uuid.uuid4()],
        on_retrieval=lambda sources: snapshots.append([copy(s) for s in sources]),
    )
    assert all(len(s) == 1 for s in snapshots)
