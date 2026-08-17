"""Control-character cleaning for untrusted text.

Postgres cannot store NUL, and broken PDF/upload encodings smuggle C0 controls,
so untrusted text is cleaned at three boundaries. Filenames strip the controls
entirely (docs/security.md §3); page text and user questions replace them with
spaces while keeping tabs/newlines (docs/ingestion.md §2, docs/security.md §4).
"""

from __future__ import annotations

import re

_STRIP = re.compile(r"[\x00-\x1f\x7f]")
_REPLACE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control_chars(text: str) -> str:
    """Remove C0 controls + DEL entirely (filenames; docs/security.md §3)."""
    return _STRIP.sub("", text)


def replace_control_chars(text: str) -> str:
    """Replace C0 controls with spaces, keeping tabs/newlines (docs/ingestion.md §2)."""
    return _REPLACE.sub(" ", text)
