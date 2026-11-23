"""The contract every connector has to meet, as a helper for its test.

    async def test_contract():
        await check_connector(
            MyConnector,
            {"url": "https://example.com"},
            invalid=[{}, {"url": "not a url"}],
            remove=remove_one_item,
        )

`check_connector` runs the connector through the real runtime against an
in-memory library and fails with an `AssertionError` that says which rule is
broken. Import it from tests only."""

import inspect
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from pydantic import ValidationError

from .library import DocumentGoneError
from .model import Record
from .registry import KINDS, Kind
from .runner import Outcome, Runner
from .sdk import Connector
from .spec import ConnectorSpec
from .state import MemoryState


class MemoryLibrary:
    """Keeps the documents of a sync in a dict, as a `Library`."""

    def __init__(self) -> None:
        # document id -> (external id, data)
        self.docs: dict[str, tuple[str, bytes]] = {}

    async def ensure_admin(self, owner: str) -> None:
        return None

    async def create(self, spec: ConnectorSpec, record: Record, data: bytes) -> str:
        document_id = uuid.uuid4().hex
        self.docs[document_id] = (record.external_id, data)
        return document_id

    async def replace(
        self, spec: ConnectorSpec, document_id: str, record: Record, data: bytes
    ) -> None:
        if document_id not in self.docs:
            raise DocumentGoneError(document_id)
        self.docs[document_id] = (record.external_id, data)

    async def delete(self, spec: ConnectorSpec, document_id: str) -> None:
        self.docs.pop(document_id, None)

    def external_ids(self) -> set[str]:
        return {external_id for external_id, _ in self.docs.values()}


Change = Callable[[], Awaitable[None] | None]


@contextmanager
def registered(connector: type[Connector[Any]], name: str) -> Iterator[None]:
    """Makes the runtime know `connector` as kind `name` while it is used."""
    KINDS[name] = Kind.of(connector)
    try:
        yield
    finally:
        del KINDS[name]


async def _call(change: Change) -> None:
    result = change()
    if inspect.isawaitable(result):
        await result


def check_config(
    connector: type[Connector[Any]],
    settings: Mapping[str, Any],
    invalid: Sequence[Mapping[str, Any]],
) -> None:
    """The settings validate, and each of `invalid` is rejected by the model
    (a problem the administrator is told about) rather than failing later."""
    connector.config_model.model_validate(settings)
    for bad in invalid:
        try:
            connector.config_model.model_validate(bad)
        except ValidationError:
            continue
        raise AssertionError(f"settings {dict(bad)!r} should be rejected, but validate")


async def check_connector(
    connector: type[Connector[Any]],
    settings: Mapping[str, Any],
    *,
    invalid: Sequence[Mapping[str, Any]] = (),
    remove: Change | None = None,
) -> Outcome:
    """Checks the contract and returns the outcome of the first sync.

    - the settings are validated by `config_model` (`invalid` ones are rejected);
    - the records have unique, non-empty external ids, and a first sync creates
      a document for them;
    - a second sync of the unchanged source is idempotent: nothing is created,
      updated or deleted, and nothing fails;
    - `remove` (optional) removes one item from the source; the next sync then
      deletes exactly its document, whether the connector lists everything
      (`complete`) or reports `deleted` records.

    The source must hold at least one item with content when this is called."""
    check_config(connector, settings, invalid)
    name = "contract-check"
    spec = ConnectorSpec(name=name, kind=name, owner="tester", public=True, settings=dict(settings))
    library = MemoryLibrary()
    runner = Runner(library, MemoryState())
    with registered(connector, name):
        listed = [
            r.external_id
            async for r in connector(connector.config_model.model_validate(settings)).list_changes(
                None
            )
        ]
        assert "" not in listed, "a record has an empty external id"
        assert len(listed) == len(set(listed)), "two records share an external id"
        first = await _sync(runner, spec, "first")
        assert first.created > 0, "the first sync created no document: is the source empty?"
        ids = library.external_ids()

        again = await _sync(runner, spec, "second")
        assert (again.created, again.updated, again.deleted) == (0, 0, 0), (
            f"syncing an unchanged source is not idempotent: {again}"
        )
        assert library.external_ids() == ids

        if remove is not None:
            await _call(remove)
            removed = await _sync(runner, spec, "third")
            assert removed.deleted == 1, f"removing one item deleted {removed.deleted} documents"
            assert len(library.external_ids()) == len(ids) - 1
    return first


async def _sync(runner: Runner, spec: ConnectorSpec, label: str) -> Outcome:
    outcome = await runner.sync(spec)
    assert outcome is not None, f"the {label} sync did not run; see the log for its status"
    assert outcome.failed == 0, f"the {label} sync had failing items: {outcome}"
    return outcome
