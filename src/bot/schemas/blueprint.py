"""Pydantic schemas for the :class:`~bot.db.models.blueprint.Blueprint` entity."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from bot.schemas.base import BaseSchema


class BlueprintCreate(BaseModel):
    """Fields captured when a user saves a post as a blueprint."""

    user_id: int
    name: str
    text: str | None = None
    photo_file_ids: list[str] = Field(default_factory=list)


class BlueprintRead(BaseSchema):
    """Blueprint representation returned to callers."""

    id: int
    user_id: int
    name: str
    slug: str
    text: str | None
    photo_file_ids: list[str]
    created_at: datetime
    updated_at: datetime
