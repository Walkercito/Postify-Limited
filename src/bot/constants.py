"""Centralized constants and enumerations.

Per the project's "no magic values" rule, every literal that carries meaning
(command names, role names, log event names, defaults, SQL pragmas, limits, ...)
lives here instead of being scattered through the codebase.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Command(StrEnum):
    """Bot commands, without the leading slash."""

    START = "start"
    HELP = "help"


class MenuAction(StrEnum):
    """Callback-query data for the inline main-menu buttons.

    Values double as the ``callback_data`` carried by each button and as the
    regex matched when registering the handler, so they must stay unique and
    stable.
    """

    MAIN = "menu:main"
    START_POST = "menu:start_post"
    BLUEPRINTS = "menu:blueprints"
    GROUPS = "menu:groups"
    MANAGEMENT = "menu:management"
    ACCOUNTS = "menu:accounts"
    REQUEST_ACCESS = "menu:request_access"


class GroupAction(StrEnum):
    """Callback-query data for the Groups screen, search and delete confirmation.

    ``ADD`` / ``LIST`` / ``SEARCH`` are static screen buttons. The rest carry a target id
    (encoded by :func:`bot.callbacks.group_decision`): ``QUICK_DELETE`` removes a
    group straight from a search-result row, ``PAGE`` carries a page *number* for
    paginating those results, and ``CONFIRM_DELETE`` / ``CANCEL_DELETE`` resolve
    the link-paste delete confirmation.
    """

    ADD = "group:add"
    LIST = "group:list"
    SEARCH = "group:search"
    QUICK_DELETE = "group:quick_delete"
    PAGE = "group:page"
    CONFIRM_DELETE = "group:confirm_delete"
    CANCEL_DELETE = "group:cancel_delete"


class PostAction(StrEnum):
    """Callback-query data for the post-composition flow.

    The compose steps (collecting text, then photos) are tracked by the
    in-memory :class:`~bot.post_drafts.PostDraftStore`, not by callback data.
    Most buttons are static; ``REMOVE_PHOTO`` carries the 0-based index of the
    photo to drop (encoded by :func:`bot.callbacks.post_photo_decision`) and
    ``RESULT_PAGE`` carries a 0-based page number for scrolling the final result
    summary (encoded by :func:`bot.callbacks.post_result_page`). ``EDIT_TEXT``
    re-arms the caption, ``CLEAR`` empties the draft, ``CANCEL`` aborts
    composition, and ``CANCEL_PUBLISH`` requests a cooperative stop of an
    in-flight multi-group run (the current group finishes, the rest stop).
    """

    PHOTOS_DONE = "post:photos_done"
    EDIT_TEXT = "post:edit_text"
    REMOVE_PHOTO = "post:remove_photo"
    CLEAR = "post:clear"
    CONFIRM = "post:confirm"
    CANCEL = "post:cancel"
    CANCEL_PUBLISH = "post:cancel_publish"
    SAVE_BLUEPRINT = "post:save_blueprint"
    RESULT_PAGE = "post:result_page"


class BlueprintAction(StrEnum):
    """Callback-query data for the Blueprints (saved-post) screens.

    Every member carries a target blueprint's internal id (encoded by
    :func:`bot.callbacks.blueprint_decision`): ``OPEN`` shows the detail screen,
    ``PUBLISH`` republishes it to every saved group, ``EDIT`` opens the edit
    submenu, ``RENAME`` / ``EDIT_TEXT`` arm a text reply that updates the name or
    body, ``DELETE`` / ``CONFIRM_DELETE`` resolve removal, and ``SHOW_IMAGES``
    re-sends the stored photos as an album preview.
    """

    OPEN = "blueprint:open"
    PUBLISH = "blueprint:publish"
    EDIT = "blueprint:edit"
    RENAME = "blueprint:rename"
    EDIT_TEXT = "blueprint:edit_text"
    DELETE = "blueprint:delete"
    CONFIRM_DELETE = "blueprint:confirm_delete"
    SHOW_IMAGES = "blueprint:show_images"


class BlueprintField(StrEnum):
    """Which field a pending blueprint edit updates from the user's next message."""

    NAME = "name"
    TEXT = "text"


class PostFailure(StrEnum):
    """Why a per-group publish failed, as a category the user-facing line maps to.

    The raw engine error is kept verbatim for the admin report; this category is
    all the *user* sees, rendered as a calm, actionable sentence. ``RATE_LIMITED``
    also covers the groups skipped after the rate-limit circuit-breaker trips;
    ``STOPPED`` covers the groups skipped after the consecutive-failure breaker
    halts the run (so the user sees "we stopped", not a misleading "retry soon").
    ``DAILY_CAP_REACHED`` covers the tail skipped when the account's rolling daily
    attempt cap is hit mid-run (the run posts up to the budget, then stops).
    """

    RATE_LIMITED = "rate_limited"
    SESSION_EXPIRED = "session_expired"
    GENERIC = "generic"
    STOPPED = "stopped"
    DAILY_CAP_REACHED = "daily_cap_reached"


