"""Scrape the per-session Comet tokens from a logged-in web.facebook.com page.

The cookie jar authenticates a plain GET of the home page; the returned HTML
embeds the short-lived tokens every GraphQL write must echo back — ``fb_dtsg`` /
``jazoest`` / ``lsd`` (the CSRF triplet), the actor id, and the haste/spin
revision markers that pin the request to the page's JS build.
:class:`SessionParams` captures them; :meth:`SessionParams.to_form` renders the
shared POST envelope every Comet mutation starts from.

The extraction patterns live here (next to the one function that uses them),
mirroring how ``bot.callbacks`` keeps its callback-data regex local — the field
*names* are the wire contract and live in :mod:`bot.constants`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bot.constants import (
    FB_WEB_AJAX_PIPE,
    FB_WEB_COMET_REQ,
    FB_WEB_DPR,
    FB_WEB_FIELD_AJAX,
    FB_WEB_FIELD_AV,
    FB_WEB_FIELD_COMET_REQ,
    FB_WEB_FIELD_CONNECTION,
    FB_WEB_FIELD_DPR,
    FB_WEB_FIELD_DTSG,
    FB_WEB_FIELD_HASTE,
    FB_WEB_FIELD_HSI,
    FB_WEB_FIELD_JAZOEST,
    FB_WEB_FIELD_LSD,
    FB_WEB_FIELD_REV,
    FB_WEB_FIELD_SPIN_B,
    FB_WEB_FIELD_SPIN_R,
    FB_WEB_FIELD_SPIN_T,
    FB_WEB_FIELD_USER,
)
from bot.core.exceptions import FacebookWebSessionExpiredError

# Per-session token extractors. The home page is a JS bundle with the tokens
# embedded as JSON fragments; each pattern lifts one value out of that blob.
_RE_ACTOR_ID = re.compile(r'"actorID":"(.*?)"')
_RE_HASTE = re.compile(r'"haste_session":"(.*?)"')
_RE_CONNECTION = re.compile(r'"connectionClass":"(.*?)"')
_RE_SPIN_R = re.compile(r'"__spin_r":(.*?),')
_RE_SPIN_B = re.compile(r'"__spin_b":"(.*?)"')
_RE_SPIN_T = re.compile(r'"__spin_t":(.*?),')
_RE_HSI = re.compile(r'"hsi":"(.*?)"')
_RE_DTSG = re.compile(r'"DTSGInitialData",\[\],\{"token":"(.*?)"\}')
_RE_JAZOEST = re.compile(r"jazoest=(\d+)")
_RE_LSD = re.compile(r'"LSD",\[\],\{"token":"(.*?)"\}')
_RE_SESSION_ID = re.compile(r'"sessionID":"(.*?)"')


def _extract(pattern: re.Pattern[str], html: str, *, default: str = "") -> str:
    """Return the first capture group of ``pattern`` in ``html`` (or ``default``)."""
    match = pattern.search(html)
    return match.group(1) if match else default


@dataclass(frozen=True, slots=True)
class SessionParams:
    """The per-session tokens scraped from a logged-in web.facebook.com page.

    ``actor_id`` / ``fb_dtsg`` / ``jazoest`` / ``lsd`` are auth-critical (the
    request is rejected without them); the rest are best-effort revision markers
    that Facebook tolerates as blank when the page markup shifts.
    """

    actor_id: str
    fb_dtsg: str
    jazoest: str
    lsd: str
    haste_session: str = ""
    connection_class: str = ""
    spin_r: str = ""
    spin_b: str = ""
    spin_t: str = ""
    hsi: str = ""
    session_id: str = ""

    def to_form(self) -> dict[str, str]:
        """Render the GraphQL POST envelope shared by every Comet mutation."""
        return {
            FB_WEB_FIELD_AV: self.actor_id,
            FB_WEB_FIELD_USER: self.actor_id,
            FB_WEB_FIELD_AJAX: FB_WEB_AJAX_PIPE,
            FB_WEB_FIELD_HASTE: self.haste_session,
            FB_WEB_FIELD_DPR: FB_WEB_DPR,
            FB_WEB_FIELD_CONNECTION: self.connection_class,
            # ``__rev`` and ``__spin_r`` carry the same JS-build revision number.
            FB_WEB_FIELD_REV: self.spin_r,
            FB_WEB_FIELD_SPIN_R: self.spin_r,
            FB_WEB_FIELD_SPIN_B: self.spin_b,
            FB_WEB_FIELD_SPIN_T: self.spin_t,
            FB_WEB_FIELD_HSI: self.hsi,
            FB_WEB_FIELD_COMET_REQ: FB_WEB_COMET_REQ,
            FB_WEB_FIELD_DTSG: self.fb_dtsg,
            FB_WEB_FIELD_JAZOEST: self.jazoest,
            FB_WEB_FIELD_LSD: self.lsd,
        }


def scrape_session_params(html: str, *, actor_id_fallback: str = "") -> SessionParams:
    """Parse the home-page HTML into :class:`SessionParams`.

    ``actor_id_fallback`` is the ``c_user`` cookie value: the actor id is already
    known from the jar, so we only scrape it for confirmation and fall back to the
    cookie if the page markup has shifted — that alone never means logged-out.

    Raises :class:`FacebookWebSessionExpiredError` if any CSRF token is absent —
    the usual cause is an expired/invalid cookie jar, which serves a logged-out
    page with no triplet, so the message points the admin at re-capturing.
    """
    actor_id = _extract(_RE_ACTOR_ID, html) or actor_id_fallback
    fb_dtsg = _extract(_RE_DTSG, html)
    jazoest = _extract(_RE_JAZOEST, html)
    lsd = _extract(_RE_LSD, html)
    missing = [
        name
        for name, value in (
            (FB_WEB_FIELD_AV, actor_id),
            (FB_WEB_FIELD_DTSG, fb_dtsg),
            (FB_WEB_FIELD_JAZOEST, jazoest),
            (FB_WEB_FIELD_LSD, lsd),
        )
        if not value
    ]
    if missing:
        raise FacebookWebSessionExpiredError(
            "web session page is missing required tokens "
            f"({', '.join(missing)}) — the cookies are likely expired; re-capture the session"
        )
    return SessionParams(
        actor_id=actor_id,
        fb_dtsg=fb_dtsg,
        jazoest=jazoest,
        lsd=lsd,
        haste_session=_extract(_RE_HASTE, html),
        connection_class=_extract(_RE_CONNECTION, html),
        spin_r=_extract(_RE_SPIN_R, html),
        spin_b=_extract(_RE_SPIN_B, html),
        spin_t=_extract(_RE_SPIN_T, html),
        hsi=_extract(_RE_HSI, html),
        session_id=_extract(_RE_SESSION_ID, html),
    )
