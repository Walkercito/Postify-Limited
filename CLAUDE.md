# CLAUDE.md

Guidance for AI agents (and humans) working in this repository. Read this
before making changes.

## What this is

A private Telegram bot built with **Pyrogram** (MTProto), persisting to
**SQLite** through **SQLAlchemy 2.0 (async)** with **Pydantic v2** schemas.
Managed with **uv**. Linted/formatted by **ruff**, type-checked by **ty**
(Astral), structured logging via **structlog**.

The bot is private: a single `admin` controls a **whitelist** of `user`s
(grant / deny / revoke access). See "Access control" below.

## Non-negotiable conventions

These are hard rules. Follow them in every change.

### Architecture principles

- **OOP** — model behaviour as cohesive classes with clear responsibilities
  (clients, repositories, services, routers). The composition root is
  `BotApplication` in `src/bot/app.py`; wire dependencies there, not via globals.
- **DRY** — no copy-paste. Shared behaviour lives in one place: generic CRUD in
  `repositories/base.py`, the Bot→Client handler bridge in `handlers/base.py`,
  cross-cutting concerns in `handlers/middleware.py`.
- **No magic values** — every meaningful literal (string, number, default,
  enum value, log event name, SQL pragma, column length) lives in
  `src/bot/constants.py`. Do **not** inline literals in logic; add a named
  constant or enum member and reference it.

### Commits

- **Never reference AI systems or assistants** anywhere in commit messages —
  not in the title, not in the body, not as a trailer/footer. Do **not** add a
  `Co-Authored-By` line for any AI tool.
- Keep commit **titles and descriptions short**.

## Layout

```
src/bot/
  __init__.py          # __version__
  __main__.py          # `python -m bot` -> app.main()
  app.py               # BotApplication: composition root + lifecycle (start/stop/run), admin seeding
  constants.py         # ALL magic values: enums (Command, Role, AccessStatus, MenuAction, CallbackScope, Outcome, LogEvent, ...) + constants
  callbacks.py         # callback-data codec: access_decision()/parse_access_decision() + regex pattern
  keyboards.py         # inline-keyboard builders (main_menu, request_access_menu, access_alert_menu, management_menu)
  facebook_session.py  # parse uploaded session.json -> CapturedSession (uid + access_token)
  fb_link_requests.py  # FacebookLinkStore: in-memory per-admin in-flight link target
  core/
    config.py          # pydantic-settings; nested via `__` delimiter; get_settings() (lru_cache)
    logging.py         # structlog config (console/JSON), get_logger()
    client.py          # Bot(Client): Pyrogram client + settings/database/error_reporter
    errors.py          # ErrorReporter: sends formatted error+traceback to the admin
    exceptions.py      # BotError hierarchy (base domain error)
  db/
    base.py            # Base (DeclarativeBase + AsyncAttrs), TimestampMixin, utcnow(), naming convention
    database.py        # Database: engine/session factory, SQLite pragmas (WAL + FK), create_all/dispose/session()
    models/
      user.py          # User ORM model
      facebook_account.py  # FacebookAccount ORM model (one linked FB session per user)
  schemas/
    base.py            # BaseSchema (from_attributes=True)
    user.py            # UserCreate / UserUpdate / UserRead
  repositories/
    base.py            # BaseRepository[ModelT]: generic async CRUD
    user.py            # UserRepository: get_by_telegram_id, list_by_access_status, set_access_status, touch_last_seen
    facebook_account.py  # FacebookAccountRepository: get_for_user, get_by_fb_uid
  services/
    user_service.py    # UserService: register (create-only), set_access, list_by_access
    facebook_account_service.py  # FacebookAccountService: link (upsert + uid-conflict guard), unlink
  handlers/
    base.py            # Router (ABC) + _add_message_handler()/_add_callback_query_handler() bridge
    middleware.py      # observed (wide-event logging + admin error report), tracks_activity (last_seen)
    commands.py        # CommandRouter: /start (access gate), /help
    menu.py            # MenuRouter: inline main-menu feature buttons (stubs)
    access.py          # AccessRouter: request access, admin alert, grant/deny/revoke
    accounts.py        # AccountsRouter: admin links/unlinks a user's FB session (upload session.json)
    __init__.py        # ROUTERS tuple + register_routers()
scripts/               # standalone CLIs run outside the bot
  fb_capture_session.py  # emit session.json for upload: log in, or --access-token (BYO token)
tests/                 # pytest (async), in-memory SQLite fixture
data/                  # runtime SQLite file lives here (gitignored)
.pre-commit-config.yaml  # git pre-commit gate (ruff, ty, pylint DRY)
.claude/
  settings.json        # Claude Code: hooks + LSP feature flag + local plugin
  hooks/               # python_quality.sh (PostToolUse), dry_check.sh (Stop)
  marketplace/         # in-repo plugin catalog providing the ty LSP server
```

