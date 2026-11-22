"""The sync runtime: one run of a connector, and the schedule that repeats it.

A run lists the source's changes, turns each into an upload, replacement or
deletion of a document and records the outcome. It keeps going past a failing
item so that one bad file does not hold the rest back; the run then counts as
failed, so the next one re-lists from the last successful start."""

import asyncio
import contextlib
import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import grpc

from .library import DocumentGoneError, Library
from .model import ConnectorError, Record
from .registry import KINDS
from .spec import ConnectorSpec, describe
from .state import State, item_key, lease_key, status_key

log = logging.getLogger(__name__)

# A lease outlives a sync that is still running; a crashed worker's lease
# expires after this long.
LEASE_SECONDS = 600
# Keeps the failure text short enough for a status line.
_MAX_ERROR = 500


@dataclass
class Outcome:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    failed: int = 0


def now() -> datetime:
    return datetime.now(UTC)


class Runner:
    """Runs syncs against a library, keeping state in `state`."""

    def __init__(
        self,
        library: Library,
        state: State,
        clock: Callable[[], datetime] = now,
        holder: str | None = None,
    ) -> None:
        self._library = library
        self._state = state
        self._clock = clock
        self._holder = holder or uuid.uuid4().hex

    async def sync(self, spec: ConnectorSpec) -> Outcome | None:
        """One sync of the connector. Returns what it did, or None when another
        worker is syncing it or the run failed as a whole (the reason is in the
        connector's status)."""
        if not await self._state.acquire(lease_key(spec.name), self._holder, LEASE_SECONDS):
            return None
        started = self._clock()
        status = await self._state.get(status_key(spec.name)) or {}
        status["last_start"] = started.isoformat()
        try:
            outcome = await self._run(spec, status, started)
        except ConnectorError as err:
            log.warning("connector %s cannot sync: %s", spec.name, err)
            status["last_error"] = str(err)
            outcome = None
        except Exception as err:
            log.exception("connector %s failed", spec.name)
            status["last_error"] = _brief(err)
            outcome = None
        finally:
            status["last_end"] = self._clock().isoformat()
            await self._state.put(status_key(spec.name), status)
            await self._state.release(lease_key(spec.name), self._holder)
        return outcome

    async def report(self, name: str, error: str) -> None:
        """Records that a connector cannot start (its settings are invalid), so
        that its status says why rather than only the worker's log."""
        status = await self._state.get(status_key(name)) or {}
        status["last_error"] = error
        status["last_end"] = self._clock().isoformat()
        await self._state.put(status_key(name), status)

    async def _run(self, spec: ConnectorSpec, status: dict[str, Any], started: datetime) -> Outcome:
        kind = KINDS[spec.kind]
        try:
            source = kind.create(kind.config.model_validate(spec.settings))
        except ValueError as err:  # a directory that vanished, a bad URL, ...
            raise ConnectorError(f"settings of {spec.name}: {describe(err)}") from err
        await self._library.ensure_admin(spec.owner)
        since = _parse(status.get("last_success_start"))
        outcome = Outcome()
        seen: set[str] = set()
        first_error = ""
        async for record in source.list_changes(since):
            seen.add(record.external_id)
            try:
                await self._apply(spec, record, outcome)
            except Exception as err:
                outcome.failed += 1
                first_error = first_error or f"{record.external_id}: {_brief(err)}"
                log.warning("connector %s: %s failed: %s", spec.name, record.external_id, err)
        if source.complete and not outcome.failed:
            await self._sweep(spec, seen, outcome)
        status["documents"] = len(await self._state.keys(f"{spec.name}.item."))
        if outcome.failed:
            status["last_error"] = f"{outcome.failed} items failed; first: {first_error}"
        else:
            status["last_error"] = ""
            status["last_success_start"] = started.isoformat()
            status["last_success"] = self._clock().isoformat()
        log.info(
            "connector %s synced: %d created, %d updated, %d deleted, %d unchanged, %d failed",
            spec.name,
            outcome.created,
            outcome.updated,
            outcome.deleted,
            outcome.unchanged,
            outcome.failed,
        )
        return outcome

    async def _apply(self, spec: ConnectorSpec, record: Record, outcome: Outcome) -> None:
        key = item_key(spec.name, record.external_id)
        item = await self._state.get(key)
        if record.deleted:
            if item:
                await self._library.delete(spec, item["document_id"])
                await self._state.delete(key)
                outcome.deleted += 1
            return
        if item and record.version and item.get("version") == record.version:
            outcome.unchanged += 1
            return
        data = await record.read()
        if not data:
            log.warning("connector %s: %s is empty, skipped", spec.name, record.external_id)
            return
        digest = hashlib.sha256(data).hexdigest()
        if item and item.get("sha256") == digest:
            # Touched but not changed: remember the version so it is not read again.
            await self._state.put(key, {**item, "version": record.version})
            outcome.unchanged += 1
            return
        document_id = item["document_id"] if item else None
        if document_id:
            try:
                await self._library.replace(spec, document_id, record, data)
                outcome.updated += 1
            except DocumentGoneError:
                document_id = None  # deleted by hand: add it again
        if not document_id:
            document_id = await self._library.create(spec, record, data)
            outcome.created += 1
        await self._state.put(
            key,
            {
                "external_id": record.external_id,
                "document_id": document_id,
                "version": record.version,
                "sha256": digest,
            },
        )

    async def _sweep(self, spec: ConnectorSpec, seen: set[str], outcome: Outcome) -> None:
        """Deletes the documents of items a complete listing no longer has."""
        for key in await self._state.keys(f"{spec.name}.item."):
            item = await self._state.get(key)
            if item is None or item["external_id"] in seen:
                continue
            try:
                await self._library.delete(spec, item["document_id"])
            except grpc.aio.AioRpcError as err:
                outcome.failed += 1
                log.warning("connector %s: could not delete %s: %s", spec.name, key, err)
                continue
            await self._state.delete(key)
            outcome.deleted += 1


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _brief(err: BaseException) -> str:
    if isinstance(err, grpc.aio.AioRpcError):
        text = f"{err.code().name}: {err.details()}"
    else:
        text = str(err) or type(err).__name__
    return text[:_MAX_ERROR]


async def run_schedule(runner: Runner, specs: list[ConnectorSpec], stop: asyncio.Event) -> None:
    """Syncs every enabled connector on its own interval, the first time at
    once, until `stop` is set."""

    async def loop(spec: ConnectorSpec) -> None:
        while not stop.is_set():
            await runner.sync(spec)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), spec.interval_seconds)

    await asyncio.gather(*(loop(s) for s in specs if s.enabled))
