import asyncio
import pathlib
from typing import Any

import pytest
from knowcel.ingestion.v1 import events_pb2
from knowcel_ingestion_worker.connectors import live
from knowcel_ingestion_worker.connectors.folder import FolderConfig, FolderConnector
from knowcel_ingestion_worker.connectors.live import LiveSearch
from knowcel_ingestion_worker.connectors.model import ConnectorError, Snippet
from knowcel_ingestion_worker.connectors.registry import KINDS, Kind
from knowcel_ingestion_worker.connectors.sdk import Connector
from knowcel_ingestion_worker.connectors.spec import ConnectorSpec, parse_specs
from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "ok"


class Stock(Connector[Config]):
    config_model = Config

    async def list_changes(self, since):  # type: ignore[no-untyped-def]
        return
        yield

    async def search(self, query: str, limit: int) -> list[Snippet]:
        if self.config.mode == "slow":
            await asyncio.sleep(10)
        if self.config.mode == "broken":
            raise RuntimeError("the warehouse is on fire")
        if self.config.mode == "denied":
            raise ConnectorError("the token is wrong")
        return [
            Snippet(text=f"{query} {i}", source_url=f"https://wms/{i}", title=f"item {i}")
            for i in range(5)
        ][:limit]


@pytest.fixture(autouse=True)
def kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(KINDS, "stock", Kind.of(Stock))


def spec(name: str = "stock", **overrides: Any) -> ConnectorSpec:
    values: dict[str, Any] = {
        "name": name,
        "kind": "stock",
        "owner": "admin",
        "public": True,
        "sync": False,
        "live_search": True,
    }
    return ConnectorSpec.model_validate(values | overrides)


async def admin(owner: str) -> None:
    return None


def request(**fields: Any) -> events_pb2.ConnectorSearchRequest:
    return events_pb2.ConnectorSearchRequest(query="boxes", limit=3, timeout_seconds=0.2, **fields)


async def test_returns_the_snippets_with_the_connector_name():
    reply = await LiveSearch([spec()], admin).search(request())
    assert [s.connector for s in reply.snippets] == ["stock"] * 3
    assert reply.snippets[0].text == "boxes 0"
    assert reply.snippets[0].source_url == "https://wms/0"
    assert reply.snippets[0].title == "item 0"
    assert not reply.unavailable_connectors


async def test_a_failing_or_slow_connector_is_named_and_the_others_answer():
    specs = [
        spec("good"),
        spec("slow", settings={"mode": "slow"}),
        spec("broken", settings={"mode": "broken"}),
        spec("denied", settings={"mode": "denied"}),
    ]
    reply = await LiveSearch(specs, admin).search(request())
    assert {s.connector for s in reply.snippets} == {"good"}
    assert sorted(reply.unavailable_connectors) == ["broken", "denied", "slow"]


async def test_connectors_are_interleaved_and_the_total_is_limited():
    reply = await LiveSearch([spec("a"), spec("b")], admin).search(request())
    assert [s.connector for s in reply.snippets] == ["a", "b", "a"]


async def test_only_connectors_the_caller_may_read_are_asked():
    specs = [
        spec("everyone"),
        spec("mine", public=False, team_ids=["t1"]),
        spec("theirs", public=False, team_ids=["t2"]),
    ]
    search = LiveSearch(specs, admin)
    reply = await search.search(request(member_team_ids=["t1"]))
    assert {s.connector for s in reply.snippets} == {"everyone", "mine"}
    nobody = await search.search(request())
    assert {s.connector for s in nobody.snippets} == {"everyone"}


async def test_a_team_scope_asks_only_connectors_of_those_teams():
    specs = [spec("everyone"), spec("mine", public=False, team_ids=["t1"])]
    search = LiveSearch(specs, admin)
    reply = await search.search(request(member_team_ids=["t1"], scope_team_ids=["t1"]))
    assert {s.connector for s in reply.snippets} == {"mine"}
    # A team the caller is not in grants nothing.
    reply = await search.search(request(scope_team_ids=["t1"]))
    assert not reply.snippets


