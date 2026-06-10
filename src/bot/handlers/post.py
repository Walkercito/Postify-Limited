"""Post-composition flow: compose a post once, publish it to every saved group.

The composer keeps the user's own messages in the chat and floats a *single
control card* beneath them. The card (text preview + photo count + the
*Listo / Editar texto / Vaciar / Cancelar* controls) is re-sent at the bottom each
time the user adds something and the previous card is deleted, so the controls are
always reachable below the latest input — the inputs themselves are never removed.

* *Start a post* (main-menu button) checks the user has a linked Facebook account
  and at least one saved group, then opens a fresh draft and renders the empty
  composer into the tapped message;
* each private text becomes (or replaces) the caption; each photo is buffered up
  to :data:`~bot.constants.POST_MAX_PHOTOS`. Telegram delivers an album as a rapid
  burst of separate photo messages, so the re-float is *debounced*
  (:data:`~bot.constants.POST_ALBUM_DEBOUNCE_SEC`): each input (re)schedules a
  detached task and only the final item of a burst floats one fresh card;
* *Listo* → a confirmation screen → *Publicar ya* downloads the photos to a temp
  directory and streams them to :class:`~bot.services.post_service.PostService`,
  whose async generator yields one per-group result as it resolves. Each yield
  re-renders a throttled progress view (Unicode bar + per-group list) carrying a
  *Cancelar publicación* button; tapping it sets a :class:`asyncio.Event` the
  publish loop honours cooperatively (the in-flight group finishes, the rest are
  marked cancelled);
* *Guardar como plantilla* (on the confirm screen) prompts for a name and saves
  the draft's text + photo ``file_id``s as a reusable blueprint instead of
  publishing. :func:`publish_blueprint` runs the reverse: it rehydrates a transient
  draft from a saved blueprint and drives the same publish path.

The "currently composing" state is the mere *presence* of a draft, so a custom
filter (:data:`_COMPOSING_FILTER`) lets this router claim the user's free text and
photos while a draft is open; otherwise they fall through to
:class:`~bot.handlers.groups.GroupsRouter`'s always-on link shortcut. That is why
this router must be registered *before* ``GroupsRouter``.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pyrogram import Client, filters
from pyrogram.errors import RPCError

from bot.callbacks import (
    POST_PHOTO_DECISION_PATTERN,
    POST_RESULT_PAGE_PATTERN,
    parse_post_photo_decision,
    parse_post_result_page,
)
from bot.constants import (
    BLUEPRINT_NAME_MAX_LENGTH,
    POST_ALBUM_DEBOUNCE_SEC,
    POST_CIRCADIAN_MIDNIGHT_DISPLAY_HOUR,
    POST_GROUP_LIMIT,
    POST_MAX_PHOTOS,
    POST_PHOTO_FILE_SUFFIX,
    POST_PREVIEW_MAX_CHARS,
    POST_PROGRESS_BAR_EMPTY,
    POST_PROGRESS_BAR_FILLED,
    POST_PROGRESS_BAR_WIDTH,
    POST_PROGRESS_MAX_LINES,
    POST_PROGRESS_THROTTLE_SEC,
    POST_RESULT_PAGE_INDICATOR,
    POST_RESULT_PAGE_SIZE,
    HandlerGroup,
    LogEvent,
    MenuAction,
    PostAction,
    PostFailure,
    PostGate,
)
from bot.core.logging import get_logger
from bot.db.base import utcnow
from bot.facebook_web import decode_cookies
from bot.handlers.base import Router
from bot.handlers.edits import edit_message, edit_text
from bot.handlers.guards import allowed_owner, guard_owner
from bot.handlers.middleware import observed, tracks_activity
from bot.keyboards import (
    back_to_menu,
    post_composer_menu,
    post_confirm_menu,
    post_name_menu,
    post_publish_menu,
    post_result_page_menu,
)
from bot.services.account_post_limit_service import AccountPostLimitService, GateDecision
from bot.services.blueprint_service import BlueprintService
from bot.services.facebook_account_service import FacebookAccountService
from bot.services.group_service import GroupService
from bot.services.post_service import GroupPostResult, PostService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pyrogram.filters import Filter
    from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

    from bot.core.client import Bot
    from bot.core.config import PostLimitsSettings
    from bot.db.models.facebook_account import FacebookAccount
    from bot.db.models.user import User
    from bot.post_drafts import PostDraft
    from bot.post_results import PostResultPage

log = get_logger(__name__)

# Dead ends at *Start a post*: nothing to post with, or nowhere to post to.
POST_NO_ACCOUNT = (
    "🔗 Todavía no tienes una cuenta de Facebook vinculada. "
    "Pídele al administrador que vincule la tuya."
)
POST_NO_GROUPS = (
    "👥 Todavía no has guardado ningún grupo. Añade uno antes de crear una publicación."
)

# Live composer (the control card re-floated below the user's inputs).
POST_COMPOSER_EMPTY = (
    "📝 <b>Nueva publicación</b>\n\n"
    "Envíame el <b>texto</b> y luego de 1 a 10 <b>fotos</b>.\n"
    "Esta vista previa se irá actualizando a medida que lo construyas."
)
POST_COMPOSER_TEMPLATE = (
    "📝 <b>Nueva publicación</b>\n\n{text}\n\n📷 {photo_count} foto(s)\n\n{hint}"
)
POST_COMPOSER_TEXT_PLACEHOLDER = "<i>— aún sin texto —</i>"

# Context hints shown at the foot of the composer, one per outstanding step.
POST_HINT_NEED_TEXT = "✍️ Falta el texto: envíamelo en un mensaje."
POST_HINT_NEED_PHOTO = "📷 Ahora envíame al menos una foto."
POST_HINT_PHOTO_LIMIT = "✅ Llegaste al límite de {limit} fotos. Pulsa Listo para continuar."
POST_HINT_READY = "✅ Todo listo. Pulsa Listo para revisar y publicar."

# Validation toasts (shown on the buttons when the draft isn't ready).
POST_NEED_TEXT_TOAST = "✍️ Primero envíame el texto de la publicación."
POST_NEED_PHOTO_TOAST = "📷 Primero añade al menos una foto."

# Edit-control toasts (the composer re-renders to reflect each change).
POST_EDIT_TEXT_TOAST = "✍️ Envíame el nuevo texto y reemplazará al actual."
POST_PHOTO_REMOVED_TOAST = "Foto eliminada 🗑"
POST_CLEARED_TOAST = "Vaciado 🧹"

# Save-as-blueprint naming sub-flow (entered from the confirm screen).
POST_NAME_PROMPT = "💾 Escríbeme un nombre para esta plantilla."
POST_NAME_EMPTY = "✍️ El nombre no puede estar vacío. Escríbeme un nombre para la plantilla."
POST_BLUEPRINT_SAVED = "✅ Plantilla guardada: <b>{name}</b>"

# Cancel-during-publish toasts.
POST_CANCELLING_TOAST = "🚫 Cancelando… termino el grupo en curso."
POST_NOT_PUBLISHING_TOAST = "Esta publicación ya terminó."

# Confirmation screen.
POST_CONFIRM_TEMPLATE = (
    "📋 <b>Revisa antes de publicar</b>\n\n"
    "{text}\n\n"
    "📷 {photo_count} foto(s)\n"
    "👥 {group_count} grupo(s)\n\n"
    "¿Publicar ahora?"
)

# Realtime progress view: a titled header (bar + tallies) over a per-group list.
POST_PUBLISH_TITLE = "🚀 <b>Publicando…</b>"
POST_PUBLISH_DONE_TITLE = "✅ <b>Publicación completada</b>"
POST_PUBLISH_CANCELLED_TITLE = "🚫 <b>Publicación cancelada</b>"
POST_PROGRESS_HEADER = (
    "{title}\n\n{bar} {pct}%\n✅ {ok} · ⏳ {pending} · ❌ {other} · {done}/{total} grupos"
)
POST_LINE_OK = '✅ <b>{name}</b> → <a href="{url}">ver</a>'
POST_LINE_PENDING = "⏳ <b>{name}</b> — esperando aprobación"
POST_LINE_FAIL = "❌ <b>{name}</b> — {reason}"
POST_LINE_CANCELLED = "⊘ <b>{name}</b> — cancelado"
POST_LINE_IN_PROGRESS = "⌛ <b>{name}</b> — publicando…"
POST_LINE_QUEUED = "• {count} grupo(s) en cola"
POST_PROGRESS_OVERFLOW = "… y {extra} grupo(s) más"

# Terminal / interrupt screens.
POST_CANCELLED = "🚮 Publicación cancelada."
POST_DRAFT_EXPIRED = "⌛ Esa publicación ya no está disponible. Empieza una nueva."
POST_DOWNLOAD_FAILED = "⚠️ No pude descargar tus fotos. Inténtalo de nuevo."

# A failed group shows the user a calm, actionable line — never the raw engine
# error (which goes to the admin instead). Keyed by the failure category.
POST_FAIL_REASON_DEFAULT = "No se pudo publicar esta vez. Vuelve a intentarlo en un momento."
POST_FAIL_REASONS = {
    PostFailure.RATE_LIMITED: (
        "Facebook limitó esta cuenta por ahora. Espera un rato y vuelve a intentarlo."
    ),
    PostFailure.SESSION_EXPIRED: (
        "La sesión de Facebook caducó. Hay que volver a vincular la cuenta antes de publicar."
    ),
    PostFailure.STOPPED: (
        "Se detuvo la publicación tras varios fallos seguidos. No se intentó en este grupo."
    ),
    PostFailure.DAILY_CAP_REACHED: (
        "Esta cuenta alcanzó su límite diario de publicaciones. No se intentó en este grupo."
    ),
    PostFailure.GENERIC: POST_FAIL_REASON_DEFAULT,
}

# A behaviour-only publish guard refused the run before it started — the user sees
# a calm "not now" with the reason; the content is untouched. CIRCADIAN formats the
# configured active window so the user knows when to come back.
POST_GATE_CIRCADIAN = (
    "🌙 Por ahora las publicaciones están en pausa fuera del horario activo "
    "({start_hour:02d}:{start_minute:02d} - {end_hour:02d}:{end_minute:02d}). "
    "Vuelve a intentarlo dentro de ese horario."
)
POST_GATE_BACKOFF = (
    "⏳ Esta cuenta está descansando tras unos bloqueos recientes de Facebook. "
    "Espera un rato antes de volver a publicar."
)
POST_GATE_DAILY_CAP = (
    "📊 Esta cuenta ya alcanzó su límite de publicaciones por hoy. Vuelve a intentarlo mañana."
)
POST_GATE_BLOCKED_DEFAULT = "🚫 No se puede publicar en este momento. Inténtalo más tarde."
POST_GATE_MESSAGES = {
    PostGate.BACKOFF: POST_GATE_BACKOFF,
    PostGate.DAILY_CAP: POST_GATE_DAILY_CAP,
}

# Per-group failure categories that mark a finished run as soft-blocked, which
# escalates the account's cross-run cooldown.
_SOFT_BLOCK_FAILURES = frozenset({PostFailure.RATE_LIMITED, PostFailure.SESSION_EXPIRED})

# Consolidated technical note sent to the admin when groups fail (English, like
# the rest of the admin error reports — it carries the raw engine reason).
POST_ADMIN_FAILURE_HEADER = "⚠️ <b>Post failures</b> — {user} (<code>{user_id}</code>)"
POST_ADMIN_FAILURE_LINE = "• <b>{name}</b> — {reason}"


@dataclass(slots=True)
class _PublishPlan:
    """The resolved inputs of one publish run, addressed at the sticky message.

    ``remaining_cap`` is the account's rolling daily-cap budget for this run (from
    the pre-flight gate): the publish loop attempts at most that many groups and
    skips the rest. ``None`` means uncapped.
    """

    account: FacebookAccount
    facebook_ids: list[str]
    name_by_id: dict[str, str]
    chat_id: int
    message_id: int
    user_id: int
    remaining_cap: int | None = None


@dataclass(slots=True)
class _Tally:
    """Per-outcome counts across the results gathered so far."""

    ok: int = 0
    pending: int = 0
    failed: int = 0
    cancelled: int = 0


async def _composing_predicate(_filter: Filter, client: Client, message: Message) -> bool:
    """True when the message's sender has an open post draft (is composing)."""
    bot = cast("Bot", client)
    user = message.from_user
    return user is not None and bot.post_drafts.is_active(user.id)


