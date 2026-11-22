"""The watched-folder connector: the files of a directory, mounted into the
worker, become documents. Adding, changing and removing files is reflected on
the next sync."""

import asyncio
import pathlib
from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from ..extract import HTML_SUFFIXES, TEXT_SUFFIXES
from .model import Record

SUPPORTED_SUFFIXES = TEXT_SUFFIXES | HTML_SUFFIXES | {".pdf", ".docx"}
# mimetypes has no entry for these on every platform.
_CONTENT_TYPES = {".md": "text/markdown", ".markdown": "text/markdown", ".rst": "text/x-rst"}


class FolderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The directory to watch, as the worker sees it.
    path: str
    # Also read the files of subdirectories.
    recursive: bool = True

    @field_validator("path")
    @classmethod
    def _is_directory(cls, value: str) -> str:
        if not pathlib.Path(value).is_dir():
            raise ValueError(f"{value!r} is not a directory the worker can read; mount it first")
        return value


class FolderSource:
    """Lists every supported file below `path`. The external id of a file is its
    path relative to the folder, so moving a file within it replaces the old
    document with a new one."""

    # Every file is listed on each sync, so a missing file means it was removed.
    complete = True

    def __init__(self, config: FolderConfig) -> None:
        self._root = pathlib.Path(config.path).resolve()
        self._recursive = config.recursive

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        # Listing only stats files; content is read when the runtime asks for
        # it, so an unchanged file costs nothing.
        for path in await asyncio.to_thread(self._files):
            try:
                stat = await asyncio.to_thread(path.stat)
            except OSError:
                continue  # removed since it was listed
            relative = path.relative_to(self._root).as_posix()
            yield Record(
                external_id=relative,
                filename=path.name,
                title=path.stem,
                content_type=_CONTENT_TYPES.get(path.suffix.lower(), ""),
                load=_reader(path),
                source_url=path.as_uri(),
                metadata={"path": relative},
                version=f"{stat.st_mtime_ns}-{stat.st_size}",
            )

    def _files(self) -> list[pathlib.Path]:
        found = self._root.rglob("*") if self._recursive else self._root.glob("*")
        return sorted(
            p
            for p in found
            if p.suffix.lower() in SUPPORTED_SUFFIXES
            and not any(part.startswith(".") for part in p.relative_to(self._root).parts)
            and p.is_file()
        )


def _reader(path: pathlib.Path):
    async def read() -> bytes:
        return await asyncio.to_thread(path.read_bytes)

    return read
