"""Connector settings: which connectors exist and how each runs.

Connectors are configured in a YAML (or JSON) file, `KNOWCEL_CONNECTORS_FILE`, so
adding one needs no code change:

    connectors:
      - name: handbook
        kind: folder
        owner: 6f1d0c3e-...        # the platform admin it runs as
        team_ids: [3c8a...]        # who can read what it syncs ...
        public: false              # ... or public: true for everyone
        interval_seconds: 300
        settings: {path: /watch}   # specific to the kind

An invalid entry never stops the others: it is reported as that connector's
error (see `load_specs`)."""

import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .registry import KINDS

NAME_PATTERN = r"[a-z0-9][a-z0-9_-]{0,62}"


class ConnectorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=f"^{NAME_PATTERN}$")
    kind: str
    enabled: bool = True
    # The platform admin the connector runs as: the user id (the subject of
    # their token). Documents it creates are owned by this user.
    owner: str = Field(min_length=1)
    # Teams the documents are shared with; the owner must be a member of each.
    team_ids: list[str] = []
    # Share with everyone instead. There is no private mode in the document
    # module yet, so a connector has to choose one or the other explicitly.
    public: bool = False
    # Seconds between the start of two syncs.
    interval_seconds: int = Field(default=300, ge=10)
    settings: dict[str, Any] = {}

    @model_validator(mode="after")
    def _sharing(self) -> "ConnectorSpec":
        if self.public and self.team_ids:
            raise ValueError("set either team_ids or public: true, not both")
        if not self.public and not self.team_ids:
            raise ValueError(
                "choose who can read the documents: list team_ids, or set public: true"
            )
        return self


@dataclass(frozen=True)
class Loaded:
    """The outcome of reading the connectors file."""

    specs: list[ConnectorSpec] = field(default_factory=list)
    # Connector name (or "#<position>" when it has none) to what is wrong.
    errors: dict[str, str] = field(default_factory=dict)


def load_specs(path: str) -> Loaded:
    """Reads and validates the connectors file. Raises `ValueError` when the file
    itself cannot be read; problems of single entries are returned in `errors`."""
    try:
        raw = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as err:
        raise ValueError(f"cannot read connectors file {path}: {err}") from err
    entries = raw.get("connectors", []) if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a top-level `connectors:` list")
    return parse_specs(entries)


def parse_specs(entries: list[Any]) -> Loaded:
    specs: list[ConnectorSpec] = []
    problems: list[tuple[int, str, str]] = []  # position, label, what is wrong
    names: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        label = f"#{position}"
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            label = entry["name"]
        try:
            spec = ConnectorSpec.model_validate(entry)
            kind = KINDS.get(spec.kind)
            if kind is None:
                raise ValueError(f"unknown kind {spec.kind!r}; known kinds: {', '.join(KINDS)}")
            kind.config.model_validate(spec.settings)
        except (ValidationError, ValueError) as err:
            problems.append((position, label, describe(err)))
            continue
        if spec.name in names:  # only valid entries claim a name
            problems.append((position, label, "the name is used twice"))
            continue
        names.add(spec.name)
        specs.append(spec)
    errors: dict[str, str] = {}
    for position, label, message in problems:
        # A problem never shares a key with a running connector or another problem.
        key = label if label not in names and label not in errors else f"{label} (entry {position})"
        errors[key] = message
    return Loaded(specs=specs, errors=errors)


def describe(err: ValidationError | ValueError) -> str:
    """The problems of a validation error in one sentence, naming each setting."""
    if not isinstance(err, ValidationError):
        return str(err)
    parts = []
    for item in err.errors():
        where = ".".join(str(p) for p in item["loc"])
        message = re.sub(r"^Value error, ", "", item["msg"])
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)
