"""The document and llm modules behind the ports of the answer use case. Their
gRPC statuses end here: callers only see PeerError."""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable, Collection, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import grpc
from knowcel.chat.v1 import chat_pb2
from knowcel.common.v1 import common_pb2
from knowcel.curation.v1 import curation_pb2, curation_pb2_grpc
from knowcel.document.v1 import document_pb2, document_pb2_grpc
from knowcel.ingestion.v1 import ingestion_pb2, ingestion_pb2_grpc
from knowcel.llm.v1 import llm_pb2, llm_pb2_grpc

from .chat import (
    Peer,
    PeerError,
    PeerUnavailableError,
    PromptMessage,
    PromptRole,
    ToolCall,
    ToolSpec,
)
from .manual import Manual, merge_sources

log = logging.getLogger("knowcel_chat")

# Peer statuses that mean "try again later" rather than a bug.
_PEER_UNAVAILABLE = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}

_LLM_ROLES = {
    PromptRole.SYSTEM: llm_pb2.ROLE_SYSTEM,
    PromptRole.USER: llm_pb2.ROLE_USER,
    PromptRole.ASSISTANT: llm_pb2.ROLE_ASSISTANT,
    PromptRole.TOOL: llm_pb2.ROLE_TOOL,
}


@contextlib.contextmanager
def _peer_errors(peer: Peer) -> Iterator[None]:
    try:
        yield
    except grpc.aio.AioRpcError as err:
        message = f"{err.code()} {err.details()}"
        if err.code() in _PEER_UNAVAILABLE:
            raise PeerUnavailableError(peer, message) from err
        raise PeerError(peer, message) from err


class PeerEmbedder:
    def __init__(self, llm: llm_pb2_grpc.LlmServiceStub) -> None:
        self._llm = llm

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        with _peer_errors(Peer.LLM):
            embedded = await self._llm.Embed(llm_pb2.EmbedRequest(inputs=list(texts)))
        return [list(e.values) for e in embedded.embeddings]


class PeerReranker:
    """Rates passages against a question with the llm module's chat model."""

    def __init__(self, llm: llm_pb2_grpc.LlmServiceStub, model: str = "") -> None:
        self._llm = llm
        self._model = model

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        with _peer_errors(Peer.LLM):
            ranked = await self._llm.Rerank(
                llm_pb2.RerankRequest(model=self._model, query=query, documents=list(texts))
            )
        if len(ranked.scores) != len(texts):
            raise PeerError(Peer.LLM, f"rerank returned {len(ranked.scores)} scores")
        return list(ranked.scores)


# Documents asked about in one ScoreChunks call, the most it takes.
_SCORE_BATCH = 100
# With curation, this many times the passages wanted are fetched, as some
# belong to documents that are left out.
_CURATION_OVERFETCH = 2


@dataclass(frozen=True)
class CurationScore:
    """What the curation module says about a document."""

    score: float
    # Deprecated or archived: not to be cited.
    excluded: bool
    # A newer version, or a confirmed replacement, the caller can read exists.
    replaced: bool


class PeerCuration:
    """The curation module's view of documents. It only refines retrieval, so
    a failure is logged and answered with None, and the caller carries on with
    the similarity order."""

    def __init__(
        self, curation: curation_pb2_grpc.CurationServiceStub, timeout: float = 3.0
    ) -> None:
        self._curation = curation
        self._timeout = timeout

    async def scores(self, document_ids: Collection[str]) -> dict[str, CurationScore] | None:
        """The scores of those of the documents that have one and that the
        caller can see; None when curation can't be asked."""
        ids = sorted(set(document_ids))
        found: dict[str, CurationScore] = {}
        try:
            for start in range(0, len(ids), _SCORE_BATCH):
                batch = curation_pb2.ScoreChunksRequest(
                    document_ids=ids[start : start + _SCORE_BATCH]
                )
                response = await self._curation.ScoreChunks(batch, timeout=self._timeout)
                for s in response.scores:
                    found[s.document_id] = CurationScore(s.score, s.excluded, s.replaced)
        except grpc.aio.AioRpcError as err:
            log.warning(
                "curation unavailable, ranking by similarity alone: %s %s",
                err.code(),
                err.details(),
            )
            return None
        return found


@dataclass(frozen=True)
class LiveSources:
    """What the connectors found at question time."""

    citations: list[chat_pb2.Citation]
    # The connectors that did not answer in time or failed, by name.
    unavailable: list[str]
    # Every connector that was asked, by name.
    searched: list[str] = field(default_factory=list)
    # The connectors could not be asked at all (ingestion or its worker is down).
    failed: bool = False


