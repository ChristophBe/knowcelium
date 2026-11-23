"""Reporting what the connectors do to the ingestion service, which serves it
as the connectors' status (ListConnectors). The worker's own bookkeeping (the
`<name>.status` keys, see state.py) stays in the key-value bucket: it is what
the next sync starts from. This is the copy people read.

Reports are events: a lost one only delays the status until the next run, so
reporting never fails a sync."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from knowcel.ingestion.v1 import events_pb2

from .spec import Loaded

log = logging.getLogger(__name__)

SUBJECT_SYNCED = "knowcel.ingestion.connector_synced"
SUBJECT_CONFIGURED = "knowcel.ingestion.connectors_configured"

# publish(subject, message, dedupe_id), as in worker.Publish.
Publish = Callable[[str, Message, str], Awaitable[None]]


class SyncResult(Enum):
    """How a sync run ended (events.proto: SyncOutcome)."""

    SUCCEEDED = events_pb2.SYNC_OUTCOME_SUCCEEDED
    # Some items synced, others failed.
    PARTIAL = events_pb2.SYNC_OUTCOME_PARTIAL
    # The run failed as a whole, or no item synced.
    FAILED = events_pb2.SYNC_OUTCOME_FAILED


@dataclass(frozen=True)
class SyncReport:
    connector: str
    result: SyncResult
    # None when the run failed before it started.
    started: datetime | None
    ended: datetime
    # None when the state store could not tell; the service keeps the last count.
    documents: int | None
    # Why the run failed, or a note about it (items skipped).
    error: str = ""
    # The connector's configuration, so that its status appears even when the
    # announcement at start was lost.
    kind: str = ""
    enabled: bool = True
    interval_seconds: int = 0


class Reporter(Protocol):
    async def configured(self, loaded: Loaded, at: datetime) -> None:
        """Announces the connectors of the connectors file, valid or not."""
        ...

    async def synced(self, report: SyncReport) -> None: ...


class NullReporter:
    """Reports nothing, for tests and runs without an ingestion service."""

    async def configured(self, loaded: Loaded, at: datetime) -> None:
        return None

    async def synced(self, report: SyncReport) -> None:
        return None


class EventReporter:
    """Reports through NATS events."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def configured(self, loaded: Loaded, at: datetime) -> None:
        event = events_pb2.ConnectorsConfigured(time=_timestamp(at))
        for spec in loaded.specs:
            event.connectors.add(
                name=spec.name,
                kind=spec.kind,
                enabled=spec.enabled,
                interval_seconds=spec.interval_seconds,
            )
        for name, error in loaded.errors.items():
            event.connectors.add(name=name, enabled=True, error=error)
        await self._send(SUBJECT_CONFIGURED, event, f"configured:{at.isoformat()}")

    async def synced(self, report: SyncReport) -> None:
        event = events_pb2.ConnectorSynced(
            name=report.connector,
            outcome=report.result.value,
            end_time=_timestamp(report.ended),
            documents=report.documents,
            error=report.error,
            kind=report.kind,
            enabled=report.enabled,
            interval_seconds=report.interval_seconds,
        )
        if report.started:
            event.start_time.CopyFrom(_timestamp(report.started))
        dedupe_id = f"synced:{report.connector}:{report.ended.isoformat()}"
        await self._send(SUBJECT_SYNCED, event, dedupe_id)

    async def _send(self, subject: str, event: Message, dedupe_id: str) -> None:
        try:
            await self._publish(subject, event, dedupe_id)
        except Exception:
            log.exception("cannot report %s", subject)


def _timestamp(value: datetime) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(value)
    return ts
