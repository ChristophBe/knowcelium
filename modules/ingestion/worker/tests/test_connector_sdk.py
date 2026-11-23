import importlib.util
import pathlib
from collections.abc import AsyncIterator
from datetime import datetime
from types import ModuleType

import pytest
from knowcel_ingestion_worker.connectors import Connector, ConnectorError, Record, Snippet
from knowcel_ingestion_worker.connectors.folder import FolderConnector
from knowcel_ingestion_worker.connectors.registry import KINDS, Kind
from knowcel_ingestion_worker.connectors.testkit import MemoryLibrary, check_connector
from pydantic import BaseModel, ConfigDict


class NotesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: str = ""


class Notes:
    """The notes of the source system the connectors below read."""

    items: dict[str, str] = {}  # noqa: RUF012 (reset by the fixture)
    removed: list[str] = []  # noqa: RUF012


@pytest.fixture(autouse=True)
def notes() -> type[Notes]:
    Notes.items = {"a": "alpha", "b": "beta"}
    Notes.removed = []
    return Notes


class ListOnly(Connector[NotesConfig]):
    """Implements nothing but `list_changes`."""

    config_model = NotesConfig

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        for key, text in Notes.items.items():
            yield Record(external_id=key, filename=f"{key}.txt", data=text.encode(), version=text)


class Incremental(ListOnly):
    """Reports the removals its source knows of as deleted records."""

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        async for record in super().list_changes(since):
            yield record
        for key in Notes.removed:
            yield Record(external_id=key, deleted=True)


class Searching(ListOnly):
    async def search(self, query: str, limit: int) -> list[Snippet]:
        hits = [(k, t) for k, t in Notes.items.items() if query in t]
        return [Snippet(text=t, source_url=f"notes://{k}", external_id=k) for k, t in hits[:limit]]


def drop_a() -> None:
    del Notes.items["a"]
    Notes.removed.append("a")


async def test_a_connector_with_only_list_changes_syncs():
    first = await check_connector(ListOnly, {}, invalid=[{"nope": 1}])
    assert first.created == 2
    assert not ListOnly.searchable()
    assert await ListOnly(NotesConfig()).search("alpha", 5) == []


async def test_incremental_connectors_report_removals_as_deleted_records():
    await check_connector(Incremental, {}, remove=drop_a)


async def test_complete_connectors_have_removed_items_deleted():
    class Complete(ListOnly):
        complete = True

    await check_connector(Complete, {}, remove=drop_a)


async def test_search_is_optional_and_limited():
    assert Searching.searchable()
    found = await Searching(NotesConfig()).search("a", 1)
    assert [s.source_url for s in found] == ["notes://a"]


async def test_the_folder_connector_meets_the_contract(tmp_path: pathlib.Path):
    (tmp_path / "a.md").write_text("one")
    (tmp_path / "b.txt").write_text("two")
    await check_connector(
        FolderConnector,
        {"path": str(tmp_path)},
        invalid=[{}, {"path": str(tmp_path / "missing")}, {"path": str(tmp_path), "x": 1}],
        remove=(tmp_path / "a.md").unlink,
    )


async def test_the_kit_reports_a_connector_that_is_not_idempotent():
    class Churning(ListOnly):
        async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
            Notes.items["a"] += "!"  # changes on every listing
            async for record in super().list_changes(since):
                yield record

    with pytest.raises(AssertionError, match="not idempotent"):
        await check_connector(Churning, {})


async def test_the_kit_reports_settings_that_should_be_rejected():
    with pytest.raises(AssertionError, match="should be rejected"):
        await check_connector(ListOnly, {}, invalid=[{}])


async def test_the_kit_reports_a_removal_that_deletes_nothing():
    # Lists only what changed and never reports a removal.
    with pytest.raises(AssertionError, match="deleted 0 documents"):
        await check_connector(ListOnly, {}, remove=drop_a)


async def test_the_kit_reports_duplicate_ids_and_an_empty_source():
    class Twice(ListOnly):
        async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
            yield Record(external_id="x", data=b"1", version="1")
            yield Record(external_id="x", data=b"2", version="2")

    with pytest.raises(AssertionError, match="share an external id"):
        await check_connector(Twice, {})
    Notes.items = {}
    with pytest.raises(AssertionError, match="no document"):
        await check_connector(ListOnly, {})


async def test_the_kit_reports_a_sync_that_did_not_run():
    calls = []

    class Flaky(ListOnly):
        async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
            calls.append(since)
            if len(calls) > 1:  # the listing check passed; the sync does not
                raise ConnectorError("the server is down")
            async for record in super().list_changes(since):
                yield record

    with pytest.raises(AssertionError, match="did not run"):
        await check_connector(Flaky, {})


async def test_the_kit_leaves_the_registry_as_it_was():
    before = dict(KINDS)
    await check_connector(ListOnly, {})
    assert before == KINDS
    assert isinstance(KINDS["folder"], Kind)


async def test_the_memory_library_behaves_like_the_document_library():
    library = MemoryLibrary()
    assert await library.ensure_admin("x") is None
    with pytest.raises(Exception, match="gone"):
        await library.replace(None, "gone", Record(external_id="a"), b"")  # type: ignore[arg-type]


def scaffold() -> ModuleType:
    path = pathlib.Path(__file__).parent.parent / "scripts" / "new_connector.py"
    spec = importlib.util.spec_from_file_location("new_connector", path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_scaffold_writes_a_connector_its_test_and_the_registration(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    module = scaffold()
    connectors, tests = tmp_path / "connectors", tmp_path / "tests"
    connectors.mkdir()
    tests.mkdir()
    registry = connectors / "registry.py"
    registry.write_text(f"from .model import Source\n\nKINDS = {{\n{module.MARKER}}}\n")
    monkeypatch.setattr(module, "CONNECTORS", connectors)
    monkeypatch.setattr(module, "TESTS", tests)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    assert module.main(["my_wiki"]) == 0
    assert (
        "class MyWikiConnector(Connector[MyWikiConfig])" in (connectors / "my_wiki.py").read_text()
    )
    assert "check_connector(MyWikiConnector" in (tests / "test_connector_my_wiki.py").read_text()
    text = registry.read_text()
    assert "from .my_wiki import MyWikiConnector" in text
    assert '"my_wiki": Kind.of(MyWikiConnector),' in text
    assert module.main(["my_wiki"]) == 1  # exists
    assert module.main(["Bad-Name"]) == 2
    assert module.main([]) == 2
    registry.write_text("KINDS = {}\n")
    assert module.main(["other"]) == 1  # no marker
