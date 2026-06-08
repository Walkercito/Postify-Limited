"""Inline-keyboard builders for the bot's menus.

Keyboards are pure functions of their inputs (no I/O). Static buttons carry a
bare :class:`~bot.constants.MenuAction`; access-decision buttons carry a
structured payload built by :func:`~bot.callbacks.access_decision`. Every
submenu ends with a *⬅️ Volver* row (:func:`_back_row`) so no screen dead-ends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.callbacks import (
    access_decision,
    account_decision,
    blueprint_decision,
    group_decision,
    post_photo_decision,
    post_result_page,
)
from bot.constants import (
    ACCESS_DENY_LABEL,
    ACCESS_GRANT_LABEL,
    ACCOUNT_CANCEL_LABEL,
    ACCOUNT_LINK_PREFIX,
    ACCOUNT_RELINK_PREFIX,
    ACCOUNT_UNLINK_LABEL,
    BLUEPRINT_BUTTON_DELETE,
    BLUEPRINT_BUTTON_EDIT,
    BLUEPRINT_BUTTON_EDIT_TEXT,
    BLUEPRINT_BUTTON_NAME_MAX_LENGTH,
    BLUEPRINT_BUTTON_PUBLISH,
    BLUEPRINT_BUTTON_RENAME,
    BLUEPRINT_BUTTON_SHOW_IMAGES,
    BLUEPRINT_CANCEL_LABEL,
    BLUEPRINT_CONFIRM_DELETE_LABEL,
    BLUEPRINT_ROW_PREFIX,
    GROUP_BUTTON_ADD,
    GROUP_BUTTON_NAME_MAX_LENGTH,
    GROUP_BUTTON_SEARCH,
    GROUP_CANCEL_DELETE_LABEL,
    GROUP_CONFIRM_DELETE_LABEL,
    GROUP_PAGE_NEXT_LABEL,
    GROUP_PAGE_PREV_LABEL,
    GROUP_RESULT_DELETE_LABEL,
    GROUP_RESULT_LINK_PREFIX,
    MANAGE_DENY_PREFIX,
    MANAGE_GRANT_PREFIX,
    MANAGE_REVOKE_PREFIX,
    MENU_BUTTON_ACCOUNTS,
    MENU_BUTTON_BACK,
    MENU_BUTTON_BLUEPRINTS,
    MENU_BUTTON_GROUPS,
    MENU_BUTTON_MANAGEMENT,
    MENU_BUTTON_REQUEST_ACCESS,
    MENU_BUTTON_START_POST,
    POST_BUTTON_CANCEL,
    POST_BUTTON_CANCEL_PUBLISH,
    POST_BUTTON_CLEAR,
    POST_BUTTON_CONFIRM,
    POST_BUTTON_DONE,
    POST_BUTTON_EDIT_TEXT,
    POST_BUTTON_SAVE_BLUEPRINT,
    POST_PHOTO_REMOVE_LABEL,
    POST_PHOTO_REMOVE_PER_ROW,
    POST_RESULT_PAGE_NEXT_LABEL,
    POST_RESULT_PAGE_PREV_LABEL,
    AccessStatus,
    AccountAction,
    BlueprintAction,
    CallbackScope,
    GroupAction,
    MenuAction,
    PostAction,
    Role,
)
from bot.facebook_url import group_url

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from bot.db.models.blueprint import Blueprint
    from bot.db.models.user import User
    from bot.group_search import GroupSearchPage
    from bot.post_results import PostResultPage


def main_menu(role: Role) -> InlineKeyboardMarkup:
    """Build the role-aware main menu shown after ``/start``.

    Every user gets *Crear publicación*, *Plantillas* and *Mis grupos*; an admin
    additionally gets *Administración* and *Facebook* (account provisioning).
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(MENU_BUTTON_START_POST, callback_data=MenuAction.START_POST)],
        [
            InlineKeyboardButton(MENU_BUTTON_BLUEPRINTS, callback_data=MenuAction.BLUEPRINTS),
            InlineKeyboardButton(MENU_BUTTON_GROUPS, callback_data=MenuAction.GROUPS),
        ],
    ]
    if role is Role.ADMIN:
        rows.append(
            [
                InlineKeyboardButton(MENU_BUTTON_MANAGEMENT, callback_data=MenuAction.MANAGEMENT),
                InlineKeyboardButton(MENU_BUTTON_ACCOUNTS, callback_data=MenuAction.ACCOUNTS),
            ]
        )
    return InlineKeyboardMarkup(rows)


def back_to_menu() -> InlineKeyboardMarkup:
    """A lone *⬅️ Volver* button — for terminal screens with no other action."""
    return InlineKeyboardMarkup([_back_row()])