class PostGate(StrEnum):
    """Whether an account may start a publish run now, and why not if it may not.

    Decided per run by
    :class:`~bot.services.account_post_limit_service.AccountPostLimitService`
    *before* any photo is downloaded or posted. ``OK`` lets the run proceed
    (possibly capped to a partial set of groups); every other member names the
    guard that refused it and maps to a friendly, actionable message the handler
    shows instead of publishing.
    """

    OK = "ok"  # the run may proceed
    CIRCADIAN = "circadian"  # outside the configured active-hours window
    BACKOFF = "backoff"  # cooling down after recent soft-blocks
    DAILY_CAP = "daily_cap"  # the rolling-24h attempt budget is already spent


class AccountAction(StrEnum):
    """Callback-query data for the Facebook-accounts admin screen.

    All three carry a target user's Telegram id (encoded by
    :func:`bot.callbacks.account_decision`): ``LINK`` arms the inject-session
    flow for that user, ``UNLINK`` removes their stored account, and ``CANCEL``
    aborts an in-progress link.
    """

    LINK = "account:link"
    UNLINK = "account:unlink"
    CANCEL = "account:cancel"


class CallbackScope(StrEnum):
    """Where an access decision originated, so the handler knows how to re-render.

    Both scopes carry the same ``scope:status:telegram_id`` payload but trigger
    different follow-up rendering (confirm the alert vs. refresh the list).
    """

    ALERT = "alert"  # the instant admin notification (a DM with Grant/Deny)
    MANAGE = "manage"  # the Management list screen


class Role(StrEnum):
    """User roles. Exactly one ``admin`` exists; everyone else is a ``user``."""

    ADMIN = "admin"
    USER = "user"


class AccessStatus(StrEnum):
    """Whitelist state of a user. Admins are implicitly allowed."""

    PENDING = "pending"  # known to the bot, awaiting an admin decision
    ALLOWED = "allowed"  # whitelisted: may use the bot
    DENIED = "denied"  # rejected or revoked


class ConversationState(StrEnum):
    """A pending multi-step exchange the user's next text message completes.

    Stored per user in the in-memory :class:`~bot.conversations.ConversationStore`
    so a free-text reply (a pasted link) is routed to the right operation.
    """

    ADD_GROUP = "add_group"
    SEARCH_GROUP = "search_group"


class UpdateType(StrEnum):
    """Kind of update a handler received, attached to the wide log event."""

    MESSAGE = "message"
    CALLBACK_QUERY = "callback_query"


class Outcome(StrEnum):
    """Result of handling a single update, attached to the wide log event."""

    SUCCESS = "success"
    ERROR = "error"


class NameSource(StrEnum):
    """Where a saved group's display name came from, attached to ``GROUP_ADDED``.

    Surfaced on the wide event so a name that failed to resolve is queryable
    (``UNRESOLVED``) instead of a silent ``name=None``, and a successful one is
    attributed to the path that produced it.
    """

    PREFETCHED = "prefetched"  # recovered while opening a share link
    AUTHENTICATED = "authenticated"  # the owner's logged-in cookie session
    UNAUTHENTICATED = "unauthenticated"  # the public, unauthenticated scrape
    UNRESOLVED = "unresolved"  # no source produced a name


class LogEvent(StrEnum):
    """Canonical structured-log event names (one wide event per occurrence)."""

    BOT_STARTING = "bot.starting"
    BOT_STARTED = "bot.started"
    BOT_STOPPING = "bot.stopping"
    BOT_STOPPED = "bot.stopped"
    DATABASE_INITIALIZED = "database.initialized"
    DATABASE_DISPOSED = "database.disposed"
    ADMIN_SEEDED = "admin.seeded"
    UPDATE_HANDLED = "update.handled"
    USER_REGISTERED = "user.registered"
    ACCESS_REQUESTED = "access.requested"
    ACCESS_GRANTED = "access.granted"
    ACCESS_DENIED = "access.denied"
    ACCESS_NOTIFY_FAILED = "access.notify_failed"
    GROUP_ADDED = "group.added"
    GROUP_REMOVED = "group.removed"
    GROUP_SEARCHED = "group.searched"
    GROUP_LISTED = "group.listed"
    FB_ACCOUNT_LINKED = "fb_account.linked"
    FB_ACCOUNT_UNLINKED = "fb_account.unlinked"
    POST_PUBLISHED = "post.published"
    POST_GATE_BLOCKED = "post.gate_blocked"
    POST_BACKOFF_ESCALATED = "post.backoff_escalated"
    POST_BACKOFF_CLEARED = "post.backoff_cleared"
    POST_REFLOAT_FAILED = "post.refloat_failed"
    BLUEPRINT_SAVED = "blueprint.saved"
    BLUEPRINT_UPDATED = "blueprint.updated"
    BLUEPRINT_REMOVED = "blueprint.removed"
    ACTIVITY_UPDATE_FAILED = "activity.update_failed"
    ERROR_REPORT_FAILED = "error.report_failed"


