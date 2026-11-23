import asyncio
import os
import pathlib
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import grpc
import pytest
from knowcel_ingestion_worker.config import Settings
from knowcel_ingestion_worker.connectors import runner as runner_module
from knowcel_ingestion_worker.connectors.folder import FolderConfig, FolderConnector
from knowcel_ingestion_worker.connectors.library import DocumentGoneError, metadata_of
from knowcel_ingestion_worker.connectors.model import ConnectorError, Record
from knowcel_ingestion_worker.connectors.registry import KINDS, Kind
from knowcel_ingestion_worker.connectors.runner import Runner, run_schedule
from knowcel_ingestion_worker.connectors.spec import ConnectorSpec, load_specs, parse_specs
from knowcel_ingestion_worker.connectors.state import KvState, MemoryState, item_key, status_key
from knowcel_platform.config import Problems
from nats.js.errors import InvalidKeyError, KeyNotFoundError, KeyWrongLastSequenceError
from pydantic import BaseModel


class FakeLibrary:
    """Keeps documents in a dict; `fail` names external ids whose upload fails."""

    def __init__(self, admin: bool = True) -> None:
        self.admin = admin
        self.docs: dict[str, tuple[str, bytes]] = {}  # document id -> (external id, data)
        self.fail: set[str] = set()
        self.calls: list[str] = []
        self.gone: set[str] = set()
        self._next = 0

    async def ensure_admin(self, owner: str) -> None:
        if not self.admin:
            raise ConnectorError(f"owner {owner} is not a platform admin")

    async def create(self, spec: ConnectorSpec, record: Record, data: bytes) -> str:
        if record.external_id in self.fail:
            raise RuntimeError("storage is down")
        self._next += 1
        doc = f"doc{self._next}"
        self.docs[doc] = (record.external_id, data)
        self.calls.append(f"create {record.external_id}")
        return doc

    async def replace(self, spec: ConnectorSpec, document_id: str, record: Record, data: bytes):
        if document_id in self.gone:
            raise DocumentGoneError(document_id)
        self.docs[document_id] = (record.external_id, data)
        self.calls.append(f"replace {record.external_id}")

    async def delete(self, spec: ConnectorSpec, document_id: str) -> None:
        self.docs.pop(document_id, None)
        self.calls.append(f"delete {document_id}")


def spec(**overrides: Any) -> ConnectorSpec:
    values: dict[str, Any] = {
        "name": "docs",
        "kind": "folder",
        "owner": "admin-1",
        "team_ids": ["team-1"],
        "settings": {"path": "."},
    }
    return ConnectorSpec(**{**values, **overrides})


class ListSource:
    """A source that returns what a test sets, as a complete or incremental listing."""

    def __init__(self, complete: bool) -> None:
        self.complete = complete
        self.records: list[Record] = []
        self.since: list[datetime | None] = []

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        self.since.append(since)
        for r in self.records:
            yield r


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> ListSource:
    src = ListSource(complete=True)
    monkeypatch.setitem(KINDS, "folder", Kind(AnySettings, lambda _c: src))
    return src


class AnySettings(BaseModel):
    pass


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


def rec(id: str, text: str = "hello", version: str = "") -> Record:
    return Record(external_id=id, filename=f"{id}.md", data=text.encode(), version=version or text)


Parts = tuple[Runner, FakeLibrary, MemoryState]


@pytest.fixture
def runner_parts() -> Parts:
    library, state = FakeLibrary(), MemoryState()
    return Runner(library, state, clock=Clock(), holder="w1"), library, state


