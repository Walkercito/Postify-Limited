"""Tests for the cookie-native web posting engine (``bot.facebook_web``).

Covers the four pure pieces — session-param scrape, mutation-variable build,
response classification, and the cookie codec — plus an end-to-end pass through
:class:`FacebookWeb` over a mocked httpx transport (home GET → photo upload →
GraphQL write), so the orchestration that glues them is exercised without a
real network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from bot.constants import (
    FB_WEB_BASE_HEADERS,
    FB_WEB_FETCH_HEADERS,
    FB_WEB_FIELD_AV,
    FB_WEB_FIELD_DTSG,
    FB_WEB_FIELD_JAZOEST,
    FB_WEB_FIELD_LSD,
    FB_WEB_FIELD_REV,
    FB_WEB_FIELD_SPIN_R,
    FB_WEB_FIELD_USER,
    FB_WEB_NAVIGATION_HEADERS,
    FB_WEB_ORIGIN,
    FB_WEB_PENDING_POSTS_MARKER,
    FB_WEB_PHOTO_UPLOAD_URL,
    FB_WEB_RESTRICTED_NEEDLES,
    FB_WEB_UPLOAD_ERROR_SNIPPET_MAX_LENGTH,
)
from bot.core.exceptions import (
    FacebookWebCheckpointError,
    FacebookWebError,
    FacebookWebRateLimitedError,
    FacebookWebSessionExpiredError,
)
from bot.facebook_web import (
    FacebookWeb,
    build_group_post_variables,
    classify_post_response,
    classify_upload_response,
    decode_cookies,
    encode_cookies,
    extract_group_name,
    extract_photo_id,
    is_blocked_page,
    scrape_session_params,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

ACTOR_ID = "100012345678901"
DTSG = "DTSG:abc123"
JAZOEST = "22334"
LSD = "LSD-xyz"
SESSION_ID = "sess-9988"
GROUP_ID = "778899"
PHOTO_ID = "554433221100"
POST_ID = "112233445566"

# A logged-in home page embeds every token as a JSON fragment; this carries one
# of each the scraper looks for.
HOME_HTML = (
    f'{{"actorID":"{ACTOR_ID}"}},'
    f'"haste_session":"HASTE_77",'
    f'"connectionClass":"EXCELLENT",'
    f'"__spin_r":987654,"__spin_b":"trunk","__spin_t":1700000000,'
    f'"hsi":"HSI_42",'
    f'"sessionID":"{SESSION_ID}",'
    f'["DTSGInitialData",[],{{"token":"{DTSG}"}}],'
    f'"jazoest=' + JAZOEST + '",'
    f'["LSD",[],{{"token":"{LSD}"}}]'
).replace("{LSD}", LSD)

# The CSRF triplet without the actorID marker — exercises the c_user fallback:
# the actor id is already known from the cookie jar, so a shifted page that omits
# actorID is not a logged-out page.
HOME_HTML_NO_ACTOR = (
    f'["DTSGInitialData",[],{{"token":"{DTSG}"}}],'
    f'"jazoest={JAZOEST}",'
    f'["LSD",[],{{"token":"{LSD}"}}]'
)


# --------------------------------------------------------------------------- #
# Session-param scrape.                                                          #
# --------------------------------------------------------------------------- #
def test_scrape_session_params_lifts_every_token() -> None:
    params = scrape_session_params(HOME_HTML)

    assert params.actor_id == ACTOR_ID
    assert params.fb_dtsg == DTSG
    assert params.jazoest == JAZOEST
    assert params.lsd == LSD
    assert params.session_id == SESSION_ID
    assert params.haste_session == "HASTE_77"
    assert params.connection_class == "EXCELLENT"
    assert params.spin_r == "987654"


def test_scrape_session_params_missing_token_raises() -> None:
    # A logged-out page has no DTSG/LSD triplet — flagged as an expired session.
    with pytest.raises(FacebookWebSessionExpiredError):
        scrape_session_params('"actorID":"123"')


def test_scrape_session_params_falls_back_to_c_user_actor_id() -> None:
    # The page markup omits actorID but the CSRF triplet is present; the c_user
    # cookie value supplies the actor id, so this is a valid (not expired) session.
    params = scrape_session_params(HOME_HTML_NO_ACTOR, actor_id_fallback="123")

    assert params.actor_id == "123"
    assert params.fb_dtsg == DTSG
    assert params.jazoest == JAZOEST
    assert params.lsd == LSD


def test_to_form_maps_fields_to_tokens() -> None:
    form = scrape_session_params(HOME_HTML).to_form()

    assert form[FB_WEB_FIELD_AV] == ACTOR_ID
    assert form[FB_WEB_FIELD_USER] == ACTOR_ID
    assert form[FB_WEB_FIELD_DTSG] == DTSG
    assert form[FB_WEB_FIELD_JAZOEST] == JAZOEST
    assert form[FB_WEB_FIELD_LSD] == LSD
    # __rev and __spin_r carry the same revision number.
    assert form[FB_WEB_FIELD_REV] == form[FB_WEB_FIELD_SPIN_R] == "987654"


# --------------------------------------------------------------------------- #
# Mutation-variable build.                                                       #
# --------------------------------------------------------------------------- #
def test_build_variables_maps_photo_ids_to_attachments() -> None:
    variables = build_group_post_variables(
        group_id=GROUP_ID,
        message="hello",
        actor_id=ACTOR_ID,
        session_id=SESSION_ID,
        photo_ids=["1", "2"],
    )

    payload = cast(dict[str, object], variables["input"])
    assert payload["attachments"] == [{"photo": {"id": "1"}}, {"photo": {"id": "2"}}]
    assert payload["message"] == {"ranges": [], "text": "hello"}
    assert payload["audience"] == {"to_id": GROUP_ID}
    assert payload["actor_id"] == ACTOR_ID
    assert payload["logging"] == {"composer_session_id": SESSION_ID}
    assert variables["isGroup"] is True


def test_build_variables_text_only_has_no_attachments() -> None:
    variables = build_group_post_variables(
        group_id=GROUP_ID,
        message="text",
        actor_id=ACTOR_ID,
        session_id=SESSION_ID,
        photo_ids=[],
    )

    payload = cast(dict[str, object], variables["input"])
    assert payload["attachments"] == []


# --------------------------------------------------------------------------- #
# Response classification.                                                       #
# --------------------------------------------------------------------------- #
def test_classify_confirms_post_id() -> None:
    outcome = classify_post_response(f'{{"post_id":"{POST_ID}"}}', group_id=GROUP_ID)

    assert outcome.post_id == POST_ID
    assert outcome.pending is False
    assert GROUP_ID in outcome.url
    assert POST_ID in outcome.url


def test_classify_flags_pending_post() -> None:
    body = f'{{"post_id":"{POST_ID}","url":"/{FB_WEB_PENDING_POSTS_MARKER}/{POST_ID}/"}}'

    outcome = classify_post_response(body, group_id=GROUP_ID)

    assert outcome.pending is True
    assert FB_WEB_PENDING_POSTS_MARKER in outcome.url


def test_classify_strips_hijack_prefix_and_escapes() -> None:
    # An anti-hijack prefix plus escaped quotes must not hide a real id.
    body = f'for (;;);{{\\"post_id\\":\\"{POST_ID}\\"}}'

    outcome = classify_post_response(body, group_id=GROUP_ID)

    assert outcome.post_id == POST_ID


def test_classify_ignores_too_short_id() -> None:
    # Fewer than the minimum digits is a feedback counter, not a story id.
    with pytest.raises(FacebookWebError):
        classify_post_response('{"post_id":"123"}', group_id=GROUP_ID)


def test_classify_rate_limit_needle_raises() -> None:
    with pytest.raises(FacebookWebRateLimitedError):
        classify_post_response('{"error":"We limit how often you can post"}', group_id=GROUP_ID)


def test_classify_checkpoint_needle_raises() -> None:
    with pytest.raises(FacebookWebCheckpointError):
        classify_post_response('{"redirect":"/checkpoint/123/"}', group_id=GROUP_ID)


def test_classify_unconfirmed_raises_plain_error() -> None:
    with pytest.raises(FacebookWebError):
        classify_post_response('{"data":{}}', group_id=GROUP_ID)


def test_extract_photo_id_reads_camel_and_snake_keys() -> None:
    assert extract_photo_id(f'{{"photoID":"{PHOTO_ID}"}}') == PHOTO_ID
    assert extract_photo_id(f'{{"photo_id":"{PHOTO_ID}"}}') == PHOTO_ID
    assert extract_photo_id('{"nothing":"here"}') is None


def test_classify_upload_returns_photo_id() -> None:
    assert classify_upload_response(f'{{"photoID":"{PHOTO_ID}"}}') == PHOTO_ID


def test_classify_upload_rate_limit_needle_raises() -> None:
    with pytest.raises(FacebookWebRateLimitedError):
        classify_upload_response('{"error":"We limit how often you can post"}')


def test_classify_upload_checkpoint_needle_raises() -> None:
    with pytest.raises(FacebookWebCheckpointError):
        classify_upload_response('{"redirect":"/checkpoint/123/"}')


def test_classify_upload_unconfirmed_quotes_a_clipped_snippet() -> None:
    padding = "x" * (FB_WEB_UPLOAD_ERROR_SNIPPET_MAX_LENGTH * 2)
    body = '{"data":\n  "rejected"}' + padding

    with pytest.raises(FacebookWebError) as excinfo:
        classify_upload_response(body)

    message = str(excinfo.value)
    assert '{"data": "rejected"}' in message  # whitespace collapsed into one line
    assert padding not in message  # the body is clipped, never echoed in full


# --------------------------------------------------------------------------- #
# Cookie codec.                                                                  #
# --------------------------------------------------------------------------- #
def test_cookie_codec_round_trips() -> None:
    jar = {"c_user": ACTOR_ID, "xs": "secret"}

    assert decode_cookies(encode_cookies(jar)) == jar


def test_encode_cookies_none_and_empty() -> None:
    assert encode_cookies(None) is None
    assert encode_cookies({}) is None


def test_decode_cookies_degrades_malformed_to_none() -> None:
    assert decode_cookies(None) is None
    assert decode_cookies("not json") is None
    assert decode_cookies("[]") is None  # a list is not a cookie map
    assert decode_cookies('{"a":""}') is None  # empty values filtered out


# --------------------------------------------------------------------------- #
# End-to-end over a mocked transport.                                           #
# --------------------------------------------------------------------------- #
def _handler(request: httpx.Request) -> httpx.Response:
    """Answer the three calls a post makes: home GET, photo upload, GraphQL write."""
    if request.method == "GET":
        return httpx.Response(200, text=HOME_HTML)
    if FB_WEB_PHOTO_UPLOAD_URL in str(request.url):
        return httpx.Response(200, text=f'{{"photoID":"{PHOTO_ID}"}}')
    return httpx.Response(200, text=f'{{"post_id":"{POST_ID}"}}')


@pytest.fixture
def patched_httpx(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Route every :class:`httpx.AsyncClient` through an in-memory mock transport."""
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)  # a mock transport supersedes any proxy
        return real_client(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    yield


@pytest.mark.usefixtures("patched_httpx")
async def test_post_to_group_uploads_then_posts(tmp_path: Path) -> None:
    image = tmp_path / "pic.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    async with FacebookWeb({"c_user": ACTOR_ID, "xs": "secret"}) as web:
        outcome = await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[str(image)])

    assert outcome.post_id == POST_ID
    assert outcome.pending is False
    assert GROUP_ID in outcome.url


