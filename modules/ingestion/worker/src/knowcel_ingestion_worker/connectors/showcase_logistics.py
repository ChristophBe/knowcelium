"""The showcase logistics connector: suppliers and stock of the mock ERP system
(`examples/showcase`) become documents, and shipments are found by live search, because their
status changes faster than a sync would keep up with."""

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import httpx

from .model import Record, Snippet
from .sdk import Connector
from .showcase_http import ShowcaseClient, ShowcaseConfig, text

_STOP_WORDS = frozenset(
    {
        *("a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from"),
        *("has", "have", "how", "in", "is", "it", "its", "me", "of", "on", "or", "the", "there"),
        *("to", "was", "we", "what", "when", "where", "which", "who", "why", "with"),
        *("shipment", "shipments", "status"),
    }
)
_SUPPLIER_ID = re.compile(r"sup-\d+")
# Words of a question that are tried; more would only slow the search down.
_MAX_TERMS = 6


class ShowcaseLogisticsConfig(ShowcaseConfig):
    pass


def _supplier(item: dict[str, Any]) -> str:
    return (
        f"# Supplier {item['id']}: {item['name']}\n\n- Country: {item['country']}\n"
        f"- Contact: {item['contact_email']}\n- Rating: {item['rating']}\n\n{item['notes']}\n"
    )


def _stock(item: dict[str, Any]) -> str:
    return (
        f"# Stock {item['id']}: {item['part_name']}\n\nPart {item['part_id']} from supplier "
        f"{item['supplier_id']}, held in {item['warehouse']}.\n\n"
        f"- On hand: {item['on_hand']}\n- Reserved: {item['reserved']}\n"
        f"- Reorder level: {item['reorder_level']}\n"
    )


def _metadata(item: dict[str, Any]) -> dict[str, str]:
    meta = {"system": "logistics", "id": item["id"], "updated_at": item["updated_at"]}
    for key in ("supplier_id", "part_id", "warehouse", "country", "rating"):
        if item.get(key) not in (None, ""):
            meta[key] = text(item[key])
    if "name" in item:  # a supplier is its own supplier
        meta["supplier_id"] = item["id"]
    return meta


# kind, endpoint, title, document body
_KINDS: tuple[
    tuple[str, str, Callable[[dict[str, Any]], str], Callable[[dict[str, Any]], str]], ...
] = (
    ("supplier", "/suppliers", lambda i: f"Supplier {i['id']}: {i['name']}", _supplier),
    ("stock", "/stock", lambda i: f"Stock {i['id']}: {i['part_name']}", _stock),
)


def _shipment(item: dict[str, Any]) -> str:
    line = f"Shipment {item['id']} from {item['supplier_id']}: {item['description']}. "
    line += f"Status: {item['status']}, expected {item['expected_at']}"
    if item.get("delivered_at"):
        line += f", delivered {item['delivered_at']}"
    if item.get("delay_days"):
        reason = item.get("delay_reason") or "no reason given"
        line += f", delayed by {item['delay_days']} days ({reason})"
    return line + "."


def _terms(query: str) -> list[str]:
    words = (w for w in re.findall(r"[\w-]+", query.lower()) if len(w) > 1)
    unique = dict.fromkeys(w for w in words if w not in _STOP_WORDS)
    return list(unique)[:_MAX_TERMS]


class ShowcaseLogisticsConnector(Connector[ShowcaseLogisticsConfig]):
    config_model = ShowcaseLogisticsConfig
    complete = False

    def __init__(
        self,
        config: ShowcaseLogisticsConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config)
        self._client = ShowcaseClient(config, transport)

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        for kind, path, title, render in _KINDS:
            async for item in self._client.records(path, since):
                yield Record(
                    external_id=f"{kind}/{item['id']}",
                    filename=f"{item['id']}.md",
                    title=title(item),
                    data=render(item).encode(),
                    source_url=f"{self._client.base_url}{path}/{item['id']}",
                    metadata={**_metadata(item), "kind": kind},
                    version=item["updated_at"],
                )

    async def search(self, query: str, limit: int) -> list[Snippet]:
        """Shipments that match the words of `query`, the best match first. A question is
        no keyword list, so each word is tried on its own and shipments that match more of
        them rank higher."""
        terms = _terms(query)
        if limit < 1 or not terms:
            return []
        suppliers = [t.upper() for t in terms if _SUPPLIER_ID.fullmatch(t)]
        requests = [("/search", {"q": t, "type": "shipment", "limit": 100}) for t in terms]
        # The search covers description, status and delay reason, not who supplies a shipment.
        requests += [("/shipments", {"supplier_id": s, "limit": 100}) for s in suppliers]
        pages = await asyncio.gather(*(self._client.get(path, params) for path, params in requests))
        found: dict[str, tuple[int, dict[str, Any]]] = {}
        for body in pages:
            for hit in body["items"]:
                score, _ = found.get(hit["id"], (0, hit))
                found[hit["id"]] = (score + 1, hit)
        ranked = sorted(found.values(), key=lambda s: (-s[0], s[1]["id"]))
        return [
            Snippet(
                text=_shipment(hit),
                source_url=f"{self._client.base_url}/shipments/{hit['id']}",
                title=f"Shipment {hit['id']}",
                external_id=f"shipment/{hit['id']}",
            )
            for _, hit in ranked[:limit]
        ]
