"""The showcase engineering connector: parts, specifications and change requests of the
mock PLM system (`examples/showcase`) become documents. Only records changed since the last
sync are read; the supplier IDs are kept in the metadata, which links them to logistics."""

from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import httpx

from .model import Record
from .sdk import Connector
from .showcase_http import ShowcaseClient, ShowcaseConfig, text


class ShowcaseEngineeringConfig(ShowcaseConfig):
    pass


def _part(item: dict[str, Any]) -> str:
    supplier = item.get("supplier_id") or "none (made in house)"
    return (
        f"# Part {item['id']}: {item['name']}\n\n{item['description']}\n\n"
        f"- Revision: {item['revision']}\n- Status: {item['status']}\n- Supplier: {supplier}\n"
    )


def _specification(item: dict[str, Any]) -> str:
    return (
        f"# Specification {item['id']}: {item['title']}\n\n"
        f"Part: {item['part_id']}\n\n{item['body']}\n"
    )


def _change_request(item: dict[str, Any]) -> str:
    parts = ", ".join(item.get("part_ids") or []) or "none"
    supplier = item.get("supplier_id") or "none"
    return (
        f"# Change request {item['id']}: {item['title']}\n\n{item['description']}\n\n"
        f"- Status: {item['status']}\n- Parts: {parts}\n- Supplier: {supplier}\n"
        f"- Requested by: {item.get('requested_by', '')}\n"
    )


def _metadata(item: dict[str, Any]) -> dict[str, str]:
    meta = {"system": "engineering", "id": item["id"], "updated_at": item["updated_at"]}
    if "revision" in item:  # a part is its own part
        meta["part_id"] = item["id"]
    for key in ("status", "supplier_id", "part_id", "revision", "requested_by"):
        if item.get(key):
            meta[key] = text(item[key])
    if item.get("part_ids"):
        meta["part_ids"] = ",".join(item["part_ids"])
    return meta


# kind, endpoint, title prefix, document body
_KINDS: tuple[tuple[str, str, str, Callable[[dict[str, Any]], str]], ...] = (
    ("part", "/parts", "Part", _part),
    ("specification", "/specifications", "Specification", _specification),
    ("change-request", "/change-requests", "Change request", _change_request),
)


class ShowcaseEngineeringConnector(Connector[ShowcaseEngineeringConfig]):
    config_model = ShowcaseEngineeringConfig
    # Lists only what changed since the last sync; the mock system never deletes.
    complete = False

    def __init__(
        self,
        config: ShowcaseEngineeringConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config)
        self._client = ShowcaseClient(config, transport)

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        for kind, path, label, render in _KINDS:
            async for item in self._client.records(path, since):
                yield Record(
                    external_id=f"{kind}/{item['id']}",
                    filename=f"{item['id']}.md",
                    title=f"{label} {item['id']}: {item.get('name') or item['title']}",
                    data=render(item).encode(),
                    source_url=f"{self._client.base_url}{path}/{item['id']}",
                    metadata={**_metadata(item), "kind": kind},
                    version=item["updated_at"],
                )
