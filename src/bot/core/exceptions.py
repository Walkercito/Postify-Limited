"""Domain exceptions raised by the application's business logic."""

from __future__ import annotations


class BotError(Exception):
    """Base class for all expected (domain) errors."""


class InvalidSessionPayloadError(BotError):
    """A supplied ``session.json`` couldn't be parsed into a usable session."""


class FacebookAccountTakenError(BotError):
    """A Facebook account is already linked to a different bot user."""

    def __init__(self, fb_uid: str) -> None:
        super().__init__(f"Facebook account {fb_uid!r} is already linked to another user")
        self.fb_uid = fb_uid


class FacebookWebError(BotError):
    """A cookie-native (web.facebook.com) post could not be completed.

    Base of the web-engine error family (:mod:`bot.facebook_web`). Carries a
    human-readable reason; subclasses mark the conditions worth reacting to
    differently (back off, ask the admin to re-verify).
    """


class FacebookWebSessionExpiredError(FacebookWebError):
    """The captured cookie jar no longer authenticates a web session.

    Facebook serves a logged-out home page that carries none of the CSRF tokens
    a write must echo back, so the account must be re-captured and re-linked.
    Distinct from a checkpoint: nothing to clear in a browser, the jar is simply
    stale.
    """


class FacebookWebRateLimitedError(FacebookWebError):
    """Facebook is rate-limiting writes from this account — back off.

    Raised when a post response shows a rate-limit needle. The post service
    treats this as a circuit-breaker: it stops the run and skips the remaining
    groups rather than digging the account deeper into the limit.
    """


class FacebookWebCheckpointError(FacebookWebError):
    """Facebook is blocking writes pending an account checkpoint.

    The captured cookies are no longer trusted for writing; the admin must clear
    the checkpoint in a browser and re-capture the session.
    """