@pytest.mark.usefixtures("patched_httpx")
async def test_post_to_group_text_only_skips_upload() -> None:
    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        outcome = await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[])

    assert outcome.post_id == POST_ID


async def test_same_photo_uploads_once_across_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The same image fanned out to many groups must be uploaded only once: the
    # composer photo id is cached per session and reused on every later write, so
    # 80+ groups cost one upload, not eighty. Posting one image to two groups must
    # therefore produce exactly one upload request (and two GraphQL writes).
    image = tmp_path / "pic.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    captured: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if request.method == "GET":
                return httpx.Response(200, text=HOME_HTML)
            if FB_WEB_PHOTO_UPLOAD_URL in str(request.url):
                return httpx.Response(200, text=f'{{"photoID":"{PHOTO_ID}"}}')
            return httpx.Response(200, text=f'{{"post_id":"{POST_ID}"}}')

        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    path = str(image)
    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        await web.post_to_group(group_id="g1", message="hi", image_paths=[path])
        await web.post_to_group(group_id="g2", message="hi", image_paths=[path])

    uploads = [r for r in captured if FB_WEB_PHOTO_UPLOAD_URL in str(r.url)]
    assert len(uploads) == 1


async def test_rejected_reused_photo_id_reuploads_and_disables_reuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # If Facebook rejects a reused composer id, the engine self-heals: the second
    # group's write (which reuses the id) fails generically, so the image is
    # re-uploaded fresh and the write retried — and reuse stays off, so the third
    # group uploads fresh too. Net: every group still succeeds; reuse never wedges
    # the run after the first group.
    image = tmp_path / "pic.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    captured: list[httpx.Request] = []
    writes = 0
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal writes
            captured.append(request)
            if request.method == "GET":
                return httpx.Response(200, text=HOME_HTML)
            if FB_WEB_PHOTO_UPLOAD_URL in str(request.url):
                return httpx.Response(200, text=f'{{"photoID":"{PHOTO_ID}"}}')
            writes += 1
            if writes == 2:  # the reused-id write is rejected (no post id)
                return httpx.Response(200, text='{"data":{}}')
            return httpx.Response(200, text=f'{{"post_id":"{POST_ID}"}}')

        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    path = str(image)
    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        first = await web.post_to_group(group_id="g1", message="hi", image_paths=[path])
        second = await web.post_to_group(group_id="g2", message="hi", image_paths=[path])
        third = await web.post_to_group(group_id="g3", message="hi", image_paths=[path])

    assert first.post_id == second.post_id == third.post_id == POST_ID
    uploads = [r for r in captured if FB_WEB_PHOTO_UPLOAD_URL in str(r.url)]
    # One upload for g1, one for the g2 self-heal, one for g3 (reuse now off) = 3.
    assert len(uploads) == 3
    assert writes == 4  # g1 ok, g2 reject, g2 retry ok, g3 ok


