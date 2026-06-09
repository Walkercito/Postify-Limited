"""Backfill missing or placeholder group display names for one user.

Groups saved before name resolution existed — or whose authenticated fetch
failed at save time — keep a ``NULL`` name or a raw ``… | Facebook`` title. This
re-resolves each through the *same* path the add-flow uses (the owner's
authenticated cookie session first, then the public scrape) and writes the
cleaned name back. A row that already has a name is only touched when its title
still carries a strippable ``| Facebook`` suffix or is a logged-out placeholder.

Every network round-trip happens *outside* the DB transactions (the same rule
the live add-flow follows), and the run is paced so it never bursts requests at a
sensitive account. ``--dry-run`` resolves and prints the plan without writing —
use it to confirm the cookie session still returns names before committing.

Usage::

    uv run python scripts/backfill_group_names.py <user_id> [--dry-run]
    uv run python scripts/backfill_group_names.py 3 --dry-run --limit 1
"""

from __future__ import annotations

import argparse
import asyncio
import random
from dataclasses import dataclass

from sqlalchemy import select

from bot.core.config import get_settings
from bot.db.database import Database
from bot.db.models.facebook_account import FacebookAccount
from bot.db.models.group import Group
from bot.facebook_web import decode_cookies, extract_group_name
from bot.handlers.groups import _resolve_group_name
from bot.services.group_service import GroupService

# Pacing between consecutive group fetches: a base delay plus a random margin, so
# a backfill of many rows never bursts a fixed-cadence stream at the account.
DEFAULT_DELAY_SEC = 5.0
DEFAULT_JITTER_SEC = 3.0
# Wrap a stored plain-text title back into <title> markup so the existing
# extractor's suffix-strip + placeholder check can clean it (no logic duplicated).
TITLE_WRAPPER = "<title>{name}</title>"
SUFFIX_STRIP_SOURCE = "suffix-strip"


@dataclass(frozen=True, slots=True)
class _Plan:
    """One resolved rename: which group, its old name, the new one, and the path."""

    group_id: int
    facebook_id: str
    old_name: str | None
    new_name: str
    source: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill group display names for a user.")
    parser.add_argument("user_id", type=int, help="the bot user id whose groups to backfill")
    parser.add_argument(
        "--dry-run", action="store_true", help="resolve and print the plan without writing"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="process at most this many groups (0 = no limit)"
    )
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC)
    parser.add_argument("--jitter", type=float, default=DEFAULT_JITTER_SEC)
    return parser.parse_args()


def _clean_existing(name: str) -> str | None:
    """Clean a stored plain-text title via the live extractor (suffix/placeholder)."""
    return extract_group_name(TITLE_WRAPPER.format(name=name))


def _needs_name(group: Group) -> bool:
    """Whether *group*'s stored name is missing, a placeholder, or suffix-dirty."""
    return group.name is None or _clean_existing(group.name) != group.name


async def _load_cookies(database: Database, user_id: int) -> dict[str, str] | None:
    """The user's decoded cookie jar, or ``None`` if unset (no secrets are logged)."""
    async with database.session() as session:
        account = await session.scalar(
            select(FacebookAccount).where(FacebookAccount.user_id == user_id)
        )
        if account is None:
            return None
        return decode_cookies(account.session_cookies)


async def _load_targets(database: Database, user_id: int, limit: int) -> list[Group]:
    """The user's groups whose name needs (re)resolving, capped by *limit*."""
    async with database.session() as session:
        groups = (
            await session.scalars(select(Group).where(Group.user_id == user_id).order_by(Group.id))
        ).all()
    targets = [group for group in groups if _needs_name(group)]
    return targets[:limit] if limit > 0 else targets


async def _resolve(group: Group, cookies: dict[str, str] | None) -> _Plan | None:
    """Resolve *group*'s name, falling back to a local suffix-strip; ``None`` if unresolved."""
    name, source = await _resolve_group_name(group.facebook_id, cookies)
    resolved_source = getattr(source, "value", str(source))
    if name is None and group.name is not None:
        cleaned = _clean_existing(group.name)
        if cleaned is not None and cleaned != group.name:
            name, resolved_source = cleaned, SUFFIX_STRIP_SOURCE
    if name is None or name == group.name:
        return None
    return _Plan(group.id, group.facebook_id, group.name, name, resolved_source)


async def _build_plans(
    targets: list[Group], cookies: dict[str, str] | None, delay: float, jitter: float
) -> list[_Plan]:
    """Resolve every target, pacing between fetches; collect the renames to apply."""
    plans: list[_Plan] = []
    for index, group in enumerate(targets):
        if index > 0:
            await asyncio.sleep(delay + random.uniform(0, jitter))
        plan = await _resolve(group, cookies)
        marker = "·" if plan is None else "→"
        resolved = "(unresolved)" if plan is None else f"{plan.new_name!r} [{plan.source}]"
        print(f"  {marker} group {group.id} ({group.facebook_id}): {group.name!r} {resolved}")
        if plan is not None:
            plans.append(plan)
    return plans


async def _apply(database: Database, user_id: int, plan: _Plan) -> None:
    """Write one rename in its own short transaction (network already done)."""
    async with database.session() as session:
        service = GroupService(session)
        group = await service.find_by_id(user_id, plan.group_id)
        if group is not None:
            await service.set_name(group, plan.new_name)


async def _run(args: argparse.Namespace) -> None:
    database = Database(get_settings().database)
    try:
        cookies = await _load_cookies(database, args.user_id)
        if cookies is None:
            print(
                f"user {args.user_id} has no stored cookie session — names resolve from the "
                "public scrape only (likely nameless)."
            )
        targets = await _load_targets(database, args.user_id, args.limit)
        print(f"{len(targets)} group(s) to resolve for user {args.user_id}:")
        plans = await _build_plans(targets, cookies, args.delay, args.jitter)
        if args.dry_run:
            print(f"dry-run: {len(plans)} rename(s) would be written, none applied.")
            return
        for plan in plans:
            await _apply(database, args.user_id, plan)
        print(f"applied {len(plans)} rename(s).")
    finally:
        await database.dispose()


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
