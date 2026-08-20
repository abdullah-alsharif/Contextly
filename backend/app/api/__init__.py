"""Router registration. Business routes (/api/v1) are auth-guarded.

Guard wiring (contracts/auth.md §1, spec US3): EVERY business router added in
later phases MUST apply `dependencies=[Depends(get_current_user)]` — either at
the APIRouter level or per endpoint — so unauthenticated requests get 401 by
construction. Auth's own `me` route is itself guarded. /healthz and / stay
outside /api/v1 and unauthenticated (infrastructure).
"""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.logs import router as logs_router
from app.api.messages import router as messages_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(conversations_router)
api_router.include_router(messages_router)
api_router.include_router(logs_router)
