"""The kinds of connectors the runtime can create."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from .folder import FolderConfig, FolderSource
from .model import Source


@dataclass(frozen=True)
class Kind:
    """A kind of connector: the model its settings are validated against, and
    how a validated one becomes a `Source`."""

    config: type[BaseModel]
    create: Callable[..., Source]


KINDS: dict[str, Kind] = {
    "folder": Kind(FolderConfig, lambda c: FolderSource(c)),
}
