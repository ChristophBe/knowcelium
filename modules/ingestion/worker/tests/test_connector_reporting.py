"""What the runtime reports to the ingestion service about each connector."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.protobuf.message import Message
from knowcel.ingestion.v1 import events_pb2
from knowcel_ingestion_worker.config import Settings
from knowcel_ingestion_worker.connectors import service
from knowcel_ingestion_worker.connectors.model import ConnectorError, Record
from knowcel_ingestion_worker.connectors.registry import KINDS, Kind
from knowcel_ingestion_worker.connectors.reporting import (
    SUBJECT_CONFIGURED,
    SUBJECT_SYNCED,
    EventReporter,
    NullReporter,
    SyncReport,
    SyncResult,
)
from knowcel_ingestion_worker.connectors.runner import Runner
from knowcel_ingestion_worker.connectors.service import announce
from knowcel_ingestion_worker.connectors.spec import ConnectorSpec, parse_specs
from knowcel_ingestion_worker.connectors.state import MemoryState
from knowcel_ingestion_worker.connectors.testkit import MemoryLibrary
from pydantic import BaseModel


class FakeLibrary(MemoryLibrary):
    """A library whose uploads of the external ids in `fail` fail."""

    def __init__(self) -> None:
        super().__init__()
        self.admin = True
        self.fail: set[str] = set()

    async def ensure_admin(self, owner: str) -> None:
        if not self.admin:
            raise ConnectorError(f"owner {owner} is not a platform admin")

    async def create(self, spec: ConnectorSpec, record: Record, data: bytes) -> str:
        if record.external_id in self.fail:
            raise RuntimeError("storage is down")
        return await super().create(spec, record, data)


class ListSource:
    complete = True

    def __init__(self) -> None:
        self.records: list[Record] = []

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        for r in self.records:
            yield r


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


def rec(id: str, text: str = "hello") -> Record:
    return Record(external_id=id, filename=id, data=text.encode(), version=text)


def spec() -> ConnectorSpec:
    return ConnectorSpec(name="docs", kind="folder", owner="admin-1", team_ids=["t"], settings={})


class Published:
    """Records what is published as (subject, message, dedupe id)."""

    def __init__(self, fail: bool = False) -> None:
        self.events: list[tuple[str, Message, str]] = []
        self.fail = fail
        self.three = asyncio.Event()  # set once three events were published

    async def __call__(self, subject: str, message: Message, dedupe_id: str) -> None:
        if self.fail:
            raise ConnectionError("nats is down")
        self.events.append((subject, message, dedupe_id))
        if len(self.events) >= 3:
            self.three.set()

    def synced(self) -> list[events_pb2.ConnectorSynced]:
        return [m for _, m, _ in self.events if isinstance(m, events_pb2.ConnectorSynced)]


class Anything(BaseModel):
    pass


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> ListSource:
    src = ListSource()
    monkeypatch.setitem(KINDS, "folder", Kind(Anything, lambda _c: src))
    return src


@pytest.fixture
def published() -> Published:
    return Published()


@pytest.fixture
def library() -> FakeLibrary:
    return FakeLibrary()


@pytest.fixture
def runner(published: Published, library: FakeLibrary) -> Runner:
    return Runner(
        library, MemoryState(), clock=Clock(), holder="w1", reporter=EventReporter(published)
    )


async def test_a_successful_sync_is_reported_with_its_times_and_documents(
    source: ListSource, runner: Runner, published: Published
):
    source.records = [rec("a.md"), rec("b.md")]
    await runner.sync(spec())
    (event,) = published.synced()
    assert event.name == "docs"
    assert event.outcome == events_pb2.SYNC_OUTCOME_SUCCEEDED
    assert event.documents == 2
    assert event.error == ""
    assert (event.kind, event.enabled, event.interval_seconds) == ("folder", True, 300)
    assert event.start_time.ToDatetime(tzinfo=UTC) < event.end_time.ToDatetime(tzinfo=UTC)
    subject, _, dedupe_id = published.events[0]
    assert subject == SUBJECT_SYNCED
    assert dedupe_id.startswith("synced:docs:")


async def test_a_failing_item_among_working_ones_is_a_partial_failure(
    source: ListSource, runner: Runner, published: Published, library: FakeLibrary
):
    library.fail = {"b.md"}
    source.records = [rec("a.md"), rec("b.md")]
    await runner.sync(spec())
    (event,) = published.synced()
    assert event.outcome == events_pb2.SYNC_OUTCOME_PARTIAL
    assert "b.md: storage is down" in event.error
    assert event.documents == 1


async def test_a_run_where_no_item_syncs_failed(
    source: ListSource, runner: Runner, published: Published, library: FakeLibrary
):
    library.fail = {"a.md"}
    source.records = [rec("a.md")]
    await runner.sync(spec())
    (event,) = published.synced()
    assert event.outcome == events_pb2.SYNC_OUTCOME_FAILED
    assert "1 items failed" in event.error


async def test_a_run_that_cannot_start_failed_with_the_reason(
    source: ListSource, runner: Runner, published: Published, library: FakeLibrary
):
    library.admin = False
    await runner.sync(spec())
    (event,) = published.synced()
    assert event.outcome == events_pb2.SYNC_OUTCOME_FAILED
    assert "not a platform admin" in event.error
    # Nothing was counted this run, but the connector has none yet either.
    assert event.documents == 0


async def test_skipped_items_are_a_success_with_a_note(
    source: ListSource, runner: Runner, published: Published
):
    source.records = [rec("a.md"), rec("empty.md", "")]
    await runner.sync(spec())
    (event,) = published.synced()
    assert event.outcome == events_pb2.SYNC_OUTCOME_SUCCEEDED
    assert "1 items skipped" in event.error


async def test_a_sync_another_worker_holds_the_lease_for_is_not_reported(
    source: ListSource, library: FakeLibrary, published: Published
):
    state = MemoryState()
    runner = Runner(library, state, clock=Clock(), reporter=EventReporter(published))
    assert await state.acquire("docs.lease", "other", 600)
    await runner.sync(spec())
    assert published.events == []


async def test_a_failing_publish_does_not_fail_the_sync(
    source: ListSource, library: FakeLibrary, caplog: pytest.LogCaptureFixture
):
    runner = Runner(
        library, MemoryState(), clock=Clock(), reporter=EventReporter(Published(fail=True))
    )
    source.records = [rec("a.md")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.created == 1
    assert "cannot report" in caplog.text


async def test_the_configured_connectors_are_announced_valid_or_not(
    source: ListSource, published: Published
):
    loaded = parse_specs(
        [
            {
                "name": "docs",
                "kind": "folder",
                "owner": "a",
                "public": True,
                "interval_seconds": 60,
            },
            {"name": "off", "kind": "folder", "owner": "a", "public": True, "enabled": False},
            {"name": "broken", "kind": "nope", "owner": "a", "public": True},
        ]
    )
    at = datetime(2026, 1, 1, tzinfo=UTC)
    await EventReporter(published).configured(loaded, at)
    ((subject, event, _),) = published.events
    assert subject == SUBJECT_CONFIGURED
    assert isinstance(event, events_pb2.ConnectorsConfigured)
    by_name: dict[str, Any] = {c.name: c for c in event.connectors}
    assert set(by_name) == {"docs", "off", "broken"}
    assert (by_name["docs"].kind, by_name["docs"].interval_seconds) == ("folder", 60)
    assert by_name["docs"].enabled
    assert not by_name["off"].enabled
    assert "unknown kind" in by_name["broken"].error
    assert by_name["docs"].error == ""
    assert event.time.ToDatetime(tzinfo=UTC) == at


async def test_a_report_of_a_run_that_never_started_has_no_start_time(published: Published):
    ended = datetime(2026, 1, 1, tzinfo=UTC)
    await EventReporter(published).synced(SyncReport("x", SyncResult.FAILED, None, ended, 0, "bad"))
    (event,) = published.synced()
    assert not event.HasField("start_time")
    assert event.HasField("end_time")


async def test_an_unreadable_state_store_leaves_the_document_count_unknown(
    source: ListSource, library: FakeLibrary, published: Published
):
    class BrokenState(MemoryState):
        async def get(self, key: str):
            if key.endswith(".status"):
                raise ConnectionError("nats is down")
            return await super().get(key)

    runner = Runner(library, BrokenState(), clock=Clock(), reporter=EventReporter(published))
    await runner.sync(spec())
    (event,) = published.synced()
    assert event.outcome == events_pb2.SYNC_OUTCOME_FAILED
    assert not event.HasField("documents")
    assert "nats is down" in event.error


async def test_the_configured_connectors_are_announced_again_until_stopped(
    source: ListSource, published: Published
):
    stop = asyncio.Event()
    task = asyncio.create_task(
        announce(EventReporter(published), parse_specs([]), stop, every=0.01)
    )
    await asyncio.wait_for(published.three.wait(), 5)
    stop.set()
    await task
    assert {subject for subject, _, _ in published.events} == {SUBJECT_CONFIGURED}


async def test_a_worker_without_a_connectors_file_announces_none(published: Published):
    class Subscription:
        async def unsubscribe(self) -> None:
            pass

    class Nats:
        async def subscribe(self, *_: object, **__: object) -> Subscription:
            return Subscription()

    settings = Settings(connectors_file="")
    stop = asyncio.Event()

    async def publish_then_stop(subject: str, message: Message, dedupe_id: str) -> None:
        await published(subject, message, dedupe_id)
        stop.set()  # it keeps answering live searches until stopped

    async with asyncio.timeout(5):
        await service.run(settings, Nats(), None, None, publish_then_stop, stop)  # type: ignore[arg-type]
    ((subject, event, _),) = published.events
    assert subject == SUBJECT_CONFIGURED
    assert isinstance(event, events_pb2.ConnectorsConfigured)
    assert len(event.connectors) == 0


async def test_the_null_reporter_does_nothing():
    reporter = NullReporter()
    await reporter.configured(parse_specs([]), datetime.now(UTC))
    await reporter.synced(SyncReport("x", SyncResult.SUCCEEDED, None, datetime.now(UTC), 0))
