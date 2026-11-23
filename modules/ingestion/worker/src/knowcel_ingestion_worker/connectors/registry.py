"""The kinds of connectors the runtime can create."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .folder import FolderConnector
from .model import Source
from .sdk import Connector
from .showcase_engineering import ShowcaseEngineeringConnector
from .showcase_logistics import ShowcaseLogisticsConnector


@dataclass(frozen=True)
class Kind:
    """A kind of connector: the model its settings are validated against, and
    how a validated one becomes a `Source`."""

    config: type[BaseModel]
    create: Callable[..., Source]
    # Whether the connector can be searched live (it implements `search`).
    searchable: bool = False

    @classmethod
    def of(cls, connector: type[Connector[Any]]) -> "Kind":
        if not hasattr(connector, "config_model"):
            raise TypeError(f"{connector.__name__} must set config_model to its settings model")
        return cls(connector.config_model, connector, connector.searchable())


KINDS: dict[str, Kind] = {
    "folder": Kind.of(FolderConnector),
    "showcase_engineering": Kind.of(ShowcaseEngineeringConnector),
    "showcase_logistics": Kind.of(ShowcaseLogisticsConnector),
    # `task connector:new` registers new connectors above this line.
}
