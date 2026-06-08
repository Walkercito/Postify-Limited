"""Cookie-native Facebook group poster (the Comet web composer, no token).

:class:`FacebookWeb` is the parallel of :class:`fb_unofficial.Facebook`: an async
context manager that posts to groups, but authenticated by a captured browser
cookie jar instead of a Graph access token. It scrapes the per-session tokens
once (:mod:`.params`), uploads any photos, builds the group mutation variables
(:mod:`.variables`), fires the GraphQL write, and classifies the reply
(:mod:`.response`). All wire literals come from :mod:`bot.constants`.

Every request carries a full desktop-Chrome header set (:data:`FB_WEB_BASE_HEADERS`
plus navigation/fetch extras): Facebook answers a bare-``User-Agent`` GET with a
400 error page that has no session tokens, so the headers are what make the home
page return the logged-in markup at all.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from bot.constants import (
    FB_WEB_API_CALLER_CLASS,
    FB_WEB_BASE_HEADERS,
    FB_WEB_DEFAULT_DOC_ID,
    FB_WEB_FETCH_HEADERS,
    FB_WEB_FIELD_CALLER_CLASS,
    FB_WEB_FIELD_DOC_ID,
    FB_WEB_FIELD_FRIENDLY_NAME,
    FB_WEB_FIELD_SERVER_TIMESTAMPS,
    FB_WEB_FIELD_UPLOAD_ID,
    FB_WEB_FIELD_UPLOAD_PROFILE_ID,
    FB_WEB_FIELD_UPLOAD_SOURCE,
    FB_WEB_FIELD_UPLOAD_WATERFALL,
    FB_WEB_FIELD_VARIABLES,
    FB_WEB_FRIENDLY_NAME_COMPOSER,
    FB_WEB_GRAPHQL_URL,
    FB_WEB_HEADER_FB_LSD,
    FB_WEB_HOME_URL,
    FB_WEB_NAVIGATION_HEADERS,
    FB_WEB_PACE_SECONDS,
    FB_WEB_PHOTO_UPLOAD_URL,
    FB_WEB_SERVER_TIMESTAMPS,
    FB_WEB_TIMEOUT_SEC,
    FB_WEB_UPLOAD_FILE_FIELD,
    FB_WEB_UPLOAD_FILE_MIME,
    FB_WEB_UPLOAD_FILE_NAME,
    FB_WEB_UPLOAD_ID,
    FB_WEB_UPLOAD_SOURCE,
    FB_WEB_UPLOAD_WATERFALL_APP,
    SESSION_COOKIE_USER_ID_NAME,
)
from bot.core.exceptions import (
    FacebookWebCheckpointError,
    FacebookWebError,
    FacebookWebRateLimitedError,
    FacebookWebSessionExpiredError,
)
from bot.facebook_web.params import SessionParams, scrape_session_params
from bot.facebook_web.response import WebPostOutcome, classify_post_response, extract_photo_id
from bot.facebook_web.variables import build_group_post_variables


class FacebookWeb:
    """Post to Facebook groups with a captured cookie jar (Comet web composer)."""

    # Seconds to wait between consecutive posts (read by the post service to pace
    # a multi-group run). Surfaced as a class attribute so the Graph adapter can
    # advertise its own (zero) cadence behind the same interface.
    pace_seconds: float = FB_WEB_PACE_SECONDS

    def __init__(
        self,
        cookies: dict[str, str],
        *,
        doc_id: str = FB_WEB_DEFAULT_DOC_ID,
        proxy: str | None = None,
        timeout: float | None = None,
    ) -> None:
        if not cookies:
            raise ValueError("session cookies are required")
        self._cookies = cookies
        self._doc_id = doc_id
        self._proxy = proxy
        self._timeout = FB_WEB_TIMEOUT_SEC if timeout is None else timeout
        self._client: httpx.AsyncClient | None = None
        self._params: SessionParams | None = None
        # Photo ids keyed by local path, so a multi-group run uploads each image
        # once and reuses the returned id across every group (see _photo_id_for).
        self._photo_ids: dict[str, str] = {}
        # Reuse is on until a write rejects a reused id; then it's disabled for the
        # rest of the session and images are uploaded fresh per group instead.
        self._reuse_enabled = True

    async def __aenter__(self) -> FacebookWeb:
        self._client = httpx.AsyncClient(
            cookies=self._cookies,
            headers=dict(FB_WEB_BASE_HEADERS),
            timeout=self._timeout,
            proxy=self._proxy,
            follow_redirects=True,
        )
        self._photo_ids = {}
        self._reuse_enabled = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._params = None
        self._photo_ids = {}
        self._reuse_enabled = True

    async def post_to_group(
        self, *, group_id: str, message: str, image_paths: list[str]
    ) -> WebPostOutcome:
        """Upload any photos, post to the group, and return the confirmed outcome.

        Photo ids are reused across groups (uploaded once). That reuse is
        *optimistic*: if the write fails with a generic error while a reused id was
        in play, the images are re-uploaded fresh once, reuse is disabled for the
        rest of the session, and the write is retried — so a Facebook that rejects a
        reused composer id self-heals into per-group uploads instead of failing
        every group after the first.
        """
        params = await self._ensure_params()
        reused = any(path in self._photo_ids for path in image_paths)
        photo_ids = [await self._photo_id_for(path) for path in image_paths]
        try:
            return await self._write_group_post(group_id, message, params, photo_ids)
        except FacebookWebError as exc:
            if not reused or not self._is_retryable_photo_failure(exc):
                raise
            fresh = await self._reupload_fresh(image_paths)
            return await self._write_group_post(group_id, message, params, fresh)

    async def _write_group_post(
        self, group_id: str, message: str, params: SessionParams, photo_ids: list[str]
    ) -> WebPostOutcome:
        """Fire the group-composer GraphQL write and classify the reply."""
        variables = build_group_post_variables(
            group_id=group_id,
            message=message,
            actor_id=params.actor_id,
            session_id=params.session_id,
            photo_ids=photo_ids,
        )
        form = params.to_form()
        form.update(
            {
                FB_WEB_FIELD_CALLER_CLASS: FB_WEB_API_CALLER_CLASS,
                FB_WEB_FIELD_FRIENDLY_NAME: FB_WEB_FRIENDLY_NAME_COMPOSER,
                FB_WEB_FIELD_VARIABLES: json.dumps(variables),
                FB_WEB_FIELD_SERVER_TIMESTAMPS: FB_WEB_SERVER_TIMESTAMPS,
                FB_WEB_FIELD_DOC_ID: self._doc_id,
            }
        )
        response = await self._require_client().post(
            FB_WEB_GRAPHQL_URL, data=form, headers=self._fetch_headers(params)
        )
        self._raise_for_status(response, leg="group post")
        return classify_post_response(response.text, group_id=group_id)

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise FacebookWebError("client is not started — use `async with FacebookWeb(...)`")
        return self._client

    @staticmethod
    def _fetch_headers(params: SessionParams) -> dict[str, str]:
        """The same-origin fetch headers for a Comet write, with the CSRF lsd token."""
        return {**FB_WEB_FETCH_HEADERS, FB_WEB_HEADER_FB_LSD: params.lsd}

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, leg: str) -> None:
        """Reject a non-2xx Comet reply as a transient block, not a logged-out session.

        Facebook answers a blocked/rate-limited request with an HTTP error page (no
        tokens, no post id). Routing it here keeps it a generic, retryable failure
        instead of misreading it as an expired session (the home GET) or an
        "unconfirmed post" (the writes).
        """
        if not response.is_success:
            raise FacebookWebError(
                f"{leg} returned HTTP {response.status_code} — Facebook may be "
                "rate-limiting or blocking this request"
            )

    async def _ensure_params(self) -> SessionParams:
        """Scrape the per-session tokens once and cache them for the session."""
        if self._params is None:
            response = await self._require_client().get(
                FB_WEB_HOME_URL, headers=FB_WEB_NAVIGATION_HEADERS
            )
            self._raise_for_status(response, leg="home page")
            self._params = scrape_session_params(
                response.text,
                actor_id_fallback=self._cookies.get(SESSION_COOKIE_USER_ID_NAME, ""),
            )
        return self._params

    async def _photo_id_for(self, image_path: str) -> str:
        """Return *image_path*'s composer photo id, uploading it only the first time.

        A run that fans one post out to N groups uploads each image *once* and
        reuses the returned id across every group — far fewer upload calls and a
        lighter footprint than re-uploading per group. The cache is per-session
        (reset on ``__aenter__``/``__aexit__``) because the ids are scoped to the
        logged-in session that produced them.

        Reuse is *optimistic*: if a later write rejects a reused id,
        :meth:`_reupload_fresh` disables reuse for the rest of the session and this
        method uploads fresh from then on (see :meth:`post_to_group`).
        """
        if self._reuse_enabled:
            cached = self._photo_ids.get(image_path)
            if cached is not None:
                return cached
        photo_id = await self._upload_photo(image_path)
        if self._reuse_enabled:
            self._photo_ids[image_path] = photo_id
        return photo_id

    async def _reupload_fresh(self, image_paths: list[str]) -> list[str]:
        """Disable composer-id reuse for the session and upload every image anew.

        Called once, the first time a write fails while a reused photo id was in
        play: Facebook may have rejected the reused id, so reuse is turned off for
        the rest of the run and each image is uploaded fresh from here on.
        """
        self._reuse_enabled = False
        self._photo_ids = {}
        return [await self._photo_id_for(path) for path in image_paths]

    @staticmethod
    def _is_retryable_photo_failure(exc: FacebookWebError) -> bool:
        """Whether *exc* is the only failure a rejected reused photo id would cause.

        A rejected composer id surfaces as a *generic* web error, so the
        re-upload-and-retry is limited to that. Rate-limit, checkpoint, and
        expired-session errors are real conditions to propagate untouched, never
        retried (retrying a rate-limit would only dig the account deeper).
        """
        return not isinstance(
            exc,
            (
                FacebookWebSessionExpiredError,
                FacebookWebRateLimitedError,
                FacebookWebCheckpointError,
            ),
        )

    async def _upload_photo(self, image_path: str) -> str:
        """Upload one local image to the composer and return its photo id."""
        params = await self._ensure_params()
        form = params.to_form()
        form.update(
            {
                FB_WEB_FIELD_UPLOAD_SOURCE: FB_WEB_UPLOAD_SOURCE,
                FB_WEB_FIELD_UPLOAD_PROFILE_ID: params.actor_id,
                FB_WEB_FIELD_UPLOAD_WATERFALL: FB_WEB_UPLOAD_WATERFALL_APP,
                FB_WEB_FIELD_UPLOAD_ID: FB_WEB_UPLOAD_ID,
            }
        )
        # Offload the blocking read so the event loop keeps serving other updates.
        buffer = await asyncio.to_thread(Path(image_path).read_bytes)
        files = {
            FB_WEB_UPLOAD_FILE_FIELD: (FB_WEB_UPLOAD_FILE_NAME, buffer, FB_WEB_UPLOAD_FILE_MIME)
        }
        response = await self._require_client().post(
            FB_WEB_PHOTO_UPLOAD_URL, data=form, files=files, headers=self._fetch_headers(params)
        )
        self._raise_for_status(response, leg="photo upload")
        photo_id = extract_photo_id(response.text)
        if photo_id is None:
            raise FacebookWebError("photo upload failed (no photo id in the response)")
        return photo_id