async def test_connector_ids_narrow_the_search():
    reply = await LiveSearch([spec("a"), spec("b")], admin).search(request(connector_ids=["b"]))
    assert {s.connector for s in reply.snippets} == {"b"}


async def test_connectors_that_do_not_search_live_are_never_asked():
    off = spec("off", live_search=False, sync=True)
    assert not (await LiveSearch([off], admin).search(request())).snippets
    assert not (await LiveSearch([spec(enabled=False)], admin).search(request())).snippets


async def test_an_owner_who_is_not_a_platform_admin_is_not_searched():
    async def refuse(owner: str) -> None:
        raise ConnectorError(f"owner {owner} is not a platform admin")

    reply = await LiveSearch([spec()], refuse).search(request())
    assert not reply.snippets
    assert list(reply.unavailable_connectors) == ["stock"]


async def test_the_admin_check_is_remembered_for_a_while():
    checks: list[str] = []
    now = [0.0]

    async def count(owner: str) -> None:
        checks.append(owner)

    search = LiveSearch([spec()], count, clock=lambda: now[0])
    await search.search(request())
    await search.search(request())
    assert checks == ["admin"]
    now[0] = live.ADMIN_TTL + 1
    await search.search(request())
    assert checks == ["admin", "admin"]


async def test_settings_that_stop_working_make_the_connector_unavailable(tmp_path: pathlib.Path):
    folder = spec("docs", kind="folder", settings={"path": str(tmp_path / "missing")})
    reply = await LiveSearch([folder], admin).search(request())
    assert list(reply.unavailable_connectors) == ["docs"]


async def test_handle_round_trips_the_wire_format():
    raw = await LiveSearch([spec()], admin).handle(request())
    reply = events_pb2.ConnectorSearchReply.FromString(raw)
    assert len(reply.snippets) == 3


def test_live_search_needs_a_connector_that_implements_search(tmp_path: pathlib.Path):
    entry = {
        "name": "x",
        "kind": "folder",
        "owner": "a",
        "public": True,
        "live_search": True,
        "settings": {"path": str(tmp_path)},
    }
    assert not parse_specs([entry]).errors  # the folder connector searches

    class Plain(Stock):
        search = Connector.search

    KINDS["plain"] = Kind.of(Plain)
    try:
        loaded = parse_specs([{**entry, "name": "y", "kind": "plain", "settings": {}}])
    finally:
        del KINDS["plain"]
    assert "does not implement search" in loaded.errors["y"]


def test_a_connector_that_does_nothing_is_rejected():
    loaded = parse_specs(
        [{"name": "x", "kind": "stock", "owner": "a", "public": True, "sync": False}]
    )
    assert "neither syncs nor searches" in loaded.errors["x"]


async def test_the_folder_finds_paragraphs_with_the_words(tmp_path: pathlib.Path):
    (tmp_path / "stock.md").write_text("Boxes: 40 in aisle 3.\n\nBolts: 12 in aisle 4.\n")
    (tmp_path / "other.txt").write_text("Nothing relevant here.\n\nBoxes and bolts together.")
    (tmp_path / "scan.pdf").write_bytes(b"%PDF boxes")
    folder = FolderConnector(FolderConfig(path=str(tmp_path)))
    hits = await folder.search("boxes bolts", 5)
    assert hits[0].text == "Boxes and bolts together."
    assert {h.external_id for h in hits} == {"stock.md", "other.txt"}
    # Half of the words of 4 letters or more have to be there: many, boxes, bolts need two.
    assert [h.text for h in await folder.search("how many boxes and bolts", 5)] == [
        "Boxes and bolts together."
    ]
    assert hits[0].source_url.startswith("file://")
    assert len(await folder.search("boxes", 1)) == 1
    assert await folder.search("zz", 5) == []
    assert await folder.search("unrelated words", 5) == []
    assert await folder.search("location shelf boxes", 5) == []


async def test_a_vanished_folder_is_an_error_not_an_empty_result(tmp_path: pathlib.Path):
    folder = FolderConnector(FolderConfig(path=str(tmp_path)))
    await asyncio.to_thread(tmp_path.rmdir)
    with pytest.raises(ConnectorError, match="cannot read the folder"):
        await folder.search("anything", 5)
