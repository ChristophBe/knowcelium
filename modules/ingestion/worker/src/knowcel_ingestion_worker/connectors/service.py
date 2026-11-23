"""Starts the connector runtime inside the worker process."""

import asyncio
import contextlib
import logging

import httpx
from knowcel.document.v1 import document_pb2_grpc
from knowcel.iam.v1 import iam_pb2_grpc
from knowcel.ingestion.v1 import ingestion_pb2_grpc
from knowcel_platform.grpc import channel
from nats.js import JetStreamContext

from ..config import Settings
from .library import GrpcLibrary
from .reporting import EventReporter, Publish, Reporter
from .runner import Runner, now, run_schedule
from .spec import Loaded, load_specs
from .state import KvState

log = logging.getLogger(__name__)

# Seconds a document or ingestion call may take; the file upload is the slowest.
_HTTP_TIMEOUT = 120
# Seconds between two announcements of the configured connectors.
ANNOUNCE_SECONDS = 300


async def run(
    settings: Settings,
    js: JetStreamContext,
    documents: document_pb2_grpc.DocumentServiceStub,
    publish: Publish,
    stop: asyncio.Event,
) -> None:
    """Syncs the connectors of `settings.connectors_file` until `stop` is set,
    reporting their status through `publish`. Does nothing without a file."""
    loaded = load_specs(settings.connectors_file) if settings.connectors_file else Loaded()
    reporter = EventReporter(publish)
    if not settings.connectors_file:
        # Says so, so that connectors configured before are forgotten.
        await reporter.configured(loaded, now())
        return
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
        runner = Runner(library, state, reporter=reporter)
        for name, error in loaded.errors.items():
            log.error("connector %s is not started: %s", name, error)
            await runner.report(name, error)
        log.info("running %d connectors", len(loaded.specs))
        announcing = asyncio.create_task(announce(reporter, loaded, stop))
        try:
            await run_schedule(runner, loaded.specs, stop)
        finally:
            announcing.cancel()


async def announce(
    reporter: Reporter, loaded: Loaded, stop: asyncio.Event, every: float = ANNOUNCE_SECONDS
) -> None:
    """Announces the configured connectors at start and then every `every`
    seconds until `stop` is set: the announcement is an event that can be
    lost, and it is what makes the service forget removed connectors."""
    while not stop.is_set():
        await reporter.configured(loaded, now())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), every)
