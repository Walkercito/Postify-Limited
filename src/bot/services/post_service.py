"""Publish a composed post to a user's Facebook groups.

Orchestrates *one of two* interchangeable posting engines behind a single
interface: the Graph ``fb_unofficial`` engine (driven by an ``access_token``) or
the cookie-native :class:`~bot.facebook_web.FacebookWeb` engine (driven by a
captured cookie jar). The caller passes whichever credential the account holds;
cookies win when both are present, since the cookie path exists precisely for
accounts the token path can no longer serve.

Each target group is posted to sequentially — safer for a single account than a
concurrent burst — paced by the engine's ``pace_seconds`` between writes. The run
is exposed as an async generator that yields one :class:`GroupPostResult` per
group *as it resolves*, so the caller can stream live progress. A detected
rate-limit short-circuits the run (remaining groups reported as skipped rather
than pushed deeper into the limit), and so does a streak of consecutive
failures — when every write starts failing, the cause is account-wide and the
remaining groups would only burn against it; an optional ``cancel_event`` lets the caller
stop cooperatively — the in-flight group finishes, the rest are marked cancelled,
and the inter-group wait is interrupted immediately. Expected Facebook failures
are captured per group (with a :class:`~bot.constants.PostFailure` category for
the user-facing line and the raw reason for the admin); anything unexpected
propagates to the ``observed`` wrapper.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bot.constants import (
    POST_BATCH_COOLDOWN_SEC,
    POST_BATCH_SIZE,
    POST_CANCELLED_REASON,
    POST_PACE_JITTER_SEC,
    POST_RUN_MAX_CONSECUTIVE_FAILURES,
    POST_SKIPPED_CONSECUTIVE_FAILURES,
    POST_SKIPPED_DAILY_CAP,
    POST_SKIPPED_RATE_LIMIT,
    PostFailure,
)
from bot.core.exceptions import (
    FacebookWebCheckpointError,
    FacebookWebError,
    FacebookWebRateLimitedError,
    FacebookWebSessionExpiredError,
)
from bot.facebook_web import FacebookWeb, WebPostOutcome
from fb_unofficial import Facebook, FacebookError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


@dataclass(frozen=True, slots=True)
class GroupPostResult:
    """Outcome of publishing to one group: a URL on success, else an error.

    ``pending`` marks a success Facebook has queued for group-admin approval —
    accepted by Facebook, but not yet visible in the group. On failure, ``error``
    holds the raw engine reason (for the admin) and ``failure`` the category the
    user-facing summary renders into a friendly, actionable line. ``cancelled``
    flags a group the run never reached because the user stopped it; ``attempted``
    is ``False`` for those and for the groups skipped after a breaker trips (a
    rate limit or a streak of consecutive failures), so the admin report can
    exclude collateral that was never actually tried.
    """

    facebook_id: str
    url: str | None
    error: str | None
    pending: bool = False
    failure: PostFailure | None = None
    cancelled: bool = False
    attempted: bool = True

    @property
    def ok(self) -> bool:
        """Whether the post to this group succeeded."""
        return self.url is not None


@dataclass(slots=True)
class _RunState:
    """Mutable per-run flags that latch the loop into a terminal mode."""

    rate_limited: bool = False
    cancelled: bool = False
    cap_reached: bool = False
    failure_streak: int = 0

    @property
    def broken(self) -> bool:
        """Whether the consecutive-failure breaker has tripped."""
        return self.failure_streak >= POST_RUN_MAX_CONSECUTIVE_FAILURES

    @property
    def stopped(self) -> bool:
        """Whether the remaining groups should no longer be attempted."""
        return self.rate_limited or self.cancelled or self.cap_reached or self.broken

    def record(self, result: GroupPostResult) -> None:
        """Advance the failure streak with an attempted result (success resets it)."""
        self.failure_streak = 0 if result.ok else self.failure_streak + 1


@dataclass(slots=True)
class _PostJob:
    """The loop-invariant inputs of a run: the engine, content, and cancel hook.

    ``remaining_cap`` is the account's rolling daily-cap budget for this run: once
    that many groups have been reached the cap latches and the rest are skipped.
    ``None`` means the run is uncapped.
    """

    poster: FacebookWeb | _GraphPoster
    message: str
    paths: list[str]
    cancel_event: asyncio.Event | None
    remaining_cap: int | None = None


def _cancel_requested(cancel_event: asyncio.Event | None) -> bool:
    """Whether a cooperative-stop has been requested for this run."""
    return cancel_event is not None and cancel_event.is_set()


async def _wait_or_cancel(seconds: float, cancel_event: asyncio.Event | None) -> bool:
    """Pace between posts, returning early ``True`` if cancelled during the wait."""
    if cancel_event is None:
        await asyncio.sleep(seconds)
        return False
    try:
        await asyncio.wait_for(cancel_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


def _inter_post_delay(index: int, base_pace: float) -> float:
    """Seconds to wait before posting to the group at *index* (0 means no wait).

    The first group (``index == 0``) and engines that don't pace (``base_pace <=
    0`` — the Graph adapter and the test fakes) return 0, so those runs stay
    immediate. Otherwise the base cadence is jittered by a random margin (up to
    :data:`~bot.constants.POST_PACE_JITTER_SEC`) so the rhythm isn't a fixed,
    fingerprintable metronome, and every :data:`~bot.constants.POST_BATCH_SIZE`
    posts an extra :data:`~bot.constants.POST_BATCH_COOLDOWN_SEC` rest is added to
    mimic a human pausing between bursts.
    """
    if index == 0 or base_pace <= 0:
        return 0.0
    delay = base_pace + random.uniform(0, POST_PACE_JITTER_SEC)
    if index % POST_BATCH_SIZE == 0:
        delay += POST_BATCH_COOLDOWN_SEC
    return delay


class _GraphPoster:
    """Adapt the Graph ``Facebook`` engine to the web poster's interface.

    Exposes the same ``pace_seconds`` / ``post_to_group`` surface as
    :class:`~bot.facebook_web.FacebookWeb` so the publish loop is engine-agnostic.
    The Graph API is not rate-paced here, so ``pace_seconds`` is zero.
    """

    pace_seconds: float = 0.0

    def __init__(self, access_token: str, *, proxy: str | None, timeout: float | None) -> None:
        self._facebook = Facebook(access_token, proxy=proxy, timeout=timeout)

    async def __aenter__(self) -> _GraphPoster:
        await self._facebook.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._facebook.__aexit__(*exc)

    async def post_to_group(
        self, *, group_id: str, message: str, image_paths: list[str]
    ) -> WebPostOutcome:
        result = await self._facebook.post(
            message=message, target=group_id, images=list(image_paths)
        )
        return WebPostOutcome(post_id=result.id, url=result.url, pending=False)


class PostService:
    """Publishes one post (text + photos) to many groups via one FB account."""

    def __init__(
        self,
        access_token: str | None = None,
        session_cookies: dict[str, str] | None = None,
        *,
        proxy: str | None = None,
        timeout: float | None = None,
    ) -> None:
        if not access_token and not session_cookies:
            raise ValueError("PostService needs an access token or session cookies")
        self._access_token = access_token
        self._session_cookies = session_cookies
        self._proxy = proxy
        self._timeout = timeout

    async def publish_to_groups(
        self,
        *,
        message: str,
        image_paths: Sequence[str],
        facebook_ids: Sequence[str],
        cancel_event: asyncio.Event | None = None,
        remaining_cap: int | None = None,
    ) -> AsyncIterator[GroupPostResult]:
        """Yield one result per id in *facebook_ids*, in order, as each resolves.

        Setting *cancel_event* requests a cooperative stop: the in-flight group is
        allowed to finish, the inter-group wait is cut short, and every remaining
        group is yielded as cancelled. Setting *remaining_cap* bounds how many
        groups the run may attempt (the account's rolling daily-cap budget): once
        reached, the remaining groups are yielded as skipped.
        """
        paths = list(image_paths)
        state = _RunState()
        async with self._build_poster() as poster:
            job = _PostJob(
                poster=poster,
                message=message,
                paths=paths,
                cancel_event=cancel_event,
                remaining_cap=remaining_cap,
            )
            for index, facebook_id in enumerate(facebook_ids):
                yield await self._next_result(job, facebook_id, index, state)

    async def _next_result(
        self, job: _PostJob, facebook_id: str, index: int, state: _RunState
    ) -> GroupPostResult:
        """Resolve the next group, advancing *state*'s terminal-mode latches."""
        if job.remaining_cap is not None and index >= job.remaining_cap:
            state.cap_reached = True
        if state.stopped:
            return self._not_attempted(facebook_id, state)
        delay = _inter_post_delay(index, job.poster.pace_seconds)
        if delay > 0 and await _wait_or_cancel(delay, job.cancel_event):
            state.cancelled = True
            return self._cancelled(facebook_id)
        if _cancel_requested(job.cancel_event):
            state.cancelled = True
            return self._cancelled(facebook_id)
        result, state.rate_limited = await self._post_one(
            job.poster, job.message, job.paths, facebook_id
        )
        state.record(result)
        return result

    def _build_poster(self) -> FacebookWeb | _GraphPoster:
        """Pick the engine for the stored credential (cookies take precedence)."""
        if self._session_cookies:
            return FacebookWeb(self._session_cookies, proxy=self._proxy, timeout=self._timeout)
        if self._access_token:
            return _GraphPoster(self._access_token, proxy=self._proxy, timeout=self._timeout)
        raise ValueError("no Facebook credential available")  # guarded in __init__

    @staticmethod
    def _not_attempted(facebook_id: str, state: _RunState) -> GroupPostResult:
        """The result for a group a stopped run never reached, per the stop cause."""
        if state.cancelled:
            return PostService._cancelled(facebook_id)
        if state.rate_limited:
            return PostService._skipped(
                facebook_id, POST_SKIPPED_RATE_LIMIT, PostFailure.RATE_LIMITED
            )
        if state.cap_reached:
            return PostService._skipped(
                facebook_id, POST_SKIPPED_DAILY_CAP, PostFailure.DAILY_CAP_REACHED
            )
        return PostService._skipped(
            facebook_id, POST_SKIPPED_CONSECUTIVE_FAILURES, PostFailure.STOPPED
        )

    @staticmethod
    def _skipped(facebook_id: str, reason: str, failure: PostFailure) -> GroupPostResult:
        return GroupPostResult(
            facebook_id=facebook_id,
            url=None,
            error=reason,
            failure=failure,
            attempted=False,
        )

    @staticmethod
    def _cancelled(facebook_id: str) -> GroupPostResult:
        return GroupPostResult(
            facebook_id=facebook_id,
            url=None,
            error=POST_CANCELLED_REASON,
            cancelled=True,
            attempted=False,
        )

    @staticmethod
    def _failed(facebook_id: str, exc: Exception, category: PostFailure) -> GroupPostResult:
        return GroupPostResult(facebook_id=facebook_id, url=None, error=str(exc), failure=category)

    @staticmethod
    async def _post_one(
        poster: FacebookWeb | _GraphPoster,
        message: str,
        image_paths: list[str],
        facebook_id: str,
    ) -> tuple[GroupPostResult, bool]:
        """Post to one group. Returns the result and whether a rate-limit tripped."""
        try:
            outcome = await poster.post_to_group(
                group_id=facebook_id, message=message, image_paths=image_paths
            )
        except FacebookWebRateLimitedError as exc:
            return PostService._failed(facebook_id, exc, PostFailure.RATE_LIMITED), True
        except (FacebookWebSessionExpiredError, FacebookWebCheckpointError) as exc:
            return PostService._failed(facebook_id, exc, PostFailure.SESSION_EXPIRED), False
        except (FacebookError, FacebookWebError) as exc:
            return PostService._failed(facebook_id, exc, PostFailure.GENERIC), False
        return (
            GroupPostResult(
                facebook_id=facebook_id, url=outcome.url, error=None, pending=outcome.pending
            ),
            False,
        )