class LogFormat(StrEnum):
    """Renderer selection for structured logging."""

    CONSOLE = "console"
    JSON = "json"


class HandlerGroup(IntEnum):
    """Pyrogram dispatch groups (lower numbers run first)."""

    DEFAULT = 0


# How long a writer waits for SQLite's single write lock before failing with
# "database is locked". The driver default (5s) proved too short when several
# updates write concurrently; WAL keeps readers unblocked, so waiting is cheap.
SQLITE_BUSY_TIMEOUT_MS: int = 15000


class SQLitePragma(StrEnum):
    """PRAGMA statements applied to every new SQLite connection."""

    FOREIGN_KEYS = "PRAGMA foreign_keys=ON"
    JOURNAL_WAL = "PRAGMA journal_mode=WAL"
    BUSY_TIMEOUT = f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}"


# In-memory SQLite database name (per-connection database).
SQLITE_MEMORY: str = ":memory:"

# Pagination defaults for repository list queries.
DEFAULT_PAGE_LIMIT: int = 100
DEFAULT_PAGE_OFFSET: int = 0

# Max groups shown in a single "list my groups" response.
GROUP_LIST_DEFAULT_LIMIT: int = 15

# Max blueprints (saved posts) shown in a single "Plantillas" list response.
BLUEPRINT_LIST_DEFAULT_LIMIT: int = 50

# Fuzzy group search (rapidfuzz). SCAN_LIMIT caps the candidate set loaded from
# the DB before scoring; MAX_RESULTS caps the ranked hits kept; PAGE_SIZE is how
# many result rows render per page; SCORE_CUTOFF is the minimum WRatio (0-100) a
# candidate must reach to count as a match (typo/accent tolerant below 100).
GROUP_SEARCH_SCAN_LIMIT: int = 1000
GROUP_SEARCH_MAX_RESULTS: int = 60
GROUP_SEARCH_PAGE_SIZE: int = 6
GROUP_SEARCH_SCORE_CUTOFF: int = 60

# Unicode general-category code for a non-spacing combining mark (an accent).
# Accent folding decomposes to NFD then drops every character of this category.
UNICODE_NONSPACING_MARK: str = "Mn"

# Time budget for the best-effort, unauthenticated group-name preview fetch.
# Short so adding a group never blocks on a slow/blocked Facebook response.
GROUP_PREVIEW_TIMEOUT_SEC: float = 8.0

# A single post fans out to at most this many of the user's saved groups. Used
# for every group read in the post flow so the count shown and the set posted to
# stay consistent (no silent truncation between confirm and publish).
POST_GROUP_LIMIT: int = 100

# Max photos attachable to one post (matches a Telegram album's hard cap).
POST_MAX_PHOTOS: int = 10

# Telegram delivers an album (media group) as separate messages arriving in a
# rapid burst. The composer coalesces a burst into a single re-render by
# debouncing: each incoming item (re)schedules the render this many seconds out,
# so only the final item of the burst triggers one render.
POST_ALBUM_DEBOUNCE_SEC: float = 0.4

# On-disk suffix for photos downloaded from Telegram before upload. Telegram
# photos are JPEG, and the engine guesses the MIME type from this extension.
POST_PHOTO_FILE_SUFFIX: str = ".jpg"

# Per-group error recorded for the groups skipped after the web engine trips a
# rate-limit circuit-breaker mid-run (the remaining posts are not attempted).
POST_SKIPPED_RATE_LIMIT: str = "omitido — la cuenta fue limitada por Facebook"

# Per-group reason recorded for groups not attempted because the user cancelled
# the run mid-flight. Kept off the admin failure report (it is not a failure).
POST_CANCELLED_REASON: str = "cancelled by user"

# A publish run stops after this many *attempted* failures in a row: when every
# write starts failing the cause is account-wide (e.g. Facebook soft-blocking
# uploads), so pushing on just burns the remaining groups against a dead engine.
POST_RUN_MAX_CONSECUTIVE_FAILURES: int = 3

# Per-group error recorded for the groups skipped after that breaker trips.
POST_SKIPPED_CONSECUTIVE_FAILURES: str = "omitido — fallos consecutivos, se detuvo la publicación"

# Per-group reason recorded for the over-cap tail of a run that was allowed to
# post only part of its groups before the account's rolling daily attempt cap was
# reached (the budget ran out mid-run; the rest are skipped, not failed).
POST_SKIPPED_DAILY_CAP: str = "omitido — se alcanzó el límite diario de la cuenta"

# The live composer truncates the *shown* caption to this many characters (the
# full text is still what gets posted) so the sticky preview message stays compact.
POST_PREVIEW_MAX_CHARS: int = 500

# Realtime publish-progress bar geometry.
POST_PROGRESS_BAR_WIDTH: int = 20
POST_PROGRESS_BAR_FILLED: str = "█"
POST_PROGRESS_BAR_EMPTY: str = "░"