def accounts_menu(rows: Sequence[tuple[User, bool]]) -> InlineKeyboardMarkup:
    """The admin's Facebook-accounts screen: one row per allowed user.

    *rows* pairs each user with whether they already have a linked account. A
    linked user gets a *Relink* + *Unlink* pair; an unlinked user gets a single
    *Link* button. Every button carries the user's Telegram id (encoded by
    :func:`~bot.callbacks.account_decision`). A *Volver* row closes the screen.
    """
    keyboard: list[list[InlineKeyboardButton]] = []
    for user, linked in rows:
        prefix = ACCOUNT_RELINK_PREFIX if linked else ACCOUNT_LINK_PREFIX
        buttons = [
            InlineKeyboardButton(
                prefix + user.display_name,
                callback_data=account_decision(AccountAction.LINK, user.telegram_id),
            )
        ]
        if linked:
            buttons.append(
                InlineKeyboardButton(
                    ACCOUNT_UNLINK_LABEL,
                    callback_data=account_decision(AccountAction.UNLINK, user.telegram_id),
                )
            )
        keyboard.append(buttons)
    keyboard.append(_back_row())
    return InlineKeyboardMarkup(keyboard)


def account_link_cancel_menu(telegram_id: int) -> InlineKeyboardMarkup:
    """The lone Cancel button shown while awaiting a session file for *telegram_id*."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    ACCOUNT_CANCEL_LABEL,
                    callback_data=account_decision(AccountAction.CANCEL, telegram_id),
                )
            ]
        ]
    )


def request_access_menu() -> InlineKeyboardMarkup:
    """The lone *Request access* button shown to a not-yet-allowed user."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    MENU_BUTTON_REQUEST_ACCESS, callback_data=MenuAction.REQUEST_ACCESS
                )
            ]
        ]
    )


def access_alert_menu(telegram_id: int) -> InlineKeyboardMarkup:
    """Grant/Deny buttons on the admin's instant access-request alert."""
    return InlineKeyboardMarkup(
        [
            [
                _decision_button(
                    ACCESS_GRANT_LABEL, CallbackScope.ALERT, AccessStatus.ALLOWED, telegram_id
                ),
                _decision_button(
                    ACCESS_DENY_LABEL, CallbackScope.ALERT, AccessStatus.DENIED, telegram_id
                ),
            ]
        ]
    )


def management_menu(pending: Sequence[User], allowed: Sequence[User]) -> InlineKeyboardMarkup:
    """The admin console: Grant/Deny per pending user, Revoke per allowed user."""
    rows: list[list[InlineKeyboardButton]] = []
    for user in pending:
        rows.append(
            [
                _decision_button(
                    MANAGE_GRANT_PREFIX + user.display_name,
                    CallbackScope.MANAGE,
                    AccessStatus.ALLOWED,
                    user.telegram_id,
                ),
                _decision_button(
                    MANAGE_DENY_PREFIX + user.display_name,
                    CallbackScope.MANAGE,
                    AccessStatus.DENIED,
                    user.telegram_id,
                ),
            ]
        )
    rows.extend(
        [
            _decision_button(
                MANAGE_REVOKE_PREFIX + user.display_name,
                CallbackScope.MANAGE,
                AccessStatus.DENIED,
                user.telegram_id,
            )
        ]
        for user in allowed
    )
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def groups_menu(*, has_groups: bool) -> InlineKeyboardMarkup:
    """The Groups screen: *Añadir* always, *Buscar* only when groups exist, Volver.

    Searching an empty set would be pointless, so the *Buscar* row is omitted
    until the user has saved at least one group.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(GROUP_BUTTON_ADD, callback_data=GroupAction.ADD)]
    ]
    if has_groups:
        rows.append([InlineKeyboardButton(GROUP_BUTTON_SEARCH, callback_data=GroupAction.SEARCH)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def group_search_results_menu(window: GroupSearchPage) -> InlineKeyboardMarkup:
    """A page of fuzzy-search results: per hit a link + quick-delete pair.

    Each result row opens the group's Facebook URL (link button, truncated name)
    next to a 🗑 quick-delete button. A conditional ◀️/▶️ nav row paginates the
    full result set (page numbers ride :class:`~bot.constants.GroupAction.PAGE`),
    and a *Volver* row closes the screen.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                GROUP_RESULT_LINK_PREFIX + _truncate(hit.name or hit.facebook_id),
                url=group_url(hit.facebook_id),
            ),
            InlineKeyboardButton(
                GROUP_RESULT_DELETE_LABEL,
                callback_data=group_decision(GroupAction.QUICK_DELETE, hit.id),
            ),
        ]
        for hit in window.hits
    ]
    nav = _nav_row(window)
    if nav:
        rows.append(nav)
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def group_delete_confirm_menu(group_id: int) -> InlineKeyboardMarkup:
    """Yes/Cancel buttons confirming deletion of the group with id *group_id*."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    GROUP_CONFIRM_DELETE_LABEL,
                    callback_data=group_decision(GroupAction.CONFIRM_DELETE, group_id),
                ),
                InlineKeyboardButton(
                    GROUP_CANCEL_DELETE_LABEL,
                    callback_data=group_decision(GroupAction.CANCEL_DELETE, group_id),
                ),
            ]
        ]
    )


def post_composer_menu(*, has_text: bool, photo_count: int) -> InlineKeyboardMarkup:
    """The live composer's keyboard: editing controls reflecting the draft state.

    *Editar texto* appears once a caption exists; a 🗑 button per photo (wrapped
    into rows of :data:`~bot.constants.POST_PHOTO_REMOVE_PER_ROW`) lets a stray
    upload be removed; *Listo* and *Vaciar* appear once the draft is non-empty.
    *Cancelar* is always present so an empty composer can still be abandoned. The
    final readiness check (text *and* at least one photo) happens on *Listo* tap.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if has_text:
        rows.append(
            [InlineKeyboardButton(POST_BUTTON_EDIT_TEXT, callback_data=PostAction.EDIT_TEXT)]
        )
    rows.extend(_photo_remove_rows(photo_count))
    bottom = [InlineKeyboardButton(POST_BUTTON_CANCEL, callback_data=PostAction.CANCEL)]
    if has_text or photo_count > 0:
        bottom.insert(0, InlineKeyboardButton(POST_BUTTON_CLEAR, callback_data=PostAction.CLEAR))
        bottom.insert(
            0, InlineKeyboardButton(POST_BUTTON_DONE, callback_data=PostAction.PHOTOS_DONE)
        )
    rows.append(bottom)
    return InlineKeyboardMarkup(rows)


