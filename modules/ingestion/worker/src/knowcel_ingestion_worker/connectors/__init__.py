"""Connectors: sync external systems into documents on a schedule.

`model` is what a connector implements (`Source`, `Record`), `spec` how
connectors are configured, `runner` the sync runtime and `library` where
synced content goes. `folder` is the first connector."""

from .model import ConnectorError, Record, Source
from .runner import Outcome, Runner, run_schedule
from .spec import ConnectorSpec, Loaded, load_specs, parse_specs

__all__ = [
    "ConnectorError",
    "ConnectorSpec",
    "Loaded",
    "Outcome",
    "Record",
    "Runner",
    "Source",
    "load_specs",
    "parse_specs",
    "run_schedule",
]
