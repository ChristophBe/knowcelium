"""The connector SDK: what to subclass to add a source system.

A connector implements `list_changes` and declares a Pydantic model for its
settings. That is enough for sync: the runtime validates the settings, turns
the records into documents, finds out what changed and deletes what vanished.
A connector may also implement `search` to be queried live, without copying
its content. `testkit` checks the contract, `docs/connectors.md` walks through
an example, and `task connector:new -- <name>` creates a starting point."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel

from .model import Record, Snippet


class Connector[C: BaseModel](ABC):
    """A system the runtime syncs from. Subclass it, set `config_model` and
    implement `list_changes`; register the class in `registry.py` (the scaffold
    does)."""

    # The settings of this connector, validated before `__init__` runs. Each
    # field becomes a key under `settings:` in the connectors file; a failing
    # check is reported to the administrator under that connector's name.
    config_model: ClassVar[type[BaseModel]]

    # True when `list_changes` always lists every item that exists, changed or
    # not: the runtime then deletes the documents of items it did not see. The
    # default is the safe one: a connector that lists only what changed has to
    # report removals as records with `deleted=True`.
    complete: bool = False

    def __init__(self, config: C) -> None:
        self.config = config

    @abstractmethod
    def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        """The items that changed since `since`, the start of the last
        successful sync (None for the first). Implement it as an async
        generator that yields `Record`s. Returning more than changed is fine:
        the runtime compares versions and content and skips what is
        unchanged. Raise `ConnectorError` for a problem the administrator can
        fix (a wrong token, an unreachable server); the run then fails
        without deleting anything."""
        ...

    async def search(self, query: str, limit: int) -> list[Snippet]:
        """Live retrieval: up to `limit` snippets of the source that match
        `query`, each with the URL it came from. Override it to be queried
        without syncing; the default finds nothing."""
        return []

    @classmethod
    def searchable(cls) -> bool:
        """True when the connector overrides `search`."""
        return cls.search is not Connector.search
