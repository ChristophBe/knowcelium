"""The watched-folder connector: the files of a directory, mounted into the
worker, become documents. Adding, changing and removing files is reflected on
the next sync."""

import asyncio
import logging
import os
import pathlib
import re
from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from ..extract import HTML_SUFFIXES, TEXT_SUFFIXES
from .model import ConnectorError, Record, Snippet
from .sdk import Connector

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = TEXT_SUFFIXES | HTML_SUFFIXES | {".pdf", ".docx"}
# mimetypes has no entry for these on every platform.
# Longest passage a live search returns.
_SNIPPET_CHARS = 1000
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


class FolderConnector(Connector[FolderConfig]):
    """Lists every supported file below `path`. The external id of a file is its
    path relative to the folder, so moving a file within it replaces the old
    document with a new one. Links that lead out of the folder are skipped."""

    config_model = FolderConfig
    # Every file is listed on each sync, so a missing file means it was removed.
    complete = True

    def __init__(self, config: FolderConfig) -> None:
        super().__init__(config)
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

    async def search(self, query: str, limit: int) -> list[Snippet]:
        """The paragraphs of the text files that contain most of the words of
        `query` (words of at least 3 letters, ignoring case), best first.
        Searching reads the files as they are now, so it also finds what has
        not been synced yet; PDF and Word files are not searched."""
        words = set(re.findall(r"\w{3,}", query.lower()))
        if not words:
            return []
        try:
            files, _ = await asyncio.to_thread(self._files)
        except OSError as err:
            raise ConnectorError(f"cannot read the folder {self._root}: {err}") from err
        found: list[tuple[int, Snippet]] = []
        for relative, path in files:
            if pathlib.PurePath(relative).suffix.lower() not in TEXT_SUFFIXES | HTML_SUFFIXES:
                continue
            try:
                text = (await asyncio.to_thread(path.read_bytes)).decode("utf-8", "replace")
            except OSError:
                continue  # removed or unreadable since it was listed
            for paragraph in re.split(r"\n\s*\n", text):
                matched = sum(1 for w in words if w in paragraph.lower())
                if matched:
                    found.append(
                        (
                            matched,
                            Snippet(
                                text=paragraph.strip()[:_SNIPPET_CHARS],
                                source_url=(self._root / relative).as_uri(),
                                title=pathlib.PurePosixPath(relative).stem,
                                external_id=relative,
                            ),
                        )
                    )
        found.sort(key=lambda hit: hit[0], reverse=True)
        return [snippet for _, snippet in found[:limit]]

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
