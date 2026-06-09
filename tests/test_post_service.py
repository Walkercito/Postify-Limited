"""Tests for the post service (streamed publish) and the progress renderer."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

from bot.constants import (
    POST_BATCH_COOLDOWN_SEC,
    POST_BATCH_SIZE,
    POST_PACE_JITTER_SEC,
    POST_RUN_MAX_CONSECUTIVE_FAILURES,
    PostFailure,
)
from bot.core.exceptions import (
    FacebookWebError,
    FacebookWebRateLimitedError,
    FacebookWebSessionExpiredError,
)
from bot.facebook_web import WebPostOutcome
from bot.handlers.post import (
    POST_FAIL_REASONS,
    POST_PUBLISH_CANCELLED_TITLE,
    POST_PUBLISH_DONE_TITLE,
    POST_PUBLISH_TITLE,
    _render_publish,
    _report_failures,
)
from bot.services import post_service
from bot.services.post_service import GroupPostResult, PostService
from fb_unofficial import FacebookApiError, PostResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bot.core.client import Bot
    from bot.db.models.user import User

ACCESS_TOKEN = "test-token"
COOKIES = {"c_user": "100012345678901", "xs": "secret"}
GROUP_OK = "111"
GROUP_OK_2 = "222"
GROUP_FAIL = "333"
GROUP_RATE_LIMITED = "999"
GROUP_SESSION_EXPIRED = "444"
POST_URL_TEMPLATE = "https://facebook.com/groups/{target}/posts/1"
FAIL_MESSAGE = "Permission denied"
SESSION_EXPIRED_MESSAGE = "cookies are likely expired"


async def _collect(
    service: PostService,
    *,
    message: str = "hi",
    image_paths: Sequence[str] = ("a.jpg",),
    facebook_ids: Sequence[str],
    cancel_event: asyncio.Event | None = None,
) -> list[GroupPostResult]:
    """Drain the publish async generator into a list (one result per group)."""
    return [
        result
        async for result in service.publish_to_groups(
            message=message,
            image_paths=list(image_paths),
            facebook_ids=facebook_ids,
            cancel_event=cancel_event,
        )
    ]


class _FakeFacebook:
    """Stand-in for ``fb_unofficial.Facebook`` that records posts and can fail.

    Posting to :data:`GROUP_FAIL` raises a :class:`FacebookApiError`, mimicking a
    per-group Facebook rejection so partial-failure handling can be exercised.
    """

    instances: ClassVar[list[_FakeFacebook]] = []

    def __init__(
        self, access_token: str, *, proxy: str | None = None, timeout: float | None = None
    ) -> None:
        self.access_token = access_token
        self.proxy = proxy
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []
        _FakeFacebook.instances.append(self)

    async def __aenter__(self) -> _FakeFacebook:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, *, message: str, target: str, images: Sequence[str]) -> PostResult:
        self.calls.append({"message": message, "target": target, "images": list(images)})
        if target == GROUP_FAIL:
            raise FacebookApiError({"message": FAIL_MESSAGE})
        return PostResult(id="1", url=POST_URL_TEMPLATE.format(target=target))


class _FakeFacebookWeb:
    """Stand-in for the cookie-native engine, with no pacing delay between posts.

    :data:`GROUP_FAIL` raises a plain web error; :data:`GROUP_RATE_LIMITED` raises
    a rate-limit error so the run's short-circuit (skip the rest) can be checked;
    :data:`GROUP_SESSION_EXPIRED` raises the expired-cookie error.
    """

    instances: ClassVar[list[_FakeFacebookWeb]] = []
    pace_seconds: float = 0.0

    def __init__(
        self,
        cookies: dict[str, str],
        *,
        proxy: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.cookies = cookies
        self.proxy = proxy
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []
        _FakeFacebookWeb.instances.append(self)

    async def __aenter__(self) -> _FakeFacebookWeb:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post_to_group(
        self, *, group_id: str, message: str, image_paths: list[str]
    ) -> WebPostOutcome:
        self.calls.append({"message": message, "group_id": group_id, "images": list(image_paths)})
        if group_id == GROUP_RATE_LIMITED:
            raise FacebookWebRateLimitedError("slow down")
        if group_id == GROUP_SESSION_EXPIRED:
            raise FacebookWebSessionExpiredError(SESSION_EXPIRED_MESSAGE)
        if group_id == GROUP_FAIL:
            raise FacebookWebError("denied")
        return WebPostOutcome(
            post_id="1", url=POST_URL_TEMPLATE.format(target=group_id), pending=False
        )


class _RecordingReporter:
    """Captures the messages an :class:`~bot.core.errors.ErrorReporter` would send."""

    def __init__(self) -> None:
        self.delivered: list[str] = []

    async def deliver(self, text: str) -> None:
        self.delivered.append(text)


class _FakeClient:
    """Minimal stand-in for :class:`Bot` exposing just the error reporter."""

    def __init__(self) -> None:
        self.error_reporter = _RecordingReporter()


class _FakeOwner:
    """Minimal stand-in for :class:`User` for the admin-report formatter."""

    display_name = "Alice"
    telegram_id = 4242


@pytest.fixture(autouse=True)
def _patch_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeFacebook.instances.clear()
    _FakeFacebookWeb.instances.clear()
    monkeypatch.setattr(post_service, "Facebook", _FakeFacebook)
    monkeypatch.setattr(post_service, "FacebookWeb", _FakeFacebookWeb)


async def test_publish_all_succeed() -> None:
    results = await _collect(PostService(ACCESS_TOKEN), facebook_ids=[GROUP_OK, GROUP_OK_2])

    assert [result.ok for result in results] == [True, True]
    assert results[0].facebook_id == GROUP_OK
    assert results[0].url == POST_URL_TEMPLATE.format(target=GROUP_OK)
    assert results[0].error is None


async def test_publish_partial_failure() -> None:
    results = await _collect(PostService(ACCESS_TOKEN), facebook_ids=[GROUP_OK, GROUP_FAIL])

    assert results[0].ok is True
    assert results[1].ok is False
    assert results[1].url is None
    assert FAIL_MESSAGE in (results[1].error or "")
    assert results[1].failure is PostFailure.GENERIC
    # A real per-group rejection counts as attempted (so the admin hears about it).
    assert results[1].attempted is True


async def test_publish_empty_ids_posts_nothing() -> None:
    results = await _collect(PostService(ACCESS_TOKEN), facebook_ids=[])

    assert results == []
    assert _FakeFacebook.instances[-1].calls == []


async def test_access_token_and_images_reach_engine() -> None:
    await _collect(
        PostService(ACCESS_TOKEN), image_paths=["a.jpg", "b.jpg"], facebook_ids=[GROUP_OK]
    )

    engine = _FakeFacebook.instances[-1]
    assert engine.access_token == ACCESS_TOKEN
    assert engine.calls[0]["images"] == ["a.jpg", "b.jpg"]
    assert engine.calls[0]["target"] == GROUP_OK


async def test_requires_a_credential() -> None:
    with pytest.raises(ValueError, match="access token or session cookies"):
        PostService()


async def test_cookies_select_the_web_engine() -> None:
    results = await _collect(
        PostService(session_cookies=COOKIES), facebook_ids=[GROUP_OK, GROUP_OK_2]
    )

    assert [result.ok for result in results] == [True, True]
    # The web engine ran (not the Graph one) and received the cookie jar.
    assert _FakeFacebook.instances == []
    web = _FakeFacebookWeb.instances[-1]
    assert web.cookies == COOKIES
    assert web.calls[0]["images"] == ["a.jpg"]


async def test_cookies_take_precedence_over_token() -> None:
    await _collect(PostService(ACCESS_TOKEN, COOKIES), facebook_ids=[GROUP_OK])

    assert _FakeFacebookWeb.instances  # web engine chosen
    assert _FakeFacebook.instances == []  # graph engine never built


async def test_rate_limit_short_circuits_remaining_groups() -> None:
    results = await _collect(
        PostService(session_cookies=COOKIES),
        facebook_ids=[GROUP_RATE_LIMITED, GROUP_OK, GROUP_OK_2],
    )

    assert results[0].ok is False
    assert results[1].ok is False
    assert results[2].ok is False
    # Only the first group was actually attempted; the rest were skipped.
    assert len(_FakeFacebookWeb.instances[-1].calls) == 1
    assert post_service.POST_SKIPPED_RATE_LIMIT in (results[2].error or "")
    # Both the tripped group and the skipped ones carry the rate-limit category.
    assert {result.failure for result in results} == {PostFailure.RATE_LIMITED}
    # The tripped group was attempted; the skipped ones were not.
    assert [result.attempted for result in results] == [True, False, False]


async def test_expired_session_is_categorized() -> None:
    results = await _collect(
        PostService(session_cookies=COOKIES), facebook_ids=[GROUP_SESSION_EXPIRED]
    )

    assert results[0].ok is False
    assert results[0].failure is PostFailure.SESSION_EXPIRED
    # The raw engine reason is preserved (for the admin), not shown to the user.
    assert SESSION_EXPIRED_MESSAGE in (results[0].error or "")


async def test_consecutive_failures_trip_the_breaker() -> None:
    streak = [GROUP_FAIL] * POST_RUN_MAX_CONSECUTIVE_FAILURES
    results = await _collect(
        PostService(session_cookies=COOKIES),
        facebook_ids=[*streak, GROUP_OK, GROUP_OK_2],
    )

    # Only the failing streak was actually attempted; the rest were skipped.
    assert len(_FakeFacebookWeb.instances[-1].calls) == POST_RUN_MAX_CONSECUTIVE_FAILURES
    assert [result.attempted for result in results] == [True] * len(streak) + [False, False]
    assert post_service.POST_SKIPPED_CONSECUTIVE_FAILURES in (results[-1].error or "")
    assert results[-1].failure is PostFailure.STOPPED


async def test_success_resets_the_failure_streak() -> None:
    # A success right before the threshold resets the streak, so the breaker
    # never trips and every group is attempted.
    near_streak = [GROUP_FAIL] * (POST_RUN_MAX_CONSECUTIVE_FAILURES - 1)
    ids = [*near_streak, GROUP_OK, *near_streak, GROUP_OK_2]

    results = await _collect(PostService(session_cookies=COOKIES), facebook_ids=ids)

    assert len(_FakeFacebookWeb.instances[-1].calls) == len(ids)
    assert all(result.attempted for result in results)
    assert results[len(near_streak)].ok is True
    assert results[-1].ok is True


async def test_cancel_before_run_marks_all_groups_cancelled() -> None:
    cancel = asyncio.Event()
    cancel.set()

    results = await _collect(
        PostService(session_cookies=COOKIES),
        facebook_ids=[GROUP_OK, GROUP_OK_2],
        cancel_event=cancel,
    )

    assert [result.cancelled for result in results] == [True, True]
    # Cancelled groups are never attempted, so nothing was actually posted.
    assert all(not result.attempted for result in results)
    assert _FakeFacebookWeb.instances[-1].calls == []


async def test_cancel_after_first_group_stops_the_rest() -> None:
    cancel = asyncio.Event()

    service = PostService(session_cookies=COOKIES)
    results: list[GroupPostResult] = []
    async for result in service.publish_to_groups(
        message="hi",
        image_paths=["a.jpg"],
        facebook_ids=[GROUP_OK, GROUP_OK_2],
        cancel_event=cancel,
    ):
        results.append(result)
        cancel.set()  # request a stop the moment the first group resolves

    assert results[0].ok is True  # the in-flight group still finished
    assert results[1].cancelled is True  # the next group was cancelled
    assert len(_FakeFacebookWeb.instances[-1].calls) == 1


def test_inter_post_delay_first_group_is_immediate() -> None:
    # The first group never waits — the run starts publishing right away.
    assert post_service._inter_post_delay(0, 45.0) == 0.0


def test_inter_post_delay_non_pacing_engine_is_immediate() -> None:
    # base_pace <= 0 (the Graph adapter / test fakes) never waits, keeping
    # token-engine runs and the test suite fast.
    assert post_service._inter_post_delay(5, 0.0) == 0.0


def test_inter_post_delay_jitters_within_bounds() -> None:
    # A non-boundary group waits the base cadence plus a random margin, never less
    # than the base and never more than base + the jitter ceiling.
    base = 45.0
    for index in range(1, POST_BATCH_SIZE):  # 1..n-1: no batch boundary in range
        delay = post_service._inter_post_delay(index, base)
        assert base <= delay <= base + POST_PACE_JITTER_SEC


def test_inter_post_delay_adds_cooldown_on_batch_boundary() -> None:
    # Every POST_BATCH_SIZE-th group rests an extra cooldown on top of the cadence.
    base = 45.0
    delay = post_service._inter_post_delay(POST_BATCH_SIZE, base)
    floor = base + POST_BATCH_COOLDOWN_SEC
    assert floor <= delay <= floor + POST_PACE_JITTER_SEC


def test_render_publish_lists_each_group() -> None:
    results = [
        GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None),
        GroupPostResult(
            facebook_id=GROUP_FAIL, url=None, error="boom", failure=PostFailure.GENERIC
        ),
    ]
    name_by_id = {GROUP_OK: "Alpha", GROUP_FAIL: "Beta"}

    text = _render_publish(
        results, name_by_id, total=2, title=POST_PUBLISH_DONE_TITLE, in_progress_name=None
    )

    assert "✅ 1" in text  # one published in the tally header
    assert "❌ 1" in text  # one failed
    assert "2/2 grupos" in text
    assert "Alpha" in text
    assert "https://x/1" in text
    assert "Beta" in text
    # The raw engine error never leaks into the user-facing view.
    assert "boom" not in text
    assert POST_FAIL_REASONS[PostFailure.GENERIC] in text


def test_render_publish_uses_a_friendly_reason_per_category() -> None:
    results = [
        GroupPostResult(
            facebook_id=GROUP_FAIL, url=None, error="raw", failure=PostFailure.SESSION_EXPIRED
        ),
        GroupPostResult(
            facebook_id=GROUP_RATE_LIMITED, url=None, error="raw", failure=PostFailure.RATE_LIMITED
        ),
    ]
    name_by_id = {GROUP_FAIL: "Beta", GROUP_RATE_LIMITED: "Gamma"}

    text = _render_publish(
        results, name_by_id, total=2, title=POST_PUBLISH_TITLE, in_progress_name=None
    )

    assert POST_FAIL_REASONS[PostFailure.SESSION_EXPIRED] in text
    assert POST_FAIL_REASONS[PostFailure.RATE_LIMITED] in text


def test_render_publish_marks_pending_separately() -> None:
    results = [
        GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None),
        GroupPostResult(facebook_id=GROUP_OK_2, url="https://x/2", error=None, pending=True),
    ]
    name_by_id = {GROUP_OK: "Alpha", GROUP_OK_2: "Gamma"}

    text = _render_publish(
        results, name_by_id, total=2, title=POST_PUBLISH_DONE_TITLE, in_progress_name=None
    )

    assert "✅ 1" in text  # one published
    assert "⏳ 1" in text  # one pending
    # A pending post is flagged as awaiting approval, not shown as a live link.
    assert "Gamma" in text
    assert "https://x/2" not in text


def test_render_publish_shows_in_progress_and_queue() -> None:
    results = [GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None)]
    name_by_id = {GROUP_OK: "Alpha", GROUP_OK_2: "Gamma"}

    text = _render_publish(
        results, name_by_id, total=3, title=POST_PUBLISH_TITLE, in_progress_name="Gamma"
    )

    assert "1/3 grupos" in text
    assert "Alpha" in text  # the resolved group
    assert "Gamma" in text  # the group currently publishing, named
    assert "publicando" in text  # the in-progress marker
    assert "1 grupo(s) en cola" in text  # the single still-queued group


def test_render_publish_marks_cancelled_groups() -> None:
    results = [
        GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None),
        GroupPostResult(
            facebook_id=GROUP_FAIL,
            url=None,
            error=post_service.POST_CANCELLED_REASON,
            cancelled=True,
            attempted=False,
        ),
    ]
    name_by_id = {GROUP_OK: "Alpha", GROUP_FAIL: "Beta"}

    text = _render_publish(
        results, name_by_id, total=2, title=POST_PUBLISH_CANCELLED_TITLE, in_progress_name=None
    )

    assert "Alpha" in text
    assert "cancelado" in text
    # A cancelled group is collateral, not a failure, so the ❌ tally stays at zero.
    assert "❌ 0" in text


def test_render_publish_falls_back_to_id_when_unnamed() -> None:
    results = [GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None)]

    text = _render_publish(
        results, {}, total=1, title=POST_PUBLISH_DONE_TITLE, in_progress_name=None
    )

    assert GROUP_OK in text


async def test_report_failures_sends_raw_reason_to_admin() -> None:
    client = _FakeClient()
    results = [
        GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None),
        GroupPostResult(
            facebook_id=GROUP_FAIL,
            url=None,
            error=SESSION_EXPIRED_MESSAGE,
            failure=PostFailure.SESSION_EXPIRED,
        ),
    ]

    await _report_failures(
        cast("Bot", client), cast("User", _FakeOwner()), results, {GROUP_FAIL: "Beta"}
    )

    assert len(client.error_reporter.delivered) == 1
    sent = client.error_reporter.delivered[0]
    assert SESSION_EXPIRED_MESSAGE in sent  # the raw reason reaches the admin
    assert "Beta" in sent
    assert "Alice" in sent


async def test_report_failures_is_silent_when_all_succeed() -> None:
    client = _FakeClient()
    results = [GroupPostResult(facebook_id=GROUP_OK, url="https://x/1", error=None)]

    await _report_failures(cast("Bot", client), cast("User", _FakeOwner()), results, {})

    assert client.error_reporter.delivered == []


async def test_report_failures_excludes_unattempted_collateral() -> None:
    client = _FakeClient()
    results = [
        # A real failure: attempted, so it reaches the admin.
        GroupPostResult(
            facebook_id=GROUP_FAIL, url=None, error="denied", failure=PostFailure.RATE_LIMITED
        ),
        # Skipped after the rate-limit tripped: never attempted, so it is excluded.
        GroupPostResult(
            facebook_id=GROUP_OK,
            url=None,
            error=post_service.POST_SKIPPED_RATE_LIMIT,
            failure=PostFailure.RATE_LIMITED,
            attempted=False,
        ),
        # Cancelled by the user: collateral, also excluded.
        GroupPostResult(
            facebook_id=GROUP_OK_2,
            url=None,
            error=post_service.POST_CANCELLED_REASON,
            cancelled=True,
            attempted=False,
        ),
    ]

    await _report_failures(
        cast("Bot", client),
        cast("User", _FakeOwner()),
        results,
        {GROUP_FAIL: "Beta", GROUP_OK: "Alpha", GROUP_OK_2: "Gamma"},
    )

    assert len(client.error_reporter.delivered) == 1
    sent = client.error_reporter.delivered[0]
    assert "Beta" in sent  # the attempted failure is reported
    assert "Alpha" not in sent  # the rate-limit-skipped group is not
    assert "Gamma" not in sent  # the cancelled group is not
