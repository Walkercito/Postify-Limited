"""Pydantic schemas for the :class:`~bot.db.models.facebook_account.FacebookAccount`."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from bot.schemas.base import BaseSchema


class FacebookAccountCreate(BaseModel):
    """Fields captured when an admin links a Facebook account to a user.

    An account is authenticated by a Graph ``access_token`` *or* a browser
    ``session_cookies`` jar (JSON-encoded name→value map) — at least one is
    required, but the two engines are mutually exclusive at post time.
    """

    user_id: int
    fb_uid: str
    access_token: str | None = None
    session_cookies: str | None = None


class FacebookAccountRead(BaseSchema):
    """Account representation returned to callers (the token is never exposed)."""

    id: int
    user_id: int
    fb_uid: str
    created_at: datetime
    updated_at: datetime