def test_facebook_web_requires_cookies() -> None:
    with pytest.raises(ValueError, match="cookies"):
        FacebookWeb({})


async def test_post_to_group_without_context_manager_raises() -> None:
    web = FacebookWeb({"c_user": ACTOR_ID})

    with pytest.raises(FacebookWebError):
        await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[])


# --------------------------------------------------------------------------- #
# Browser headers + home-status guard.                                          #
# --------------------------------------------------------------------------- #
def test_web_header_sets_omit_accept_encoding() -> None:
    # Advertising a codec httpx can't decode (e.g. brotli) yields an unreadable body
    # that reads as "no tokens" and re-triggers the original bug; the engine must
    # never pin Accept-Encoding itself — httpx negotiates only what it can decode.
    for headers in (FB_WEB_BASE_HEADERS, FB_WEB_NAVIGATION_HEADERS, FB_WEB_FETCH_HEADERS):
        assert not any(key.lower() == "accept-encoding" for key in headers)


async def test_post_sends_browser_navigation_and_fetch_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bare User-Agent gets a 400 from FB; assert the real-browser fingerprint is
    # present — navigation metadata on the home GET, fetch metadata + the CSRF lsd
    # header on the write.
    captured: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if request.method == "GET":
                return httpx.Response(200, text=HOME_HTML)
            return httpx.Response(200, text=f'{{"post_id":"{POST_ID}"}}')

        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[])

    get_req = next(r for r in captured if r.method == "GET")
    post_req = next(r for r in captured if r.method == "POST")
    assert get_req.headers["user-agent"].startswith("Mozilla/5.0")
    assert get_req.headers["sec-ch-ua-platform"] == '"Windows"'
    assert get_req.headers["sec-fetch-mode"] == "navigate"
    assert post_req.headers["sec-fetch-mode"] == "cors"
    assert post_req.headers["origin"] == FB_WEB_ORIGIN
    assert post_req.headers["x-fb-lsd"] == LSD


