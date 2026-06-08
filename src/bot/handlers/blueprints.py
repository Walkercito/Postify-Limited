"""Blueprints feature: list, preview, publish, edit and delete saved posts.

A *blueprint* is a post (text and/or photos) the user saved to reuse later (see
:func:`~bot.handlers.post.publish_blueprint` and the *Guardar como plantilla*
button on the confirm screen). This router owns every screen reached from the
*Plantillas* main-menu button:

* the **list** (``MenuAction.BLUEPRINTS``) — one row per saved blueprint, also the
  return target of every detail/edit *Volver*;
* the **detail** screen (``BlueprintAction.OPEN``) — preview text + photo count,
  with *Publicar* / *Editar* / *Eliminar* and, when photos are stored, a *Ver
  imágenes* button that re-sends them as an album;
* **publish** (``BlueprintAction.PUBLISH``) — hands the stored text + photo
  ``file_id``s to :func:`~bot.handlers.post.publish_blueprint`, which streams the
  same live progress a fresh post does;
* the **edit** submenu (``BlueprintAction.EDIT``) — *Renombrar* / *Editar texto*
  each arm a :class:`~bot.blueprint_edits.PendingBlueprintEdit` so the user's next
  message updates that field; and
* **delete** (``BlueprintAction.DELETE`` → ``CONFIRM_DELETE``).

Every parameterized button carries its blueprint id and routes through one
dispatcher (:meth:`BlueprintsRouter._on_blueprint_decision` → ``_ACTION_HANDLERS``).
Renaming / editing text spans two updates, so a state gate
(:data:`_EDITING_FILTER`) lets this router claim the user's free text *only* while
an edit is armed; otherwise it falls through to ``GroupsRouter``'s link shortcut —
which is why this router is registered *before* ``GroupsRouter``.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, cast

from pyrogram import Client, filters
from pyrogram.types import InputMediaPhoto

from bot.blueprint_edits import PendingBlueprintEdit
from bot.callbacks import BLUEPRINT_DECISION_PATTERN, parse_blueprint_decision
from bot.constants import (
    BLUEPRINT_NAME_MAX_LENGTH,
    POST_PREVIEW_MAX_CHARS,
    BlueprintAction,
    BlueprintField,
    HandlerGroup,
    LogEvent,
    MenuAction,
)
from bot.core.logging import get_logger
from bot.handlers.base import Router
from bot.handlers.edits import edit_message, edit_text
from bot.handlers.guards import allowed_owner, guard_owner
from bot.handlers.middleware import observed, tracks_activity
from bot.handlers.post import publish_blueprint
from bot.keyboards import (
    back_to_menu,
    blueprint_delete_confirm_menu,
    blueprint_detail_menu,
    blueprint_edit_cancel_menu,
    blueprint_edit_menu,
    blueprints_menu,
)
from bot.services.blueprint_service import BlueprintService

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from pyrogram.filters import Filter
    from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

    from bot.core.client import Bot
    from bot.db.models.blueprint import Blueprint
    from bot.db.models.user import User

    _BlueprintHandler = Callable[[Bot, CallbackQuery, User, int], Awaitable[None]]

log = get_logger(__name__)

# Plantillas list.
BLUEPRINTS_HEADER = "📋 <b>Plantillas</b>\n📊 Tienes <b>{count}</b> plantilla(s) guardada(s)."
BLUEPRINTS_EMPTY = (
    "📋 <b>Plantillas</b>\n"
    "📭 Todavía no has guardado ninguna plantilla. "
    "Crea una publicación y pulsa «Guardar como plantilla» para reutilizarla."
)

# Detail screen.
BLUEPRINT_DETAIL_TEMPLATE = "📋 <b>{name}</b>\n\n{text}\n\n📷 {photo_count} foto(s)"
BLUEPRINT_TEXT_PLACEHOLDER = "<i>— sin texto —</i>"

# Edit submenu + the two field-edit prompts.
BLUEPRINT_EDIT_PROMPT = "✏️ ¿Qué quieres editar de esta plantilla?"
BLUEPRINT_RENAME_PROMPT = "🏷 Escríbeme el nuevo nombre para esta plantilla."
BLUEPRINT_RENAME_EMPTY = "✍️ El nombre no puede estar vacío. Escríbeme un nombre para la plantilla."
BLUEPRINT_EDIT_TEXT_PROMPT = "✏️ Escríbeme el nuevo texto para esta plantilla."

# Delete confirmation + terminal / toast feedback.
BLUEPRINT_DELETE_CONFIRM = "🗑 ¿Seguro que quieres eliminar <b>{name}</b>?"
BLUEPRINT_GONE = "⌛ Esa plantilla ya no está disponible."
BLUEPRINT_GONE_TOAST = "Esa plantilla ya no existe."
BLUEPRINT_DELETED_TOAST = "Plantilla eliminada 🗑"
BLUEPRINT_NO_IMAGES_TOAST = "Esta plantilla no tiene imágenes."


async def _editing_predicate(_filter: Filter, client: Client, message: Message) -> bool:
    """True when the sender has a blueprint edit (rename / edit-text) armed."""
    bot = cast("Bot", client)
    user = message.from_user
    return user is not None and bot.blueprint_edits.get(user.id) is not None


# State gate: only claim free text while a blueprint edit is armed, so idle
# messages fall through to GroupsRouter's link shortcut.
_EDITING_FILTER = filters.create(_editing_predicate)


class BlueprintsRouter(Router):
    """Registers the Plantillas list, detail/edit/delete actions and edit replies."""

    def register(self, bot: Bot) -> None:
        self._add_callback_query_handler(
            bot,
            self._on_blueprints,
            filters.regex(rf"^{MenuAction.BLUEPRINTS}$"),
            HandlerGroup.DEFAULT,
        )
        self._add_callback_query_handler(
            bot,
            self._on_blueprint_decision,
            filters.regex(BLUEPRINT_DECISION_PATTERN),
            HandlerGroup.DEFAULT,
        )
        # State-gated edit reply: claimed only while a rename / edit-text is armed.
        self._add_message_handler(
            bot,
            self._on_edit_reply,
            filters.private & filters.text & _EDITING_FILTER,
            HandlerGroup.DEFAULT,
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_blueprints(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        client.blueprint_edits.clear(owner.telegram_id)
        await _render_list(client, callback_query, owner)
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_blueprint_decision(client: Bot, callback_query: CallbackQuery) -> None:
        """Route a parameterized blueprint button to its action handler."""
        data = callback_query.data
        parsed = parse_blueprint_decision(data) if isinstance(data, str) else None
        if parsed is None:
            return
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        # Any blueprint button tap disarms a stale edit; arm actions re-arm below.
        client.blueprint_edits.clear(owner.telegram_id)
        action, blueprint_id = parsed
        handler = _ACTION_HANDLERS.get(action)
        if handler is not None:
            await handler(client, callback_query, owner, blueprint_id)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_edit_reply(client: Bot, message: Message) -> None:
        """Apply a typed rename / new text to the armed blueprint, then refresh it."""
        user = message.from_user
        if user is None:
            return
        pending = client.blueprint_edits.get(user.id)
        if pending is None:
            return
        value = (message.text or "").strip()
        async with client.database.session() as session:
            owner = await allowed_owner(session, user.id)
            if owner is None:
                client.blueprint_edits.clear(user.id)
                return
            service = BlueprintService(session)
            blueprint = await service.find_by_id(owner.id, pending.blueprint_id)
            if blueprint is None:
                client.blueprint_edits.clear(user.id)
                await _edit_card(client, pending, BLUEPRINT_GONE, back_to_menu())
                return
            if pending.field is BlueprintField.NAME and not value:
                await _edit_card(
                    client, pending, BLUEPRINT_RENAME_EMPTY, _cancel_menu(pending.blueprint_id)
                )
                return
            await _apply_edit(service, blueprint, pending.field, value)
            log.info(
                LogEvent.BLUEPRINT_UPDATED,
                blueprint_id=blueprint.id,
                slug=blueprint.slug,
                field=pending.field,
            )
            card = _render_detail(blueprint)
            has_photos = bool(blueprint.photo_file_ids)
        client.blueprint_edits.clear(user.id)
        await _edit_card(
            client,
            pending,
            card,
            blueprint_detail_menu(pending.blueprint_id, has_photos=has_photos),
        )


async def _open_blueprint(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Render a blueprint's detail screen."""
    blueprint = await _load_or_list(client, callback_query, owner, blueprint_id)
    if blueprint is None:
        return
    await edit_text(
        callback_query,
        _render_detail(blueprint),
        reply_markup=blueprint_detail_menu(blueprint_id, has_photos=bool(blueprint.photo_file_ids)),
    )
    await callback_query.answer()


