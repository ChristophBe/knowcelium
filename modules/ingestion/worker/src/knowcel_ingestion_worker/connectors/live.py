"""Live search: asking connectors for passages at question time.

The ingestion service sends a `ConnectorSearchRequest` over NATS (request/reply
on `SUBJECT`, see docs/adr/0015-live-retrieval-through-connectors.md); the
worker that receives it asks every connector the caller may read, concurrently,
and replies with the snippets and the names of the connectors that failed. A
connector never fails the whole search: its error or timeout only puts its
name on the list."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from knowcel.ingestion.v1 import events_pb2, ingestion_pb2

from .model import ConnectorError, Snippet
from .registry import KINDS
from .sdk import Connector
from .spec import ConnectorSpec, describe

log = logging.getLogger(__name__)

# The core NATS subject of search requests. It is outside the INGESTION stream
# (`knowcel.ingestion.>`), which would answer a request with a stream ack.
SUBJECT = "knowcel.connectors.search"
QUEUE = "ingestion-worker"

# Seconds a connector gets when the request names none.
DEFAULT_TIMEOUT = 5.0
# Seconds a successful check that a connector's owner is a platform admin holds.
ADMIN_TTL = 60.0
MAX_LIMIT = 20

EnsureAdmin = Callable[[str], Awaitable[None]]


class LiveSearch:
    """The connectors that allow live search, as the worker serves them."""

    def __init__(
        self,
        specs: list[ConnectorSpec],
        ensure_admin: EnsureAdmin,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._specs = [s for s in specs if s.enabled and s.live_search]
        self._ensure_admin = ensure_admin
        self._clock = clock
        self._approved: dict[str, float] = {}  # owner -> when the approval expires
        self._connectors: dict[str, Connector[Any]] = {}

    async def handle(self, request: events_pb2.ConnectorSearchRequest) -> bytes:
        """The serialized `ConnectorSearchReply` to a serialized request."""
        return (await self.search(request)).SerializeToString()

    async def search(
        self, request: events_pb2.ConnectorSearchRequest
    ) -> events_pb2.ConnectorSearchReply:
        asked = [s for s in self._specs if _asked(s, request)]
        limit = min(max(request.limit, 1), MAX_LIMIT)
        timeout = request.timeout_seconds or DEFAULT_TIMEOUT
        results = await asyncio.gather(
            *(self._ask(s, request.query, limit, timeout) for s in asked)
        )
        reply = events_pb2.ConnectorSearchReply(searched_connectors=[s.name for s in asked])
        found: list[list[ingestion_pb2.ConnectorSnippet]] = []
        for spec, result in zip(asked, results, strict=True):
            if result is None:
                reply.unavailable_connectors.append(spec.name)
            else:
                found.append(result)
        reply.snippets.extend(_interleave(found)[:limit])
        return reply

    async def _ask(
        self, spec: ConnectorSpec, query: str, limit: int, deadline: float
    ) -> list[ingestion_pb2.ConnectorSnippet] | None:
        """The snippets of one connector, or None when it failed or was too slow."""
        try:
            async with asyncio.timeout(deadline):
                await self._approve(spec)
                snippets = await self._connector(spec).search(query, limit)
        except TimeoutError:
            log.warning("connector %s did not answer a live search in %ss", spec.name, deadline)
            return None
        except ConnectorError as err:
            log.warning("connector %s cannot be searched: %s", spec.name, err)
            return None
        except Exception:
            log.exception("connector %s failed a live search", spec.name)
            return None
        return [_snippet(spec, s) for s in snippets[:limit] if s.text.strip()]

    async def _approve(self, spec: ConnectorSpec) -> None:
        """Raises `ConnectorError` unless the connector's owner is (still) a
        platform admin: only a platform admin may expose a source to live search."""
        if self._approved.get(spec.owner, 0.0) > self._clock():
            return
        await self._ensure_admin(spec.owner)
        self._approved[spec.owner] = self._clock() + ADMIN_TTL

    def _connector(self, spec: ConnectorSpec) -> Connector[Any]:
        if (connector := self._connectors.get(spec.name)) is not None:
            return connector
        kind = KINDS[spec.kind]
        try:
            created = kind.create(kind.config.model_validate(spec.settings))
        except ValueError as err:  # a directory that vanished, a bad URL, ...
            raise ConnectorError(f"settings of {spec.name}: {describe(err)}") from err
        if not isinstance(created, Connector):
            raise ConnectorError(f"{spec.name} cannot be searched live")
        self._connectors[spec.name] = created
        return created


def _asked(spec: ConnectorSpec, request: events_pb2.ConnectorSearchRequest) -> bool:
    """Whether a search for this caller asks the connector: it was named (when
    names are given), within the scope (when teams are given), and the caller
    may read it."""
    if request.connector_ids and spec.name not in request.connector_ids:
        return False
    if request.scope_team_ids:
        return bool(set(spec.team_ids) & set(request.scope_team_ids) & set(request.member_team_ids))
    return spec.public or bool(set(spec.team_ids) & set(request.member_team_ids))


def _snippet(spec: ConnectorSpec, snippet: Snippet) -> ingestion_pb2.ConnectorSnippet:
    return ingestion_pb2.ConnectorSnippet(
        connector=spec.name,
        title=snippet.title,
        text=snippet.text,
        source_url=snippet.source_url,
        external_id=snippet.external_id,
    )


def _interleave(
    lists: list[list[ingestion_pb2.ConnectorSnippet]],
) -> list[ingestion_pb2.ConnectorSnippet]:
    """The best of each connector first: round robin over the connectors."""
    merged: list[ingestion_pb2.ConnectorSnippet] = []
    for rank in range(max((len(x) for x in lists), default=0)):
        merged.extend(x[rank] for x in lists if rank < len(x))
    return merged