# Min seconds between progress edits — a throttle to dodge Telegram flood limits
# and MESSAGE_NOT_MODIFIED churn. The terminal state is always rendered unthrottled.
POST_PROGRESS_THROTTLE_SEC: float = 1.5

# Cap on per-group lines in the live progress message so a large run cannot exceed
# Telegram's message-length limit; any overflow is declared, never silently dropped.
POST_PROGRESS_MAX_LINES: int = 25

# Per-group lines shown per page of the *final* result summary. Unlike the live
# progress view (which truncates), the terminal summary paginates the full list so
# every group is reachable; a run of 80+ groups scrolls across pages of this size.
POST_RESULT_PAGE_SIZE: int = 20

# Default on-disk async SQLite location.
DEFAULT_DATABASE_URL: str = "sqlite+aiosqlite:///data/bot.db"

# Default Pyrogram client/session name and working directory.
DEFAULT_SESSION_NAME: str = "bot"
DEFAULT_WORKDIR: str = ".pyrogram"

# Default logging verbosity.
DEFAULT_LOG_LEVEL: str = "INFO"

# Separator joining the parts of a structured callback_data payload.
CALLBACK_DATA_SEPARATOR: str = ":"

# Facebook group links look like ``facebook.com/groups/<id>`` where ``<id>`` is
# either a numeric id or a vanity slug. These pieces build the extraction regex
# and rebuild the canonical URL from a stored id.
FACEBOOK_DOMAIN: str = "facebook.com"
FACEBOOK_GROUPS_PATH: str = "groups"
FACEBOOK_GROUP_ID_CHARSET: str = r"[A-Za-z0-9._-]+"
FACEBOOK_GROUP_URL_TEMPLATE: str = "https://www.facebook.com/groups/{group_id}"

# A group *share* link looks like ``facebook.com/share/g/<token>``. The token is
# an opaque redirect handle, not a usable group id, so it must be resolved by
# opening the link (its ``og:url`` carries the canonical numeric id). These
# pieces build the share-link regex and rebuild the share URL from a token.
FACEBOOK_SHARE_PATH: str = "share"
FACEBOOK_SHARE_GROUP_SEGMENT: str = "g"
FACEBOOK_SHARE_TOKEN_CHARSET: str = r"[A-Za-z0-9]+"
FACEBOOK_SHARE_GROUP_URL_TEMPLATE: str = "https://www.facebook.com/share/g/{token}/"

# Column sizes (mirror Telegram's own field limits where applicable).
ROLE_NAME_MAX_LENGTH: int = 16
ACCESS_STATUS_MAX_LENGTH: int = 16
USERNAME_MAX_LENGTH: int = 32
FIRST_NAME_MAX_LENGTH: int = 64
LAST_NAME_MAX_LENGTH: int = 64
LANGUAGE_CODE_MAX_LENGTH: int = 16
GROUP_FB_ID_MAX_LENGTH: int = 128
GROUP_NAME_MAX_LENGTH: int = 128

# Blueprint (saved post) column sizes. ``name`` is the human label the user
# types; ``slug`` is its derived, per-user-unique handle (a few chars longer to
# fit the disambiguating numeric suffix).
BLUEPRINT_NAME_MAX_LENGTH: int = 80
BLUEPRINT_SLUG_MAX_LENGTH: int = 96

# Slug derivation: fold accents, lowercase, then collapse every run of
# characters *not* in this kept set into the separator, trimming separators off
# the ends. An empty result (e.g. an emoji-only name) falls back to a fixed
# stem. Per-user uniqueness appends ``-<n>`` starting at this first suffix.
BLUEPRINT_SLUG_SEPARATOR: str = "-"
BLUEPRINT_SLUG_STRIP_PATTERN: str = r"[^a-z0-9]+"
BLUEPRINT_SLUG_FALLBACK: str = "plantilla"
BLUEPRINT_SLUG_FIRST_SUFFIX: int = 2

# Stored per-user Facebook account (session) column sizes. The access token is
# the dependency the posting operation consumes; the uid identifies the account.
FB_UID_MAX_LENGTH: int = 32
FB_ACCESS_TOKEN_MAX_LENGTH: int = 512

# Wire format of the ``session.json`` produced by ``scripts/fb_capture_session.py``
# and uploaded by the admin to link a Facebook account. The top-level
# ``session_blob`` holds the captured session (and the credentials used to
# obtain it) under nested keys; the bot only consumes the session. A small size
# cap rejects anything that clearly isn't a captured session.
SESSION_PAYLOAD_BLOB_KEY: str = "session_blob"
SESSION_BLOB_SESSION_KEY: str = "session"
SESSION_BLOB_CREDENTIALS_KEY: str = "credentials"
# Inside the ``session`` object: the Graph access token (token mode) and/or the
# browser cookie name→value map (cookie mode). An account needs at least one.
SESSION_ACCESS_TOKEN_KEY: str = "access_token"
SESSION_UID_KEY: str = "uid"
SESSION_COOKIES_KEY: str = "session_cookies"
SESSION_CREATED_AT_KEY: str = "created_at"
# When ``session_cookies`` arrives as a list of cookie objects (the shape
# ``fb_unofficial.Session`` serializes), these keys carry each cookie's name and
# value; the parser normalizes the list to a flat name→value map.
SESSION_COOKIE_NAME_KEY: str = "name"
SESSION_COOKIE_VALUE_KEY: str = "value"
# The cookie that carries the logged-in Facebook user id; the capture script
# derives the account ``uid`` from it when building a cookie-mode session.
SESSION_COOKIE_USER_ID_NAME: str = "c_user"
SESSION_FILE_MAX_BYTES: int = 65536