## Commands

```bash
uv sync                      # install deps + create venv/lockfile
cp .env.example .env         # then fill in credentials
uv run pre-commit install    # one-time: install the git pre-commit hook
uv run bot                   # run the bot (also: uv run python -m bot)

uv run ruff format .         # format
uv run ruff check --fix .    # lint (+autofix)
uv run ty check              # type-check
uv run pytest                # tests
uv run pre-commit run --all-files   # run the full commit gate manually
```

Run all four checks before considering a change done; they are expected to pass
with zero diagnostics. See "Quality automation" below for how these run
automatically.

## Quality automation

Three layers enforce the conventions above so violations are caught early.

### 1. Linters (the rules)

- **ruff** (`[tool.ruff.lint]`): beyond the usual `E/F/I/UP/B/SIM/ASYNC/RUF`,
  we enable `N` (naming), `C90` (mccabe complexity), and `PL` (pylint). Notably
  **`PLR2004`** flags magic values used in comparisons — the mechanical half of
  the *no-magic-values* rule — and the `PLR09xx`/`C901` rules flag oversized
  functions/classes (OOP/DRY smells). `max-complexity = 10`, `max-args = 6`.
- **ty**: full-project static type checking.
- **pylint (DRY only)**: pylint is installed *solely* as a copy/paste detector;
  everything but `duplicate-code` (`R0801`) is disabled. Tuned in
  `[tool.pylint.similarities]` (`min-similarity-lines = 8`).

### 2. Git pre-commit (`.pre-commit-config.yaml`)

Runs on `git commit` (install once with `uv run pre-commit install`). Every hook
is a `local` hook invoked through `uv run`, so the tool versions come only from
the dev dependency group — there is no second place to bump them. Hooks: ruff
format, ruff check (`--fix`), ty check, pylint duplicate-code. Run them all
manually with `uv run pre-commit run --all-files`.

### 3. Claude Code hooks (`.claude/settings.json` + `.claude/hooks/`)

These give agents immediate, automated feedback while editing:

- **`PostToolUse`** (on `Edit`/`Write`/`MultiEdit`) → `python_quality.sh`:
  formats the edited Python file, then runs ruff check + ty on it. On any
  violation it exits 2 so the failure is fed straight back to the agent to fix
  before continuing. Non-Python edits are ignored.
- **`Stop`** → `dry_check.sh`: runs the pylint duplicate-code (DRY) detector
  over `src/bot` when a turn ends and surfaces duplication as a non-blocking
  warning (it never blocks, to avoid stop-hook loops).

Both scripts are plain bash + `jq`; they read the project root from
`$CLAUDE_PROJECT_DIR` and degrade gracefully if a tool is missing.

### 4. LSP — `ty` language server (`.claude/marketplace/`)

