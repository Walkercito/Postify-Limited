"""Pydantic schemas for the :class:`~bot.db.models.group.Group` entity."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from bot.schemas.base import BaseSchema


class GroupCreate(BaseModel):
    """Fields captured when a user saves a group."""

    user_id: int
    facebook_id: str
    name: str | None = None


class GroupRead(BaseSchema):
    """Group representation returned to callers."""

    id: int
    user_id: int
    facebook_id: str
    name: str | None
    created_at: datetime
    updated_at: datetime
