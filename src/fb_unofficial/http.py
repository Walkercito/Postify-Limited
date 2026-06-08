"""Async HTTP layer around httpx with Facebook-specific error handling."""
from __future__ import annotations

from typing import Any, Literal

import httpx

from .constants import DEFAULT_TIMEOUT_SEC
from .errors import FacebookApiError
from .types import ClientConfig, FacebookErrorPayload, Step
from .user_agents import random_android_ua

Method = Literal["GET", "POST", "DELETE"]

# httpx multipart files: dict[field, (filename, content, content_type)]
Multipart = dict[str, tuple[str, bytes, str]]


def build_user_agent(ua: str | None) -> str | None:
    """Resolve the `auto` sentinel to a random UA; pass other values through."""
    if ua is None:
        return None
    if ua == "auto":
        return random_android_ua()
    return ua


def _filter_query(query: dict[str, Any] | None) -> dict[str, str] | None:
    if not query:
        return None
    return {k: str(v) for k, v in query.items() if v is not None}


async def request(
    url: str,
    *,
    method: Method = "GET",
    body: dict[str, str] | None = None,
    files: Multipart | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    user_agent: str | None = None,
    timeout: float | None = None,
    proxy: str | None = None,
    step: Step = "request",
    client: httpx.AsyncClient | None = None,
) -> Any:
    """Send a request and return parsed JSON (or raw text when not JSON).

    Raises :class:`FacebookApiError` on non-2xx responses or payloads with an
    ``error`` envelope.
    """
    hdrs: dict[str, str] = dict(headers or {})
    resolved_ua = build_user_agent(user_agent)
    if resolved_ua:
        hdrs.setdefault("User-Agent", resolved_ua)

    req_kwargs: dict[str, Any] = {
        "method": method,
        "url": url,
        "params": _filter_query(query),
        "headers": hdrs,
    }
    if method != "GET":
        if files is not None:
            req_kwargs["data"] = body or {}
            req_kwargs["files"] = files
        elif body is not None:
            req_kwargs["data"] = body

    timeout_val = timeout if timeout is not None else DEFAULT_TIMEOUT_SEC

    if client is None:
        async with httpx.AsyncClient(timeout=timeout_val, proxy=proxy) as c:
            response = await c.request(**req_kwargs)
    else:
        response = await client.request(timeout=timeout_val, **req_kwargs)

    return _parse_response(response, step)


def _parse_response(response: httpx.Response, step: Step) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FacebookApiError(
                FacebookErrorPayload(message=f"Invalid JSON: {exc}", type="ParseError"),
                step,
            ) from exc
    else:
        payload = response.text

    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        raise FacebookApiError(payload["error"], step)

    if response.status_code >= 400:
        raise FacebookApiError(
            FacebookErrorPayload(
                message=f"HTTP {response.status_code}",
                type="HttpError",
                code=response.status_code,
            ),
            step,
        )
    return payload


def config_to_request_kwargs(config: ClientConfig | None) -> dict[str, Any]:
    """Extract only the request-relevant fields from a client config."""
    if config is None:
        return {}
    out: dict[str, Any] = {}
    if config.user_agent is not None:
        out["user_agent"] = config.user_agent
    if config.timeout is not None:
        out["timeout"] = config.timeout
    if config.proxy is not None:
        out["proxy"] = config.proxy
    return out