def post_confirm_menu() -> InlineKeyboardMarkup:
    """Post-now/Cancel buttons, plus *Guardar como plantilla*, on the confirm screen."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(POST_BUTTON_CONFIRM, callback_data=PostAction.CONFIRM),
                InlineKeyboardButton(POST_BUTTON_CANCEL, callback_data=PostAction.CANCEL),
            ],
            [
                InlineKeyboardButton(
                    POST_BUTTON_SAVE_BLUEPRINT, callback_data=PostAction.SAVE_BLUEPRINT
                )
            ],
        ]
    )


def post_publish_menu() -> InlineKeyboardMarkup:
    """The lone *Cancelar publicación* button shown while a run is in flight."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    POST_BUTTON_CANCEL_PUBLISH, callback_data=PostAction.CANCEL_PUBLISH
                )
            ]
        ]
    )


def post_result_page_menu(window: PostResultPage) -> InlineKeyboardMarkup:
    """The final result summary's keyboard: a ◀️/▶️ nav row (if paged) then *Volver*."""
    rows: list[list[InlineKeyboardButton]] = []
    nav = _result_nav_row(window)
    if nav:
        rows.append(nav)
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def _truncate(name: str, limit: int = GROUP_BUTTON_NAME_MAX_LENGTH) -> str:
    """Shorten a name to fit a button label, with an ellipsis if clipped."""
    if len(name) <= limit:
        return name
    return name[: limit - 1].rstrip() + "…"


def _pagination_row(
    window: GroupSearchPage | PostResultPage,
    prev_label: str,
    next_label: str,
    encode: Callable[[int], str],
) -> list[InlineKeyboardButton]:
    """A ◀️/▶️ nav row for any paged window (empty when there's a single page).

    Shared by every paginated screen: *encode* maps a target page number to that
    screen's ``callback_data`` (so the same arrow logic serves group search and
    post-result summaries without copy-paste).
    """
    buttons: list[InlineKeyboardButton] = []
    if window.has_prev:
        buttons.append(InlineKeyboardButton(prev_label, callback_data=encode(window.page - 1)))
    if window.has_next:
        buttons.append(InlineKeyboardButton(next_label, callback_data=encode(window.page + 1)))
    return buttons


def _nav_row(window: GroupSearchPage) -> list[InlineKeyboardButton]:
    """The ◀️/▶️ pagination row for a group-search results page."""
    return _pagination_row(
        window,
        GROUP_PAGE_PREV_LABEL,
        GROUP_PAGE_NEXT_LABEL,
        lambda page: group_decision(GroupAction.PAGE, page),
    )


def _result_nav_row(window: PostResultPage) -> list[InlineKeyboardButton]:
    """The ◀️/▶️ pagination row for the final post-result summary."""
    return _pagination_row(
        window,
        POST_RESULT_PAGE_PREV_LABEL,
        POST_RESULT_PAGE_NEXT_LABEL,
        post_result_page,
    )


