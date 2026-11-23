from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from knowcel_ingestion_worker.connectors.model import ConnectorError
from knowcel_ingestion_worker.connectors.registry import KINDS
from knowcel_ingestion_worker.connectors.showcase_engineering import (
    ShowcaseEngineeringConfig,
    ShowcaseEngineeringConnector,
)
from knowcel_ingestion_worker.connectors.testkit import check_connector

# The `fake_system` fixture of conftest.py: builds a FakeSystem from its list endpoints.
FakeSystems = Callable[[dict[str, list[dict[str, Any]]]], Any]

URL = "http://engineering.test"


def system(fake_system: FakeSystems):
    return fake_system(
        {
            "/parts": [
                {
                    "id": "P-1",
                    "name": "Hub motor",
                    "description": "250 W",
                    "revision": "C",
                    "status": "released",
                    "supplier_id": "SUP-1001",
                    "updated_at": "2026-09-01T08:00:00Z",
                },
                {
                    "id": "P-2",
                    "name": "Frame",
                    "description": "Aluminium",
                    "revision": "F",
                    "status": "released",
                    "supplier_id": None,
                    "updated_at": "2026-10-01T08:00:00Z",
                },
            ],
            "/specifications": [
                {
                    "id": "S-1",
                    "part_id": "P-1",
                    "title": "Motor spec",
                    "body": "45 Nm",
                    "updated_at": "2026-09-02T08:00:00Z",
                }
            ],
            "/change-requests": [
                {
                    "id": "CR-1",
                    "title": "Switch cells",
                    "description": "Cheaper cells",
                    "status": "open",
                    "part_ids": ["P-1", "P-2"],
                    "supplier_id": "SUP-1002",
                    "requested_by": "Ada",
                    "updated_at": "2026-10-05T08:00:00Z",
                }
            ],
        }
    )


def connector(fake: Any, page_size: int = 50):
    config = ShowcaseEngineeringConfig(base_url=URL, page_size=page_size)
    return ShowcaseEngineeringConnector(config, transport=fake.transport)


async def records(conn: Any, since: datetime | None = None):
    return [r async for r in conn.list_changes(since)]


async def test_syncs_parts_specifications_and_change_requests(fake_system: FakeSystems):
    fake = system(fake_system)
    found = {r.external_id: r for r in await records(connector(fake, page_size=1))}
    assert set(found) == {"part/P-1", "part/P-2", "specification/S-1", "change-request/CR-1"}
    part = found["part/P-1"]
    assert part.title == "Part P-1: Hub motor"
    assert part.metadata["supplier_id"] == "SUP-1001"
    assert part.version == "2026-09-01T08:00:00Z"
    assert part.source_url == f"{URL}/parts/P-1"
    assert b"Supplier: SUP-1001" in await part.read()
    assert "supplier_id" not in found["part/P-2"].metadata
    request = found["change-request/CR-1"]
    assert request.metadata["supplier_id"] == "SUP-1002"
    assert request.metadata["part_ids"] == "P-1,P-2"
    assert found["specification/S-1"].metadata["part_id"] == "P-1"


async def test_asks_only_for_what_changed_since_the_last_sync(fake_system: FakeSystems):
    fake = system(fake_system)
    since = datetime(2026, 9, 15, tzinfo=UTC)
    found = {r.external_id for r in await records(connector(fake), since)}
    assert found == {"part/P-2", "change-request/CR-1"}
    assert all(r.url.params["updated_since"].startswith("2026-09-15") for r in fake.requests)


async def test_follows_the_pages(fake_system: FakeSystems):
    fake = system(fake_system)
    await records(connector(fake, page_size=1))
    offsets = [r.url.params["offset"] for r in fake.requests if r.url.path == "/parts"]
    assert offsets == ["0", "1"]


async def test_an_unreachable_system_fails_the_run(fake_system: FakeSystems):
    fake = system(fake_system)
    fake.status = 500
    with pytest.raises(ConnectorError, match="answered 500"):
        await records(connector(fake))


async def test_a_page_without_progress_is_an_error(fake_system: FakeSystems):
    fake = system(fake_system)
    fake.lists["/parts"] = []
    original = fake._handle

    def stuck(request: httpx.Request) -> httpx.Response:
        response = original(request)
        if request.url.path == "/parts":
            return httpx.Response(200, json={"items": [], "next_offset": 5})
        return response

    fake.transport = type(fake.transport)(stuck)
    with pytest.raises(ConnectorError, match="without making progress"):
        await records(connector(fake))


def test_settings_are_validated():
    with pytest.raises(ValueError, match="http"):
        ShowcaseEngineeringConfig(base_url="engineering:8091")
    with pytest.raises(ValueError, match="page_size"):
        ShowcaseEngineeringConfig(base_url=URL, page_size=500)
    assert ShowcaseEngineeringConfig(base_url=URL + "/").base_url == URL


async def test_meets_the_connector_contract(fake_system: FakeSystems):
    fake = system(fake_system)

    class Bound(ShowcaseEngineeringConnector):
        def __init__(self, config: Any) -> None:
            super().__init__(config, transport=fake.transport)

    await check_connector(Bound, {"base_url": URL}, invalid=[{}, {"base_url": "nope"}, {"x": 1}])


def test_is_registered_and_not_searchable():
    assert KINDS["showcase_engineering"].config is ShowcaseEngineeringConfig
    assert not ShowcaseEngineeringConnector.searchable()
