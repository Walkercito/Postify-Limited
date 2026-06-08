# Postify-Limited

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/managed%20by-uv-de5fe9.svg)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/lint-ruff-d7ff64.svg)](https://docs.astral.sh/ruff/)
[![ty](https://img.shields.io/badge/types-ty-261230.svg)](https://github.com/astral-sh/ty)
[![Telegram](https://img.shields.io/badge/Telegram-Pyrogram-26A5E4.svg)](https://docs.pyrogram.org/)

A **private** Telegram bot that publishes a post to many Facebook groups in one
run. A single admin keeps a whitelist of users, links each one to a captured
Facebook session, and the bot fans the post out — paced and jittered — reporting
a paginated, per-group result when it finishes.

> ⚠️ The Facebook engine drives the unofficial web/Graph surface and violates
> Facebook's ToS. Use throwaway accounts only.

## Stack

**Pyrogram** (`kurigram` fork, MTProto) · **SQLAlchemy 2.0** async + SQLite ·
**Pydantic v2** / pydantic-settings · **structlog** wide-event logging ·
**uv** · **ruff** · **ty**.

## Features

- 🔐 One admin, a whitelist of users (request → grant / deny / revoke).
- 📎 Per-user Facebook session linking (stores only `uid` + token, never the password).
- 📤 Multi-group publishing with pacing, jitter, batch cool-downs, and self-healing photo reuse.
- 📄 Paginated, no-truncation result summary across every target group.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
git clone git@github.com:Walkercito/Postify-Limited.git
cd Postify-Limited

uv sync                      # create the venv + install everything
cp .env.example .env         # then fill in your Telegram credentials
uv run pre-commit install    # one-time: install the commit gate
```

Get `api_id` / `api_hash` from <https://my.telegram.org> and a bot token from
[@BotFather](https://t.me/BotFather); set your numeric `TELEGRAM__ADMIN_ID`.

## Run

```bash
uv run bot                   # or: uv run python -m bot
```

## Linking a Facebook account

Capture a session on a device Facebook already trusts (sidesteps checkpoints),
then hand the file to the admin:

```bash
uv run python scripts/fb_capture_session.py            # email + password → ./session.json
uv run python scripts/fb_capture_session.py --access-token   # bring your own EAAB… token
```

If the login is challenged, the script pauses so you can clear it in a browser,
then retries (the device id is reused via `.fb_machine_id` so the trust sticks).
In the bot's **Facebook** screen the admin taps *Link* for a user and uploads
`session.json` as a document. **`session.json` holds a live token — delete it
after uploading** (it's gitignored).

## Development

```bash
uv run ruff format src tests scripts    # format
uv run ruff check --fix src tests scripts   # lint (autofix)
uv run ty check                         # type-check
uv run pytest                           # tests
```

See [`CLAUDE.md`](CLAUDE.md) for the full architecture and conventions.