async def test_upload_post_carries_fetch_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The photo upload hits a different host (upload.facebook.com); assert it still
    # carries the same fetch headers + CSRF lsd header the write needs — this leg
    # has no live coverage, so the header contract is locked here.
    image = tmp_path / "pic.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    captured: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if request.method == "GET":
                return httpx.Response(200, text=HOME_HTML)
            if FB_WEB_PHOTO_UPLOAD_URL in str(request.url):
                return httpx.Response(200, text=f'{{"photoID":"{PHOTO_ID}"}}')
            return httpx.Response(200, text=f'{{"post_id":"{POST_ID}"}}')

        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[str(image)])

    upload_req = next(r for r in captured if FB_WEB_PHOTO_UPLOAD_URL in str(r.url))
    assert upload_req.headers["origin"] == FB_WEB_ORIGIN
    assert upload_req.headers["sec-fetch-mode"] == "cors"
    assert upload_req.headers["x-fb-lsd"] == LSD


# --------------------------------------------------------------------------- #
# Group-name lift from the logged-in group page.                                #
# --------------------------------------------------------------------------- #
# A logged-in group page carries the display name in the HTML <title>; the entity
# escape + locale suffix exercise the unescape and the suffix strip.
GROUP_PAGE_HTML = "<html><head><title>Aqu&iacute; S&iacute; Compro - Facebook</title></head></html>"