class PeerConnectors:
    """Live retrieval through the ingestion module: the connectors that allow it
    are searched at question time. They only add sources, so any failure of
    ingestion (it is down, slow, or its worker is) is logged and answered with
    nothing found, and the answer is written from documents alone."""

    def __init__(
        self,
        ingestion: ingestion_pb2_grpc.IngestionServiceStub,
        score: float,
        timeout: float = 8.0,
    ) -> None:
        self._ingestion = ingestion
        self._score = score
        self._timeout = timeout

    async def search(
        self,
        query: str,
        limit: int,
        team_ids: Sequence[uuid.UUID],
        connector_ids: Sequence[str] = (),
    ) -> LiveSources:
        try:
            with _peer_errors(Peer.INGESTION):
                found = await self._ingestion.SearchConnectors(
                    ingestion_pb2.SearchConnectorsRequest(
                        query=query,
                        limit=limit,
                        team_ids=[str(i) for i in team_ids],
                        connector_ids=list(connector_ids),
                    ),
                    timeout=self._timeout,
                )
        except PeerError as err:
            log.warning("connectors unavailable, answering from documents: %s", err)
            return LiveSources([], [], failed=True)
        citations = [
            chat_pb2.Citation(
                document_title=s.title or s.connector,
                snippet=s.text,
                # Snippets come best first, as the connector ranked them; they have
                # no similarity, so they rank after each other from a fixed start.
                score=self._score - 0.01 * rank,
                connector=s.connector,
                source_url=s.source_url,
            )
            for rank, s in enumerate(found.snippets)
        ]
        return LiveSources(
            citations, list(found.unavailable_connectors), list(found.searched_connectors)
        )


def _source(kind: chat_pb2.RetrievalSourceKind, connector: str = "") -> chat_pb2.RetrievalSource:
    return chat_pb2.RetrievalSource(
        kind=kind, connector=connector, state=chat_pb2.RETRIEVAL_STATE_SEARCHING
    )


def _connector_states(live: LiveSources) -> list[chat_pb2.RetrievalSource]:
    if live.failed:
        return [
            chat_pb2.RetrievalSource(
                kind=chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR,
                state=chat_pb2.RETRIEVAL_STATE_UNAVAILABLE,
            )
        ]
    states = []
    for name in live.searched:
        down = name in live.unavailable
        states.append(
            chat_pb2.RetrievalSource(
                kind=chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR,
                connector=name,
                state=chat_pb2.RETRIEVAL_STATE_UNAVAILABLE
                if down
                else chat_pb2.RETRIEVAL_STATE_DONE,
                results=0 if down else sum(c.connector == name for c in live.citations),
            )
        )
    return states


