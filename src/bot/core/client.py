"""Pyrogram client subclass carrying application-scoped dependencies."""

from __future__ import annotations

from pathlib import Path

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions

from bot.blueprint_edits import BlueprintEditStore
from bot.conversations import ConversationStore
from bot.core.config import Settings
from bot.core.errors import ErrorReporter
from bot.db.database import Database
from bot.fb_link_requests import FacebookLinkStore
from bot.group_search import GroupSearchStore
from bot.post_drafts import PostDraftStore
from bot.post_results import PostResultStore


class Bot(Client):
    """A Pyrogram :class:`~pyrogram.Client` augmented with shared services.

    Handlers receive this instance as their ``client`` argument and reach the
    application's dependencies (settings, database, error reporter, in-memory
    conversation state) through it, keeping handler signatures free of globals.
    """

    def __init__(self, settings: Settings, database: Database) -> None:
        telegram = settings.telegram
        # Pyrogram opens its session file under ``workdir`` but never creates
        # the directory; ensure it exists so a fresh checkout starts cleanly.
        Path(telegram.workdir).mkdir(parents=True, exist_ok=True)
        super().__init__(
            name=telegram.session_name,
            api_id=telegram.api_id,
            api_hash=telegram.api_hash.get_secret_value(),
            bot_token=telegram.bot_token.get_secret_value(),
            workdir=telegram.workdir,
            # Never expand link previews: post-result lines carry "ver" links to
            # the published posts, and a preview of the first would bloat the
            # message. This client-wide default applies to every send/edit/reply
            # (each falls back to it); a call may still override per message.
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        # Render every outgoing message as HTML by default, so handler prose can
        # use <b>/<code> for emphasis; user-derived values are html.escape()d at
        # their interpolation sites. Calls may still override per message.
        self.set_parse_mode(ParseMode.HTML)
        self.settings = settings
        self.database = database
        self.error_reporter = ErrorReporter(self, telegram.admin_id)
        self.conversations = ConversationStore()
        self.post_drafts = PostDraftStore()
        self.post_results = PostResultStore()
        self.group_searches = GroupSearchStore()
        self.fb_links = FacebookLinkStore()
        self.blueprint_edits = BlueprintEditStore()
