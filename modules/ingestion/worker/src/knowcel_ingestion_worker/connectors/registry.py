"""The kinds of connectors the runtime can create."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .folder import FolderConnector
from .model import Source
from .sdk import Connector


@dataclass(frozen=True)
class Kind:
    """A kind of connector: the model its settings are validated against, and
    how a validated one becomes a `Source`."""

    config: type[BaseModel]
    create: Callable[..., Source]

    @classmethod
    def of(cls, connector: type[Connector[Any]]) -> "Kind":
        if not hasattr(connector, "config_model"):
            raise TypeError(f"{connector.__name__} must set config_model to its settings model")
        return cls(connector.config_model, connector)


KINDS: dict[str, Kind] = {
    "folder": Kind.of(FolderConnector),
    # `task connector:new` registers new connectors above this line.
}
