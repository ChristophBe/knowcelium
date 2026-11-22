"""The watched-folder connector: the files of a directory, mounted into the
worker, become documents. Adding, changing and removing files is reflected on
the next sync."""

import asyncio
import logging
import os
import pathlib
from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from ..extract import HTML_SUFFIXES, TEXT_SUFFIXES
from .model import ConnectorError, Record

log = logging.getLogger(__name__)

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
    document with a new one. Links that lead out of the folder are skipped."""

    # Every file is listed on each sync, so a missing file means it was removed.
    complete = True

    def __init__(self, config: FolderConfig) -> None:
        self._root = pathlib.Path(config.path).resolve()
        self._recursive = config.recursive

    async def list_changes(self, since: datetime | None) -> AsyncIterator[Record]:
        # An unreadable or vanished folder is an error, not an empty listing:
        # the runtime would delete every document of a folder that is merely
        # not mounted.
        try:
            await asyncio.to_thread(self._check_readable)
        except OSError as err:
            raise ConnectorError(f"cannot read the folder {self._root}: {err}") from err
        files, unreadable = await asyncio.to_thread(self._files)
        # Listing only stats files; content is read when the runtime asks for
        # it, so an unchanged file costs nothing.
        for relative, path in files:
            try:
                stat = await asyncio.to_thread(path.stat)
            except FileNotFoundError:
                continue  # removed since it was listed
            except OSError as err:
                unreadable.append(f"{relative}: {err}")
                continue
            name = pathlib.PurePosixPath(relative)
            yield Record(
                external_id=relative,
                filename=name.name,
                title=name.stem,
                content_type=_CONTENT_TYPES.get(name.suffix.lower(), ""),
                load=_reader(path),
                source_url=(self._root / relative).as_uri(),
                metadata={"path": relative},
                version=f"{stat.st_mtime_ns}-{stat.st_size}",
            )
        if unreadable:
            # Files may be missing from the listing: the run fails, so that the
            # runtime does not delete their documents.
            raise ConnectorError(
                f"{len(unreadable)} paths of {self._root} cannot be read; first: {unreadable[0]}"
            )

    def _check_readable(self) -> None:
        with os.scandir(self._root) as entries:
            next(entries, None)

    def _files(self) -> tuple[list[tuple[str, pathlib.Path]], list[str]]:
        """The supported files as (id, real path), and the paths that could not
        be read."""
        found: list[tuple[str, pathlib.Path]] = []
        unreadable: list[str] = []

        def on_error(err: OSError) -> None:
            unreadable.append(f"{err.filename}: {err.strerror}")

        for directory, dirs, names in os.walk(self._root, onerror=on_error):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if self._recursive else []
            for name in sorted(names):
                if name.startswith(".") or pathlib.PurePath(name).suffix.lower() not in (
                    SUPPORTED_SUFFIXES
                ):
                    continue
                link = pathlib.Path(directory, name)
                try:
                    real = link.resolve(strict=True)
                except OSError:  # a broken link, or removed since it was listed
                    continue
                if not real.is_relative_to(self._root):
                    log.warning("folder %s: %s leads outside the folder, skipped", self._root, link)
                    continue
                if real.is_file():
                    found.append((link.relative_to(self._root).as_posix(), real))
        found.sort()
        return found, unreadable


def _reader(path: pathlib.Path):
    async def read() -> bytes:
        return await asyncio.to_thread(path.read_bytes)

    return read
