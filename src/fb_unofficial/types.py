from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Step = Literal["upload", "publish", "resolve", "auth", "request"]


class Cookie(BaseModel):
    name: str
    value: str
    domain: str | None = None
    path: str | None = None
    expires: str | None = None
    expires_timestamp: int | None = None
    secure: bool | None = None
    httponly: bool | None = None
    samesite: str | None = None


class Session(BaseModel):
    access_token: str
    uid: str
    secret: str | None = None
    session_key: str | None = None
    machine_id: str | None = None
    session_cookies: list[Cookie] | None = None
    identifier: str | None = None
    created_at: int


class ClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    api_version: str | None = None
    user_agent: str | Literal["auto"] | None = "auto"
    proxy: str | None = None
    timeout: float | None = None
    base_url: str | None = None


class PostResult(BaseModel):
    id: str
    url: str


class User(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str


class UserProfile(BaseModel):
    """Rich user profile with optional edge summaries.

    Count fields are ``None`` when the token lacks permission for the
    corresponding edge (e.g. ``user_friends``, ``user_managed_groups``).
    """

    id: str
    name: str
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    link: str | None = None
    picture_url: str | None = None
    birthday: str | None = None
    gender: str | None = None
    locale: str | None = None
    timezone: float | None = None
    email: str | None = None
    friends_count: int | None = None
    groups_count: int | None = None
    pages_liked_count: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class GroupPreview(BaseModel):
    """Public preview of a Facebook group, scraped without authentication.

    Assembled from the group page's Open Graph tags. Only fields Facebook
    exposes publicly are populated: ``description`` is frequently absent, and
    member count / privacy are never available this way.
    """

    id: str | None = None
    name: str
    cover_url: str | None = None
    description: str | None = None
    url: str | None = None


class Credentials(BaseModel):
    email: str
    password: str


class TwoFactorChallenge(BaseModel):
    """Continuation state returned by FB when a login triggers 2FA."""

    email: str
    uid: str
    machine_id: str
    first_factor: str
    subcode: int | None = None


class LoadResult(BaseModel):
    session: Session
    credentials: Credentials | None = None


class FacebookErrorPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    type: str = "Unknown"
    code: int = -1
    is_transient: bool | None = None
    fbtrace_id: str | None = None
    error_subcode: int | None = None
    error_user_msg: str | None = None
