"""What a connector hands to the runtime: records, not documents.

A connector knows its source system and nothing about ingestion. It yields one
`Record` per item (a file, a ticket, a part) with a stable external id, and
the runtime turns them into documents, finds out what changed and deletes what
disappeared. The SDK's `Connector` base class (sdk.py) implements
`Source` on top of this."""

import mimetypes
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

Loader = Callable[[], Awaitable[bytes]]


@dataclass(frozen=True)
class Record:
    """One item of a source system."""

    # Identifies the item within its connector and never changes, so a rename
    # or an edit in the source updates the document instead of adding one.
    external_id: str
    # The file a document is made of; its extension decides how the text is read.
    filename: str = ""
    title: str = ""
    content_type: str = ""
    # The content, or a coroutine that reads it. A loader lets a source list
    # many items cheaply and read only those that changed (see `version`).
    data: bytes | None = None
    load: Loader | None = None
    # Where the item lives in the source, for people who want to open the original.
    source_url: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    # A cheap fingerprint of the item's state in the source (a modification time,
    # an etag). While it is unchanged the runtime does not read the content again.
    version: str = ""
    # The item no longer exists in the source: its document is deleted.
    deleted: bool = False

    async def read(self) -> bytes:
        if self.data is not None:
            return self.data
        if self.load is not None:
            return await self.load()
        return b""

    def media_type(self) -> str:
        if self.content_type:
            return self.content_type
        guessed, _ = mimetypes.guess_type(self.filename)
        return guessed or "application/octet-stream"


@dataclass(frozen=True)
class Snippet:
    """A passage a connector found when searched live (`Connector.search`)."""

    text: str
    # Where to open the original; shown as the citation.
    source_url: str
    title: str = ""
    external_id: str = ""


class Source(Protocol):
    """A system the runtime syncs from, created from a connector's settings."""

    # True when `list_changes` always lists every item that exists, changed or
    # not: the runtime then deletes the documents of items it did not see. A
    # source that only lists what changed since `since` reports removals as
    # records with `deleted` set instead.
    complete: bool

    def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        """The items that changed since `since`, the start of the last
        successful sync (None for the first). Returning more than changed is
        fine: the runtime compares versions and content and skips what is
        unchanged."""
        ...


class ConnectorError(Exception):
    """A connector cannot run because of its settings or permissions. The
    message is what the administrator reads, so it names the setting to fix."""
