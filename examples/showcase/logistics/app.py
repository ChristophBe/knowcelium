"""Routes of the mock logistics system (read-only)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from shared.api import PAGING_PARAMS, ApiError, Query, Record, Router, lookup, paginate, search

from . import data

SUPPLIERS = data.suppliers()
STOCK = data.stock()
SHIPMENTS = data.shipments()

# What `GET /search` looks through: record type -> (records, searched fields).
SEARCHABLE: dict[str, tuple[Sequence[Record], tuple[str, ...]]] = {
    "supplier": (SUPPLIERS, ("name", "country", "notes")),
    "stock": (STOCK, ("part_name", "part_id", "warehouse")),
    "shipment": (SHIPMENTS, ("description", "status", "delay_reason")),
}

router = Router()


def _where(records: Sequence[Record], query: Query, *fields: str) -> list[Record]:
    """Records equal to every query parameter named in `fields` (an exact-match filter)."""
    return [r for r in records if all(f not in query or r.get(f) == query[f] for f in fields)]


@router.get("/health")
def health(_query: Query, _match: re.Match[str]) -> Any:
    return {"status": "ok"}


@router.get("/suppliers", params=PAGING_PARAMS)
def list_suppliers(query: Query, _match: re.Match[str]) -> Any:
    return paginate(SUPPLIERS, query)


@router.get("/suppliers/(?P<id>[^/]+)")
def get_supplier(_query: Query, match: re.Match[str]) -> Any:
    return lookup(SUPPLIERS, match["id"])


@router.get("/stock", params=(*PAGING_PARAMS, "supplier_id", "part_id"))
def list_stock(query: Query, _match: re.Match[str]) -> Any:
    return paginate(_where(STOCK, query, "supplier_id", "part_id"), query)


@router.get("/shipments", params=(*PAGING_PARAMS, "supplier_id", "status"))
def list_shipments(query: Query, _match: re.Match[str]) -> Any:
    return paginate(_where(SHIPMENTS, query, "supplier_id", "status"), query)


@router.get("/stock/(?P<id>[^/]+)")
def get_stock(_query: Query, match: re.Match[str]) -> Any:
    return lookup(STOCK, match["id"])


@router.get("/shipments/(?P<id>[^/]+)")
def get_shipment(_query: Query, match: re.Match[str]) -> Any:
    return lookup(SHIPMENTS, match["id"])


@router.get("/search", params=(*PAGING_PARAMS, "q", "type"))
def search_all(query: Query, _match: re.Match[str]) -> Any:
    """Full-text search over suppliers, stock and shipments; each hit carries its `type`.

    Parameters: `q` (required), `type` (supplier, stock or shipment; default all), `limit`,
    `offset` and `updated_since` as on the list endpoints.
    """
    kinds = [query["type"]] if "type" in query else list(SEARCHABLE)
    if any(k not in SEARCHABLE for k in kinds):
        raise ApiError(400, f"type must be one of {', '.join(SEARCHABLE)}")
    hits = [
        {**record, "type": kind}
        for kind in kinds
        for record in search(*SEARCHABLE[kind], query.get("q", ""))
    ]
    return paginate(hits, query)
