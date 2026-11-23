"""What the two showcase connectors share: settings and the paginated JSON API of the
mock systems in `examples/showcase`."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .model import ConnectorError


class ShowcaseConfig(BaseModel):
    """Settings under `settings:` of a showcase connector."""

    model_config = ConfigDict(extra="forbid")

    # The mock system, as the worker reaches it (http://showcase-engineering:8091 in compose).
    base_url: str
    # Records per request; the mock systems allow 1 to 100.
    page_size: int = Field(default=50, ge=1, le=100)
    # Seconds a request may take.
    timeout_seconds: float = Field(default=10, gt=0, le=120)

    @field_validator("base_url")
    @classmethod
    def _is_http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        try:
            parts.port  # noqa: B018 (raises for a port that is not a number)
        except ValueError:
            raise ValueError(f"{value!r} has an invalid port") from None
        if (
            parts.scheme not in ("http", "https")
            or not parts.netloc
            or parts.query
            or parts.fragment
        ):
            raise ValueError(f"{value!r} is not an http(s) URL such as http://host:8091")
        return value.rstrip("/")


class ShowcaseClient:
    """Reads the list and search endpoints of a mock system."""

    def __init__(self, config: ShowcaseConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = config.base_url
        self._page_size = config.page_size
        self._timeout = config.timeout_seconds
        self._transport = transport

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            # One client per request: a connector may be used across many syncs.
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self._timeout, transport=self._transport
            ) as http:
                response = await http.get(path, params=params)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as err:
            code = err.response.status_code
            hint = "; check base_url" if code == 404 else ""
            raise ConnectorError(f"{self.base_url}{path} answered {code}{hint}") from err
        except (httpx.HTTPError, ValueError) as err:
            raise ConnectorError(f"cannot read {self.base_url}{path}: {err}") from err
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise ConnectorError(f"{self.base_url}{path} did not answer a page of items")
        return body

    async def records(self, path: str, since: datetime | None) -> AsyncIterator[dict[str, Any]]:
        """Every record of a list endpoint, following `next_offset`. `since` limits them to
        those updated at or after it."""
        params: dict[str, Any] = {"limit": self._page_size}
        if since is not None:
            params["updated_since"] = since.astimezone(UTC).isoformat()
        offset: int | None = 0
        while offset is not None:
            body = await self.get(path, {**params, "offset": offset})
            previous, offset = offset, body.get("next_offset")
            if offset is not None and (not body["items"] or offset <= previous):
                raise ConnectorError(f"{self.base_url}{path} paged without making progress")
            for item in body["items"]:
                yield item


def text(value: object) -> str:
    """A metadata value: empty for missing data."""
    return "" if value is None else str(value)