class PeerRetriever:
    """Finds document passages and, with a manual, the manual sections that
    match the question; the question is embedded once for both. Passages
    scoring below `min_score` are unrelated to the question and left out, unless
    they contain its words. With `curation`, passages of documents that are
    replaced, deprecated or archived are left out, and a passage ranks down
    with its document's score (by up to `curation_weight`); without an answer
    from curation the order stays as found. With a `reranker`, `candidates`
    passages are fetched and the `limit` best by the reranker's rating are
    kept (passages rated alike keep the order before); if it fails, the best by
    the order before are. With `connectors`, the connectors that allow live search
    are asked at the same time (unless the question is limited to documents) and
    their snippets are cited next to the passages; they are not reranked."""

    def __init__(
        self,
        documents: document_pb2_grpc.DocumentServiceStub,
        llm: llm_pb2_grpc.LlmServiceStub,
        manual: Manual | None = None,
        min_score: float = 0.0,
        reranker: PeerReranker | None = None,
        candidates: int = 0,
        curation: PeerCuration | None = None,
        curation_weight: float = 0.0,
        connectors: PeerConnectors | None = None,
        connector_limit: int = 3,
    ) -> None:
        self._connectors = connectors
        self._connector_limit = connector_limit
        self._documents = documents
        self._embedder = PeerEmbedder(llm)
        self._manual = manual
        self._min_score = min_score
        self._reranker = reranker
        self._candidates = candidates
        self._curation = curation
        self._curation_weight = curation_weight

    async def retrieve(
        self,
        query: str,
        limit: int,
        document_ids: Sequence[uuid.UUID],
        team_ids: Sequence[uuid.UUID] = (),
        on_rating: Callable[[Sequence[chat_pb2.Citation]], None] | None = None,
        on_unavailable: Callable[[Sequence[str]], None] | None = None,
        on_retrieval: Callable[[list[chat_pb2.RetrievalSource]], None] | None = None,
    ) -> list[chat_pb2.Citation]:
        documents_state = _source(chat_pb2.RETRIEVAL_SOURCE_KIND_DOCUMENTS)
        connector_states: list[chat_pb2.RetrievalSource] = []

        def report() -> None:
            if on_retrieval:
                on_retrieval([documents_state, *connector_states])

        # Asked while the documents are searched; a question limited to chosen
        # documents is about those, not about connected systems.
        live = (
            asyncio.create_task(self._connectors.search(query, self._connector_limit, team_ids))
            if self._connectors and not document_ids
            else None
        )
        if live:
            # Their names are known only when they answer; until then one entry.
            connector_states.append(_source(chat_pb2.RETRIEVAL_SOURCE_KIND_CONNECTOR))

            def connectors_answered(task: "asyncio.Task[LiveSources]") -> None:
                if task.cancelled() or task.exception():
                    return
                connector_states[:] = _connector_states(task.result())
                report()

            live.add_done_callback(connectors_answered)
        report()
        try:
            found = await self.search_documents(query, limit, document_ids, team_ids, on_rating)
            documents_state.state = chat_pb2.RETRIEVAL_STATE_DONE
            documents_state.results = len(found)
            report()
            sources = await live if live else LiveSources([], [])
        finally:
            if live:
                live.cancel()
        if sources.unavailable and on_unavailable:
            on_unavailable(sources.unavailable)
        return merge_sources(found, sources.citations)

    async def search_documents(
        self,
        query: str,
        limit: int,
        document_ids: Sequence[uuid.UUID],
        team_ids: Sequence[uuid.UUID],
        on_rating: Callable[[Sequence[chat_pb2.Citation]], None] | None = None,
    ) -> list[chat_pb2.Citation]:
        """The passages of the documents, and the manual sections, that match `query`."""
        (embedding,) = await self._embedder.embed([query])
        fetch = max(limit, self._candidates) if self._reranker else limit
        if self._curation:
            fetch = max(fetch, limit * _CURATION_OVERFETCH)
        with _peer_errors(Peer.DOCUMENT):
            result = await self._documents.SearchChunks(
                document_pb2.SearchChunksRequest(
                    embedding=embedding,
                    # With the words too, passages with an exact term (a name,
                    # an id) are found even when they are far from the question
                    # in meaning.
                    query=query,
                    # Visibility is filtered by the document module, so only
                    # passages the caller may read reach the reranker.
                    limit=fetch,
                    document_ids=[str(i) for i in document_ids],
                    team_ids=[str(i) for i in team_ids],
                )
            )
        # `min_score` is the similarity; a passage that has the question's words
        # stays even when it is semantically far, as exact terms are.
        found = [r for r in result.results if r.keyword_match or r.score >= self._min_score]
        found = await self._curate(found)
        documents = [
            chat_pb2.Citation(
                document_id=r.chunk.document_id,
                document_title=r.document_title,
                chunk_index=r.chunk.index,
                # The passage that matched, not the whole chunk, when words found it.
                snippet=r.excerpt or r.chunk.text,
                score=r.score,
            )
            for r in found
        ]
        if self._reranker:
            # Rated on the whole chunk, whatever fragment is shown.
            documents = await self._rerank(
                query, documents, [r.chunk.text for r in found], on_rating
            )
        documents = documents[:limit]
        manual = self._manual.search(embedding) if self._manual else []
        return merge_sources(documents, manual)

    async def _curate(self, found: list[Any]) -> list[Any]:
        """Leaves out the passages of documents curation says not to cite and
        ranks the rest down by their document's score. The order of the
        document module is by rank, not by similarity, so a passage moves back
        by the factor its document's score takes off, not by a recomputed score."""
        if self._curation is None or not found:
            return found
        scores = await self._curation.scores({r.chunk.document_id for r in found})
        if scores is None:
            return found
        kept = [
            (position, r)
            for position, r in enumerate(found)
            if not ((s := scores.get(r.chunk.document_id)) and (s.excluded or s.replaced))
        ]

        def key(item: tuple[int, Any]) -> float:
            position, r = item
            s = scores.get(r.chunk.document_id)
            # A document without a score is new: it ranks as it was found.
            factor = 1 - self._curation_weight * (1 - s.score) if s else 1
            return (position + 1) / max(factor, 1e-6)

        return [r for _, r in sorted(kept, key=key)]

    async def _rerank(
        self,
        query: str,
        passages: list[chat_pb2.Citation],
        texts: list[str],
        on_rating: Callable[[Sequence[chat_pb2.Citation]], None] | None,
    ) -> list[chat_pb2.Citation]:
        if len(passages) < 2 or self._reranker is None:
            return passages
        if on_rating:
            on_rating(passages)
        try:
            scores = await self._reranker.rerank(query, texts)
        except PeerError as err:
            # Reranking only refines the order; the similarity order is still a good answer.
            log.warning("rerank failed, keeping the similarity order: %s", err)
            return passages
        order = sorted(range(len(passages)), key=lambda i: scores[i], reverse=True)
        return [passages[i] for i in order]


