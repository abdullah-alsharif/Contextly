"""Identity resolved from an authenticated request (contracts/auth.md)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Identity:
    """Who the caller is, derived from the verified JWT.

    `user_id` == JWT `sub` == `profiles.id` == `auth.uid()` in RLS
    (docs/security.md §1, docs/multi-tenancy.md §2).
    """

    user_id: uuid.UUID
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)
