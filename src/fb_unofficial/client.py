"""High-level async Facebook client."""

from __future__ import annotations

import asyncio
import mimetypes
import re
from pathlib import Path
from typing import Any, Final, Self

from .constants import DEFAULT_GRAPH_BASE, FB_WEB_BASE
from .errors import FacebookApiError
from .groups import fetch_group_preview
from .http import Multipart, config_to_request_kwargs, request
from .resolve import resolve_id as _resolve_id
from .types import (
    ClientConfig,
    FacebookErrorPayload,
    GroupPreview,
    PostResult,
    Session,
    Step,
    User,
    UserProfile,
)

_BASIC_PROFILE_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "name",
    "first_name",
    "last_name",
    "middle_name",
    "link",
    "picture.type(large)",
    "birthday",
    "gender",
    "locale",
    "timezone",
    "email",
)

_COUNT_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("friends", "friends_count"),
    ("groups", "groups_count"),
    ("likes", "pages_liked_count"),
)

_REMOTE_URL_RE: Final[re.Pattern[str]] = re.compile(r"^https?://", re.IGNORECASE)


def _build_post_url(post_id: str) -> str:
    owner, _, post = post_id.partition("_")
    if owner and post:
        return f"{FB_WEB_BASE}/{owner}/posts/{post}"
    return f"{FB_WEB_BASE}/{post_id}"


def _summary_count(edge: Any) -> int | None:
    if not isinstance(edge, dict):
        return None
    summary = edge.get("summary")
    if not isinstance(summary, dict):
        return None
    total = summary.get("total_count")
    return int(total) if isinstance(total, int) else None


def _picture_url(picture: Any) -> str | None:
    if not isinstance(picture, dict):
        return None
    data = picture.get("data")
    if not isinstance(data, dict):
        return None
    url = data.get("url")
    return url if isinstance(url, str) else None


def _profile_from_raw(data: dict[str, Any]) -> UserProfile:
    return UserProfile(
        id=str(data["id"]),
        name=str(data.get("name", "")),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        middle_name=data.get("middle_name"),
        link=data.get("link"),
        picture_url=_picture_url(data.get("picture")),
        birthday=data.get("birthday"),
        gender=data.get("gender"),
        locale=data.get("locale"),
        timezone=data.get("timezone"),
        email=data.get("email"),
        friends_count=_summary_count(data.get("friends")),
        groups_count=_summary_count(data.get("groups")),
        pages_liked_count=_summary_count(data.get("likes")),
        raw=data,
    )


