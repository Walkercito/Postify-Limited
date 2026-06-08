# automatizacion-facebook

A Telegram bot built with **Pyrogram** (`kurigram` fork), **SQLAlchemy 2.0**
(async + SQLite), **Pydantic** / **pydantic-settings**, and **structlog**.
Managed with **uv**; linted/formatted with **ruff**; type-checked with **ty**.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync                 # create the venv and install everything
cp .env.example .env    # then fill in your Telegram credentials
```

Get `api_id` / `api_hash` from <https://my.telegram.org> and a bot token from
[@BotFather](https://t.me/BotFather).

## Run

```bash
uv run bot              # or: uv run python -m bot
```

## Facebook account provisioning

The bot posts on a user's behalf with a captured Facebook **session**. Capture
it on a device Facebook already trusts (sidesteps checkpoint challenges), then
hand the file to the admin:

```bash
uv run python scripts/fb_capture_session.py   # prompts for email + password
# writes ./session.json
```

If Facebook challenges the login (an account-verification checkpoint or a "Was
this you?" approval), the script **pauses**: clear it at
<https://www.facebook.com>, then press Enter to retry. The device id is saved to
`.fb_machine_id` and reused every run, so once a checkpoint is cleared the trust
sticks (a fresh id each run would just re-trigger it). A 2FA code, if required,
is prompted inline.

If the login is permanently checkpoint-blocked, **bring your own token** instead
— supply an `EAAB…` access token captured from an already-authenticated session
(e.g. by intercepting the Facebook app's Graph traffic):

```bash
uv run python scripts/fb_capture_session.py --access-token   # prompts (not echoed)
# or pass it directly: --access-token EAAB...  (lands in shell history)
```

The script verifies the token against the Graph API, derives the `uid` (override
with `--uid`), and writes the same `session.json` — no email/password or login.

The admin opens the bot's **Facebook** screen, taps *Link* for a user, and
sends `session.json` as a document. Only the account uid and access token are
stored — never the password. **`session.json` holds a live token: delete it
once uploaded** (it's gitignored). The Facebook engine violates Facebook's ToS,
so use throwaway accounts only.

## Development

```bash
uv run ruff format .            # format
uv run ruff check --fix .       # lint (autofix)
uv run ty check                 # type-check
uv run pytest                   # tests
```

## Layout

```
src/bot/
├── app.py            # BotApplication + entry point
├── constants.py      # enums & constants (no magic values)
├── core/             # config, logging, Pyrogram client
├── db/               # engine/session, declarative base, models
├── schemas/          # Pydantic DTOs
├── repositories/     # data-access layer
├── services/         # business logic
└── handlers/         # Pyrogram routers + per-update logging
scripts/              # standalone CLIs (e.g. fb_capture_session.py)
```

See `CLAUDE.md` for architecture and conventions.
