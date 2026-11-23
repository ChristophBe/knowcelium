"""Connectors: sync external systems into documents on a schedule.

`sdk` is what a connector subclasses (`Connector`), `model` what it yields (`Record`), `spec` how
connectors are configured, `runner` the sync runtime and `library` where
synced content goes. `folder` is the first connector."""

from .model import ConnectorError, Record, Snippet, Source
from .runner import Outcome, Runner, run_schedule
from .sdk import Connector
from .spec import ConnectorSpec, Loaded, load_specs, parse_specs

__all__ = [
    "Connector",
    "ConnectorError",
    "ConnectorSpec",
    "Loaded",
    "Outcome",
    "Record",
    "Runner",
    "Snippet",
    "Source",
    "load_specs",
    "parse_specs",
    "run_schedule",
]
