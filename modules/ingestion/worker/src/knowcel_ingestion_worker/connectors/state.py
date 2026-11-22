"""What the runtime remembers between syncs: per connector its status and, per
item, the document it became and the version it was synced at. Held in a
JetStream key-value bucket, so the worker needs no database of its own and the
state survives restarts."""

import contextlib
import hashlib
import json
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from nats.js import JetStreamContext
from nats.js.errors import (
    BucketNotFoundError,
    KeyDeletedError,
    KeyNotFoundError,
    KeyWrongLastSequenceError,
)

from .spec import NAME_PATTERN

BUCKET = "ingestion_connectors"

Entry = dict[str, Any]

# Reading a key that never existed or was deleted.
_ABSENT = (KeyNotFoundError, KeyDeletedError)


class State(Protocol):
    async def get(self, key: str) -> Entry | None: ...

    async def put(self, key: str, value: Entry) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def keys(self, prefix: str) -> list[str]: ...

    async def items(self, prefix: str) -> dict[str, Entry]:
        """The entries whose key starts with `prefix`, in one read."""
        ...

    async def acquire(self, key: str, holder: str, ttl: float) -> bool:
        """Takes a lease on `key` for `ttl` seconds unless another holder has one,
        so that two workers never sync the same connector at once."""
        ...

    async def release(self, key: str, holder: str) -> None: ...


def item_key(connector: str, external_id: str) -> str:
    """The key of an item; external ids are arbitrary text, keys are not."""
    return f"{connector}.item.{hashlib.sha256(external_id.encode()).hexdigest()[:40]}"


def status_key(connector: str) -> str:
    """The key of a connector's status. The name of a connector that is not
    valid (it is only reported) is encoded: it may hold characters a key
    cannot, and must not collide with a valid name."""
    if re.fullmatch(NAME_PATTERN, connector):
        return f"{connector}.status"
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", connector).strip("_")[:40]
    digest = hashlib.sha256(connector.encode()).hexdigest()[:10]
    return f"invalid.{safe}-{digest}.status"


def lease_key(connector: str) -> str:
    return f"{connector}.lease"


class MemoryState:
    """State in memory, for tests and single-process runs."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._data: dict[str, Entry] = {}
        self._clock = clock

    async def get(self, key: str) -> Entry | None:
        return self._data.get(key)

    async def put(self, key: str, value: Entry) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def keys(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]

    async def items(self, prefix: str) -> dict[str, Entry]:
        return {k: v for k, v in self._data.items() if k.startswith(prefix)}

    async def acquire(self, key: str, holder: str, ttl: float) -> bool:
        lease = self._data.get(key)
        if lease and lease["holder"] != holder and lease["until"] > self._clock():
            return False
        self._data[key] = {"holder": holder, "until": self._clock() + ttl}
        return True

    async def release(self, key: str, holder: str) -> None:
        if (lease := self._data.get(key)) and lease["holder"] == holder:
            del self._data[key]


class KvState:
    """State in a JetStream key-value bucket."""

    def __init__(self, kv: Any, clock: Callable[[], float] = time.time) -> None:
        self._kv = kv
        self._clock = clock

    @classmethod
    async def open(cls, js: JetStreamContext) -> "KvState":
        try:
            kv = await js.key_value(BUCKET)
        except BucketNotFoundError:
            kv = await js.create_key_value(bucket=BUCKET)
        return cls(kv)

    async def get(self, key: str) -> Entry | None:
        try:
            entry = await self._kv.get(key)
        except _ABSENT:
            return None
        return json.loads(entry.value) if entry.value else None

    async def put(self, key: str, value: Entry) -> None:
        await self._kv.put(key, json.dumps(value).encode())

    async def delete(self, key: str) -> None:
        with contextlib.suppress(*_ABSENT):
            await self._kv.delete(key)

    async def keys(self, prefix: str) -> list[str]:
        return list(await self._watch(prefix, meta_only=True))

    async def items(self, prefix: str) -> dict[str, Entry]:
        return await self._watch(prefix, meta_only=False)

    async def _watch(self, prefix: str, meta_only: bool) -> dict[str, Entry]:
        # A watch on the subject `<prefix>>` reads only the keys below the prefix
        # (which ends in a "."), unlike `keys()`, which reads every key, and
        # carries the values, so there is no get per key.
        watcher = await self._kv.watch(f"{prefix}>", ignore_deletes=True, meta_only=meta_only)
        found: dict[str, Entry] = {}
        try:
            async for entry in watcher:
                if entry is None:  # what exists has been listed
                    break
                found[entry.key] = json.loads(entry.value) if entry.value else {}
        finally:
            await watcher.stop()
        return found

    async def acquire(self, key: str, holder: str, ttl: float) -> bool:
        lease = json.dumps({"holder": holder, "until": self._clock() + ttl}).encode()
        try:
            entry = await self._kv.get(key)
        except _ABSENT:
            entry = None
        try:
            if entry is None:
                await self._kv.create(key, lease)
                return True
            current = json.loads(entry.value) if entry.value else {}
            if current and current["holder"] != holder and current["until"] > self._clock():
                return False
            # Compare-and-set on the revision we read, so only one claimant wins.
            await self._kv.update(key, lease, entry.revision)
        except KeyWrongLastSequenceError:
            return False
        return True

    async def release(self, key: str, holder: str) -> None:
        try:
            entry = await self._kv.get(key)
        except _ABSENT:
            return
        if entry.value and json.loads(entry.value).get("holder") == holder:
            await self.delete(key)
