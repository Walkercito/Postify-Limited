"""Resolve usernames, URLs, and share links to numeric Facebook ids."""
from __future__ import annotations

import re
from typing import Final
from urllib.parse import parse_qs, urlparse

import httpx

from .constants import DEFAULT_GRAPH_BASE, DEFAULT_TIMEOUT_SEC
from .errors import FacebookResolveError
from .http import build_user_agent, config_to_request_kwargs, request
from .types import ClientConfig

_NUMERIC_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$")
_GROUP_PATH_RE: Final[re.Pattern[str]] = re.compile(r"/groups/(\d+)")
_PROFILE_ID_RE: Final[re.Pattern[str]] = re.compile(r"/profile\.php")
_USERNAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9.]{1,50}$")


async def resolve_id(input_value: str, config: ClientConfig) -> str:
    """Return a numeric Facebook id for a username, URL, or share link."""
    value = input_value.strip()
    if not value:
        raise FacebookResolveError("empty input")

    if _NUMERIC_RE.match(value):
        return value

    if value.startswith(("http://", "https://")):
        return await _resolve_url(value, config)

    if _USERNAME_RE.match(value):
        return await _lookup_username(value, config)

    raise FacebookResolveError(f"can't resolve {value!r}")


def _extract_numeric_id(url: str) -> str | None:
    parsed = urlparse(url)
    group_match = _GROUP_PATH_RE.search(parsed.path)
    if group_match:
        return group_match.group(1)
    if _PROFILE_ID_RE.search(parsed.path):
        ids = parse_qs(parsed.query).get("id")
        if ids and _NUMERIC_RE.match(ids[0]):
            return ids[0]
    return None


async def _resolve_url(url: str, config: ClientConfig) -> str:
    direct = _extract_numeric_id(url)
    if direct is not None:
        return direct

    final = await _follow_redirect(url, config)
    if final == url:
        raise FacebookResolveError(f"no redirect from {url}")

    resolved = _extract_numeric_id(final)
    if resolved is not None:
        return resolved
    raise FacebookResolveError(f"could not extract id from {final!r}")


async def _follow_redirect(url: str, config: ClientConfig) -> str:
    ua = build_user_agent(config.user_agent) or ""
    timeout = config.timeout if config.timeout is not None else DEFAULT_TIMEOUT_SEC
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        proxy=config.proxy,
        headers={"User-Agent": ua} if ua else {},
    ) as client:
        response = await client.head(url)
        return str(response.url)


async def _lookup_username(username: str, config: ClientConfig) -> str:
    base = (config.base_url or DEFAULT_GRAPH_BASE).rstrip("/")
    version = f"/{config.api_version}" if config.api_version else ""
    data = await request(
        f"{base}{version}/{username}",
        query={"fields": "id", "access_token": config.access_token},
        step="resolve",
        **config_to_request_kwargs(config),
    )
    if isinstance(data, dict) and isinstance(data.get("id"), str):
        return data["id"]
    raise FacebookResolveError(f"username {username!r} did not return an id")
