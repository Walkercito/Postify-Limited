"""Shared Pydantic schema base."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Base for schemas read from ORM objects (``from_attributes``)."""

    model_config = ConfigDict(from_attributes=True)