async def _publish_blueprint_to_groups(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Republish a blueprint's stored content to every saved group."""
    blueprint = await _load_or_list(client, callback_query, owner, blueprint_id)
    if blueprint is None:
        return
    await publish_blueprint(
        client,
        callback_query,
        owner,
        text=blueprint.text,
        photo_file_ids=blueprint.photo_file_ids,
    )


async def _open_edit(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Open the rename / edit-text submenu for a blueprint."""
    blueprint = await _load_or_list(client, callback_query, owner, blueprint_id)
    if blueprint is None:
        return
    await edit_text(
        callback_query, BLUEPRINT_EDIT_PROMPT, reply_markup=blueprint_edit_menu(blueprint_id)
    )
    await callback_query.answer()


async def _arm_rename(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Arm a rename: the user's next message becomes the new name."""
    await _arm_edit(
        client, callback_query, owner, blueprint_id, BlueprintField.NAME, BLUEPRINT_RENAME_PROMPT
    )


async def _arm_edit_text(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Arm a text edit: the user's next message becomes the new body."""
    await _arm_edit(
        client, callback_query, owner, blueprint_id, BlueprintField.TEXT, BLUEPRINT_EDIT_TEXT_PROMPT
    )


async def _ask_delete(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Show the delete confirmation for a blueprint."""
    blueprint = await _load_or_list(client, callback_query, owner, blueprint_id)
    if blueprint is None:
        return
    await edit_text(
        callback_query,
        BLUEPRINT_DELETE_CONFIRM.format(name=html.escape(blueprint.name)),
        reply_markup=blueprint_delete_confirm_menu(blueprint_id),
    )
    await callback_query.answer()


async def _do_delete(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Remove a blueprint and return to the (now shorter) list."""
    async with client.database.session() as session:
        removed = await BlueprintService(session).remove_by_id(owner.id, blueprint_id)
        slug = removed.slug if removed is not None else None
    if removed is not None:
        log.info(LogEvent.BLUEPRINT_REMOVED, blueprint_id=blueprint_id, slug=slug)
    await _render_list(client, callback_query, owner)
    await callback_query.answer(
        BLUEPRINT_DELETED_TOAST if removed is not None else BLUEPRINT_GONE_TOAST
    )


async def _show_images(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> None:
    """Re-send a blueprint's stored photos as an album (or a single photo)."""
    blueprint = await _load_or_list(client, callback_query, owner, blueprint_id)
    if blueprint is None:
        return
    file_ids = list(blueprint.photo_file_ids)
    location = _card_location(callback_query)
    if not file_ids or location is None:
        await callback_query.answer(BLUEPRINT_NO_IMAGES_TOAST)
        return
    await _send_photos(client, location[0], file_ids)
    await callback_query.answer()


# Maps each parameterized blueprint action to its handler (defined above so the
# references resolve). The dispatcher looks this up at call time.
_ACTION_HANDLERS: dict[BlueprintAction, _BlueprintHandler] = {
    BlueprintAction.OPEN: _open_blueprint,
    BlueprintAction.PUBLISH: _publish_blueprint_to_groups,
    BlueprintAction.EDIT: _open_edit,
    BlueprintAction.RENAME: _arm_rename,
    BlueprintAction.EDIT_TEXT: _arm_edit_text,
    BlueprintAction.DELETE: _ask_delete,
    BlueprintAction.CONFIRM_DELETE: _do_delete,
    BlueprintAction.SHOW_IMAGES: _show_images,
}


async def _arm_edit(
    client: Bot,
    callback_query: CallbackQuery,
    owner: User,
    blueprint_id: int,
    field: BlueprintField,
    prompt: str,
) -> None:
    """Verify the blueprint, remember which field the next message edits, and prompt."""
    blueprint = await _load_or_list(client, callback_query, owner, blueprint_id)
    if blueprint is None:
        return
    location = _card_location(callback_query)
    if location is None:
        await callback_query.answer()
        return
    chat_id, message_id = location
    client.blueprint_edits.begin(
        owner.telegram_id,
        PendingBlueprintEdit(
            blueprint_id=blueprint_id, field=field, chat_id=chat_id, message_id=message_id
        ),
    )
    await edit_text(callback_query, prompt, reply_markup=_cancel_menu(blueprint_id))
    await callback_query.answer()


async def _apply_edit(
    service: BlueprintService, blueprint: Blueprint, field: BlueprintField, value: str
) -> None:
    """Persist a rename (truncated) or a text replacement (blank clears the body)."""
    if field is BlueprintField.NAME:
        await service.rename(blueprint, value[:BLUEPRINT_NAME_MAX_LENGTH])
    else:
        await service.set_text(blueprint, value or None)


async def _load_or_list(
    client: Bot, callback_query: CallbackQuery, owner: User, blueprint_id: int
) -> Blueprint | None:
    """Fetch the owner's blueprint, or fall back to the list if it's gone (answered).

    Centralizes the "stale button → blueprint no longer exists" path: on a miss it
    re-renders the list, toasts, and returns ``None`` so the caller just returns.
    """
    async with client.database.session() as session:
        blueprint = await BlueprintService(session).find_by_id(owner.id, blueprint_id)
    if blueprint is None:
        await _render_list(client, callback_query, owner)
        await callback_query.answer(BLUEPRINT_GONE_TOAST)
    return blueprint


async def _render_list(client: Bot, callback_query: CallbackQuery, owner: User) -> None:
    """Render the owner's Plantillas list into the callback message (does not answer)."""
    async with client.database.session() as session:
        blueprints = await BlueprintService(session).list_for_user(owner.id)
    text = BLUEPRINTS_HEADER.format(count=len(blueprints)) if blueprints else BLUEPRINTS_EMPTY
    await edit_text(callback_query, text, reply_markup=blueprints_menu(blueprints))


async def _edit_card(
    client: Bot, pending: PendingBlueprintEdit, text: str, markup: InlineKeyboardMarkup
) -> None:
    """Re-render the detail card a pending edit points at (by chat / message id)."""
    await edit_message(client, pending.chat_id, pending.message_id, text, reply_markup=markup)


async def _send_photos(client: Bot, chat_id: int, file_ids: Sequence[str]) -> None:
    """Send the stored photos: a media-group album for several, a single photo for one."""
    if len(file_ids) == 1:
        await client.send_photo(chat_id, file_ids[0])
        return
    await client.send_media_group(chat_id, [InputMediaPhoto(file_id) for file_id in file_ids])


def _cancel_menu(blueprint_id: int) -> InlineKeyboardMarkup:
    """The lone Cancel keyboard shown while awaiting an edit reply."""
    return blueprint_edit_cancel_menu(blueprint_id)


def _render_detail(blueprint: Blueprint) -> str:
    """Build a blueprint's detail body: name, (capped) text preview and photo count."""
    return BLUEPRINT_DETAIL_TEMPLATE.format(
        name=html.escape(blueprint.name),
        text=_render_preview(blueprint.text),
        photo_count=len(blueprint.photo_file_ids),
    )


def _render_preview(text: str | None) -> str:
    """Escaped, length-capped text for display, or a placeholder when there is none."""
    raw = (text or "").strip()
    if not raw:
        return BLUEPRINT_TEXT_PLACEHOLDER
    if len(raw) > POST_PREVIEW_MAX_CHARS:
        raw = raw[:POST_PREVIEW_MAX_CHARS] + "…"
    return html.escape(raw)


def _card_location(callback_query: CallbackQuery) -> tuple[int, int] | None:
    """The ``(chat_id, message_id)`` of the card a blueprint callback rode in on."""
    message = callback_query.message
    if message is None or message.chat is None or message.chat.id is None:
        return None
    return message.chat.id, message.id
