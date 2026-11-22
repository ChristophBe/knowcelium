import json
from typing import Any

import grpc
import httpx
import pytest
from knowcel.document.v1 import document_pb2
from knowcel.iam.v1 import iam_pb2
from knowcel.ingestion.v1 import ingestion_pb2
from knowcel_ingestion_worker.connectors.library import DocumentGoneError, GrpcLibrary
from knowcel_ingestion_worker.connectors.model import ConnectorError, Record
from knowcel_ingestion_worker.connectors.spec import ConnectorSpec
from knowcel_ingestion_worker.connectors.state import KvState
from knowcel_platform.grpc import current_user
from nats.js.errors import KeyDeletedError, KeyNotFoundError, KeyWrongLastSequenceError


def rpc_error(code: grpc.StatusCode) -> grpc.aio.AioRpcError:
    return grpc.aio.AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), "x")


class FakeIngestion:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, str | None]] = []
        self.replace_error: grpc.StatusCode | None = None

    async def CreateUpload(self, req: ingestion_pb2.CreateUploadRequest):
        self.calls.append(("create", req, current_user()))
        return ingestion_pb2.CreateUploadResponse(
            job=ingestion_pb2.Job(id="job1", document_id="doc1"),
            upload_url="http://localhost:8333/bucket/doc1?X-Amz-Signature=s",
        )

    async def ReplaceUpload(self, req: ingestion_pb2.ReplaceUploadRequest):
        if self.replace_error:
            raise rpc_error(self.replace_error)
        self.calls.append(("replace", req, current_user()))
        return ingestion_pb2.ReplaceUploadResponse(
            job=ingestion_pb2.Job(id="job2", document_id=req.document_id),
            upload_url="http://localhost:8333/bucket/doc1?v=2",
        )

    async def CompleteUpload(self, req: ingestion_pb2.CompleteUploadRequest):
        self.calls.append(("complete", req, current_user()))
        return ingestion_pb2.CompleteUploadResponse()


class FakeDocuments:
    def __init__(self) -> None:
        self.updates: list[document_pb2.UpdateDocumentRequest] = []
        self.deleted: list[str] = []
        self.delete_error: grpc.StatusCode | None = None

    async def UpdateDocument(self, req: document_pb2.UpdateDocumentRequest):
        self.updates.append(req)
        return document_pb2.UpdateDocumentResponse()

    async def DeleteDocument(self, req: document_pb2.DeleteDocumentRequest):
        if self.delete_error:
            raise rpc_error(self.delete_error)
        self.deleted.append(req.id)
        return document_pb2.DeleteDocumentResponse()


class FakeIam:
    def __init__(self, admin: bool) -> None:
        self.admin = admin
        self.asked_as: str | None = None

    async def ResolveCaller(self, req: iam_pb2.ResolveCallerRequest):
        self.asked_as = current_user()
        return iam_pb2.ResolveCallerResponse(user_id="u", platform_admin=self.admin)


SPEC = ConnectorSpec(
    name="docs", kind="folder", owner="admin-1", team_ids=["t1"], settings={"path": "."}
)
RECORD = Record(
    external_id="a.md", filename="a.md", title="A", source_url="file:///a.md", metadata={"k": "v"}
)


def build(
    upload_endpoint: str = "", status: int = 200, admin: bool = True
) -> tuple[GrpcLibrary, FakeIngestion, FakeDocuments, FakeIam, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status)

    ingestion, documents, iam = FakeIngestion(), FakeDocuments(), FakeIam(admin)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    library = GrpcLibrary(ingestion, documents, iam, http, upload_endpoint)  # type: ignore[arg-type]
    return library, ingestion, documents, iam, requests


async def test_create_uploads_as_the_owner_to_the_chosen_teams():
    library, ingestion, documents, _, requests = build()
    assert await library.create(SPEC, RECORD, b"hello") == "doc1"
    kinds = [c[0] for c in ingestion.calls]
    assert kinds == ["create", "complete"]
    assert {c[2] for c in ingestion.calls} == {"admin-1"}
    request = ingestion.calls[0][1]
    assert list(request.team_ids) == ["t1"]
    assert request.access == ingestion_pb2.ACCESS_TEAM
    assert (request.filename, request.title, request.size_bytes) == ("a.md", "A", 5)
    assert requests[0].content == b"hello"
    assert requests[0].headers["content-type"] == "text/markdown"
    assert dict(documents.updates[0].metadata) == {
        "k": "v",
        "connector": "docs",
        "connector_external_id": "a.md",
        "source_url": "file:///a.md",
    }


async def test_public_connectors_upload_publicly():
    library, ingestion, *_ = build()
    public = SPEC.model_copy(update={"team_ids": [], "public": True})
    await library.create(public, RECORD, b"x")
    assert ingestion.calls[0][1].access == ingestion_pb2.ACCESS_PUBLIC


async def test_the_upload_goes_to_the_internal_storage_with_the_signed_host():
    library, *_, requests = build(upload_endpoint="s3:8333")
    await library.create(SPEC, RECORD, b"x")
    assert requests[0].url.host == "s3"
    assert requests[0].headers["host"] == "localhost:8333"
    assert requests[0].url.params["X-Amz-Signature"] == "s"


async def test_a_failed_upload_removes_the_unfinished_document():
    library, ingestion, documents, _, _ = build(status=500)
    with pytest.raises(httpx.HTTPStatusError):
        await library.create(SPEC, RECORD, b"x")
    assert documents.deleted == ["doc1"]
    assert "complete" not in [c[0] for c in ingestion.calls]


