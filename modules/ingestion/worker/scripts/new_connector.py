"""Creates a connector from the template: `task connector:new -- <name>`.

Writes `connectors/<name>.py` and `tests/test_connector_<name>.py` (a passing
contract test) and registers the kind in `connectors/registry.py`."""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONNECTORS = ROOT / "src" / "knowcel_ingestion_worker" / "connectors"
TESTS = ROOT / "tests"
MARKER = "    # `task connector:new` registers new connectors above this line.\n"

CONNECTOR = '''"""The {name} connector. TODO: say what it syncs."""

from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .model import Record
from .sdk import Connector


class {cls}Config(BaseModel):
    """Settings under `settings:` of a `kind: {name}` entry in the connectors file."""

    model_config = ConfigDict(extra="forbid")

    # TODO: replace with the settings your source needs (url, token, ...).
    greeting: str = "Hello"


class {cls}Connector(Connector[{cls}Config]):
    config_model = {cls}Config
    # TODO: True when list_changes always lists every item, so that missing ones are deleted.
    complete = True

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        # TODO: list the items of your source; `since` is the start of the last
        # successful sync, or None for the first.
        yield Record(
            external_id="hello",
            filename="hello.md",
            title="Hello",
            data=f"{{self.config.greeting}} from the {name} connector.".encode(),
            version="1",
        )
'''

TEST = """from knowcel_ingestion_worker.connectors.{name} import {cls}Connector
from knowcel_ingestion_worker.connectors.testkit import check_connector


async def test_{name}_meets_the_connector_contract():
    await check_connector({cls}Connector, {{"greeting": "Hi"}}, invalid=[{{"unknown": 1}}])
"""


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", argv[0]):
        print(
            "usage: task connector:new -- <name>  (lowercase letters, digits and _, "
            "starting with a letter)",
            file=sys.stderr,
        )
        return 2
    name = argv[0]
    cls = "".join(part.capitalize() for part in name.split("_"))
    module, test = CONNECTORS / f"{name}.py", TESTS / f"test_connector_{name}.py"
    registry = CONNECTORS / "registry.py"
    text = registry.read_text(encoding="utf-8")
    if module.exists() or test.exists() or f'"{name}":' in text:
        print(f"a connector or module named {name!r} already exists", file=sys.stderr)
        return 1
    if MARKER not in text:
        print(f"cannot find the registration marker in {registry}", file=sys.stderr)
        return 1
    module.write_text(CONNECTOR.format(name=name, cls=cls), encoding="utf-8")
    test.write_text(TEST.format(name=name, cls=cls), encoding="utf-8")
    text = text.replace(
        "from .model import Source\n",
        f"from .{name} import {cls}Connector\nfrom .model import Source\n",
        1,
    )
    text = text.replace(MARKER, f'    "{name}": Kind.of({cls}Connector),\n{MARKER}')
    registry.write_text(text, encoding="utf-8")
    print(f"created {module.name} and {test.name}; registered kind {name!r}")
    print("next: implement list_changes, then read docs/connectors.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
