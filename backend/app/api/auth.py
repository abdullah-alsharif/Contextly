"""Auth router: GET/PATCH /auth/me (docs/api.md §1, contracts/auth.md §6).

Only profile endpoints exist in FastAPI this phase — login/register/logout are
proxied by the frontend server to Supabase (docs/api.md §1 footnote, Phase 8).
"""

from __future__ import annotations


from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_general_rate_limit
from app.core.security.deps import get_current_user
from app.core.security.identity import Identity
from app.db.session import get_db
from app.schemas.profile import ProfileIn, ProfileOut
from app.services.profiles import get_profile, update_full_name

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=ProfileOut,
    dependencies=[Depends(get_current_user), Depends(enforce_general_rate_limit)],
)
async def get_me(
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return the current user's profile (provisioned on first sight)."""
    return await get_profile(db, identity)


@router.patch(
    "/me",
    response_model=ProfileOut,
    dependencies=[Depends(get_current_user), Depends(enforce_general_rate_limit)],
)
async def patch_me(
    body: ProfileIn,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Update the caller's display name (email stays immutable)."""
    return await update_full_name(db, identity, body.full_name)
