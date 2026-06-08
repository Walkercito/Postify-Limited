"""Codec for parameterized inline-button ``callback_data``.

Static menu buttons carry a bare :class:`~bot.constants.MenuAction`; access
decisions instead need to name a target user, so they carry a structured
``scope:status:telegram_id`` payload. Encoding (for keyboards) and parsing (for
handlers) live here together so the wire format has a single definition (DRY).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from bot.constants import (
    CALLBACK_DATA_SEPARATOR,
    AccessStatus,
    AccountAction,
    BlueprintAction,
    CallbackScope,
    GroupAction,
    PostAction,
)

# Every blueprint action carries a target blueprint's internal id.
BLUEPRINT_DECISION_ACTIONS: tuple[BlueprintAction, ...] = tuple(BlueprintAction)

# Only these two statuses are ever the result of an admin decision.
DECISION_STATUSES: tuple[AccessStatus, ...] = (AccessStatus.ALLOWED, AccessStatus.DENIED)

# Group actions that carry a trailing integer. QUICK_DELETE / CONFIRM_DELETE /
# CANCEL_DELETE carry a group id; PAGE carries a 0-based result page number.
GROUP_DECISION_ACTIONS: tuple[GroupAction, ...] = (
    GroupAction.QUICK_DELETE,
    GroupAction.PAGE,
    GroupAction.CONFIRM_DELETE,
    GroupAction.CANCEL_DELETE,
)

# Post actions carrying a trailing integer, each with its own pattern so their
# handlers don't claim each other: REMOVE_PHOTO carries a 0-based photo index,
# RESULT_PAGE a 0-based result-summary page number.
POST_DECISION_ACTIONS: tuple[PostAction, ...] = (PostAction.REMOVE_PHOTO,)
POST_RESULT_PAGE_ACTIONS: tuple[PostAction, ...] = (PostAction.RESULT_PAGE,)

# Every account action carries a target user's Telegram id.
ACCOUNT_DECISION_ACTIONS: tuple[AccountAction, ...] = (
    AccountAction.LINK,
    AccountAction.UNLINK,
    AccountAction.CANCEL,
)


def _alternation(values: Iterable[str]) -> str:
    return "|".join(re.escape(value) for value in values)


_SEPARATOR = re.escape(CALLBACK_DATA_SEPARATOR)
ACCESS_DECISION_PATTERN: str = (
    rf"^({_alternation(CallbackScope)}){_SEPARATOR}"
    rf"({_alternation(DECISION_STATUSES)}){_SEPARATOR}"
    rf"(\d+)$"
)
_ACCESS_DECISION_RE = re.compile(ACCESS_DECISION_PATTERN)


GROUP_DECISION_PATTERN: str = rf"^({_alternation(GROUP_DECISION_ACTIONS)}){_SEPARATOR}(\d+)$"
_GROUP_DECISION_RE = re.compile(GROUP_DECISION_PATTERN)


POST_PHOTO_DECISION_PATTERN: str = rf"^({_alternation(POST_DECISION_ACTIONS)}){_SEPARATOR}(\d+)$"
_POST_PHOTO_DECISION_RE = re.compile(POST_PHOTO_DECISION_PATTERN)


POST_RESULT_PAGE_PATTERN: str = rf"^({_alternation(POST_RESULT_PAGE_ACTIONS)}){_SEPARATOR}(\d+)$"
_POST_RESULT_PAGE_RE = re.compile(POST_RESULT_PAGE_PATTERN)


ACCOUNT_DECISION_PATTERN: str = rf"^({_alternation(ACCOUNT_DECISION_ACTIONS)}){_SEPARATOR}(\d+)$"
_ACCOUNT_DECISION_RE = re.compile(ACCOUNT_DECISION_PATTERN)


BLUEPRINT_DECISION_PATTERN: str = (
    rf"^({_alternation(BLUEPRINT_DECISION_ACTIONS)}){_SEPARATOR}(\d+)$"
)
_BLUEPRINT_DECISION_RE = re.compile(BLUEPRINT_DECISION_PATTERN)


def access_decision(scope: CallbackScope, status: AccessStatus, telegram_id: int) -> str:
    """Build the ``callback_data`` for a Grant/Deny/Revoke button."""
    return CALLBACK_DATA_SEPARATOR.join((scope, status, str(telegram_id)))


def parse_access_decision(data: str) -> tuple[CallbackScope, AccessStatus, int] | None:
    """Parse an access-decision payload, or ``None`` if it doesn't match."""
    match = _ACCESS_DECISION_RE.match(data)
    if match is None:
        return None
    scope, status, telegram_id = match.groups()
    return CallbackScope(scope), AccessStatus(status), int(telegram_id)


def group_decision(action: GroupAction, group_id: int) -> str:
    """Build the ``callback_data`` for a delete-confirmation button."""
    return CALLBACK_DATA_SEPARATOR.join((action, str(group_id)))


def parse_group_decision(data: str) -> tuple[GroupAction, int] | None:
    """Parse a group-decision payload, or ``None`` if it doesn't match."""
    match = _GROUP_DECISION_RE.match(data)
    if match is None:
        return None
    action, group_id = match.groups()
    return GroupAction(action), int(group_id)


def post_photo_decision(index: int) -> str:
    """Build the ``callback_data`` for a remove-photo button (0-based index)."""
    return CALLBACK_DATA_SEPARATOR.join((PostAction.REMOVE_PHOTO, str(index)))


def parse_post_photo_decision(data: str) -> int | None:
    """Parse a remove-photo payload to its photo index, or ``None`` if it doesn't match."""
    match = _POST_PHOTO_DECISION_RE.match(data)
    if match is None:
        return None
    return int(match.group(2))


def post_result_page(page: int) -> str:
    """Build the ``callback_data`` for a result-summary page button (0-based page)."""
    return CALLBACK_DATA_SEPARATOR.join((PostAction.RESULT_PAGE, str(page)))


def parse_post_result_page(data: str) -> int | None:
    """Parse a result-page payload to its page number, or ``None`` if it doesn't match."""
    match = _POST_RESULT_PAGE_RE.match(data)
    if match is None:
        return None
    return int(match.group(2))


def account_decision(action: AccountAction, telegram_id: int) -> str:
    """Build the ``callback_data`` for a Link/Unlink/Cancel account button."""
    return CALLBACK_DATA_SEPARATOR.join((action, str(telegram_id)))


def parse_account_decision(data: str) -> tuple[AccountAction, int] | None:
    """Parse an account-decision payload, or ``None`` if it doesn't match."""
    match = _ACCOUNT_DECISION_RE.match(data)
    if match is None:
        return None
    action, telegram_id = match.groups()
    return AccountAction(action), int(telegram_id)


def blueprint_decision(action: BlueprintAction, blueprint_id: int) -> str:
    """Build the ``callback_data`` for a blueprint action button."""
    return CALLBACK_DATA_SEPARATOR.join((action, str(blueprint_id)))


def parse_blueprint_decision(data: str) -> tuple[BlueprintAction, int] | None:
    """Parse a blueprint-decision payload, or ``None`` if it doesn't match."""
    match = _BLUEPRINT_DECISION_RE.match(data)
    if match is None:
        return None
    action, blueprint_id = match.groups()
    return BlueprintAction(action), int(blueprint_id)