async def test_sync_adds_changes_and_removes(source: ListSource, runner_parts: Parts):
    runner, library, state = runner_parts
    source.records = [rec("a.md", "one"), rec("b.md", "two")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.created == 2
    assert sorted(d[0] for d in library.docs.values()) == ["a.md", "b.md"]

    # Unchanged files are left alone, a changed one is replaced, a missing one is deleted.
    source.records = [rec("a.md", "one"), rec("b.md", "two, changed")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert (outcome.unchanged, outcome.updated) == (1, 1)
    source.records = [rec("b.md", "two, changed")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.deleted == 1
    assert [d[0] for d in library.docs.values()] == ["b.md"]
    status = await state.get(status_key("docs"))
    assert status
    assert status["documents"] == 1
    assert status["last_error"] == ""


async def test_sync_is_idempotent_and_skips_touched_files(source: ListSource, runner_parts: Parts):
    runner, library, _ = runner_parts
    source.records = [rec("a.md", "one", version="v1")]
    await runner.sync(spec())
    # A new version with the same content updates nothing.
    source.records = [rec("a.md", "one", version="v2")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.unchanged == 1
    assert library.calls == ["create a.md"]


async def test_records_the_last_success_so_the_next_run_asks_for_changes(
    source: ListSource, runner_parts: Parts
):
    runner, _, state = runner_parts
    source.complete = False
    source.records = [rec("a.md")]
    await runner.sync(spec())
    first = await state.get(status_key("docs"))
    assert first
    started = datetime.fromisoformat(first["last_success_start"])
    await runner.sync(spec())
    assert source.since[0] is None
    assert source.since[1] == started


async def test_deleted_records_remove_documents_of_incremental_sources(
    source: ListSource, runner_parts: Parts
):
    runner, library, _ = runner_parts
    source.complete = False
    source.records = [rec("a.md")]
    await runner.sync(spec())
    source.records = [Record(external_id="a.md", deleted=True), Record("never.md", deleted=True)]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.deleted == 1
    assert library.docs == {}


async def test_a_failing_item_fails_the_run_but_not_the_others(
    source: ListSource, runner_parts: Parts
):
    runner, library, state = runner_parts
    library.fail = {"b.md"}
    source.records = [rec("a.md"), rec("b.md"), rec("c.md")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert (outcome.created, outcome.failed) == (2, 1)
    status = await state.get(status_key("docs"))
    assert status
    assert "b.md: storage is down" in status["last_error"]
    assert "last_success" not in status
    # The next run retries what failed; the items that worked are not uploaded again.
    library.fail = set()
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert (outcome.created, outcome.unchanged) == (1, 2)


async def test_removed_while_failing_is_deleted_once_the_run_succeeds(
    source: ListSource, runner_parts: Parts
):
    runner, library, _ = runner_parts
    source.records = [rec("a.md"), rec("b.md")]
    await runner.sync(spec())
    # b.md is gone from the source, but c.md fails, so nothing is deleted yet.
    library.fail = {"c.md"}
    source.records = [rec("a.md"), rec("c.md")]
    await runner.sync(spec())
    assert "delete doc2" not in library.calls
    library.fail = set()
    await runner.sync(spec())
    assert sorted(d[0] for d in library.docs.values()) == ["a.md", "c.md"]


async def test_a_document_deleted_by_hand_is_added_again(source: ListSource, runner_parts: Parts):
    runner, library, _ = runner_parts
    source.records = [rec("a.md", "one")]
    await runner.sync(spec())
    library.gone = {"doc1"}
    source.records = [rec("a.md", "one, changed")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.created == 1
    assert outcome.updated == 0


async def test_empty_items_are_skipped(source: ListSource, runner_parts: Parts):
    runner, library, _ = runner_parts
    source.records = [Record(external_id="a.md", filename="a.md", data=b"")]
    outcome = await runner.sync(spec())
    assert outcome is not None
    assert outcome.failed == 0
    assert library.docs == {}


async def test_an_owner_who_is_not_a_platform_admin_is_reported(
    source: ListSource, runner_parts: Parts
):
    runner, library, state = runner_parts
    library.admin = False
    source.records = [rec("a.md")]
    assert await runner.sync(spec()) is None
    status = await state.get(status_key("docs"))
    assert status
    assert "not a platform admin" in status["last_error"]
    assert library.docs == {}


async def test_settings_that_stop_working_are_reported(
    monkeypatch: pytest.MonkeyPatch, runner_parts: Parts
):
    runner, _, state = runner_parts

    class Config(BaseModel):
        path: str

    def create(_config: Config):
        raise ValueError("/gone is not a directory")

    monkeypatch.setitem(KINDS, "folder", Kind(Config, create))
    assert await runner.sync(spec(settings={"path": "/gone"})) is None
    status = await state.get(status_key("docs"))
    assert status
    assert "is not a directory" in status["last_error"]


async def test_an_unexpected_failure_is_reported(source: ListSource, runner_parts: Parts):
    runner, library, state = runner_parts

    async def boom(owner: str) -> None:
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE, grpc.aio.Metadata(), grpc.aio.Metadata(), "iam is down"
        )

    library.ensure_admin = boom
    assert await runner.sync(spec()) is None
    status = await state.get(status_key("docs"))
    assert status
    assert "UNAVAILABLE: iam is down" in status["last_error"]


async def test_only_one_worker_syncs_a_connector_at_a_time(source: ListSource, runner_parts: Parts):
    runner, library, state = runner_parts
    assert await state.acquire("docs.lease", "other", 600)
    assert await runner.sync(spec()) is None
    assert library.calls == []
    await state.release("docs.lease", "other")
    assert await runner.sync(spec()) is not None
    assert await state.get("docs.lease") is None


async def test_report_records_why_a_connector_did_not_start(runner_parts: Parts):
    runner, _, state = runner_parts
    await runner.report("broken", "owner: field required")
    status = await state.get(status_key("broken"))
    assert status
    assert status["last_error"] == "owner: field required"


async def test_schedule_runs_enabled_connectors_until_stopped(
    source: ListSource, runner_parts: Parts
):
    runner, library, _ = runner_parts
    source.records = [rec("a.md")]
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_schedule(runner, [spec(), spec(name="off", enabled=False)], stop)
    )
    for _ in range(50):
        if library.calls:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 1)
    assert library.calls == ["create a.md"]


def test_leases_expire():
    now = [100.0]
    state = MemoryState(clock=lambda: now[0])

    async def go() -> None:
        assert await state.acquire("k", "a", 10)
        assert not await state.acquire("k", "b", 10)
        now[0] = 111
        assert await state.acquire("k", "b", 10)

    asyncio.run(go())


def test_item_keys_are_safe_for_any_external_id():
    key = item_key("docs", "dir/Ünï code & spaces.md")
    assert key.startswith("docs.item.")
    assert key.replace(".", "").replace("-", "").isalnum()
    assert key != item_key("docs", "other")


# --- settings ---------------------------------------------------------------


def test_spec_needs_a_choice_of_who_can_read():
    with pytest.raises(ValueError, match="choose who can read"):
        spec(team_ids=[])
    with pytest.raises(ValueError, match="not both"):
        spec(public=True)
    assert spec(team_ids=[], public=True).public


def test_parse_reports_every_bad_connector_and_keeps_the_good_ones(tmp_path: pathlib.Path):
    loaded = parse_specs(
        [
            {
                "name": "ok",
                "kind": "folder",
                "owner": "a",
                "public": True,
                "settings": {"path": str(tmp_path)},
            },
            {
                "name": "ok",
                "kind": "folder",
                "owner": "a",
                "public": True,
                "settings": {"path": str(tmp_path)},
            },
            {
                "name": "nowhere",
                "kind": "folder",
                "owner": "a",
                "public": True,
                "settings": {"path": str(tmp_path / "missing")},
            },
            {"name": "weird", "kind": "ftp", "owner": "a", "public": True},
            {"name": "Bad Name", "kind": "folder", "owner": "a", "public": True},
            {"kind": "folder"},
            "nonsense",
        ]
    )
    assert [s.name for s in loaded.specs] == ["ok"]
    assert "used twice" in loaded.errors["ok (entry 2)"]
    assert "mount it first" in loaded.errors["nowhere"]
    assert "unknown kind 'ftp'" in loaded.errors["weird"]
    assert "name" in loaded.errors["Bad Name"]
    assert "owner" in loaded.errors["#6"]
    assert "#7" in loaded.errors


def test_load_specs_reads_a_yaml_file(tmp_path: pathlib.Path):
    f = tmp_path / "connectors.yaml"
    f.write_text(
        f"connectors:\n  - {{name: notes, kind: folder, owner: u1, public: true,"
        f" settings: {{path: {tmp_path}}}}}\n"
    )
    assert [s.name for s in load_specs(str(f)).specs] == ["notes"]
    f.write_text("")
    assert load_specs(str(f)).specs == []
    f.write_text("connectors: {a: 1}")
    with pytest.raises(ValueError, match="`connectors:` list"):
        load_specs(str(f))
    f.write_text("a: [")
    with pytest.raises(ValueError, match="cannot read"):
        load_specs(str(f))
    with pytest.raises(ValueError, match="cannot read"):
        load_specs(str(tmp_path / "nope.yaml"))


def test_metadata_names_the_connector_and_origin():
    s = spec()
    record = Record(external_id="x/y.md", source_url="file:///x/y.md", metadata={"path": "x/y.md"})
    assert metadata_of(s, record) == {
        "path": "x/y.md",
        "connector": "docs",
        "connector_external_id": "x/y.md",
        "source_url": "file:///x/y.md",
    }


# --- the watched folder -----------------------------------------------------


async def listing(path: pathlib.Path, **config: Any) -> dict[str, Record]:
    source = FolderConnector(FolderConfig(path=str(path), **config))
    return {r.external_id: r async for r in source.list_changes(None)}


async def test_folder_lists_supported_files_with_stable_ids(tmp_path: pathlib.Path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")
    (tmp_path / "image.png").write_bytes(b"x")
    (tmp_path / ".hidden.md").write_text("h")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "c.md").write_text("c")
    records = await listing(tmp_path)
    assert sorted(records) == ["a.md", "sub/b.txt"]
    a = records["a.md"]
    assert (a.title, a.filename, a.media_type()) == ("a", "a.md", "text/markdown")
    assert a.source_url.startswith("file://")
    assert await a.read() == b"# A"
    assert records["sub/b.txt"].media_type() == "text/plain"
    assert sorted(await listing(tmp_path, recursive=False)) == ["a.md"]


async def test_folder_version_changes_with_the_file(tmp_path: pathlib.Path):
    f = tmp_path / "a.md"
    f.write_text("one")
    before = (await listing(tmp_path))["a.md"].version
    f.write_text("two!")
    os.utime(f, ns=(1, 1))
    assert (await listing(tmp_path))["a.md"].version != before


def test_folder_must_exist(tmp_path: pathlib.Path):
    with pytest.raises(ValueError, match="mount it first"):
        FolderConfig(path=str(tmp_path / "missing"))


async def test_folder_end_to_end_with_the_runtime(tmp_path: pathlib.Path):
    (tmp_path / "a.md").write_text("one")
    (tmp_path / "b.md").write_text("two")
    library, state = FakeLibrary(), MemoryState()
    runner = Runner(library, state, clock=Clock())
    s = spec(settings={"path": str(tmp_path)})
    await runner.sync(s)
    assert sorted(d[0] for d in library.docs.values()) == ["a.md", "b.md"]
    (tmp_path / "a.md").write_text("one, edited")
    (tmp_path / "b.md").unlink()
    (tmp_path / "c.md").write_text("three")
    await runner.sync(s)
    assert {d[0]: d[1] for d in library.docs.values()} == {
        "a.md": b"one, edited",
        "c.md": b"three",
    }


def test_settings_check_the_connectors_file(tmp_path: pathlib.Path):
    def problems(**values: Any) -> list[str]:
        found = Problems()
        Settings(**values).check(found)
        return found.items

    assert problems() == []
    assert problems(connectors_file=str(tmp_path / "missing.yaml"))[0].startswith(
        "KNOWCEL_CONNECTORS_FILE: cannot read connectors file"
    )
    f = tmp_path / "c.yaml"
    f.write_text("connectors: []")
    assert problems(connectors_file=str(f)) == []
    assert problems(connectors_file=str(f), connectors_upload_endpoint="nope") == [
        "KNOWCEL_CONNECTORS_UPLOAD_ENDPOINT: must be host:port, got 'nope'"
    ]


# --- the key-value state ----------------------------------------------------

_KEY = re.compile(r"^[-/_=.a-zA-Z0-9]+$")


class _Entry:
    def __init__(self, key: str, value: bytes, revision: int) -> None:
        self.key, self.value, self.revision = key, value, revision


class _Watcher:
    def __init__(self, entries: list[_Entry]) -> None:
        self._items: list[_Entry | None] = [*entries, None]
        self.stopped = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> _Entry | None:
        return self._items.pop(0)

    async def stop(self) -> None:
        self.stopped = True


class FakeKv:
    """The parts of a NATS key-value bucket the state uses, with its key rules
    and failures on demand (`broken` names operations that raise)."""

    def __init__(self) -> None:
        self.data: dict[str, _Entry] = {}
        self.broken: set[str] = set()
        self._rev = 0

    def _check(self, op: str, key: str = "a") -> None:
        if op in self.broken:
            raise ConnectionError(f"{op}: nats is unreachable")
        if not _KEY.match(key):
            raise InvalidKeyError(key)

    async def get(self, key: str) -> _Entry:
        self._check("get", key)
        if key not in self.data:
            raise KeyNotFoundError
        return self.data[key]

    async def put(self, key: str, value: bytes) -> int:
        self._check("put", key)
        return self._store(key, value)

    def _store(self, key: str, value: bytes) -> int:
        self._rev += 1
        self.data[key] = _Entry(key, value, self._rev)
        return self._rev

    async def create(self, key: str, value: bytes) -> int:
        self._check("create", key)
        if key in self.data:
            raise KeyWrongLastSequenceError
        return self._store(key, value)

    async def update(self, key: str, value: bytes, last: int) -> int:
        self._check("update", key)
        if self.data[key].revision != last:
            raise KeyWrongLastSequenceError
        return self._store(key, value)

    async def delete(self, key: str) -> bool:
        self._check("delete", key)
        self.data.pop(key, None)
        return True

    async def watch(self, subject: str, **_: Any) -> _Watcher:
        self._check("watch")
        assert subject.endswith(">")
        return _Watcher([e for k, e in self.data.items() if k.startswith(subject[:-1])])


async def test_invalid_entries_are_reported_under_keys_the_bucket_accepts(
    source: ListSource,
):
    kv = FakeKv()
    runner = Runner(FakeLibrary(), KvState(kv), clock=Clock())
    loaded = parse_specs(
        [
            {"name": "Bad Name", "kind": "folder", "owner": "a", "public": True},
            {"name": "x/y z!", "kind": "folder"},
            {"kind": "folder"},
            "nonsense",
            {"name": "ok", "kind": "folder", "owner": "a", "public": True, "settings": {}},
            {"name": "ok", "kind": "folder", "owner": "a", "public": True, "settings": {}},
        ]
    )
    assert [s.name for s in loaded.specs] == ["ok"]
    for name, error in loaded.errors.items():
        await runner.report(name, error)  # raises InvalidKeyError on a bad key
    assert len(kv.data) == len(loaded.errors) == 5
    assert all(_KEY.match(k) for k in kv.data)
    # A valid connector is not affected by invalid ones.
    assert await runner.sync(spec()) is not None


def test_a_later_valid_entry_is_not_rejected_for_the_name_of_an_invalid_one(
    tmp_path: pathlib.Path,
):
    good = {"kind": "folder", "owner": "a", "public": True, "settings": {"path": str(tmp_path)}}
    loaded = parse_specs(
        [{"name": "dup", "kind": "ftp", "owner": "a", "public": True}, {"name": "dup", **good}]
    )
    assert [s.name for s in loaded.specs] == ["dup"]
    assert "unknown kind" in loaded.errors["dup (entry 1)"]
    assert "dup" not in loaded.errors


async def test_a_state_failure_does_not_end_the_schedule_and_the_lease_is_released(
    source: ListSource,
):
    kv = FakeKv()
    runner = Runner(FakeLibrary(), KvState(kv), clock=Clock(), holder="w1")
    source.records = [rec("a.md")]
    kv.broken = {"put"}
    assert await runner.sync(spec()) is not None  # does not raise
    kv.broken = set()
    assert "docs.lease" not in kv.data  # the failed status write did not skip the release
    kv.broken = {"get"}
    assert await runner.sync(spec()) is None  # does not raise
    kv.broken = {"create"}
    assert await runner.sync(spec()) is None  # cannot take the lease
    kv.broken = set()
    assert await runner.sync(spec()) is not None


async def test_the_schedule_survives_a_failing_sync(source: ListSource):
    class Boom(Runner):
        calls = 0

        async def sync(self, spec: ConnectorSpec) -> None:
            Boom.calls += 1
            raise RuntimeError("nats is unreachable")

    stop = asyncio.Event()
    s = spec(interval_seconds=10)
    task = asyncio.create_task(run_schedule(Boom(FakeLibrary(), MemoryState()), [s], stop))
    await asyncio.sleep(0.05)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, 1)
    assert Boom.calls == 1


async def test_the_lease_is_renewed_while_a_long_sync_runs(
    source: ListSource, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(runner_module, "LEASE_SECONDS", 6)

    class Counting(KvState):
        acquires = 0

        async def acquire(self, key: str, holder: str, ttl: float) -> bool:
            self.acquires += 1
            return await super().acquire(key, holder, ttl)

    state = Counting(FakeKv(), clock=lambda: 0)
    runner = Runner(FakeLibrary(), state, clock=Clock(), holder="w1")
    source.records = [rec(f"{i}.md") for i in range(10)]
    assert await runner.sync(spec()) is not None
    assert state.acquires > 1


async def test_an_item_that_became_empty_is_remembered_and_reported(
    source: ListSource, runner_parts: Parts
):
    runner, library, state = runner_parts
    source.records = [rec("a.md", "content", version="1")]
    await runner.sync(spec())
    source.records = [Record(external_id="a.md", filename="a.md", data=b"", version="2")]
    outcome = await runner.sync(spec())
    assert outcome
    assert outcome.skipped == 1
    assert outcome.failed == 0
    status = await state.get(status_key("docs"))
    assert status
    assert "1 items skipped" in status["last_error"]
    assert "a.md is empty" in status["last_error"]
    assert [d[1] for d in library.docs.values()] == [b"content"]  # unchanged, but reported
    # The version is known, so the next sync does not read it again, and still reports it.
    reads = 0

    async def load() -> bytes:
        nonlocal reads
        reads += 1
        return b""

    source.records = [Record(external_id="a.md", filename="a.md", load=load, version="2")]
    outcome = await runner.sync(spec())
    assert reads == 0
    assert outcome
    assert outcome.skipped == 1
    # Filled again: updated.
    source.records = [rec("a.md", "new", version="3")]
    await runner.sync(spec())
    assert [d[1] for d in library.docs.values()] == [b"new"]
    status = await state.get(status_key("docs"))
    assert status
    assert status["last_error"] == ""


async def test_a_new_empty_item_can_be_filled_later_and_removed(
    source: ListSource, runner_parts: Parts
):
    runner, library, _ = runner_parts
    source.records = [Record(external_id="a.md", filename="a.md", data=b"", version="1")]
    await runner.sync(spec())
    source.records = [rec("a.md", "x", version="2")]
    await runner.sync(spec())
    assert library.calls == ["create a.md"]
    source.records = [Record(external_id="b.md", filename="b.md", data=b"", version="1")]
    await runner.sync(spec())
    source.records = [rec("a.md", "x", version="2")]
    await runner.sync(spec())  # b.md left without ever having a document: no failure
    assert len(library.docs) == 1


async def test_a_source_that_lists_nothing_does_not_delete_every_document(
    source: ListSource, runner_parts: Parts
):
    runner, library, state = runner_parts
    source.records = [rec("a.md"), rec("b.md", "two")]
    await runner.sync(spec())
    source.records = []
    assert await runner.sync(spec()) is None
    assert len(library.docs) == 2
    status = await state.get(status_key("docs"))
    assert status
    assert "not deleting" in status["last_error"]


async def test_the_sweep_lists_items_in_one_read(source: ListSource):
    kv = FakeKv()
    runner = Runner(FakeLibrary(), KvState(kv), clock=Clock())
    source.records = [rec("a.md"), rec("b.md", "two")]
    await runner.sync(spec())
    source.records = [rec("a.md")]
    outcome = await runner.sync(spec())
    assert outcome
    assert outcome.deleted == 1
    assert len([k for k in kv.data if ".item." in k]) == 1


async def test_the_folder_is_an_error_when_it_cannot_be_read(tmp_path: pathlib.Path):
    folder = tmp_path / "mount"
    folder.mkdir()
    (folder / "a.md").write_text("one")
    library, state = FakeLibrary(), MemoryState()
    runner = Runner(library, state, clock=Clock())
    s = spec(settings={"path": str(folder)})
    await runner.sync(s)
    (folder / "a.md").unlink()
    folder.rmdir()  # unmounted
    folder.mkdir()
    # An empty folder where documents exist is not trusted ...
    assert await runner.sync(s) is None
    assert len(library.docs) == 1
    folder.rmdir()  # ... and a missing one is an error of its own.
    assert await runner.sync(s) is None
    status = await state.get(status_key("docs"))
    assert status
    assert status["last_error"]
    assert len(library.docs) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
async def test_unreadable_paths_fail_the_run_instead_of_shrinking_the_listing(
    tmp_path: pathlib.Path,
):
    (tmp_path / "a.md").write_text("one")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "b.md").write_text("two")
    library, state = FakeLibrary(), MemoryState()
    runner = Runner(library, state, clock=Clock())
    s = spec(settings={"path": str(tmp_path)})
    await runner.sync(s)
    assert len(library.docs) == 2
    locked.chmod(0)
    try:
        assert await runner.sync(s) is None
        assert len(library.docs) == 2  # b.md was not deleted
        status = await state.get(status_key("docs"))
        assert status
        assert "cannot be read" in status["last_error"]
    finally:
        locked.chmod(0o755)


async def test_folder_skips_links_that_leave_the_folder(tmp_path: pathlib.Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.md").write_text("a")
    (tmp_path / "secret.md").write_text("secret")
    (root / "escape.md").symlink_to(tmp_path / "secret.md")
    (root / "inside.md").symlink_to(root / "a.md")
    (root / "gone.md").symlink_to(tmp_path / "nowhere.md")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "c.md").write_text("c")
    (root / "dir").symlink_to(outside, target_is_directory=True)
    assert sorted(await listing(root)) == ["a.md", "inside.md"]