# --------------------------------------------------------------------------- #
# Cookie-native (web.facebook.com Comet) posting engine.                        #
#                                                                               #
# A linked account posts to groups with EITHER a Graph ``access_token`` (the    #
# vendored ``fb_unofficial`` engine) OR a browser cookie jar driving the same   #
# ComposerStoryCreateMutation the web composer calls — no token. These literals #
# are the wire contract of that mutation. Persisted-query ids (``doc_id``) and  #
# localized response strings drift over time; treat them as best-effort and     #
# expect occasional re-capture/re-scrape. See ``bot.facebook_web``.             #
# --------------------------------------------------------------------------- #

# Endpoints. The home page is fetched (authenticated by cookies) to scrape the
# per-session tokens; photos upload to ``upload.facebook.com``; the post itself
# is a GraphQL mutation against ``web.facebook.com``.
FB_WEB_HOME_URL: str = "https://web.facebook.com/"
FB_WEB_GRAPHQL_URL: str = "https://web.facebook.com/api/graphql/"
FB_WEB_PHOTO_UPLOAD_URL: str = (
    "https://upload.facebook.com/ajax/react_composer/attachments/photo/upload"
)

# The logged-in group page, GET to resolve a group's display name. Facebook
# stopped serving group ``og`` tags to logged-out fetches, so the name is read
# from the authenticated page's HTML ``<title>`` (see facebook_web.group_page).
FB_WEB_GROUP_PAGE_URL_TEMPLATE: str = "https://web.facebook.com/groups/{group_id}"
# A trailing locale suffix the ``<title>`` may carry after the group name.
FB_WEB_TITLE_SUFFIXES: tuple[str, ...] = (" | Facebook", " - Facebook")
# Titles Facebook serves on the login wall instead of the real group name
# (casefolded for comparison).
FB_WEB_TITLE_PLACEHOLDERS: frozenset[str] = frozenset(
    {"facebook", "log in to facebook", "log into facebook", "log in or sign up to view"}
)

# Permalink shapes for a created group post (and one awaiting admin approval).
FB_WEB_GROUP_POST_URL_TEMPLATE: str = "https://www.facebook.com/groups/{group_id}/posts/{post_id}"
FB_WEB_GROUP_PENDING_URL_TEMPLATE: str = (
    "https://www.facebook.com/groups/{group_id}/pending_posts/{post_id}"
)

# GraphQL POST envelope fields shared by every Comet mutation.
FB_WEB_API_CALLER_CLASS: str = "RelayModern"
FB_WEB_FRIENDLY_NAME_COMPOSER: str = "ComposerStoryCreateMutation"
# Live persisted-query id for ComposerStoryCreateMutation (verified Feb 2026).
FB_WEB_DEFAULT_DOC_ID: str = "25352629677749205"
FB_WEB_COMET_REQ: str = "15"
FB_WEB_AJAX_PIPE: str = "1"
FB_WEB_DPR: str = "1.5"
FB_WEB_SERVER_TIMESTAMPS: str = "true"

# Per-session token form-field keys (scraped from the home page, see params.py).
FB_WEB_FIELD_AV: str = "av"
FB_WEB_FIELD_USER: str = "__user"
FB_WEB_FIELD_AJAX: str = "__a"
FB_WEB_FIELD_HASTE: str = "__hs"
FB_WEB_FIELD_DPR: str = "dpr"
FB_WEB_FIELD_CONNECTION: str = "__ccg"
FB_WEB_FIELD_REV: str = "__rev"
FB_WEB_FIELD_SPIN_R: str = "__spin_r"
FB_WEB_FIELD_SPIN_B: str = "__spin_b"
FB_WEB_FIELD_SPIN_T: str = "__spin_t"
FB_WEB_FIELD_HSI: str = "__hsi"
FB_WEB_FIELD_COMET_REQ: str = "__comet_req"
FB_WEB_FIELD_DTSG: str = "fb_dtsg"
FB_WEB_FIELD_JAZOEST: str = "jazoest"
FB_WEB_FIELD_LSD: str = "lsd"
FB_WEB_FIELD_CALLER_CLASS: str = "fb_api_caller_class"
FB_WEB_FIELD_FRIENDLY_NAME: str = "fb_api_req_friendly_name"
FB_WEB_FIELD_VARIABLES: str = "variables"
FB_WEB_FIELD_SERVER_TIMESTAMPS: str = "server_timestamps"
FB_WEB_FIELD_DOC_ID: str = "doc_id"

