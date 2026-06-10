"""Tests for the behaviour-only publish guards (circadian / daily cap / back-off).

Exercises :class:`~bot.services.account_post_limit_service.AccountPostLimitService`
against a real in-memory SQLite session, so the naive/aware datetime coercion
(SQLite drops tzinfo on read) is covered end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bot.constants import PostGate
from bot.core.config import PostLimitsSettings
from bot.services.account_post_limit_service import AccountPostLimitService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

FB_UID = "100012345678901"
# Inside the configured 08:00-23:00 active window, in UTC.
NOON = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
# Before the window opens — circadian should refuse the run.
PREDAWN = datetime(2026, 6, 9, 3, 0, tzinfo=UTC)


def _limits(
    *,
    daily_cap: int = 5,
    window_seconds: int = 3600,
    backoff_base_sec: float = 900.0,
    backoff_multiplier: float = 2.0,
    backoff_cap_sec: float = 7200.0,
) -> PostLimitsSettings:
    """A guard config in UTC with an 08:00-23:00 window and small, exact numbers."""
    return PostLimitsSettings(
        active_start_hour=8,
        active_end_hour=23,
        timezone="UTC",
        daily_cap=daily_cap,
        window_seconds=window_seconds,
        backoff_base_sec=backoff_base_sec,
        backoff_multiplier=backoff_multiplier,
        backoff_cap_sec=backoff_cap_sec,
    )


def _service(
    session: AsyncSession, limits: PostLimitsSettings | None = None
) -> AccountPostLimitService:
    """Build the service bound to *session* (defaulting to `_limits()`)."""
    return AccountPostLimitService(session, limits or _limits())


async def test_evaluate_ok_within_window_offers_full_budget(session: AsyncSession) -> None:
    decision = await _service(session).evaluate(fb_uid=FB_UID, now=NOON)

    assert decision.gate is PostGate.OK
    assert decision.remaining_cap == 5  # a fresh account has the whole daily cap


async def test_circadian_blocks_outside_window(session: AsyncSession) -> None:
    decision = await _service(session).evaluate(fb_uid=FB_UID, now=PREDAWN)

    assert decision.gate is PostGate.CIRCADIAN
    assert decision.remaining_cap is None  # no run starts, so no budget is offered


async def test_recorded_attempts_decrement_remaining(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=2, soft_blocked=False)

    decision = await service.evaluate(fb_uid=FB_UID, now=NOON)

    assert decision.gate is PostGate.OK
    assert decision.remaining_cap == 3  # 5 cap - 2 already attempted this window


async def test_daily_cap_blocks_when_spent(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=5, soft_blocked=False)

    decision = await service.evaluate(fb_uid=FB_UID, now=NOON)

    assert decision.gate is PostGate.DAILY_CAP
    assert decision.remaining_cap is None


async def test_window_rollover_restores_budget(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=5, soft_blocked=False)

    # Past the 3600s window, the count rolls over and the full cap is available.
    later = NOON + timedelta(seconds=3601)
    decision = await service.evaluate(fb_uid=FB_UID, now=later)

    assert decision.gate is PostGate.OK
    assert decision.remaining_cap == 5


async def test_soft_block_starts_cooldown(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=1, soft_blocked=True)

    # Still inside the 900s back-off shortly after the soft-block.
    decision = await service.evaluate(fb_uid=FB_UID, now=NOON + timedelta(seconds=60))

    assert decision.gate is PostGate.BACKOFF


async def test_cooldown_expires_after_its_duration(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=1, soft_blocked=True)

    # Just past the 900s base cooldown, the account may post again.
    decision = await service.evaluate(fb_uid=FB_UID, now=NOON + timedelta(seconds=901))

    assert decision.gate is PostGate.OK
    assert decision.remaining_cap == 4  # the one attempted post still counts


async def test_clean_run_clears_cooldown(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=1, soft_blocked=True)
    # A clean run resets the back-off even though the cooldown had not elapsed.
    await service.record(
        fb_uid=FB_UID, now=NOON + timedelta(seconds=10), attempted=1, soft_blocked=False
    )

    decision = await service.evaluate(fb_uid=FB_UID, now=NOON + timedelta(seconds=60))

    assert decision.gate is PostGate.OK


async def test_back_off_escalates_on_consecutive_soft_blocks(session: AsyncSession) -> None:
    service = _service(session, _limits(backoff_base_sec=100.0, backoff_multiplier=2.0))
    await service.record(fb_uid=FB_UID, now=NOON, attempted=1, soft_blocked=True)
    # Second consecutive soft-block: cooldown is 100*2 = 200s from this run, so it
    # reaches NOON+210 — a flat (non-escalating) 100s back-off would be long gone.
    await service.record(
        fb_uid=FB_UID, now=NOON + timedelta(seconds=10), attempted=1, soft_blocked=True
    )

    decision = await service.evaluate(fb_uid=FB_UID, now=NOON + timedelta(seconds=160))

    assert decision.gate is PostGate.BACKOFF


async def test_back_off_is_capped(session: AsyncSession) -> None:
    # base 1000, multiplier 1000 → the 2nd block would be 1_000_000s uncapped; the
    # 2000s cap pins it, so the account is free again well before that runaway.
    service = _service(
        session, _limits(backoff_base_sec=1000.0, backoff_multiplier=1000.0, backoff_cap_sec=2000.0)
    )
    await service.record(fb_uid=FB_UID, now=NOON, attempted=1, soft_blocked=True)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=1, soft_blocked=True)

    decision = await service.evaluate(fb_uid=FB_UID, now=NOON + timedelta(seconds=2001))

    assert decision.gate is not PostGate.BACKOFF


async def test_state_survives_a_reload(session: AsyncSession) -> None:
    service = _service(session)
    await service.record(fb_uid=FB_UID, now=NOON, attempted=3, soft_blocked=False)

    # Force a re-read from SQLite (which drops tzinfo): the next evaluate must
    # coerce the naive stored timestamps back to aware UTC without raising.
    session.expire_all()
    decision = await service.evaluate(fb_uid=FB_UID, now=NOON)

    assert decision.gate is PostGate.OK
    assert decision.remaining_cap == 2  # 5 cap - 3 attempted, read back from the row