def _photo_remove_rows(photo_count: int) -> list[list[InlineKeyboardButton]]:
    """A 🗑-per-photo grid (1-based labels), wrapped into tappable rows."""
    buttons = [
        InlineKeyboardButton(
            POST_PHOTO_REMOVE_LABEL.format(n=index + 1),
            callback_data=post_photo_decision(index),
        )
        for index in range(photo_count)
    ]
    return [
        buttons[start : start + POST_PHOTO_REMOVE_PER_ROW]
        for start in range(0, len(buttons), POST_PHOTO_REMOVE_PER_ROW)
    ]


def _back_row() -> list[InlineKeyboardButton]:
    """A single-button row returning to the main menu (``MenuAction.MAIN``)."""
    return [InlineKeyboardButton(MENU_BUTTON_BACK, callback_data=MenuAction.MAIN)]


def _decision_button(
    label: str, scope: CallbackScope, status: AccessStatus, telegram_id: int
) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=access_decision(scope, status, telegram_id))


def post_name_menu() -> InlineKeyboardMarkup:
    """The lone Cancel button shown while prompting for a blueprint name."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(POST_BUTTON_CANCEL, callback_data=PostAction.CANCEL)]]
    )


def blueprints_menu(blueprints: Sequence[Blueprint]) -> InlineKeyboardMarkup:
    """The Plantillas list: one row per saved blueprint, then a *Volver* row.

    Each row opens the blueprint's detail screen (its id rides
    :class:`~bot.constants.BlueprintAction.OPEN`).
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                BLUEPRINT_ROW_PREFIX + _truncate(blueprint.name, BLUEPRINT_BUTTON_NAME_MAX_LENGTH),
                callback_data=blueprint_decision(BlueprintAction.OPEN, blueprint.id),
            )
        ]
        for blueprint in blueprints
    ]
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def blueprint_detail_menu(blueprint_id: int, *, has_photos: bool) -> InlineKeyboardMarkup:
    """A blueprint's detail screen: publish / edit / delete (+ preview), then back.

    *Ver imágenes* appears only when the blueprint has stored photos. *Volver*
    returns to the Plantillas list (``MenuAction.BLUEPRINTS``).
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                BLUEPRINT_BUTTON_PUBLISH,
                callback_data=blueprint_decision(BlueprintAction.PUBLISH, blueprint_id),
            ),
            InlineKeyboardButton(
                BLUEPRINT_BUTTON_EDIT,
                callback_data=blueprint_decision(BlueprintAction.EDIT, blueprint_id),
            ),
        ],
        [
            InlineKeyboardButton(
                BLUEPRINT_BUTTON_DELETE,
                callback_data=blueprint_decision(BlueprintAction.DELETE, blueprint_id),
            )
        ],
    ]
    if has_photos:
        rows.append(
            [
                InlineKeyboardButton(
                    BLUEPRINT_BUTTON_SHOW_IMAGES,
                    callback_data=blueprint_decision(BlueprintAction.SHOW_IMAGES, blueprint_id),
                )
            ]
        )
    rows.append([InlineKeyboardButton(MENU_BUTTON_BACK, callback_data=MenuAction.BLUEPRINTS)])
    return InlineKeyboardMarkup(rows)


def blueprint_edit_menu(blueprint_id: int) -> InlineKeyboardMarkup:
    """A blueprint's edit submenu: rename / edit-text, then back to its detail."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    BLUEPRINT_BUTTON_RENAME,
                    callback_data=blueprint_decision(BlueprintAction.RENAME, blueprint_id),
                ),
                InlineKeyboardButton(
                    BLUEPRINT_BUTTON_EDIT_TEXT,
                    callback_data=blueprint_decision(BlueprintAction.EDIT_TEXT, blueprint_id),
                ),
            ],
            [
                InlineKeyboardButton(
                    MENU_BUTTON_BACK,
                    callback_data=blueprint_decision(BlueprintAction.OPEN, blueprint_id),
                )
            ],
        ]
    )


def blueprint_delete_confirm_menu(blueprint_id: int) -> InlineKeyboardMarkup:
    """Yes/Cancel buttons confirming deletion of the blueprint with *blueprint_id*."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    BLUEPRINT_CONFIRM_DELETE_LABEL,
                    callback_data=blueprint_decision(BlueprintAction.CONFIRM_DELETE, blueprint_id),
                ),
                InlineKeyboardButton(
                    BLUEPRINT_CANCEL_LABEL,
                    callback_data=blueprint_decision(BlueprintAction.OPEN, blueprint_id),
                ),
            ]
        ]
    )


def blueprint_edit_cancel_menu(blueprint_id: int) -> InlineKeyboardMarkup:
    """A lone Cancel shown while awaiting the new name / text for a blueprint.

    Cancelling returns to the blueprint's detail (``BlueprintAction.OPEN``), which
    also discards the armed edit.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    BLUEPRINT_CANCEL_LABEL,
                    callback_data=blueprint_decision(BlueprintAction.OPEN, blueprint_id),
                )
            ]
        ]
    )
