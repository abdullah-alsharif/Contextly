"""StorageProvider factory: env-switched provider selection (constitution IV).

STORAGE_PROVIDER=local → LocalStorageProvider (zero credentials, dev/tests);
STORAGE_PROVIDER=supabase → SupabaseStorageProvider (production). `local` is
dev-only (mirrors the AI_PROVIDER=fake guard); unknown values fail loudly at
startup (contracts/storage.md §4, mirrors auth mode).
"""

from __future__ import annotations

from app.core.config import Settings
from app.providers.storage.base import StorageProvider
from app.providers.storage.local import LocalStorageProvider
from app.providers.storage.supabase import SupabaseStorageProvider


def build_storage_provider(settings: Settings) -> StorageProvider:
    """Return the provider selected by settings.storage_provider."""
    if settings.storage_provider == "local":
        if settings.app_env != "dev":
            raise RuntimeError(
                "STORAGE_PROVIDER=local is only allowed when APP_ENV=dev "
                f"(got APP_ENV={settings.app_env!r})"
            )
        return LocalStorageProvider(root=settings.local_storage_dir)
    if settings.storage_provider == "supabase":
        return SupabaseStorageProvider(
            base_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            bucket=settings.storage_bucket,
        )
    raise ValueError(
        f"storage_provider must be 'local' or 'supabase', got {settings.storage_provider!r}"
    )
