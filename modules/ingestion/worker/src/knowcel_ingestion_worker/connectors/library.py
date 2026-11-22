"""Where synced content goes: the knowledge base, reached as the connector's
owner through the same RPCs a user's upload takes. Jobs, events, processing
and access rules are therefore exactly those of an upload."""

import hashlib
import logging
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import grpc
import httpx
from knowcel.document.v1 import document_pb2, document_pb2_grpc
from knowcel.iam.v1 import iam_pb2, iam_pb2_grpc
from knowcel.ingestion.v1 import ingestion_pb2, ingestion_pb2_grpc
from knowcel_platform.grpc import as_user

from .model import ConnectorError, Record
from .spec import ConnectorSpec

log = logging.getLogger(__name__)

# Metadata every synced document carries; the document page shows it as the
# document's origin.
META_CONNECTOR = "connector"
META_EXTERNAL_ID = "connector_external_id"
META_SOURCE_URL = "source_url"


class DocumentGoneError(Exception):
    """The document was deleted in the knowledge base since it was synced."""


class Library(Protocol):
    async def ensure_admin(self, owner: str) -> None:
        """Raises `ConnectorError` unless `owner` is a platform admin."""
        ...

    async def create(self, spec: ConnectorSpec, record: Record, data: bytes) -> str:
        """Adds a document and queues its processing; returns its id."""
        ...

    async def replace(
        self, spec: ConnectorSpec, document_id: str, record: Record, data: bytes
    ) -> None:
        """Uploads a new version; raises `DocumentGoneError` when the document is gone."""
        ...

    async def delete(self, spec: ConnectorSpec, document_id: str) -> None: ...


def metadata_of(spec: ConnectorSpec, record: Record) -> dict[str, str]:
    meta = dict(record.metadata)
    meta[META_CONNECTOR] = spec.name
    meta[META_EXTERNAL_ID] = record.external_id
    if record.source_url:
        meta[META_SOURCE_URL] = record.source_url
    return meta


class GrpcLibrary:
    def __init__(
        self,
        ingestion: ingestion_pb2_grpc.IngestionServiceStub,
        documents: document_pb2_grpc.DocumentServiceStub,
        iam: iam_pb2_grpc.IamServiceStub,
        http: httpx.AsyncClient,
        upload_endpoint: str = "",
    ) -> None:
        self._ingestion = ingestion
        self._documents = documents
        self._iam = iam
        self._http = http
        self._upload_endpoint = upload_endpoint

    async def ensure_admin(self, owner: str) -> None:
        with as_user(owner):
            caller = await self._iam.ResolveCaller(iam_pb2.ResolveCallerRequest())
        if not caller.platform_admin:
            raise ConnectorError(
                f"owner {owner} is not a platform admin; only a platform admin can run a connector"
            )

    async def create(self, spec: ConnectorSpec, record: Record, data: bytes) -> str:
        content_type = record.media_type()
        with as_user(spec.owner):
            resp = await self._ingestion.CreateUpload(
                ingestion_pb2.CreateUploadRequest(
                    filename=record.filename or record.external_id,
                    content_type=content_type,
                    size_bytes=len(data),
                    title=record.title,
                    sha256=hashlib.sha256(data).hexdigest(),
                    access=ingestion_pb2.ACCESS_PUBLIC
                    if spec.public
                    else ingestion_pb2.ACCESS_TEAM,
                    team_ids=spec.team_ids,
                )
            )
            document_id = resp.job.document_id
            try:
                await self._set_metadata(document_id, metadata_of(spec, record))
                await self._upload(resp.upload_url, content_type, data)
                await self._ingestion.CompleteUpload(
                    ingestion_pb2.CompleteUploadRequest(job_id=resp.job.id)
                )
            except Exception:
                # Nothing would ever finish or clean up a document left waiting for its file.
                try:
                    await self._documents.DeleteDocument(
                        document_pb2.DeleteDocumentRequest(id=document_id)
                    )
                except grpc.aio.AioRpcError as err:
                    log.warning("could not remove unfinished document %s: %s", document_id, err)
                raise
        return document_id

    async def replace(
        self, spec: ConnectorSpec, document_id: str, record: Record, data: bytes
    ) -> None:
        content_type = record.media_type()
        with as_user(spec.owner):
            try:
                resp = await self._ingestion.ReplaceUpload(
                    ingestion_pb2.ReplaceUploadRequest(
                        document_id=document_id,
                        filename=record.filename or record.external_id,
                        content_type=content_type,
                        size_bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )
            except grpc.aio.AioRpcError as err:
                if err.code() == grpc.StatusCode.NOT_FOUND:
                    raise DocumentGoneError(document_id) from err
                raise
            await self._upload(resp.upload_url, content_type, data)
            await self._ingestion.CompleteUpload(
                ingestion_pb2.CompleteUploadRequest(job_id=resp.job.id)
            )
            await self._set_metadata(document_id, metadata_of(spec, record), record.title)

    async def delete(self, spec: ConnectorSpec, document_id: str) -> None:
        with as_user(spec.owner):
            try:
                await self._documents.DeleteDocument(
                    document_pb2.DeleteDocumentRequest(id=document_id)
                )
            except grpc.aio.AioRpcError as err:
                if err.code() != grpc.StatusCode.NOT_FOUND:
                    raise

    async def _set_metadata(
        self, document_id: str, metadata: Mapping[str, str], title: str | None = None
    ) -> None:
        await self._documents.UpdateDocument(
            document_pb2.UpdateDocumentRequest(
                id=document_id, title=title or None, metadata=metadata, set_metadata=True
            )
        )

    async def _upload(self, url: str, content_type: str, data: bytes) -> None:
        """PUTs the file to the presigned URL. That URL names the storage
        server as clients outside the stack reach it; from the worker the same
        server is at `upload_endpoint`, and the signature only holds with the
        original Host header."""
        parts = urlsplit(url)
        headers = {"Content-Type": content_type}
        if self._upload_endpoint:
            headers["Host"] = parts.netloc
            url = urlunsplit(parts._replace(netloc=self._upload_endpoint))
        resp = await self._http.put(url, content=data, headers=headers)
        resp.raise_for_status()
