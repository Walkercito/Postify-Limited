"""Cookie-native (web.facebook.com Comet) Facebook posting engine.

The parallel of :mod:`fb_unofficial`: post to Facebook groups with a captured
browser cookie jar instead of a Graph access token. :class:`FacebookWeb` is the
client; :func:`encode_cookies` / :func:`decode_cookies` are the storage codec for
the jar. The scraping/variable/response helpers are exported for unit testing.
"""

from __future__ import annotations

from bot.facebook_web.client import FacebookWeb
from bot.facebook_web.cookies import decode_cookies, encode_cookies
from bot.facebook_web.group_page import extract_group_name
from bot.facebook_web.params import SessionParams, scrape_session_params
from bot.facebook_web.response import (
    WebPostOutcome,
    classify_post_response,
    classify_upload_response,
    extract_photo_id,
    is_blocked_page,
)
from bot.facebook_web.variables import build_group_post_variables

__all__ = [
    "FacebookWeb",
    "SessionParams",
    "WebPostOutcome",
    "build_group_post_variables",
    "classify_post_response",
    "classify_upload_response",
    "decode_cookies",
    "encode_cookies",
    "extract_group_name",
    "extract_photo_id",
    "is_blocked_page",
    "scrape_session_params",
]
