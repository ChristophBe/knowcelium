from typing import Any

from engineering.app import CHANGE_REQUESTS, PARTS, router
from logistics.app import SUPPLIERS


def get(target: str) -> tuple[int, Any]:
    return router.dispatch(target)


def test_at_least_20_parts():
    assert len(PARTS) >= 20
    status, body = get("/parts?limit=100")
    assert status == 200
    assert body["total"] == len(PARTS) >= 20


def test_part_suppliers_exist_in_logistics():
    ids = {s["id"] for s in SUPPLIERS}
    linked = [p for p in PARTS if p["supplier_id"]]
    assert len(linked) >= 5
    assert all(p["supplier_id"] in ids for p in linked)
    assert all(c["supplier_id"] in ids for c in CHANGE_REQUESTS if c["supplier_id"])


def test_pagination_walks_all_parts_once():
    seen, offset = [], 0
    while offset is not None:
        _, page = get(f"/parts?limit=7&offset={offset}")
        assert page["limit"] == 7
        seen += [p["id"] for p in page["items"]]
        offset = page["next_offset"]
    assert sorted(seen) == sorted(p["id"] for p in PARTS)


def test_default_limit_and_last_page():
    _, page = get("/parts")
    assert len(page["items"]) == 20
    assert page["next_offset"] == 20
    _, last = get("/parts?offset=20")
    assert len(last["items"]) == len(PARTS) - 20
    assert last["next_offset"] is None


def test_oldest_change_first():
    _, page = get("/parts?limit=100")
    stamps = [p["updated_at"] for p in page["items"]]
    assert stamps == sorted(stamps)


def test_updated_since_filters_and_is_inclusive():
    _, page = get("/parts?updated_since=2026-11-09T09:35:00Z")
    assert [p["id"] for p in page["items"]] == ["P-1013", "P-1019", "P-1024"]
    assert page["total"] == 3


def test_updated_since_with_offset_and_no_zone():
    _, all_ = get("/parts?updated_since=2026-11-01T00:00:00")
    assert all(p["updated_at"] >= "2026-11-01" for p in all_["items"])
    assert all_["total"] == len(all_["items"])
    _, none = get("/parts?updated_since=2027-01-01T00:00:00%2B01:00")
    assert none["items"] == []
    assert none["total"] == 0


def test_invalid_parameters_are_400():
    for target in (
        "/parts?limit=0",
        "/parts?limit=101",
        "/parts?limit=x",
        "/parts?offset=-1",
        "/parts?updated_since=yesterday",
    ):
        status, body = get(target)
        assert status == 400, target
        assert "error" in body


def test_filters_and_lookup():
    _, page = get("/parts?supplier_id=SUP-1004")
    assert {p["id"] for p in page["items"]} == {"P-1006", "P-1024"}
    assert get("/parts/P-1001")[1]["name"] == "Hub motor 250 W"
    assert get("/parts/nope")[0] == 404
    assert get("/specifications?part_id=P-1002")[1]["total"] == 1
    assert get("/specifications/SPEC-2001")[0] == 200
    assert get("/change-requests?status=open")[1]["total"] == 2
    assert get("/change-requests/CR-3001")[0] == 200
    assert get("/elsewhere")[0] == 404
    assert get("/health/")[1] == {"status": "ok"}