# State gate: only claim free text / photos while a draft is in progress, so
# idle messages fall through to GroupsRouter's link shortcut.
_COMPOSING_FILTER = filters.create(_composing_predicate)


class PostRouter(Router):
    """Registers the *Start a post* button and the compose/confirm/publish flow."""

    def register(self, bot: Bot) -> None:
        self._add_callback_query_handler(
            bot,
            self._on_start_post,
            filters.regex(rf"^{MenuAction.START_POST}$"),
            HandlerGroup.DEFAULT,
        )
        callbacks = {
            PostAction.PHOTOS_DONE: self._on_photos_done,
            PostAction.EDIT_TEXT: self._on_edit_text,
            PostAction.CLEAR: self._on_clear,
            PostAction.CONFIRM: self._on_confirm,
            PostAction.CANCEL: self._on_cancel,
            PostAction.CANCEL_PUBLISH: self._on_cancel_publish,
            PostAction.SAVE_BLUEPRINT: self._on_save_blueprint,
        }
        for action, handler in callbacks.items():
            self._add_callback_query_handler(
                bot, handler, filters.regex(rf"^{action}$"), HandlerGroup.DEFAULT
            )
        self._add_callback_query_handler(
            bot,
            self._on_remove_photo,
            filters.regex(POST_PHOTO_DECISION_PATTERN),
            HandlerGroup.DEFAULT,
        )
        self._add_callback_query_handler(
            bot,
            self._on_result_page,
            filters.regex(POST_RESULT_PAGE_PATTERN),
            HandlerGroup.DEFAULT,
        )
        self._add_message_handler(
            bot,
            self._on_text,
            filters.private & filters.text & _COMPOSING_FILTER,
            HandlerGroup.DEFAULT,
        )
        self._add_message_handler(
            bot,
            self._on_photo,
            filters.private & filters.photo & _COMPOSING_FILTER,
            HandlerGroup.DEFAULT,
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_start_post(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        async with client.database.session() as session:
            account = await FacebookAccountService(session).get_for_user(owner.id)
            groups = await GroupService(session).list_for_user(owner.id, limit=POST_GROUP_LIMIT)
        location = _sticky_location(callback_query)
        if account is None or not groups or location is None:
            await _end(callback_query, _blocked_reason(location, account, bool(groups)))
            return
        client.conversations.clear(owner.telegram_id)
        draft = client.post_drafts.start(owner.telegram_id)
        draft.bind_message(*location)
        await edit_text(
            callback_query,
            _render_composer(draft),
            reply_markup=post_composer_menu(has_text=False, photo_count=0),
        )
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_text(client: Bot, message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        draft = client.post_drafts.get(user.id)
        if draft is None or draft.is_publishing:
            return
        if draft.naming:
            await _save_blueprint(client, message, user.id, draft)
            return
        draft.text = message.text
        _schedule_refloat(client, draft, user.id)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_photo(client: Bot, message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        draft = client.post_drafts.get(user.id)
        if draft is None or draft.is_publishing or draft.naming:
            return
        # An album's caption rides on its first photo; adopt it if still untexted.
        if not draft.has_text and message.caption:
            draft.text = message.caption
        if draft.photo_count < POST_MAX_PHOTOS and message.photo is not None:
            draft.photo_file_ids.append(message.photo.file_id)
        _schedule_refloat(client, draft, user.id)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_photos_done(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        draft = client.post_drafts.get(owner.telegram_id)
        if draft is None:
            await _end(callback_query, POST_DRAFT_EXPIRED)
            return
        draft.cancel_render()
        if not draft.has_text:
            await callback_query.answer(POST_NEED_TEXT_TOAST, show_alert=True)
            return
        if draft.photo_count == 0:
            await callback_query.answer(POST_NEED_PHOTO_TOAST, show_alert=True)
            return
        async with client.database.session() as session:
            groups = await GroupService(session).list_for_user(owner.id, limit=POST_GROUP_LIMIT)
        if not groups:
            client.post_drafts.clear(owner.telegram_id)
            await _end(callback_query, POST_NO_GROUPS)
            return
        text = POST_CONFIRM_TEMPLATE.format(
            text=_render_preview_text(draft.text),
            photo_count=draft.photo_count,
            group_count=len(groups),
        )
        await edit_text(callback_query, text, reply_markup=post_confirm_menu())
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_confirm(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        draft = client.post_drafts.get(owner.telegram_id)
        if draft is None or draft.is_empty or not draft.has_text or draft.photo_count == 0:
            client.post_drafts.clear(owner.telegram_id)
            await _end(callback_query, POST_DRAFT_EXPIRED)
            return
        if draft.is_publishing:
            await callback_query.answer()
            return
        await _run_post(client, callback_query, owner, draft)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_save_blueprint(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        draft = client.post_drafts.get(owner.telegram_id)
        if draft is None or draft.is_empty:
            client.post_drafts.clear(owner.telegram_id)
            await _end(callback_query, POST_DRAFT_EXPIRED)
            return
        if draft.is_publishing:
            await callback_query.answer()
            return
        draft.cancel_render()
        draft.naming = True
        await edit_text(callback_query, POST_NAME_PROMPT, reply_markup=post_name_menu())
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_cancel(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        draft = client.post_drafts.get(owner.telegram_id)
        if draft is not None:
            draft.cancel_render()
        client.post_drafts.clear(owner.telegram_id)
        await _end(callback_query, POST_CANCELLED)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_cancel_publish(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        draft = client.post_drafts.get(owner.telegram_id)
        if draft is None or draft.cancel_event is None:
            await callback_query.answer(POST_NOT_PUBLISHING_TOAST)
            return
        draft.cancel_event.set()
        await callback_query.answer(POST_CANCELLING_TOAST)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_edit_text(client: Bot, callback_query: CallbackQuery) -> None:
        draft = await _composing_draft(client, callback_query)
        if draft is None:
            return
        await callback_query.answer(POST_EDIT_TEXT_TOAST)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_clear(client: Bot, callback_query: CallbackQuery) -> None:
        draft = await _composing_draft(client, callback_query)
        if draft is None:
            return
        draft.reset_content()
        await _refresh_composer(client, draft)
        await callback_query.answer(POST_CLEARED_TOAST)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_remove_photo(client: Bot, callback_query: CallbackQuery) -> None:
        draft = await _composing_draft(client, callback_query)
        if draft is None:
            return
        data = callback_query.data
        index = parse_post_photo_decision(data) if isinstance(data, str) else None
        if index is None:
            await callback_query.answer()
            return
        removed = draft.remove_photo(index)
        await _refresh_composer(client, draft)
        await callback_query.answer(POST_PHOTO_REMOVED_TOAST if removed else "")

    @staticmethod
    @observed
    @tracks_activity
    async def _on_result_page(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        result_set = client.post_results.get(owner.telegram_id)
        data = callback_query.data
        page = parse_post_result_page(data) if isinstance(data, str) else None
        if result_set is None or page is None:
            await callback_query.answer()
            return
        result_set.go_to(page)
        window = result_set.window(POST_RESULT_PAGE_SIZE)
        await edit_text(
            callback_query,
            _render_result_page(result_set.header, window),
            reply_markup=post_result_page_menu(window),
        )
        await callback_query.answer()


async def _composing_draft(client: Bot, callback_query: CallbackQuery) -> PostDraft | None:
    """The owner's draft while it's still being *composed*, else ``None`` (answered).

    Guards owner, presence, and phase in one place so the edit-control handlers
    never touch a missing or already-publishing draft. A pending album re-float is
    cancelled here so it can't fight the in-place edit the caller is about to make.
    """
    owner = await guard_owner(client, callback_query)
    if owner is None:
        return None
    draft = client.post_drafts.get(owner.telegram_id)
    if draft is None or draft.is_publishing:
        await callback_query.answer()
        return None
    draft.cancel_render()
    return draft


def _schedule_refloat(client: Bot, draft: PostDraft, user_id: int) -> None:
    """(Re)arm the debounced re-float so only the last input of a burst renders."""
    draft.cancel_render()
    draft.render_task = asyncio.create_task(_debounced_refloat(client, draft, user_id))


async def _debounced_refloat(client: Bot, draft: PostDraft, user_id: int) -> None:
    """After the album-burst debounce settles, float one fresh control card.

    Detached from any ``observed`` wrapper, so it owns its error handling: an
    unexpected failure is logged and reported to the admin instead of vanishing.
    Cancellation (a newer input rescheduling) propagates out of the sleep cleanly.
    """
    await asyncio.sleep(POST_ALBUM_DEBOUNCE_SEC)
    if client.post_drafts.get(user_id) is not draft or draft.is_publishing or draft.naming:
        return
    try:
        await _refloat_card(client, draft)
    except Exception as exc:
        log.exception(LogEvent.POST_REFLOAT_FAILED)
        await client.error_reporter.report(exc, context={"event": LogEvent.POST_REFLOAT_FAILED})


async def _refloat_card(client: Bot, draft: PostDraft) -> None:
    """Send a fresh control card at the bottom and delete the previous one."""
    if draft.chat_id is None:
        return
    chat_id = draft.chat_id
    previous_id = draft.message_id
    sent = await client.send_message(
        chat_id,
        _render_composer(draft),
        reply_markup=post_composer_menu(has_text=draft.has_text, photo_count=draft.photo_count),
    )
    draft.bind_message(chat_id, sent.id)
    if previous_id is not None:
        with contextlib.suppress(RPCError):
            await client.delete_messages(chat_id, previous_id)


async def _save_blueprint(client: Bot, message: Message, user_id: int, draft: PostDraft) -> None:
    """Persist the composed draft as a named blueprint from the user's typed name."""
    name = (message.text or "").strip()
    if not name:
        await _reprompt_name(client, draft)
        return
    async with client.database.session() as session:
        owner = await allowed_owner(session, user_id)
        if owner is None:
            client.post_drafts.clear(user_id)
            return
        blueprint = await BlueprintService(session).create(
            owner.id,
            name[:BLUEPRINT_NAME_MAX_LENGTH],
            text=draft.text,
            photo_file_ids=draft.photo_file_ids,
        )
        log.info(
            LogEvent.BLUEPRINT_SAVED,
            blueprint_id=blueprint.id,
            slug=blueprint.slug,
            photos=len(blueprint.photo_file_ids),
            has_text=bool(blueprint.text and blueprint.text.strip()),
        )
        saved_name = blueprint.name
    client.post_drafts.clear(user_id)
    await _finish_blueprint(client, draft, saved_name)


async def _reprompt_name(client: Bot, draft: PostDraft) -> None:
    """Re-show the name prompt after the user sent a blank name."""
    if draft.chat_id is None or draft.message_id is None:
        return
    await edit_message(
        client, draft.chat_id, draft.message_id, POST_NAME_EMPTY, reply_markup=post_name_menu()
    )


async def _finish_blueprint(client: Bot, draft: PostDraft, name: str) -> None:
    """Render the saved-blueprint confirmation into the control card."""
    if draft.chat_id is None or draft.message_id is None:
        return
    await edit_message(
        client,
        draft.chat_id,
        draft.message_id,
        POST_BLUEPRINT_SAVED.format(name=html.escape(name)),
        reply_markup=back_to_menu(),
    )


async def _end(callback_query: CallbackQuery, text: str) -> None:
    """Replace the screen with a terminal message + a *Volver* button."""
    await edit_text(callback_query, text, reply_markup=back_to_menu())
    await callback_query.answer()


def _sticky_location(callback_query: CallbackQuery) -> tuple[int, int] | None:
    """The ``(chat_id, message_id)`` of the message a callback rode in on, if any."""
    message = callback_query.message
    if message is None:
        return None
    chat = message.chat
    if chat is None or chat.id is None:
        return None
    return chat.id, message.id


def _blocked_reason(
    location: tuple[int, int] | None, account: FacebookAccount | None, has_groups: bool
) -> str:
    """Which precondition stopped *Start a post* (missing message / account / groups)."""
    if location is None:
        return POST_DRAFT_EXPIRED
    if account is None:
        return POST_NO_ACCOUNT
    return POST_NO_GROUPS if not has_groups else POST_DRAFT_EXPIRED


async def _refresh_composer(client: Bot, draft: PostDraft) -> None:
    """Re-render the control card in place to mirror the draft's current state.

    Used by the callback-driven edit controls (clear / remove-photo), which keep
    the card where it is; the message-driven inputs re-float a fresh card instead.
    """
    if draft.chat_id is None or draft.message_id is None:
        return
    await edit_message(
        client,
        draft.chat_id,
        draft.message_id,
        _render_composer(draft),
        reply_markup=post_composer_menu(has_text=draft.has_text, photo_count=draft.photo_count),
    )


def _render_composer(draft: PostDraft) -> str:
    """Build the live composer body: empty prompt, or preview + photo count + hint."""
    if draft.is_empty:
        return POST_COMPOSER_EMPTY
    text = _render_preview_text(draft.text) if draft.has_text else POST_COMPOSER_TEXT_PLACEHOLDER
    return POST_COMPOSER_TEMPLATE.format(
        text=text, photo_count=draft.photo_count, hint=_composer_hint(draft)
    )


def _composer_hint(draft: PostDraft) -> str:
    """The next-step nudge shown under the preview, by what the draft still needs."""
    if not draft.has_text:
        return POST_HINT_NEED_TEXT
    if draft.photo_count == 0:
        return POST_HINT_NEED_PHOTO
    if draft.photo_count >= POST_MAX_PHOTOS:
        return POST_HINT_PHOTO_LIMIT.format(limit=POST_MAX_PHOTOS)
    return POST_HINT_READY


def _render_preview_text(text: str | None) -> str:
    """Escaped, length-capped caption for display (the full text is still posted)."""
    raw = (text or "").strip()
    if len(raw) > POST_PREVIEW_MAX_CHARS:
        raw = raw[:POST_PREVIEW_MAX_CHARS] + "…"
    return html.escape(raw)


async def publish_blueprint(
    client: Bot,
    callback_query: CallbackQuery,
    owner: User,
    *,
    text: str | None,
    photo_file_ids: Sequence[str],
) -> None:
    """Publish a saved blueprint's content, reusing the live post-run machinery.

    Rehydrates a transient draft from the blueprint's stored text + photo
    ``file_id``s and drives the same :func:`_run_post` path the confirm screen
    uses, so a republish streams identical live progress into the callback message.
    """
    draft = client.post_drafts.start(owner.telegram_id)
    draft.text = text
    draft.photo_file_ids = list(photo_file_ids)
    await _run_post(client, callback_query, owner, draft)


async def _run_post(
    client: Bot, callback_query: CallbackQuery, owner: User, draft: PostDraft
) -> None:
    """Resolve the account + groups and stream the publish into the sticky message."""
    draft.cancel_render()
    async with client.database.session() as session:
        account = await FacebookAccountService(session).get_for_user(owner.id)
        groups = await GroupService(session).list_for_user(owner.id, limit=POST_GROUP_LIMIT)
    location = _sticky_location(callback_query)
    if account is None or not groups or location is None:
        client.post_drafts.clear(owner.telegram_id)
        await _end(callback_query, _blocked_reason(location, account, bool(groups)))
        return
    decision = await _evaluate_gate(client, account)
    if decision.gate is not PostGate.OK:
        log.info(LogEvent.POST_GATE_BLOCKED, gate=decision.gate, fb_uid=account.fb_uid)
        client.post_drafts.clear(owner.telegram_id)
        await _end(callback_query, _gate_message(decision.gate, client.settings.post_limits))
        return
    draft.begin_publishing()
    await callback_query.answer()
    chat_id, message_id = location
    plan = _PublishPlan(
        account=account,
        facebook_ids=[group.facebook_id for group in groups],
        name_by_id={group.facebook_id: group.name or group.facebook_id for group in groups},
        chat_id=chat_id,
        message_id=message_id,
        user_id=owner.telegram_id,
        remaining_cap=decision.remaining_cap,
    )
    results = await _run_publish(client, draft, plan)
    cancelled = bool(draft.cancel_event and draft.cancel_event.is_set())
    client.post_drafts.clear(owner.telegram_id)
    if results is None:
        await edit_message(
            client, plan.chat_id, plan.message_id, POST_DOWNLOAD_FAILED, reply_markup=back_to_menu()
        )
        return
    await _record_run(client, plan, results)
    _log_outcome(results, cancelled=cancelled)
    await _report_failures(client, owner, results, plan.name_by_id)


async def _evaluate_gate(client: Bot, account: FacebookAccount) -> GateDecision:
    """Run the pre-flight publish guards for *account* (read-only, its own session)."""
    async with client.database.session() as session:
        service = AccountPostLimitService(session, client.settings.post_limits)
        return await service.evaluate(fb_uid=account.fb_uid, now=utcnow())


async def _record_run(client: Bot, plan: _PublishPlan, results: Sequence[GroupPostResult]) -> None:
    """Persist the finished run against the account's guards (window + back-off).

    ``attempted`` is the daily-cap budget the run spent (groups it actually tried);
    a run that hit a rate-limit or an expired session counts as soft-blocked and
    escalates the account's cooldown.
    """
    attempted = sum(1 for result in results if result.attempted)
    soft_blocked = any(result.failure in _SOFT_BLOCK_FAILURES for result in results)
    async with client.database.session() as session:
        service = AccountPostLimitService(session, client.settings.post_limits)
        await service.record(
            fb_uid=plan.account.fb_uid,
            now=utcnow(),
            attempted=attempted,
            soft_blocked=soft_blocked,
        )


def _gate_message(gate: PostGate, limits: PostLimitsSettings) -> str:
    """The calm, actionable line shown to the user when a guard refused the run."""
    if gate is PostGate.CIRCADIAN:
        return POST_GATE_CIRCADIAN.format(
            start_hour=limits.active_start_hour,
            start_minute=limits.active_start_minute,
            # A midnight end is stored as hour 0; show it as 24:00 to the user.
            end_hour=limits.active_end_hour or POST_CIRCADIAN_MIDNIGHT_DISPLAY_HOUR,
            end_minute=limits.active_end_minute,
        )
    return POST_GATE_MESSAGES.get(gate, POST_GATE_BLOCKED_DEFAULT)


async def _run_publish(
    client: Bot, draft: PostDraft, plan: _PublishPlan
) -> list[GroupPostResult] | None:
    """Download the photos to a temp dir and stream the publish; ``None`` on no photo."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = await _download_photos(client, draft.photo_file_ids, tmp_dir)
        if not paths:
            return None
        return await _stream_publish(client, draft, plan, paths)


async def _stream_publish(
    client: Bot, draft: PostDraft, plan: _PublishPlan, paths: list[str]
) -> list[GroupPostResult]:
    """Drive the publish generator, re-rendering progress after each group resolves."""
    renderer = _ProgressRenderer(client, plan)
    service = PostService(plan.account.access_token, decode_cookies(plan.account.session_cookies))
    results: list[GroupPostResult] = []
    await renderer.update(results, force=True)
    async for result in service.publish_to_groups(
        message=draft.text or "",
        image_paths=paths,
        facebook_ids=plan.facebook_ids,
        cancel_event=draft.cancel_event,
        remaining_cap=plan.remaining_cap,
    ):
        results.append(result)
        await renderer.update(results)
    cancelled = bool(draft.cancel_event and draft.cancel_event.is_set())
    await renderer.finalize(results, cancelled=cancelled)
    return results


class _ProgressRenderer:
    """Throttled, de-duplicated editor of the sticky message during a publish run.

    Edits are gated to one per :data:`~bot.constants.POST_PROGRESS_THROTTLE_SEC`
    (dodging Telegram flood limits and ``MESSAGE_NOT_MODIFIED`` churn) and skipped
    when the rendered text is unchanged. The terminal :meth:`finalize` render is
    always emitted, swapping the *Cancelar* button for *Volver*.
    """

    def __init__(self, client: Bot, plan: _PublishPlan) -> None:
        self._client = client
        self._plan = plan
        self._total = len(plan.facebook_ids)
        self._last_edit = 0.0
        self._last_text = ""

    async def update(self, results: Sequence[GroupPostResult], *, force: bool = False) -> None:
        """Render in-flight progress, throttled unless *force* (the first frame)."""
        if not force and time.monotonic() - self._last_edit < POST_PROGRESS_THROTTLE_SEC:
            return
        await self._render(results, POST_PUBLISH_TITLE, post_publish_menu())

    async def finalize(self, results: Sequence[GroupPostResult], *, cancelled: bool) -> None:
        """Store the full result set and render its first page with paging controls.

        Unlike the throttled in-flight frames (which truncate to keep edits cheap),
        the terminal view shows *every* per-group line: the complete list is kept
        in :class:`~bot.post_results.PostResultStore` (keyed by the run's owner) and
        the *Cancelar* button is swapped for ◀▶ paging over it plus *Volver*.
        """
        title = POST_PUBLISH_CANCELLED_TITLE if cancelled else POST_PUBLISH_DONE_TITLE
        header = _summary_header(results, total=self._total, title=title)
        lines = [
            _result_line(result, self._plan.name_by_id.get(result.facebook_id, result.facebook_id))
            for result in results
        ]
        result_set = self._client.post_results.put(self._plan.user_id, header, lines)
        window = result_set.window(POST_RESULT_PAGE_SIZE)
        await edit_message(
            self._client,
            self._plan.chat_id,
            self._plan.message_id,
            _render_result_page(header, window),
            reply_markup=post_result_page_menu(window),
        )

    async def _render(
        self,
        results: Sequence[GroupPostResult],
        title: str,
        markup: InlineKeyboardMarkup,
        *,
        force: bool = False,
    ) -> None:
        text = _render_publish(
            results,
            self._plan.name_by_id,
            total=self._total,
            title=title,
            in_progress_name=self._in_progress_name(results),
        )
        if not force and text == self._last_text:
            return
        self._last_edit = time.monotonic()
        self._last_text = text
        await edit_message(
            self._client, self._plan.chat_id, self._plan.message_id, text, reply_markup=markup
        )

    def _in_progress_name(self, results: Sequence[GroupPostResult]) -> str | None:
        """Display name of the group currently publishing, or ``None`` when done."""
        done = len(results)
        if done >= self._total:
            return None
        facebook_id = self._plan.facebook_ids[done]
        return self._plan.name_by_id.get(facebook_id, facebook_id)


async def _download_photos(client: Bot, file_ids: Sequence[str], dest_dir: str) -> list[str]:
    """Download each Telegram photo into *dest_dir*, returning the saved paths."""
    paths: list[str] = []
    to_disk: Literal[False] = False  # selects download_media's str-returning overload
    for index, file_id in enumerate(file_ids):
        target = str(Path(dest_dir) / f"{index}{POST_PHOTO_FILE_SUFFIX}")
        downloaded = await client.download_media(file_id, file_name=target, in_memory=to_disk)
        if isinstance(downloaded, str):
            paths.append(downloaded)
    return paths


def _render_publish(
    results: Sequence[GroupPostResult],
    name_by_id: dict[str, str],
    *,
    total: int,
    title: str,
    in_progress_name: str | None,
) -> str:
    """Render the live progress view: header (bar + tallies) over a group list."""
    done = len(results)
    lines = [_summary_header(results, total=total, title=title), ""]
    result_lines = [_result_line(r, name_by_id.get(r.facebook_id, r.facebook_id)) for r in results]
    lines.extend(result_lines[:POST_PROGRESS_MAX_LINES])
    hidden = len(result_lines) - min(len(result_lines), POST_PROGRESS_MAX_LINES)
    if hidden:
        lines.append(POST_PROGRESS_OVERFLOW.format(extra=hidden))
    if in_progress_name is not None:
        lines.append(POST_LINE_IN_PROGRESS.format(name=html.escape(in_progress_name)))
    queued = total - done - (1 if in_progress_name is not None else 0)
    if queued > 0:
        lines.append(POST_LINE_QUEUED.format(count=queued))
    return "\n".join(lines)


def _summary_header(results: Sequence[GroupPostResult], *, total: int, title: str) -> str:
    """The titled header line (bar + percentage + per-outcome tallies) of a run."""
    tally = _tally(results)
    done = len(results)
    return POST_PROGRESS_HEADER.format(
        title=title,
        bar=_progress_bar(done, total),
        pct=_pct(done, total),
        ok=tally.ok,
        pending=tally.pending,
        other=tally.failed,
        done=done,
        total=total,
    )


def _render_result_page(header: str, window: PostResultPage) -> str:
    """Render one page of the final summary: header, the page's lines, page footer.

    Unlike the live progress view, this never truncates — the full per-group list
    is reachable by paging — so a run of 80+ groups stays within Telegram's
    message limit while still showing every result.
    """
    lines = [header, "", *window.lines]
    if window.total_pages > 1:
        lines.append("")
        lines.append(
            POST_RESULT_PAGE_INDICATOR.format(page=window.page + 1, total=window.total_pages)
        )
    return "\n".join(lines)


def _result_line(result: GroupPostResult, name: str) -> str:
    """One per-group line, tagged by outcome with user-derived text escaped."""
    safe = html.escape(name)
    if result.cancelled:
        return POST_LINE_CANCELLED.format(name=safe)
    if not result.ok:
        return POST_LINE_FAIL.format(name=safe, reason=_fail_reason(result.failure))
    if result.pending:
        return POST_LINE_PENDING.format(name=safe)
    return POST_LINE_OK.format(name=safe, url=html.escape(result.url or "", quote=True))


def _tally(results: Sequence[GroupPostResult]) -> _Tally:
    """Count the per-outcome totals across *results*."""
    tally = _Tally()
    for result in results:
        if result.cancelled:
            tally.cancelled += 1
        elif result.ok and result.pending:
            tally.pending += 1
        elif result.ok:
            tally.ok += 1
        else:
            tally.failed += 1
    return tally


def _progress_bar(done: int, total: int) -> str:
    """A fixed-width Unicode bar filled proportionally to ``done / total``."""
    if total <= 0:
        filled = POST_PROGRESS_BAR_WIDTH
    else:
        filled = min(POST_PROGRESS_BAR_WIDTH, int(done / total * POST_PROGRESS_BAR_WIDTH))
    empty = POST_PROGRESS_BAR_WIDTH - filled
    return POST_PROGRESS_BAR_FILLED * filled + POST_PROGRESS_BAR_EMPTY * empty


def _pct(done: int, total: int) -> int:
    """Whole-number completion percentage (100 when there is nothing to do)."""
    return 100 if total <= 0 else round(done / total * 100)


def _log_outcome(results: Sequence[GroupPostResult], *, cancelled: bool) -> None:
    """Emit the single canonical publish event with the per-outcome tallies."""
    tally = _tally(results)
    log.info(
        LogEvent.POST_PUBLISHED,
        groups=len(results),
        published=tally.ok,
        pending=tally.pending,
        failed=tally.failed,
        cancelled_groups=tally.cancelled,
        run_cancelled=cancelled,
    )


async def _report_failures(
    client: Bot,
    owner: User,
    results: Sequence[GroupPostResult],
    name_by_id: dict[str, str],
) -> None:
    """Send the admin one consolidated note with the raw reason per failed group.

    Only groups that were actually *attempted* and failed are reported — cancelled
    or rate-limit-skipped groups are collateral, not failures. These expected
    per-group failures the user only sees softened, so their technical detail (e.g.
    expired cookies, a duplicate rejection) would otherwise be lost. Best-effort:
    the reporter swallows any delivery error.
    """
    failed = [result for result in results if not result.ok and result.attempted]
    if not failed:
        return
    lines = [
        POST_ADMIN_FAILURE_HEADER.format(
            user=html.escape(owner.display_name), user_id=owner.telegram_id
        )
    ]
    lines.extend(
        POST_ADMIN_FAILURE_LINE.format(
            name=html.escape(name_by_id.get(result.facebook_id, result.facebook_id)),
            reason=html.escape(result.error or ""),
        )
        for result in failed
    )
    await client.error_reporter.deliver("\n".join(lines))


def _fail_reason(failure: PostFailure | None) -> str:
    """Map a failure category to its friendly user line, defaulting when absent."""
    if failure is None:
        return POST_FAIL_REASON_DEFAULT
    return POST_FAIL_REASONS.get(failure, POST_FAIL_REASON_DEFAULT)
