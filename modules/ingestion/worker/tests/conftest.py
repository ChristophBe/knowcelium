from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest


def _haystack(record: dict[str, Any]) -> str:
    fields = ("name", "country", "notes", "part_name", "description", "status", "delay_reason")
    return " ".join(str(record.get(f) or "") for f in fields).lower()


class FakeSystem:
    """A mock showcase system in memory: paginated list endpoints with `updated_since`,
    and `/search` over the records of `search_in` (every word of `q` must occur)."""

    def __init__(self, lists: dict[str, list[dict[str, Any]]]) -> None:
        self.lists = lists
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "broken"})
        query = dict(request.url.params)
        path = request.url.path
        if path == "/search":
            words = query["q"].lower().split()
            records = [
                r
                for r in self.lists.get(f"/{query.get('type', '')}s", [])
                if all(w in _haystack(r) for w in words)
            ]
        elif path in self.lists:
            records = self.lists[path]
        else:
            return httpx.Response(404, json={"error": "not found"})
        if "supplier_id" in query:
            records = [r for r in records if r.get("supplier_id") == query["supplier_id"]]
        if "updated_since" in query:
            since = datetime.fromisoformat(query["updated_since"])
            records = [r for r in records if datetime.fromisoformat(r["updated_at"]) >= since]
        limit, offset = int(query["limit"]), int(query.get("offset", 0))
        items = records[offset : offset + limit]
        end = offset + len(items)
        return httpx.Response(
            200,
            json={
                "items": items,
                "total": len(records),
                "limit": limit,
                "offset": offset,
                "next_offset": end if end < len(records) else None,
            },
        )


@pytest.fixture
def fake_system() -> Callable[[dict[str, list[dict[str, Any]]]], FakeSystem]:
    return FakeSystem
