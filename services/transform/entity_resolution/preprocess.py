from __future__ import annotations

import re
import unicodedata
from typing import Any

_WS_RE = re.compile(r"\s+")
_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brist\.(?=\W|$)", re.IGNORECASE), "ristorante"),
    (re.compile(r"\btrat\.(?=\W|$)", re.IGNORECASE), "trattoria"),
    (re.compile(r"\bp\.?za\b", re.IGNORECASE), "piazza"),
)


def normalize_name(text: Any) -> str:
    """Normalize a restaurant/name-like string for in-memory comparison only."""
    if text is None:
        return ""
    normalized = str(text).lower()
    for pattern, replacement in _ABBREVIATIONS:
        normalized = pattern.sub(replacement, normalized)
    normalized = "".join(
        " " if unicodedata.category(char).startswith("P") else char for char in normalized
    )
    return _WS_RE.sub(" ", normalized).strip()


def name_tokens(text: Any, *, min_length: int = 4) -> set[str]:
    """Return normalized name tokens long enough to be useful for fallback blocking."""
    return {token for token in normalize_name(text).split() if len(token) >= min_length}
