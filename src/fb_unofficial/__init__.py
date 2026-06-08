"""Unofficial Facebook client for Python."""

from .auth import load_session, login, refresh_session, save_session, validate_session
from .client import Facebook
from .errors import (
    FacebookApiError,
    FacebookApprovalRequired,
    FacebookAuthError,
    FacebookCheckpointRequired,
    FacebookError,
    FacebookResolveError,
    FacebookTwoFactorRequired,
)
from .groups import fetch_group_preview
from .types import (
    ClientConfig,
    Cookie,
    Credentials,
    FacebookErrorPayload,
    GroupPreview,
    LoadResult,
    PostResult,
    Session,
    TwoFactorChallenge,
    User,
    UserProfile,
)

__all__ = [
    "ClientConfig",
    "Cookie",
    "Credentials",
    "Facebook",
    "FacebookApiError",
    "FacebookApprovalRequired",
    "FacebookAuthError",
    "FacebookCheckpointRequired",
    "FacebookError",
    "FacebookErrorPayload",
    "FacebookResolveError",
    "FacebookTwoFactorRequired",
    "GroupPreview",
    "LoadResult",
    "PostResult",
    "Session",
    "TwoFactorChallenge",
    "User",
    "UserProfile",
    "fetch_group_preview",
    "load_session",
    "login",
    "refresh_session",
    "save_session",
    "validate_session",
]