class Facebook:
    """Async client for Facebook's Graph API using a leaked Android token."""

    def __init__(
        self,
        access_token: str,
        *,
        api_version: str | None = None,
        user_agent: str | None = "auto",
        proxy: str | None = None,
        timeout: float | None = None,
        base_url: str | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self._config = ClientConfig(
            access_token=access_token,
            api_version=api_version,
            user_agent=user_agent,
            proxy=proxy,
            timeout=timeout,
            base_url=base_url or DEFAULT_GRAPH_BASE,
        )

    @classmethod
    def from_session(cls, session: Session, **overrides: Any) -> Self:
        return cls(session.access_token, **overrides)

    @property
    def config(self) -> ClientConfig:
        return self._config

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    # public API

    async def me(self, fields: str = "id,name") -> User:
        data = await self._get("me", {"fields": fields})
        return User.model_validate(data)

    async def get_user(self, user_id: str, fields: str = "id,name") -> User:
        resolved = await self.resolve_id(user_id)
        data = await self._get(resolved, {"fields": fields})
        return User.model_validate(data)

    async def get_profile(
        self,
        user_id: str = "me",
        *,
        include_counts: bool = True,
    ) -> UserProfile:
        """Fetch a rich profile in a single Graph request.

        When ``include_counts`` is true (default), friends / groups / pages-liked
        counts are requested via field expansion. Any edge the token can't read
        comes back as ``None`` rather than raising.
        """
        target = "me" if user_id == "me" else await self.resolve_id(user_id)
        fields = list(_BASIC_PROFILE_FIELDS)
        if include_counts:
            fields += [f"{edge}.limit(0).summary(true)" for edge, _ in _COUNT_EDGES]

        data = await self._get(target, {"fields": ",".join(fields)})
        if not isinstance(data, dict):
            raise FacebookApiError(
                FacebookErrorPayload(
                    message=f"unexpected profile response: {data!r}", type="ProfileError"
                ),
                "request",
            )
        return _profile_from_raw(data)

    async def resolve_id(self, input_value: str) -> str:
        if not input_value or input_value == "me":
            return "me"
        return await _resolve_id(input_value, self._config)

    async def get_group_preview(self, url_or_id: str) -> GroupPreview | None:
        """Public group preview (name / cover) — **unauthenticated**.

        Scrapes the group's public Open Graph tags using only this client's
        ``proxy`` / ``timeout``; the access token is **not** sent. Returns
        ``None`` when no public preview is available. See
        :func:`fb_unofficial.groups.fetch_group_preview`.
        """
        ua = self._config.user_agent if self._config.user_agent not in (None, "auto") else None
        return await fetch_group_preview(
            url_or_id,
            user_agent=ua,
            proxy=self._config.proxy,
            timeout=self._config.timeout,
        )

    async def like(self, post_id: str) -> None:
        await self._post(f"{post_id}/likes", {})

    async def comment(self, post_id: str, message: str) -> dict[str, Any]:
        data = await self._post(f"{post_id}/comments", {"message": message})
        return data if isinstance(data, dict) else {"raw": data}

    async def delete(self, post_id: str) -> None:
        """Delete a post, photo, or comment you own (DELETE /{id})."""
        await request(
            self._graph_url(post_id),
            method="DELETE",
            query={"access_token": self._config.access_token},
            step="request",
            **config_to_request_kwargs(self._config),
        )

    async def post(
        self,
        *,
        message: str | None = None,
        target: str | None = None,
        image: str | None = None,
        images: list[str] | None = None,
        link: str | None = None,
    ) -> PostResult:
        if image is not None and images is not None:
            raise ValueError("post() accepts `image` or `images`, not both")

        resolved_images = [image] if image is not None else list(images or [])
        resolved_target = await self.resolve_id(target or "me")

        if resolved_images:
            return await self._post_with_images(resolved_target, resolved_images, message)
        return await self._post_text(resolved_target, message or "", link)

    # internal

    def _graph_url(self, path: str) -> str:
        version = f"/{self._config.api_version}" if self._config.api_version else ""
        base = (self._config.base_url or DEFAULT_GRAPH_BASE).rstrip("/")
        return f"{base}{version}/{path.lstrip('/')}"

    async def _get(self, path: str, query: dict[str, Any]) -> Any:
        return await request(
            self._graph_url(path),
            method="GET",
            query={"access_token": self._config.access_token, **query},
            step="request",
            **config_to_request_kwargs(self._config),
        )

    async def _post(self, path: str, body: dict[str, str], step: Step = "request") -> Any:
        return await request(
            self._graph_url(path),
            method="POST",
            body={"access_token": self._config.access_token, **body},
            step=step,
            **config_to_request_kwargs(self._config),
        )

    async def _post_text(self, target: str, message: str, link: str | None) -> PostResult:
        body: dict[str, str] = {"message": message}
        if link:
            body["link"] = link
        data = await self._post(f"{target}/feed", body, step="publish")
        return self._to_post_result(data)

    async def _post_with_images(
        self,
        target: str,
        images: list[str],
        message: str | None,
    ) -> PostResult:
        photo_ids = await asyncio.gather(*(self._upload_unpublished_photo(src) for src in images))
        body: dict[str, str] = {"message": message or ""}
        for i, photo_id in enumerate(photo_ids):
            body[f"attached_media[{i}]"] = f'{{"media_fbid":"{photo_id}"}}'
        data = await self._post(f"{target}/feed", body, step="publish")
        return self._to_post_result(data)

    async def _upload_unpublished_photo(self, image: str) -> str:
        body: dict[str, str] = {
            "access_token": self._config.access_token,
            "published": "false",
        }
        files: Multipart | None = None

        if _REMOTE_URL_RE.match(image):
            body["url"] = image
        else:
            files = self._build_local_photo_files(image)

        data = await request(
            self._graph_url("me/photos"),
            method="POST",
            body=body,
            files=files,
            step="upload",
            **config_to_request_kwargs(self._config),
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise FacebookApiError(
                FacebookErrorPayload(message="Photo upload returned no id", type="UploadError"),
                "upload",
            )
        return str(data["id"])

    @staticmethod
    def _build_local_photo_files(path: str) -> Multipart:
        file_path = Path(path)
        buffer = file_path.read_bytes()
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return {"source": (file_path.name, buffer, mime)}

    def _to_post_result(self, data: Any) -> PostResult:
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise FacebookApiError(
                FacebookErrorPayload(
                    message=f"Unexpected publish response: {data!r}", type="PublishError"
                ),
                "publish",
            )
        post_id = data["id"]
        return PostResult(id=post_id, url=_build_post_url(post_id))
