"""Contact normalization helpers shared by clean transforms."""

from __future__ import annotations

import re
from typing import Any

_PHONE_FORMATTING_RE = re.compile(r"[\s().-]+")
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_WWW_RE = re.compile(r"^www\.", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    if cleaned.lower() == "nan":
        return None
    return cleaned or None


def normalize_phone(value: Any) -> str | None:
    """Normalize an Italian phone candidate to compact E.164 when possible."""
    text = _clean_optional_text(value)
    if text is None:
        return None
    compact = _PHONE_FORMATTING_RE.sub("", text)
    if compact.startswith("+"):
        return compact
    if compact.startswith(("0", "3")):
        return f"+39{compact}"
    return compact or None


def normalize_website(value: Any) -> str | None:
    """Normalize a website string for direct equality comparison."""
    text = _clean_optional_text(value)
    if text is None:
        return None
    normalized = _SCHEME_RE.sub("", text)
    normalized = _WWW_RE.sub("", normalized)
    normalized = normalized.rstrip("/")
    return normalized or None
