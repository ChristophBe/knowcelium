import os
import pathlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import grpc
import pytest
from knowcel_ingestion_worker.config import Settings
from knowcel_ingestion_worker.connectors.folder import FolderConfig, FolderSource
from knowcel_ingestion_worker.connectors.library import DocumentGoneError, metadata_of
from knowcel_ingestion_worker.connectors.model import ConnectorError, Record
from knowcel_ingestion_worker.connectors.registry import KINDS, Kind
from knowcel_ingestion_worker.connectors.runner import Runner, run_schedule
from knowcel_ingestion_worker.connectors.spec import ConnectorSpec, load_specs, parse_specs
from knowcel_ingestion_worker.connectors.state import MemoryState, item_key, status_key
from knowcel_platform.config import Problems
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
    import asyncio

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

    import asyncio

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
    source = FolderSource(FolderConfig(path=str(path), **config))
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