For real-time code intelligence (diagnostics, go-to-definition, hover, find
references) we ship a tiny in-repo plugin (`python-lsp`) that runs
`ty server` against the project venv. It's wired declaratively in
`.claude/settings.json` via `env.ENABLE_LSP_TOOL=1` (gates the feature),
`extraKnownMarketplaces` (registers the local `.claude/marketplace` catalog),
and `enabledPlugins` (`python-lsp@local-tooling`). The LSP binary is the
project's own `.venv/bin/ty`, so it must exist (`uv sync`).

If the plugin is not picked up automatically on session start, enable it once
interactively:

```text
/plugin marketplace add .claude/marketplace
/plugin install python-lsp@local-tooling
```

## Key design decisions

### Pyrogram via kurigram

The dependency is **`kurigram`** (a maintained fork), but the import name is
still `pyrogram`. Import from `pyrogram` as normal. `tgcrypto2` is installed as
an optional C speedup for MTProto crypto.

### Configuration

`core/config.py` uses pydantic-settings. Nested sections use the `__`
delimiter, e.g. `TELEGRAM__API_ID` → `settings.telegram.api_id`. Required
credentials live under `TELEGRAM__*`; missing them raises a validation error at
startup. All nested settings use `Field(default_factory=...)` — this keeps env
population working *and* keeps the type checker happy (it does not model
pydantic-settings env loading). `get_settings()` is `lru_cache`d.

### Access control — one admin, a whitelist of users

`Role` (in `constants.py`) has two members: `ADMIN` and `USER`. There is
exactly **one** admin (the seeded `TELEGRAM__ADMIN_ID`); everyone else is a
`USER`. Single-admin is preserved **by construction** — only `admin_id` is ever
assigned `ADMIN` (in `_seed_admin()` and `/start`), so no DB uniqueness
constraint is needed.

Whether a `USER` may actually use the bot is a separate axis: `AccessStatus`
(`PENDING` / `ALLOWED` / `DENIED`) on `User.access_status`. The admin owns this
whitelist:

- **`User.is_allowed`** is `True` for the admin (implicitly) or any user whose
  `access_status` is `ALLOWED`.
- **`/start`** registers the caller (`PENDING` by default, `ALLOWED` for the
  admin) and, if not allowed, shows a *"no access"* message plus a *Request
  access* button instead of the menu.
- **Request flow** (`AccessRouter`, `handlers/access.py`): tapping *Request
  access* DMs the admin an instant alert with Grant/Deny buttons and logs
  `ACCESS_REQUESTED`. The admin can also open *Management* (admin-only menu
  button) to Grant/Deny pending users and Revoke allowed ones.
- **Decisions** flow through one parameterized callback (`access.py`):
  `CallbackScope` (`ALERT` vs `MANAGE`) + target `AccessStatus` + the target's
  Telegram id, encoded/decoded by `bot/callbacks.py`. `UserService.set_access()`
  applies the change; the target is best-effort notified.

`register()` is **create-only / idempotent**: if the Telegram id already exists
it returns `(existing_user, False)` without overwriting the stored profile or
its `access_status`. The admin is seeded on startup in
`BotApplication._seed_admin()` from `TELEGRAM__ADMIN_ID` as `ADMIN` / `ALLOWED`.

### Facebook account provisioning

The bot posts on a user's behalf with a captured Facebook **session**. The admin
captures it out-of-band on a trusted device with `scripts/fb_capture_session.py`
(prompts for email/password, logs in via `fb_unofficial`, writes `session.json`)
— doing this on a trusted device sidesteps Facebook's checkpoint challenges. The
script emits the *full* blob (session + credentials, for portability), but the
bot stores **only the `uid` + `access_token`**; the password is never persisted.

If Facebook still challenges the login, the script pauses and waits: a 405
account-verification checkpoint (`FacebookCheckpointRequired`) or a "Was this
you?" approval (`FacebookApprovalRequired`) prints instructions, blocks on Enter
while the admin clears it in a browser, then retries. Crucially it reuses one
`machine_id` persisted in `.fb_machine_id` (gitignored) across runs — a fresh
device id each run would re-trigger the checkpoint, so verification never stuck.
`auth._do_login` also coerces FB's occasional non-JSON error body back to a dict
so the 405 is recognized instead of surfacing as "unexpected login response".

