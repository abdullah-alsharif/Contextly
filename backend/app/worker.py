"""DB-backed worker entrypoint (Phase 0 stub).

Phase 4 fills in the real loop: lease + retry, PDF parsing, chunking, persist.
"""
import logging
import time

from app.core.config import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


def run() -> None:
    settings = get_settings()
    logger.info(
        "worker starting (stub) | ai_provider=%s storage_provider=%s",
        settings.ai_provider,
        settings.storage_provider,
    )
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()