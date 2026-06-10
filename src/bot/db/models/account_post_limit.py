"""AccountPostLimit ORM model: persistent per-account publish-guard state.

Backs the behaviour-only anti-automation gates enforced by
:class:`~bot.services.account_post_limit_service.AccountPostLimitService`. One row
per Facebook account (keyed by :attr:`fb_uid`, not the linkable
``facebook_accounts`` row, so a cooldown and the daily count survive an
unlink/relink as well as a restart). The row carries the two pieces of state that
*must* persist between runs:

* the rolling daily-cap window (:attr:`window_start` + :attr:`window_count`), and
* the escalating cross-run back-off (:attr:`cooldown_until` +
  :attr:`consecutive_soft_blocks`).

Circadian gating needs no stored state — it is a pure function of the wall clock —
so it has no column here.

Timestamps are written tz-aware (UTC) but SQLite reads them back *naive*; the
service re-attaches UTC before any comparison.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from bot.constants import FB_UID_MAX_LENGTH
from bot.db.base import Base, TimestampMixin, utcnow


class AccountPostLimit(Base, TimestampMixin):
    """Persistent guard state for one Facebook account's publish runs.

    ``window_start``/``window_count`` track attempts inside the current rolling
    daily-cap window; when the window elapses the service rolls it over (resets
    the start to now and the count to zero). ``cooldown_until`` is the absolute
    instant the account may start a run again (``None`` when not cooling down),
    and ``consecutive_soft_blocks`` is the escalation level — bumped per
    soft-blocked run, reset to zero after a clean one.
    """

    __tablename__ = "account_post_limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    fb_uid: Mapped[str] = mapped_column(String(FB_UID_MAX_LENGTH), unique=True, index=True)
    window_start: Mapped[datetime] = mapped_column(default=utcnow)
    window_count: Mapped[int] = mapped_column(default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    consecutive_soft_blocks: Mapped[int] = mapped_column(default=0)

    def __repr__(self) -> str:
        return (
            f"AccountPostLimit(id={self.id!r}, fb_uid={self.fb_uid!r}, "
            f"window_count={self.window_count!r}, cooldown_until={self.cooldown_until!r})"
        )
