# Build a connector

A connector connects Knowcelium to a system that holds content: a wiki, a drive, a ticket tracker. You write a small Python class; the ingestion worker does the rest (scheduling, settings validation, creating, replacing and deleting documents, status reporting). To run connectors, see [Connectors](operations/connectors.md).

A connector works in one or both of two modes:

- **Sync** copies the source into documents on a schedule. Everything downstream (search, chat, access rules) then works as for an upload. Implement `list_changes`; this is all a connector needs.
- **Live search** asks the source at question time and copies nothing, for content that is too large or too volatile to mirror. Implement `search` in addition and set `live_search: true` on the connector ([operations](operations/connectors.md#live-search)). Chat then asks the connector whenever someone asks a question and cites what it returns, next to document passages. A connector can do both, or only live search (`sync: false`).

The code lives in `modules/ingestion/worker/src/knowcel_ingestion_worker/connectors/`:

| File | What it is |
|---|---|
| `sdk.py` | `Connector`, the base class you subclass |
| `model.py` | `Record` (what `list_changes` yields), `Snippet` (what `search` returns), `ConnectorError` |
| `testkit.py` | `check_connector`, the contract test |
| `registry.py` | the kinds the runtime knows |
| `folder.py` | the watched-folder connector, used as the example below |

## Start from the scaffold

```sh
task connector:new -- wiki
```

This writes `connectors/wiki.py` and `tests/test_connector_wiki.py`, and registers the kind `wiki` in `registry.py`. The generated connector yields one hello-world record, and `task test` passes unchanged. Replace the TODOs, then use it in the connectors file with `kind: wiki`.

Names are lowercase letters, digits and `_`, starting with a letter.

## The shape of a connector

```python
class FolderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str  # the directory to watch, as the worker sees it
    recursive: bool = True

    @field_validator("path")
    @classmethod
    def _is_directory(cls, value: str) -> str: ...


class FolderConnector(Connector[FolderConfig]):
    config_model = FolderConfig
    complete = True

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]: ...
```

### Settings

`config_model` is a Pydantic model. Its fields are the keys under `settings:` of the connector's entry in the connectors file. The framework validates them before your class is created, and a problem is reported against that connector (naming the setting) without stopping the others. Use `extra="forbid"` so that typos are caught, and validators for what only your source can check. Your `__init__` receives the validated model as `self.config`.

### `list_changes(since)`

An async generator that yields one `Record` per item of the source:

| Field | Meaning |
|---|---|
| `external_id` | Identifies the item in your source and never changes: a renamed or edited item updates its document instead of adding one. The folder connector uses the relative path. |
| `filename` | The file the document is made of; its extension decides how the text is read (`.md`, `.txt`, `.html`, `.pdf`, `.docx`). |
| `title`, `source_url`, `metadata` | Shown on the document; `source_url` links people to the original. |
| `data` or `load` | The content as bytes, or a coroutine that reads it. Prefer `load`: list cheaply and read only what changed. |
| `version` | A cheap fingerprint (a modification time, an etag). While it is unchanged the runtime does not read the content again. |
| `deleted` | The item no longer exists: its document is deleted. |

`since` is the start of the last successful sync, or `None` for the first one. You may ignore it and list everything: the runtime compares versions and content, so unchanged items cost nothing, and a sync twice in a row changes nothing.

Raise `ConnectorError` with a message the administrator can act on for problems they can fix (a wrong token, an unmounted folder). The run then fails without deleting anything.

### Deletions: `complete`

The runtime has to learn what disappeared. Pick one:

- `complete = True`: your listing always contains every item that exists. Documents of items you did not list are deleted. Right for folders and anything that is cheap to list in full. A listing that is empty while documents exist is refused, in case the source is merely unreachable.
- `complete = False` (the default): you list only what changed since `since`, and report removals as records with `deleted=True`. This is the safe default for a connector that stops at the first change.

### `search(query, limit)` (optional)

```python
async def search(self, query: str, limit: int) -> list[Snippet]: ...
```

Return up to `limit` `Snippet`s (`text`, `source_url`, optional `title` and `external_id`) that match the query, best first. `Connector.searchable()` tells the framework whether you did. A connector without it returns nothing.

Things to know when you write one:

- **The query is the user's question**, as typed. Turn it into what your source understands (keywords, filters).
- **You do not learn who is asking.** The connector runs with its own credentials, and everyone allowed to read it (`public`, or a member of one of its `team_ids`) gets whatever you return. Only expose in `search` what all of them may see; the administrator has to opt in per connector.
- **Be quick.** A search that takes longer than the timeout (5 s by default) is dropped and the answer notes that the connector was unavailable. Raise `ConnectorError` for problems the administrator can fix; any other exception is logged and treated the same way.
- `source_url` is shown as the citation's link, and is only followed when it is an `http` or `https` address.

## Walkthrough: the watched folder

`folder.py` is about 130 lines and uses everything above.

1. `FolderConfig` takes the directory and a `recursive` flag, and its validator rejects a path that is not a readable directory, which tells the administrator to mount it.
2. `FolderConnector.list_changes` first checks that the folder can be read, because an unmounted folder looks empty and would otherwise delete every document. Then it walks the files, skips hidden files, unsupported types and links that leave the folder, and yields a `Record` per file with the relative path as `external_id`, a `file://` source URL, and `mtime-size` as `version`.
3. The content is not read while listing: each record carries a `load` coroutine, so an unchanged file costs one `stat`.
4. `complete = True`: the folder is listed in full on every sync, so a file that is gone is deleted.
5. Paths that cannot be read make the run fail at the end of the listing instead of shrinking it.

## Test it

`testkit.check_connector` runs your connector through the real runtime against an in-memory library:

```python
async def test_contract(tmp_path):
    (tmp_path / "a.md").write_text("one")
    await check_connector(
        FolderConnector,
        {"path": str(tmp_path)},
        invalid=[{}, {"path": str(tmp_path / "missing")}],
        remove=(tmp_path / "a.md").unlink,
    )
```

It checks that the settings validate and `invalid` ones are rejected, that the records have unique external ids, that a first sync creates documents, that a second sync of the unchanged source creates, updates and deletes nothing, and (with `remove`, a function that removes one item from your source) that exactly that item's document is deleted on the next sync. The source must hold at least one item when the check starts. Test your connector's own logic (pagination, error cases) in ordinary tests next to it.

## Register and run

`task connector:new` registers the class in `registry.py`; for a hand-written one add `"<kind>": Kind.of(YourConnector)` to `KINDS`. Then configure an entry with that `kind` as described in [Connectors](operations/connectors.md).
