from typing import Any

from .types import FacebookErrorPayload, Step, TwoFactorChallenge


class FacebookError(Exception):
    """Base class for all fb_unofficial errors."""


class FacebookApiError(FacebookError):
    def __init__(self, payload: FacebookErrorPayload | dict[str, Any], step: Step = "request") -> None:
        data = payload if isinstance(payload, FacebookErrorPayload) else FacebookErrorPayload(**payload)
        super().__init__(data.message)
        self.code: int = data.code
        self.type: str = data.type
        self.fbtrace_id: str | None = data.fbtrace_id
        self.is_transient: bool = bool(data.is_transient)
        self.error_subcode: int | None = data.error_subcode
        self.error_user_msg: str | None = data.error_user_msg
        self.step: Step = step
        self.payload: FacebookErrorPayload = data

    def __repr__(self) -> str:
        return f"FacebookApiError(code={self.code}, step={self.step!r}, message={str(self)!r})"


class FacebookAuthError(FacebookError):
    """Raised when login / session refresh fails."""


class FacebookTwoFactorRequired(FacebookAuthError):
    """Login needs a TOTP code. Retry ``login()`` with ``totp=<code>``."""

    def __init__(self, challenge: TwoFactorChallenge, message: str | None = None) -> None:
        super().__init__(message or "Two-factor authentication required")
        self.challenge: TwoFactorChallenge = challenge


class FacebookApprovalRequired(FacebookAuthError):
    """Login is held pending device approval ("Was this you?").

    The user must approve on another logged-in device. Retry the same
    ``login()`` call (ideally with ``approval_poll_seconds=N``) afterwards.
    """

    def __init__(self, email: str, message: str | None = None) -> None:
        super().__init__(
            message or "Login approval required — approve the prompt in the Facebook mobile app",
        )
        self.email: str = email


class FacebookCheckpointRequired(FacebookAuthError):
    """Login blocked by an account-verification checkpoint (FB error 405).

    Facebook wants the account verified in a browser/app at www.facebook.com
    before it will trust this login. After verifying, retry the same ``login()``
    call with the SAME ``machine_id`` so Facebook recognizes the now-trusted
    device.
    """

    def __init__(self, email: str, message: str | None = None) -> None:
        super().__init__(
            message or "Account verification required — verify at www.facebook.com, then retry",
        )
        self.email: str = email


class FacebookResolveError(FacebookError):
    """Raised when an id/URL can't be resolved to a numeric Facebook id."""
