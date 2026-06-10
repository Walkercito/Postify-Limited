"""Behaviour-only publish guards: decide *whether* and *how much* to post.

Enforces three account-level gates that change only WHEN and HOW MANY posts go
out — never the content — to keep a captured account's posting rhythm humanly
plausible:

* **Circadian** — refuse any run outside the configured local active-hours
  window, so the account never posts overnight. Stateless (a pure function of the
  wall clock).
* **Daily cap** — at most ``daily_cap`` attempted posts per rolling window; a run
  already at the cap is refused, one that would cross it is capped to the
  remaining budget.
* **Back-off** — after any run that hits a soft-block (a Facebook rate-limit or an
  expired session) the account is put on an escalating cooldown
  (``base * multiplier ** (blocks - 1)``, ceilinged), cleared after a clean run.

:meth:`evaluate` is read-only and returns a :class:`GateDecision` *before* any
photo is downloaded; :meth:`record` is called *after* the run to advance the
rolling window and the back-off state. Daily-cap and back-off state persist in the
``account_post_limits`` table (keyed by ``fb_uid``), so a cooldown and the daily
count survive a restart. SQLite reads stored timestamps back *naive*, so every
comparison re-attaches UTC via :func:`_as_aware_utc`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from bot.constants import LogEvent, PostGate
from bot.core.logging import get_logger
from bot.db.models.account_post_limit import AccountPostLimit
from bot.repositories.account_post_limit import AccountPostLimitRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.core.config import PostLimitsSettings

log = get_logger(__name__)


def _as_aware_utc(moment: datetime) -> datetime:
    """Coerce a possibly-naive datetime (SQLite drops tzinfo on read) to aware UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Whether a run may start now and, if so, how many groups it may attempt.

    ``remaining_cap`` is the rolling-window budget left for this account (always a
    positive int when ``gate`` is :attr:`~bot.constants.PostGate.OK`); it is
    ``None`` for every blocking gate, where no run starts at all.
    """

    gate: PostGate
    remaining_cap: int | None = None


class AccountPostLimitService:
    """Coordinates the publish guards on top of :class:`AccountPostLimitRepository`."""

    def __init__(self, session: AsyncSession, limits: PostLimitsSettings) -> None:
        self._rows = AccountPostLimitRepository(session)
        self._limits = limits

    async def evaluate(self, *, fb_uid: str, now: datetime) -> GateDecision:
        """Decide the gate for an account about to publish (read-only).

        Checks the cheapest stateless guard first (circadian), then the persisted
        ones (back-off cooldown, then the rolling daily cap). On ``OK`` the
        returned ``remaining_cap`` is how many groups the run may still attempt.
        """
        if not self._within_active_hours(now):
            return GateDecision(gate=PostGate.CIRCADIAN)
        row = await self._rows.get_by_fb_uid(fb_uid)
        if row is not None and self._cooling_down(row, now):
            return GateDecision(gate=PostGate.BACKOFF)
        used = self._effective_window_count(row, now)
        remaining = self._limits.daily_cap - used
        if remaining <= 0:
            return GateDecision(gate=PostGate.DAILY_CAP)
        return GateDecision(gate=PostGate.OK, remaining_cap=remaining)

    async def record(
        self, *, fb_uid: str, now: datetime, attempted: int, soft_blocked: bool
    ) -> None:
        """Persist a finished run: advance the rolling window and the back-off.

        ``attempted`` is how many groups the run actually tried (the daily-cap
        budget it spent); ``soft_blocked`` marks a run that hit a rate-limit or an
        expired session, which escalates the cooldown (a clean run resets it).
        """
        row = await self._rows.get_by_fb_uid(fb_uid)
        if row is None:
            # Column defaults only land at flush; this run mutates the row first,
            # so initialise the counters we read/increment before persisting.
            row = AccountPostLimit(
                fb_uid=fb_uid, window_start=now, window_count=0, consecutive_soft_blocks=0
            )
        self._advance_window(row, now, attempted)
        self._advance_backoff(row, now, fb_uid=fb_uid, soft_blocked=soft_blocked)
        await self._rows.add(row)

    def _within_active_hours(self, now: datetime) -> bool:
        """Whether *now*, in the configured local timezone, is inside the window."""
        local = now.astimezone(ZoneInfo(self._limits.timezone)).time()
        start = time(self._limits.active_start_hour, self._limits.active_start_minute)
        end = time(self._limits.active_end_hour, self._limits.active_end_minute)
        if start <= end:
            return start <= local < end
        return local >= start or local < end  # window straddles midnight

    def _cooling_down(self, row: AccountPostLimit, now: datetime) -> bool:
        """Whether *row*'s back-off cooldown is still in effect at *now*."""
        if row.cooldown_until is None:
            return False
        return now < _as_aware_utc(row.cooldown_until)

    def _window_elapsed(self, row: AccountPostLimit, now: datetime) -> bool:
        """Whether *row*'s rolling daily-cap window has fully elapsed by *now*."""
        elapsed = (now - _as_aware_utc(row.window_start)).total_seconds()
        return elapsed >= self._limits.window_seconds

    def _effective_window_count(self, row: AccountPostLimit | None, now: datetime) -> int:
        """Attempts counted against the cap right now (zero once the window rolls)."""
        if row is None or self._window_elapsed(row, now):
            return 0
        return row.window_count

    def _advance_window(self, row: AccountPostLimit, now: datetime, attempted: int) -> None:
        """Roll the window over if elapsed, then add this run's attempts."""
        if self._window_elapsed(row, now):
            row.window_start = now
            row.window_count = 0
        row.window_count += attempted

    def _advance_backoff(
        self, row: AccountPostLimit, now: datetime, *, fb_uid: str, soft_blocked: bool
    ) -> None:
        """Escalate the cooldown on a soft-block, or clear it after a clean run."""
        if soft_blocked:
            row.consecutive_soft_blocks += 1
            duration = self._backoff_duration(row.consecutive_soft_blocks)
            row.cooldown_until = now + timedelta(seconds=duration)
            log.info(
                LogEvent.POST_BACKOFF_ESCALATED,
                fb_uid=fb_uid,
                consecutive_soft_blocks=row.consecutive_soft_blocks,
                cooldown_seconds=duration,
            )
        elif row.consecutive_soft_blocks > 0 or row.cooldown_until is not None:
            row.consecutive_soft_blocks = 0
            row.cooldown_until = None
            log.info(LogEvent.POST_BACKOFF_CLEARED, fb_uid=fb_uid)

    def _backoff_duration(self, blocks: int) -> float:
        """Escalating cooldown seconds for *blocks* consecutive soft-blocks (capped)."""
        duration = self._limits.backoff_base_sec * self._limits.backoff_multiplier ** (blocks - 1)
        return min(duration, self._limits.backoff_cap_sec)