# Photo upload: extra form fields beside the session bundle, and the multipart
# file part. Facebook returns the uploaded photo's id as ``photoID``.
FB_WEB_FIELD_UPLOAD_SOURCE: str = "source"
FB_WEB_FIELD_UPLOAD_PROFILE_ID: str = "profile_id"
FB_WEB_FIELD_UPLOAD_WATERFALL: str = "waterfallxapp"
FB_WEB_FIELD_UPLOAD_ID: str = "upload_id"
FB_WEB_UPLOAD_SOURCE: str = "8"
FB_WEB_UPLOAD_WATERFALL_APP: str = "comet"
FB_WEB_UPLOAD_ID: str = "jsc_c_1g"
FB_WEB_UPLOAD_FILE_FIELD: str = "file"
FB_WEB_UPLOAD_FILE_NAME: str = "image.jpg"
FB_WEB_UPLOAD_FILE_MIME: str = "image/jpeg"

# ComposerStoryCreateMutation ``variables`` — the meaningful, tunable scalars of
# the group-post input (the rest is the fixed Comet payload skeleton built in
# ``bot.facebook_web.variables``).
FB_WEB_COMPOSER_ENTRY_POINT: str = "publisher_bar_media"
FB_WEB_COMPOSER_SOURCE_SURFACE_GROUP: str = "group"
FB_WEB_COMPOSER_TYPE_GROUP: str = "group"
FB_WEB_COMPOSER_SOURCE: str = "WWW"
FB_WEB_FEED_LOCATION_GROUP: str = "GROUP"
FB_WEB_RENDER_LOCATION_GROUP: str = "group"
FB_WEB_PRIVACY_SELECTOR_RENDER_LOCATION: str = "COMET_STREAM"
FB_WEB_EVENT_SHARE_SURFACE: str = "newsfeed"
FB_WEB_GROUP_COMMENTS_KEY: str = "CometGroupDiscussionRootSuccessQuery"
FB_WEB_CLIENT_MUTATION_ID: str = "1"
FB_WEB_SCALE: float = 1.5
FB_WEB_GROUP_ATTRIBUTION_ID: str = (
    "CometGroupDiscussionRoot.react,comet.group,via_cold_start,0,0,0,,"
)

# Response classification. Facebook answers HTTP 200 even on failure, may prefix
# the body with an anti-JSON-hijack token, and streams benign ``errors`` in
# deferred fragments — so success is confirmed *only* by a real post id. These
# needles are localized by the account and thus best-effort.
FB_WEB_JSON_HIJACK_PREFIXES: tuple[str, ...] = ("for (;;);", "for(;;);")
FB_WEB_POST_ID_MIN_DIGITS: int = 8
FB_WEB_PENDING_POSTS_MARKER: str = "pending_posts"
FB_WEB_PHOTO_ID_KEYS: tuple[str, ...] = ("photoID", "photo_id")
FB_WEB_RATE_LIMIT_NEEDLES: tuple[str, ...] = (
    "We limit how often",
    "temporarily blocked",
    "temporarily restricted",
    "try again later",
)
FB_WEB_CHECKPOINT_NEEDLES: tuple[str, ...] = (
    "/checkpoint/",
    "checkpoint_required",
    "Please Confirm Your Identity",
    "We need to confirm",
)
FB_WEB_RESTRICTED_NEEDLES: tuple[str, ...] = (
    "Your account is restricted",
    "Akun Anda dibatasi",
    "You're Temporarily Restricted",
)
FB_WEB_DUPLICATE_NEEDLES: tuple[str, ...] = (
    "Status Baru Duplikat",
    "already shared this",
    "already posted",
)

# An unclassifiable upload failure quotes the response body (whitespace-collapsed)
# up to this many characters, so the admin report shows *what* Facebook answered.
FB_WEB_UPLOAD_ERROR_SNIPPET_MAX_LENGTH: int = 160

# Desktop browser User-Agent for the web engine. Comet serves the modern markup
# (and the session tokens we scrape) to a desktop Chrome string.
FB_WEB_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

# Browser request headers. Facebook now answers a bare-User-Agent GET with a 400
# error page that carries *no* session tokens (which then misreads as "logged
# out"), so every web request must present a full desktop-Chrome fingerprint. The
# Client-Hints version mirrors the Chrome major in the UA above. Accept-Encoding
# is deliberately omitted so httpx negotiates only codecs it can decompress —
# advertising a brotli we can't decode yields an unreadable body.
FB_WEB_CLIENT_HINTS_UA: str = '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"'
FB_WEB_ACCEPT_LANGUAGE: str = "en-US,en;q=0.9"
FB_WEB_PLATFORM: str = '"Windows"'
FB_WEB_ORIGIN: str = "https://web.facebook.com"
# The CSRF ``lsd`` token, echoed as a request header on Comet writes (in addition
# to the form field); set per-request from the scraped session params.
FB_WEB_HEADER_FB_LSD: str = "X-FB-LSD"