The script has **two modes**, dispatched in `main()` on `--access-token`:
the default *login* path above (`_run_password_mode`), and a *bring-your-own-token*
path (`_run_token_mode`) for when `auth.login` is permanently checkpoint-blocked.
`--access-token` takes an optional value (`nargs="?"`); the flag alone prompts via
`getpass` (not echoed), or you pass the `EAAB…` token directly. `_capture_from_token`
verifies it with `Facebook(token).get_profile()` (the fetch *is* the validation —
a dead token aborts before writing), derives the `uid` (override with `--uid`), and
builds the same `session_blob.session` (`access_token`/`uid`/`created_at`) — no
credentials, since none were used. Both modes funnel through `_build_upload()` (the
shared payload shape) and `_write_payload()`.

Linking spans two updates and is **admin-only**: in the *Facebook* screen
(`AccountsRouter`, `handlers/accounts.py`) the admin taps *Link* for an allowed
user — which arms an in-memory request in `FacebookLinkStore` (keyed by admin
id) — then uploads `session.json` as a document. A custom filter
(`_AWAITING_SESSION_FILTER`) lets the router claim that document only while a
link is armed. `facebook_session.parse_session_payload()` extracts the
`CapturedSession`; `FacebookAccountService.link()` upserts it (one account per
user) and rejects a `uid` already linked to another user
(`FacebookAccountTakenError`). *Unlink* removes the stored account. Confirmations
echo only the `fb_uid` + display name — never the token.

`session.json` holds a live token and is gitignored; the capture script tells
the admin to delete it after upload. The `fb_unofficial` engine violates
Facebook's ToS — use throwaway accounts only.

### Error reporting to the admin

Any unexpected exception raised inside a handler is reported to the admin via
`ErrorReporter` (`core/errors.py`): an HTML-escaped message with the timestamp,
exception type/message, bound context, and a (truncated) traceback, sent to
`TELEGRAM__ADMIN_ID`. This is wired through the `observed` middleware — handlers
do not need to call it directly. Failures to deliver the report are logged, not
raised.

### Logging — wide events

We follow the **wide-event** pattern: exactly **one** rich, structured log
event per update. The `observed` decorator (`handlers/middleware.py`) binds
per-update context via `contextvars`, times the handler, and emits a single
`UPDATE_HANDLED` event with `outcome` (success/error) and `duration_ms`. Do not
scatter `log.info` calls through handler bodies; add context to the wide event
instead. Use `get_logger(__name__)` (structlog) everywhere — one logger,
consistent schema. Output is console-rendered by default, JSON when
`LOGGING__FORMAT=json`.

### Handler typing bridge

Pyrogram types its callback against the base `Client`; our handlers are typed
against the `Bot` subclass for ergonomic access to `settings`, `database`, and
`error_reporter`. The single safe cast bridging the two lives in
`Router._add_message_handler()` — register handlers through it, never call
`bot.add_handler(...)` directly from a router.

### Database

`Database` (`db/database.py`) owns the async engine and a session factory
(`expire_on_commit=False`). SQLite is configured with WAL journal mode and
foreign-key enforcement via connect-time pragmas. Use the `Database.session()`
async context manager — it opens a transaction and commits on success. Models
inherit timestamps from `TimestampMixin` (client-side `utcnow` defaults).

## Adding things

- **New command/handler**: add the message to the relevant constant, implement
  the handler (decorate with `@observed` outermost, then `@tracks_activity`),
  register it via `self._add_message_handler(...)` in a `Router`, and ensure the
  router is in `ROUTERS` (`handlers/__init__.py`).
- **New model**: subclass `Base` (+ `TimestampMixin`), export it from
  `db/models/__init__.py`, add a schema in `schemas/`, and a repository in
  `repositories/` (subclass `BaseRepository`).
- **New literal**: it goes in `constants.py`. Always.
