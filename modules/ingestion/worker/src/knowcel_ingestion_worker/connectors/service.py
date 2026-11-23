"""Starts the connector runtime inside the worker process."""

import asyncio
import logging

import httpx
from knowcel.document.v1 import document_pb2_grpc
from knowcel.iam.v1 import iam_pb2_grpc
from knowcel.ingestion.v1 import ingestion_pb2_grpc
from knowcel_platform.grpc import channel
from nats.js import JetStreamContext

from ..config import Settings
from .library import GrpcLibrary
from .reporting import EventReporter, Publish
from .runner import Runner, now, run_schedule
from .spec import load_specs
from .state import KvState

log = logging.getLogger(__name__)

# Seconds a document or ingestion call may take; the file upload is the slowest.
_HTTP_TIMEOUT = 120


async def run(
    settings: Settings,
    js: JetStreamContext,
    documents: document_pb2_grpc.DocumentServiceStub,
    publish: Publish,
    stop: asyncio.Event,
) -> None:
    """Syncs the connectors of `settings.connectors_file` until `stop` is set,
    reporting their status through `publish`. Does nothing without a file."""
    if not settings.connectors_file:
        return
    loaded = load_specs(settings.connectors_file)
    state = await KvState.open(js)
    async with (
        channel(settings.ingestion_addr) as ingestion_ch,
        channel(settings.iam_addr) as iam_ch,
        httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as http,
    ):
        library = GrpcLibrary(
            ingestion_pb2_grpc.IngestionServiceStub(ingestion_ch),
            documents,
            iam_pb2_grpc.IamServiceStub(iam_ch),
            http,
            settings.connectors_upload_endpoint,
        )
        reporter = EventReporter(publish)
        runner = Runner(library, state, reporter=reporter)
        await reporter.configured(loaded, now())
        for name, error in loaded.errors.items():
            log.error("connector %s is not started: %s", name, error)
            await runner.report(name, error)
        log.info("running %d connectors", len(loaded.specs))
        await run_schedule(runner, loaded.specs, stop)