# The UA + Client-Hints fingerprint shared by every web request (set as the
# httpx client's default headers).
FB_WEB_BASE_HEADERS: dict[str, str] = {
    "User-Agent": FB_WEB_USER_AGENT,
    "Accept-Language": FB_WEB_ACCEPT_LANGUAGE,
    "Sec-Ch-Ua": FB_WEB_CLIENT_HINTS_UA,
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": FB_WEB_PLATFORM,
}
# Extra headers for the top-level navigation (the home GET that mints the session
# tokens) — what FB expects from a real document request.
FB_WEB_NAVIGATION_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
# Extra headers for the same-origin fetch/XHR writes (GraphQL post + photo
# upload). Pinned to the GraphQL host, which does not cross-redirect.
FB_WEB_FETCH_HEADERS: dict[str, str] = {
    "Accept": "*/*",
    "Origin": FB_WEB_ORIGIN,
    "Referer": FB_WEB_HOME_URL,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Pacing: seconds to wait between consecutive group posts on the web engine, to
# stay under Facebook's write rate limits (one account, sequential). A detected
# rate-limit short-circuits the rest of the run.
FB_WEB_PACE_SECONDS: float = 22.0
FB_WEB_TIMEOUT_SEC: float = 30.0

# Anti-detection pacing layered on top of the engine's base ``pace_seconds`` (the
# post service applies both). A random margin of up to POST_PACE_JITTER_SEC is
# added to every inter-post wait so the cadence is not a fixed, fingerprintable
# metronome; and after every POST_BATCH_SIZE posts an extra POST_BATCH_COOLDOWN_SEC
# rest mimics a human pausing between bursts. Engines that do not pace (base pace
# of 0 — the Graph adapter and the test fakes) skip all of this and run immediately.
# Tuned for ~38s/group average (≈1h for 100 groups), trading some margin for speed.
POST_PACE_JITTER_SEC: float = 15.0
POST_BATCH_SIZE: int = 10
POST_BATCH_COOLDOWN_SEC: float = 90.0

# --------------------------------------------------------------------------- #
# Per-account publish guards (behaviour-only anti-automation hardening).        #
#                                                                               #
# Three account-level gates that change only WHEN and HOW MANY posts go out —    #
# never the content. State persists per account in the ``account_post_limits``  #
# table (so a cooldown and the daily count survive a restart). Defaults are      #
# production-sane; override via the ``POST_LIMITS__*`` env prefix. The service    #
# implementing these is ``bot.services.account_post_limit_service``.            #
# --------------------------------------------------------------------------- #

# Circadian gating: a run is refused outside this local active-hours window, so
# the account never posts overnight (a human-implausible signal). The window is a
# time-of-day range ``[start, end)`` evaluated in POST_CIRCADIAN_TIMEZONE; the
# default keeps posting to Cuba waking hours (07:00 through 23:59 local). An end
# hour of 0 means midnight (24:00) — the exclusive upper bound — since Python's
# ``time`` rejects hour 24; the service's midnight-straddle branch handles it.
POST_CIRCADIAN_ACTIVE_START_HOUR: int = 7
POST_CIRCADIAN_ACTIVE_START_MINUTE: int = 0
POST_CIRCADIAN_ACTIVE_END_HOUR: int = 0
POST_CIRCADIAN_ACTIVE_END_MINUTE: int = 0
POST_CIRCADIAN_TIMEZONE: str = "America/Havana"
# Display only: a window ending at midnight is stored as hour 0 but shown to the
# user as 24:00 (reads as "until midnight", not "closes at the day's start").
POST_CIRCADIAN_MIDNIGHT_DISPLAY_HOUR: int = 24

# Daily cap: at most this many *attempted* posts per Facebook account per rolling
# window. A run already at the cap is refused outright; a run that would cross it
# posts up to the remaining budget and skips the rest. POST_WINDOW_SECONDS is the
# window length, used by the elapsed-since-window-start rollover test (24h).
POST_DAILY_CAP_ATTEMPTS: int = 200
POST_WINDOW_SECONDS: int = 86400

# Cross-run back-off: after any run that hits a soft-block (a Facebook rate-limit
# or an expired session), the account is put on a cooldown before it may start
# again. The cooldown escalates per consecutive soft-blocked run —
# ``base * multiplier ** (blocks - 1)``, ceilinged at the cap — and fully resets
# after one clean run. Stored as an absolute instant, so it survives a restart.
POST_BACKOFF_BASE_SEC: float = 900.0
POST_BACKOFF_MULTIPLIER: float = 2.0
POST_BACKOFF_CAP_SEC: float = 7200.0

# Shared navigation label: return to the main menu from any submenu (its
# callback_data is ``MenuAction.MAIN``).
MENU_BUTTON_BACK: str = "⬅️ Volver"

# Inline main-menu button labels (paired with the MenuAction callback data).
MENU_BUTTON_START_POST: str = "📝 Crear publicación"
MENU_BUTTON_BLUEPRINTS: str = "📋 Plantillas"
MENU_BUTTON_GROUPS: str = "👥 Mis grupos"
MENU_BUTTON_MANAGEMENT: str = "⚙️ Administración"
MENU_BUTTON_ACCOUNTS: str = "🔗 Facebook"
MENU_BUTTON_REQUEST_ACCESS: str = "📨 Solicitar acceso"

# Facebook-accounts screen button labels. Each row names a user (display name)
# joined with a status emoji prefix; Unlink/Cancel are fixed.
ACCOUNT_LINK_PREFIX: str = "🔗 "
ACCOUNT_RELINK_PREFIX: str = "✅ "
ACCOUNT_UNLINK_LABEL: str = "🔓 Desvincular"
ACCOUNT_CANCEL_LABEL: str = "✖️ Cancelar"

# Access-decision button labels. The alert (admin DM) names the user in its text,
# so its buttons are fixed; the Management list repeats the name, so those labels
# are an emoji prefix joined with the user's display name.
ACCESS_GRANT_LABEL: str = "✅ Aprobar"
ACCESS_DENY_LABEL: str = "🚫 Rechazar"
MANAGE_GRANT_PREFIX: str = "✅ "
MANAGE_DENY_PREFIX: str = "🚫 "
MANAGE_REVOKE_PREFIX: str = "♻️ "

# Groups submenu + delete-confirmation button labels.
GROUP_BUTTON_ADD: str = "📥 Añadir"
GROUP_BUTTON_LIST: str = "📋 Lista"
GROUP_BUTTON_SEARCH: str = "🔍 Buscar"
GROUP_CONFIRM_DELETE_LABEL: str = "✅ Sí, eliminar"
GROUP_CANCEL_DELETE_LABEL: str = "✖️ Cancelar"

# Search-result row labels: a link button (emoji prefix + truncated group name,
# opening the FB URL) paired with a quick-delete button, plus pagination arrows.
GROUP_RESULT_LINK_PREFIX: str = "🔗 "
GROUP_RESULT_DELETE_LABEL: str = "🗑"
GROUP_PAGE_PREV_LABEL: str = "◀️"
GROUP_PAGE_NEXT_LABEL: str = "▶️"
GROUP_BUTTON_NAME_MAX_LENGTH: int = 40

# Post-composition button labels.
POST_BUTTON_DONE: str = "✅ Listo"
POST_BUTTON_EDIT_TEXT: str = "✏️ Editar texto"
POST_BUTTON_CLEAR: str = "🧹 Vaciar"
POST_BUTTON_CONFIRM: str = "📤 Publicar ya"
POST_BUTTON_CANCEL: str = "✖️ Cancelar"
POST_BUTTON_CANCEL_PUBLISH: str = "🚫 Cancelar publicación"
POST_BUTTON_SAVE_BLUEPRINT: str = "💾 Guardar como plantilla"

# Pagination of the final post-result summary: ◀️/▶️ nav buttons (their page number
# rides PostAction.RESULT_PAGE) and a footer telling the user which page they're on.
POST_RESULT_PAGE_PREV_LABEL: str = "◀️"
POST_RESULT_PAGE_NEXT_LABEL: str = "▶️"
POST_RESULT_PAGE_INDICATOR: str = "Página {page}/{total}"

# Blueprints (Plantillas) screen button labels. Each list row is an emoji-prefixed
# blueprint name opening its detail screen; the detail/edit/confirm actions are fixed.
BLUEPRINT_ROW_PREFIX: str = "📋 "
BLUEPRINT_BUTTON_PUBLISH: str = "🚀 Publicar"
BLUEPRINT_BUTTON_EDIT: str = "✏️ Editar"
BLUEPRINT_BUTTON_DELETE: str = "🗑 Eliminar"
BLUEPRINT_BUTTON_SHOW_IMAGES: str = "📷 Ver imágenes"
BLUEPRINT_BUTTON_RENAME: str = "🏷 Renombrar"
BLUEPRINT_BUTTON_EDIT_TEXT: str = "✏️ Editar texto"
BLUEPRINT_CONFIRM_DELETE_LABEL: str = "✅ Sí, eliminar"
BLUEPRINT_CANCEL_LABEL: str = "✖️ Cancelar"
BLUEPRINT_BUTTON_NAME_MAX_LENGTH: int = 40

# Per-photo quick-remove buttons in the composer: the label is formatted with the
# 1-based photo number; rows wrap after this many buttons to stay tappable.
POST_PHOTO_REMOVE_LABEL: str = "🗑 {n}"
POST_PHOTO_REMOVE_PER_ROW: int = 5

# Telegram hard limit for a single text message.
TELEGRAM_MESSAGE_LIMIT: int = 4096

# Max traceback characters included in an admin error report (tail kept).
ERROR_REPORT_TRACEBACK_LIMIT: int = 3000
