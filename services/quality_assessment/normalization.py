from __future__ import annotations

import re
import unicodedata
from math import isnan
from typing import Any

MISSING_STRINGS = {"", "nan", "null", "none", "n/a", "na", "-"}
_NUMBER_RE = re.compile(r"[-+]?\d[\d.,]*")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_STRINGS
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def parse_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value).strip())
    if not match:
        return None
    return float(normalize_number_token(match.group(0)))


def parse_int(value: Any) -> int | None:
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    token = match.group(0)
    sign = -1 if token.startswith("-") else 1
    digits = re.sub(r"\D", "", token)
    return sign * int(digits) if digits else None


def normalize_number_token(token: str) -> str:
    """Convert locale-formatted numeric tokens to a Python decimal string."""
    token = token.strip()
    if "." in token and "," in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        return token.replace(thousands_sep, "").replace(decimal_sep, ".")
    if "," in token:
        parts = token.split(",")
        if _looks_like_thousands_groups(parts):
            return "".join(parts)
        return token.replace(",", ".")
    if "." in token:
        parts = token.split(".")
        if _looks_like_thousands_groups(parts):
            return "".join(parts)
    return token


def _looks_like_thousands_groups(parts: list[str]) -> bool:
    if len(parts) < 2:
        return False
    head = parts[0].lstrip("+-")
    return 1 <= len(head) <= 3 and all(part.isdigit() and len(part) == 3 for part in parts[1:])


def normalize_text(value: Any) -> str:
    if is_missing(value):
        return ""
    folded = (
        unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").lower()
    )
    return " ".join(_NON_ALNUM_RE.sub(" ", folded).split())


def in_milan_area(latitude: float | None, longitude: float | None) -> bool:
    """Broad bounding box covering Milan and nearby municipalities."""
    if latitude is None or longitude is None:
        return False
    return 45.35 <= latitude <= 45.58 and 9.00 <= longitude <= 9.35


def first_present(*values: Any) -> Any:
    for value in values:
        if not is_missing(value):
            return value
    return None