class PeerGenerator:
    def __init__(self, llm: llm_pb2_grpc.LlmServiceStub) -> None:
        self._llm = llm

    async def generate(self, model: str, prompt: list[PromptMessage]) -> AsyncGenerator[str]:
        async with contextlib.aclosing(self.turn(model, prompt, ())) as items:
            async for item in items:
                if isinstance(item, str):
                    yield item

    async def turn(
        self, model: str, prompt: list[PromptMessage], tools: Sequence[ToolSpec]
    ) -> AsyncGenerator[str | ToolCall]:
        """One generation: the text in deltas, then the tools the model called."""
        request = llm_pb2.GenerateRequest(
            model=model,
            messages=[_llm_message(m) for m in prompt],
            tools=[
                llm_pb2.ToolSpec(
                    name=t.name,
                    description=t.description,
                    parameters_json_schema=json.dumps(t.parameters),
                )
                for t in tools
            ],
            caller_module="chat",
        )
        with _peer_errors(Peer.LLM):
            call = self._llm.Generate(request)
            try:
                async for chunk in call:
                    if chunk.delta:
                        yield chunk.delta
                    for c in chunk.tool_calls:
                        yield ToolCall(c.id, c.name, c.arguments_json)
            finally:
                # Closed early (the answer was stopped): the llm stops generating.
                # A no-op once the call has finished.
                call.cancel()

    async def supports_tools(self, model: str) -> bool:
        """Whether the chat model (the llm module's default for an empty name)
        can call tools. When that can't be found out, it can't: the answer is
        then written without them."""
        try:
            with _peer_errors(Peer.LLM):
                if not model:
                    status = await self._llm.GetProviderStatus(llm_pb2.GetProviderStatusRequest())
                    model = status.default_chat_model
                listed = await self._llm.ListModels(llm_pb2.ListModelsRequest())
        except PeerError as err:
            log.warning("tool support of the model is unknown, answering without tools: %s", err)
            return False
        return any(
            m.id == model and m.kind == llm_pb2.MODEL_KIND_CHAT and m.supports_tools
            for m in listed.models
        )


def _llm_message(m: PromptMessage) -> llm_pb2.Message:
    return llm_pb2.Message(
        role=_LLM_ROLES[m.role],
        content=m.content,
        tool_calls=[
            llm_pb2.ToolCall(id=c.id, name=c.name, arguments_json=c.arguments) for c in m.tool_calls
        ],
        tool_call_id=m.tool_call_id,
    )


# Chunks of a document the model reads at once.
READ_CHUNKS = 4


class PeerDocuments:
    """Reads documents through the document module, for the caller's access."""

    def __init__(self, documents: document_pb2_grpc.DocumentServiceStub) -> None:
        self._documents = documents

    async def read(self, document_id: uuid.UUID, section: int) -> chat_pb2.Citation | None:
        """The `section` (from 1) of a document, `READ_CHUNKS` chunks of it, as
        one source; None past its end."""
        with _peer_errors(Peer.DOCUMENT):
            document = (
                await self._documents.GetDocument(
                    document_pb2.GetDocumentRequest(id=str(document_id))
                )
            ).document
            token = ""
            chunks: list[Any] = []
            for _ in range(section):
                if chunks and not token:
                    return None  # the document ended before this section
                page = await self._documents.ListChunks(
                    document_pb2.ListChunksRequest(
                        document_id=str(document_id),
                        page=common_pb2.PageRequest(page_size=READ_CHUNKS, page_token=token),
                    )
                )
                chunks, token = list(page.chunks), page.page.next_page_token
        if not chunks:
            return None
        return chat_pb2.Citation(
            document_id=str(document_id),
            document_title=document.title,
            chunk_index=chunks[0].index,
            snippet="\n\n".join(c.text for c in chunks),
            score=1.0,
        )
