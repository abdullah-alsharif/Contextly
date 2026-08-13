"""Profile provisioning: bootstrap the profiles row on first sight.

docs/security.md §1 ("Profiles bootstrap: on first /auth/me, create profiles
row if missing (upsert)"). Idempotent and race-safe via PK ON CONFLICT.
Runs inside the request's RLS session (role + claim already set by
get_current_user), so the profiles_user_isolation policy passes
(docs/multi-tenancy.md §2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity import Identity

_AUTH_SHIM_INSERT = text(
    """
    insert into auth.users (id)
    values (:user_id)
    on conflict (id) do nothing
    """
)

_PROFILE_UPSERT = text(
    """
    insert into profiles (id, email, full_name)
    values (:user_id, :email, :full_name)
    on conflict (id) do update
        set email = excluded.email,
            full_name = profiles.full_name,
            updated_at = now()
    returning id, email, full_name, created_at, updated_at
    """
)


async def _has_auth_shim(db: AsyncSession) -> bool:
    """True when the local auth shim (single-column auth.users) is present.

    The dev shim is the only place auth.users has exactly one column; on
    Supabase-hosted the real table has many columns and provisioning must not
    touch it (research.md §5, data-model.md).
    """
    result = await db.execute(
        text(
            "select count(*) from information_schema.columns "
            "where table_schema = 'auth' and table_name = 'users'"
        )
    )
    return bool(result.scalar_one() == 1)


async def ensure_profile(db: AsyncSession, identity: Identity) -> None:
    """Upsert the user's profile row (idempotent; contract auth.md §5).

    Runs on every authenticated request. full_name seeds on first sight only —
    conflict updates keep the persisted name, so a stale register-time claim
    never reverts a name edited via PATCH /auth/me.
    """
    if await _has_auth_shim(db):
        # Satisfy the profiles.id -> auth.users(id) FK in dev.
        await db.execute(_AUTH_SHIM_INSERT, {"user_id": str(identity.user_id)})

    email = identity.email or f"{identity.user_id}@dev.contextly.local"
    await db.execute(
        _PROFILE_UPSERT,
        {
            "user_id": str(identity.user_id),
            "email": email,
            "full_name": identity.full_name,
        },
    )


def _profile_row(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "email": row.email,
        "full_name": row.full_name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def update_full_name(
    db: AsyncSession, identity: Identity, full_name: str | None
) -> dict[str, Any]:
    """Set the caller's display name on their profile row (null clears it)."""
    result = await db.execute(
        text(
            "update profiles set full_name = :full_name, updated_at = now() "
            "where id = :user_id "
            "returning id, email, full_name, created_at, updated_at"
        ),
        {"full_name": full_name, "user_id": str(identity.user_id)},
    )
    return _profile_row(result.one())


async def get_profile(db: AsyncSession, identity: Identity) -> dict[str, Any]:
    """Fetch the caller's profile row (must exist after ensure_profile)."""
    result = await db.execute(
        text(
            "select id, email, full_name, created_at, updated_at "
            "from profiles where id = :user_id"
        ),
        {"user_id": str(identity.user_id)},
    )
    return _profile_row(result.one())
