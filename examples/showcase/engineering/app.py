"""Routes of the mock engineering system (read-only)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from shared.api import PAGING_PARAMS, Query, Record, Router, lookup, paginate

from . import data

PARTS = data.parts()
SPECIFICATIONS = data.specifications()
CHANGE_REQUESTS = data.change_requests()

router = Router()


def _where(records: Sequence[Record], query: Query, *fields: str) -> list[Record]:
    """Records equal to every query parameter named in `fields` (an exact-match filter)."""
    return [r for r in records if all(f not in query or r.get(f) == query[f] for f in fields)]


@router.get("/health")
def health(_query: Query, _match: re.Match[str]) -> Any:
    return {"status": "ok"}


@router.get("/parts", params=(*PAGING_PARAMS, "status", "supplier_id"))
def list_parts(query: Query, _match: re.Match[str]) -> Any:
    return paginate(_where(PARTS, query, "status", "supplier_id"), query)


@router.get("/parts/(?P<id>[^/]+)")
def get_part(_query: Query, match: re.Match[str]) -> Any:
    return lookup(PARTS, match["id"])


@router.get("/specifications", params=(*PAGING_PARAMS, "part_id"))
def list_specifications(query: Query, _match: re.Match[str]) -> Any:
    return paginate(_where(SPECIFICATIONS, query, "part_id"), query)


@router.get("/specifications/(?P<id>[^/]+)")
def get_specification(_query: Query, match: re.Match[str]) -> Any:
    return lookup(SPECIFICATIONS, match["id"])


@router.get("/change-requests", params=(*PAGING_PARAMS, "status", "supplier_id"))
def list_change_requests(query: Query, _match: re.Match[str]) -> Any:
    return paginate(_where(CHANGE_REQUESTS, query, "status", "supplier_id"), query)


@router.get("/change-requests/(?P<id>[^/]+)")
def get_change_request(_query: Query, match: re.Match[str]) -> Any:
    return lookup(CHANGE_REQUESTS, match["id"])