def test_extract_group_name_reads_title_strips_suffix() -> None:
    assert extract_group_name("<title>Rodas Cienfuegos | Facebook</title>") == "Rodas Cienfuegos"


def test_extract_group_name_unescapes_entities() -> None:
    assert extract_group_name(GROUP_PAGE_HTML) == "Aquí Sí Compro"


def test_extract_group_name_none_without_title() -> None:
    assert extract_group_name("<html><body>no title element here</body></html>") is None


def test_extract_group_name_none_on_logged_out_placeholder() -> None:
    # An expired session lands on the login wall, whose title is a bare placeholder;
    # treating it as "no name" lets the caller fall back to the public scrape.
    assert extract_group_name("<title>Facebook</title>") is None
    assert extract_group_name("<title>Log in to Facebook</title>") is None


async def test_fetch_group_name_lifts_title_from_group_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The authenticated client GETs the group page with navigation headers and lifts
    # the name from its <title>; lock the URL (carries the group id) and that header.
    captured: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text=GROUP_PAGE_HTML)

        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        name = await web.fetch_group_name(GROUP_ID)

    assert name == "Aquí Sí Compro"
    request = captured[0]
    assert request.method == "GET"
    assert GROUP_ID in str(request.url)
    assert request.headers["sec-fetch-mode"] == "navigate"


