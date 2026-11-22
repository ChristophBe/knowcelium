import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from typing import Any

import pytest
from engineering.app import PARTS
from logistics.app import SHIPMENTS, STOCK, SUPPLIERS, router
from shared import api


def get(target: str) -> tuple[int, Any]:
    return router.dispatch(target)


def test_seed_data_is_linked():
    supplier_ids = {s["id"] for s in SUPPLIERS}
    assert len({p["supplier_id"] for p in PARTS if p["supplier_id"]} & supplier_ids) >= 5
    assert {s["supplier_id"] for s in STOCK} <= supplier_ids
    assert {s["supplier_id"] for s in SHIPMENTS} <= supplier_ids
    stock_ids = {s["id"] for s in STOCK}
    assert all(set(s["stock_ids"]) <= stock_ids for s in SHIPMENTS)
    part_ids = {p["id"] for p in PARTS}
    assert {s["part_id"] for s in STOCK} <= part_ids


def test_at_least_two_shipments_are_delayed():
    _, page = get("/shipments?status=delayed")
    assert page["total"] >= 2
    assert all(s["delay_days"] > 0 and s["delay_reason"] for s in page["items"])


def test_lists_are_paginated():
    _, first = get("/suppliers?limit=3")
    assert len(first["items"]) == 3
    assert first["total"] == len(SUPPLIERS)
    assert first["next_offset"] == 3
    _, rest = get("/suppliers?limit=3&offset=6")
    assert len(rest["items"]) == len(SUPPLIERS) - 6
    assert rest["next_offset"] is None
    assert get("/stock?limit=5")[1]["next_offset"] == 5
    assert get("/shipments?limit=4&offset=4")[1]["offset"] == 4


def test_updated_since():
    _, page = get("/shipments?updated_since=2026-11-19T00:00:00Z")
    assert [s["id"] for s in page["items"]] == ["SHP-5002", "SHP-5005", "SHP-5003", "SHP-5008"]
    _, stock = get("/stock?updated_since=2026-11-19T06:00:00Z")
    assert {s["id"] for s in stock["items"]} == {"STK-4002", "STK-4003"}
    assert get("/suppliers?updated_since=2026-11-16T09:10:00Z")[1]["total"] == 1
    assert get("/stock?updated_since=bad")[0] == 400


def test_filters_and_lookup():
    assert get("/stock?supplier_id=SUP-1002")[1]["total"] == 3
    assert get("/stock?part_id=P-1006")[1]["total"] == 1
    assert get("/suppliers/SUP-1001")[1]["country"] == "DE"
    assert get("/shipments/SHP-5002")[1]["status"] == "delayed"
    assert get("/shipments/missing")[0] == 404


def test_search_finds_across_kinds():
    _, page = get("/search?q=cell")
    types = {(h["type"], h["id"]) for h in page["items"]}
    assert ("supplier", "SUP-1002") in types
    assert ("stock", "STK-4003") in types
    assert ("shipment", "SHP-5002") in types


def test_search_is_case_insensitive_and_matches_all_words():
    _, page = get("/search?q=CUSTOMS%20basel")
    assert [h["id"] for h in page["items"]] == ["SHP-5004"]
    assert get("/search?q=customs%20hamburg")[1]["total"] == 0


def test_search_type_filter_pagination_and_updated_since():
    _, page = get("/search?q=hamburg&type=stock&limit=2")
    assert len(page["items"]) == 2
    assert page["total"] > 2
    assert all(h["type"] == "stock" for h in page["items"])
    _, recent = get("/search?q=delayed&updated_since=2026-11-19T08:00:00Z")
    assert [h["id"] for h in recent["items"]] == ["SHP-5005"]


@pytest.mark.parametrize("target", ["/search", "/search?q=%20", "/search?q=x&type=bogus"])
def test_search_bad_requests(target: str):
    assert get(target)[0] == 400


def test_http_server_serves_json_and_is_read_only(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class Once(ThreadingHTTPServer):
        def serve_forever(self, poll_interval: float = 0.5) -> None:
            captured["server"] = self
            ready.set()
            super().serve_forever(poll_interval)

    ready = threading.Event()
    monkeypatch.setattr(api, "ThreadingHTTPServer", Once)
    monkeypatch.setenv("PORT", "0")
    thread = threading.Thread(
        target=api.serve, args=(router,), kwargs={"name": "t", "default_port": 0}
    )
    thread.start()
    assert ready.wait(5)
    server = captured["server"]
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/suppliers?limit=1")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "application/json"
        assert json.load(resp)["total"] == len(SUPPLIERS)
        conn.request("HEAD", "/health")
        head = conn.getresponse()
        assert head.status == 200
        assert head.read() == b""
        conn.request("POST", "/suppliers", body="{}")
        post = conn.getresponse()
        assert post.status == 405
        post.read()
        conn.close()
    finally:
        server.shutdown()
        thread.join(5)
