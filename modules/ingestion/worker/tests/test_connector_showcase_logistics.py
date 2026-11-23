from collections.abc import Callable
from typing import Any

import pytest
from knowcel_ingestion_worker.connectors.registry import KINDS
from knowcel_ingestion_worker.connectors.showcase_logistics import (
    ShowcaseLogisticsConfig,
    ShowcaseLogisticsConnector,
)
from knowcel_ingestion_worker.connectors.testkit import check_connector

# The `fake_system` fixture of conftest.py: builds a FakeSystem from its list endpoints.
FakeSystems = Callable[[dict[str, list[dict[str, Any]]]], Any]

URL = "http://logistics.test"


def system(fake_system: FakeSystems):
    return fake_system(
        {
            "/suppliers": [
                {
                    "id": "SUP-1001",
                    "name": "Motorworks",
                    "country": "DE",
                    "contact_email": "a@example.com",
                    "rating": 4,
                    "notes": "Reliable",
                    "updated_at": "2026-09-01T08:00:00Z",
                }
            ],
            "/stock": [
                {
                    "id": "ST-1",
                    "supplier_id": "SUP-1001",
                    "part_id": "P-1",
                    "part_name": "Hub motor",
                    "on_hand": 10,
                    "reserved": 2,
                    "reorder_level": 5,
                    "warehouse": "Berlin",
                    "updated_at": "2026-09-02T08:00:00Z",
                }
            ],
            "/shipments": [
                {
                    "id": "SH-1",
                    "supplier_id": "SUP-1001",
                    "stock_ids": ["ST-1"],
                    "description": "Motors for May",
                    "status": "delayed",
                    "expected_at": "2026-11-01",
                    "delivered_at": None,
                    "delay_days": 6,
                    "delay_reason": "customs",
                    "updated_at": "2026-11-02T08:00:00Z",
                },
                {
                    "id": "SH-2",
                    "supplier_id": "SUP-1001",
                    "stock_ids": ["ST-1"],
                    "description": "Cells",
                    "status": "delivered",
                    "expected_at": "2026-10-01",
                    "delivered_at": "2026-10-02",
                    "delay_days": 0,
                    "delay_reason": None,
                    "updated_at": "2026-10-02T08:00:00Z",
                },
            ],
        }
    )


def connector(fake: Any):
    return ShowcaseLogisticsConnector(ShowcaseLogisticsConfig(base_url=URL), fake.transport)


async def test_syncs_suppliers_and_stock(fake_system: FakeSystems):
    fake = system(fake_system)
    found = {r.external_id: r async for r in connector(fake).list_changes(None)}
    assert set(found) == {"supplier/SUP-1001", "stock/ST-1"}
    assert found["supplier/SUP-1001"].metadata["supplier_id"] == "SUP-1001"
    assert found["stock/ST-1"].metadata["supplier_id"] == "SUP-1001"
    assert found["stock/ST-1"].metadata["part_id"] == "P-1"
    assert b"On hand: 10" in await found["stock/ST-1"].read()
    assert not any(r.url.path == "/shipments" for r in fake.requests)


async def test_search_finds_shipments_by_status(fake_system: FakeSystems):
    fake = system(fake_system)
    snippets = await connector(fake).search("Which shipments are delayed?", 5)
    assert [s.external_id for s in snippets] == ["shipment/SH-1"]
    assert snippets[0].source_url == f"{URL}/shipments/SH-1"
    assert "delayed by 6 days (customs)" in snippets[0].text
    assert {r.url.params["type"] for r in fake.requests} == {"shipment"}


async def test_search_ranks_shipments_matching_more_words_first(fake_system: FakeSystems):
    fake = system(fake_system)
    snippets = await connector(fake).search("cells delivered motors", 1)
    assert [s.external_id for s in snippets] == ["shipment/SH-2"]
    assert "delivered 2026-10-02" in snippets[0].text


async def test_search_without_usable_words_or_room_finds_nothing(fake_system: FakeSystems):
    fake = system(fake_system)
    assert await connector(fake).search("what is the status?", 5) == []
    assert await connector(fake).search("delayed", 0) == []
    assert fake.requests == []


def test_is_registered_and_searchable():
    assert KINDS["showcase_logistics"].config is ShowcaseLogisticsConfig
    assert ShowcaseLogisticsConnector.searchable()


async def test_meets_the_connector_contract(fake_system: FakeSystems):
    fake = system(fake_system)

    class Bound(ShowcaseLogisticsConnector):
        def __init__(self, config: Any) -> None:
            super().__init__(config, fake.transport)

    await check_connector(Bound, {"base_url": URL}, invalid=[{}, {"base_url": "nope"}])


def test_rejects_an_unknown_setting():
    with pytest.raises(ValueError, match="token"):
        ShowcaseLogisticsConfig.model_validate({"base_url": URL, "token": "x"})


async def test_search_finds_the_shipments_of_a_named_supplier(fake_system: FakeSystems):
    fake = system(fake_system)
    snippets = await connector(fake).search("Where is the delivery from sup-1001?", 5)
    assert {s.external_id for s in snippets} == {"shipment/SH-1", "shipment/SH-2"}
    assert any(
        r.url.path == "/shipments" and r.url.params["supplier_id"] == "SUP-1001"
        for r in fake.requests
    )
