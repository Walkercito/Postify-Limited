"""Structured logging setup (structlog).

Routes both structlog events and stdlib library logs (pyrogram, sqlalchemy)
through a single ``ProcessorFormatter`` so output is uniform. The renderer is a
human-friendly console renderer in development and JSON in production, selected
by :class:`~bot.constants.LogFormat`.

The bot follows the "wide event" pattern: per-update context (``user_id``,
``chat_id``, ...) is bound via ``contextvars`` and a single rich event is
emitted per update (see :mod:`bot.handlers.middleware`).
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.typing import Processor

from bot.constants import LogFormat
from bot.core.config import LoggingSettings

# Third-party loggers whose default verbosity is too high; values are levels.
NOISY_LOGGERS: dict[str, int] = {
    "pyrogram": logging.INFO,
    "sqlalchemy.engine": logging.WARNING,
    "aiosqlite": logging.WARNING,
}


def _resolve_level(level: str) -> int:
    return logging.getLevelNamesMapping().get(level.upper(), logging.INFO)


def _shared_processors(*, json_output: bool) -> list[Processor]:
    """Processors applied to every record (structlog and foreign alike)."""
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # MUST be first: wide-event ctx
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    # Structured tracebacks for aggregators in prod; readable strings in dev.
    processors.append(
        structlog.processors.dict_tracebacks
        if json_output
        else structlog.processors.format_exc_info
    )
    return processors


def configure_logging(settings: LoggingSettings) -> None:
    """Configure structlog + the stdlib root logger. Call once at startup."""
    level = _resolve_level(settings.level)
    json_output = settings.format is LogFormat.JSON
    shared = _shared_processors(json_output=json_output)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name, noisy_level in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(noisy_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
