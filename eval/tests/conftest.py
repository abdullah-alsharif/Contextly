"""Pin a hermetic provider so eval tests never hit a live AI API.

The eval tests exercise the committed fixtures and must run offline
(docs/testing.md §6) regardless of a local `.env` pointing at a real provider.
Force the same env the CI gate uses (APP_ENV=dev, AI_PROVIDER=fake).
"""

from __future__ import annotations

import os

os.environ["APP_ENV"] = "dev"
os.environ["AI_PROVIDER"] = "fake"
