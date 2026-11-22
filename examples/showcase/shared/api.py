"""Pagination, the `updated_since` filter and a minimal HTTP server for read-only JSON APIs.

Each mock system is a `Router` of GET routes over in-memory records (dicts with an `id` and an
ISO 8601 `updated_at`). Standard library only, so the services need no dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

type Record = Mapping[str, Any]
type Query = Mapping[str, str]
type Handler = Callable[[Query, re.Match[str]], Any]

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

log = logging.getLogger("showcase")


class ApiError(Exception):
    """An error answered as `{"error": message}` with the given HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def parse_time(value: str) -> datetime:
    """Parse an ISO 8601 timestamp; one without an offset is taken as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ApiError(400, f"not an ISO 8601 timestamp: {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _int_param(query: Query, name: str, default: int, *, low: int, high: int | None = None) -> int:
    raw = query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, f"{name} must be an integer") from None
    if value < low or (high is not None and value > high):
        bound = f"between {low} and {high}" if high is not None else f"at least {low}"
        raise ApiError(400, f"{name} must be {bound}")
    return value


def paginate(records: Iterable[Record], query: Query) -> dict[str, Any]:
    """One page of `records`, oldest change first, optionally only those updated since a time.

    Query parameters: `limit` (1..100, default 20), `offset` (default 0) and `updated_since`
    (ISO 8601; records with `updated_at >= updated_since`). `next_offset` is null on the last page.
    """
    since = parse_time(query["updated_since"]) if "updated_since" in query else None
    limit = _int_param(query, "limit", DEFAULT_LIMIT, low=1, high=MAX_LIMIT)
    offset = _int_param(query, "offset", 0, low=0)
    matching = sorted(
        (r for r in records if since is None or parse_time(r["updated_at"]) >= since),
        key=lambda r: (parse_time(r["updated_at"]), r["id"]),
    )
    items = matching[offset : offset + limit]
    end = offset + len(items)
    return {
        "items": items,
        "total": len(matching),
        "limit": limit,
        "offset": offset,
        "next_offset": end if end < len(matching) else None,
    }


def search(records: Sequence[Record], fields: Sequence[str], term: str) -> list[Record]:
    """Records where every word of `term` occurs (case-insensitive) in one of `fields`."""
    words = term.lower().split()
    if not words:
        raise ApiError(400, "q must not be empty")
    return [
        r
        for r in records
        if all(any(w in str(r.get(f, "")).lower() for f in fields) for w in words)
    ]


class Router:
    """GET routes by path pattern; a handler returns the JSON body."""

    def __init__(self) -> None:
        self._routes: list[tuple[re.Pattern[str], Handler]] = []

    def get(self, pattern: str) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            self._routes.append((re.compile(pattern), handler))
            return handler

        return register

    def dispatch(self, target: str) -> tuple[int, Any]:
        """The status and JSON body for a request target (path and query string)."""
        parts = urlsplit(target)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        try:
            for pattern, handler in self._routes:
                if match := pattern.fullmatch(parts.path.rstrip("/") or "/"):
                    return 200, handler(query, match)
        except ApiError as err:
            return err.status, {"error": err.message}
        return 404, {"error": "not found"}


def lookup(records: Iterable[Record], record_id: str) -> Record:
    for record in records:
        if record["id"] == record_id:
            return record
    raise ApiError(404, f"{record_id} not found")


def serve(router: Router, *, name: str, default_port: int) -> None:
    """Serve `router` on $PORT (default `default_port`) until interrupted."""

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, body = router.dispatch(self.path)
            self._send(status, body)

        def do_HEAD(self) -> None:
            self._send(*router.dispatch(self.path), head=True)

        def _send(self, status: int, body: Any, *, head: bool = False) -> None:
            payload = json.dumps(body, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if not head:
                self.wfile.write(payload)

        def _method_not_allowed(self) -> None:
            self._send(405, {"error": "read-only API: only GET is supported"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed  # noqa: N815

        def log_message(self, format: str, *args: Any) -> None:
            log.info("%s %s", self.address_string(), format % args)

    logging.basicConfig(level=os.environ.get("KNOWCEL_LOG_LEVEL", "INFO"))
    port = int(os.environ.get("PORT", default_port))
    server = ThreadingHTTPServer(("0.0.0.0", port), RequestHandler)
    log.info("%s listening on :%d", name, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