async def test_fetch_group_name_error_status_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-2xx on the group page (block / gone) surfaces as a generic web error, so
    # the caller swallows it and falls back to the public scrape rather than crash.
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)
        return real_client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(404, text="gone")),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        with pytest.raises(FacebookWebError):
            await web.fetch_group_name(GROUP_ID)


# A checkpoint or account-restriction wall answers HTTP 200 with its own <title>;
# this one carries the restricted needle as the page title (what would be stored).
BLOCKED_PAGE_HTML = (
    f"<html><head><title>{FB_WEB_RESTRICTED_NEEDLES[0]} | Facebook</title></head></html>"
)

# A genuine logged-in group page is packed with benign markup — including
# JSON-escaped \/checkpoint\/ links in its scripts. is_blocked_page must ignore
# the body entirely (keying only off the final URL + <title>), so this real page
# at the group URL is never mistaken for a wall.
REAL_PAGE_WITH_CHECKPOINT_MARKUP = (
    "<!DOCTYPE html><html><head>"
    "<title>Revolico Aguada de Pasajeros</title></head><body>"
    '<script>{"uri":"https:\\/\\/web.facebook.com\\/checkpoint\\/?next=foo"}</script>'
    "</body></html>"
)


def test_is_blocked_page_detects_checkpoint_in_url() -> None:
    # A checkpoint interstitial redirects to a /checkpoint/ URL — caught via the URL.
    assert is_blocked_page("https://web.facebook.com/checkpoint/12345/", "<title>Facebook</title>")


def test_is_blocked_page_detects_restriction_in_title() -> None:
    # An account-restriction wall keeps the group URL but its <title> is the wall's,
    # carrying the restricted needle — caught via the title, not a body scan.
    assert is_blocked_page("https://web.facebook.com/groups/778899/", BLOCKED_PAGE_HTML)


def test_is_blocked_page_false_for_a_real_group_page() -> None:
    # A genuine logged-in group page is not a wall, so the title may be lifted.
    assert not is_blocked_page("https://web.facebook.com/groups/778899/", GROUP_PAGE_HTML)


def test_is_blocked_page_false_when_body_has_escaped_checkpoint_markup() -> None:
    # Regression: a real group page embeds escaped \/checkpoint\/ links throughout
    # its scripts. Un-escaping and scanning the body would flag every real page as a
    # checkpoint wall; keying only off the final URL + <title> must not.
    assert not is_blocked_page(
        "https://web.facebook.com/groups/778899/", REAL_PAGE_WITH_CHECKPOINT_MARKUP
    )


async def test_fetch_group_name_none_on_blocked_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A checkpoint/restriction wall answers 200 with its own <title>; fetch_group_name
    # must return None (so the caller falls back to the public scrape) instead of
    # storing the wall's title as the authenticated group name.
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)
        return real_client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(200, text=BLOCKED_PAGE_HTML)),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        assert await web.fetch_group_name(GROUP_ID) is None


async def test_home_error_status_raises_generic_not_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FB's bare-UA rejection is a 400 error page, not a logged-out body: it must
    # surface as a transient/generic failure (retry), never as "session expired".
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)
        return real_client(
            transport=httpx.MockTransport(
                lambda _req: httpx.Response(400, text="<html>Error</html>")
            ),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        with pytest.raises(FacebookWebError) as exc_info:
            await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[])
    assert not isinstance(exc_info.value, FacebookWebSessionExpiredError)


async def test_write_error_status_raises_generic_not_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-2xx on the GraphQL write (an HTTP-level block) must surface as a generic
    # retryable failure — not the misleading "session expired" or "unconfirmed post".
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("proxy", None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, text=HOME_HTML)
            return httpx.Response(429, text="<html>blocked</html>")

        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async with FacebookWeb({"c_user": ACTOR_ID}) as web:
        with pytest.raises(FacebookWebError) as exc_info:
            await web.post_to_group(group_id=GROUP_ID, message="hi", image_paths=[])
    assert not isinstance(exc_info.value, FacebookWebSessionExpiredError)
