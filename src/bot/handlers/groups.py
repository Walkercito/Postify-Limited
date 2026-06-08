"""Groups feature: each user curates a personal list of Facebook groups.

Three entry points:

* the *Groups* screen → *Añadir* starts a short conversation (the user's next
  message is read as a link);
* *Buscar* starts a fuzzy search (the next message is the search term), which
  renders ranked, paginated result rows — each a link to the group plus a quick
  🗑 delete — instead of dumping the whole list as text; and
* an always-on shortcut — pasting a group link at any time (when no other step
  is in progress) saves it, or offers to delete it if it's already saved.

Two link forms are accepted (:mod:`bot.facebook_url`): a direct
``facebook.com/groups/<id>`` link (numeric id or vanity slug, used as-is) and a
``facebook.com/share/g/<token>`` share link, whose opaque token is resolved to
the canonical numeric id by opening it (that fetch also yields the name). On a
new save we best-effort fetch the group's public name (unauthenticated, via the
vendored ``fb_unofficial`` engine) and store it. The client renders HTML by
default, so stored ids/names are echoed back inside ``<code>``/``<b>`` and
``html.escape``d at the interpolation site so user-derived text can't break the
markup.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

import httpx
from pyrogram import filters

from bot.callbacks import GROUP_DECISION_PATTERN, parse_group_decision
from bot.constants import (
    GROUP_PREVIEW_TIMEOUT_SEC,
    GROUP_SEARCH_PAGE_SIZE,
    ConversationState,
    GroupAction,
    HandlerGroup,
    LogEvent,
    MenuAction,
)
from bot.core.logging import get_logger
from bot.facebook_url import extract_group_id, extract_group_share_token, share_group_url
from bot.group_search import GroupHit
from bot.handlers.base import Router
from bot.handlers.edits import edit_text
from bot.handlers.guards import allowed_owner, guard_owner
from bot.handlers.middleware import observed, tracks_activity
from bot.keyboards import (
    back_to_menu,
    group_delete_confirm_menu,
    group_search_results_menu,
    groups_menu,
)
from bot.services.group_service import GroupService
from fb_unofficial import fetch_group_preview

if TYPE_CHECKING:
    from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

    from bot.core.client import Bot
    from bot.db.models.group import Group
    from bot.group_search import GroupSearch
    from fb_unofficial import GroupPreview

log = get_logger(__name__)

GROUPS_HEADER = "👥 <b>Mis grupos</b>\n📊 Tienes <b>{count}</b> grupo(s) guardado(s)."
GROUPS_EMPTY = (
    "👥 <b>Mis grupos</b>\n"
    "📭 Todavía no has guardado ningún grupo. "
    "Envíame el enlace de un grupo de Facebook para añadirlo."
)
GROUP_ADD_PROMPT = "🔗 Envíame el enlace del grupo de Facebook que quieres añadir."
GROUP_SEARCH_PROMPT = "🔍 Escribe parte del nombre del grupo que buscas."
GROUP_SEARCH_HEADER = (
    "🔎 Resultados para «<b>{query}</b>» — página {page}/{total_pages} ({total} en total):"
)
GROUP_SEARCH_NO_RESULTS = "🤷 No encontré grupos parecidos a «<b>{query}</b>»."
GROUP_SEARCH_EXPIRED = "⌛ Esa búsqueda ya expiró. Abre <b>Grupos</b> y busca de nuevo."
INVALID_LINK_MESSAGE = "🤔 Eso no parece el enlace de un grupo de Facebook."
SHARE_LINK_UNRESOLVED = (
    "😕 No pude abrir ese enlace para compartir. "
    "Prueba con el enlace directo del grupo (facebook.com/groups/…)."
)
GROUP_ADDED_MESSAGE = "✅ Grupo guardado: <code>{group_id}</code>"
GROUP_ADDED_NAMED_MESSAGE = "✅ Guardado: <b>{name}</b>\n<code>{group_id}</code>"
GROUP_DELETE_CONFIRM_MESSAGE = "🗑 ¿Quitar <code>{group_id}</code> de tu lista?"
GROUP_DELETED_MESSAGE = "🗑 Quité <code>{group_id}</code> de tu lista."
GROUP_DELETE_CANCELLED = "👍 Lo dejé como estaba."
GROUP_DELETE_MISSING = "🤷 Ese grupo ya no está en tu lista."
GROUP_DELETED_TOAST = "Eliminado 🗑"


class GroupsRouter(Router):
    """Registers the Groups screen, search, delete confirmation and link shortcut."""

    def register(self, bot: Bot) -> None:
        callbacks = {
            MenuAction.GROUPS: self._on_groups,
            GroupAction.ADD: self._on_add,
            GroupAction.SEARCH: self._on_search,
        }
        for action, handler in callbacks.items():
            self._add_callback_query_handler(
                bot, handler, filters.regex(rf"^{action}$"), HandlerGroup.DEFAULT
            )
        self._add_callback_query_handler(
            bot,
            self._on_group_decision,
            filters.regex(GROUP_DECISION_PATTERN),
            HandlerGroup.DEFAULT,
        )
        # Always-on link shortcut: any private text the command/menu handlers
        # don't claim first is inspected here for a group link.
        self._add_message_handler(
            bot, self._on_text, filters.private & filters.text, HandlerGroup.DEFAULT
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_groups(client: Bot, callback_query: CallbackQuery) -> None:
        owner = await guard_owner(client, callback_query)
        if owner is None:
            return
        async with client.database.session() as session:
            count = await GroupService(session).count_for_user(owner.id)
        text = GROUPS_HEADER.format(count=count) if count else GROUPS_EMPTY
        await edit_text(callback_query, text, reply_markup=groups_menu(has_groups=count > 0))
        await callback_query.answer()

    @staticmethod
    @observed
    @tracks_activity
    async def _on_add(client: Bot, callback_query: CallbackQuery) -> None:
        await _begin_conversation(
            client, callback_query, ConversationState.ADD_GROUP, GROUP_ADD_PROMPT
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_search(client: Bot, callback_query: CallbackQuery) -> None:
        await _begin_conversation(
            client, callback_query, ConversationState.SEARCH_GROUP, GROUP_SEARCH_PROMPT
        )

    @staticmethod
    @observed
    @tracks_activity
    async def _on_group_decision(client: Bot, callback_query: CallbackQuery) -> None:
        """Route a parameterized group button (delete/page) to its handler."""
        data = callback_query.data
        parsed = parse_group_decision(data) if isinstance(data, str) else None
        if parsed is None:
            return
        action, value = parsed
        if action is GroupAction.PAGE:
            await _handle_page(client, callback_query, value)
        elif action is GroupAction.QUICK_DELETE:
            await _handle_quick_delete(client, callback_query, value)
        elif action is GroupAction.CONFIRM_DELETE:
            await _handle_confirm_delete(client, callback_query, value)
        else:  # CANCEL_DELETE
            await _handle_cancel_delete(callback_query)

    @staticmethod
    @observed
    @tracks_activity
    async def _on_text(client: Bot, message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        state = client.conversations.pop(user.id)
        text = message.text or ""
        if state is ConversationState.SEARCH_GROUP:
            await _dispatch_search(client, message, user.id, text)
            return
        direct = extract_group_id(text)
        token = extract_group_share_token(text) if direct is None else None
        if state is None and direct is None and token is None:
            return  # idle chatter that isn't a group link — ignore.
        async with client.database.session() as session:
            owner = await allowed_owner(session, user.id)
            if owner is None:
                return
            await _handle_add_request(message, GroupService(session), owner.id, direct, token)


async def _begin_conversation(
    client: Bot,
    callback_query: CallbackQuery,
    state: ConversationState,
    prompt: str,
) -> None:
    """Gate on access, arm the conversation, and prompt for the next message."""
    owner = await guard_owner(client, callback_query)
    if owner is None:
        return
    client.conversations.begin(owner.telegram_id, state)
    await edit_text(callback_query, prompt)
    await callback_query.answer()


async def _dispatch_search(client: Bot, message: Message, telegram_id: int, query: str) -> None:
    """Run a fuzzy search, store the result set, and reply with its first page."""
    async with client.database.session() as session:
        owner = await allowed_owner(session, telegram_id)
        if owner is None:
            return
        results = await GroupService(session).search(owner.id, query)
    hits = [
        GroupHit(id=group.id, facebook_id=group.facebook_id, name=group.name) for group in results
    ]
    log.info(LogEvent.GROUP_SEARCHED, query=query, results=len(hits))
    search = client.group_searches.put(owner.telegram_id, query, hits)
    text, markup = _render_search(search)
    await message.reply_text(text, reply_markup=markup)


async def _handle_page(client: Bot, callback_query: CallbackQuery, page: int) -> None:
    """Re-render the active search at *page* (the heavy hit list is kept server-side)."""
    owner = await guard_owner(client, callback_query)
    if owner is None:
        return
    search = client.group_searches.get(owner.telegram_id)
    if search is None:
        await edit_text(callback_query, GROUP_SEARCH_EXPIRED)
        await callback_query.answer()
        return
    search.go_to(page)
    text, markup = _render_search(search)
    await edit_text(callback_query, text, reply_markup=markup)
    await callback_query.answer()


async def _handle_quick_delete(client: Bot, callback_query: CallbackQuery, group_id: int) -> None:
    """Delete a group straight from a result row, then re-render the same page."""
    owner = await guard_owner(client, callback_query)
    if owner is None:
        return
    search = client.group_searches.get(owner.telegram_id)
    if search is None:
        await edit_text(callback_query, GROUP_SEARCH_EXPIRED)
        await callback_query.answer()
        return
    async with client.database.session() as session:
        removed = await GroupService(session).remove_by_id(owner.id, group_id)
    if removed is not None:
        log.info(LogEvent.GROUP_REMOVED, facebook_id=removed.facebook_id)
    search.remove(group_id)
    text, markup = _render_search(search)
    await edit_text(callback_query, text, reply_markup=markup)
    await callback_query.answer(
        GROUP_DELETED_TOAST if removed is not None else GROUP_DELETE_MISSING
    )


async def _handle_confirm_delete(client: Bot, callback_query: CallbackQuery, group_id: int) -> None:
    """Resolve a delete confirmation (from a pasted, already-saved link)."""
    owner = await guard_owner(client, callback_query)
    if owner is None:
        return
    async with client.database.session() as session:
        removed = await GroupService(session).remove_by_id(owner.id, group_id)
    if removed is None:
        await edit_text(callback_query, GROUP_DELETE_MISSING)
        await callback_query.answer()
        return
    log.info(LogEvent.GROUP_REMOVED, facebook_id=removed.facebook_id)
    await edit_text(
        callback_query,
        GROUP_DELETED_MESSAGE.format(group_id=html.escape(removed.facebook_id)),
    )
    await callback_query.answer(GROUP_DELETED_TOAST)


async def _handle_cancel_delete(callback_query: CallbackQuery) -> None:
    """Dismiss a delete confirmation without removing anything."""
    await edit_text(callback_query, GROUP_DELETE_CANCELLED)
    await callback_query.answer()


def _render_search(search: GroupSearch) -> tuple[str, InlineKeyboardMarkup]:
    """Render a search's current page to ``(text, keyboard)``.

    An exhausted result set (e.g. after deleting the last match) falls back to
    the no-results message with a plain *Volver* keyboard.
    """
    if not search.hits:
        return GROUP_SEARCH_NO_RESULTS.format(query=html.escape(search.query)), back_to_menu()
    window = search.window(GROUP_SEARCH_PAGE_SIZE)
    text = GROUP_SEARCH_HEADER.format(
        query=html.escape(search.query),
        page=window.page + 1,
        total_pages=window.total_pages,
        total=window.total,
    )
    return text, group_search_results_menu(window)


async def _handle_add_request(
    message: Message,
    service: GroupService,
    owner_id: int,
    direct: str | None,
    token: str | None,
) -> None:
    """Add the referenced group, or offer to delete it if already saved.

    Resolves the link to a canonical id first. A share link's resolve already
    yields the public name, so it's reused instead of fetching it twice; a
    direct link still fetches the name lazily after the save.
    """
    resolved = await _resolve_reference(direct, token)
    if resolved is None:
        await message.reply_text(SHARE_LINK_UNRESOLVED if token else INVALID_LINK_MESSAGE)
        return
    group_id, prefetched_name = resolved
    group, created = await service.add(owner_id, group_id)
    if not created:
        await _offer_delete(message, group)
        return
    name = prefetched_name if prefetched_name is not None else await _resolve_group_name(group_id)
    if name is not None:
        await service.set_name(group, name)
    log.info(LogEvent.GROUP_ADDED, facebook_id=group_id, name=name)
    escaped_id = html.escape(group_id)
    text = (
        GROUP_ADDED_NAMED_MESSAGE.format(name=html.escape(name), group_id=escaped_id)
        if name is not None
        else GROUP_ADDED_MESSAGE.format(group_id=escaped_id)
    )
    await message.reply_text(text)


async def _resolve_reference(
    direct: str | None, token: str | None
) -> tuple[str, str | None] | None:
    """Resolve a parsed link to ``(group_id, prefetched_name)``, or ``None``.

    A direct id needs no network — its name is fetched later — so it returns
    immediately with no name. A share token is opened to recover the canonical
    numeric id from the resolved page's ``og:url``; that same fetch yields the
    name, returned here so the caller avoids a second round-trip. ``None`` means
    the token couldn't be resolved (login wall / unreachable / no usable id).
    """
    if direct is not None:
        return direct, None
    if token is None:
        return None
    preview = await _fetch_preview(share_group_url(token))
    if preview is None or preview.id is None:
        return None
    return preview.id, preview.name


async def _resolve_group_name(facebook_id: str) -> str | None:
    """Best-effort public name for a group id, or ``None`` when unavailable."""
    preview = await _fetch_preview(facebook_id)
    return preview.name if preview is not None else None


async def _fetch_preview(url_or_id: str) -> GroupPreview | None:
    """Best-effort public :class:`GroupPreview` for a link/id, or ``None``.

    Unauthenticated and optional: transport failures (no network, blocked,
    timeout) are swallowed to ``None`` so adding a group never depends on
    Facebook being reachable. Anything unexpected propagates to ``observed``.
    """
    try:
        return await fetch_group_preview(url_or_id, timeout=GROUP_PREVIEW_TIMEOUT_SEC)
    except httpx.HTTPError:
        return None


async def _offer_delete(message: Message, group: Group) -> None:
    """Reply with the delete-confirmation question for *group*."""
    await message.reply_text(
        GROUP_DELETE_CONFIRM_MESSAGE.format(group_id=html.escape(group.facebook_id)),
        reply_markup=group_delete_confirm_menu(group.id),
    )