async def test_a_failed_cleanup_does_not_hide_the_error():
    library, _, documents, _, _ = build(status=500)
    documents.delete_error = grpc.StatusCode.UNAVAILABLE
    with pytest.raises(httpx.HTTPStatusError):
        await library.create(SPEC, RECORD, b"x")


async def test_replace_uploads_a_new_version_and_updates_title_and_metadata():
    library, ingestion, documents, _, requests = build()
    await library.replace(SPEC, "doc1", RECORD, b"new")
    assert [c[0] for c in ingestion.calls] == ["replace", "complete"]
    assert requests[0].content == b"new"
    assert documents.updates[0].title == "A"
    assert documents.updates[0].metadata["connector"] == "docs"


async def test_replace_of_a_deleted_document_says_so():
    library, ingestion, *_ = build()
    ingestion.replace_error = grpc.StatusCode.NOT_FOUND
    with pytest.raises(DocumentGoneError):
        await library.replace(SPEC, "doc1", RECORD, b"x")
    ingestion.replace_error = grpc.StatusCode.FAILED_PRECONDITION
    with pytest.raises(grpc.aio.AioRpcError):
        await library.replace(SPEC, "doc1", RECORD, b"x")


async def test_delete_ignores_documents_that_are_already_gone():
    library, _, documents, _, _ = build()
    await library.delete(SPEC, "doc1")
    assert documents.deleted == ["doc1"]
    documents.delete_error = grpc.StatusCode.NOT_FOUND
    await library.delete(SPEC, "doc2")
    documents.delete_error = grpc.StatusCode.UNAVAILABLE
    with pytest.raises(grpc.aio.AioRpcError):
        await library.delete(SPEC, "doc3")


async def test_only_a_platform_admin_may_own_a_connector():
    library, _, _, iam, _ = build(admin=True)
    await library.ensure_admin("admin-1")
    assert iam.asked_as == "admin-1"
    library, *_ = build(admin=False)
    with pytest.raises(ConnectorError, match="not a platform admin"):
        await library.ensure_admin("someone")


# --- the JetStream key-value state ------------------------------------------


class Entry:
    def __init__(self, value: bytes, revision: int) -> None:
        self.value, self.revision = value, revision


class FakeKv:
    """The parts of a JetStream key-value bucket KvState uses."""

    def __init__(self) -> None:
        self.data: dict[str, Entry] = {}
        self.rev = 0

    async def get(self, key: str) -> Entry:
        if key not in self.data:
            raise KeyNotFoundError
        entry = self.data[key]
        if not entry.value:
            raise KeyDeletedError
        return entry

    async def put(self, key: str, value: bytes) -> int:
        self.rev += 1
        self.data[key] = Entry(value, self.rev)
        return self.rev

    async def create(self, key: str, value: bytes) -> int:
        if key in self.data and self.data[key].value:
            raise KeyWrongLastSequenceError
        return await self.put(key, value)

    async def update(self, key: str, value: bytes, last: int) -> int:
        if self.data[key].revision != last:
            raise KeyWrongLastSequenceError
        return await self.put(key, value)

    async def delete(self, key: str) -> None:
        if key not in self.data:
            raise KeyNotFoundError
        await self.put(key, b"")

    async def watch(self, subject: str, **_: object) -> "Watcher":
        assert subject.endswith(">")
        live = [(k, e) for k, e in self.data.items() if e.value and k.startswith(subject[:-1])]
        return Watcher([Item(k, e.value) for k, e in live])


class Item:
    def __init__(self, key: str, value: bytes) -> None:
        self.key, self.value = key, value


class Watcher:
    def __init__(self, items: list[Item]) -> None:
        self._items: list[Item | None] = [*items, None]

    def __aiter__(self):
        return self

    async def __anext__(self) -> Item | None:
        return self._items.pop(0)

    async def stop(self) -> None:
        pass


async def test_kv_state_stores_json_by_key():
    state = KvState(FakeKv())
    assert await state.get("a.item.1") is None
    assert await state.keys("a.item.") == []
    await state.put("a.item.1", {"x": 1})
    await state.put("b.status", {"y": 2})
    assert await state.get("a.item.1") == {"x": 1}
    await state.put("a.items", {"z": 3})
    assert await state.keys("a.item.") == ["a.item.1"]
    assert await state.items("a.item.") == {"a.item.1": {"x": 1}}
    await state.delete("a.item.1")
    await state.delete("a.item.1")
    assert await state.get("a.item.1") is None


async def test_kv_state_leases():
    now = [100.0]
    kv = FakeKv()
    state = KvState(kv, clock=lambda: now[0])
    assert await state.acquire("c.lease", "a", 10)
    assert await state.acquire("c.lease", "a", 10)  # the holder renews
    assert not await state.acquire("c.lease", "b", 10)
    await state.release("c.lease", "b")  # not the holder: no effect
    assert not await state.acquire("c.lease", "b", 10)
    now[0] = 111
    assert await state.acquire("c.lease", "b", 10)  # expired
    await state.release("c.lease", "b")
    await state.release("c.lease", "b")
    assert await state.acquire("c.lease", "a", 10)  # after a release (deleted marker)


async def test_kv_state_loses_a_race_for_the_lease():
    class Racing(FakeKv):
        async def update(self, key: str, value: bytes, last: int) -> int:
            await self.put(key, json.dumps({"holder": "c", "until": 10**9}).encode())
            return await super().update(key, value, last)

    kv = Racing()
    state = KvState(kv, clock=lambda: 100.0)
    await state.put("c.lease", {"holder": "a", "until": 1})
    assert not await state.acquire("c.lease", "b", 10)
